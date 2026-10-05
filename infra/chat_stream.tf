# Streaming chat (POST /v1/chat/stream) over a Lambda function URL.
#
# API Gateway HTTP APIs buffer the whole response, so the streamed frames would
# arrive together at the end. A function URL in RESPONSE_STREAM mode sends them
# as they are produced. Python has no native streaming handler, so this second
# function runs the same FastAPI app under uvicorn behind the AWS Lambda Web
# Adapter layer. NOT APPLIED: everything here is off until
# chat_stream_enabled = true. See docs/ARCHITECTURE.md, "Chat streaming".

variable "chat_stream_enabled" {
  description = "Create the streaming chat function and its function URL."
  type        = bool
  default     = false
}

variable "chat_stream_adapter_layer_arn" {
  description = "ARN of the AWS Lambda Web Adapter layer for arm64 in this region (see the aws-lambda-web-adapter README for the current version)."
  type        = string
  default     = ""

  validation {
    condition     = var.chat_stream_adapter_layer_arn == "" || can(regex("^arn:aws[a-z-]*:lambda:", var.chat_stream_adapter_layer_arn))
    error_message = "chat_stream_adapter_layer_arn must be a Lambda layer ARN."
  }
}

variable "chat_stream_timeout_seconds" {
  description = "Timeout of the streaming function. A function URL is not bound by API Gateway's 30s limit."
  type        = number
  default     = 60
}

locals {
  chat_stream_function_name = "${local.api_function_name}-chat-stream"
}

resource "aws_cloudwatch_log_group" "chat_stream" {
  count             = var.chat_stream_enabled ? 1 : 0
  name              = "/aws/lambda/${local.chat_stream_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "chat_stream" {
  count         = var.chat_stream_enabled ? 1 : 0
  function_name = local.chat_stream_function_name
  role          = aws_iam_role.api_lambda.arn

  runtime       = "python3.12"
  architectures = ["arm64"]
  # The Web Adapter wrapper runs this script instead of a Python handler.
  handler     = "api/run_stream.sh"
  memory_size = var.lambda_memory_mb
  timeout     = var.chat_stream_timeout_seconds
  layers      = [var.chat_stream_adapter_layer_arn]

  filename = var.lambda_zip_path

  environment {
    variables = {
      AWS_LAMBDA_EXEC_WRAPPER            = "/opt/bootstrap"
      AWS_LWA_INVOKE_MODE                = "response_stream"
      AWS_LWA_READINESS_CHECK_PATH       = "/v1/sources"
      PORT                               = "8000"
      PYTHONPATH                         = "/var/task"
      DATABASE_URL_SSM_PARAM             = aws_ssm_parameter.database_url.name
      LOCATIONIQ_API_KEY_SSM_PARAM       = aws_ssm_parameter.locationiq_api_key.name
      ANTHROPIC_API_KEY_SSM_PARAM        = aws_ssm_parameter.anthropic_api_key.name
      OPENROUTESERVICE_API_KEY_SSM_PARAM = aws_ssm_parameter.openrouteservice_api_key.name
      CORS_ALLOWED_ORIGINS               = "https://${var.domain_name},https://${local.www_domain}"
      SCORING_WEIGHTS_VERSION            = var.scoring_weights_version
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }

  depends_on = [
    aws_cloudwatch_log_group.chat_stream,
    aws_iam_role_policy.api_lambda,
  ]
}

resource "aws_lambda_function_url" "chat_stream" {
  count              = var.chat_stream_enabled ? 1 : 0
  function_name      = aws_lambda_function.chat_stream[0].function_name
  authorization_type = "NONE"
  invoke_mode        = "RESPONSE_STREAM"

  cors {
    allow_origins = ["https://${var.domain_name}", "https://${local.www_domain}"]
    allow_methods = ["POST"]
    allow_headers = ["content-type"]
    max_age       = 86400
  }
}

output "chat_stream_url" {
  description = "Set NEXT_PUBLIC_CHAT_STREAM_URL to this value plus v1/chat/stream (empty while chat_stream_enabled is false)."
  value       = var.chat_stream_enabled ? aws_lambda_function_url.chat_stream[0].function_url : ""
}
