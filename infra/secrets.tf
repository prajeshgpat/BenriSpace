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
