# Serving stage. Created only when var.deploy_serving is true, i.e. after the
# training job finished and its artifact was proven to exist in S3.
#
# The inference container is the same image that trained the model: a mismatch
# between training and serving runtimes is one of the classic ways an ML system
# breaks after "the model worked".

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

resource "aws_sagemaker_endpoint_configuration" "churn" {
  count = var.deploy_serving ? 1 : 0

  name = local.endpoint_config_name

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.churn[0].name
    initial_instance_count = 1
    instance_type          = var.instance_type
    initial_variant_weight = 1
  }
}
