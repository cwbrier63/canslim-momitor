"""
CANSLIM Monitor - Phase 2 Service Architecture Tests
Tests for threads, IPC, and service controller components.
"""

import unittest
import threading
import time
import queue
import json
from datetime import datetime, date
from unittest.mock import Mock, MagicMock, patch
import tempfile
import os

# Add project root to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data import DatabaseManager, init_database
from canslim_monitor.data.repositories import RepositoryManager


class TestBaseThread(unittest.TestCase):
    """Test base thread functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shutdown_event = threading.Event()
    
    def tearDown(self):
        """Clean up."""
        self.shutdown_event.set()
    
    def test_thread_creation(self):
        """Test creating a base thread subclass."""
        from service.threads.base_thread import BaseThread
        
        class TestThread(BaseThread):
            def __init__(self, shutdown_event):
                super().__init__(
                    name='test',
                    shutdown_event=shutdown_event,
                    poll_interval=1,
                    market_hours_only=False
                )
                self.work_count = 0
            
            def do_work(self):
                self.work_count += 1
                return {'count': self.work_count}
        
        thread = TestThread(self.shutdown_event)
        self.assertEqual(thread.name, 'test')
        self.assertEqual(thread.poll_interval, 1)
        self.assertFalse(thread.market_hours_only)
    
    def test_thread_runs_work(self):
        """Test that thread executes do_work."""
        from service.threads.base_thread import BaseThread
        
        class TestThread(BaseThread):
            def __init__(self, shutdown_event):
                super().__init__(
                    name='test',
                    shutdown_event=shutdown_event,
                    poll_interval=0.1,
                    market_hours_only=False
                )
                self.work_count = 0
            
            def do_work(self):
                self.work_count += 1
                if self.work_count >= 3:
                    self.shutdown_event.set()
                return {'count': self.work_count}
        
        thread = TestThread(self.shutdown_event)
        thread.start()
        thread.join(timeout=2)
        
        self.assertGreaterEqual(thread.work_count, 3)
    
    def test_thread_status(self):
        """Test getting thread status."""
        from service.threads.base_thread import BaseThread
        
        class TestThread(BaseThread):
            def __init__(self, shutdown_event):
                super().__init__(
                    name='test',
                    shutdown_event=shutdown_event,
                    poll_interval=1,
                    market_hours_only=False
                )
            
            def do_work(self):
                return {}
        
        thread = TestThread(self.shutdown_event)
        status = thread.get_status()
        
        self.assertEqual(status['name'], 'test')
        self.assertEqual(status['status'], 'initialized')
        self.assertEqual(status['run_count'], 0)
        self.assertEqual(status['error_count'], 0)
    
    def test_thread_manager(self):
        """Test thread manager functionality."""
        from service.threads.base_thread import BaseThread, ThreadManager
        
        class TestThread(BaseThread):
            def __init__(self, name, shutdown_event):
                super().__init__(
                    name=name,
                    shutdown_event=shutdown_event,
                    poll_interval=0.1,
                    market_hours_only=False
                )
            
            def do_work(self):
                return {}
        
        manager = ThreadManager()
        
        thread1 = TestThread('test1', manager.shutdown_event)
        thread2 = TestThread('test2', manager.shutdown_event)
        
        manager.register(thread1)
        manager.register(thread2)
        
        self.assertEqual(len(manager.threads), 2)
        self.assertIn('test1', manager.threads)
        self.assertIn('test2', manager.threads)
        
        # Start and stop
        manager.start_all()
        time.sleep(0.2)
        manager.stop_all(timeout=1)
        
        # Check status
        status = manager.get_status()
        self.assertIn('test1', status)
        self.assertIn('test2', status)


class TestBreakoutThread(unittest.TestCase):
    """Test breakout thread functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shutdown_event = threading.Event()
        
        # Create temp database
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db = init_database(db_path=self.db_path)
    
    def tearDown(self):
        """Clean up."""
        self.shutdown_event.set()
        self.db.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
    
    def test_thread_creation(self):
        """Test creating breakout thread."""
        from service.threads import BreakoutThread
        
        thread = BreakoutThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=60,
            market_hours_only=False
        )
        
        self.assertEqual(thread.name, 'breakout')
        self.assertEqual(thread.poll_interval, 60)
    
    def test_do_work_no_positions(self):
        """Test do_work with no positions."""
        from service.threads import BreakoutThread
        
        thread = BreakoutThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=60,
            market_hours_only=False
        )
        
        result = thread.do_work()
        
        self.assertEqual(result['checked'], 0)
        self.assertEqual(result['breakouts'], 0)
    
    def test_do_work_with_positions(self):
        """Test do_work with watching positions."""
        from service.threads import BreakoutThread
        
        # Add a watching position
        session = self.db.get_new_session()
        repos = RepositoryManager(session)
        repos.positions.create(
            symbol='TEST',
            portfolio='IRA',
            state=0,  # Watching
            pivot=100.0,
            rs_rating=90
        )
        session.commit()
        session.close()
        
        thread = BreakoutThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=60,
            market_hours_only=False
        )
        
        result = thread.do_work()
        
        self.assertEqual(result['checked'], 1)
    
    def test_cooldown_tracking(self):
        """Test cooldown functionality."""
        from service.threads import BreakoutThread
        
        thread = BreakoutThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=60,
            market_hours_only=False
        )
        
        # Initially not in cooldown
        self.assertFalse(thread._in_cooldown('TEST'))
        
        # Update cooldown
        thread._cooldown_cache['TEST'] = datetime.now()
        
        # Now in cooldown
        self.assertTrue(thread._in_cooldown('TEST'))
        
        # Clear cooldown
        thread.clear_cooldown('TEST')
        self.assertFalse(thread._in_cooldown('TEST'))
    
    def test_score_calculation_fallback(self):
        """Test fallback scoring without scoring engine."""
        from service.threads import BreakoutThread
        
        thread = BreakoutThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=60,
            market_hours_only=False
        )
        
        # Create mock position
        position = Mock()
        position.rs_rating = 95
        
        result = thread._calculate_score(position, {}, 'BULLISH')
        
        self.assertEqual(result['grade'], 'A')
        self.assertEqual(result['score'], 20)
        
        # Test lower RS rating
        position.rs_rating = 75
        result = thread._calculate_score(position, {}, 'BULLISH')
        
        self.assertEqual(result['grade'], 'C')


