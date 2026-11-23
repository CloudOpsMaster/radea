# Deliberately insecure; every finding RADEA reports here is real.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

module "network" {
  source = "terraform-aws-modules/vpc/aws"
}

resource "aws_security_group_rule" "ssh" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = "sg-1"
}

resource "aws_db_instance" "db" {
  engine              = "postgres"
  password            = "SuperSecret123"
  storage_encrypted   = false
  publicly_accessible = true
  skip_final_snapshot = true
}
