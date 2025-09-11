"""
Query Templates - Reusable query patterns for daily/weekly reports
"""

from typing import Dict, List, Any, Callable, Awaitable
from datetime import datetime, timezone


class QueryTemplates:
    """Pre-defined query templates for common reporting needs"""
    
    def __init__(self, governance, ecocredit, consensus, stats):
        self.governance = governance
        self.ecocredit = ecocredit
        self.consensus = consensus
        self.stats = stats
    
    async def daily_snapshot(self) -> Dict[str, Any]:
        """
        Get a complete daily snapshot of network activity
        
        Returns:
            Dictionary with all key daily metrics
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "network_status": await self.consensus.get_network_status(),
            "active_proposals": await self.governance.get_active_proposals(),
            "recent_issuances": await self.ecocredit.get_recent_issuances(limit=5),
            "marketplace_orders": len(await self.ecocredit.get_marketplace_sell_orders()),
            "daily_stats": await self.stats.generate_daily_stats()
        }
    
    async def governance_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive governance summary
        
        Returns:
            Dictionary with governance metrics and active items
        """
        active = await self.governance.get_active_proposals()
        passed = await self.governance.get_passed_proposals(limit=5)
        rejected = await self.governance.get_rejected_proposals(limit=5)
        params = await self.governance.get_governance_params()
        
        return {
            "active_proposals": active,
            "recent_passed": passed,
            "recent_rejected": rejected,
            "governance_params": params,
            "summary": {
                "active_count": len(active),
                "passed_count": len(passed),
                "rejected_count": len(rejected)
            }
        }
    
    async def credit_market_overview(self) -> Dict[str, Any]:
        """
        Get credit market overview
        
        Returns:
            Dictionary with credit and marketplace metrics
        """
        classes = await self.ecocredit.get_all_credit_classes()
        orders = await self.ecocredit.get_marketplace_sell_orders()
        stats = await self.ecocredit.generate_ecocredit_stats()
        
        # Calculate average price if orders exist
        total_quantity = 0
        total_value = 0
        for order in orders:
            try:
                quantity = float(order.get("quantity", "0").replace(",", ""))
                price = order.get("ask_price", {})
                if price and price.get("amount"):
                    value = float(price["amount"]) * quantity
                    total_quantity += quantity
                    total_value += value
            except:
                pass
        
        avg_price = total_value / total_quantity if total_quantity > 0 else 0
        
        return {
            "total_classes": len(classes),
            "total_batches": stats.get("total_batches", 0),
            "credits_issued": stats.get("total_credits_issued", 0),
            "credits_retired": stats.get("total_credits_retired", 0),
            "retirement_rate": stats.get("retirement_rate", 0),
            "marketplace": {
                "active_orders": len(orders),
                "total_volume": stats.get("marketplace_volume", 0),
                "average_price": avg_price
            },
            "top_classes": stats.get("classes_summary", [])[:5]
        }
    
    async def validator_performance(self) -> Dict[str, Any]:
        """
        Get validator performance metrics
        
        Returns:
            Dictionary with validator statistics
        """
        validators = await self.consensus.get_validator_ranking(limit=20)
        pool = await self.consensus.get_staking_pool()
        params = await self.consensus.get_staking_params()
        
        # Calculate concentration
        total_power = sum(int(v.get("voting_power", 0)) for v in validators)
        top_10_power = sum(int(v.get("voting_power", 0)) for v in validators[:10])
        concentration = top_10_power / total_power if total_power > 0 else 0
        
        return {
            "top_validators": validators,
            "staking_pool": pool,
            "staking_params": params,
            "metrics": {
                "total_validators": len(validators),
                "total_voting_power": total_power,
                "top_10_concentration": concentration,
                "bonding_ratio": pool.get("bonded_tokens", 0) / (pool.get("bonded_tokens", 0) + pool.get("not_bonded_tokens", 1))
            }
        }
    
    async def recent_activity_feed(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get recent activity across all modules
        
        Args:
            hours: Number of hours to look back
        
        Returns:
            List of recent activities sorted by time
        """
        activities = []
        
        # Get recent proposals
        proposals = await self.governance.get_all_proposals()
        for proposal in proposals[:5]:
            submit_time = proposal.get("submit_time")
            if submit_time:
                activities.append({
                    "type": "proposal",
                    "timestamp": submit_time,
                    "description": f"Proposal #{proposal.get('proposal_id')}: {proposal.get('content', {}).get('title')}",
                    "data": proposal
                })
        
        # Get recent issuances
        issuances = await self.ecocredit.get_recent_issuances(limit=10)
        for batch in issuances:
            if batch.get("issuance_date"):
                activities.append({
                    "type": "issuance",
                    "timestamp": batch["issuance_date"],
                    "description": f"Batch {batch.get('denom')}: {batch.get('total_amount')} credits issued",
                    "data": batch
                })
        
        # Get recent marketplace listings
        orders = await self.ecocredit.get_marketplace_sell_orders()
        for order in orders[:5]:
            activities.append({
                "type": "marketplace",
                "timestamp": datetime.now(timezone.utc).isoformat(),  # Orders don't have timestamps
                "description": f"Sell order: {order.get('quantity')} credits at {order.get('ask_price', {}).get('amount')}",
                "data": order
            })
        
        # Sort by timestamp
        activities.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return activities[:20]  # Return top 20 most recent
    
    async def network_health_check(self) -> Dict[str, Any]:
        """
        Perform comprehensive network health check
        
        Returns:
            Dictionary with health indicators
        """
        status = await self.consensus.get_network_status()
        validators = await self.consensus.get_validators(limit=50)
        block_time = await self.consensus.calculate_block_time()
        net_info = await self.consensus.get_net_info()
        
        # Calculate health indicators
        is_syncing = status.get("sync_info", {}).get("catching_up", False)
        active_validators = len([v for v in validators if int(v.get("voting_power", 0)) > 0])
        peer_count = int(net_info.get("n_peers", 0)) if net_info else 0
        
        health_score = 100
        issues = []
        
        if is_syncing:
            health_score -= 20
            issues.append("Node is syncing")
        
        if active_validators < 100:
            health_score -= 10
            issues.append(f"Low validator count: {active_validators}")
        
        if peer_count < 5:
            health_score -= 15
            issues.append(f"Low peer count: {peer_count}")
        
        if block_time > 7:  # Expected ~6 seconds
            health_score -= 10
            issues.append(f"Slow block time: {block_time:.1f}s")
        
        return {
            "health_score": max(0, health_score),
            "status": "healthy" if health_score >= 80 else "degraded" if health_score >= 50 else "unhealthy",
            "indicators": {
                "is_syncing": is_syncing,
                "block_height": status.get("sync_info", {}).get("latest_block_height"),
                "active_validators": active_validators,
                "peer_count": peer_count,
                "average_block_time": block_time
            },
            "issues": issues
        }
    
    async def data_for_daily_tweet(self) -> Dict[str, Any]:
        """
        Get data optimized for daily tweet generation
        
        Returns:
            Dictionary with tweet-friendly content
        """
        # Get interesting stat
        stat = await self.stats.generate_stat_for_daily_bot()
        
        # Get active proposals if any
        active_proposals = await self.governance.get_active_proposals()
        proposal_cta = None
        if active_proposals:
            prop = active_proposals[0]
            proposal_cta = f"Vote on Proposal #{prop.get('proposal_id')}: {prop.get('content', {}).get('title', '')[:50]}"
        
        # Get marketplace highlight
        orders = await self.ecocredit.get_marketplace_sell_orders()
        market_highlight = None
        if orders:
            total_available = sum(float(o.get("quantity", "0").replace(",", "")) for o in orders)
            market_highlight = f"{len(orders)} marketplace listings with {total_available:,.0f} credits available"
        
        # Get recent issuance
        issuances = await self.ecocredit.get_recent_issuances(limit=1)
        recent_issuance = None
        if issuances:
            batch = issuances[0]
            recent_issuance = f"New batch {batch.get('denom')}: {batch.get('total_amount')} credits"
        
        return {
            "headline_stat": stat,
            "proposal_cta": proposal_cta,
            "market_highlight": market_highlight,
            "recent_issuance": recent_issuance,
            "links": {
                "registry": "https://registry.regen.network",
                "governance": "https://commonwealth.im/regen",
                "docs": "https://docs.regen.network"
            }
        }
    
    async def data_for_weekly_digest(self) -> Dict[str, Any]:
        """
        Get comprehensive data for weekly digest
        
        Returns:
            Dictionary with all weekly digest content
        """
        # Get weekly stats
        weekly_stats = await self.stats.generate_weekly_stats()
        
        # Get digest content
        digest = await self.stats.get_content_for_digest()
        
        # Get additional context
        governance = await self.governance_summary()
        market = await self.credit_market_overview()
        validators = await self.validator_performance()
        health = await self.network_health_check()
        
        return {
            "digest": digest,
            "weekly_stats": weekly_stats,
            "governance": governance,
            "market": market,
            "validators": validators,
            "network_health": health,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }