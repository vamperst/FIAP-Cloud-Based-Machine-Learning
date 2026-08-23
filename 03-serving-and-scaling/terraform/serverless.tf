# Serverless Inference: same artifact and image, no persistent instance. AWS
# manages capacity; the lab measures (not promises) first-request/cold
# behaviour in `make compare`.
resource "aws_sagemaker_endpoint_configuration" "serverless" {
  count = var.deploy_serving ? 1 : 0

  name = local.serverless_endpoint_config_name

  production_variants {
    variant_name = "AllTraffic"
    model_name   = aws_sagemaker_model.churn[0].name

    serverless_config {
      max_concurrency   = var.serverless_max_concurrency
      memory_size_in_mb = var.serverless_memory_size_in_mb
    }
  }
}

resource "aws_sagemaker_endpoint" "serverless" {
  count = var.deploy_serving ? 1 : 0

  name                 = local.serverless_endpoint_name
  endpoint_config_name = aws_sagemaker_endpoint_configuration.serverless[0].name
}
