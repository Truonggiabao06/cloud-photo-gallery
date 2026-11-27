output "frontend_url" {
  value = render_static_site.frontend.url
}
output "backend_url" {
  value = render_web_service.backend.url
}
output "worker_url" {
  value = render_web_service.worker.url
}
output "github_environment_variables" {
  value = {
    RENDER_DEPLOY_BRANCH = var.deploy_branch
    RENDER_BACKEND_ID    = render_web_service.backend.id
    RENDER_WORKER_ID     = render_web_service.worker.id
    RENDER_FRONTEND_ID   = render_static_site.frontend.id
    RENDER_BACKEND_URL   = render_web_service.backend.url
    RENDER_WORKER_URL    = render_web_service.worker.url
    RENDER_FRONTEND_URL  = render_static_site.frontend.url
  }
}
