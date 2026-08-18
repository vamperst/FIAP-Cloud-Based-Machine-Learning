# SageMaker training job.
#
# Two behaviours of this resource in provider 6.60.0 shape the whole design and
# are documented in docs/adr/0001-artifact-uri-resolution.md:
#   1. create returns as soon as the job reaches InProgress - it does NOT wait
#      for Completed, so a green apply is not a trained model;
#   2. it exports only `arn` and `tags_all` - there is no computed artifact URI.
# Hence the artifact is resolved out-of-band by scripts/wait_training.py.
#
# `s3_data_distribution_type` is set explicitly on every channel: when omitted,
# provider 6.60.0 sends "ShardedByS3Key" (verified with DescribeTrainingJob) and
# then fails the apply with "Provider produced inconsistent result after apply".
# The AWS API default is "FullyReplicated", which is what a single-instance job
# training on the whole dataset actually needs.
resource "aws_sagemaker_training_job" "churn" {
  training_job_name = local.training_job_name
  role_arn          = data.aws_iam_role.lab_role.arn

  hyper_parameters = var.hyperparameters

  # Left disabled to match the Academy preflight that is known to work.
  enable_network_isolation = false

  algorithm_specification {
    training_image      = var.training_image
    training_input_mode = "File"
  }

  input_data_config {
    channel_name = "train"
    content_type = "text/csv"
    input_mode   = "File"

    data_source {
      s3_data_source {
        s3_data_type              = "S3Prefix"
        s3_uri                    = local.train_channel_uri
        s3_data_distribution_type = "FullyReplicated"
      }
    }
  }

  input_data_config {
    channel_name = "validation"
    content_type = "text/csv"
    input_mode   = "File"

    data_source {
      s3_data_source {
        s3_data_type              = "S3Prefix"
        s3_uri                    = local.validation_channel_uri
        s3_data_distribution_type = "FullyReplicated"
      }
    }
  }

  output_data_config {
    s3_output_path = local.training_output_uri
  }

  resource_config {
    instance_count    = 1
    instance_type     = var.instance_type
    volume_size_in_gb = var.volume_size_in_gb
  }

  stopping_condition {
    max_runtime_in_seconds = var.max_runtime_in_seconds
  }

  depends_on = [
    aws_s3_object.train,
    aws_s3_object.validation,
  ]
}
