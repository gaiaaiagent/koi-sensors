"""
Test Suite for Scheduling & Automation System
Tests the complete automation cycle from scheduling to execution
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
import unittest
from unittest.mock import Mock, patch, AsyncMock
from loguru import logger

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent / "koi-processor"))

from scheduler.daily_scheduler import DailyScheduler, JobStatus, JobResult, JobConfig
from scheduler.job_queue import JobQueue, Job, JobState, JobPriority
from scheduler.monitoring import MonitoringSystem, HealthStatus, AlertLevel


class TestDailyScheduler(unittest.TestCase):
    """Test cases for the Daily Scheduler"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_config = {
            'scheduler': {
                'daily_cron': '0 12 * * 1-5',
                'weekly_cron': '0 14 * * 5',
                'timezone': 'America/New_York'
            },
            'alerts': {
                'enabled': False
            }
        }
        
        # Create temp config file
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        import yaml
        yaml.dump(self.test_config, self.temp_config)
        self.temp_config.close()
        
        self.scheduler = DailyScheduler(self.temp_config.name)
    
    def tearDown(self):
        """Clean up test fixtures"""
        Path(self.temp_config.name).unlink()
    
    def test_scheduler_initialization(self):
        """Test scheduler initializes correctly"""
        self.assertIsNotNone(self.scheduler)
        self.assertFalse(self.scheduler.running)
        self.assertEqual(len(self.scheduler.jobs), 0)
    
    def test_job_registration(self):
        """Test job registration"""
        self.scheduler.register_jobs()
        
        # Should have daily, weekly, and health check jobs
        self.assertGreaterEqual(len(self.scheduler.jobs), 3)
        
        # Check job names
        job_names = [job.name for job in self.scheduler.jobs]
        self.assertIn('daily_curator', job_names)
        self.assertIn('weekly_digest', job_names)
        self.assertIn('health_check', job_names)
    
    def test_cron_parsing(self):
        """Test cron expression parsing"""
        # Mock schedule module
        with patch('scheduler.daily_scheduler.schedule') as mock_schedule:
            job_func = Mock()
            
            # Test weekday cron
            self.scheduler._parse_cron_to_schedule('0 12 * * 1-5', job_func)
            self.assertEqual(mock_schedule.every().monday.at.call_count, 1)
            self.assertEqual(mock_schedule.every().friday.at.call_count, 1)
            
            # Test Friday only cron
            self.scheduler._parse_cron_to_schedule('0 14 * * 5', job_func)
            
            # Test interval cron
            self.scheduler._parse_cron_to_schedule('*/5 * * * *', job_func)
            mock_schedule.every.assert_called()
    
    @patch('scheduler.daily_scheduler.DailyCurator')
    @patch('scheduler.daily_scheduler.XDailyBot')
    async def test_daily_curator_job(self, mock_bot, mock_curator):
        """Test daily curator job execution"""
        # Setup mocks
        mock_curator_instance = AsyncMock()
        mock_curator_instance.generate_daily_thread.return_value = {
            'posts': [{'content': 'test'}],
            'thread_date': datetime.now().isoformat()
        }
        mock_curator.return_value = mock_curator_instance
        
        mock_bot_instance = AsyncMock()
        mock_bot_instance.process_curator_output.return_value = {
            'draft_id': 'test-draft-123',
            'posts': [{'content': 'test'}],
            'style_score': 0.95
        }
        mock_bot.return_value = mock_bot_instance
        
        # Reinitialize scheduler with mocks
        self.scheduler._init_components()
        
        # Run daily curator job
        result = await self.scheduler._run_daily_curator()
        
        # Check result
        self.assertEqual(result.status, JobStatus.COMPLETED)
        self.assertIsNotNone(result.output)
        self.assertEqual(result.output['draft_id'], 'test-draft-123')
    
    def test_job_history_tracking(self):
        """Test job history is tracked correctly"""
        # Create test job results
        for i in range(5):
            result = JobResult(
                job_id=f"test_{i}",
                job_type="test",
                status=JobStatus.COMPLETED if i % 2 == 0 else JobStatus.FAILED,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc)
            )
            self.scheduler.job_history.append(result)
        
        # Check history
        self.assertEqual(len(self.scheduler.job_history), 5)
        
        # Check failure counting
        failures = self.scheduler._count_recent_failures(hours=1)
        self.assertEqual(failures, 2)
    
    def test_scheduler_status(self):
        """Test scheduler status reporting"""
        self.scheduler.register_jobs()
        status = self.scheduler.get_status()
        
        self.assertIn('running', status)
        self.assertIn('jobs', status)
        self.assertIn('statistics', status)
        self.assertFalse(status['running'])
        self.assertGreaterEqual(len(status['jobs']), 3)