class TestPositionThread(unittest.TestCase):
    """Test position thread functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shutdown_event = threading.Event()
        
        # Create temp database
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db = init_database(db_path=self.db_path)
    
    def tearDown(self):
        """Clean up."""
        self.shutdown_event.set()
        self.db.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
    
    def test_thread_creation(self):
        """Test creating position thread."""
        from service.threads import PositionThread
        
        thread = PositionThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=30,
            market_hours_only=False
        )
        
        self.assertEqual(thread.name, 'position')
        self.assertEqual(thread.poll_interval, 30)
    
    def test_do_work_no_positions(self):
        """Test do_work with no active positions."""
        from service.threads import PositionThread
        
        thread = PositionThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=30,
            market_hours_only=False
        )
        
        result = thread.do_work()
        
        self.assertEqual(result['checked'], 0)
        self.assertEqual(result['alerts'], 0)
    
    def test_health_score_calculation(self):
        """Test health score calculation."""
        from service.threads import PositionThread
        
        thread = PositionThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=30,
            market_hours_only=False
        )
        
        # Create mock position
        position = Mock()
        position.avg_cost = 100.0
        position.rs_rating = 90
        
        # Profitable position above MAs
        price_data = {
            'ma50': 95.0,
            'ma21': 98.0,
            'volume_ratio': 1.5
        }
        
        score = thread._calculate_health_score(position, 110.0, price_data)
        
        # Should have high score
        self.assertGreater(score, 70)
    
    def test_score_to_rating(self):
        """Test score to rating conversion."""
        from service.threads import PositionThread
        
        thread = PositionThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=30,
            market_hours_only=False
        )
        
        self.assertEqual(thread._score_to_rating(85), 'EXCELLENT')
        self.assertEqual(thread._score_to_rating(65), 'GOOD')
        self.assertEqual(thread._score_to_rating(45), 'FAIR')
        self.assertEqual(thread._score_to_rating(30), 'POOR')
    
    def test_cooldown_tracking(self):
        """Test position thread cooldown."""
        from service.threads import PositionThread
        
        thread = PositionThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=30,
            market_hours_only=False
        )
        
        # Not in cooldown initially
        self.assertFalse(thread._in_cooldown('TEST', 'STOP', 'WARNING'))
        
        # Update cooldown
        thread._update_cooldown('TEST', 'STOP', 'WARNING')
        
        # Now in cooldown
        self.assertTrue(thread._in_cooldown('TEST', 'STOP', 'WARNING'))


class TestMarketThread(unittest.TestCase):
    """Test market thread functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.shutdown_event = threading.Event()
        
        # Create temp database
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db = init_database(db_path=self.db_path)
    
    def tearDown(self):
        """Clean up."""
        self.shutdown_event.set()
        self.db.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
    
    def test_thread_creation(self):
        """Test creating market thread."""
        from service.threads import MarketThread
        
        thread = MarketThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=300,
            market_hours_only=False
        )
        
        self.assertEqual(thread.name, 'market')
        self.assertEqual(thread.poll_interval, 300)
    
    def test_regime_classification(self):
        """Test market regime classification."""
        from service.threads import MarketThread
        
        thread = MarketThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=300,
            market_hours_only=False
        )
        
        self.assertEqual(thread._classify_regime(50), 'BULLISH')
        self.assertEqual(thread._classify_regime(0), 'NEUTRAL')
        self.assertEqual(thread._classify_regime(-50), 'BEARISH')
    
    def test_exposure_calculation(self):
        """Test exposure level calculation."""
        from service.threads import MarketThread
        
        thread = MarketThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=300,
            market_hours_only=False
        )
        
        # Full bullish
        self.assertEqual(thread._calculate_exposure('BULLISH', 70), 5)
        
        # Moderate bullish
        self.assertEqual(thread._calculate_exposure('BULLISH', 35), 3)
        
        # Bearish
        self.assertEqual(thread._calculate_exposure('BEARISH', -70), 1)
        
        # Neutral
        self.assertEqual(thread._calculate_exposure('NEUTRAL', 0), 3)
    
    def test_distribution_day_detection(self):
        """Test distribution day detection."""
        from service.threads import MarketThread
        
        thread = MarketThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=300,
            market_hours_only=False
        )
        
        # Distribution day: decline with higher volume
        data = {
            'last': 99.5,
            'prev_close': 100.0,
            'volume': 1_000_000,
            'prev_volume': 900_000
        }
        
        self.assertTrue(thread._is_distribution_day(data))
        
        # Not a distribution day: up day
        data['last'] = 101.0
        self.assertFalse(thread._is_distribution_day(data))
        
        # Not a distribution day: low volume
        data['last'] = 99.5
        data['volume'] = 800_000
        self.assertFalse(thread._is_distribution_day(data))
    
    def test_index_analysis(self):
        """Test single index analysis."""
        from service.threads import MarketThread
        
        thread = MarketThread(
            shutdown_event=self.shutdown_event,
            db=self.db,
            poll_interval=300,
            market_hours_only=False
        )
        
        data = {
            'last': 450.0,
            'prev_close': 445.0,
            'ma50': 440.0,
            'ma200': 420.0
        }
        
        analysis = thread._analyze_index(data, 'SPY')
        
        self.assertEqual(analysis['symbol'], 'SPY')
        self.assertEqual(analysis['price'], 450.0)
        self.assertTrue(analysis['above_50ma'])
        self.assertTrue(analysis['above_200ma'])
        self.assertAlmostEqual(analysis['daily_change_pct'], 1.12, places=1)


