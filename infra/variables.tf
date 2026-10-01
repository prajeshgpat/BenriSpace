variable "aws_region" {
  description = "AWS region for all regional resources."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name, used as a prefix for resource names and in tags."
  type        = string
  default     = "benrispace"
}

variable "environment" {
  description = "Deployment environment, used in tags and the SSM parameter path."
  type        = string
  default     = "prod"
}

variable "domain_name" {
  description = "Apex domain. The frontend is served at the apex and www, the API at api.<domain>."
  type        = string
  default     = "benrispace.com"
}

# --- Lambda API ---------------------------------------------------------------

variable "lambda_zip_path" {
  description = "Path to the Lambda deployment zip. Only read when the function is first created; CI owns the code afterwards."
  type        = string
  default     = "../build/lambda.zip"
}

variable "lambda_memory_mb" {
  description = "Lambda memory in MB. CPU scales with memory, which mostly matters for cold-start import time."
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout. Must stay below API Gateway's 30s integration limit."
  type        = number
  default     = 20

  validation {
    condition     = var.lambda_timeout_seconds > 0 && var.lambda_timeout_seconds < 30
    error_message = "lambda_timeout_seconds must be between 1 and 29 (API Gateway HTTP APIs cut integrations off at 30s)."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the API function."
  type        = number
  default     = 14
}

variable "api_throttle_rate_limit" {
  description = "Steady-state requests per second allowed across the API's default stage."
  type        = number
  default     = 10
}

variable "api_throttle_burst_limit" {
  description = "Burst request capacity for the API's default stage."
  type        = number
  default     = 20
}

variable "disable_execute_api_endpoint" {
  description = "Turn off the generated execute-api hostname so api.<domain> is the only entry point. Leave false until the custom domain resolves, since the execute-api URL is the only way to reach the API before then."
  type        = bool
  default     = false
}

# --- GitHub -------------------------------------------------------------------

variable "github_repository" {
  description = "GitHub repository as owner/name. Used for the OIDC deploy role trust and the Amplify source."
  type        = string
  default     = "prajeshgpat/BenriSpace"
}

variable "github_branch" {
  description = "Branch that may deploy the API and that Amplify builds as production."
  type        = string
  default     = "main"
}

variable "github_access_token" {
  description = "GitHub personal access token (classic, scope admin:repo_hook) that Amplify uses once, at app creation, to register its webhook. Required for the first apply only; see terraform.tfvars.example."
  type        = string
  sensitive   = true
  default     = null
}

# --- Budget -------------------------------------------------------------------

variable "monthly_budget_usd" {
  description = "Monthly cost budget for the whole account, in USD."
  type        = number
  default     = 10
}

variable "budget_alert_email" {
  description = "Email address that receives budget alerts."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_alert_email))
    error_message = "budget_alert_email must be a valid email address."
  }
}
