# KOI Sensors Documentation Index

## Quick Links
- [Main README](../README.md)
- [Quick Start Guide](../QUICKSTART.md)

## Documentation Structure

### 📁 Architecture
- [Implementation Details](architecture/IMPLEMENTATION.md)
- [KOI Implementation](KOI_IMPLEMENTATION.md)
- [Sensor vs Server Comparison](SENSOR_VS_SERVER_COMPARISON.md)

### 📁 Development
- [Claude Development Guide](development/CLAUDE.md)
- [Instructions for Claude](development/INSTRUCTIONS_FOR_CLAUDE.md)
- [Next Steps](development/NEXT_STEPS.md)

### 📁 Status
- [Changelog](status/CHANGELOG.md)
- [Recent Changes](status/RECENT_CHANGES.md)
- [KOI Pipeline Status](status/KOI_PIPELINE_STATUS.md)
- [Documentation Status](DOCUMENTATION_STATUS.md)


### 📁 Integration Guides
- [Integration Guide](INTEGRATION_GUIDE.md)
- [Notion Integration](NOTION_INTEGRATION.md)
- [Twitter Integration](TWITTER_INTEGRATION.md)

### 📁 Deployment
- [Deployment Guide](DEPLOYMENT.md)

### 📁 Milestones
- [Project Milestones](milestones/)

## Main Components

### Sensors
Individual sensor implementations in `/sensors/`:
- Website Sensor
- Twitter Sensor
- Discord Sensor
- Notion Sensor
- Medium Sensor
- GitHub/GitLab Sensors
- Podcast Sensor
- Ledger Sensor

### KOI Protocol
Core protocol implementation in `/koi_protocol/`:
- Coordinator
- RID System
- Bundle System
- Node implementations

### Indexing
Legacy indexing system in `/indexing/`:
- Collectors
- Processors
- Storage systems