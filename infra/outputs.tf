output "cloudflare_zone_id" {
  description = "Cloudflare zone that holds every DNS record for the domain."
  value       = local.cloudflare_zone_id
}

output "api_base_url" {
  description = "Public base URL of the API, including the /v1 prefix the app serves."
  value       = "https://${local.api_domain}/v1"
}

output "api_execute_url" {
  description = "Generated API Gateway URL (no custom domain). Append /v1. Unreachable once disable_execute_api_endpoint is true."
  value       = aws_apigatewayv2_api.api.api_endpoint
}

output "api_gateway_target_domain" {
  description = "Regional API Gateway hostname that api.<domain> aliases to."
  value       = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].target_domain_name
}

output "lambda_function_name" {
  description = "Name of the API Lambda function."
  value       = aws_lambda_function.api.function_name
}

output "database_url_ssm_parameter" {
  description = "SSM parameter to populate with the real database URL."
  value       = aws_ssm_parameter.database_url.name
}

output "github_deploy_role_arn" {
  description = "Store as the GitHub repository variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.github_deploy.arn
}

output "amplify_app_id" {
  description = "Amplify app ID, e.g. for `aws amplify start-job`."
  value       = aws_amplify_app.web.id
}

output "amplify_default_domain" {
  description = "Amplify-generated hostname for the production branch, usable before the custom domain is live."
  value       = "https://${aws_amplify_branch.main.branch_name}.${aws_amplify_app.web.default_domain}"
}

output "amplify_dns_targets" {
  description = "CloudFront targets Amplify assigned to the apex and www hostnames."
  value       = local.amplify_dns_targets
}