class TestIPCMessage(unittest.TestCase):
    """Test IPC message serialization."""
    
    def test_message_creation(self):
        """Test creating an IPC message."""
        from service.ipc.pipe_server import IPCMessage
        
        msg = IPCMessage(
            msg_type='GET_STATUS',
            data={'filter': 'active'}
        )
        
        self.assertEqual(msg.type, 'GET_STATUS')
        self.assertEqual(msg.data['filter'], 'active')
        self.assertIsNotNone(msg.request_id)
        self.assertIsNotNone(msg.timestamp)
    
    def test_message_serialization(self):
        """Test message to/from JSON."""
        from service.ipc.pipe_server import IPCMessage
        
        msg = IPCMessage(
            msg_type='FORCE_CHECK',
            data={'symbol': 'NVDA'},
            request_id='test-123'
        )
        
        json_str = msg.to_json()
        parsed = IPCMessage.from_json(json_str)
        
        self.assertEqual(parsed.type, 'FORCE_CHECK')
        self.assertEqual(parsed.data['symbol'], 'NVDA')
        self.assertEqual(parsed.request_id, 'test-123')
    
    def test_response_creation(self):
        """Test creating an IPC response."""
        from service.ipc.pipe_server import IPCResponse
        
        response = IPCResponse(
            request_id='test-123',
            status='success',
            data={'positions': 10}
        )
        
        self.assertEqual(response.request_id, 'test-123')
        self.assertEqual(response.status, 'success')
        self.assertEqual(response.data['positions'], 10)
    
    def test_error_response(self):
        """Test error response."""
        from service.ipc.pipe_server import IPCResponse
        
        response = IPCResponse(
            request_id='test-456',
            status='error',
            error='Position not found'
        )
        
        json_str = response.to_json()
        parsed = json.loads(json_str)
        
        self.assertEqual(parsed['status'], 'error')
        self.assertEqual(parsed['error'], 'Position not found')


