# Certificate for the API Gateway regional custom domain. Must live in the
# same region as the API.
resource "aws_acm_certificate" "api" {
  domain_name       = local.api_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "cloudflare_dns_record" "api_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.api.domain_validation_options : dvo.domain_name => {
      name   = trimsuffix(dvo.resource_record_name, ".")
      type   = dvo.resource_record_type
      record = trimsuffix(dvo.resource_record_value, ".")
    }
  }

  zone_id = local.cloudflare_zone_id
  name    = each.value.name
  type    = each.value.type
  content = each.value.record
  ttl     = local.cloudflare_auto_ttl
  proxied = false
  comment = "ACM validation (Terraform)"
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for r in cloudflare_dns_record.api_cert_validation : r.name]
}

# Certificate for the Amplify custom domain. Amplify serves through CloudFront,
# so this one is pinned to us-east-1 regardless of var.aws_region.
resource "aws_acm_certificate" "web" {
  region = "us-east-1"

  domain_name               = var.domain_name
  subject_alternative_names = [local.www_domain]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "cloudflare_dns_record" "web_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.web.domain_validation_options : dvo.domain_name => {
      name   = trimsuffix(dvo.resource_record_name, ".")
      type   = dvo.resource_record_type
      record = trimsuffix(dvo.resource_record_value, ".")
    }
  }

  zone_id = local.cloudflare_zone_id
  name    = each.value.name
  type    = each.value.type
  content = each.value.record
  ttl     = local.cloudflare_auto_ttl
  proxied = false
  comment = "ACM validation (Terraform)"
}

resource "aws_acm_certificate_validation" "web" {
  region = "us-east-1"

  certificate_arn         = aws_acm_certificate.web.arn
  validation_record_fqdns = [for r in cloudflare_dns_record.web_cert_validation : r.name]
}
