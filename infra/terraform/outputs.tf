output "app_url" {
  value = google_cloud_run_v2_service.app.uri
}

output "image_repo" {
  description = "Push images here, e.g. <image_repo>/app:<tag>"
  value       = local.image_repo
}

output "deployer_service_account" {
  description = "GitHub secret GCP_SERVICE_ACCOUNT"
  value       = google_service_account.deployer.email
}

output "workload_identity_provider" {
  description = "GitHub secret GCP_WORKLOAD_IDENTITY_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.github.name
}
