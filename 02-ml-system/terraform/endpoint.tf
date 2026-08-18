# Real-time endpoint. This resource DOES wait for InService in provider 6.60.0
# (waitEndpointInService), so a successful apply here means the capability is
# actually reachable - unlike the training job resource.
#
# This is the only continuously billed resource in the lab. `make destroy` and
# `make verify-clean` exist because of this line.
resource "aws_sagemaker_endpoint" "churn" {
  count = var.deploy_serving ? 1 : 0

  name                 = local.endpoint_name
  endpoint_config_name = aws_sagemaker_endpoint_configuration.churn[0].name
}
