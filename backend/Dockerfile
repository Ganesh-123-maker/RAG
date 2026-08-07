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

# Ensure Python finds the app package
ENV PYTHONPATH=/app

EXPOSE 8000
