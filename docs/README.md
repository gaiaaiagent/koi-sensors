# KOI Sensors Documentation

## Quick Links
- [Main README](../README.md)
- [Quick Start Guide](../QUICKSTART.md)
- [CLAUDE Configuration](../CLAUDE.md)

## Documentation Structure

### 📁 Status
- [Main Changelog](status/CHANGELOG.md)
- [Weekly Status Reports](status/)

### 📁 Integration Guides
- [Integration Guide](INTEGRATION_GUIDE.md)
- [Notion Integration](NOTION_INTEGRATION.md)
- [Twitter Integration](TWITTER_INTEGRATION.md)
- [Telegram Sensor Setup](TELEGRAM_SENSOR_SETUP.md)

### 📁 Implementation
- [KOI Implementation](KOI_IMPLEMENTATION.md)

### 📁 Deployment
- [Deployment Guide](DEPLOYMENT.md)

### 📁 Milestones
- [Project Milestones](milestones/)

## Main Components

### Sensors (12 Active)
Individual sensor implementations in `/sensors/`:
- Website Sensor - Continuous monitoring with hash-based change detection
- GitHub Sensor - Repository monitoring with heartbeat support
- GitHub Activity Sensor - Comprehensive activity tracking for daily/weekly curation
- GitLab Sensor - Documentation monitoring
- Medium Sensor - RSS feed monitoring
- Discourse Sensor - Forum monitoring
- Telegram Sensor - Real-time channel monitoring
- Twitter Sensor v2 - Playwright-based monitoring
- Discord Sensor - Real-time message monitoring
- Podcast Sensor - RSS feed monitoring
- Notion Sensor - Database monitoring
- Ledger Sensor - Blockchain monitoring

### KOI Protocol
Core protocol implementation in `/koi_protocol/`:
- KOI Coordinator (Port 8005) - Central event routing
- RID System - Resource Identifier management
- Bundle System - Content packaging
- Full/Partial Node implementations

### Event Bridge v2
Real-time content processing:
- RID-based deduplication
- Content versioning with superseded_at timestamps
- Event filtering for heartbeats and test data
- Direct PostgreSQL integration

### Dashboard
Live monitoring at https://regen.gaiaai.xyz/koi:
- Real-time sensor status
- Pipeline flow visualization
- Provenance tracking
- Transformation timeline

## Current Status (September 28, 2025)
- **12 Active Sensors** in production
- **Event Bridge v2** with deduplication and filtering
- **Content-based deduplication** preventing duplicate processing
- **Complete pipeline** from sensors to agent RAG access
- **Dashboard** with live monitoring and provenance tracking