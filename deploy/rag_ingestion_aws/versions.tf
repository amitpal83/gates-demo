terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local state only, deliberately -- this is a small-team/POC-leaning
  # single-instance stack, not a multi-operator production system. No S3
  # backend, no DynamoDB lock table. See README.md "Future improvements"
  # for what a hardened setup would add (S3 backend + state locking, plus
  # moving the secrets in terraform.tfvars into AWS Secrets Manager/SSM
  # Parameter Store instead of a local file).
}

provider "aws" {
  region = var.aws_region
}