class TestJobQueue(unittest.IsolatedAsyncioTestCase):
    """Test cases for the Job Queue system"""
    
    async def asyncSetUp(self):
        """Set up async test fixtures"""
        # Use temp database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        
        self.queue = JobQueue(self.temp_db.name)
        
        # Register test handler
        async def test_handler(payload):
            await asyncio.sleep(0.1)
            return {'result': 'success', 'payload': payload}
        
        self.queue.register_handler('test_job', test_handler)
    
    async def asyncTearDown(self):
        """Clean up async test fixtures"""
        await self.queue.stop()
        Path(self.temp_db.name).unlink()
    
    async def test_job_enqueue(self):
        """Test job enqueueing"""
        job_id = await self.queue.enqueue(
            'test_job',
            {'data': 'test'},
            priority=JobPriority.HIGH
        )
        
        self.assertIsNotNone(job_id)
        
        # Check job status
        status = await self.queue.get_job_status(job_id)
        self.assertEqual(status['type'], 'test_job')
        self.assertEqual(status['state'], JobState.QUEUED.value)
        self.assertEqual(status['priority'], JobPriority.HIGH.value)
    
    async def test_job_processing(self):
        """Test job processing by workers"""
        # Start queue
        await self.queue.start()
        
        # Enqueue job
        job_id = await self.queue.enqueue(
            'test_job',
            {'data': 'test'}
        )
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Check job completed
        status = await self.queue.get_job_status(job_id)
        self.assertEqual(status['state'], JobState.COMPLETED.value)
    
    async def test_job_failure_and_retry(self):
        """Test job failure and retry logic"""
        # Register failing handler
        attempt_count = 0
        
        async def failing_handler(payload):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception("Test failure")
            return {'result': 'success after retries'}
        
        self.queue.register_handler('failing_job', failing_handler)
        
        # Start queue
        await self.queue.start()
        
        # Enqueue job
        job_id = await self.queue.enqueue(
            'failing_job',
            {'data': 'test'},
            max_retries=3
        )
        
        # Wait for retries
        await asyncio.sleep(2)
        
        # Check job eventually succeeded
        status = await self.queue.get_job_status(job_id)
        self.assertIn(status['state'], [JobState.COMPLETED.value, JobState.RETRYING.value])
    
    async def test_job_cancellation(self):
        """Test job cancellation"""
        # Enqueue job
        job_id = await self.queue.enqueue(
            'test_job',
            {'data': 'test'}
        )
        
        # Cancel job
        cancelled = await self.queue.cancel_job(job_id)
        self.assertTrue(cancelled)
        
        # Check job status
        status = await self.queue.get_job_status(job_id)
        self.assertEqual(status['state'], JobState.CANCELLED.value)
    
    async def test_queue_statistics(self):
        """Test queue statistics"""
        # Enqueue multiple jobs
        for i in range(5):
            await self.queue.enqueue(
                'test_job',
                {'data': f'test_{i}'}
            )
        
        # Get statistics
        stats = await self.queue.get_queue_stats()
        
        self.assertIn('queued', stats)
        self.assertEqual(stats['queued'], 5)
        self.assertIn('avg_processing_time', stats)


