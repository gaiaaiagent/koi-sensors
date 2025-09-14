# Recent Changes - KOI Sensors (September 13, 2025)

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
- ⚠️ **Issue**: Events contain metadata only, no actual content data
- ⚠️ Event Bridge reports "Content too short or empty"
- ⚠️ No data being stored in database (0 chunks, 0 embeddings)

## Next Steps for Local Development
The sensors need to be enhanced to:
1. Actually fetch and extract webpage/article content
2. Include content data in the KOI event bundles
3. Ensure the Event Bridge can process and store the content

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