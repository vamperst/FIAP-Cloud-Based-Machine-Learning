# Real-Time Endpoint: persistent instance, previsible latency, cobra 24/7.
# This resource DOES wait for InService in provider 6.60.0, so a successful
# apply here means the endpoint is actually reachable.
resource "aws_sagemaker_endpoint_configuration" "realtime" {
  count = var.deploy_serving ? 1 : 0

  name = local.realtime_endpoint_config_name

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.churn[0].name
    initial_instance_count = 1
    instance_type          = var.instance_type
    initial_variant_weight = 1
  }
}

resource "aws_sagemaker_endpoint" "realtime" {
  count = var.deploy_serving ? 1 : 0

  name                 = local.realtime_endpoint_name
  endpoint_config_name = aws_sagemaker_endpoint_configuration.realtime[0].name
}
