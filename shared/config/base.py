"""
KOI Sensor Network - Base Configuration
Shared configuration classes for sensor nodes
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import timedelta


class APIConfig(BaseModel):
    """Base API configuration"""
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    access_token_secret: Optional[str] = None
    base_url: Optional[str] = None
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000
    timeout_seconds: int = 30
    max_retries: int = 3
    backoff_factor: float = 2.0


class ContentFilterConfig(BaseModel):
    """Content filtering configuration"""
    keywords_include: List[str] = Field(default_factory=list)
    keywords_exclude: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=lambda: ["en"])
    min_content_length: int = 10
    max_content_length: int = 10000
    filter_retweets: bool = True
    filter_replies: bool = False


class ProcessingConfig(BaseModel):
    """Content processing configuration"""
    extract_entities: bool = True
    extract_sentiment: bool = True
    extract_topics: bool = True
    extract_essence_alignments: bool = True
    confidence_threshold: float = 0.7
    batch_size: int = 100
    processing_interval_seconds: int = 60


class KoiNetConfig(BaseModel):
    """KOI-net protocol configuration"""
    node_name: str
    node_type: str = "PARTIAL"  # PARTIAL or FULL
    coordinator_url: str = "http://localhost:8000/koi-net"
    cache_directory: str = ".sensor_cache"
    event_queue_file: str = "sensor_events.json"
    polling_interval_seconds: int = 30
    max_cache_size_mb: int = 1000
    max_event_queue_size: int = 10000


class MonitoringConfig(BaseModel):
    """Monitoring and alerting configuration"""
    log_level: str = "INFO"
    log_file: Optional[str] = None
    enable_metrics: bool = True
    metrics_port: int = 9090
    health_check_port: int = 8080
    alert_on_errors: bool = True
    alert_webhook_url: Optional[str] = None


class BaseSensorConfig(BaseModel):
    """Base sensor node configuration"""
    sensor_name: str
    platform: str
    api: APIConfig
    content_filter: ContentFilterConfig = Field(default_factory=ContentFilterConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    koi_net: KoiNetConfig
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    
    # Platform-specific extra configuration
    extra_config: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        env_prefix = "KOI_SENSOR_"
        env_file = ".env"
        
    @classmethod
    def load_from_yaml(cls, config_path: str):
        """Load configuration from YAML file"""
        import yaml
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        return cls(**config_data)
    
    def save_to_yaml(self, config_path: str):
        """Save configuration to YAML file"""
        import yaml
        with open(config_path, 'w') as f:
            yaml.safe_dump(self.dict(), f, default_flow_style=False)