"""
KOI Ledger Sensor - Direct Regen Network Blockchain Integration
Queries RPC and REST endpoints for governance, ecocredit, and consensus data
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

import sys
sys.path.append('/opt/projects/koi-sensors')

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.bundle_system import document_to_bundle
from shared.handlers.base_sensor import BaseSensor
from shared.config.base import BaseSensorConfig


class LedgerSensorConfig(BaseSensorConfig):
    """Ledger sensor specific configuration"""
    platform: str = "regen-ledger"
    
    # RPC endpoints with fallbacks
    rpc_endpoints: List[str] = [
        "https://regen-rpc.polkachu.com",
        "https://rpc-regen.ecostake.com",
        "https://regen.rpc.m.stavr.tech"
    ]
    
    # REST/LCD endpoints with fallbacks
    rest_endpoints: List[str] = [
        "https://regen-rest.publicnode.com",
        "https://rest-regen.ecostake.com",
        "https://regen.api.m.stavr.tech",
        "https://api-regen-ia.cosmosia.notional.ventures",
        "https://regen.api.ping.pub"
    ]
    
    # Query intervals (seconds)
    governance_interval: int = 300  # 5 minutes
    ecocredit_interval: int = 600   # 10 minutes
    consensus_interval: int = 60    # 1 minute
    stats_interval: int = 3600      # 1 hour


class LedgerSensor(BaseSensor):
    """Sensor for Regen Network blockchain data"""

    def __init__(self, config: LedgerSensorConfig):
        super().__init__(config)
        self.config: LedgerSensorConfig = config
        self.session: Optional[aiohttp.ClientSession] = None

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="ledger-sensor",
            coordinator_url="http://localhost:8005",
            poll_interval=30
        )

        # Track last query times
        self.last_queries = {
            "governance": None,
            "ecocredit": None,
            "consensus": None,
            "stats": None
        }

        # Active endpoints (selected from fallbacks)
        self.active_rpc_endpoint = None
        self.active_rest_endpoint = None

        # Track data for heartbeat
        self.total_proposals = 0
        self.total_credits = 0
        self.last_block_height = 0
    
    async def initialize(self):
        """Initialize HTTP session and test endpoints"""
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )

        # Start KOI node
        await self.koi_node.start()

        # Send initial heartbeat
        await self.send_heartbeat_event()

        # Start background tasks
        asyncio.create_task(self.send_periodic_heartbeats())
        asyncio.create_task(self.handle_coordinator_events())

        # Test and select working endpoints
        await self._select_active_endpoints()

    async def send_heartbeat_event(self, response_to: str = None):
        """Send a heartbeat event to register with coordinator"""
        try:
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": "ledger-sensor",
                "sensor_type": "ledger",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": {
                    "rpc_endpoint": self.active_rpc_endpoint,
                    "rest_endpoint": self.active_rest_endpoint,
                    "proposals_tracked": self.total_proposals,
                    "credits_tracked": self.total_credits,
                    "last_block": self.last_block_height
                }
            }

            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create document for heartbeat
            heartbeat_document = {
                'id': f"ledger_heartbeat_{int(datetime.now().timestamp())}",
                'title': 'Ledger Sensor Heartbeat',
                'url': '',
                'type': 'heartbeat',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'content': json.dumps(heartbeat_data),
                'metadata': {
                    'sensor_type': 'ledger',
                    'sensor_id': 'ledger-sensor',
                    'event_type': 'HEARTBEAT'
                }
            }

            # Convert to bundle and emit
            bundle = document_to_bundle(heartbeat_document)
            await self.koi_node.emit_new_event(bundle)

            if not response_to:
                self.logger.info("Sent heartbeat event to coordinator")
            else:
                self.logger.info(f"Responded to ping request {response_to}")

        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats every 30 minutes"""
        while True:
            await asyncio.sleep(1800)  # 30 minutes
            await self.send_heartbeat_event()

    async def handle_coordinator_events(self):
        """Listen for ping requests from coordinator"""
        try:
            # Subscribe to coordinator events
            async for event in self.koi_node.event_stream():
                if event.get('type') == 'PING_REQUEST':
                    # Check if this ping is for us
                    target = event.get('target')
                    if target == 'ledger-sensor' or target == 'all':
                        self.logger.info(f"Received ping request, responding...")
                        await self.send_heartbeat_event(response_to=event.get('id'))
        except Exception as e:
            self.logger.error(f"Error handling coordinator events: {e}")
    
    async def _select_active_endpoints(self):
        """Test endpoints and select working ones"""
        # Test RPC endpoints
        for endpoint in self.config.rpc_endpoints:
            try:
                async with self.session.get(f"{endpoint}/status") as response:
                    if response.status == 200:
                        self.active_rpc_endpoint = endpoint
                        self.logger.info(f"Selected RPC endpoint: {endpoint}")
                        break
            except Exception as e:
                self.logger.warning(f"RPC endpoint {endpoint} failed: {e}")
        
        if not self.active_rpc_endpoint:
            raise RuntimeError("No working RPC endpoints found")
        
        # Test REST endpoints
        for endpoint in self.config.rest_endpoints:
            try:
                async with self.session.get(f"{endpoint}/cosmos/base/tendermint/v1beta1/node_info") as response:
                    if response.status == 200:
                        self.active_rest_endpoint = endpoint
                        self.logger.info(f"Selected REST endpoint: {endpoint}")
                        break
            except Exception as e:
                self.logger.warning(f"REST endpoint {endpoint} failed: {e}")
        
        if not self.active_rest_endpoint:
            raise RuntimeError("No working REST endpoints found")
    
    async def query_rpc(self, path: str) -> Dict[str, Any]:
        """Query RPC endpoint with automatic fallback"""
        if not self.session:
            await self.initialize()
        
        url = f"{self.active_rpc_endpoint}{path}"
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.error(f"RPC query failed: {response.status} for {url}")
                    # Try next endpoint on failure
                    await self._select_active_endpoints()
                    return await self.query_rpc(path)
        except Exception as e:
            self.logger.error(f"RPC query error: {e}")
            await self._select_active_endpoints()
            raise
    
    async def query_rest(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Query REST endpoint with automatic fallback"""
        if not self.session:
            await self.initialize()
        
        url = f"{self.active_rest_endpoint}{path}"
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.error(f"REST query failed: {response.status} for {url}")
                    # Try next endpoint on failure
                    await self._select_active_endpoints()
                    return await self.query_rest(path, params)
        except Exception as e:
            self.logger.error(f"REST query error: {e}")
            await self._select_active_endpoints()
            raise
    
    async def collect_data(self) -> List[Dict[str, Any]]:
        """Collect data from all sources based on intervals"""
        collected_items = []
        current_time = datetime.now(timezone.utc)
        
        # Check governance proposals
        if self._should_query("governance", self.config.governance_interval):
            governance_data = await self.query_governance_proposals()
            collected_items.extend(governance_data)
            self.last_queries["governance"] = current_time
        
        # Check ecocredit data
        if self._should_query("ecocredit", self.config.ecocredit_interval):
            ecocredit_data = await self.query_ecocredit_data()
            collected_items.extend(ecocredit_data)
            self.last_queries["ecocredit"] = current_time
        
        # Check consensus data
        if self._should_query("consensus", self.config.consensus_interval):
            consensus_data = await self.query_consensus_data()
            collected_items.extend(consensus_data)
            self.last_queries["consensus"] = current_time
        
        # Generate stats
        if self._should_query("stats", self.config.stats_interval):
            stats_data = await self.generate_stats()
            collected_items.extend(stats_data)
            self.last_queries["stats"] = current_time
        
        return collected_items
    
    def _should_query(self, query_type: str, interval: int) -> bool:
        """Check if enough time has passed for a query type"""
        last_query = self.last_queries.get(query_type)
        if last_query is None:
            return True
        
        elapsed = (datetime.now(timezone.utc) - last_query).total_seconds()
        return elapsed >= interval
    
    async def query_governance_proposals(self) -> List[Dict[str, Any]]:
        """Query all governance proposals"""
        items = []
        
        try:
            # Get all proposals
            response = await self.query_rest("/cosmos/gov/v1beta1/proposals")
            proposals = response.get("proposals", [])
            
            for proposal in proposals:
                # Create item for each proposal
                item = {
                    "type": "governance_proposal",
                    "proposal_id": proposal.get("proposal_id"),
                    "status": proposal.get("status"),
                    "content": proposal.get("content", {}),
                    "submit_time": proposal.get("submit_time"),
                    "deposit_end_time": proposal.get("deposit_end_time"),
                    "voting_start_time": proposal.get("voting_start_time"),
                    "voting_end_time": proposal.get("voting_end_time"),
                    "total_deposit": proposal.get("total_deposit", []),
                    "final_tally_result": proposal.get("final_tally_result"),
                    "raw_data": proposal
                }
                items.append(item)
                
                # Get votes for active proposals
                if proposal.get("status") in ["PROPOSAL_STATUS_VOTING_PERIOD"]:
                    votes_response = await self.query_rest(
                        f"/cosmos/gov/v1beta1/proposals/{proposal['proposal_id']}/votes"
                    )
                    item["votes"] = votes_response.get("votes", [])
            
            self.logger.info(f"Collected {len(items)} governance proposals")
            
        except Exception as e:
            self.logger.error(f"Error querying governance: {e}")
        
        return items
    
    async def query_ecocredit_data(self) -> List[Dict[str, Any]]:
        """Query ecocredit classes, batches, and balances"""
        items = []
        
        try:
            # Get credit classes
            classes_response = await self.query_rest("/regen/ecocredit/v1/classes")
            credit_classes = classes_response.get("classes", [])
            
            for credit_class in credit_classes:
                # Create item for each credit class
                class_item = {
                    "type": "credit_class",
                    "class_id": credit_class.get("id"),
                    "admin": credit_class.get("admin"),
                    "metadata": credit_class.get("metadata"),
                    "credit_type": credit_class.get("credit_type", {}).get("name"),
                    "raw_data": credit_class
                }
                items.append(class_item)
                
                # Get batches for this class
                batches_response = await self.query_rest(
                    f"/regen/ecocredit/v1/batches/class/{credit_class['id']}"
                )
                batches = batches_response.get("batches", [])
                
                for batch in batches:
                    batch_item = {
                        "type": "credit_batch",
                        "batch_denom": batch.get("denom"),
                        "class_id": credit_class.get("id"),
                        "issuer": batch.get("issuer"),
                        "total_amount": batch.get("total_amount"),
                        "metadata": batch.get("metadata"),
                        "start_date": batch.get("start_date"),
                        "end_date": batch.get("end_date"),
                        "project_location": batch.get("project_location"),
                        "raw_data": batch
                    }
                    items.append(batch_item)
            
            # Get marketplace listings
            listings_response = await self.query_rest("/regen/ecocredit/marketplace/v1/sell-orders")
            sell_orders = listings_response.get("sell_orders", [])
            
            for order in sell_orders:
                market_item = {
                    "type": "marketplace_listing",
                    "order_id": order.get("id"),
                    "seller": order.get("seller"),
                    "batch_denom": order.get("batch_denom"),
                    "quantity": order.get("quantity"),
                    "ask_price": order.get("ask_price"),
                    "disable_auto_retire": order.get("disable_auto_retire"),
                    "expiration": order.get("expiration"),
                    "raw_data": order
                }
                items.append(market_item)
            
            self.logger.info(f"Collected {len(items)} ecocredit items")
            
        except Exception as e:
            self.logger.error(f"Error querying ecocredit data: {e}")
        
        return items
    
    async def query_consensus_data(self) -> List[Dict[str, Any]]:
        """Query validators and network status"""
        items = []
        
        try:
            # Get block height and network status
            status_response = await self.query_rpc("/status")
            status = status_response.get("result", {})
            
            network_item = {
                "type": "network_status",
                "chain_id": status.get("node_info", {}).get("network"),
                "block_height": status.get("sync_info", {}).get("latest_block_height"),
                "block_time": status.get("sync_info", {}).get("latest_block_time"),
                "catching_up": status.get("sync_info", {}).get("catching_up"),
                "validator_info": status.get("validator_info"),
                "raw_data": status
            }
            items.append(network_item)
            
            # Get validators
            validators_response = await self.query_rpc("/validators")
            validators = validators_response.get("result", {}).get("validators", [])
            
            for validator in validators[:20]:  # Top 20 validators
                val_item = {
                    "type": "validator",
                    "address": validator.get("address"),
                    "voting_power": validator.get("voting_power"),
                    "proposer_priority": validator.get("proposer_priority"),
                    "raw_data": validator
                }
                items.append(val_item)
            
            self.logger.info(f"Collected {len(items)} consensus items")
            
        except Exception as e:
            self.logger.error(f"Error querying consensus data: {e}")
        
        return items
    
    async def generate_stats(self) -> List[Dict[str, Any]]:
        """Generate aggregate statistics"""
        stats_items = []
        
        try:
            # Credit statistics
            classes_response = await self.query_rest("/regen/ecocredit/v1/classes")
            total_classes = len(classes_response.get("classes", []))
            
            # Get total supply across all batches
            total_credits_issued = 0
            total_credits_retired = 0
            
            for credit_class in classes_response.get("classes", []):
                batches_response = await self.query_rest(
                    f"/regen/ecocredit/v1/batches/class/{credit_class['id']}"
                )
                for batch in batches_response.get("batches", []):
                    # Get batch supply
                    supply_response = await self.query_rest(
                        f"/regen/ecocredit/v1/batches/{batch['denom']}/supply"
                    )
                    supply = supply_response.get("supply", {})
                    
                    if supply.get("tradable_amount"):
                        total_credits_issued += float(supply["tradable_amount"])
                    if supply.get("retired_amount"):
                        total_credits_retired += float(supply["retired_amount"])
            
            # Governance statistics
            proposals_response = await self.query_rest("/cosmos/gov/v1beta1/proposals")
            proposals = proposals_response.get("proposals", [])
            active_proposals = len([p for p in proposals if p.get("status") == "PROPOSAL_STATUS_VOTING_PERIOD"])
            
            # Network statistics
            status_response = await self.query_rpc("/status")
            block_height = status_response.get("result", {}).get("sync_info", {}).get("latest_block_height")
            
            validators_response = await self.query_rpc("/validators")
            total_validators = len(validators_response.get("result", {}).get("validators", []))
            
            # Create daily stats item
            daily_stats = {
                "type": "daily_stats",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stats": {
                    "total_credit_classes": total_classes,
                    "total_credits_issued": total_credits_issued,
                    "total_credits_retired": total_credits_retired,
                    "retirement_rate": total_credits_retired / total_credits_issued if total_credits_issued > 0 else 0,
                    "active_governance_proposals": active_proposals,
                    "total_validators": total_validators,
                    "current_block_height": block_height
                }
            }
            stats_items.append(daily_stats)
            
            self.logger.info(f"Generated daily stats: {daily_stats['stats']}")
            
        except Exception as e:
            self.logger.error(f"Error generating stats: {e}")
        
        return stats_items
    
    def create_rid(self, item_data: Dict[str, Any]) -> RID:
        """Create RID for ledger data"""
        item_type = item_data.get("type")
        
        if item_type == "governance_proposal":
            proposal_id = item_data.get("proposal_id")
            return RID.generate(f"governance:proposal:{proposal_id}")
        
        elif item_type == "credit_class":
            class_id = item_data.get("class_id")
            return RID.generate(f"ecocredit:class:{class_id}")
        
        elif item_type == "credit_batch":
            batch_denom = item_data.get("batch_denom")
            return RID.generate(f"ecocredit:batch:{batch_denom}")
        
        elif item_type == "marketplace_listing":
            order_id = item_data.get("order_id")
            return RID.generate(f"marketplace:order:{order_id}")
        
        elif item_type == "validator":
            address = item_data.get("address")
            return RID.generate(f"validator:{address}")
        
        elif item_type == "network_status":
            block_height = item_data.get("block_height")
            return RID.generate(f"network:status:{block_height}")
        
        elif item_type == "daily_stats":
            date = item_data.get("date")
            return RID.generate(f"stats:daily:{date}")
        
        else:
            # Fallback
            timestamp = datetime.now(timezone.utc).isoformat()
            return RID.generate(f"ledger:unknown:{timestamp}")
    
    def extract_content(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract normalized content from ledger data"""
        item_type = item_data.get("type")
        
        # Extract blockchain timestamp for publication date
        block_time = None
        confidence = 0.0
        
        # For blockchain data, use block time as publication date
        if item_data.get("block_time"):
            block_time = item_data.get("block_time")
            confidence = 1.0  # Blockchain timestamps are immutable and exact
        elif item_data.get("timestamp"):
            block_time = item_data.get("timestamp")
            confidence = 0.95
        else:
            # Use current time as fallback
            block_time = datetime.now(timezone.utc).isoformat()
            confidence = 0.5
        
        content = {
            "type": item_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Publication date metadata for Daily Curator
            "published_at": block_time,
            "published_confidence": confidence
        }
        
        if item_type == "governance_proposal":
            proposal_content = item_data.get("content", {})
            content.update({
                "text": proposal_content.get("description", ""),
                "title": proposal_content.get("title", f"Proposal {item_data.get('proposal_id')}"),
                "proposal_id": item_data.get("proposal_id"),
                "status": item_data.get("status"),
                "voting_end_time": item_data.get("voting_end_time"),
                "tally_result": item_data.get("final_tally_result")
            })
        
        elif item_type == "credit_class":
            content.update({
                "text": f"Credit Class {item_data.get('class_id')}: {item_data.get('metadata', '')}",
                "title": f"Credit Class {item_data.get('class_id')}",
                "class_id": item_data.get("class_id"),
                "admin": item_data.get("admin"),
                "credit_type": item_data.get("credit_type")
            })
        
        elif item_type == "credit_batch":
            content.update({
                "text": f"Credit Batch {item_data.get('batch_denom')} from class {item_data.get('class_id')}",
                "title": f"Batch {item_data.get('batch_denom')}",
                "batch_denom": item_data.get("batch_denom"),
                "class_id": item_data.get("class_id"),
                "issuer": item_data.get("issuer"),
                "total_amount": item_data.get("total_amount"),
                "project_location": item_data.get("project_location"),
                "date_range": f"{item_data.get('start_date')} to {item_data.get('end_date')}"
            })
        
        elif item_type == "marketplace_listing":
            content.update({
                "text": f"Marketplace listing: {item_data.get('quantity')} credits from {item_data.get('batch_denom')} at {item_data.get('ask_price')}",
                "title": f"Sell Order {item_data.get('order_id')}",
                "order_id": item_data.get("order_id"),
                "seller": item_data.get("seller"),
                "batch_denom": item_data.get("batch_denom"),
                "quantity": item_data.get("quantity"),
                "ask_price": item_data.get("ask_price")
            })
        
        elif item_type == "validator":
            content.update({
                "text": f"Validator {item_data.get('address')} with voting power {item_data.get('voting_power')}",
                "title": f"Validator {item_data.get('address')[:10]}...",
                "address": item_data.get("address"),
                "voting_power": item_data.get("voting_power")
            })
        
        elif item_type == "network_status":
            content.update({
                "text": f"Network at block {item_data.get('block_height')} on chain {item_data.get('chain_id')}",
                "title": "Network Status",
                "chain_id": item_data.get("chain_id"),
                "block_height": item_data.get("block_height"),
                "block_time": item_data.get("block_time")
            })
        
        elif item_type == "daily_stats":
            stats = item_data.get("stats", {})
            content.update({
                "text": f"Daily Stats: {stats.get('total_credit_classes')} classes, {stats.get('total_credits_issued'):.0f} credits issued, {stats.get('total_credits_retired'):.0f} retired, {stats.get('active_governance_proposals')} active proposals",
                "title": f"Daily Stats for {item_data.get('date')}",
                "date": item_data.get("date"),
                "stats": stats
            })
        
        return content
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()
        if self.koi_node:
            await self.koi_node.stop()
            self.session = None


async def main():
    """Main entry point with continuous polling"""
    import os
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Get polling interval from environment (default 10 minutes)
    poll_interval = int(os.getenv('LEDGER_POLL_INTERVAL', 600))

    # Configuration
    config = LedgerSensorConfig(
        sensor_name="ledger-sensor",
        platform="regen-ledger",
        governance_interval=poll_interval,
        ecocredit_interval=poll_interval * 2,  # Less frequent
        consensus_interval=60,  # Keep frequent for consensus
        stats_interval=3600  # Hourly stats
    )

    sensor = LedgerSensor(config)

    print(f"Starting Ledger sensor with {poll_interval} second polling interval ({poll_interval/60:.1f} minutes)")
    print(f"Monitoring Regen Network blockchain...")

    try:
        # Initialize sensor
        await sensor.initialize()

        # Continuous monitoring loop
        while True:
            try:
                print(f"\n{'='*50}")
                print(f"Starting Ledger collection cycle - {datetime.now().isoformat()}")
                print(f"{'='*50}")

                # Run all queries
                tasks = []

                # Query governance proposals
                if hasattr(sensor, 'query_governance'):
                    tasks.append(sensor.query_governance())

                # Query ecocredit data
                if hasattr(sensor, 'query_ecocredits'):
                    tasks.append(sensor.query_ecocredits())

                # Query consensus state
                if hasattr(sensor, 'query_consensus'):
                    tasks.append(sensor.query_consensus())

                # Query network stats
                if hasattr(sensor, 'query_stats'):
                    tasks.append(sensor.query_stats())

                # Run all queries in parallel
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Process results
                    for result in results:
                        if isinstance(result, Exception):
                            print(f"Error in query: {result}")

                print(f"\n✅ Collection cycle complete")
                print(f"⏰ Next collection in {poll_interval} seconds ({poll_interval/60:.1f} minutes)")

                # Wait for next poll interval
                await asyncio.sleep(poll_interval)

            except Exception as e:
                print(f"❌ Error in collection cycle: {e}")
                print(f"⏰ Retrying in {poll_interval} seconds...")
                await asyncio.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\n🛑 Received interrupt signal, shutting down...")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        await sensor.cleanup()
        print("Ledger sensor stopped")


if __name__ == "__main__":
    asyncio.run(main())