class TestServiceController(unittest.TestCase):
    """Test service controller functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temp database
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
    
    def tearDown(self):
        """Clean up."""
        os.close(self.db_fd)
        try:
            os.unlink(self.db_path)
        except:
            pass
    
    def test_controller_creation(self):
        """Test creating service controller."""
        from service.service_controller import ServiceController
        
        controller = ServiceController(
            db_path=self.db_path
        )
        
        self.assertIsNotNone(controller)
        self.assertEqual(controller._status, 'initialized')
    
    def test_config_defaults(self):
        """Test default configuration loading."""
        from service.service_controller import ServiceController
        
        controller = ServiceController(
            db_path=self.db_path
        )
        
        controller._load_config()
        
        self.assertIn('service', controller._config)
        self.assertIn('ibkr', controller._config)
        self.assertIn('alerts', controller._config)
        
        # Check defaults
        self.assertEqual(
            controller._config['service']['poll_interval_breakout'],
            60
        )
        self.assertEqual(
            controller._config['ibkr']['port'],
            7497
        )
    
    def test_get_status_handler(self):
        """Test GET_STATUS command handler."""
        from service.service_controller import ServiceController
        
        controller = ServiceController(
            db_path=self.db_path
        )
        
        # Initialize minimally for testing
        controller._started_at = datetime.now()
        controller._status = 'running'
        controller.thread_manager.threads = {}
        controller.pipe_server = None
        controller.db = Mock()
        controller.db.get_stats.return_value = {'file_size_mb': 1.0}
        
        result = controller._get_status()
        
        self.assertEqual(result['status'], 'running')
        self.assertIn('uptime_seconds', result)
        self.assertIn('threads', result)
    
    def test_ipc_command_routing(self):
        """Test IPC command routing."""
        from service.service_controller import ServiceController
        
        controller = ServiceController(
            db_path=self.db_path
        )
        
        # Test unknown command
        result = controller._handle_ipc_command({'type': 'UNKNOWN_CMD'})
        self.assertIn('error', result)
        
        # Mock get_status for testing
        controller._started_at = datetime.now()
        controller._status = 'testing'
        controller.thread_manager.threads = {}
        controller.pipe_server = None
        controller.db = Mock()
        controller.db.get_stats.return_value = {}
        
        result = controller._handle_ipc_command({'type': 'GET_STATUS'})
        self.assertNotIn('error', result)
        self.assertEqual(result['status'], 'testing')


class TestMockIPCServerClient(unittest.TestCase):
    """Test mock IPC server/client for non-Windows testing."""
    
    def test_mock_server_client_communication(self):
        """Test mock server and client can communicate."""
        from service.ipc.pipe_server import MockPipeServer
        from service.ipc.pipe_client import MockIPCClient
        
        shutdown_event = threading.Event()
        command_queue = queue.Queue()
        
        def handler(cmd):
            if cmd['type'] == 'TEST':
                return {'result': 'success'}
            return {'error': 'unknown'}
        
        # Start mock server
        server = MockPipeServer(
            command_queue=command_queue,
            shutdown_event=shutdown_event,
            command_handler=handler,
            port=19999
        )
        server.start()
        time.sleep(0.2)  # Let server start
        
        try:
            # Create and connect client
            client = MockIPCClient(port=19999)
            connected = client.connect(timeout=2.0)
            
            if connected:
                # Test ping
                pong = client.ping()
                self.assertTrue(pong)
                
                # Test custom command
                result = client.send_command('TEST', {})
                self.assertEqual(result.get('result'), 'success')
                
                client.disconnect()
        finally:
            shutdown_event.set()
            server.join(timeout=1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
