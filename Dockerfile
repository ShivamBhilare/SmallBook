# ==============================================================================
# SmallBook Multi-Service Container Image
# ==============================================================================
FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered output logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

# Install system utilities needed for building packages, SSL, and network healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv directly from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency configuration first to leverage Docker layer caching
COPY pyproject.toml ./

# Install project dependencies into system environment using uv
RUN uv pip install --system -r pyproject.toml

# Copy application source code
COPY app/ ./app/
COPY main.py ./

# Expose web application port
EXPOSE 8000

# Default command for the web service (overridden by celery service in compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
