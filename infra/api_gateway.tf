resource "aws_apigatewayv2_api" "api" {
  name          = local.api_function_name
  protocol_type = "HTTP"

  disable_execute_api_endpoint = var.disable_execute_api_endpoint
}

resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# CORS is answered by the FastAPI app (CORS_ALLOWED_ORIGINS), so every method
# including OPTIONS is forwarded and no cors_configuration is set on the API.
resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

# The $default stage serves from the domain root, so the only path prefix is
# the /v1 that FastAPI itself mounts its routes under.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.api_throttle_rate_limit
    throttling_burst_limit = var.api_throttle_burst_limit
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

resource "aws_apigatewayv2_domain_name" "api" {
  domain_name = local.api_domain

  domain_name_configuration {
    # Going through the validation resource makes this wait for an issued cert.
    certificate_arn = aws_acm_certificate_validation.api.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  domain_name = aws_apigatewayv2_domain_name.api.id
  stage       = aws_apigatewayv2_stage.default.id
}

resource "cloudflare_dns_record" "api" {
  zone_id = local.cloudflare_zone_id
  name    = local.api_domain
  type    = "CNAME"
  content = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].target_domain_name
  ttl     = local.cloudflare_auto_ttl
  proxied = var.enable_edge_cache # DNS-only unless edge caching is on (edge_cache.tf)
  comment = "API Gateway custom domain (Terraform)"
}
