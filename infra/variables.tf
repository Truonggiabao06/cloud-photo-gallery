variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-southeast1"
}

variable "prefix" {
  type    = string
  default = "photo07"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,14}[a-z0-9]$", var.prefix))
    error_message = "Use 4–16 lowercase letters, digits or dashes, starting with a letter and ending with a letter or digit."
  }
}

variable "bucket_name" {
  type = string
}

variable "entra_tenant_id" {
  type = string
}

variable "entra_api_client_id" {
  type = string
}

variable "entra_audience" {
  type    = string
  default = ""
}

variable "required_api_scope" {
  type    = string
  default = "access_as_user"
}

variable "extra_frontend_origins" {
  type    = list(string)
  default = []
}

variable "github_repository" {
  description = "GitHub owner/repository (exact case)."
  type        = string
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID as a string."
  type        = string
}

variable "github_owner_id" {
  description = "Numeric GitHub repository owner ID as a string."
  type        = string
}

variable "deploy_branch" {
  type    = string
  default = "main"
}

variable "alert_email" {
  type = string
}

variable "app_secrets_ready" {
  description = "Attach existing worker secret version to Backend and Worker."
  type        = bool
  default     = false
}

variable "enable_postgres" {
  description = "Create private Cloud SQL PostgreSQL 15 and its database."
  type        = bool
  default     = false
}

variable "postgres_secret_ready" {
  description = "Expose DB_PASS only after its secret version and SQL application user exist."
  type        = bool
  default     = false
}

variable "enable_static_atlas_egress" {
  description = "Route Backend egress via Cloud NAT with one reserved public IP for Atlas."
  type        = bool
  default     = false
}

variable "enable_push" {
  description = "Create authenticated subscription after deploying a real Worker."
  type        = bool
  default     = false
}

variable "worker_push_path" {
  type    = string
  default = "/pubsub/push"
  validation {
    condition     = can(regex("^/([A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+$", var.worker_push_path))
    error_message = "Use an absolute HTTP path such as /pubsub/push."
  }
}

variable "derivative_prefix" {
  type    = string
  default = "thumbnails/"
  validation {
    condition     = var.derivative_prefix == "thumbnails/"
    error_message = "Use thumbnails/ to match the generated PostgreSQL object keys."
  }
}

variable "qa_principals" {
  description = "IAM members, e.g. user:qa@example.org, in staging only."
  type        = set(string)
  default     = []
}

variable "bootstrap_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello:latest"
}
