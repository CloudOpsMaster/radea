terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.40" }
  }
}

module "network" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.8.1"
}

resource "aws_security_group_rule" "https" {
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["10.0.0.0/8"]
  security_group_id = "sg-1"
}

resource "aws_db_instance" "db" {
  engine              = "postgres"
  password            = var.db_password
  storage_encrypted   = true
  publicly_accessible = false
  deletion_protection = true

  lifecycle {
    prevent_destroy = true
  }
}
