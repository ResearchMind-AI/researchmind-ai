resource "aws_db_subnet_group" "main" {
  name        = "${var.project_name}-db-subnet-group"
  description = "Subnet group for ${var.project_name} RDS"
  subnet_ids  = var.subnet_ids

  tags = {
    Name    = "${var.project_name}-db-subnet-group"
    Project = var.project_name
  }
}

resource "aws_db_parameter_group" "postgres" {
  name        = "${var.project_name}-postgres-params"
  family      = "postgres15"
  description = "Parameter group for ${var.project_name} PostgreSQL 15"

  tags = {
    Name    = "${var.project_name}-postgres-params"
    Project = var.project_name
  }
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.project_name}/rds/master-password"
  description             = "RDS master password for ${var.project_name}"
  recovery_window_in_days = 0 # Immediate deletion (change to 7 for production safety)

  tags = {
    Project = var.project_name
  }
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = var.db_password
}

resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-postgres"

  engine         = "postgres"
  engine_version = "15"
  instance_class = var.instance_class

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  # Free tier: 20GB gp2 storage (up to 20GB is free)
  allocated_storage     = 20
  storage_type          = "gp2"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.postgres.name

  # Single-AZ for free tier (multi-AZ doubles the cost)
  multi_az            = false
  publicly_accessible = false

  # Backups
  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  # Monitoring
  performance_insights_enabled          = false # Costs extra on t3.micro
  monitoring_interval                   = 0

  # Lifecycle
  deletion_protection       = false # Set to true before going to real production
  skip_final_snapshot       = true
  delete_automated_backups  = true

  tags = {
    Name    = "${var.project_name}-postgres"
    Project = var.project_name
  }
}
