# The real connection string is set out-of-band (`aws ssm put-parameter
# --overwrite`). `value_wo` is write-only: Terraform sends the placeholder once
# and never reads the value back, so the secret is never written to state.
# A plain `value` with ignore_changes would not achieve that, because refresh
# decrypts the live value into state.
resource "aws_ssm_parameter" "database_url" {
  name        = "/${var.project}/${var.environment}/database_url"
  description = "Postgres connection string for the API. Value is managed outside Terraform."
  type        = "SecureString"

  value_wo         = "placeholder-set-me-with-aws-ssm-put-parameter"
  value_wo_version = 1
}

# Optional: LocationIQ key for address autocomplete. Without a real value the
# API falls back to the slower keyless Photon service. Set it out-of-band:
#   aws ssm put-parameter --name /<project>/<env>/locationiq_api_key \
#     --type SecureString --overwrite --value-from-file <file>
resource "aws_ssm_parameter" "locationiq_api_key" {
  name        = "/${var.project}/${var.environment}/locationiq_api_key"
  description = "LocationIQ API key for address autocomplete. Value is managed outside Terraform."
  type        = "SecureString"

  value_wo         = "placeholder-set-me-with-aws-ssm-put-parameter"
  value_wo_version = 1
}

# Anthropic API key for the AI explanation layer (Haiku 4.5). Without a real
# value the API serves the rule-based explanation. Set it out-of-band with
# `aws ssm put-parameter --overwrite` (never via Terraform).
resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "/${var.project}/${var.environment}/anthropic_api_key"
  description = "Anthropic API key for AI explanations. Value is managed outside Terraform."
  type        = "SecureString"

  value_wo         = "placeholder-set-me-with-aws-ssm-put-parameter"
  value_wo_version = 1
}
