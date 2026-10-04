resource "aws_cloudwatch_log_group" "api" {
  # Lambda's default log group name; creating it here is what gives it a
  # retention period instead of Lambda auto-creating it with none.
  name              = "/aws/lambda/${local.api_function_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api_lambda" {
  name               = "${local.api_function_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api_lambda" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }

  statement {
    sid     = "ReadSecrets"
    actions = ["ssm:GetParameter"]
    resources = [
      aws_ssm_parameter.database_url.arn,
      aws_ssm_parameter.locationiq_api_key.arn,
      aws_ssm_parameter.anthropic_api_key.arn,
      aws_ssm_parameter.openrouteservice_api_key.arn,
    ]
  }

  # The parameter is encrypted with the AWS-managed aws/ssm key, whose alias
  # does not exist in a fresh account until first use, so it cannot be looked
  # up by ARN here. The conditions scope decryption to this one parameter.
  statement {
    sid       = "DecryptSecrets"
    actions   = ["kms:Decrypt"]
    resources = ["arn:${local.partition}:kms:${var.aws_region}:${local.account_id}:key/*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:PARAMETER_ARN"
      values = [
        aws_ssm_parameter.database_url.arn,
        aws_ssm_parameter.locationiq_api_key.arn,
        aws_ssm_parameter.anthropic_api_key.arn,
        aws_ssm_parameter.openrouteservice_api_key.arn,
      ]
    }
  }
}

resource "aws_iam_role_policy" "api_lambda" {
  name   = "runtime"
  role   = aws_iam_role.api_lambda.id
  policy = data.aws_iam_policy_document.api_lambda.json
}

resource "aws_lambda_function" "api" {
  function_name = local.api_function_name
  role          = aws_iam_role.api_lambda.arn

  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "api.lambda_handler.handler"
  memory_size   = var.lambda_memory_mb
  timeout       = var.lambda_timeout_seconds

  filename = var.lambda_zip_path

  environment {
    variables = {
      DATABASE_URL_SSM_PARAM             = aws_ssm_parameter.database_url.name
      LOCATIONIQ_API_KEY_SSM_PARAM       = aws_ssm_parameter.locationiq_api_key.name
      ANTHROPIC_API_KEY_SSM_PARAM        = aws_ssm_parameter.anthropic_api_key.name
      OPENROUTESERVICE_API_KEY_SSM_PARAM = aws_ssm_parameter.openrouteservice_api_key.name
      CORS_ALLOWED_ORIGINS               = "https://${var.domain_name},https://${local.www_domain}"
      SCORING_WEIGHTS_VERSION            = var.scoring_weights_version
    }
  }

  # The zip only seeds the function. After creation the deploy workflow ships
  # code with `aws lambda update-function-code`; Terraform owns configuration.
  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }

  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy.api_lambda,
  ]
}
