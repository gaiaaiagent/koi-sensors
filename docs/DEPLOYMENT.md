# KOI Sensors - Production Deployment Guide

## Overview
This guide covers deploying the KOI sensor network to production. All sensors are configured to use environment variables for credentials, ensuring replicability across environments.

## Prerequisites

### System Requirements
- Python 3.11+
- Git
- PostgreSQL with pgvector extension (for KOI processor)
- 4GB+ RAM recommended
- Ubuntu 22.04 or similar Linux distribution

### Required Services
- KOI Coordinator (port 8005)
- KOI Event Bridge (port 8100)
- BGE Embedding Server (port 8080)
- PostgreSQL database

## Quick Deployment

### 1. Clone and Setup

```bash
# Clone repositories
git clone https://github.com/yourusername/koi-sensors.git
git clone https://github.com/yourusername/koi-processor.git

# Navigate to sensors directory
cd koi-sensors

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Create `.env` file with your credentials:

```bash
cp .env.template .env
nano .env
```

Required environment variables:

```env
# Core Configuration
KOI_COORDINATOR_URL=http://localhost:8005
EVENT_BRIDGE_URL=http://localhost:8100
LOG_LEVEL=INFO

# API Keys (only add what you need)
NOTION_API_KEY=your_notion_integration_secret
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHANNEL=@your_channel

# Optional APIs
DISCORD_BOT_TOKEN=
TWITTER_API_KEY=
```

### 3. Start Core Services

```bash
# Start KOI Coordinator
cd koi-sensors
python3 koi_protocol/coordinator/run_coordinator.py &

# Start Event Bridge (in koi-processor directory)
cd ../koi-processor
USE_ISOLATED_TABLES=false python3 koi_event_bridge_v2.py &

# Start BGE Server
python3 bge_server.py &
```

### 4. Deploy Sensors

#### Option A: Run All Sensors
```bash
cd koi-sensors
./start_all_sensors.sh
```

#### Option B: Run Specific Sensors
```bash
# Website sensor
python3 sensors/website/website_sensor.py &

# Discourse forums (no API key needed)
python3 sensors/discourse/discourse_sensor.py &

# GitHub/GitLab (public repos, no auth needed)
python3 sensors/github/github_sensor.py &
python3 sensors/gitlab/gitlab_sensor.py &

# Notion (requires API key in .env)
python3 sensors/notion/notion_sensor.py &

# Telegram (requires bot token in .env)
python3 sensors/telegram/telegram_sensor.py &
```

## Sensor Status

| Sensor | Status | Authentication | Notes |
|--------|--------|---------------|-------|
| Website | ✅ Ready | None | Scrapes any public website |
| Discourse | ✅ Ready | Optional | Works without API key via public JSON |
| GitHub | ✅ Ready | None | Clones public repositories |
| GitLab | ✅ Ready | None | Clones public repositories |
| Notion | ✅ Ready | Required | Needs integration secret in .env |
| Telegram | ✅ Ready | Required | Bot token in .env, limited to pinned messages |
| Twitter | ⚠️ Needs Fix | Required | API key needed, rate limits apply |
| Discord | ❌ Not Ready | Required | Needs bot setup |
| Podcast | ❌ Not Ready | N/A | Under development |

## Production Checklist

### Before Deployment

- [ ] Review and update `.env` with production credentials
- [ ] Remove any hardcoded credentials from code
- [ ] Set LOG_LEVEL=WARNING for production
- [ ] Configure database connection for production PostgreSQL
- [ ] Set up proper process management (systemd/supervisor)
- [ ] Configure firewall rules for required ports
- [ ] Set up monitoring and alerting

### Security Considerations

1. **Never commit `.env` file to Git** - it's in .gitignore
2. **Use read-only API keys** where possible
3. **Rotate credentials regularly**
4. **Monitor API usage** to avoid rate limits
5. **Use HTTPS** for all external connections

### Systemd Service Example

Create `/etc/systemd/system/koi-coordinator.service`:

```ini
[Unit]
Description=KOI Coordinator Service
After=network.target

[Service]
Type=simple
User=koi
WorkingDirectory=/opt/koi-sensors
Environment="PATH=/opt/koi-sensors/venv/bin"
ExecStart=/opt/koi-sensors/venv/bin/python koi_protocol/coordinator/run_coordinator.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable koi-coordinator
sudo systemctl start koi-coordinator
```

## Monitoring

### Health Checks

```bash
# Check coordinator
curl http://localhost:8005/health

# Check event bridge
curl http://localhost:8100/

# Check BGE server
curl http://localhost:8080/health
```

### Logs

```bash
# View coordinator logs
tail -f logs/coordinator.log

# View event bridge logs
tail -f ../koi-processor/logs/event_bridge.log

# View sensor logs
tail -f logs/sensors/*.log
```

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure all dependencies in requirements.txt are installed
2. **Connection refused**: Check that coordinator and event bridge are running
3. **401 Unauthorized**: Verify API keys in .env file
4. **Rate limiting**: Implement exponential backoff for API calls
5. **Database errors**: Check PostgreSQL connection and pgvector extension

### Debug Mode

For debugging, set in your environment:
```bash
export LOG_LEVEL=DEBUG
export PYTHONDONTWRITEBYTECODE=1
```

## Data Flow

```
Sensors → Coordinator → Event Bridge → BGE Server → PostgreSQL
   ↓          ↓             ↓              ↓            ↓
Collect   Validate    Deduplicate    Embeddings    Storage
```

## Scaling Considerations

- Sensors can run on multiple machines pointing to same coordinator
- Use Redis for coordinator message queue in high-volume scenarios  
- Consider rate limiting per sensor to avoid overwhelming APIs
- Implement circuit breakers for external API calls

## Support

For issues or questions:
- Check logs in `logs/` directory
- Review error messages for missing dependencies
- Ensure all services are running and accessible
- Verify network connectivity to external APIs