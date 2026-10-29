import os

try:
    import boto3
except Exception:
    boto3 = None


class S3Storage:
    def __init__(self):
        self.endpoint = os.getenv("S3_ENDPOINT")
        self.bucket = os.getenv("S3_BUCKET")
        self.key = os.getenv("S3_KEY")
        self.secret = os.getenv("S3_SECRET")
        if boto3 is None:
            raise RuntimeError("boto3 not installed")  # noqa: B904
        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.key,
            aws_secret_access_key=self.secret,
        )

    def put(self, data, content_type, owner):
        import hashlib

        sha = hashlib.sha256(data).hexdigest()
        storage_key = sha + ".webp"
        self.client.put_object(
            Bucket=self.bucket, Key=storage_key, Body=data, ContentType=content_type
        )
        return None

    def get(self, media_id):
        raise NotImplementedError("resolve via DB")  # noqa: B904

    def delete(self, media_id):
        pass
