# Намеренные IaC-мисконфигурации проекта-полигона (docs/e2e-test-plan.md).
#
# Только тестовые данные. Trivy misconfig (AVD-*) должен сработать на:
#   1. aws_s3_bucket c acl="public-read"  -> AVD-AWS-0086 (public ACL)
#   2. IAM policy c Action="*"/Resource="*" -> AVD-AWS-0057 (full access)
#   3. aws_db_instance c password в коде    -> AVD-AWS-0138 (password in resource)
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_s3_bucket" "public_assets" {
  bucket = "appsecgate-e2e-public-assets"
  acl    = "public-read"
}

resource "aws_iam_user" "e2e_ci" {
  name = "appsecgate-e2e-ci"
}

resource "aws_iam_user_policy" "e2e_ci_full_access" {
  name = "full-access"
  user = aws_iam_user.e2e_ci.name
  policy = <<-POLICY
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": "*",
        "Resource": "*"
      }
    ]
  }
  POLICY
}

resource "aws_db_instance" "e2e_db" {
  engine              = "mysql"
  instance_class      = "db.t3.micro"
  allocated_storage   = 20
  username            = "admin"
  password            = "SuperSecret123456"
  skip_final_snapshot = true
}
