FROM mcr.microsoft.com/playwright/python:v1.62.0-noble
WORKDIR /app
# Build context is ./backend: the golden fixtures and design tokens now live inside the service, so
# the image no longer needs the repository root and no longer drags the frontend into the context.
COPY . /app/backend
RUN pip install --no-cache-dir -e "/app/backend[render]"
ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD ["sh", "/app/backend/entrypoint.sh"]
