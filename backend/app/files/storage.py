import json
from typing import Protocol

from minio import Minio
from urllib3 import PoolManager
from urllib3.util import Retry, Timeout


class ObjectStoreUnavailableError(RuntimeError):
    """Raised when the configured object-store backend cannot serve requests."""


class ObjectStore(Protocol):
    def upload(self, *, object_name: str, content: bytes, content_type: str) -> str: ...

    def delete(self, object_name: str) -> None: ...

    def check_ready(self) -> None: ...


class MinioObjectStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
        public_read: bool,
        connect_timeout_seconds: int = 5,
        read_timeout_seconds: int = 30,
        max_retries: int = 2,
    ) -> None:
        clean_endpoint = endpoint.removeprefix("http://").removeprefix("https://").rstrip("/")
        if not clean_endpoint:
            raise ValueError("MINIO_ENDPOINT 未配置")
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._public_read = public_read
        http_client = PoolManager(
            timeout=Timeout(
                connect=max(1, connect_timeout_seconds),
                read=max(1, read_timeout_seconds),
            ),
            maxsize=10,
            retries=Retry(
                total=max(0, max_retries),
                backoff_factor=0.2,
                status_forcelist=[500, 502, 503, 504],
            ),
        )
        self._client = Minio(
            clean_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            http_client=http_client,
        )

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            if self._public_read:
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{self._bucket}/*"],
                        }
                    ],
                }
                self._client.set_bucket_policy(self._bucket, json.dumps(policy))

    def upload(self, *, object_name: str, content: bytes, content_type: str) -> str:
        import io

        try:
            self._ensure_bucket()
            self._client.put_object(
                self._bucket,
                object_name,
                io.BytesIO(content),
                length=len(content),
                content_type=content_type,
            )
        except Exception as exc:
            raise ObjectStoreUnavailableError("MinIO 对象存储暂时不可用") from exc
        return f"{self._endpoint}/{self._bucket}/{object_name}"

    def delete(self, object_name: str) -> None:
        try:
            self._client.remove_object(self._bucket, object_name)
        except Exception as exc:
            raise ObjectStoreUnavailableError("MinIO 对象存储暂时不可用") from exc

    def check_ready(self) -> None:
        try:
            self._client.bucket_exists(self._bucket)
        except Exception as exc:
            raise ObjectStoreUnavailableError("MinIO 对象存储暂时不可用") from exc
