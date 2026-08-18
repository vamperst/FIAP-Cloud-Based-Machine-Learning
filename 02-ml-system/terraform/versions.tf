terraform {
  # Pinned exactly, not with "~>": a classroom where two students resolve
  # different versions is a classroom debugging Terraform instead of ML systems.
  required_version = "= 1.15.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.60.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.0"
    }
  }
}
