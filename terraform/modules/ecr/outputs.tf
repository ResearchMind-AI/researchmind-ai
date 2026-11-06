output "repository_urls" {
  description = "Map of repository name to ECR URL"
  value       = { for name, repo in aws_ecr_repository.repos : name => repo.repository_url }
}

output "registry_id" {
  description = "ECR registry ID (AWS account ID)"
  value       = length(aws_ecr_repository.repos) > 0 ? values(aws_ecr_repository.repos)[0].registry_id : ""
}
