FROM python:3.10-slim

LABEL maintainer="WMS"

WORKDIR /app

# Install build dependencies for cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirement.txt .
RUN pip install -r requirement.txt

# Copy application source
COPY . .

# Ensure runtime directories exist and entrypoint is executable
RUN mkdir -p log excels data/history data/data \
    && chmod +x docker-entrypoint.sh

EXPOSE 5000

# Use entrypoint script for migrations and startup
ENTRYPOINT ["./docker-entrypoint.sh"]
