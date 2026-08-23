# The one Model every serving mode below points to. "One model, four ways to
# consume it" only holds if the three EndpointConfigs all reference this same
# resource - never a per-mode copy of the artifact.
resource "aws_sagemaker_model" "churn" {
  count = var.deploy_serving ? 1 : 0

  name               = local.model_name
  execution_role_arn = data.aws_iam_role.lab_role.arn

  primary_container {
    image          = var.training_image
    model_data_url = var.model_artifact_uri
  }

  lifecycle {
    precondition {
      condition     = var.model_artifact_uri != ""
      error_message = "model_artifact_uri is empty. Run `make apply`, which resolves it from DescribeTrainingJob before deploying."
    }
  }
}
