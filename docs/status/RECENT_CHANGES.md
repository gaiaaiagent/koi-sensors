# Recent Changes - KOI Sensors

## September 18, 2025 Updates

### Major Enhancements

#### Discourse Sensor
- **Full Pagination Support**: Now fetches ALL posts from topics (previously limited to first 20)
- **Individual Post Storage**: Each post stored as separate document with its own `published_at` date
- **RID Compliance Fix**: Changed source_type from "forum_post" to "forum-post" for validation
- **Deterministic RID Generation**: Posts have unique RIDs based on forum:topic:post:author:created

#### Website Sensor
- **Site-Specific Handlers**: Added custom handlers for better content extraction
- **Regentokenomics Fix**: Fixed date extraction for URLs with month abbreviations (e.g., /sep-16)
- **Date Pattern Matching**: Enhanced to handle concatenated text like "Date of SessionSeptember 16, 2025"
- **Confidence Scoring**: Improved publication date confidence levels

#### KOI Coordinator
- **Enhanced Delivery Tracking**: Added comprehensive delivery confirmation system
- **Better Error Handling**: Improved retry logic and error reporting
- **Sensor Health Monitoring**: Better tracking of sensor status

### Processing Pipeline
- **Smart Chunking**: Improved document chunking for semantic preservation
- **Storage Architecture**: Enhanced with better deduplication and versioning
- **Database Migrations**: Added new migration scripts for improved schema

## September 13, 2025 - Previous Updates

## Fixed Issues
1. **Coordinator Port Configuration**: Fixed hardcoded port 8000 → 8005 in all sensors
2. **Coordinator Import Error**: Fixed duplicate datetime import causing UnboundLocalError
3. **Config File URLs**: Removed incorrect `/api/event` suffix from coordinator URLs

## New Features
1. **Sensor Startup Script**: Added `start_all_sensors.sh` for easy sensor management
   - Sets proper PYTHONPATH
   - Starts website and medium sensors
   - Provides status monitoring
   - Handles graceful shutdown

## Modified Files

### Sensor Configurations
- All `config.yaml` files: Updated coordinator URL from `http://localhost:8005/api/event` to `http://localhost:8005`

### Sensor Code
- `sensors/websites/website_sensor.py`: Updated hardcoded coordinator URL to port 8005
- `sensors/medium/medium_sensor.py`: Updated hardcoded coordinator URL to port 8005

### Coordinator
- `koi_protocol/coordinator/koi_coordinator.py`: Removed duplicate datetime import that was causing errors

## Current Status
- ✅ Sensors successfully connect to coordinator
- ✅ Events flow from sensors → coordinator → event bridge
- ✅ **RESOLVED**: Events now contain full content data
- ✅ **RESOLVED**: Event Bridge successfully processes content
- ✅ Data being stored in database with chunks and embeddings
- ✅ Discourse sensor fetches ALL posts with pagination
- ✅ Website sensor extracts dates correctly from all configured sites

## Next Steps
- Continue monitoring sensor performance
- Add more site-specific handlers for website sensor
- Implement incremental updates for discourse sensor

## How to Run Locally
```bash
# Set environment variables
export KOI_COORDINATOR_PORT=8005
export PYTHONPATH=/path/to/koi-sensors:$PYTHONPATH

# Start coordinator
cd koi-sensors
python3 koi_protocol/coordinator/run_coordinator.py

# In another terminal, start sensors
./start_all_sensors.sh

# Monitor logs
tail -f /tmp/*_sensor.log
tail -f /tmp/koi_coordinator*.log
```