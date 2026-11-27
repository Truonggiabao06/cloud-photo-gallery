terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.50"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 6.50"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}
