data "aws_iam_policy_document" "amplify_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["amplify.amazonaws.com"]
    }
  }
}

# Amplify's SSR compute needs a service role to ship its runtime logs.
resource "aws_iam_role" "amplify" {
  name               = "${var.project}-amplify"
  assume_role_policy = data.aws_iam_policy_document.amplify_assume.json
}

data "aws_iam_policy_document" "amplify" {
  statement {
    sid = "WriteAmplifyLogs"

    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/amplify/*",
      "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/amplify/*:log-stream:*",
    ]
  }

  statement {
    sid       = "DescribeLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:*"]
  }
}

resource "aws_iam_role_policy" "amplify" {
  name   = "ssr-logging"
  role   = aws_iam_role.amplify.id
  policy = data.aws_iam_policy_document.amplify.json
}

resource "aws_amplify_app" "web" {
  name        = "${var.project}-web"
  description = "Next.js frontend for ${var.domain_name}"
  repository  = "https://github.com/${var.github_repository}"
  platform    = "WEB_COMPUTE"

  iam_service_role_arn = aws_iam_role.amplify.arn
  access_token         = var.github_access_token

  environment_variables = {
    AMPLIFY_MONOREPO_APP_ROOT = "web"
    NEXT_PUBLIC_API_BASE_URL  = "https://${local.api_domain}/v1"
  }

  # Node is pinned here rather than inherited from the build image default.
  # Amplify runs SSR on the same major version the build used, so this also
  # selects the runtime.
  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: web
        frontend:
          phases:
            preBuild:
              commands:
                - nvm install 24
                - nvm use 24
                - npm ci
            build:
              commands:
                - npm run build
          artifacts:
            baseDirectory: .next
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
              - .next/cache/**/*
  YAML

  # Amplify consumes the token once to register its webhook and does not keep
  # it, so it can be dropped from tfvars (and revoked) after the first apply.
  lifecycle {
    ignore_changes = [access_token]
  }
}

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.web.id
  branch_name = var.github_branch

  framework         = "Next.js - SSR"
  stage             = "PRODUCTION"
  enable_auto_build = true
}

resource "aws_amplify_domain_association" "web" {
  app_id      = aws_amplify_app.web.id
  domain_name = var.domain_name

  # Verification needs the routing records below, which need this resource's
  # outputs, so waiting here would deadlock.
  wait_for_verification = false

  certificate_settings {
    type                   = "CUSTOM"
    custom_certificate_arn = aws_acm_certificate_validation.web.certificate_arn
  }

  sub_domain {
    branch_name = aws_amplify_branch.main.branch_name
    prefix      = ""
  }

  sub_domain {
    branch_name = aws_amplify_branch.main.branch_name
    prefix      = "www"
  }
}

locals {
  # Amplify reports each target as "<prefix> CNAME <target>"; keep the target.
  amplify_dns_targets = {
    for sd in aws_amplify_domain_association.web.sub_domain :
    sd.prefix => reverse(split(" ", trimspace(sd.dns_record)))[0]
  }
}

# Cloudflare flattens a CNAME at the zone apex, so the apex can point at
# Amplify's CloudFront hostname directly.
resource "cloudflare_dns_record" "web_apex" {
  zone_id = local.cloudflare_zone_id
  name    = var.domain_name
  type    = "CNAME"
  content = local.amplify_dns_targets[""]
  ttl     = local.cloudflare_auto_ttl
  proxied = false
  comment = "Amplify frontend (Terraform)"
}

resource "cloudflare_dns_record" "web_www" {
  zone_id = local.cloudflare_zone_id
  name    = local.www_domain
  type    = "CNAME"
  content = local.amplify_dns_targets["www"]
  ttl     = local.cloudflare_auto_ttl
  proxied = false
  comment = "Amplify frontend (Terraform)"
}
