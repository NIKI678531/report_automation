FROM mcr.microsoft.com/playwright/python:v1.62.0-noble
WORKDIR /app
COPY services/api /app/services/api
COPY tests /app/tests
COPY packages /app/packages
COPY output /app/output
RUN pip install --no-cache-dir -e "/app/services/api[render]"
ENV PYTHONPATH=/app/services/api
EXPOSE 8000
CMD ["sh", "/app/services/api/entrypoint.sh"]
