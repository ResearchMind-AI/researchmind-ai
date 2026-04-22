variable "aws_region" {
  description = "AWS region to deploy resources in"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming (keep it short, lowercase, hyphens ok)"
  type        = string
  default     = "researchmind"
}

variable "db_password" {
  description = "Master password for the RDS PostgreSQL instance"
  type        = string
  sensitive   = true
}

variable "ec2_public_key" {
  description = "SSH public key content for EC2 access (generate with: ssh-keygen -t ed25519)"
  type        = string
  sensitive   = true
}

variable "availability_zones" {
  description = "Availability zones in the selected region (at least 2 required for RDS)"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}
