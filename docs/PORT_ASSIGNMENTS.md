# KOI Sensor Network - Port Assignments & Services

Last Updated: September 14, 2025
Status: PRODUCTION - All critical services operational with clean data

## Active Services and Port Mappings

### Core Web Services

| Port | Service | Description | Access URL |
|------|---------|-------------|------------|
| **80** | Nginx HTTP | Redirects to HTTPS | http://regen.gaiaai.xyz/ → https |
| **443** | Nginx HTTPS | Main web proxy | https://regen.gaiaai.xyz/ |
| **3000** | ElizaOS/RegenAI | Main agent interface | Internal only (proxied via nginx) |
| **3007** | Grant API | IRL grant submissions | Internal only (proxied via nginx) |
| **5433** | PostgreSQL | Database (Docker) | localhost only |
| **8000** | Django Admin | Admin interface (Docker) | https://admin.regen.gaiaai.xyz/ |

### KOI Pipeline Services

| Port | Service | Description | Status |
|------|---------|-------------|--------|
| **8005** | KOI Coordinator | Event coordination hub | ✅ Active |
| **8090** | BGE Server | Embedding generation | ✅ Active |
| **8100** | KOI Event Bridge v2 | Event processing | ✅ Active |
| **8200** | MCP Knowledge Server | Agent knowledge API | ✅ Active |
| **8400** | Content Dashboard | Milestone B dashboard | ✅ Active |
| **8001** | KOI API Server | SPARQL/Graph API | ✅ Active |

### Sensor Network Status

#### Active Sensors (Fixed Text Extraction - Sept 14, 2025)
- ✅ **Website Sensor** - Clean text extraction with BeautifulSoup
- ✅ **GitHub Sensor v2** - Repository monitoring
- ✅ **GitLab Sensor v2** - Whitepaper monitoring
- ✅ **Medium Sensor** - RSS feed monitoring
- ✅ **Discourse Sensor** - Forum content extraction

#### Configured but Optional
- ⚠️ **Telegram Sensor v2** - Requires bot token
- ⚠️ **Twitter Sensor** - Requires bearer token
- ⚠️ **Notion Sensor** - Requires API key

## Nginx Proxy Configuration

### Main Site Routes
- `/` → Port 3000 (ElizaOS with basic auth)
- `/koi` → Port 3000 (KOI dashboard, part of ElizaOS client)
- `/irl/` → Static files from `/opt/projects/GAIA/Gaia-IRL/`

### API Routes
- `/api/grants/` → Port 3007 (Grant API)
- `/api/koi/coordinator/` → Port 8005
- `/api/koi/event-bridge/` → Port 8100
- `/api/koi/bge/` → Port 8090
- `/api/koi/mcp/` → Port 8200

### Admin Routes
- `admin.regen.gaiaai.xyz` → Port 8000 (Django)
- `dashboard.regen.gaiaai.xyz` → Port 8000 (Django)

## Docker Services

```bash
# Running containers
- nginx (Ports 80, 443)
- django-admin (Port 8000)
- gaia-postgres-1 (Port 5433)
- fuseki-koi (Port 3030)
```

## Starting Services

### Start All Sensors
```bash
cd /opt/projects/koi-sensors
source venv/bin/activate
./start_all_sensors.sh
```

### Start ElizaOS Agent
```bash
cd /opt/projects/GAIA
PORT=3000 POSTGRES_URL=postgresql://postgres:postgres@localhost:5433/eliza \
bun packages/cli/dist/index.js start --character characters/regenai.character.json
```

### Start KOI Coordinator
```bash
cd /opt/projects/koi-sensors
source venv/bin/activate
KOI_COORDINATOR_PORT=8005 python3 koi_protocol/coordinator/run_coordinator.py
```

### Start Grant API
```bash
cd /opt/projects/GAIA
bun grant-submission-api.js
```

## Authentication

- **Main Site**: Basic Auth (Username: `regenai`, Password: `regen2025`)
- **Django Admin**: Django user credentials
- **API Endpoints**: No auth (internal network only)

## Health Check Endpoints

- KOI Coordinator: `http://localhost:8005/health`
- KOI Coordinator Sensors: `http://localhost:8005/sensors`
- BGE Server: `http://localhost:8090/health`
- Event Bridge: `http://localhost:8100/stats`
- Django: `https://admin.regen.gaiaai.xyz/admin/`

## Common Issues & Solutions

### 502 Bad Gateway
- Check if ElizaOS is running on port 3000
- Verify nginx upstream configuration points to correct port
- Restart nginx: `docker compose restart nginx`

### Sensors Not Showing
- Sensors must broadcast events to register
- Check coordinator timeout settings (currently 1 hour)
- Verify sensor is using KOIPartialNode

### Port Conflicts
- Kill existing process: `lsof -i :PORT && kill -9 PID`
- Check Docker isn't binding the port
- Verify no duplicate services running