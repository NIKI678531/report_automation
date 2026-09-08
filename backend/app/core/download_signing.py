"""Short-lived download grants, independent of any file storage backend."""
import hashlib
import hmac
import json
import re
import time

from .config import settings


def sign(resource: str, subject: str, expires_at: int) -> str:
    message = json.dumps([resource, subject, expires_at], separators=(",", ":")).encode()
    return hmac.new(settings.download_secret.encode(), message, hashlib.sha256).hexdigest()


def verify(resource: str, subject: str, expires_at: int, signature: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{64}", signature)) and expires_at >= int(time.time()) and hmac.compare_digest(signature, sign(resource, subject, expires_at))
