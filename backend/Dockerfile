FROM python:3.11-slim

WORKDIR /app

# System dependencies for psycopg, pdfplumber, python-docx
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Non-root runtime user (uploads dir is pre-created so the named volume
# inherits its ownership on first mount).
RUN mkdir -p /app/uploads && \
    useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app

# Ensure Python finds the app package
ENV PYTHONPATH=/app

EXPOSE 8000

USER appuser

# Runs `alembic upgrade head` then uvicorn; see entrypoint.sh.
CMD ["sh", "entrypoint.sh"]
