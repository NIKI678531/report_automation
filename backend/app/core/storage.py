from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    checksum: str


class LocalObjectStorage:
    """Filesystem implementation of the object-storage port used in local/UAT."""

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

    def sign(self, artifact_id: str, subject: str, expires_at: int) -> str:
        message = f"{artifact_id}:{subject}:{expires_at}".encode()
        return hmac.new(settings.download_secret.encode(), message, hashlib.sha256).hexdigest()

    def verify(self, artifact_id: str, subject: str, expires_at: int, signature: str) -> bool:
        return expires_at >= int(time.time()) and hmac.compare_digest(signature, self.sign(artifact_id, subject, expires_at))


storage = LocalObjectStorage(settings.output_root)
