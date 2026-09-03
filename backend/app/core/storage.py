"""The object-storage port and the two backends that implement it.

A `storage_key` reaches this module from the database, so it is untrusted input: `..` inside one
must not walk out of the object root or out of the bucket prefix. Downloads are handed out as HMAC
signatures rather than paths, and a signature is bound to one artifact, one subject and one
deadline — a link copied to a colleague is not a second grant.

`LOCAL` writes to `var/output` and is for workstations and UAT. Production runs `S3`: the
deployment provides no persistent volume, so an artifact on container-local disk is lost at the
next restart and invisible to every other replica. `Settings.deployment_problems()` refuses to
start a non-LOCAL process on `LOCAL` storage for exactly that reason.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ConfigurationError, SUPPORTED_STORAGE_BACKENDS, settings

# Large enough that a report-sized PDF is a handful of reads, small enough that a download never
# holds the whole artifact in memory.
_CHUNK_BYTES = 64 * 1024
# What an S3-compatible vendor calls "that key is not here". TOS, MinIO and AWS disagree on which
# of these they return, and a missing object is a 404 to the caller, not a 500.
_MISSING_OBJECT_CODES = {"NoSuchKey", "NoSuchBucket", "NotFound", "404"}


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    checksum: str


@dataclass(frozen=True)
class ObjectBody:
    """A stored object opened for delivery: the byte stream plus the length to advertise."""

    chunks: Iterator[bytes]
    size_bytes: int


def _iter_file(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            yield chunk


class _SignedDownloads:
    """Download signing, identical for every backend because it protects the link, not the store."""

    def sign(self, artifact_id: str, subject: str, expires_at: int) -> str:
        message = f"{artifact_id}:{subject}:{expires_at}".encode()
        return hmac.new(settings.download_secret.encode(), message, hashlib.sha256).hexdigest()

    def verify(self, artifact_id: str, subject: str, expires_at: int, signature: str) -> bool:
        return expires_at >= int(time.time()) and hmac.compare_digest(
            signature, self.sign(artifact_id, subject, expires_at)
        )


class LocalObjectStorage(_SignedDownloads):
    """Filesystem implementation of the object-storage port, used on workstations and in UAT."""

    backend = "LOCAL"

    def __init__(self, root: Path):
        self.root = root.resolve()

    def put_file(self, source: Path, key: str) -> StoredObject:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("Storage key escapes the configured object root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target:
            target.write_bytes(source.read_bytes())
        data = target.read_bytes()
        return StoredObject(key=key.replace("\\", "/"), size_bytes=len(data), checksum=hashlib.sha256(data).hexdigest())

    def resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents or not path.is_file():
            raise FileNotFoundError(key)
        return path

    def open(self, key: str) -> ObjectBody:
        path = self.resolve(key)
        return ObjectBody(chunks=_iter_file(path), size_bytes=path.stat().st_size)


def _object_key(prefix: str, key: str) -> str:
    """Place `key` under `prefix`, refusing one that would address a different object.

    S3 has no filesystem to resolve `..` against, so a key containing one is not caught by the
    store — it simply names a different object, potentially another environment's.
    """
    candidate = key.replace("\\", "/")
    # An empty segment is a leading, trailing or doubled slash: on S3 that is a *different* object
    # from the one the database recorded, so it is refused rather than quietly normalised away.
    if not candidate or any(segment in ("", ".", "..") for segment in candidate.split("/")):
        raise ValueError(f"Storage key escapes the configured object root: {key!r}")
    return f"{prefix}/{candidate}" if prefix else candidate


def _is_missing_object(error: Exception) -> bool:
    code = getattr(error, "response", {}).get("Error", {}).get("Code") if hasattr(error, "response") else None
    return str(code) in _MISSING_OBJECT_CODES


def _build_client() -> Any:
    """Construct the boto3 client from settings, naming the extra to install if it is absent."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError as error:
        raise ConfigurationError(
            'STORAGE_BACKEND=S3 needs the boto3 client. Install it with: pip install -e "./backend[storage]"'
        ) from error
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        region_name=settings.s3_region or None,
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
        config=Config(s3={"addressing_style": settings.s3_addressing_style}),
    )


class S3ObjectStorage(_SignedDownloads):
    """S3-compatible object storage — Volcengine TOS, MinIO and AWS S3 all speak this API.

    The client is built on first use rather than in `__init__`, so importing this module never
    requires boto3 and a test can inject a stub: there is no S3 endpoint in the test environment,
    and a backend that is only exercised in production is a backend nobody has exercised.
    """

    backend = "S3"

    def __init__(self, bucket: str, prefix: str = "", client: Any | None = None):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _build_client()
        return self._client

    def put_file(self, source: Path, key: str) -> StoredObject:
        object_key = _object_key(self.prefix, key)
        digest = hashlib.sha256()
        size = 0
        # Hashed in a streaming pass so a large artifact is never held whole, and handed to the
        # client as a file object so boto3 can decide on its own whether to use multipart.
        with source.open("rb") as handle:
            while chunk := handle.read(_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
        with source.open("rb") as handle:
            self.client.put_object(Bucket=self.bucket, Key=object_key, Body=handle)
        return StoredObject(key=key.replace("\\", "/"), size_bytes=size, checksum=digest.hexdigest())

    def open(self, key: str) -> ObjectBody:
        object_key = _object_key(self.prefix, key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        except Exception as error:
            if _is_missing_object(error):
                raise FileNotFoundError(key) from error
            raise
        body = response["Body"]
        chunks = body.iter_chunks(_CHUNK_BYTES) if hasattr(body, "iter_chunks") else iter([body.read()])
        return ObjectBody(chunks=chunks, size_bytes=int(response.get("ContentLength", 0)))


def build_storage() -> LocalObjectStorage | S3ObjectStorage:
    """Return the backend named by STORAGE_BACKEND, refusing a name nothing implements."""
    if settings.storage_backend == "LOCAL":
        return LocalObjectStorage(settings.output_root)
    if settings.storage_backend == "S3":
        if not settings.s3_bucket:
            raise ConfigurationError("STORAGE_BACKEND=S3 requires S3_BUCKET; there is nowhere to write.")
        return S3ObjectStorage(settings.s3_bucket, settings.s3_prefix)
    raise ConfigurationError(
        f"STORAGE_BACKEND={settings.storage_backend!r} is not implemented "
        f"(supported: {', '.join(SUPPORTED_STORAGE_BACKENDS)}). An unrecognised value used to fall "
        "through to local disk without a word, so a deployment looked configured and stored nothing."
    )


storage = build_storage()
