# CLAUDE.md - KOI Sensors Project

This file provides guidance to Claude Code when working specifically in the koi-sensors project.

## 🚨 Current System State (Sept 26, 2025)

- **11 Active Sensors**: Website, GitHub, GitLab, Medium, Discourse, Telegram, Twitter, Discord, Podcast, Notion, Ledger
- **Health Monitoring**: Smart Hybrid system with 30-min heartbeats and on-demand ping
- **Coordinator**: Running on port 8005 with event routing and sensor tracking
- **Dashboard**: Live at https://regen.gaiaai.xyz/koi showing real-time sensor status
- **Twitter Sensor**: Uses `twitter_sensor_koi.py` (Playwright-based, no auth required)
- **GitLab Sensor**: Fixed to use KOIPartialNode and document_to_bundle (Sept 26 fix)

## 🔧 CRITICAL: Dependency Management Rules

**ALWAYS follow these rules when installing packages:**

1. **NEVER use `pip install --break-system-packages`**
2. **ALWAYS use the virtual environment**: `source venv/bin/activate`
3. **ALWAYS update requirements files** after installing:
   - Main dependencies → `requirements.txt`
   - Sensor-specific → `sensors/[sensor_name]/requirements.txt`
   - Dev dependencies → `requirements-dev.txt`

4. **Installation procedure for new packages:**
```bash
# First activate venv
source venv/bin/activate

# Install the package
pip install package-name

# Update appropriate requirements file
pip freeze | grep package-name >> requirements.txt
# OR for sensor-specific:
echo "package-name>=version" >> sensors/[sensor]/requirements.txt
```

5. **Sensor-specific dependencies:**
   - Each sensor has its own `venv` and `requirements.txt`
   - Dependencies are installed via `./setup.sh` in each sensor directory
   - NEVER install globally or break system packages

6. **Replicability requirements:**
   - All dependencies must be in requirements files
   - Version pins should use `>=` for flexibility
   - Document any system-level dependencies (e.g., Playwright browsers)
   - Test setup from clean environment before committing

## 🚀 Sensor Management Architecture

The system uses a **microservices architecture** with isolated virtual environments:

- **Individual Isolation**: Each sensor runs in its own `venv` with specific dependencies
- **Master Orchestration**: Unified scripts for system-wide operations
- **Replicable Setup**: Anyone cloning the repo can run `./setup_all.sh` to install everything

### Available Commands
```bash
# System-wide operations
./setup_all.sh    # Setup all sensors (interactive: sequential/parallel)
./start_all.sh    # Start all configured sensors
./stop_all.sh     # Gracefully stop all sensors
./status.sh       # Show current status of all sensors

# Individual sensor operations (in sensors/<name>/)
./setup.sh        # Setup this sensor's environment
./start.sh        # Start this sensor
./start.sh -b     # Start in background mode
```

## 📝 Environment Variables

The `.env` file in the root contains API keys and configuration:
- Automatically sourced by all `start.sh` scripts
- Contains: NOTION_API_KEY, TELEGRAM_BOT_TOKEN, etc.
- DO NOT commit to git

## 🔍 Debugging

When sensors fail to start:
1. Check the log: `tail -f sensors/[name]/[name]_sensor.log`
2. Verify dependencies: `cd sensors/[name] && ./setup.sh`
3. Check .env variables: `source .env && env | grep API`
4. Try manual start: `source venv/bin/activate && python3 [name]_sensor.py`

## ⚠️ Common Issues

1. **Missing dependencies**: Always run `./setup.sh` first
2. **API key errors**: Check `.env` file has required keys
3. **Port conflicts**: KOI Coordinator runs on port 8005
4. **RID generation errors**: Ensure documents have required fields (id, title, content)

Remember: **Replicability is key** - test everything from a clean clone!