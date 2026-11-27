output "frontend_url" {
  value = google_cloud_run_v2_service.frontend.uri
}
output "backend_url" {
  value = google_cloud_run_v2_service.backend.uri
}
output "worker_url" {
  value = google_cloud_run_v2_service.worker.uri
}
output "bucket" {
  value = google_storage_bucket.images.name
}
output "topic" {
  value = google_pubsub_topic.process.name
}
output "dead_letter_subscription" {
  value = google_pubsub_subscription.dead.name
}
output "push_subscription" {
  value = one(google_pubsub_subscription.push[*].name)
}
output "secret_ids" {
  value = { for key, secret in google_secret_manager_secret.app : key => secret.secret_id }
}
output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
output "atlas_egress_ip" {
  value = one(google_compute_address.nat[*].address)
}
output "postgres_private_ip" {
  value = one(google_sql_database_instance.postgres[*].private_ip_address)
}
output "github_variables" {
  value = {
    GCP_PROJECT_ID         = var.project_id
    GCP_REGION             = var.region
    RUN_PREFIX             = var.prefix
    ARTIFACT_REGISTRY      = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
    WIF_PROVIDER           = google_iam_workload_identity_pool_provider.github.name
    DEPLOY_SERVICE_ACCOUNT = google_service_account.identity["deploy"].email
    VITE_API_BASE_URL      = google_cloud_run_v2_service.backend.uri
    VITE_ENTRA_TENANT_ID   = var.entra_tenant_id
    VITE_ENTRA_API_SCOPE   = "api://${var.entra_api_client_id}/${var.required_api_scope}"
  }
}
