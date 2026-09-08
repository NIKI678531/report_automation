"""Application logs to stdout; retain failed probes and redact signed URL queries."""

import logging
import os
import sys


class AccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) != 5:
            return True
        client, method, path, version, status = record.args
        path = str(path).split("?", 1)[0]
        record.args = (client, method, path, version, status)
        return not (method in {"GET", "HEAD"} and path == "/api/v1/health" and status == 200)


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Client libraries log full URLs at INFO/DEBUG (including signed object-store URLs).
    # Enabling application INFO must not also expose provider query credentials.
    for name in ("httpx", "httpcore", "botocore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessLogFilter) for item in access.filters):
        access.addFilter(AccessLogFilter())
