FROM python:3.11-slim

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy sensor code
COPY . .
COPY ../../koi_protocol ./koi_protocol
COPY ../../shared ./shared

# Create non-root user
RUN useradd -m -u 1000 koisensor && \
    chown -R koisensor:koisensor /app
USER koisensor

# Expose port (optional, for health checks)
EXPOSE 8081

# Health check
HEALTHCHECK --interval=60s --timeout=15s --start-period=10s --retries=3 \
    CMD python -c "import asyncio; from podcast_sensor import PodcastKOISensor; print('healthy')" || exit 1

# Run the podcast sensor
CMD ["python", "run_podcast_sensor.py"]