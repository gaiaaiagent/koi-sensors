"""
Governance Query Module - Regen Network Governance Proposals and Votes
"""

import aiohttp
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


class GovernanceQueries:
    """Query governance proposals, votes, and parameters"""
    
    def __init__(self, rest_endpoint: str, session: aiohttp.ClientSession, logger: logging.Logger):
        self.rest_endpoint = rest_endpoint
        self.session = session
        self.logger = logger
    
    async def get_all_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all governance proposals
        
        Args:
            status: Filter by status (PROPOSAL_STATUS_VOTING_PERIOD, PROPOSAL_STATUS_PASSED, etc.)
        
        Returns:
            List of proposal dictionaries
        """
        proposals = []
        pagination_key = None
        
        while True:
            params = {}
            if status:
                params["proposal_status"] = status
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/cosmos/gov/v1beta1/proposals"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        proposals.extend(data.get("proposals", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        self.logger.error(f"Failed to get proposals: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error querying proposals: {e}")
                break
        
        return proposals
    
    async def get_proposal_details(self, proposal_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific proposal
        
        Args:
            proposal_id: The proposal ID
        
        Returns:
            Proposal details or None if not found
        """
        url = f"{self.rest_endpoint}/cosmos/gov/v1beta1/proposals/{proposal_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("proposal")
                else:
                    self.logger.warning(f"Proposal {proposal_id} not found: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting proposal {proposal_id}: {e}")
            return None
    
    async def get_proposal_votes(self, proposal_id: int) -> List[Dict[str, Any]]:
        """
        Get all votes for a proposal
        
        Args:
            proposal_id: The proposal ID
        
        Returns:
            List of vote records
        """
        votes = []
        pagination_key = None
        
        while True:
            params = {}
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/cosmos/gov/v1beta1/proposals/{proposal_id}/votes"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        votes.extend(data.get("votes", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        self.logger.warning(f"Failed to get votes for proposal {proposal_id}: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error getting votes for proposal {proposal_id}: {e}")
                break
        
        return votes
    
    async def get_proposal_tally(self, proposal_id: int) -> Optional[Dict[str, Any]]:
        """
        Get current tally for a proposal
        
        Args:
            proposal_id: The proposal ID
        
        Returns:
            Tally results or None if not found
        """
        url = f"{self.rest_endpoint}/cosmos/gov/v1beta1/proposals/{proposal_id}/tally"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("tally")
                else:
                    self.logger.warning(f"Failed to get tally for proposal {proposal_id}: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting tally for proposal {proposal_id}: {e}")
            return None
    
    async def get_governance_params(self) -> Dict[str, Any]:
        """
        Get current governance parameters
        
        Returns:
            Dictionary with deposit, voting, and tally parameters
        """
        params = {}
        
        # Get deposit parameters
        try:
            url = f"{self.rest_endpoint}/cosmos/gov/v1beta1/params/deposit"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    params["deposit_params"] = data.get("deposit_params")
        except Exception as e:
            self.logger.error(f"Error getting deposit params: {e}")
        
        # Get voting parameters
        try:
            url = f"{self.rest_endpoint}/cosmos/gov/v1beta1/params/voting"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    params["voting_params"] = data.get("voting_params")
        except Exception as e:
            self.logger.error(f"Error getting voting params: {e}")
        
        # Get tally parameters
        try:
            url = f"{self.rest_endpoint}/cosmos/gov/v1beta1/params/tallying"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    params["tally_params"] = data.get("tally_params")
        except Exception as e:
            self.logger.error(f"Error getting tally params: {e}")
        
        return params
    
    async def get_active_proposals(self) -> List[Dict[str, Any]]:
        """Get all proposals currently in voting period"""
        return await self.get_all_proposals(status="PROPOSAL_STATUS_VOTING_PERIOD")
    
    async def get_passed_proposals(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recently passed proposals"""
        all_passed = await self.get_all_proposals(status="PROPOSAL_STATUS_PASSED")
        # Sort by proposal ID (descending) and return most recent
        all_passed.sort(key=lambda x: int(x.get("proposal_id", 0)), reverse=True)
        return all_passed[:limit]
    
    async def get_rejected_proposals(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recently rejected proposals"""
        all_rejected = await self.get_all_proposals(status="PROPOSAL_STATUS_REJECTED")
        # Sort by proposal ID (descending) and return most recent
        all_rejected.sort(key=lambda x: int(x.get("proposal_id", 0)), reverse=True)
        return all_rejected[:limit]
    
    async def get_proposal_summary(self, proposal_id: int) -> Dict[str, Any]:
        """
        Get a comprehensive summary of a proposal
        
        Args:
            proposal_id: The proposal ID
        
        Returns:
            Summary including proposal, votes, and tally
        """
        summary = {
            "proposal_id": proposal_id,
            "retrieved_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Get proposal details
        proposal = await self.get_proposal_details(proposal_id)
        if proposal:
            summary["proposal"] = proposal
            
            # Get tally
            tally = await self.get_proposal_tally(proposal_id)
            summary["tally"] = tally
            
            # Get vote count (not all votes, just count)
            votes = await self.get_proposal_votes(proposal_id)
            summary["vote_count"] = len(votes)
            summary["top_votes"] = votes[:10] if votes else []  # Just top 10 votes
        
        return summary
    
    async def generate_governance_stats(self) -> Dict[str, Any]:
        """Generate governance statistics"""
        stats = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "active_proposals": 0,
            "total_proposals": 0,
            "passed_proposals": 0,
            "rejected_proposals": 0,
            "proposal_participation_rate": 0.0
        }
        
        try:
            # Get all proposals
            all_proposals = await self.get_all_proposals()
            stats["total_proposals"] = len(all_proposals)
            
            # Count by status
            for proposal in all_proposals:
                status = proposal.get("status")
                if status == "PROPOSAL_STATUS_VOTING_PERIOD":
                    stats["active_proposals"] += 1
                elif status == "PROPOSAL_STATUS_PASSED":
                    stats["passed_proposals"] += 1
                elif status == "PROPOSAL_STATUS_REJECTED":
                    stats["rejected_proposals"] += 1
            
            # Calculate pass rate
            decided = stats["passed_proposals"] + stats["rejected_proposals"]
            if decided > 0:
                stats["pass_rate"] = stats["passed_proposals"] / decided
            
            # Get governance parameters
            params = await self.get_governance_params()
            stats["governance_params"] = params
            
        except Exception as e:
            self.logger.error(f"Error generating governance stats: {e}")
        
        return stats