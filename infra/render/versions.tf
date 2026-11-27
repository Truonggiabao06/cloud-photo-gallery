terraform {
  required_version = ">= 1.9"

  required_providers {
    render = {
      source  = "render-oss/render"
      version = "= 1.9.1"
    }
  }
}

provider "render" {
  skip_deploy_after_service_update = true
}
