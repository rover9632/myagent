import hashlib
import logging
from io import BytesIO

from qcloud_cos import CosClientError, CosConfig, CosS3Client, CosServiceError

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
COS_CONF = settings.cos_conf
COS_BUCKET = settings.cos_bucket


def upload_file(x, key=None, prefix="p", suffix=""):
    if isinstance(x, str):
        with open(x, "rb") as f:
            x = f.read()
    if not key:
        md5 = hashlib.md5(x).hexdigest()
        key = f"{md5[:3]}/{md5[3:6]}/{md5[6:9]}/{md5}"
    key = f"{prefix}/{key}{suffix}"
    try:
        client = CosS3Client(CosConfig(**COS_CONF))
        client.upload_file_from_buffer(COS_BUCKET, Key=key, Body=BytesIO(x))
        return client.get_object_url(COS_BUCKET, Key=key)
    except (CosClientError, CosServiceError) as e:
        logger.error(f"Upload to cos failed! key: {key}, exc: {e}")
    return ""


def list_files(prefix=""):
    try:
        rsp = CosS3Client(CosConfig(**COS_CONF)).list_objects(COS_BUCKET, Prefix=prefix)
        if 'Contents' in rsp:
            return [obj['Key'] for obj in rsp['Contents']]
        else:
            logger.info("Not Found !")
    except Exception as e:
        logger.error(f"List cos files failed, exc: {e}")
    return []


def download_file(key, dst_path):
    try:
        CosS3Client(CosConfig(**COS_CONF)).download_file(COS_BUCKET, key, dst_path)
        return True
    except (CosClientError, CosServiceError) as e:
        logger.error(f"Download from cos failed! key: {key}, exc: {e}")
    return False


def delete_file(key):
    try:
        CosS3Client(CosConfig(**COS_CONF)).delete_object(COS_BUCKET, key)
        return True
    except (CosClientError, CosServiceError) as e:
        logger.error(f"Delete from cos failed! key: {key}, exc: {e}")
    return False


def main(_):
    print(upload_file(b"hello world", key=None, prefix="p", suffix=".txt"))
