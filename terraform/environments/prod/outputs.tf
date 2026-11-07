output "ec2_public_ip" {
  description = "Public IP of the EC2 instance — add this to your DNS and to the EC2_HOST GitHub secret"
  value       = module.ec2.public_ip
}

output "rds_endpoint" {
  description = "RDS endpoint — use in DATABASE_URL on the EC2 instance"
  value       = module.rds.endpoint
}

output "rds_address" {
  description = "RDS hostname"
  value       = module.rds.address
}

output "ecr_backend_url" {
  description = "ECR URL for the backend image"
  value       = module.ecr.repository_urls["${var.project_name}-backend"]
}

output "ecr_frontend_url" {
  description = "ECR URL for the frontend image"
  value       = module.ecr.repository_urls["${var.project_name}-frontend"]
}

output "db_password_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the RDS master password"
  value       = module.rds.secret_arn
}
