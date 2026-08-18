resource "aws_s3_bucket" "lab" {
  bucket = local.bucket_name

  # Educational cleanup: `make destroy` must not leave a bucket behind just
  # because training wrote artifacts into it.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "lab" {
  bucket = aws_s3_bucket.lab.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lab" {
  bucket = aws_s3_bucket.lab.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Uploading through Terraform (instead of `aws s3 cp`) puts the data in the
# dependency graph: the training job cannot start before the bytes it reads exist.
resource "aws_s3_object" "train" {
  bucket = aws_s3_bucket.lab.id
  key    = "${local.s3_prefixes.train}/train.csv"
  source = "${local.data_dir}/model_train_headerless.csv"
  etag   = filemd5("${local.data_dir}/model_train_headerless.csv")

  content_type = "text/csv"
}

resource "aws_s3_object" "validation" {
  bucket = aws_s3_bucket.lab.id
  key    = "${local.s3_prefixes.validation}/validation.csv"
  source = "${local.data_dir}/model_validation_headerless.csv"
  etag   = filemd5("${local.data_dir}/model_validation_headerless.csv")

  content_type = "text/csv"
}

# Metadata travels with the data. Anyone auditing the bucket can tell which
# dataset produced which model without reading this repository.
resource "aws_s3_object" "manifest" {
  bucket = aws_s3_bucket.lab.id
  key    = "${local.s3_prefixes.metadata}/dataset_manifest.json"
  source = "${local.data_dir}/dataset_manifest.json"
  etag   = filemd5("${local.data_dir}/dataset_manifest.json")

  content_type = "application/json"
}

resource "aws_s3_object" "schema" {
  bucket = aws_s3_bucket.lab.id
  key    = "${local.s3_prefixes.metadata}/schema.json"
  source = "${path.module}/../config/schema.json"
  etag   = filemd5("${path.module}/../config/schema.json")

  content_type = "application/json"
}
