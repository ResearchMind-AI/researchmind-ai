variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type (t2.micro is free tier eligible)"
  type        = string
  default     = "t2.micro"
}

variable "ec2_public_key" {
  description = "SSH public key for EC2 access (corresponds to EC2_SSH_PRIVATE_KEY secret)"
  type        = string
  sensitive   = true
}

variable "subnet_id" {
  description = "Subnet ID to launch the instance in"
  type        = string
}

variable "security_group_id" {
  description = "Security group ID for the EC2 instance"
  type        = string
}
