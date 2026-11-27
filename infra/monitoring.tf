locals {
  worker_log = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.worker.name}\""
  terminal   = "${local.worker_log} AND jsonPayload.event=\"job_terminal\""
  log_counts = {
    terminal = local.terminal
    failed   = "${local.terminal} AND jsonPayload.status=\"FAILED\""
    retries  = "${local.worker_log} AND jsonPayload.event=\"job_attempt\" AND jsonPayload.deliveryAttempt>1"
  }
  age_filter  = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" AND resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${var.prefix}-worker-push\""
  bytes_type  = "custom.googleapis.com/${var.prefix}/derivative_storage_bytes"
  oldest_type = "custom.googleapis.com/${var.prefix}/oldest_job_age_seconds"
}

resource "google_logging_metric" "counts" {
  for_each = local.log_counts
  name     = "${var.prefix}_${each.key}"
  filter   = each.value
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_logging_metric" "latency" {
  name            = "${var.prefix}_latency_seconds"
  filter          = "${local.terminal} AND jsonPayload.status=\"COMPLETED\" AND jsonPayload.latencySeconds>=0"
  value_extractor = "EXTRACT(jsonPayload.latencySeconds)"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "s"
  }
  bucket_options {
    explicit_buckets {
      bounds = [0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 90, 120, 180, 300, 600, 1200]
    }
  }
}

resource "google_monitoring_metric_descriptor" "derivative_bytes" {
  type         = local.bytes_type
  display_name = "Derivative storage size"
  metric_kind  = "GAUGE"
  value_type   = "INT64"
  unit         = "By"
  labels {
    key        = "bucket"
    value_type = "STRING"
  }
  depends_on = [google_project_service.api]
}

resource "google_monitoring_metric_descriptor" "oldest_job" {
  type         = local.oldest_type
  display_name = "Oldest unfinished ProcessingJob age"
  metric_kind  = "GAUGE"
  value_type   = "INT64"
  unit         = "s"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_member" "write_metrics" {
  for_each = toset(["meter", "worker"])
  role     = "roles/monitoring.metricWriter"
  member   = google_service_account.identity[each.key].member
}

resource "google_storage_bucket_iam_member" "meter" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.identity["meter"].member
}

resource "google_cloud_run_v2_job" "meter" {
  name                = "${var.prefix}-storage-meter"
  location            = var.region
  deletion_protection = false
  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.identity["meter"].email
      timeout         = "180s"
      max_retries     = 0
      containers {
        image   = "gcr.io/google.com/cloudsdktool/google-cloud-cli:stable"
        command = ["python3"]
        args    = ["-c", file("${path.module}/measure_derivatives.py")]
        resources {
          limits = { cpu = "1", memory = "256Mi" }
        }
        dynamic "env" {
          for_each = {
            PROJECT_ID        = var.project_id
            GCS_BUCKET_NAME   = google_storage_bucket.images.name
            DERIVATIVE_PREFIX = var.derivative_prefix
            METRIC_TYPE       = google_monitoring_metric_descriptor.derivative_bytes.type
          }
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
  depends_on = [google_storage_bucket_iam_member.meter, google_project_iam_member.write_metrics]
}

resource "google_cloud_run_v2_job_iam_member" "schedule" {
  name     = google_cloud_run_v2_job.meter.name
  location = var.region
  role     = "roles/run.invoker"
  member   = google_service_account.identity["scheduler"].member
}

resource "google_cloud_scheduler_job" "meter" {
  name      = "${var.prefix}-storage-meter"
  region    = var.region
  schedule  = "*/15 * * * *"
  time_zone = "Etc/UTC"
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.meter.name}:run"
    oauth_token {
      service_account_email = google_service_account.identity["scheduler"].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  depends_on = [google_cloud_run_v2_job_iam_member.schedule]
}

resource "google_monitoring_notification_channel" "email" {
  display_name = "${var.prefix} on-call"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.api]
}

resource "google_monitoring_alert_policy" "backlog" {
  display_name          = "${var.prefix}: worker has unacknowledged work over 120s"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.name]
  enabled               = var.enable_push
  documentation {
    mime_type = "text/markdown"
    content   = "Open Cloud Run Worker revision logs and trace photoId/jobId/messageId. If a bad revision or the staging fault drill is active, route 100% to the known-good revision. Verify pending work drains; inspect DLQ for exhausted jobs before replay. See docs/monitoring_runbook.md."
  }
  conditions {
    display_name = "Oldest push message age stays above 120s for 60s"
    condition_threshold {
      filter          = local.age_filter
      comparison      = "COMPARISON_GT"
      threshold_value = 120
      duration        = "60s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }
}

locals {
  charts = [
    {
      title = "Oldest job age (s) | DB gauge and Pub/Sub proxy"
      queries = [
        { timeSeriesFilter = { filter = "metric.type=\"${google_monitoring_metric_descriptor.oldest_job.type}\" AND resource.type=\"global\"", aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_MAX" } } },
        { timeSeriesFilter = { filter = local.age_filter, aggregation = { alignmentPeriod = "60s", perSeriesAligner = "ALIGN_MAX" } } }
      ]
    },
    {
      title = "Processing latency p95 (s)"
      queries = [
        { timeSeriesFilter = {
          filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.latency.name}\" AND resource.type=\"cloud_run_revision\""
          aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_DELTA", crossSeriesReducer = "REDUCE_PERCENTILE_95" }
        } }
      ]
    },
    {
      title = "Failure rate (%)"
      queries = [
        { prometheusQuery = "100 * (sum(increase({__name__=\"logging.googleapis.com/user/${google_logging_metric.counts["failed"].name}\",monitored_resource=\"cloud_run_revision\"}[5m])) or vector(0)) / (sum(increase({__name__=\"logging.googleapis.com/user/${google_logging_metric.counts["terminal"].name}\",monitored_resource=\"cloud_run_revision\"}[5m])) > 0)" }
      ]
    },
    {
      title = "Retry count (per 5 min)"
      queries = [
        { timeSeriesFilter = {
          filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.counts["retries"].name}\" AND resource.type=\"cloud_run_revision\""
          aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_SUM", crossSeriesReducer = "REDUCE_SUM" }
        } }
      ]
    },
    {
      title = "Derivative storage size (bytes)"
      queries = [
        { timeSeriesFilter = { filter = "metric.type=\"${google_monitoring_metric_descriptor.derivative_bytes.type}\" AND resource.type=\"global\"" } }
      ]
    }
  ]
}

resource "google_monitoring_dashboard" "ops" {
  dashboard_json = jsonencode({
    displayName = "${var.prefix} | Cloud Photo Operations"
    gridLayout = {
      columns = "2"
      widgets = [
        for chart in local.charts : {
          title = chart.title
          xyChart = {
            dataSets = [
              for query in chart.queries : { timeSeriesQuery = merge(query, chart.title == "Failure rate (%)" ? { unitOverride = "%" } : {}), plotType = "LINE", minAlignmentPeriod = "60s" }
            ]
            chartOptions = { mode = "COLOR" }
          }
        }
      ]
    }
  })
}
