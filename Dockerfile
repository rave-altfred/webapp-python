# syntax=docker/dockerfile:1.4
# Multi-stage build for Flask webapp
FROM python:3.11-slim as deps

# Set working directory
WORKDIR /app

# Install system dependencies with cache mount for faster rebuilds
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Create virtual environment and install dependencies with pip cache
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt

ENV PATH="/opt/venv/bin:$PATH"

# Production stage
FROM python:3.11-slim as production

# Install runtime dependencies with cache mount
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl

# Create non-root user
RUN groupadd -r webapp && useradd -r -g webapp webapp

# Set working directory
WORKDIR /app

# Copy virtual environment from deps stage
COPY --from=deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application files
COPY app.py .
COPY production.config.json .
COPY templates/ templates/
COPY schema.sql .

# Create necessary directories
RUN mkdir -p logs && \
    chown -R webapp:webapp /app

# Switch to non-root user
USER webapp

# Add metadata labels at the end to avoid cache invalidation
ARG BUILD_DATE
ARG VERSION
ARG VCS_REF

LABEL org.label-schema.build-date=$BUILD_DATE \
      org.label-schema.name="Database Statistics Dashboard" \
      org.label-schema.description="Flask webapp for monitoring Valkey and PostgreSQL databases" \
      org.label-schema.version=$VERSION \
      org.label-schema.vcs-ref=$VCS_REF \
      org.label-schema.vcs-url="https://github.com/altfred/webapp-python" \
      org.label-schema.schema-version="1.0"

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Use gunicorn for production
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "4", \
     "--worker-class", "sync", \
     "--timeout", "30", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--preload", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "app:app"]
