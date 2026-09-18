terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local state only -- see README.md "Future improvements" for an S3 backend.
}

provider "aws" {
  region = var.aws_region
}