class TestMonitoringSystem(unittest.IsolatedAsyncioTestCase):
    """Test cases for the Monitoring System"""
    
    async def asyncSetUp(self):
        """Set up async test fixtures"""
        self.config = {
            'monitoring': {
                'metrics_port': 8299  # Use different port for tests
            },
            'alerts': {
                'enabled': False
            },
            'thresholds': {
                'test.metric': {
                    'max': 100,
                    'min': 10
                }
            }
        }
        
        self.monitor = MonitoringSystem(self.config)
    
    async def asyncTearDown(self):
        """Clean up async test fixtures"""
        await self.monitor.stop()
    
    async def test_metric_collection(self):
        """Test metric collection"""
        await self.monitor.collect_metric('test.metric', 50, 'units')
        
        self.assertEqual(len(self.monitor.metrics), 1)
        metric = self.monitor.metrics[0]
        self.assertEqual(metric.name, 'test.metric')
        self.assertEqual(metric.value, 50)
        self.assertEqual(metric.unit, 'units')
    
    async def test_threshold_alerts(self):
        """Test threshold violation alerts"""
        # Collect metric above threshold
        await self.monitor.collect_metric('test.metric', 150, 'units')
        
        # Check alert created
        self.assertEqual(len(self.monitor.alerts), 1)
        alert = self.monitor.alerts[0]
        self.assertEqual(alert.level, AlertLevel.WARNING)
        self.assertIn('exceeded maximum', alert.message)
        
        # Collect metric below threshold
        await self.monitor.collect_metric('test.metric', 5, 'units')
        
        # Check second alert created
        self.assertEqual(len(self.monitor.alerts), 2)
    
    async def test_health_checks(self):
        """Test health check registration and execution"""
        # Register health check
        async def test_check():
            return {'status': 'healthy', 'details': 'test'}
        
        self.monitor.register_health_check('test_check', test_check)
        
        # Get health status
        status = await self.monitor.get_health_status()
        
        self.assertEqual(status['status'], HealthStatus.HEALTHY.value)
        self.assertIn('test_check', status['checks'])
        self.assertEqual(status['checks']['test_check']['status'], 'healthy')
    
    async def test_alert_creation(self):
        """Test alert creation and management"""
        await self.monitor.send_alert(
            AlertLevel.ERROR,
            'test_component',
            'Test error message',
            {'key': 'value'}
        )
        
        self.assertEqual(len(self.monitor.alerts), 1)
        alert = self.monitor.alerts[0]
        self.assertEqual(alert.level, AlertLevel.ERROR)
        self.assertEqual(alert.component, 'test_component')
        self.assertFalse(alert.resolved)
    
    async def test_statistics(self):
        """Test statistics generation"""
        # Add some test data
        for i in range(10):
            await self.monitor.collect_metric(f'test.metric.{i}', i * 10, 'units')
        
        await self.monitor.send_alert(AlertLevel.INFO, 'test', 'Info')
        await self.monitor.send_alert(AlertLevel.WARNING, 'test', 'Warning')
        
        # Get statistics
        stats = await self.monitor.get_statistics()
        
        self.assertEqual(stats['metrics']['total'], 10)
        self.assertEqual(stats['alerts']['total'], 2)
        self.assertEqual(stats['alerts']['by_level']['info'], 1)
        self.assertEqual(stats['alerts']['by_level']['warning'], 1)


class TestIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the complete system"""
    
    async def test_end_to_end_automation(self):
        """Test complete automation cycle"""
        # Setup components
        config = {
            'scheduler': {
                'daily_cron': '0 12 * * 1-5',
                'weekly_cron': '0 14 * * 5',
                'timezone': 'America/New_York'
            },
            'alerts': {'enabled': False},
            'monitoring': {'metrics_port': 8298}
        }
        
        # Create temp config
        temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        import yaml
        yaml.dump(config, temp_config)
        temp_config.close()
        
        try:
            # Initialize components
            scheduler = DailyScheduler(temp_config.name)
            
            temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
            temp_db.close()
            queue = JobQueue(temp_db.name)
            
            monitor = MonitoringSystem(config)
            
            # Register health checks
            async def scheduler_health():
                return {
                    'status': 'healthy' if scheduler.running else 'unhealthy',
                    'jobs': len(scheduler.jobs)
                }
            
            monitor.register_health_check('scheduler', scheduler_health)
            
            # Start monitoring
            await monitor.start()
            
            # Register and start scheduler
            scheduler.register_jobs()
            scheduler.start()
            
            # Start job queue
            await queue.start()
            
            # Wait a bit
            await asyncio.sleep(1)
            
            # Check health
            health = await monitor.get_health_status()
            self.assertIn('status', health)
            
            # Check scheduler status
            status = scheduler.get_status()
            self.assertTrue(status['running'])
            self.assertGreaterEqual(len(status['jobs']), 3)
            
            # Check queue stats
            stats = await queue.get_queue_stats()
            self.assertIn('queued', stats)
            
            # Stop everything
            scheduler.stop()
            await queue.stop()
            await monitor.stop()
            
        finally:
            # Cleanup
            Path(temp_config.name).unlink()
            Path(temp_db.name).unlink()


def run_tests():
    """Run all tests"""
    # Configure logging for tests
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestDailyScheduler))
    suite.addTests(loader.loadTestsFromTestCase(TestJobQueue))
    suite.addTests(loader.loadTestsFromTestCase(TestMonitoringSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)