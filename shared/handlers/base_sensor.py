"""
KOI Sensor Network - Base Sensor Class
Abstract base class for all sensor nodes with common functionality
"""

import asyncio
import logging
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Type
from pathlib import Path

from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, Manifest
from shared.config.base import BaseSensorConfig


class BaseSensor(ABC):
    """Abstract base class for KOI sensor nodes"""
    
    def __init__(self, config: BaseSensorConfig):
        self.config = config
        self.logger = self._setup_logging()
        self.running = False
        self.cache_dir = Path(config.koi_net.cache_directory)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Initialize metrics tracking
        self.metrics = {
            "items_collected": 0,
            "items_processed": 0,
            "api_calls_made": 0,
            "errors_encountered": 0,
            "last_collection_time": None,
            "processing_rate": 0.0
        }
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger(f"koi.sensor.{self.config.sensor_name}")
        logger.setLevel(getattr(logging, self.config.monitoring.log_level))
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler if configured
        if self.config.monitoring.log_file:
            file_handler = logging.FileHandler(self.config.monitoring.log_file)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
    
    @abstractmethod
    async def collect_data(self) -> List[Dict[str, Any]]:
        """Collect data from the platform API
        
        Returns:
            List of raw data items from the platform
        """
        pass
    
    @abstractmethod
    def create_rid(self, item_data: Dict[str, Any]) -> RID:
        """Create a Resource Identifier for the data item
        
        Args:
            item_data: Raw data from platform
            
        Returns:
            RID instance for the item
        """
        pass
    
    @abstractmethod
    def extract_content(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and normalize content from raw platform data
        
        Args:
            item_data: Raw data from platform
            
        Returns:
            Normalized content dictionary
        """
        pass
    
    def apply_content_filters(self, item_data: Dict[str, Any]) -> bool:
        """Apply content filtering rules
        
        Args:
            item_data: Raw data from platform
            
        Returns:
            True if item passes filters, False otherwise
        """
        content = self.extract_content(item_data)
        text_content = content.get("text", "").lower()
        
        # Check content length
        if len(text_content) < self.config.content_filter.min_content_length:
            return False
        if len(text_content) > self.config.content_filter.max_content_length:
            return False
        
        # Check include keywords
        if self.config.content_filter.keywords_include:
            has_include_keyword = any(
                keyword.lower() in text_content 
                for keyword in self.config.content_filter.keywords_include
            )
            if not has_include_keyword:
                return False
        
        # Check exclude keywords
        if self.config.content_filter.keywords_exclude:
            has_exclude_keyword = any(
                keyword.lower() in text_content 
                for keyword in self.config.content_filter.keywords_exclude
            )
            if has_exclude_keyword:
                return False
        
        return True
    
    def is_cached(self, rid: RID) -> bool:
        """Check if RID is already cached
        
        Args:
            rid: Resource identifier to check
            
        Returns:
            True if cached, False otherwise
        """
        cache_file = self.cache_dir / f"{rid.to_string().replace(':', '_')}.json"
        return cache_file.exists()
    
    def get_cached_bundle(self, rid: RID) -> Optional[Bundle]:
        """Retrieve cached bundle for RID
        
        Args:
            rid: Resource identifier
            
        Returns:
            Cached Bundle or None if not found
        """
        cache_file = self.cache_dir / f"{rid.to_string().replace(':', '_')}.json"
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                return Bundle.from_dict(data)
        except Exception as e:
            self.logger.error(f"Error loading cached bundle for {rid}: {e}")
            return None
    
    def cache_bundle(self, bundle: Bundle):
        """Cache bundle to disk
        
        Args:
            bundle: Bundle to cache
        """
        cache_file = self.cache_dir / f"{bundle.rid.to_string().replace(':', '_')}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump(bundle.to_dict(), f, indent=2)
        except Exception as e:
            self.logger.error(f"Error caching bundle for {bundle.rid}: {e}")
    
    def process_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Apply content processing (sentiment, entities, etc.)
        
        Args:
            content: Normalized content dictionary
            
        Returns:
            Processed content with additional metadata
        """
        processed_content = content.copy()
        
        if self.config.processing.extract_sentiment:
            # Placeholder for sentiment analysis
            processed_content["sentiment"] = {
                "score": 0.0,
                "label": "neutral",
                "confidence": 0.0
            }
        
        if self.config.processing.extract_entities:
            # Placeholder for entity extraction
            processed_content["entities"] = []
        
        if self.config.processing.extract_topics:
            # Placeholder for topic extraction
            processed_content["topics"] = []
        
        if self.config.processing.extract_essence_alignments:
            # Placeholder for essence alignment detection
            processed_content["essence_alignments"] = {
                "re_whole_value": 0.0,
                "nest_caring": 0.0,
                "harmonize_agency": 0.0
            }
        
        processed_content["processing_metadata"] = {
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "processor_version": "1.0.0",
            "sensor_name": self.config.sensor_name
        }
        
        return processed_content
    
    def create_bundle(self, rid: RID, raw_data: Dict[str, Any]) -> Bundle:
        """Create a Bundle from raw platform data
        
        Args:
            rid: Resource identifier
            raw_data: Raw data from platform
            
        Returns:
            Bundle with processed content
        """
        # Extract and normalize content
        content = self.extract_content(raw_data)
        
        # Apply content processing
        processed_content = self.process_content(content)
        
        # Create bundle
        bundle = Bundle.generate(
            rid=rid,
            contents={
                "raw_data": raw_data,
                "processed_content": processed_content,
                "collection_metadata": {
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "sensor_name": self.config.sensor_name,
                    "platform": self.config.platform
                }
            }
        )
        
        return bundle
    
    async def collection_loop(self):
        """Main data collection loop"""
        self.logger.info(f"Starting collection loop for {self.config.sensor_name}")
        
        while self.running:
            try:
                start_time = datetime.now()
                
                # Collect data from platform
                raw_items = await self.collect_data()
                self.metrics["api_calls_made"] += 1
                self.metrics["items_collected"] += len(raw_items)
                
                # Process each item
                processed_count = 0
                for item_data in raw_items:
                    try:
                        # Apply content filters
                        if not self.apply_content_filters(item_data):
                            continue
                        
                        # Create RID and check if already cached
                        rid = self.create_rid(item_data)
                        if self.is_cached(rid):
                            continue
                        
                        # Create and cache bundle
                        bundle = self.create_bundle(rid, item_data)
                        self.cache_bundle(bundle)
                        
                        # TODO: Send to KOI-net coordinator
                        await self.emit_koi_event(bundle, "NEW")
                        
                        processed_count += 1
                        
                    except Exception as e:
                        self.logger.error(f"Error processing item: {e}")
                        self.metrics["errors_encountered"] += 1
                
                self.metrics["items_processed"] += processed_count
                self.metrics["last_collection_time"] = datetime.now(timezone.utc).isoformat()
                
                # Calculate processing rate
                elapsed = (datetime.now() - start_time).total_seconds()
                self.metrics["processing_rate"] = processed_count / elapsed if elapsed > 0 else 0
                
                self.logger.info(
                    f"Processed {processed_count}/{len(raw_items)} items in {elapsed:.2f}s"
                )
                
                # Wait before next collection
                await asyncio.sleep(self.config.processing.processing_interval_seconds)
                
            except Exception as e:
                self.logger.error(f"Error in collection loop: {e}")
                self.metrics["errors_encountered"] += 1
                await asyncio.sleep(60)  # Wait longer after errors
    
    async def emit_koi_event(self, bundle: Bundle, event_type: str):
        """Emit event to KOI-net coordinator
        
        Args:
            bundle: Bundle to emit
            event_type: Type of event (NEW, UPDATE, FORGET)
        """
        # TODO: Implement KOI-net event emission
        self.logger.debug(f"Emitting {event_type} event for {bundle.rid}")
    
    async def start(self):
        """Start the sensor node"""
        self.logger.info(f"Starting {self.config.sensor_name} sensor")
        self.running = True
        await self.collection_loop()
    
    async def stop(self):
        """Stop the sensor node"""
        self.logger.info(f"Stopping {self.config.sensor_name} sensor")
        self.running = False
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        return self.metrics.copy()
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status"""
        return {
            "status": "healthy" if self.running else "stopped",
            "sensor_name": self.config.sensor_name,
            "platform": self.config.platform,
            "metrics": self.get_metrics(),
            "last_check": datetime.now(timezone.utc).isoformat()
        }