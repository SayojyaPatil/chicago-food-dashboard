variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Scheduler and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "bq_location" {
  description = "BigQuery dataset location"
  type        = string
  default     = "US"
}

variable "vertex_location" {
  description = "Vertex AI location for the model and embeddings. Newer Gemini models are served only from global."
  type        = string
  default     = "global"
}

variable "image" {
  description = "Container image. The first apply uses a placeholder; deploys replace it."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "agent_model" {
  description = "Gemini model ID on Vertex AI. Check Model Garden for retirements."
  type        = string
  default     = "gemini-3.8-flash"
}

variable "github_repo" {
  description = "owner/name of the GitHub repo allowed to deploy"
  type        = string
  default     = "SayojyaPatil/chicago-food-dashboard"
}

variable "etl_schedule" {
  description = "Cron schedule for the daily ETL (America/Chicago)"
  type        = string
  default     = "15 6 * * *"
}

variable "max_instances" {
  description = "Upper bound on Cloud Run instances; caps cost"
  type        = number
  default     = 2
}
