resource "aws_s3_bucket" "lab" {
  bucket = local.bucket_name

  # Educational cleanup: `make destroy` must not leave a bucket behind just
  # because training/async/batch wrote objects into it.
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

# Uploading through Terraform puts the data in the dependency graph: the
# training job cannot start before the bytes it reads exist.
resource "aws_s3_object" "train" {
  bucket = aws_s3_bucket.lab.id
  key    = "${local.s3_prefixes.train}/train.csv"
  source = "${local.data_dir}/train.csv"
  etag   = filemd5("${local.data_dir}/train.csv")

  content_type = "text/csv"
}

resource "aws_s3_object" "validation" {
  bucket = aws_s3_bucket.lab.id
  key    = "${local.s3_prefixes.validation}/validation.csv"
  source = "${local.data_dir}/validation.csv"
  etag   = filemd5("${local.data_dir}/validation.csv")

  content_type = "text/csv"
}

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
