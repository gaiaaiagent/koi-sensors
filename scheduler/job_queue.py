"""
Job Queue System - Persistent job management with error recovery
Handles job queuing, execution, and failure recovery
"""

import asyncio
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import uuid
from loguru import logger
import pickle
import base64


class JobPriority(Enum):
    """Job priority levels"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class JobState(Enum):
    """Job execution states"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class Job:
    """Represents a queued job"""
    id: str
    type: str
    payload: Dict[str, Any]
    priority: JobPriority
    state: JobState
    created_at: datetime
    scheduled_for: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary"""
        return {
            'id': self.id,
            'type': self.type,
            'payload': json.dumps(self.payload),
            'priority': self.priority.value,
            'state': self.state.value,
            'created_at': self.created_at.isoformat(),
            'scheduled_for': self.scheduled_for.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'error': self.error,
            'result': json.dumps(self.result) if self.result else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Job':
        """Create job from dictionary"""
        return cls(
            id=data['id'],
            type=data['type'],
            payload=json.loads(data['payload']) if isinstance(data['payload'], str) else data['payload'],
            priority=JobPriority(data['priority']),
            state=JobState(data['state']),
            created_at=datetime.fromisoformat(data['created_at']),
            scheduled_for=datetime.fromisoformat(data['scheduled_for']),
            started_at=datetime.fromisoformat(data['started_at']) if data['started_at'] else None,
            completed_at=datetime.fromisoformat(data['completed_at']) if data['completed_at'] else None,
            retry_count=data['retry_count'],
            max_retries=data['max_retries'],
            error=data['error'],
            result=json.loads(data['result']) if data['result'] else None
        )


class JobQueue:
    """
    Persistent job queue with SQLite backend
    Manages job lifecycle with retry logic and error recovery
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize job queue with database"""
        self.db_path = db_path or Path(__file__).parent / "jobs.db"
        self.handlers: Dict[str, Callable] = {}
        self.workers: List[asyncio.Task] = []
        self.running = False
        self.worker_count = 3  # Number of concurrent workers
        
        # Initialize database
        self._init_database()
        
        logger.info(f"Job Queue initialized with database: {self.db_path}")
    
    def _init_database(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                priority INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                scheduled_for TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                error TEXT,
                result TEXT,
                INDEX idx_state (state),
                INDEX idx_scheduled (scheduled_for),
                INDEX idx_priority (priority)
            )
        """)
        
        # Create indices for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_state ON jobs(state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled ON jobs(scheduled_for)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_priority ON jobs(priority)")
        
        conn.commit()
        conn.close()
    
    def register_handler(self, job_type: str, handler: Callable):
        """Register a handler for a job type"""
        self.handlers[job_type] = handler
        logger.info(f"Registered handler for job type: {job_type}")
    
    async def enqueue(
        self,
        job_type: str,
        payload: Dict[str, Any],
        priority: JobPriority = JobPriority.NORMAL,
        scheduled_for: Optional[datetime] = None,
        max_retries: int = 3
    ) -> str:
        """Add a job to the queue"""
        job_id = str(uuid.uuid4())
        
        job = Job(
            id=job_id,
            type=job_type,
            payload=payload,
            priority=priority,
            state=JobState.QUEUED,
            created_at=datetime.now(timezone.utc),
            scheduled_for=scheduled_for or datetime.now(timezone.utc),
            max_retries=max_retries
        )
        
        # Save to database
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        job_dict = job.to_dict()
        cursor.execute("""
            INSERT INTO jobs (
                id, type, payload, priority, state, created_at, 
                scheduled_for, retry_count, max_retries
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_dict['id'],
            job_dict['type'],
            job_dict['payload'],
            job_dict['priority'],
            job_dict['state'],
            job_dict['created_at'],
            job_dict['scheduled_for'],
            job_dict['retry_count'],
            job_dict['max_retries']
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Enqueued job {job_id} of type {job_type} with priority {priority.name}")
        return job_id
    
    async def get_next_job(self) -> Optional[Job]:
        """Get the next job to process"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Get highest priority job that's ready to run
        cursor.execute("""
            SELECT * FROM jobs
            WHERE state IN (?, ?)
            AND scheduled_for <= ?
            ORDER BY priority DESC, scheduled_for ASC
            LIMIT 1
        """, (
            JobState.QUEUED.value,
            JobState.RETRYING.value,
            datetime.now(timezone.utc).isoformat()
        ))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            # Convert row to dict
            columns = ['id', 'type', 'payload', 'priority', 'state', 'created_at',
                      'scheduled_for', 'started_at', 'completed_at', 'retry_count',
                      'max_retries', 'error', 'result']
            job_dict = dict(zip(columns, row))
            return Job.from_dict(job_dict)
        
        return None
    
    async def update_job(self, job: Job):
        """Update job in database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        job_dict = job.to_dict()
        cursor.execute("""
            UPDATE jobs SET
                state = ?,
                started_at = ?,
                completed_at = ?,
                retry_count = ?,
                error = ?,
                result = ?
            WHERE id = ?
        """, (
            job_dict['state'],
            job_dict['started_at'],
            job_dict['completed_at'],
            job_dict['retry_count'],
            job_dict['error'],
            job_dict['result'],
            job_dict['id']
        ))
        
        conn.commit()
        conn.close()
    
    async def _worker(self, worker_id: int):
        """Worker coroutine that processes jobs"""
        logger.info(f"Worker {worker_id} started")
        
        while self.running:
            try:
                # Get next job
                job = await self.get_next_job()
                
                if not job:
                    # No jobs available, wait a bit
                    await asyncio.sleep(5)
                    continue
                
                # Check if we have a handler for this job type
                if job.type not in self.handlers:
                    logger.error(f"No handler registered for job type: {job.type}")
                    job.state = JobState.FAILED
                    job.error = f"No handler for job type: {job.type}"
                    await self.update_job(job)
                    continue
                
                # Mark job as running
                job.state = JobState.RUNNING
                job.started_at = datetime.now(timezone.utc)
                await self.update_job(job)
                
                logger.info(f"Worker {worker_id} processing job {job.id} of type {job.type}")
                
                try:
                    # Execute job handler
                    handler = self.handlers[job.type]
                    result = await handler(job.payload)
                    
                    # Mark job as completed
                    job.state = JobState.COMPLETED
                    job.completed_at = datetime.now(timezone.utc)
                    job.result = result
                    await self.update_job(job)
                    
                    logger.info(f"Worker {worker_id} completed job {job.id}")
                    
                except Exception as e:
                    logger.error(f"Worker {worker_id} failed processing job {job.id}: {e}")
                    
                    # Handle failure
                    job.retry_count += 1
                    job.error = str(e)
                    
                    if job.retry_count < job.max_retries:
                        # Schedule retry
                        job.state = JobState.RETRYING
                        job.scheduled_for = datetime.now(timezone.utc) + timedelta(
                            minutes=5 * job.retry_count  # Exponential backoff
                        )
                        logger.info(f"Scheduling retry {job.retry_count}/{job.max_retries} for job {job.id}")
                    else:
                        # Max retries exceeded
                        job.state = JobState.FAILED
                        job.completed_at = datetime.now(timezone.utc)
                        logger.error(f"Job {job.id} failed after {job.retry_count} retries")
                    
                    await self.update_job(job)
                    
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(10)
        
        logger.info(f"Worker {worker_id} stopped")
    
    async def start(self):
        """Start the job queue workers"""
        if self.running:
            logger.warning("Job queue is already running")
            return
        
        self.running = True
        
        # Start worker tasks
        for i in range(self.worker_count):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
        
        logger.info(f"Started {self.worker_count} workers")
    
    async def stop(self):
        """Stop the job queue workers"""
        if not self.running:
            logger.warning("Job queue is not running")
            return
        
        logger.info("Stopping job queue...")
        self.running = False
        
        # Wait for workers to finish
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
            self.workers.clear()
        
        logger.info("Job queue stopped")
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued job"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE jobs SET state = ?
            WHERE id = ? AND state = ?
        """, (JobState.CANCELLED.value, job_id, JobState.QUEUED.value))
        
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected > 0:
            logger.info(f"Cancelled job {job_id}")
            return True
        else:
            logger.warning(f"Could not cancel job {job_id} (not found or not queued)")
            return False
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific job"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            columns = ['id', 'type', 'payload', 'priority', 'state', 'created_at',
                      'scheduled_for', 'started_at', 'completed_at', 'retry_count',
                      'max_retries', 'error', 'result']
            job_dict = dict(zip(columns, row))
            return {
                'id': job_dict['id'],
                'type': job_dict['type'],
                'state': job_dict['state'],
                'priority': job_dict['priority'],
                'created_at': job_dict['created_at'],
                'scheduled_for': job_dict['scheduled_for'],
                'started_at': job_dict['started_at'],
                'completed_at': job_dict['completed_at'],
                'retry_count': job_dict['retry_count'],
                'error': job_dict['error']
            }
        
        return None
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        stats = {}
        
        # Count jobs by state
        for state in JobState:
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE state = ?", (state.value,))
            count = cursor.fetchone()[0]
            stats[state.value] = count
        
        # Get recent failures
        cursor.execute("""
            SELECT COUNT(*) FROM jobs
            WHERE state = ? AND completed_at > ?
        """, (
            JobState.FAILED.value,
            (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        ))
        stats['recent_failures'] = cursor.fetchone()[0]
        
        # Get average processing time
        cursor.execute("""
            SELECT AVG(julianday(completed_at) - julianday(started_at)) * 86400
            FROM jobs
            WHERE state = ? AND started_at IS NOT NULL AND completed_at IS NOT NULL
        """, (JobState.COMPLETED.value,))
        avg_time = cursor.fetchone()[0]
        stats['avg_processing_time'] = avg_time or 0
        
        conn.close()
        
        return stats
    
    async def cleanup_old_jobs(self, days: int = 7):
        """Remove old completed/failed jobs"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        cursor.execute("""
            DELETE FROM jobs
            WHERE state IN (?, ?, ?)
            AND completed_at < ?
        """, (
            JobState.COMPLETED.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
            cutoff
        ))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"Cleaned up {deleted} old jobs")
        return deleted