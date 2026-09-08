# syntax=docker/dockerfile:1.7
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp \
    TZ=Asia/Hong_Kong \
    AUTH_MODE=REMOTE \
    TASK_MODE=EAGER
WORKDIR /app/backend
# Calibri-compatible Carlito and both Noto packages are the existing report font contract.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tini tzdata \
      fonts-crosextra-carlito fonts-noto-cjk fonts-noto-cjk-extra \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 commentary \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin commentary
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
 && python -c "import tomllib; p=tomllib.load(open('pyproject.toml','rb'))['project']; print(*p['dependencies'], *[d for e in ('render','entra') for d in p['optional-dependencies'][e]], sep=chr(10))" > /tmp/requirements-check.txt \
 && pip install --no-index --no-deps -r /tmp/requirements-check.txt \
 && pip check \
 && rm /tmp/requirements-check.txt \
 && python -m playwright install --with-deps chromium \
 && chmod -R a+rX /ms-playwright \
 && rm -rf /var/lib/apt/lists/*
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini entrypoint.sh ./
RUN chmod 0555 entrypoint.sh \
 && python -c "import ssl; ssl.create_default_context(cafile='app/integrations/certs/aws-rds-ap-east-1.pem')"
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--", "sh", "/app/backend/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "210"]
