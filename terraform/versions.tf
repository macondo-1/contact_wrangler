terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state on purpose (Task 8.4 leaves a remote backend as optional):
  # this is a single-maintainer portfolio deployment, not a team-shared
  # one, so an S3+DynamoDB remote backend would add real setup cost
  # (a bucket and lock table to bootstrap before this config can even run)
  # for no locking/collaboration benefit anyone actually needs here.
  # terraform.tfstate is gitignored -- see the note in outputs.tf about
  # what that means for secrets.
}
