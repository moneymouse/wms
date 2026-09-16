FROM python:3.10-slim

LABEL maintainer="WMS"

WORKDIR /app

# Ali ECS reaches the Aliyun Debian mirror much more reliably than the default
# Debian mirror. These remain build arguments so another environment can
# override them without editing the Dockerfile.
ARG DEBIAN_MIRROR=https://mirrors.aliyun.com/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security

# Install build dependencies for cryptography
RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
COPY requirement.txt .
RUN pip install \
        --index-url "$PIP_INDEX_URL" \
        --timeout 60 \
        --retries 5 \
        -r requirement.txt

# Copy application source
COPY . .

# Ensure runtime directories exist and entrypoint is executable
RUN mkdir -p log excels data/history data/data \
    && chmod +x docker-entrypoint.sh

EXPOSE 5000

# Use entrypoint script for migrations and startup
ENTRYPOINT ["./docker-entrypoint.sh"]
