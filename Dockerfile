# ─────────────────────────────────────────────────────────────────────────────
# Ghost Data Still Exists — Dockerfile
# Supports CLI pipeline run (default) or FastAPI server (CMD ["api"])
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY code/ ./code/
COPY server.py ./
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# Default mount points
VOLUME ["/app/dataset", "/app/code/runs"]

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["cli"]
