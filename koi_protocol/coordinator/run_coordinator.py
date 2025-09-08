#!/usr/bin/env python3
import os
"""
Simple KOI Coordinator Runner
Demonstrates how coordinator receives events from sensors
"""

import asyncio
import logging
from pathlib import Path
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.coordinator.koi_coordinator import KOICoordinator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Run the KOI Coordinator"""
    print("🌐 Starting KOI Coordinator")
    print("=" * 50)
    print("This coordinator will:")
    print("1. Listen for events from sensor nodes")
    print("2. Forward events to processor nodes")
    print("3. Provide event polling for partial nodes")
    print("=" * 50)
    
    # Create and start coordinator
    coordinator = KOICoordinator(
        node_name="koi-coordinator-main",
        port=int(os.getenv("KOI_COORDINATOR_PORT", 8000))
    )
    
    try:
        logger.info(f"Starting KOI Coordinator on port {coordinator.port}...")
        await coordinator.start()
        
        # Keep running
        print("\n✅ Coordinator ready! Sensors can now connect.")
        print(f"📡 Listening on http://localhost:{coordinator.port}")
        print("🔗 Key endpoints:")
        print("   POST /events/broadcast - Receive events from sensors")
        print("   GET  /events/poll      - Poll events (for partial nodes)")
        print("   GET  /bundles/fetch    - Fetch bundles by RID")
        print("\nPress Ctrl+C to stop...")
        
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Shutting down coordinator...")
        await coordinator.stop()
        print("👋 Coordinator stopped.")

if __name__ == "__main__":
    asyncio.run(main())