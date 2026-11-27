locals {
  apis = toset([
    "artifactregistry.googleapis.com", "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com", "compute.googleapis.com", "iam.googleapis.com",
    "iamcredentials.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com",
    "pubsub.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com", "sqladmin.googleapis.com", "storage.googleapis.com",
    "sts.googleapis.com"
  ])
  runtime     = toset(["frontend", "backend", "worker"])
  use_network = var.enable_postgres || var.enable_static_atlas_egress
  secrets = {
    MONGODB_URI          = "mongodb-uri"
    WORKER_SHARED_SECRET = "worker-shared-secret"
    DB_PASS              = "db-pass"
  }
  secret_access = {
    "api-mongo"     = { service = "backend", secret = "MONGODB_URI" }
    "api-shared"    = { service = "backend", secret = "WORKER_SHARED_SECRET" }
    "worker-shared" = { service = "worker", secret = "WORKER_SHARED_SECRET" }
    "api-db"        = { service = "backend", secret = "DB_PASS" }
    "worker-db"     = { service = "worker", secret = "DB_PASS" }
  }
  sql_env = var.enable_postgres ? {
    DB_HOST = google_sql_database_instance.postgres[0].private_ip_address
    DB_PORT = "5432"
    DB_NAME = google_sql_database.gallery[0].name
    DB_USER = "photo_app"
  } : {}
}

resource "google_project_service" "api" {
  for_each           = local.apis
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.prefix
  format        = "DOCKER"
  description   = "Cloud Photo deployment images"
  depends_on    = [google_project_service.api]
}

resource "google_service_account" "identity" {
  for_each     = setunion(local.runtime, toset(["push", "deploy", "meter", "scheduler"]))
  account_id   = "${var.prefix}-${each.key}"
  display_name = "Cloud Photo ${each.key}"
  depends_on   = [google_project_service.api]
}

resource "google_storage_bucket" "images" {
  name                        = var.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  cors {
    origin          = distinct(concat([google_cloud_run_v2_service.frontend.uri], var.extra_frontend_origins))
    method          = ["GET", "HEAD", "PUT", "POST"]
    response_header = ["Content-Type", "ETag", "x-goog-generation", "x-goog-if-generation-match", "x-goog-resumable", "Location"]
    max_age_seconds = 3600
  }
  depends_on = [google_project_service.api]
}

resource "google_storage_bucket_iam_member" "writer" {
  for_each = toset(["backend", "worker"])
  bucket   = google_storage_bucket.images.name
  role     = "roles/storage.objectUser"
  member   = google_service_account.identity[each.key].member
}

resource "google_project_iam_custom_role" "signer" {
  role_id     = "${replace(var.prefix, "-", "_")}_url_signer"
  title       = "Cloud Photo URL signer"
  permissions = ["iam.serviceAccounts.signBlob"]
  depends_on  = [google_project_service.api]
}

resource "google_service_account_iam_member" "signer" {
  service_account_id = google_service_account.identity["backend"].name
  role               = google_project_iam_custom_role.signer.name
  member             = google_service_account.identity["backend"].member
}

resource "google_secret_manager_secret" "app" {
  for_each  = local.secrets
  secret_id = "${var.prefix}-${each.value}"
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "app" {
  for_each  = local.secret_access
  secret_id = google_secret_manager_secret.app[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.identity[each.value.service].member
}

resource "google_compute_network" "app" {
  count                   = local.use_network ? 1 : 0
  name                    = "${var.prefix}-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.api]
}

resource "google_compute_subnetwork" "run" {
  count                    = local.use_network ? 1 : 0
  name                     = "${var.prefix}-run"
  ip_cidr_range            = "10.70.0.0/24"
  network                  = google_compute_network.app[0].id
  private_ip_google_access = true
}

resource "google_compute_global_address" "sql" {
  count         = var.enable_postgres ? 1 : 0
  name          = "${var.prefix}-sql-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 24
  network       = google_compute_network.app[0].id
}

resource "google_service_networking_connection" "sql" {
  count                   = var.enable_postgres ? 1 : 0
  network                 = google_compute_network.app[0].id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql[0].name]
}

resource "google_sql_database_instance" "postgres" {
  count               = var.enable_postgres ? 1 : 0
  name                = "${var.prefix}-pg15"
  database_version    = "POSTGRES_15"
  region              = var.region
  deletion_protection = false
  settings {
    edition                     = "ENTERPRISE"
    tier                        = "db-f1-micro"
    availability_type           = "ZONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = 10
    disk_autoresize             = false
    deletion_protection_enabled = false
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.app[0].id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled    = true
      start_time = "18:30"
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }
  }
  depends_on = [google_service_networking_connection.sql]
}

