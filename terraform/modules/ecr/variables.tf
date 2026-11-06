variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
}

variable "repository_names" {
  description = "List of ECR repository names to create"
  type        = list(string)
}
