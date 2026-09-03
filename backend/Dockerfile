FROM mcr.microsoft.com/playwright/python:v1.62.0-noble
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
# Build context is ./backend: the golden fixtures and design tokens now live inside the service, so
# the image no longer needs the repository root and no longer drags the frontend into the context.
COPY . /app/backend
# `entra` and `storage` are baked in even though AUTH_MODE=LOCAL needs neither: the image is the
# artifact that gets promoted to production, and a deployment that sets AUTH_MODE=ENTRA or
# STORAGE_BACKEND=S3 would otherwise fail at startup on a missing dependency it cannot install.
RUN pip install --no-cache-dir -e "/app/backend[render,entra,storage]"
ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD ["sh", "/app/backend/entrypoint.sh"]
