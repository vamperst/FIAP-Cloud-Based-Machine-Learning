variable "region" {
  description = "AWS region. The Academy Learner Lab, and the XGBoost image URI used here, are validated only in us-east-1."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.region == "us-east-1"
    error_message = "This lab is validated only in us-east-1."
  }
}

variable "project_prefix" {
  description = "Short semantic prefix for every resource name. Mirrored in config/lab.yaml."
  type        = string
  default     = "prb-cloud-ml-lab2"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,32}$", var.project_prefix))
    error_message = "Prefix must be lowercase letters, digits and hyphens (S3 and SageMaker naming)."
  }
}

variable "execution_role_name" {
  description = "Pre-provisioned Academy role. The lab is not allowed to create IAM roles."
  type        = string
  default     = "LabRole"
}

variable "data_dir" {
  description = "Directory holding the generated dataset uploaded to S3."
  type        = string
  default     = "../artifacts/data"
}

variable "training_image" {
  description = "Managed SageMaker built-in XGBoost image. Training and all three serving modes share it."
  type        = string
  default     = "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-xgboost:1.7-1"
}

variable "instance_type" {
  description = "Instance type for training, real-time and async variants."
  type        = string
  default     = "ml.m5.large"
}

variable "volume_size_in_gb" {
  description = "Training EBS volume."
  type        = number
  default     = 30
}

variable "max_runtime_in_seconds" {
  description = "Hard stop for the training job, so a hung run cannot drain the lab budget."
  type        = number
  default     = 900

  validation {
    condition     = var.max_runtime_in_seconds >= 600 && var.max_runtime_in_seconds <= 900
    error_message = "Keep the stopping condition between 600 and 900 seconds."
  }
}

variable "hyperparameters" {
  description = "Built-in XGBoost hyperparameters. Values are strings, as the API requires."
  type        = map(string)
  default = {
    objective        = "binary:logistic"
    eval_metric      = "auc"
    num_round        = "50"
    max_depth        = "4"
    eta              = "0.10"
    subsample        = "0.90"
    colsample_bytree = "0.90"
    verbosity        = "1"
  }
}

# --------------------------------------------------------------------------- #
# Two-stage handoff (same pattern validated in 02-ml-system)
# --------------------------------------------------------------------------- #

variable "deploy_serving" {
  description = <<-EOT
    Stage gate. False creates storage + training only; true additionally
    creates the Model and the three EndpointConfigs/Endpoints + autoscaling.
    `make apply` flips it automatically once the artifact has been proven.
  EOT
  type        = bool
  default     = false
}

variable "model_artifact_uri" {
  description = <<-EOT
    Authoritative S3 URI of model.tar.gz, taken from DescribeTrainingJob by
    scripts/lab.py wait-training and written to artifact.auto.tfvars.json.
    Never a path assembled by hand.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.model_artifact_uri == "" || can(regex("^s3://[a-z0-9.-]+/.+\\.tar\\.gz$", var.model_artifact_uri))
    error_message = "model_artifact_uri must be empty or an s3:// URI ending in .tar.gz."
  }
}

# --------------------------------------------------------------------------- #
# Real-Time Endpoint + Application Auto Scaling
# --------------------------------------------------------------------------- #

variable "realtime_min_capacity" {
  type    = number
  default = 1
}

variable "realtime_max_capacity" {
  type    = number
  default = 2
}

variable "realtime_target_invocations_per_instance" {
  description = "Target for SageMakerVariantInvocationsPerInstance target tracking."
  type        = number
  default     = 60
}

variable "realtime_scale_out_cooldown" {
  type    = number
  default = 60
}

variable "realtime_scale_in_cooldown" {
  type    = number
  default = 180
}

# --------------------------------------------------------------------------- #
# Serverless Inference
# --------------------------------------------------------------------------- #

variable "serverless_memory_size_in_mb" {
  type    = number
  default = 2048
}

variable "serverless_max_concurrency" {
  type    = number
  default = 5
}

# --------------------------------------------------------------------------- #
# Asynchronous Inference + Application Auto Scaling (0-1)
# --------------------------------------------------------------------------- #

variable "async_max_concurrent_invocations_per_instance" {
  type    = number
  default = 1
}

variable "async_min_capacity" {
  type    = number
  default = 0
}

variable "async_max_capacity" {
  type    = number
  default = 1
}

variable "async_target_backlog_per_instance" {
  description = "Target for the ApproximateBacklogSizePerInstance target-tracking policy."
  type        = number
  default     = 5
}
