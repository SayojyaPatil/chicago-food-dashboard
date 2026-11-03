resource "google_bigquery_dataset" "food" {
  dataset_id  = "food_safety"
  location    = var.bq_location
  description = "City of Chicago food inspections and the food code search index"
  depends_on  = [google_project_service.enabled]
}

resource "google_bigquery_table" "inspections" {
  dataset_id          = google_bigquery_dataset.food.dataset_id
  table_id            = "inspections"
  deletion_protection = false
  clustering          = ["zip", "results"]

  time_partitioning {
    type  = "MONTH"
    field = "inspection_date"
  }

  schema = jsonencode([
    { name = "inspection_id", type = "STRING", mode = "REQUIRED" },
    { name = "dba_name", type = "STRING" },
    { name = "aka_name", type = "STRING" },
    { name = "license_num", type = "STRING" },
    { name = "facility_type", type = "STRING" },
    { name = "risk", type = "STRING" },
    { name = "address", type = "STRING" },
    { name = "city", type = "STRING" },
    { name = "state", type = "STRING" },
    { name = "zip", type = "STRING" },
    { name = "inspection_date", type = "DATE" },
    { name = "inspection_type", type = "STRING" },
    { name = "results", type = "STRING" },
    { name = "violations", type = "STRING" },
    { name = "latitude", type = "FLOAT64" },
    { name = "longitude", type = "FLOAT64" },
  ])
}

resource "google_bigquery_table" "etl_runs" {
  dataset_id          = google_bigquery_dataset.food.dataset_id
  table_id            = "etl_runs"
  deletion_protection = false

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "started_at", type = "TIMESTAMP" },
    { name = "finished_at", type = "TIMESTAMP" },
    { name = "since_date", type = "DATE" },
    { name = "rows_fetched", type = "INT64" },
    { name = "rows_merged", type = "INT64" },
    { name = "status", type = "STRING" },
    { name = "error", type = "STRING" },
  ])
}

# Filled by scripts/ingest_food_code.py (it replaces the contents on each run).
resource "google_bigquery_table" "food_code_chunks" {
  dataset_id          = google_bigquery_dataset.food.dataset_id
  table_id            = "food_code_chunks"
  deletion_protection = false

  schema = jsonencode([
    { name = "chunk_id", type = "STRING", mode = "REQUIRED" },
    { name = "section", type = "STRING" },
    { name = "title", type = "STRING" },
    { name = "text", type = "STRING" },
    { name = "source", type = "STRING" },
    { name = "embedding", type = "FLOAT64", mode = "REPEATED" },
  ])
}
