FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
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
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import asyncio; from website_sensor import WebsiteKOISensor; print('healthy')" || exit 1

# Run the website sensor
CMD ["python", "run_website_sensor.py"]