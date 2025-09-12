# KOI Scheduling & Automation System

## Overview

The KOI Scheduling & Automation System provides automated triggers and job management for the content pipeline. It ensures daily content generation and weekly digest creation run reliably at scheduled times with comprehensive monitoring and error recovery.

## Components

### 1. Daily Scheduler (`daily_scheduler.py`)
The main orchestration component that manages cron-based job scheduling.

**Features:**
- Cron expression support for flexible scheduling
- Timezone-aware execution (default: America/New_York)
- Job retry logic with exponential backoff
- Graceful shutdown handling
- Integration with Daily Curator and X Bot

**Default Schedule:**
- **Daily Content**: 12:00 ET on weekdays (Monday-Friday)
- **Weekly Digest**: 14:00 ET on Fridays
- **Health Checks**: Every 5 minutes

### 2. Job Queue (`job_queue.py`)
Persistent job queue system with SQLite backend for reliable job execution.

**Features:**
- Priority-based job execution (LOW, NORMAL, HIGH, CRITICAL)
- Persistent storage with SQLite
- Concurrent worker processing
- Automatic retry with configurable limits
- Job state tracking (QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)

### 3. Monitoring System (`monitoring.py`)
Comprehensive monitoring with metrics collection and alerting.

**Features:**
- Real-time metrics collection
- Configurable threshold alerts
- Health check framework
- REST API for metrics and status
- External alert integration (webhooks, email)

**API Endpoints:**
- `GET /health` - System health status
- `GET /metrics` - Current metrics
- `GET /alerts` - Active alerts
- `GET /stats` - System statistics
- `POST /alert/resolve/{alert_id}` - Resolve an alert

## Installation

### Prerequisites
```bash
# Required Python packages
pip install schedule pytz loguru aiohttp fastapi uvicorn psutil pyyaml
```

### Configuration

The system uses the main curator configuration file at `koi-processor/config/curator_config.yaml`:

```yaml
scheduler:
  daily_cron: "0 12 * * 1-5"     # 12:00 ET weekdays
  weekly_cron: "0 14 * * 5"      # 14:00 ET Fridays
  timezone: "America/New_York"

alerts:
  enabled: true
  webhook: "https://hooks.slack.com/services/..."  # Optional
  email:
    enabled: false
    smtp_server: "smtp.gmail.com"
    recipients: ["team@example.com"]

monitoring:
  health_check_interval: 300  # 5 minutes
  metrics_port: 8200
  collection_interval: 60      # seconds

thresholds:
  "system.cpu.usage":
    max: 90  # Alert if CPU > 90%
  "system.memory.usage":
    max: 85  # Alert if memory > 85%
  "system.disk.usage":
    max: 90  # Alert if disk > 90%
```

## Usage

### Running the Scheduler

```python
# Start as standalone service
python scheduler/daily_scheduler.py

# Or import and use programmatically
from scheduler.daily_scheduler import DailyScheduler

scheduler = DailyScheduler()
scheduler.start()

# Keep running
while True:
    time.sleep(60)
    status = scheduler.get_status()
    print(f"Jobs run: {status['statistics']['total_jobs_run']}")

# Graceful shutdown
scheduler.stop()
```

### Using the Job Queue

```python
from scheduler.job_queue import JobQueue, JobPriority
import asyncio

async def main():
    # Initialize queue
    queue = JobQueue()
    
    # Register job handler
    async def process_content(payload):
        # Process the content
        print(f"Processing: {payload}")
        return {"status": "success"}
    
    queue.register_handler("content_processing", process_content)
    
    # Start workers
    await queue.start()
    
    # Enqueue jobs
    job_id = await queue.enqueue(
        "content_processing",
        {"content": "data"},
        priority=JobPriority.HIGH
    )
    
    # Check status
    status = await queue.get_job_status(job_id)
    print(f"Job status: {status['state']}")
    
    # Get statistics
    stats = await queue.get_queue_stats()
    print(f"Queue stats: {stats}")
    
    # Stop queue
    await queue.stop()

asyncio.run(main())
```

### Monitoring Integration

```python
from scheduler.monitoring import MonitoringSystem, AlertLevel
import asyncio

async def main():
    # Initialize monitoring
    monitor = MonitoringSystem()
    
    # Register health checks
    async def check_database():
        # Check database connectivity
        return {"status": "healthy", "latency_ms": 5}
    
    monitor.register_health_check("database", check_database)
    
    # Start monitoring
    await monitor.start()
    
    # Collect metrics
    await monitor.collect_metric("custom.metric", 42, "units")
    
    # Send alerts
    await monitor.send_alert(
        AlertLevel.WARNING,
        "scheduler",
        "High job failure rate detected"
    )
    
    # Access API at http://localhost:8200/health
    
    await monitor.stop()

asyncio.run(main())
```

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
python scheduler/test_scheduler.py

