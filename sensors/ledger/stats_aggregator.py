"""
Stats Aggregator Module - Generate daily/weekly statistics for Regen Network
"""

import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from .governance_queries import GovernanceQueries
from .ecocredit_queries import EcocreditQueries
from .consensus_queries import ConsensusQueries


class StatsAggregator:
    """Generate comprehensive statistics for daily/weekly reports"""
    
    def __init__(self, 
                 governance: GovernanceQueries,
                 ecocredit: EcocreditQueries, 
                 consensus: ConsensusQueries,
                 logger: logging.Logger):
        self.governance = governance
        self.ecocredit = ecocredit
        self.consensus = consensus
        self.logger = logger
        
        # Cache for expensive queries
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes
    
    async def generate_daily_stats(self) -> Dict[str, Any]:
        """
        Generate comprehensive daily statistics
        
        Returns:
            Dictionary with all daily statistics
        """
        stats = {
            "type": "daily_stats",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sections": {}
        }
        
        try:
            # Network consensus stats
            self.logger.info("Generating consensus statistics...")
            consensus_stats = await self.consensus.generate_consensus_stats()
            stats["sections"]["network"] = {
                "block_height": consensus_stats["block_height"],
                "average_block_time": consensus_stats["average_block_time"],
                "active_validators": consensus_stats["active_validators"],
                "total_voting_power": consensus_stats["total_voting_power"],
                "bonding_ratio": consensus_stats["bonding_ratio"],
                "peer_count": consensus_stats["peer_count"]
            }
            
            # Ecocredit stats
            self.logger.info("Generating ecocredit statistics...")
            ecocredit_stats = await self.ecocredit.generate_ecocredit_stats()
            stats["sections"]["ecocredits"] = {
                "total_credit_classes": ecocredit_stats["total_credit_classes"],
                "total_batches": ecocredit_stats["total_batches"],
                "total_credits_issued": ecocredit_stats["total_credits_issued"],
                "total_credits_retired": ecocredit_stats["total_credits_retired"],
                "retirement_rate": ecocredit_stats.get("retirement_rate", 0),
                "active_sell_orders": ecocredit_stats["active_sell_orders"],
                "marketplace_volume": ecocredit_stats["marketplace_volume"]
            }
            
            # Governance stats
            self.logger.info("Generating governance statistics...")
            governance_stats = await self.governance.generate_governance_stats()
            stats["sections"]["governance"] = {
                "active_proposals": governance_stats["active_proposals"],
                "total_proposals": governance_stats["total_proposals"],
                "passed_proposals": governance_stats["passed_proposals"],
                "rejected_proposals": governance_stats["rejected_proposals"],
                "pass_rate": governance_stats.get("pass_rate", 0)
            }
            
            # Key metrics for daily bot
            stats["key_metrics"] = {
                "headline_stat": f"{ecocredit_stats['total_credits_retired']:,.0f} credits retired",
                "network_health": "healthy" if not consensus_stats["catching_up"] else "syncing",
                "active_governance": governance_stats["active_proposals"] > 0,
                "marketplace_active": ecocredit_stats["active_sell_orders"] > 0
            }
            
            # Notable events
            stats["notable_events"] = await self._identify_notable_events()
            
        except Exception as e:
            self.logger.error(f"Error generating daily stats: {e}")
            stats["error"] = str(e)
        
        return stats
    
    async def generate_weekly_stats(self) -> Dict[str, Any]:
        """
        Generate comprehensive weekly statistics
        
        Returns:
            Dictionary with weekly statistics and trends
        """
        stats = {
            "type": "weekly_stats",
            "week_ending": datetime.now(timezone.utc).date().isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sections": {}
        }
        
        try:
            # Get daily stats first
            daily_stats = await self.generate_daily_stats()
            
            # Add weekly-specific analysis
            stats["sections"] = daily_stats["sections"].copy()
            
            # Recent credit issuances
            self.logger.info("Getting recent issuances...")
            recent_issuances = await self.ecocredit.get_recent_issuances(limit=5)
            stats["sections"]["recent_issuances"] = [
                {
                    "batch_denom": batch.get("denom"),
                    "class_id": batch.get("class_id"),
                    "issuer": batch.get("issuer"),
                    "total_amount": batch.get("total_amount")
                }
                for batch in recent_issuances
            ]
            
            # Active proposals detail
            self.logger.info("Getting active proposals...")
            active_proposals = await self.governance.get_active_proposals()
            stats["sections"]["active_proposals"] = [
                {
                    "proposal_id": prop.get("proposal_id"),
                    "title": prop.get("content", {}).get("title"),
                    "status": prop.get("status"),
                    "voting_end": prop.get("voting_end_time")
                }
                for prop in active_proposals
            ]
            
            # Top validators
            self.logger.info("Getting validator rankings...")
            top_validators = await self.consensus.get_validator_ranking(limit=10)
            stats["sections"]["top_validators"] = [
                {
                    "rank": val.get("rank"),
                    "address": val.get("address"),
                    "voting_power": val.get("voting_power")
                }
                for val in top_validators
            ]
            
            # Weekly trends
            stats["trends"] = await self._calculate_weekly_trends()
            
            # Summary narrative
            stats["summary"] = self._generate_weekly_summary(stats)
            
        except Exception as e:
            self.logger.error(f"Error generating weekly stats: {e}")
            stats["error"] = str(e)
        
        return stats
    
    async def _identify_notable_events(self) -> List[Dict[str, Any]]:
        """
        Identify notable events for reporting
        
        Returns:
            List of notable events
        """
        events = []
        
        try:
            # Check for new proposals
            active_proposals = await self.governance.get_active_proposals()
            for proposal in active_proposals:
                submit_time = proposal.get("submit_time")
                if submit_time:
                    submit_dt = datetime.fromisoformat(submit_time.replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - submit_dt).days < 1:
                        events.append({
                            "type": "new_proposal",
                            "description": f"New governance proposal #{proposal.get('proposal_id')}: {proposal.get('content', {}).get('title')}",
                            "timestamp": submit_time
                        })
            
            # Check for large credit issuances
            recent_issuances = await self.ecocredit.get_recent_issuances(limit=10)
            for batch in recent_issuances:
                amount = batch.get("total_amount", "0")
                try:
                    if float(amount.replace(",", "")) > 100000:
                        events.append({
                            "type": "large_issuance",
                            "description": f"Large credit issuance: {amount} credits in batch {batch.get('denom')}",
                            "timestamp": batch.get("issuance_date")
                        })
                except:
                    pass
            
            # Check for high marketplace activity
            sell_orders = await self.ecocredit.get_marketplace_sell_orders()
            if len(sell_orders) > 20:
                events.append({
                    "type": "high_marketplace_activity",
                    "description": f"High marketplace activity with {len(sell_orders)} active sell orders",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            
        except Exception as e:
            self.logger.error(f"Error identifying notable events: {e}")
        
        return events
    
    async def _calculate_weekly_trends(self) -> Dict[str, Any]:
        """
        Calculate weekly trends (placeholder for historical comparison)
        
        Returns:
            Dictionary with trend indicators
        """
        trends = {
            "credits_retired_trend": "stable",  # Would compare to previous week
            "governance_activity": "normal",
            "marketplace_trend": "growing",
            "network_growth": "stable"
        }
        
        # In production, this would compare to previous week's data
        # For now, return placeholder trends
        
        return trends
    
    def _generate_weekly_summary(self, stats: Dict[str, Any]) -> str:
        """
        Generate a narrative summary of weekly statistics
        
        Args:
            stats: Weekly statistics dictionary
        
        Returns:
            Narrative summary string
        """
        sections = stats.get("sections", {})
        ecocredits = sections.get("ecocredits", {})
        governance = sections.get("governance", {})
        network = sections.get("network", {})
        
        summary_parts = []
        
        # Network status
        summary_parts.append(
            f"The Regen Network is operating at block height {network.get('block_height', 'unknown')} "
            f"with {network.get('active_validators', 0)} active validators."
        )
        
        # Ecocredit activity
        summary_parts.append(
            f"This week saw {ecocredits.get('total_credits_retired', 0):,.0f} credits retired "
            f"across {ecocredits.get('total_credit_classes', 0)} credit classes, "
            f"with {ecocredits.get('active_sell_orders', 0)} active marketplace listings."
        )
        
        # Governance activity
        if governance.get("active_proposals", 0) > 0:
            summary_parts.append(
                f"There are {governance.get('active_proposals', 0)} active governance proposals "
                f"currently in voting period."
            )
        else:
            summary_parts.append(
                "No governance proposals are currently active for voting."
            )
        
        return " ".join(summary_parts)
    
    async def generate_stat_for_daily_bot(self) -> str:
        """
        Generate a single interesting statistic for the daily bot
        
        Returns:
            Formatted statistic string
        """
        try:
            # Rotate through different stat types
            import random
            stat_type = random.choice(["credits", "governance", "network", "marketplace"])
            
            if stat_type == "credits":
                eco_stats = await self.ecocredit.generate_ecocredit_stats()
                retired = eco_stats.get("total_credits_retired", 0)
                rate = eco_stats.get("retirement_rate", 0) * 100
                return f"📊 {retired:,.0f} credits retired ({rate:.1f}% retirement rate)"
            
            elif stat_type == "governance":
                gov_stats = await self.governance.generate_governance_stats()
                active = gov_stats.get("active_proposals", 0)
                if active > 0:
                    return f"🗳️ {active} governance proposal{'s' if active != 1 else ''} in voting period"
                else:
                    total = gov_stats.get("total_proposals", 0)
                    return f"📜 {total} total governance proposals to date"
            
            elif stat_type == "network":
                con_stats = await self.consensus.generate_consensus_stats()
                validators = con_stats.get("active_validators", 0)
                bonding = con_stats.get("bonding_ratio", 0) * 100
                return f"🔗 {validators} active validators securing {bonding:.1f}% bonded stake"
            
            else:  # marketplace
                eco_stats = await self.ecocredit.generate_ecocredit_stats()
                orders = eco_stats.get("active_sell_orders", 0)
                volume = eco_stats.get("marketplace_volume", 0)
                return f"🛒 {orders} marketplace listings offering {volume:,.0f} credits"
            
        except Exception as e:
            self.logger.error(f"Error generating daily bot stat: {e}")
            return "📊 Regen Network operational"
    
    async def get_content_for_digest(self) -> Dict[str, Any]:
        """
        Get structured content for weekly digest
        
        Returns:
            Dictionary with content sections for digest
        """
        digest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": f"Regen Network Weekly Digest - {datetime.now(timezone.utc).date().isoformat()}",
            "sections": []
        }
        
        try:
            # Get weekly stats
            weekly_stats = await self.generate_weekly_stats()
            
            # Executive Summary
            digest["sections"].append({
                "title": "Executive Summary",
                "content": weekly_stats.get("summary", ""),
                "priority": 1
            })
            
            # Key Metrics
            metrics_content = []
            eco = weekly_stats["sections"].get("ecocredits", {})
            metrics_content.append(f"- Total Credits Retired: {eco.get('total_credits_retired', 0):,.0f}")
            metrics_content.append(f"- Credit Classes: {eco.get('total_credit_classes', 0)}")
            metrics_content.append(f"- Active Marketplace Listings: {eco.get('active_sell_orders', 0)}")
            
            gov = weekly_stats["sections"].get("governance", {})
            if gov.get("active_proposals", 0) > 0:
                metrics_content.append(f"- Active Governance Proposals: {gov.get('active_proposals', 0)}")
            
            digest["sections"].append({
                "title": "Key Metrics",
                "content": "\n".join(metrics_content),
                "priority": 2
            })
            
            # Notable Events
            events = weekly_stats.get("notable_events", [])
            if events:
                events_content = []
                for event in events[:5]:  # Top 5 events
                    events_content.append(f"- {event['description']}")
                
                digest["sections"].append({
                    "title": "Notable Events",
                    "content": "\n".join(events_content),
                    "priority": 3
                })
            
            # Recent Issuances
            issuances = weekly_stats["sections"].get("recent_issuances", [])
            if issuances:
                issuance_content = []
                for batch in issuances[:3]:  # Top 3 issuances
                    issuance_content.append(
                        f"- {batch['batch_denom']}: {batch.get('total_amount', 'unknown')} credits"
                    )
                
                digest["sections"].append({
                    "title": "Recent Credit Issuances",
                    "content": "\n".join(issuance_content),
                    "priority": 4
                })
            
            # Active Proposals
            proposals = weekly_stats["sections"].get("active_proposals", [])
            if proposals:
                proposal_content = []
                for prop in proposals[:3]:  # Top 3 proposals
                    proposal_content.append(
                        f"- Proposal #{prop['proposal_id']}: {prop.get('title', 'Untitled')}"
                    )
                
                digest["sections"].append({
                    "title": "Active Governance Proposals",
                    "content": "\n".join(proposal_content),
                    "priority": 5
                })
            
        except Exception as e:
            self.logger.error(f"Error generating digest content: {e}")
            digest["error"] = str(e)
        
        return digest