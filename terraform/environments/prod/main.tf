module "vpc" {
  source = "../../modules/vpc"

  project_name        = var.project_name
  vpc_cidr            = "10.0.0.0/16"
  public_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]
  availability_zones  = var.availability_zones
}

module "ecr" {
  source = "../../modules/ecr"

  project_name     = var.project_name
  repository_names = [
    "${var.project_name}-backend",
    "${var.project_name}-frontend",
  ]
}

module "rds" {
  source = "../../modules/rds"

  project_name      = var.project_name
  instance_class    = "db.t3.micro" # Free tier eligible
  db_name           = "researchmind_db"
  db_username       = "researchmind"
  db_password       = var.db_password
  subnet_ids        = module.vpc.public_subnet_ids
  security_group_id = module.vpc.rds_security_group_id
}

module "ec2" {
  source = "../../modules/ec2"

  project_name      = var.project_name
  instance_type     = "t2.micro" # Free tier eligible (t3.micro also works)
  ec2_public_key    = var.ec2_public_key
  subnet_id         = module.vpc.public_subnet_ids[0]
  security_group_id = module.vpc.ec2_security_group_id
}
