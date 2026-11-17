# Example Terraform file for radea iac-review demo.
# Contains intentional issues for RADEA to flag.

resource "aws_iam_role" "lambda_exec" {
  name = "lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name   = "lambda-policy"
  role   = aws_iam_role.lambda_exec.id

  # Intentionally over-permissive — RADEA should flag this
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}

resource "aws_s3_bucket" "assets" {
  bucket = "my-app-assets"
}

# Missing: server_side_encryption_configuration — RADEA should flag this
# Missing: aws_s3_bucket_public_access_block     — RADEA should flag this

resource "aws_lambda_function" "api" {
  function_name = "my-api"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "function.zip"
}
