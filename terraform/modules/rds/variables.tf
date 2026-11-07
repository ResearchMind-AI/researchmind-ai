variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
}

variable "instance_class" {
  description = "RDS instance class (db.t3.micro is free tier eligible)"
  type        = string
  default     = "db.t3.micro"
}

variable "db_name" {
  description = "Name of the database to create"
  type        = string
  default     = "researchmind_db"
}

variable "db_username" {
  description = "Master username for the database"
  type        = string
  default     = "researchmind"
}

variable "db_password" {
  description = "Master password for the database"
  type        = string
  sensitive   = true
}

variable "subnet_ids" {
  description = "List of subnet IDs for the DB subnet group (needs at least 2 AZs)"
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group ID that controls access to RDS"
  type        = string
}
