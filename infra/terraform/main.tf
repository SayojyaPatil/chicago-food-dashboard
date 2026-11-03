terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # State is local by default. To share it, create a bucket and uncomment:
  # backend "gcs" { bucket = "YOUR-PROJECT-tfstate" prefix = "food-safety" }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  services = [
    "run.googleapis.com",
    "bigquery.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ]
  image_repo = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
  common_env = {
    DATA_BACKEND    = "bigquery"
    GCP_PROJECT     = var.project_id
    BQ_DATASET      = google_bigquery_dataset.food.dataset_id
    BQ_LOCATION     = var.bq_location
    VERTEX_LOCATION = var.vertex_location
  }
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "food-safety"
  format        = "DOCKER"
  description   = "Images for the Chicago food inspections app"

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  depends_on = [google_project_service.enabled]
}
