"""
Monitoring System - Health checks, metrics, and alerting
Provides observability for the scheduling and automation pipeline
"""

import asyncio
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
from loguru import logger
import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import threading


class HealthStatus(Enum):
    """System health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Metric:
    """Represents a system metric"""
    name: str
    value: float
    unit: str
    timestamp: datetime
    labels: Dict[str, str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat(),
            'labels': self.labels or {}
        }


@dataclass
class Alert:
    """Represents a system alert"""
    id: str
    level: AlertLevel
    component: str
    message: str
    timestamp: datetime
    metadata: Dict[str, Any] = None
    resolved: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'level': self.level.value,
            'component': self.component,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata or {},
            'resolved': self.resolved
        }


class MonitoringSystem:
    """
    Comprehensive monitoring for the KOI automation pipeline
    Tracks health, metrics, and sends alerts
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize monitoring system"""
        self.config = config or {}
        self.metrics: List[Metric] = []
        self.alerts: List[Alert] = []
        self.health_checks: Dict[str, Callable] = {}
        self.app = FastAPI(title="KOI Monitoring API")
        self.running = False
        self.server_thread = None
        
        # Metrics collection interval
        self.collection_interval = config.get('collection_interval', 60)  # seconds
        
        # Alert configuration
        self.alert_config = config.get('alerts', {})
        self.webhook_url = self.alert_config.get('webhook')
        self.email_config = self.alert_config.get('email', {})
        
        # Setup API routes
        self._setup_routes()
        
        logger.info("Monitoring System initialized")
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
        @self.app.get("/health")
        async def health():
            """Overall system health"""
            status = await self.get_health_status()
            return JSONResponse(
                content=status,
                status_code=200 if status['status'] == 'healthy' else 503
            )
        
        @self.app.get("/metrics")
        async def metrics():
            """Get current metrics"""
            return {
                'metrics': [m.to_dict() for m in self.metrics[-100:]],  # Last 100 metrics
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        
        @self.app.get("/alerts")
        async def alerts():
            """Get active alerts"""
            active_alerts = [a for a in self.alerts if not a.resolved]
            return {
                'alerts': [a.to_dict() for a in active_alerts],
                'total': len(active_alerts)
            }
        
        @self.app.get("/stats")
        async def stats():
            """Get system statistics"""
            return await self.get_statistics()
        
        @self.app.post("/alert/resolve/{alert_id}")
        async def resolve_alert(alert_id: str):
            """Resolve an alert"""
            for alert in self.alerts:
                if alert.id == alert_id:
                    alert.resolved = True
                    return {'message': f'Alert {alert_id} resolved'}
            raise HTTPException(status_code=404, detail="Alert not found")
    
    def register_health_check(self, name: str, check_func: Callable):
        """Register a health check function"""
        self.health_checks[name] = check_func
        logger.info(f"Registered health check: {name}")
    
    async def collect_metric(self, name: str, value: float, unit: str = "", labels: Dict[str, str] = None):
        """Collect a metric"""
        metric = Metric(
            name=name,
            value=value,
            unit=unit,
            timestamp=datetime.now(timezone.utc),
            labels=labels
        )
        
        self.metrics.append(metric)
        
        # Keep only last 10000 metrics
        if len(self.metrics) > 10000:
            self.metrics = self.metrics[-10000:]
        
        # Check for threshold violations
        await self._check_thresholds(metric)
    
    async def send_alert(
        self,
        level: AlertLevel,
        component: str,
        message: str,
        metadata: Dict[str, Any] = None
    ):
        """Send an alert"""
        import uuid
        
        alert = Alert(
            id=str(uuid.uuid4()),
            level=level,
            component=component,
            message=message,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata
        )
        
        self.alerts.append(alert)
        
        # Keep only last 1000 alerts
        if len(self.alerts) > 1000:
            self.alerts = self.alerts[-1000:]
        
        logger.warning(f"ALERT [{level.value}] {component}: {message}")
        
        # Send external notifications for high severity
        if level in [AlertLevel.ERROR, AlertLevel.CRITICAL]:
            await self._send_external_alert(alert)
    
    async def _send_external_alert(self, alert: Alert):
        """Send alert to external systems"""
        # Webhook notification
        if self.webhook_url:
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        'text': f"🚨 [{alert.level.value.upper()}] {alert.component}\n{alert.message}",
                        'alert': alert.to_dict()
                    }
                    async with session.post(self.webhook_url, json=payload) as resp:
                        if resp.status != 200:
                            logger.error(f"Failed to send webhook alert: {resp.status}")
            except Exception as e:
                logger.error(f"Error sending webhook alert: {e}")
        
        # Email notification (placeholder)
        if self.email_config.get('enabled'):
            # Implement email sending
            pass
    
    async def _check_thresholds(self, metric: Metric):
        """Check metric against configured thresholds"""
        thresholds = self.config.get('thresholds', {})
        
        if metric.name in thresholds:
            threshold = thresholds[metric.name]
            
            if 'max' in threshold and metric.value > threshold['max']:
                await self.send_alert(
                    AlertLevel.WARNING,
                    f"threshold_{metric.name}",
                    f"{metric.name} exceeded maximum threshold: {metric.value} > {threshold['max']} {metric.unit}"
                )
            
            if 'min' in threshold and metric.value < threshold['min']:
                await self.send_alert(
                    AlertLevel.WARNING,
                    f"threshold_{metric.name}",
                    f"{metric.name} below minimum threshold: {metric.value} < {threshold['min']} {metric.unit}"
                )
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get overall system health status"""
        health_results = {}
        overall_status = HealthStatus.HEALTHY
        
        # Run all health checks
        for name, check_func in self.health_checks.items():
            try:
                result = await check_func()
                health_results[name] = result
                
                # Update overall status
                if result.get('status') == 'unhealthy':
                    overall_status = HealthStatus.UNHEALTHY
                elif result.get('status') == 'degraded' and overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED
                    
            except Exception as e:
                health_results[name] = {
                    'status': 'error',
                    'error': str(e)
                }
                overall_status = HealthStatus.UNHEALTHY
        
        # Check for recent failures
        recent_failures = sum(
            1 for a in self.alerts
            if a.level in [AlertLevel.ERROR, AlertLevel.CRITICAL]
            and not a.resolved
            and a.timestamp > datetime.now(timezone.utc) - timedelta(hours=1)
        )
        
        if recent_failures > 5:
            overall_status = HealthStatus.CRITICAL
        elif recent_failures > 2:
            overall_status = HealthStatus.DEGRADED
        
        return {
            'status': overall_status.value,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': health_results,
            'recent_failures': recent_failures
        }
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        stats = {
            'metrics': {
                'total': len(self.metrics),
                'last_hour': sum(
                    1 for m in self.metrics
                    if m.timestamp > datetime.now(timezone.utc) - timedelta(hours=1)
                )
            },
            'alerts': {
                'total': len(self.alerts),
                'active': sum(1 for a in self.alerts if not a.resolved),
                'by_level': {}
            },
            'uptime': self._get_uptime()
        }
        
        # Count alerts by level
        for level in AlertLevel:
            stats['alerts']['by_level'][level.value] = sum(
                1 for a in self.alerts
                if a.level == level and not a.resolved
            )
        
        return stats
    
    def _get_uptime(self) -> str:
        """Get system uptime"""
        if hasattr(self, 'start_time'):
            uptime = datetime.now(timezone.utc) - self.start_time
            days = uptime.days
            hours = uptime.seconds // 3600
            minutes = (uptime.seconds % 3600) // 60
            return f"{days}d {hours}h {minutes}m"
        return "unknown"
    
    async def _collect_system_metrics(self):
        """Collect system-level metrics"""
        try:
            import psutil
            
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            await self.collect_metric("system.cpu.usage", cpu_percent, "%")
            
            # Memory usage
            memory = psutil.virtual_memory()
            await self.collect_metric("system.memory.usage", memory.percent, "%")
            await self.collect_metric("system.memory.available", memory.available / (1024**3), "GB")
            
            # Disk usage
            disk = psutil.disk_usage('/')
            await self.collect_metric("system.disk.usage", disk.percent, "%")
            await self.collect_metric("system.disk.free", disk.free / (1024**3), "GB")
            
            # Network I/O
            net_io = psutil.net_io_counters()
            await self.collect_metric("system.network.bytes_sent", net_io.bytes_sent, "bytes")
            await self.collect_metric("system.network.bytes_recv", net_io.bytes_recv, "bytes")
            
        except ImportError:
            logger.warning("psutil not available, skipping system metrics")
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    async def _metrics_collector(self):
        """Background task to collect metrics"""
        while self.running:
            try:
                await self._collect_system_metrics()
                await asyncio.sleep(self.collection_interval)
            except Exception as e:
                logger.error(f"Error in metrics collector: {e}")
                await asyncio.sleep(60)
    
    def _run_server(self):
        """Run the FastAPI server in a thread"""
        port = self.config.get('monitoring', {}).get('metrics_port', 8200)
        uvicorn.run(self.app, host="0.0.0.0", port=port, log_level="warning")
    
    async def start(self):
        """Start the monitoring system"""
        if self.running:
            logger.warning("Monitoring system is already running")
            return
        
        self.running = True
        self.start_time = datetime.now(timezone.utc)
        
        # Start metrics collector
        asyncio.create_task(self._metrics_collector())
        
        # Start API server in thread
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        
        port = self.config.get('monitoring', {}).get('metrics_port', 8200)
        logger.info(f"Monitoring system started on port {port}")
    
    async def stop(self):
        """Stop the monitoring system"""
        if not self.running:
            logger.warning("Monitoring system is not running")
            return
        
        self.running = False
        logger.info("Monitoring system stopped")


# Example health check functions
async def check_database_health() -> Dict[str, Any]:
    """Check database connectivity"""
    # Implement actual database check
    return {
        'status': 'healthy',
        'latency_ms': 5
    }


async def check_api_health() -> Dict[str, Any]:
    """Check external API availability"""
    # Implement actual API check
    return {
        'status': 'healthy',
        'response_time_ms': 150
    }