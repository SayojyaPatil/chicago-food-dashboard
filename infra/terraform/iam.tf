# One service account per job, each with only what it needs.

resource "google_service_account" "app" {
  account_id   = "food-app"
  display_name = "Cloud Run app: reads BigQuery, calls Vertex AI"
}

resource "google_service_account" "etl" {
  account_id   = "food-etl"
  display_name = "Cloud Run job: loads inspections into BigQuery"
}

resource "google_service_account" "scheduler" {
  account_id   = "food-scheduler"
  display_name = "Cloud Scheduler: starts the ETL job"
}

resource "google_service_account" "deployer" {
  account_id   = "food-deployer"
  display_name = "GitHub Actions: deploys and runs evals"
}

# App: run queries, read the dataset, call Gemini and embeddings.
resource "google_project_iam_member" "app_roles" {
  for_each = toset(["roles/bigquery.jobUser", "roles/aiplatform.user"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

resource "google_bigquery_dataset_iam_member" "app_read" {
  dataset_id = google_bigquery_dataset.food.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.app.email}"
}

# ETL: run load/merge jobs and write to the dataset only.
resource "google_project_iam_member" "etl_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.etl.email}"
}

resource "google_bigquery_dataset_iam_member" "etl_write" {
  dataset_id = google_bigquery_dataset.food.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.etl.email}"
}

# Scheduler: allowed to start this one job.
resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_etl" {
  name     = google_cloud_run_v2_job.etl.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# Deployer: push images, update Cloud Run, and run the eval suite.
resource "google_project_iam_member" "deployer_roles" {
  for_each = toset([
    "roles/run.developer",
    "roles/artifactregistry.writer",
    "roles/bigquery.jobUser",
    "roles/aiplatform.user",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_bigquery_dataset_iam_member" "deployer_read" {
  dataset_id = google_bigquery_dataset.food.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a service that runs as app/etl requires permission to act as them.
resource "google_service_account_iam_member" "deployer_acts_as" {
  for_each           = { app = google_service_account.app.name, etl = google_service_account.etl.name }
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# ── GitHub Actions sign-in without a key file (Workload Identity Federation) ──

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == \"${var.github_repo}\""
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_uses_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
