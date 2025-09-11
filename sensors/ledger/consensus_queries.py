"""
Consensus Query Module - Regen Network Validators, Blocks, and Network Status
"""

import aiohttp
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


class ConsensusQueries:
    """Query validators, blocks, and network consensus data"""
    
    def __init__(self, rpc_endpoint: str, rest_endpoint: str, session: aiohttp.ClientSession, logger: logging.Logger):
        self.rpc_endpoint = rpc_endpoint
        self.rest_endpoint = rest_endpoint
        self.session = session
        self.logger = logger
    
    async def get_network_status(self) -> Optional[Dict[str, Any]]:
        """
        Get current network status
        
        Returns:
            Network status including block height, chain ID, and sync info
        """
        url = f"{self.rpc_endpoint}/status"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("result")
                else:
                    self.logger.error(f"Failed to get network status: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting network status: {e}")
            return None
    
    async def get_block_height(self) -> Optional[int]:
        """
        Get current block height
        
        Returns:
            Current block height or None if error
        """
        status = await self.get_network_status()
        if status:
            height_str = status.get("sync_info", {}).get("latest_block_height")
            if height_str:
                return int(height_str)
        return None
    
    async def get_block(self, height: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Get block at specific height or latest block
        
        Args:
            height: Block height (None for latest)
        
        Returns:
            Block data or None if not found
        """
        params = {"height": str(height)} if height else {}
        url = f"{self.rpc_endpoint}/block"
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("result")
                else:
                    self.logger.warning(f"Failed to get block at height {height}: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting block at height {height}: {e}")
            return None
    
    async def get_validators(self, height: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get validator set at specific height
        
        Args:
            height: Block height (None for latest)
            limit: Maximum number of validators to return
        
        Returns:
            List of validator dictionaries
        """
        validators = []
        page = 1
        per_page = min(limit, 100)
        
        while len(validators) < limit:
            params = {
                "page": str(page),
                "per_page": str(per_page)
            }
            if height:
                params["height"] = str(height)
            
            url = f"{self.rpc_endpoint}/validators"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data.get("result", {})
                        new_validators = result.get("validators", [])
                        validators.extend(new_validators)
                        
                        # Check if there are more pages
                        total = int(result.get("total", "0"))
                        if len(validators) >= total or len(new_validators) < per_page:
                            break
                        
                        page += 1
                    else:
                        self.logger.error(f"Failed to get validators: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error getting validators: {e}")
                break
        
        return validators[:limit]
    
    async def get_validator_details(self, validator_address: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific validator
        
        Args:
            validator_address: The validator operator address
        
        Returns:
            Validator details or None if not found
        """
        url = f"{self.rest_endpoint}/cosmos/staking/v1beta1/validators/{validator_address}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("validator")
                else:
                    self.logger.warning(f"Validator {validator_address} not found: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting validator {validator_address}: {e}")
            return None
    
    async def get_validator_delegations(self, validator_address: str) -> List[Dict[str, Any]]:
        """
        Get all delegations to a validator
        
        Args:
            validator_address: The validator operator address
        
        Returns:
            List of delegation records
        """
        delegations = []
        pagination_key = None
        
        while True:
            params = {}
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/cosmos/staking/v1beta1/validators/{validator_address}/delegations"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        delegations.extend(data.get("delegation_responses", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        self.logger.warning(f"Failed to get delegations for {validator_address}: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error getting delegations for {validator_address}: {e}")
                break
        
        return delegations
    
    async def get_staking_params(self) -> Optional[Dict[str, Any]]:
        """
        Get current staking parameters
        
        Returns:
            Staking parameters or None if error
        """
        url = f"{self.rest_endpoint}/cosmos/staking/v1beta1/params"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("params")
                else:
                    self.logger.error(f"Failed to get staking params: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting staking params: {e}")
            return None
    
    async def get_staking_pool(self) -> Optional[Dict[str, Any]]:
        """
        Get current staking pool information
        
        Returns:
            Staking pool info (bonded/unbonded tokens) or None if error
        """
        url = f"{self.rest_endpoint}/cosmos/staking/v1beta1/pool"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("pool")
                else:
                    self.logger.error(f"Failed to get staking pool: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting staking pool: {e}")
            return None
    
    async def get_latest_block_time(self) -> Optional[datetime]:
        """
        Get timestamp of latest block
        
        Returns:
            Latest block timestamp or None if error
        """
        status = await self.get_network_status()
        if status:
            time_str = status.get("sync_info", {}).get("latest_block_time")
            if time_str:
                try:
                    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                except:
                    pass
        return None
    
    async def get_consensus_state(self) -> Optional[Dict[str, Any]]:
        """
        Get current consensus state
        
        Returns:
            Consensus state information
        """
        url = f"{self.rpc_endpoint}/consensus_state"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("result")
                else:
                    self.logger.warning(f"Failed to get consensus state: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting consensus state: {e}")
            return None
    
    async def get_net_info(self) -> Optional[Dict[str, Any]]:
        """
        Get network peer information
        
        Returns:
            Network peer info or None if error
        """
        url = f"{self.rpc_endpoint}/net_info"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("result")
                else:
                    self.logger.warning(f"Failed to get net info: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting net info: {e}")
            return None
    
    async def calculate_block_time(self, num_blocks: int = 100) -> float:
        """
        Calculate average block time over recent blocks
        
        Args:
            num_blocks: Number of recent blocks to analyze
        
        Returns:
            Average block time in seconds
        """
        try:
            # Get current height
            current_height = await self.get_block_height()
            if not current_height:
                return 0.0
            
            # Get current and past block
            current_block = await self.get_block(current_height)
            past_block = await self.get_block(current_height - num_blocks)
            
            if current_block and past_block:
                current_time = current_block.get("block", {}).get("header", {}).get("time")
                past_time = past_block.get("block", {}).get("header", {}).get("time")
                
                if current_time and past_time:
                    current_dt = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
                    past_dt = datetime.fromisoformat(past_time.replace("Z", "+00:00"))
                    
                    time_diff = (current_dt - past_dt).total_seconds()
                    return time_diff / num_blocks
            
        except Exception as e:
            self.logger.error(f"Error calculating block time: {e}")
        
        return 0.0
    
    async def generate_consensus_stats(self) -> Dict[str, Any]:
        """Generate comprehensive consensus statistics"""
        stats = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chain_id": None,
            "block_height": 0,
            "block_time": None,
            "average_block_time": 0.0,
            "total_validators": 0,
            "active_validators": 0,
            "total_voting_power": 0,
            "bonded_tokens": 0,
            "unbonded_tokens": 0,
            "bonding_ratio": 0.0,
            "peer_count": 0,
            "catching_up": False
        }
        
        try:
            # Get network status
            status = await self.get_network_status()
            if status:
                stats["chain_id"] = status.get("node_info", {}).get("network")
                stats["block_height"] = int(status.get("sync_info", {}).get("latest_block_height", 0))
                stats["block_time"] = status.get("sync_info", {}).get("latest_block_time")
                stats["catching_up"] = status.get("sync_info", {}).get("catching_up", False)
            
            # Calculate average block time
            stats["average_block_time"] = await self.calculate_block_time()
            
            # Get validators
            validators = await self.get_validators()
            stats["total_validators"] = len(validators)
            
            # Calculate total voting power
            for validator in validators:
                voting_power = int(validator.get("voting_power", 0))
                stats["total_voting_power"] += voting_power
                if voting_power > 0:
                    stats["active_validators"] += 1
            
            # Get staking pool
            pool = await self.get_staking_pool()
            if pool:
                stats["bonded_tokens"] = int(pool.get("bonded_tokens", 0))
                stats["unbonded_tokens"] = int(pool.get("not_bonded_tokens", 0))
                
                total_tokens = stats["bonded_tokens"] + stats["unbonded_tokens"]
                if total_tokens > 0:
                    stats["bonding_ratio"] = stats["bonded_tokens"] / total_tokens
            
            # Get peer count
            net_info = await self.get_net_info()
            if net_info:
                stats["peer_count"] = int(net_info.get("n_peers", 0))
            
        except Exception as e:
            self.logger.error(f"Error generating consensus stats: {e}")
        
        return stats
    
    async def get_validator_ranking(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get top validators by voting power
        
        Args:
            limit: Number of validators to return
        
        Returns:
            List of validators sorted by voting power
        """
        validators = await self.get_validators(limit=limit)
        
        # Sort by voting power
        validators.sort(key=lambda x: int(x.get("voting_power", 0)), reverse=True)
        
        # Add ranking
        for i, validator in enumerate(validators):
            validator["rank"] = i + 1
        
        return validators[:limit]