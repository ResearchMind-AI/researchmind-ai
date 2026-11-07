output "endpoint" {
  description = "RDS instance endpoint (host:port)"
  value       = aws_db_instance.postgres.endpoint
}

output "address" {
  description = "RDS instance hostname"
  value       = aws_db_instance.postgres.address
}

output "port" {
  description = "RDS instance port"
  value       = aws_db_instance.postgres.port
}

output "db_name" {
  description = "Database name"
  value       = aws_db_instance.postgres.db_name
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret containing the DB password"
  value       = aws_secretsmanager_secret.db_password.arn
}
