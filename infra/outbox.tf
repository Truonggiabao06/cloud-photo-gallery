resource "google_pubsub_topic_iam_member" "outbox" {
  topic  = google_pubsub_topic.process.name
  role   = "roles/pubsub.publisher"
  member = google_service_account.identity["relay"].member
}

resource "google_cloud_run_v2_job" "outbox" {
  name                = "${var.prefix}-outbox"
  location            = var.region
  deletion_protection = false

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.identity["relay"].email
      timeout         = "110s"
      max_retries     = 0

      dynamic "vpc_access" {
        for_each = var.enable_postgres ? [1] : []
        content {
          egress = "PRIVATE_RANGES_ONLY"
          network_interfaces {
            network    = google_compute_network.app[0].name
            subnetwork = google_compute_subnetwork.run[0].name
          }
        }
      }

      containers {
        image   = var.bootstrap_image
        command = ["node"]
        args    = ["src/outbox-relay.js"]
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "PUBSUB_TOPIC"
          value = google_pubsub_topic.process.name
        }
        dynamic "env" {
          for_each = local.sql_env
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = var.enable_postgres && var.postgres_secret_ready ? [1] : []
          content {
            name = "DB_PASS"
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.app["DB_PASS"].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }
  depends_on = [google_secret_manager_secret_iam_member.app, google_pubsub_topic_iam_member.outbox, google_project_iam_member.sql_client]
}

resource "google_cloud_run_v2_job_iam_member" "deploy_outbox" {
  name     = google_cloud_run_v2_job.outbox.name
  location = var.region
  role     = "roles/run.developer"
  member   = google_service_account.identity["deploy"].member
}

resource "google_cloud_run_v2_job_iam_member" "schedule_outbox" {
  name     = google_cloud_run_v2_job.outbox.name
  location = var.region
  role     = "roles/run.invoker"
  member   = google_service_account.identity["scheduler"].member
}

resource "google_cloud_scheduler_job" "outbox" {
  count     = var.enable_push ? 1 : 0
  name      = "${var.prefix}-outbox"
  region    = var.region
  schedule  = "* * * * *"
  time_zone = "Etc/UTC"
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.outbox.name}:run"
    oauth_token {
      service_account_email = google_service_account.identity["scheduler"].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  depends_on = [
    google_cloud_run_v2_job_iam_member.schedule_outbox, google_pubsub_subscription.push,
    google_pubsub_subscription_iam_member.dead_forwarder
  ]
}
