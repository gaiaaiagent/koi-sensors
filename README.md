# KOI Sensors Network

100% KOI Protocol-compliant sensor network for RegenAI data collection, built upon proven scraping methods and fully integrated with KOI-net specifications.

## Overview

This system transforms your existing high-performance data collectors (86.4% success rate, 12,967+ documents) into a fully compliant KOI sensor network while preserving all proven collection methods and authentication strategies.

### Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Twitter       │    │   Discord       │    │   Telegram      │
│   Sensor        │    │   Sensor        │    │   Sensor        │
│   (Partial)     │    │   (Partial)     │    │   (Partial)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   KOI           │
                    │   Coordinator   │
                    │   (Full Node)   │
                    └─────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   YouTube       │    │   Notion        │    │   Website       │
│   Sensor        │    │   Sensor        │    │   Scraper       │
│   (Partial)     │    │   (Partial)     │    │   (Partial)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## KOI Protocol Compliance

### ✅ Full KOI-net Implementation

- **Resource Identifiers (RIDs)**: Platform-specific ORNs (`orn:twitter.tweet:user_id/tweet_id`)
- **Bundle System**: Content + Manifest + SHA-256 integrity verification
- **FUN Events**: NEW/UPDATE/FORGET event emission and handling
- **Node Types**: Full coordinator + Partial sensor architecture
- **Protocol Endpoints**: Complete KOI-net API (`/events/broadcast`, `/events/poll`, etc.)

### ✅ Proven Data Collection Integration

- **Existing Collectors**: Wraps your successful Twitter, Discourse, Notion collectors
- **Authentication**: Preserves encrypted cookie storage, API keys, graceful degradation
- **Rate Limiting**: Maintains proven backoff strategies and request throttling
- **Error Handling**: Keeps existing retry logic and graceful failure modes
- **Performance**: Preserves 86.4% collection success rate