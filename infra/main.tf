provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Authenticates from the CLOUDFLARE_API_TOKEN environment variable, so the
# token never appears in tfvars or state.
provider "cloudflare" {}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  api_domain = "api.${var.domain_name}"
  www_domain = "www.${var.domain_name}"

  api_function_name = "${var.project}-api"
}
