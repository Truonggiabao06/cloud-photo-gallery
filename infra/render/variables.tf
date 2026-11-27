variable "environment" {
  type        = string
  description = "Environment and Terraform workspace name."
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "Use staging or prod."
  }
}

variable "project_name" {
  type        = string
  description = "Lowercase Render naming prefix, unique within your workspace."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.project_name))
    error_message = "Use 3–30 lowercase letters, digits, and hyphens."
  }
}

variable "repo_url" {
  type = string
  validation {
    condition     = can(regex("^https://github\\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", var.repo_url))
    error_message = "Use the public GitHub HTTPS repository URL with no credentials."
  }
}

variable "deploy_branch" {
  type = string
}

variable "region" {
  type    = string
  default = "singapore"
}

variable "supabase_s3_endpoint" {
  type        = string
  description = "Public endpoint from Supabase Storage settings."
  validation {
    condition     = can(regex("^https://[a-z0-9]+\\.storage\\.supabase\\.co/storage/v1/s3$", var.supabase_s3_endpoint))
    error_message = "Use the Supabase Storage HTTPS S3 endpoint without query parameters."
  }
}

variable "supabase_s3_region" {
  type = string
}

variable "supabase_bucket" {
  type = string
}

variable "shared_env_group_id" {
  type        = string
  description = "The existing Render environment group ID. Secret values remain in Render."
  validation {
    condition     = can(regex("^evg-[a-z0-9]+$", var.shared_env_group_id))
    error_message = "Use the evg-* ID of this environment's Render group."
  }
}

variable "frontend_origin" {
  type        = string
  default     = null
  description = "Set to frontend_url from the first apply."
  validation {
    condition     = var.frontend_origin == null ? true : can(regex("^https://[a-z0-9-]+\\.onrender\\.com$", var.frontend_origin))
    error_message = "Use the Render Frontend HTTPS origin without a trailing slash."
  }
}

variable "worker_wake_url" {
  type        = string
  default     = null
  description = "Set to worker_url from the first apply."
  validation {
    condition     = var.worker_wake_url == null ? true : can(regex("^https://[a-z0-9-]+\\.onrender\\.com$", var.worker_wake_url))
    error_message = "Use the Render Worker HTTPS origin without a trailing slash."
  }
}

variable "entra" {
  type = object({
    tenant_id          = string
    api_client_id      = string
    frontend_client_id = string
    scope              = optional(string, "access_as_user")
  })
  validation {
    condition = alltrue([
      for id in [var.entra.tenant_id, var.entra.api_client_id, var.entra.frontend_client_id] :
      can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", id))
    ]) && can(regex("^[a-zA-Z0-9_.-]+$", var.entra.scope))
    error_message = "Provide valid Entra client and tenant UUIDs and a short delegated scope."
  }
}
