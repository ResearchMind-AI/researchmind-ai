output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.app.id
}

output "public_ip" {
  description = "Elastic IP address of the EC2 instance"
  value       = aws_eip.app.public_ip
}

output "instance_profile_name" {
  description = "IAM instance profile name"
  value       = aws_iam_instance_profile.ec2.name
}
