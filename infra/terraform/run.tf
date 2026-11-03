# The web app: FastAPI serves the API, the agent and the built React files.
resource "google_cloud_run_v2_service" "app" {
  name                = "food-inspections"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.app.email
    timeout         = "120s"

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
      dynamic "env" {
        for_each = merge(local.common_env, {
          STATIC_DIR  = "/app/static"
          AGENT_MODEL = var.agent_model
        })
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  # Deploys (GitHub Actions or Cloud Build) change the image; Terraform owns the rest.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_project_service.enabled]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.app.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# The daily ETL: same image, different command.
resource "google_cloud_run_v2_job" "etl" {
  name                = "food-etl"
  location            = var.region
  deletion_protection = false

  template {
    task_count = 1
    template {
      service_account = google_service_account.etl.email
      timeout         = "1800s"
      max_retries     = 1
      containers {
        image   = var.image
        command = ["python", "-m", "etl.bq_load"]
        resources {
          limits = { cpu = "1", memory = "1Gi" }
        }
        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_project_service.enabled]
}

resource "google_cloud_scheduler_job" "daily_etl" {
  name      = "food-etl-daily"
  region    = var.region
  schedule  = var.etl_schedule
  time_zone = "America/Chicago"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.etl.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  depends_on = [google_project_service.enabled]
}
