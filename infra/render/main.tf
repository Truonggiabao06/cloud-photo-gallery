locals {
  prefix = "${var.project_name}-${var.environment}"
  storage = {
    S3_ENDPOINT = var.supabase_s3_endpoint
    S3_REGION   = var.supabase_s3_region
    S3_BUCKET   = var.supabase_bucket
  }
}

resource "render_web_service" "backend" {
  name              = "${local.prefix}-api"
  plan              = "free"
  region            = var.region
  health_check_path = "/health"

  runtime_source = {
    docker = {
      repo_url            = var.repo_url
      branch              = var.deploy_branch
      context             = "./backend"
      dockerfile_path     = "./backend/Dockerfile"
      auto_deploy_trigger = "off"
    }
  }

  env_vars = {
    for key, value in merge(local.storage, {
      STORAGE_BACKEND            = "s3"
      HTTP_TRUST_PROXY_HOPS      = "1"
      HTTP_RATE_LIMIT_PER_15_MIN = var.environment == "staging" ? "3000" : "300"
      ENTRA_TENANT_ID            = var.entra.tenant_id
      ENTRA_API_CLIENT_ID        = var.entra.api_client_id
      REQUIRED_API_SCOPE         = var.entra.scope
      }, var.frontend_origin == null ? {} : {
      CORS_ORIGINS = var.frontend_origin
      }, var.worker_wake_url == null ? {} : {
      WORKER_WAKE_URL = var.worker_wake_url
    }) : key => { value = value }
  }

  lifecycle {
    precondition {
      condition     = terraform.workspace == var.environment
      error_message = "Select the staging or prod workspace matching environment."
    }
  }
}

resource "render_web_service" "worker" {
  name              = "${local.prefix}-worker"
  plan              = "free"
  region            = var.region
  health_check_path = "/health"

  runtime_source = {
    docker = {
      repo_url            = var.repo_url
      branch              = var.deploy_branch
      context             = "./worker"
      dockerfile_path     = "./worker/Dockerfile"
      auto_deploy_trigger = "off"
    }
  }

  env_vars = {
    for key, value in merge(local.storage, {
      WORKER_MODE        = "outbox"
      DEPLOY_ENVIRONMENT = var.environment
      BACKEND_BASE_URL   = render_web_service.backend.url
    }) : key => { value = value }
  }
}

resource "render_static_site" "frontend" {
  name                = "${local.prefix}-web"
  repo_url            = var.repo_url
  branch              = var.deploy_branch
  root_directory      = "frontend"
  build_command       = "node build-config.cjs && mkdir -p dist && cp -R index.html css js dist/"
  publish_path        = "dist"
  auto_deploy_trigger = "off"

  env_vars = {
    VITE_API_BASE_URL    = { value = render_web_service.backend.url }
    VITE_ENTRA_TENANT_ID = { value = var.entra.tenant_id }
    VITE_ENTRA_CLIENT_ID = { value = var.entra.frontend_client_id }
    VITE_ENTRA_API_SCOPE = { value = "api://${var.entra.api_client_id}/${var.entra.scope}" }
  }

  headers = [
    { path = "/*", name = "X-Content-Type-Options", value = "nosniff" },
    { path = "/*", name = "Referrer-Policy", value = "no-referrer" },
    { path = "/*", name = "X-Frame-Options", value = "DENY" }
  ]
}

resource "render_env_group_link" "app" {
  env_group_id = var.shared_env_group_id
  service_ids  = [render_web_service.backend.id, render_web_service.worker.id]
}