resource "google_sql_database" "gallery" {
  count    = var.enable_postgres ? 1 : 0
  name     = "cloud_gallery"
  instance = google_sql_database_instance.postgres[0].name
}

resource "google_compute_address" "nat" {
  count      = var.enable_static_atlas_egress ? 1 : 0
  name       = "${var.prefix}-nat-ip"
  depends_on = [google_project_service.api]
}

resource "google_compute_router" "nat" {
  count   = var.enable_static_atlas_egress ? 1 : 0
  name    = "${var.prefix}-router"
  network = google_compute_network.app[0].id
}

resource "google_compute_router_nat" "app" {
  count                              = var.enable_static_atlas_egress ? 1 : 0
  name                               = "${var.prefix}-nat"
  router                             = google_compute_router.nat[0].name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat[0].self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {
    name                    = google_compute_subnetwork.run[0].id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

resource "google_cloud_run_v2_service" "frontend" {
  name                 = "${var.prefix}-frontend"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = true
  deletion_protection  = false

  template {
    service_account = google_service_account.identity["frontend"].email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.bootstrap_image
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "256Mi" }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, traffic]
  }
}

resource "google_cloud_run_v2_service" "backend" {
  name                 = "${var.prefix}-backend"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = true
  deletion_protection  = false

  template {
    service_account                  = google_service_account.identity["backend"].email
    timeout                          = "60s"
    max_instance_request_concurrency = 12
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
    dynamic "vpc_access" {
      for_each = local.use_network ? [1] : []
      content {
        egress = var.enable_static_atlas_egress ? "ALL_TRAFFIC" : "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = google_compute_network.app[0].name
          subnetwork = google_compute_subnetwork.run[0].name
        }
      }
    }
    containers {
      image = var.bootstrap_image
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      dynamic "env" {
        for_each = merge(local.sql_env, {
          NODE_ENV            = "production"
          ENTRA_TENANT_ID     = var.entra_tenant_id
          ENTRA_API_CLIENT_ID = var.entra_api_client_id
          ENTRA_AUDIENCE      = coalesce(var.entra_audience, var.entra_api_client_id)
          REQUIRED_API_SCOPE  = var.required_api_scope
          GCP_PROJECT_ID      = var.project_id
          GCS_BUCKET_NAME     = google_storage_bucket.images.name
          PUBSUB_TOPIC        = google_pubsub_topic.process.name
          CORS_ORIGINS        = join(",", distinct(concat([google_cloud_run_v2_service.frontend.uri], var.extra_frontend_origins)))
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = setunion(var.app_secrets_ready ? toset(["MONGODB_URI", "WORKER_SHARED_SECRET"]) : toset([]), var.enable_postgres && var.postgres_secret_ready ? toset(["DB_PASS"]) : toset([]))
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, traffic]
  }
  depends_on = [google_secret_manager_secret_iam_member.app, google_storage_bucket_iam_member.writer, google_service_account_iam_member.signer, google_pubsub_topic_iam_member.api]
}

resource "google_cloud_run_v2_service" "worker" {
  name                 = "${var.prefix}-worker"
  location             = var.region
  ingress              = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  invoker_iam_disabled = false
  deletion_protection  = false

  template {
    service_account                  = google_service_account.identity["worker"].email
    timeout                          = "105s"
    max_instance_request_concurrency = 1
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
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
      image = var.bootstrap_image
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      dynamic "env" {
        for_each = merge(local.sql_env, {
          NODE_ENV          = "production"
          GCP_PROJECT_ID    = var.project_id
          GCS_BUCKET_NAME   = google_storage_bucket.images.name
          BACKEND_BASE_URL  = google_cloud_run_v2_service.backend.uri
          DERIVATIVE_PREFIX = var.derivative_prefix
          PUBSUB_PUSH_PATH  = var.worker_push_path
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = setunion(var.app_secrets_ready ? toset(["WORKER_SHARED_SECRET"]) : toset([]), var.enable_postgres && var.postgres_secret_ready ? toset(["DB_PASS"]) : toset([]))
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, traffic]
    precondition {
      condition     = !var.enable_push || var.app_secrets_ready
      error_message = "Attach the application secrets and deploy the real Worker before enabling push."
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.app, google_storage_bucket_iam_member.writer]
}

resource "google_cloud_run_v2_service_iam_member" "invoke" {
  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = google_service_account.identity["push"].member
}

resource "google_pubsub_topic" "process" {
  name                       = "${var.prefix}-photo-processing"
  message_retention_duration = "172800s"
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_project_service.api]
}

resource "google_pubsub_topic" "dead" {
  name = "${var.prefix}-dead-letter"
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_project_service.api]
}

resource "google_pubsub_subscription" "dead" {
  name                       = "${var.prefix}-dead-letter"
  topic                      = google_pubsub_topic.dead.id
  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }
}

resource "google_project_service_identity" "pubsub" {
  provider   = google-beta
  service    = "pubsub.googleapis.com"
  depends_on = [google_project_service.api]
}

resource "google_service_account_iam_member" "push_token" {
  service_account_id = google_service_account.identity["push"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_pubsub_topic_iam_member" "api" {
  topic  = google_pubsub_topic.process.name
  role   = "roles/pubsub.publisher"
  member = google_service_account.identity["backend"].member
}

resource "google_pubsub_topic_iam_member" "dead" {
  topic  = google_pubsub_topic.dead.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_pubsub_subscription" "push" {
  count                      = var.enable_push ? 1 : 0
  name                       = "${var.prefix}-worker-push"
  topic                      = google_pubsub_topic.process.id
  ack_deadline_seconds       = 120
  message_retention_duration = "172800s"
  expiration_policy { ttl = "" }

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}${var.worker_push_path}"
    oidc_token {
      service_account_email = google_service_account.identity["push"].email
      audience              = google_cloud_run_v2_service.worker.uri
    }
  }
  retry_policy {
    minimum_backoff = "30s"
    maximum_backoff = "90s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead.id
    max_delivery_attempts = 10
  }
  depends_on = [
    google_cloud_run_v2_service_iam_member.invoke, google_service_account_iam_member.push_token,
    google_pubsub_topic_iam_member.dead, google_pubsub_subscription.dead
  ]
}

resource "google_pubsub_subscription_iam_member" "dead_forwarder" {
  count        = var.enable_push ? 1 : 0
  subscription = google_pubsub_subscription.push[0].name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_storage_bucket_iam_member" "qa" {
  for_each = var.qa_principals
  bucket   = google_storage_bucket.images.name
  role     = "roles/storage.objectViewer"
  member   = each.key
}

resource "google_pubsub_topic_iam_member" "qa" {
  for_each = var.qa_principals
  topic    = google_pubsub_topic.process.name
  role     = "roles/pubsub.publisher"
  member   = each.key
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${var.prefix}-github"
  display_name              = "Cloud Photo GitHub"
  depends_on                = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository_id" = "assertion.repository_id"
  }
  attribute_condition = "assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_owner_id}' && assertion.ref == 'refs/heads/${var.deploy_branch}' && assertion.workflow_ref == '${var.github_repository}/.github/workflows/deploy.yml@refs/heads/${var.deploy_branch}'"
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}

resource "google_service_account_iam_member" "github" {
  service_account_id = google_service_account.identity["deploy"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}

resource "google_artifact_registry_repository_iam_member" "deploy" {
  repository = google_artifact_registry_repository.images.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.identity["deploy"].member
}

resource "google_cloud_run_v2_service_iam_member" "deploy" {
  for_each = {
    frontend = google_cloud_run_v2_service.frontend.name
    backend  = google_cloud_run_v2_service.backend.name
    worker   = google_cloud_run_v2_service.worker.name
  }
  name     = each.value
  location = var.region
  role     = "roles/run.developer"
  member   = google_service_account.identity["deploy"].member
}

resource "google_service_account_iam_member" "act_as" {
  for_each           = local.runtime
  service_account_id = google_service_account.identity[each.key].name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.identity["deploy"].member
}
