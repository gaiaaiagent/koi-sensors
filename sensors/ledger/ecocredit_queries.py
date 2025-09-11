"""
Ecocredit Query Module - Regen Network Credit Classes, Batches, and Marketplace
"""

import aiohttp
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


class EcocreditQueries:
    """Query credit classes, batches, balances, and marketplace data"""
    
    def __init__(self, rest_endpoint: str, session: aiohttp.ClientSession, logger: logging.Logger):
        self.rest_endpoint = rest_endpoint
        self.session = session
        self.logger = logger
    
    async def get_all_credit_classes(self) -> List[Dict[str, Any]]:
        """
        Get all credit classes
        
        Returns:
            List of credit class dictionaries
        """
        classes = []
        pagination_key = None
        
        while True:
            params = {}
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/regen/ecocredit/v1/classes"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        classes.extend(data.get("classes", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        self.logger.error(f"Failed to get credit classes: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error querying credit classes: {e}")
                break
        
        return classes
    
    async def get_credit_class_details(self, class_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific credit class
        
        Args:
            class_id: The credit class ID (e.g., "C01", "C02")
        
        Returns:
            Credit class details or None if not found
        """
        url = f"{self.rest_endpoint}/regen/ecocredit/v1/classes/{class_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("class")
                else:
                    self.logger.warning(f"Credit class {class_id} not found: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting credit class {class_id}: {e}")
            return None
    
    async def get_class_issuers(self, class_id: str) -> List[str]:
        """
        Get authorized issuers for a credit class
        
        Args:
            class_id: The credit class ID
        
        Returns:
            List of issuer addresses
        """
        url = f"{self.rest_endpoint}/regen/ecocredit/v1/classes/{class_id}/issuers"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("issuers", [])
                else:
                    self.logger.warning(f"Failed to get issuers for class {class_id}: {response.status}")
                    return []
        except Exception as e:
            self.logger.error(f"Error getting issuers for class {class_id}: {e}")
            return []
    
    async def get_class_batches(self, class_id: str) -> List[Dict[str, Any]]:
        """
        Get all batches for a credit class
        
        Args:
            class_id: The credit class ID
        
        Returns:
            List of batch dictionaries
        """
        batches = []
        pagination_key = None
        
        while True:
            params = {}
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/regen/ecocredit/v1/batches/class/{class_id}"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        batches.extend(data.get("batches", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        self.logger.warning(f"Failed to get batches for class {class_id}: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error getting batches for class {class_id}: {e}")
                break
        
        return batches
    
    async def get_batch_details(self, batch_denom: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific batch
        
        Args:
            batch_denom: The batch denomination
        
        Returns:
            Batch details or None if not found
        """
        url = f"{self.rest_endpoint}/regen/ecocredit/v1/batches/{batch_denom}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("batch")
                else:
                    self.logger.warning(f"Batch {batch_denom} not found: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting batch {batch_denom}: {e}")
            return None
    
    async def get_batch_supply(self, batch_denom: str) -> Optional[Dict[str, Any]]:
        """
        Get supply information for a batch
        
        Args:
            batch_denom: The batch denomination
        
        Returns:
            Supply information (tradable, retired, cancelled amounts)
        """
        url = f"{self.rest_endpoint}/regen/ecocredit/v1/batches/{batch_denom}/supply"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("supply")
                else:
                    self.logger.warning(f"Failed to get supply for batch {batch_denom}: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting supply for batch {batch_denom}: {e}")
            return None
    
    async def get_credit_balances(self, address: str) -> List[Dict[str, Any]]:
        """
        Get credit balances for an address
        
        Args:
            address: The account address
        
        Returns:
            List of balance records
        """
        balances = []
        pagination_key = None
        
        while True:
            params = {}
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/regen/ecocredit/v1/balances/{address}"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        balances.extend(data.get("balances", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        self.logger.warning(f"Failed to get balances for {address}: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error getting balances for {address}: {e}")
                break
        
        return balances
    
    async def get_marketplace_sell_orders(self) -> List[Dict[str, Any]]:
        """
        Get all active marketplace sell orders
        
        Returns:
            List of sell order dictionaries
        """
        orders = []
        pagination_key = None
        
        while True:
            params = {}
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/regen/ecocredit/marketplace/v1/sell-orders"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        orders.extend(data.get("sell_orders", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        self.logger.warning(f"Failed to get sell orders: {response.status}")
                        break
            except Exception as e:
                self.logger.error(f"Error getting sell orders: {e}")
                break
        
        return orders
    
    async def get_sell_order_details(self, order_id: int) -> Optional[Dict[str, Any]]:
        """
        Get details of a specific sell order
        
        Args:
            order_id: The sell order ID
        
        Returns:
            Sell order details or None if not found
        """
        url = f"{self.rest_endpoint}/regen/ecocredit/marketplace/v1/sell-orders/{order_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("sell_order")
                else:
                    self.logger.warning(f"Sell order {order_id} not found: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error getting sell order {order_id}: {e}")
            return None
    
    async def get_seller_orders(self, seller: str) -> List[Dict[str, Any]]:
        """
        Get all sell orders for a specific seller
        
        Args:
            seller: The seller address
        
        Returns:
            List of sell orders
        """
        url = f"{self.rest_endpoint}/regen/ecocredit/marketplace/v1/sell-orders/seller/{seller}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("sell_orders", [])
                else:
                    self.logger.warning(f"Failed to get orders for seller {seller}: {response.status}")
                    return []
        except Exception as e:
            self.logger.error(f"Error getting orders for seller {seller}: {e}")
            return []
    
    async def get_projects_by_class(self, class_id: str) -> List[Dict[str, Any]]:
        """
        Get all projects for a credit class
        
        Args:
            class_id: The credit class ID
        
        Returns:
            List of project dictionaries
        """
        projects = []
        pagination_key = None
        
        while True:
            params = {}
            if pagination_key:
                params["pagination.key"] = pagination_key
            
            url = f"{self.rest_endpoint}/regen/ecocredit/v1/projects/class/{class_id}"
            
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        projects.extend(data.get("projects", []))
                        
                        # Check for more pages
                        pagination = data.get("pagination", {})
                        pagination_key = pagination.get("next_key")
                        if not pagination_key:
                            break
                    else:
                        # Projects endpoint might not exist in older versions
                        self.logger.debug(f"Projects endpoint not available for class {class_id}")
                        break
            except Exception as e:
                self.logger.debug(f"Projects query not supported: {e}")
                break
        
        return projects
    
    async def generate_ecocredit_stats(self) -> Dict[str, Any]:
        """Generate comprehensive ecocredit statistics"""
        stats = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_credit_classes": 0,
            "total_batches": 0,
            "total_credits_issued": 0.0,
            "total_credits_retired": 0.0,
            "total_credits_tradable": 0.0,
            "total_credits_cancelled": 0.0,
            "active_sell_orders": 0,
            "marketplace_volume": 0.0,
            "classes_summary": []
        }
        
        try:
            # Get all credit classes
            classes = await self.get_all_credit_classes()
            stats["total_credit_classes"] = len(classes)
            
            # Process each class
            for credit_class in classes:
                class_id = credit_class.get("id")
                class_summary = {
                    "class_id": class_id,
                    "credit_type": credit_class.get("credit_type", {}).get("name"),
                    "total_batches": 0,
                    "total_issued": 0.0,
                    "total_retired": 0.0,
                    "total_tradable": 0.0
                }
                
                # Get batches for this class
                batches = await self.get_class_batches(class_id)
                class_summary["total_batches"] = len(batches)
                stats["total_batches"] += len(batches)
                
                # Process each batch
                for batch in batches:
                    batch_denom = batch.get("denom")
                    
                    # Get supply for this batch
                    supply = await self.get_batch_supply(batch_denom)
                    if supply:
                        tradable = float(supply.get("tradable_amount", "0").replace(",", ""))
                        retired = float(supply.get("retired_amount", "0").replace(",", ""))
                        cancelled = float(supply.get("cancelled_amount", "0").replace(",", ""))
                        
                        total_issued = tradable + retired + cancelled
                        
                        class_summary["total_issued"] += total_issued
                        class_summary["total_retired"] += retired
                        class_summary["total_tradable"] += tradable
                        
                        stats["total_credits_issued"] += total_issued
                        stats["total_credits_retired"] += retired
                        stats["total_credits_tradable"] += tradable
                        stats["total_credits_cancelled"] += cancelled
                
                stats["classes_summary"].append(class_summary)
            
            # Get marketplace statistics
            sell_orders = await self.get_marketplace_sell_orders()
            stats["active_sell_orders"] = len(sell_orders)
            
            # Calculate marketplace volume
            for order in sell_orders:
                quantity = float(order.get("quantity", "0").replace(",", ""))
                stats["marketplace_volume"] += quantity
            
            # Calculate retirement rate
            if stats["total_credits_issued"] > 0:
                stats["retirement_rate"] = stats["total_credits_retired"] / stats["total_credits_issued"]
            else:
                stats["retirement_rate"] = 0.0
            
        except Exception as e:
            self.logger.error(f"Error generating ecocredit stats: {e}")
        
        return stats
    
    async def get_recent_issuances(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get most recent credit issuances
        
        Args:
            limit: Maximum number of issuances to return
        
        Returns:
            List of recent batch issuances
        """
        recent_batches = []
        
        try:
            # Get all credit classes
            classes = await self.get_all_credit_classes()
            
            # Collect all batches with timestamps
            all_batches = []
            for credit_class in classes:
                class_id = credit_class.get("id")
                batches = await self.get_class_batches(class_id)
                
                for batch in batches:
                    batch["class_id"] = class_id
                    # Parse issuance date if available
                    if batch.get("issuance_date"):
                        batch["timestamp"] = batch["issuance_date"]
                    all_batches.append(batch)
            
            # Sort by timestamp (most recent first)
            all_batches.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            recent_batches = all_batches[:limit]
            
        except Exception as e:
            self.logger.error(f"Error getting recent issuances: {e}")
        
        return recent_batches