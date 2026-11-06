# NOTE: You must create this S3 bucket manually before running `terraform init`.
#
#   aws s3api create-bucket \
#     --bucket researchmind-terraform-state \
#     --region us-east-1
#
#   aws s3api put-bucket-versioning \
#     --bucket researchmind-terraform-state \
#     --versioning-configuration Status=Enabled
#
# Then update the region below to match your chosen AWS region.

terraform {
  backend "s3" {
    bucket = "researchmind-terraform-state"
    key    = "prod/terraform.tfstate"
    region = "us-east-1" # Update to your region
  }
}
