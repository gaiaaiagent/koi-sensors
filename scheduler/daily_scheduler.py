"""
Daily Scheduler - Automated trigger system for content pipeline
Handles daily curator runs and weekly digest generation
Implements Milestone B requirements for automated content publishing
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import schedule
import pytz
import time
import threading
import signal
import yaml
from loguru import logger
import traceback

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent / "koi-processor"))

# Import our pipeline components
from koi_processor.daily_curator import DailyCurator
from bots.x_daily_bot import XDailyBot


class JobStatus(Enum):
    """Job execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class JobResult:
    """Result of a scheduled job execution"""
    job_id: str
    job_type: str
    status: JobStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    retries: int = 0


@dataclass
class JobConfig:
    """Configuration for a scheduled job"""
    name: str
    cron_expression: str
    function: Callable
    enabled: bool = True
    max_retries: int = 3
    retry_delay: int = 300  # 5 minutes
    timeout: int = 3600  # 1 hour
    alert_on_failure: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class DailyScheduler:
    """
    Main scheduler class for automated content pipeline
    Manages cron-based job execution with error handling and monitoring
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the scheduler with configuration"""
        self.config = self._load_config(config_path)
        self.jobs: List[JobConfig] = []
        self.job_history: List[JobResult] = []
        self.running = False
        self.scheduler_thread = None
        
        # Set timezone
        self.timezone = pytz.timezone(self.config.get('scheduler', {}).get('timezone', 'America/New_York'))
        
        # Initialize components
        self._init_components()
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Daily Scheduler initialized (timezone: {self.timezone})")
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        if not config_path:
            config_path = Path(__file__).parent.parent.parent / "koi-processor" / "config" / "curator_config.yaml"
        
        if Path(config_path).exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                logger.info(f"Loaded config from {config_path}")
                return config
        else:
            logger.warning("No config file found, using defaults")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration"""
        return {
            'scheduler': {
                'daily_cron': '0 12 * * 1-5',  # 12:00 ET weekdays
                'weekly_cron': '0 14 * * 5',    # 14:00 ET Fridays
                'timezone': 'America/New_York'
            },
            'alerts': {
                'enabled': True,
                'email': None,
                'webhook': None
            },
            'monitoring': {
                'health_check_interval': 300,  # 5 minutes
                'metrics_port': 8200
            }
        }
    
    def _init_components(self):
        """Initialize pipeline components"""
        try:
            # Initialize Daily Curator
            self.curator = DailyCurator(self.config)
            logger.info("Daily Curator initialized")
            
            # Initialize X Bot
            self.x_bot = XDailyBot(self.config)
            logger.info("X Bot initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            raise
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.stop()
        sys.exit(0)
    
    def register_jobs(self):
        """Register all scheduled jobs"""
        # Daily curator job (weekdays)
        daily_job = JobConfig(
            name="daily_curator",
            cron_expression=self.config['scheduler']['daily_cron'],
            function=self._run_daily_curator,
            enabled=True,
            max_retries=3,
            alert_on_failure=True,
            metadata={
                "description": "Generate daily content thread",
                "output_type": "daily_thread"
            }
        )
        self.jobs.append(daily_job)
        
        # Weekly digest job (Fridays)
        weekly_job = JobConfig(
            name="weekly_digest",
            cron_expression=self.config['scheduler']['weekly_cron'],
            function=self._run_weekly_digest,
            enabled=True,
            max_retries=2,
            alert_on_failure=True,
            metadata={
                "description": "Generate weekly digest",
                "output_type": "weekly_digest"
            }
        )
        self.jobs.append(weekly_job)
        
        # Health check job (every 5 minutes)
        health_job = JobConfig(
            name="health_check",
            cron_expression="*/5 * * * *",  # Every 5 minutes
            function=self._run_health_check,
            enabled=True,
            max_retries=1,
            alert_on_failure=False,
            metadata={
                "description": "System health check",
                "output_type": "health_status"
            }
        )
        self.jobs.append(health_job)
        
        logger.info(f"Registered {len(self.jobs)} scheduled jobs")
    
    def _parse_cron_to_schedule(self, cron_expr: str, job_func: Callable):
        """Convert cron expression to schedule.py format"""
        # Parse cron expression (minute hour day month weekday)
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")
        
        minute, hour, day, month, weekday = parts
        
        # Handle daily jobs
        if weekday == "1-5":  # Weekdays
            schedule.every().monday.at(f"{hour}:{minute}").do(job_func)
            schedule.every().tuesday.at(f"{hour}:{minute}").do(job_func)
            schedule.every().wednesday.at(f"{hour}:{minute}").do(job_func)
            schedule.every().thursday.at(f"{hour}:{minute}").do(job_func)
            schedule.every().friday.at(f"{hour}:{minute}").do(job_func)
        elif weekday == "5":  # Friday
            schedule.every().friday.at(f"{hour}:{minute}").do(job_func)
        elif minute.startswith("*/"):  # Interval jobs
            interval = int(minute[2:])
            schedule.every(interval).minutes.do(job_func)
        else:
            # Default to daily at specified time
            schedule.every().day.at(f"{hour}:{minute}").do(job_func)
    
    async def _run_daily_curator(self) -> JobResult:
        """Run the daily curator pipeline"""
        job_id = f"daily_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        result = JobResult(
            job_id=job_id,
            job_type="daily_curator",
            status=JobStatus.RUNNING,
            started_at=datetime.now(timezone.utc)
        )
        
        try:
            logger.info(f"Starting daily curator job: {job_id}")
            
            # Run curator
            curator_output = await self.curator.generate_daily_thread()
            
            # Process with X Bot
            if curator_output and curator_output.get('posts'):
                # Save curator output
                output_path = self._save_curator_output(curator_output)
                
                # Generate draft thread
                draft = await self.x_bot.process_curator_output(output_path)
                
                result.output = {
                    'curator_output': output_path,
                    'draft_id': draft.get('draft_id'),
                    'post_count': len(draft.get('posts', [])),
                    'style_score': draft.get('style_score', 0)
                }
                
                logger.info(f"Daily curator job completed: {job_id}")
                result.status = JobStatus.COMPLETED
            else:
                logger.warning(f"No content generated for daily curator: {job_id}")
                result.status = JobStatus.SKIPPED
                result.output = {'reason': 'No content available'}
            
        except Exception as e:
            logger.error(f"Daily curator job failed: {e}")
            result.status = JobStatus.FAILED
            result.error = str(e)
            
            # Send alert if configured
            if self.config.get('alerts', {}).get('enabled'):
                await self._send_alert(f"Daily curator job failed: {e}")
        
        finally:
            result.completed_at = datetime.now(timezone.utc)
            self.job_history.append(result)
        
        return result
    
    async def _run_weekly_digest(self) -> JobResult:
        """Run the weekly digest generation"""
        job_id = f"weekly_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        result = JobResult(
            job_id=job_id,
            job_type="weekly_digest",
            status=JobStatus.RUNNING,
            started_at=datetime.now(timezone.utc)
        )
        
        try:
            logger.info(f"Starting weekly digest job: {job_id}")
            
            # Generate weekly digest
            digest_output = await self.curator.generate_weekly_digest()
            
            if digest_output:
                # Save digest output
                output_path = self._save_digest_output(digest_output)
                
                result.output = {
                    'digest_output': output_path,
                    'word_count': digest_output.get('word_count', 0),
                    'sections': len(digest_output.get('sections', [])),
                    'sources': digest_output.get('source_count', 0)
                }
                
                logger.info(f"Weekly digest job completed: {job_id}")
                result.status = JobStatus.COMPLETED
            else:
                logger.warning(f"No digest generated: {job_id}")
                result.status = JobStatus.SKIPPED
                result.output = {'reason': 'Insufficient content for digest'}
            
        except Exception as e:
            logger.error(f"Weekly digest job failed: {e}")
            result.status = JobStatus.FAILED
            result.error = str(e)
            
            # Send alert if configured
            if self.config.get('alerts', {}).get('enabled'):
                await self._send_alert(f"Weekly digest job failed: {e}")
        
        finally:
            result.completed_at = datetime.now(timezone.utc)
            self.job_history.append(result)
        
        return result
    
    async def _run_health_check(self) -> JobResult:
        """Run system health check"""
        job_id = f"health_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        result = JobResult(
            job_id=job_id,
            job_type="health_check",
            status=JobStatus.RUNNING,
            started_at=datetime.now(timezone.utc)
        )
        
        try:
            health_status = {
                'scheduler': 'running' if self.running else 'stopped',
                'jobs_scheduled': len(self.jobs),
                'jobs_enabled': sum(1 for j in self.jobs if j.enabled),
                'recent_failures': self._count_recent_failures(),
                'database': await self._check_database_health(),
                'memory_usage': self._get_memory_usage(),
                'disk_space': self._get_disk_space()
            }
            
            result.output = health_status
            result.status = JobStatus.COMPLETED
            
            # Log warnings if issues detected
            if health_status['recent_failures'] > 5:
                logger.warning(f"High failure rate detected: {health_status['recent_failures']} failures in last hour")
            
            if health_status['disk_space'] < 10:  # Less than 10% free
                logger.warning(f"Low disk space: {health_status['disk_space']}% free")
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            result.status = JobStatus.FAILED
            result.error = str(e)
        
        finally:
            result.completed_at = datetime.now(timezone.utc)
            self.job_history.append(result)
        
        return result
    
    def _save_curator_output(self, output: Dict[str, Any]) -> str:
        """Save curator output to file"""
        output_dir = Path(self.config.get('output', {}).get('daily_thread_path', 'output/daily_threads'))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"curator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = output_dir / filename
        
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        
        logger.info(f"Saved curator output to {output_path}")
        return str(output_path)
    
    def _save_digest_output(self, output: Dict[str, Any]) -> str:
        """Save weekly digest output to file"""
        output_dir = Path(self.config.get('output', {}).get('weekly_digest_path', 'output/weekly_digests'))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = output_dir / filename
        
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        
        logger.info(f"Saved digest output to {output_path}")
        return str(output_path)
    
    def _count_recent_failures(self, hours: int = 1) -> int:
        """Count job failures in recent time window"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return sum(
            1 for job in self.job_history
            if job.status == JobStatus.FAILED and job.started_at >= cutoff
        )
    
    async def _check_database_health(self) -> str:
        """Check database connectivity"""
        try:
            # Try to connect to database (implementation depends on your DB)
            # This is a placeholder
            return "healthy"
        except Exception:
            return "unhealthy"
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage percentage"""
        try:
            import psutil
            return psutil.virtual_memory().percent
        except ImportError:
            return 0.0
    
    def _get_disk_space(self) -> float:
        """Get available disk space percentage"""
        try:
            import psutil
            usage = psutil.disk_usage('/')
            return 100 - usage.percent
        except ImportError:
            return 100.0
    
    async def _send_alert(self, message: str):
        """Send alert notification"""
        logger.warning(f"ALERT: {message}")
        
        # Email alert
        if self.config.get('alerts', {}).get('email'):
            # Implement email sending
            pass
        
        # Webhook alert
        if self.config.get('alerts', {}).get('webhook'):
            # Implement webhook posting
            pass
    
    def _schedule_runner(self):
        """Background thread for running scheduled jobs"""
        logger.info("Schedule runner thread started")
        
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Schedule runner error: {e}")
                time.sleep(60)  # Wait a bit longer on error
    
    def start(self):
        """Start the scheduler"""
        if self.running:
            logger.warning("Scheduler is already running")
            return
        
        logger.info("Starting Daily Scheduler...")
        
        # Register all jobs
        self.register_jobs()
        
        # Schedule jobs
        for job in self.jobs:
            if job.enabled:
                def run_job(j=job):
                    asyncio.run(self._execute_job(j))
                
                self._parse_cron_to_schedule(job.cron_expression, run_job)
                logger.info(f"Scheduled job: {job.name} ({job.cron_expression})")
        
        # Start scheduler thread
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._schedule_runner, daemon=True)
        self.scheduler_thread.start()
        
        logger.info("Daily Scheduler started successfully")
    
    async def _execute_job(self, job: JobConfig):
        """Execute a scheduled job with retry logic"""
        retries = 0
        
        while retries <= job.max_retries:
            try:
                logger.info(f"Executing job: {job.name} (attempt {retries + 1}/{job.max_retries + 1})")
                
                # Execute job function
                result = await asyncio.wait_for(
                    job.function(),
                    timeout=job.timeout
                )
                
                if result.status == JobStatus.COMPLETED:
                    return result
                elif result.status == JobStatus.FAILED and retries < job.max_retries:
                    retries += 1
                    logger.warning(f"Job {job.name} failed, retrying in {job.retry_delay} seconds...")
                    await asyncio.sleep(job.retry_delay)
                else:
                    return result
                    
            except asyncio.TimeoutError:
                logger.error(f"Job {job.name} timed out after {job.timeout} seconds")
                if retries < job.max_retries:
                    retries += 1
                    await asyncio.sleep(job.retry_delay)
                else:
                    if job.alert_on_failure:
                        await self._send_alert(f"Job {job.name} failed after {retries + 1} attempts (timeout)")
                    break
                    
            except Exception as e:
                logger.error(f"Job {job.name} failed with error: {e}")
                if retries < job.max_retries:
                    retries += 1
                    await asyncio.sleep(job.retry_delay)
                else:
                    if job.alert_on_failure:
                        await self._send_alert(f"Job {job.name} failed after {retries + 1} attempts: {e}")
                    break
    
    def stop(self):
        """Stop the scheduler"""
        if not self.running:
            logger.warning("Scheduler is not running")
            return
        
        logger.info("Stopping Daily Scheduler...")
        self.running = False
        
        # Clear all scheduled jobs
        schedule.clear()
        
        # Wait for thread to finish
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        
        logger.info("Daily Scheduler stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status and statistics"""
        return {
            'running': self.running,
            'jobs': [
                {
                    'name': job.name,
                    'enabled': job.enabled,
                    'cron': job.cron_expression,
                    'description': job.metadata.get('description', '')
                }
                for job in self.jobs
            ],
            'recent_history': [
                {
                    'job_id': r.job_id,
                    'type': r.job_type,
                    'status': r.status.value,
                    'started': r.started_at.isoformat(),
                    'completed': r.completed_at.isoformat() if r.completed_at else None,
                    'error': r.error
                }
                for r in self.job_history[-10:]  # Last 10 jobs
            ],
            'statistics': {
                'total_jobs_run': len(self.job_history),
                'successful': sum(1 for r in self.job_history if r.status == JobStatus.COMPLETED),
                'failed': sum(1 for r in self.job_history if r.status == JobStatus.FAILED),
                'recent_failures': self._count_recent_failures()
            }
        }


def main():
    """Main entry point for the scheduler"""
    logger.info("="*60)
    logger.info("KOI Daily Scheduler - Starting")
    logger.info("="*60)
    
    # Create scheduler instance
    scheduler = DailyScheduler()
    
    # Start scheduler
    scheduler.start()
    
    try:
        # Keep running until interrupted
        while True:
            time.sleep(60)
            
            # Log status every hour
            if datetime.now().minute == 0:
                status = scheduler.get_status()
                logger.info(f"Scheduler status: {status['statistics']}")
    
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    
    finally:
        scheduler.stop()
        logger.info("Scheduler shutdown complete")


if __name__ == "__main__":
    main()