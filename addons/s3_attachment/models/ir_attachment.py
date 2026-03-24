import os
import logging
import boto3
from botocore.exceptions import ClientError
from odoo import models

_logger = logging.getLogger(__name__)

S3_BUCKET = os.environ.get("AWS_S3_BUCKET")
S3_REGION = os.environ.get("AWS_REGION", "us-east-2")
AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")


def _s3_enabled():
    return bool(S3_BUCKET)


def _get_client():
    return boto3.client(
        "s3",
        region_name=S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY or None,
        aws_secret_access_key=AWS_SECRET_KEY or None,
    )


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _file_write(self, bin_data, checksum):
        if not _s3_enabled():
            return super()._file_write(bin_data, checksum)
        try:
            _get_client().put_object(
                Bucket=S3_BUCKET,
                Key=checksum,
                Body=bin_data,
            )
            _logger.debug("S3: uploaded %s to bucket %s", checksum, S3_BUCKET)
            return checksum
        except ClientError:
            _logger.exception("S3: upload failed for %s, falling back to filesystem", checksum)
            return super()._file_write(bin_data, checksum)

    def _file_read(self, fname):
        if not _s3_enabled():
            return super()._file_read(fname)
        try:
            obj = _get_client().get_object(Bucket=S3_BUCKET, Key=fname)
            return obj["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                # File not in S3, try local filesystem (migration scenario)
                return super()._file_read(fname)
            _logger.exception("S3: read failed for %s", fname)
            raise

    def _file_delete(self, fname):
        if not _s3_enabled():
            return super()._file_delete(fname)
        try:
            _get_client().delete_object(Bucket=S3_BUCKET, Key=fname)
            _logger.debug("S3: deleted %s from bucket %s", fname, S3_BUCKET)
        except ClientError:
            _logger.exception("S3: delete failed for %s", fname)