# Run specific test class
python -m unittest scheduler.test_scheduler.TestDailyScheduler

# Run with coverage
coverage run scheduler/test_scheduler.py
coverage report
```

## Job Types

### Daily Curator Job
- **Type**: `daily_curator`
- **Schedule**: 12:00 ET weekdays
- **Function**: Generates daily content thread
- **Output**: JSON file with curator output and draft ID
- **Retries**: 3 attempts with 5-minute delays

### Weekly Digest Job
- **Type**: `weekly_digest`
- **Schedule**: 14:00 ET Fridays
- **Function**: Generates weekly digest
- **Output**: JSON file with digest content
- **Retries**: 2 attempts

### Health Check Job
- **Type**: `health_check`
- **Schedule**: Every 5 minutes
- **Function**: System health monitoring
- **Output**: Health status metrics
- **Alerts**: Triggered on failures or degraded performance

## Error Handling

The system implements multiple layers of error handling:

1. **Job-Level Retries**: Failed jobs automatically retry with exponential backoff
2. **Queue Persistence**: Jobs survive system restarts
3. **Alert System**: Critical failures trigger external notifications
4. **Health Monitoring**: Continuous system health checks
5. **Graceful Degradation**: System continues operating with reduced functionality

## Monitoring Dashboard

Access the monitoring dashboard at `http://localhost:8200`:

- `/health` - Overall system health
- `/metrics` - Real-time metrics
- `/alerts` - Active alerts
- `/stats` - Detailed statistics

## Troubleshooting

### Common Issues

1. **Jobs not running at scheduled time**
   - Check timezone configuration
   - Verify cron expression format
   - Check scheduler is running: `scheduler.get_status()`

2. **High memory usage**
   - Old jobs may need cleanup: `queue.cleanup_old_jobs(days=7)`
   - Check metrics retention: limit to 10,000 entries

3. **Database locked errors**
   - Ensure only one queue instance per database
   - Check for stale lock files

4. **Alert webhook failures**
   - Verify webhook URL is accessible
   - Check network connectivity
   - Review webhook payload format

### Debug Mode

Enable debug logging:

```python
from loguru import logger
logger.add("scheduler.log", level="DEBUG")
```

## Production Deployment

### Systemd Service

Create `/etc/systemd/system/koi-scheduler.service`:

```ini
[Unit]
Description=KOI Scheduler Service
After=network.target postgresql.service

[Service]
Type=simple
User=koi
WorkingDirectory=/opt/koi-sensors
ExecStart=/usr/bin/python3 /opt/koi-sensors/scheduler/daily_scheduler.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY scheduler/ scheduler/
COPY koi-processor/ koi-processor/

CMD ["python", "scheduler/daily_scheduler.py"]
```

### Environment Variables

```bash
# Timezone
export TZ=America/New_York

# Database
export DATABASE_URL=postgresql://user:pass@localhost/koi

# Monitoring
export MONITORING_PORT=8200

# Alerts
export ALERT_WEBHOOK_URL=https://hooks.slack.com/...
```

## Performance Considerations

- **Worker Count**: Default 3 workers, adjust based on load
- **Collection Interval**: 60 seconds default, increase for lower overhead
- **Metric Retention**: Limited to 10,000 entries
- **Alert History**: Limited to 1,000 alerts
- **Job History**: Cleanup old jobs weekly

## Security

- Job payloads are JSON-serialized, not pickled (prevents code injection)
- SQLite database should have restricted permissions
- Webhook URLs should use HTTPS
- Monitor API should be behind authentication in production

## Future Enhancements

- [ ] Redis backend option for job queue
- [ ] Distributed scheduling across multiple nodes
- [ ] Web UI for job management
- [ ] Prometheus metrics export
- [ ] Advanced scheduling patterns (e.g., "last Friday of month")
- [ ] Job dependencies and workflows
- [ ] Rate limiting for job types
- [ ] Cost tracking for API calls

## Support

For issues or questions:
1. Check the logs in `logs/scheduler.log`
2. Review monitoring dashboard at `http://localhost:8200`
3. Check job queue status with `queue.get_queue_stats()`
4. Review the test suite for usage examples