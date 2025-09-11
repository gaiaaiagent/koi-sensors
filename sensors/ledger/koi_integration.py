"""
KOI Integration Module - Send ledger data to KOI Event Bridge
"""

import httpx
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import hashlib
import json


class KOIIntegration:
    """Integration with KOI Event Bridge v2"""
    
    def __init__(self, koi_bridge_url: str = "http://localhost:8089", logger: Optional[logging.Logger] = None):
        self.koi_bridge_url = koi_bridge_url
        self.logger = logger or logging.getLogger(__name__)
        self.source_sensor = "ledger-sensor"
    
    async def send_event(self, 
                        event_type: str,
                        rid: str,
                        content: Dict[str, Any],
                        metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send event to KOI Event Bridge
        
        Args:
            event_type: Type of event (NEW, UPDATE, FORGET)
            rid: Resource identifier
            content: Content dictionary
            metadata: Optional metadata
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Generate CID from content
            content_str = json.dumps(content, sort_keys=True)
            cid = hashlib.sha256(content_str.encode()).hexdigest()
            
            # Create bundle
            bundle = {
                "rid": rid,
                "cid": cid,
                "content": content,
                "metadata": metadata or {},
                "manifest": {
                    "version": "1.0.0",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source": self.source_sensor
                }
            }
            
            # Create event
            event = {
                "event_type": event_type,
                "source_sensor": self.source_sensor,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "bundle": bundle
            }
            
            # Send to KOI Event Bridge
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.koi_bridge_url}/process",
                    json=event
                )
                
                if response.status_code == 200:
                    result = response.json()
                    self.logger.info(
                        f"Sent {event_type} event for {rid}: "
                        f"{result.get('chunks_created')} chunks, "
                        f"{result.get('embeddings_created')} embeddings"
                    )
                    return True
                else:
                    self.logger.error(f"Failed to send event: {response.status_code}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error sending KOI event: {e}")
            return False
    
    async def send_governance_proposal(self, proposal_data: Dict[str, Any]) -> bool:
        """
        Send governance proposal to KOI
        
        Args:
            proposal_data: Proposal data from ledger query
        
        Returns:
            True if successful
        """
        proposal_id = proposal_data.get("proposal_id")
        rid = f"governance:proposal:{proposal_id}"
        
        # Extract content
        proposal_content = proposal_data.get("content", {})
        content = {
            "type": "governance_proposal",
            "proposal_id": proposal_id,
            "title": proposal_content.get("title", f"Proposal {proposal_id}"),
            "description": proposal_content.get("description", ""),
            "status": proposal_data.get("status"),
            "submit_time": proposal_data.get("submit_time"),
            "voting_end_time": proposal_data.get("voting_end_time"),
            "text": f"{proposal_content.get('title', '')}\n\n{proposal_content.get('description', '')}",
            "raw_data": proposal_data
        }
        
        # Determine event type based on status
        event_type = "NEW"
        if proposal_data.get("status") in ["PROPOSAL_STATUS_PASSED", "PROPOSAL_STATUS_REJECTED", "PROPOSAL_STATUS_FAILED"]:
            event_type = "UPDATE"
        
        return await self.send_event(event_type, rid, content)
    
    async def send_credit_class(self, class_data: Dict[str, Any]) -> bool:
        """
        Send credit class to KOI
        
        Args:
            class_data: Credit class data from ledger query
        
        Returns:
            True if successful
        """
        class_id = class_data.get("id")
        rid = f"ecocredit:class:{class_id}"
        
        content = {
            "type": "credit_class",
            "class_id": class_id,
            "admin": class_data.get("admin"),
            "metadata": class_data.get("metadata"),
            "credit_type": class_data.get("credit_type", {}).get("name"),
            "text": f"Credit Class {class_id}: {class_data.get('metadata', '')}",
            "raw_data": class_data
        }
        
        return await self.send_event("NEW", rid, content)
    
    async def send_credit_batch(self, batch_data: Dict[str, Any], class_id: str) -> bool:
        """
        Send credit batch to KOI
        
        Args:
            batch_data: Batch data from ledger query
            class_id: Associated credit class ID
        
        Returns:
            True if successful
        """
        batch_denom = batch_data.get("denom")
        rid = f"ecocredit:batch:{batch_denom}"
        
        content = {
            "type": "credit_batch",
            "batch_denom": batch_denom,
            "class_id": class_id,
            "issuer": batch_data.get("issuer"),
            "total_amount": batch_data.get("total_amount"),
            "metadata": batch_data.get("metadata"),
            "start_date": batch_data.get("start_date"),
            "end_date": batch_data.get("end_date"),
            "project_location": batch_data.get("project_location"),
            "text": f"Credit Batch {batch_denom} from class {class_id}: {batch_data.get('total_amount', '0')} credits issued",
            "raw_data": batch_data
        }
        
        return await self.send_event("NEW", rid, content)
    
    async def send_marketplace_listing(self, order_data: Dict[str, Any]) -> bool:
        """
        Send marketplace listing to KOI
        
        Args:
            order_data: Sell order data from ledger query
        
        Returns:
            True if successful
        """
        order_id = order_data.get("id")
        rid = f"marketplace:order:{order_id}"
        
        content = {
            "type": "marketplace_listing",
            "order_id": order_id,
            "seller": order_data.get("seller"),
            "batch_denom": order_data.get("batch_denom"),
            "quantity": order_data.get("quantity"),
            "ask_price": order_data.get("ask_price"),
            "disable_auto_retire": order_data.get("disable_auto_retire"),
            "expiration": order_data.get("expiration"),
            "text": f"Marketplace listing: {order_data.get('quantity')} credits from {order_data.get('batch_denom')} at {order_data.get('ask_price')}",
            "raw_data": order_data
        }
        
        return await self.send_event("NEW", rid, content)
    
    async def send_daily_stats(self, stats_data: Dict[str, Any]) -> bool:
        """
        Send daily statistics to KOI
        
        Args:
            stats_data: Daily statistics dictionary
        
        Returns:
            True if successful
        """
        date = stats_data.get("date", datetime.now(timezone.utc).date().isoformat())
        rid = f"stats:daily:{date}"
        
        # Create narrative text from stats
        sections = stats_data.get("sections", {})
        eco = sections.get("ecocredits", {})
        gov = sections.get("governance", {})
        net = sections.get("network", {})
        
        text_parts = [
            f"Daily Statistics for {date}",
            f"\nNetwork: Block height {net.get('block_height', 'unknown')} with {net.get('active_validators', 0)} validators",
            f"\nEcocredits: {eco.get('total_credits_retired', 0):,.0f} credits retired ({eco.get('retirement_rate', 0)*100:.1f}% rate)",
            f"\nGovernance: {gov.get('active_proposals', 0)} active proposals, {gov.get('total_proposals', 0)} total"
        ]
        
        if eco.get('active_sell_orders', 0) > 0:
            text_parts.append(f"\nMarketplace: {eco.get('active_sell_orders', 0)} active listings")
        
        content = {
            "type": "daily_stats",
            "date": date,
            "timestamp": stats_data.get("timestamp"),
            "stats": stats_data.get("sections", {}),
            "key_metrics": stats_data.get("key_metrics", {}),
            "notable_events": stats_data.get("notable_events", []),
            "text": "\n".join(text_parts),
            "raw_data": stats_data
        }
        
        return await self.send_event("NEW", rid, content)
    
    async def send_weekly_digest(self, digest_data: Dict[str, Any]) -> bool:
        """
        Send weekly digest to KOI
        
        Args:
            digest_data: Weekly digest dictionary
        
        Returns:
            True if successful
        """
        week_ending = digest_data.get("week_ending", datetime.now(timezone.utc).date().isoformat())
        rid = f"digest:weekly:{week_ending}"
        
        # Compile text from sections
        text_parts = [digest_data.get("title", f"Weekly Digest - {week_ending}")]
        
        for section in digest_data.get("sections", []):
            text_parts.append(f"\n## {section['title']}")
            text_parts.append(section['content'])
        
        content = {
            "type": "weekly_digest",
            "week_ending": week_ending,
            "timestamp": digest_data.get("generated_at"),
            "sections": digest_data.get("sections", []),
            "text": "\n".join(text_parts),
            "raw_data": digest_data
        }
        
        return await self.send_event("NEW", rid, content)