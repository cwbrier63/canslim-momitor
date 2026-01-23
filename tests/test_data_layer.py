"""
CANSLIM Monitor - Unit Tests for Data Layer
Phase 1: Database Foundation

Tests for database models, repositories, and seeding functionality.
"""

import os
import sys
import unittest
from datetime import datetime, date, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from canslim_monitor.data.database import DatabaseManager, init_database
from canslim_monitor.data.models import Position, Alert, DailySnapshot, Outcome, MarketRegime, Config
from canslim_monitor.data.repositories import (
    RepositoryManager,
    PositionRepository,
    AlertRepository,
    SnapshotRepository,
    OutcomeRepository,
    MarketRegimeRepository,
    ConfigRepository
)


class TestDatabaseManager(unittest.TestCase):
    """Tests for DatabaseManager class."""
    
    def setUp(self):
        """Set up test database."""
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
    
    def tearDown(self):
        """Clean up test database."""
        self.db.close()
    
    def test_initialization(self):
        """Test database initializes correctly."""
        self.assertTrue(self.db._initialized)
    
    def test_session_context_manager(self):
        """Test session context manager works."""
        with self.db.get_session() as session:
            self.assertIsNotNone(session)
    
    def test_stats(self):
        """Test database statistics."""
        stats = self.db.get_stats()
        self.assertIn('positions_count', stats)
        self.assertIn('config_count', stats)
        self.assertGreater(stats['config_count'], 0)  # Default config seeded


class TestPositionRepository(unittest.TestCase):
    """Tests for PositionRepository class."""
    
    def setUp(self):
        """Set up test database and repository."""
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = PositionRepository(self.session)
    
    def tearDown(self):
        """Clean up."""
        self.session.close()
        self.db.close()
    
    def test_create_position(self):
        """Test creating a position."""
        position = self.repo.create(
            symbol='NVDA',
            pivot=120.0,
            pattern='Cup w/Handle',
            portfolio='CWB'
        )
        
        self.assertIsNotNone(position.id)
        self.assertEqual(position.symbol, 'NVDA')
        self.assertEqual(position.pivot, 120.0)
        self.assertEqual(position.state, 0)
    
    def test_create_watchlist_item(self):
        """Test creating a watchlist item."""
        position = self.repo.create_watchlist_item(
            symbol='AAPL',
            pivot=200.0,
            pattern='Flat Base',
            rs_rating=95
        )
        
        self.assertEqual(position.state, 0)
        self.assertEqual(position.rs_rating, 95)
        self.assertEqual(position.watch_date, date.today())
    
    def test_get_by_symbol(self):
        """Test getting position by symbol."""
        self.repo.create(symbol='TSLA', pivot=250.0, pattern='Double Bottom')
        self.session.commit()
        
        position = self.repo.get_by_symbol('TSLA')
        self.assertIsNotNone(position)
        self.assertEqual(position.symbol, 'TSLA')
        
        # Test case insensitivity
        position = self.repo.get_by_symbol('tsla')
        self.assertIsNotNone(position)
    
    def test_get_watching(self):
        """Test getting watching positions."""
        self.repo.create(symbol='MSFT', pivot=400.0, pattern='Base', state=0)
        self.repo.create(symbol='GOOG', pivot=150.0, pattern='Base', state=1)
        self.session.commit()
        
        watching = self.repo.get_watching()
        self.assertEqual(len(watching), 1)
        self.assertEqual(watching[0].symbol, 'MSFT')
    
    def test_get_in_position(self):
        """Test getting in-position positions."""
        self.repo.create(symbol='AMZN', pivot=180.0, pattern='Base', state=0)
        self.repo.create(symbol='META', pivot=500.0, pattern='Base', state=2)
        self.session.commit()
        
        in_position = self.repo.get_in_position()
        self.assertEqual(len(in_position), 1)
        self.assertEqual(in_position[0].symbol, 'META')
    
    def test_update_price(self):
        """Test updating position price."""
        position = self.repo.create(
            symbol='SHOP',
            pivot=100.0,
            pattern='Cup',
            e1_price=100.0,
            e1_shares=100
        )
        position.avg_cost = 100.0
        self.session.commit()
        
        self.repo.update_price(position, 110.0)
        
        self.assertEqual(position.last_price, 110.0)
        self.assertAlmostEqual(position.current_pnl_pct, 10.0, places=2)
    
    def test_transition_state(self):
        """Test state transition."""
        position = self.repo.create(symbol='CRM', pivot=300.0, pattern='Base', state=0)
        self.session.commit()
        
        self.repo.transition_state(position, 1, entry_date=date.today())
        
        self.assertEqual(position.state, 1)
        self.assertIsNotNone(position.state_updated_at)
        self.assertEqual(position.entry_date, date.today())
    
    def test_search(self):
        """Test position search."""
        self.repo.create(symbol='AMD', pivot=150.0, pattern='Cup', rs_rating=92)
        self.repo.create(symbol='INTC', pivot=50.0, pattern='Flat', rs_rating=65)
        self.session.commit()
        
        # Search by RS rating
        results = self.repo.search(min_rs=90)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].symbol, 'AMD')
        
        # Search by pattern
        results = self.repo.search(pattern='Flat')
        self.assertEqual(len(results), 1)
    
    def test_bulk_update_prices(self):
        """Test bulk price updates."""
        self.repo.create(symbol='UBER', pivot=70.0, pattern='Base')
        self.repo.create(symbol='LYFT', pivot=15.0, pattern='Base')
        self.session.commit()
        
        prices = {'UBER': 75.0, 'LYFT': 16.0}
        updated = self.repo.bulk_update_prices(prices)
        
        self.assertEqual(updated, 2)
        
        uber = self.repo.get_by_symbol('UBER')
        self.assertEqual(uber.last_price, 75.0)
    
    def test_delete_position(self):
        """Test deleting a position."""
        position = self.repo.create(symbol='COIN', pivot=250.0, pattern='Base')
        self.session.commit()
        
        result = self.repo.delete_by_symbol('COIN')
        self.assertTrue(result)
        
        position = self.repo.get_by_symbol('COIN')
        self.assertIsNone(position)


class TestAlertRepository(unittest.TestCase):
    """Tests for AlertRepository class."""
    
    def setUp(self):
        """Set up test database and repository."""
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = AlertRepository(self.session)
    
    def tearDown(self):
        """Clean up."""
        self.session.close()
        self.db.close()
    
    def test_create_breakout_alert(self):
        """Test creating a breakout alert."""
        alert = self.repo.create_breakout_alert(
            symbol='NVDA',
            price=125.0,
            pivot=120.0,
            grade='A',
            score=22,
            volume_ratio=2.5
        )
        
        self.assertIsNotNone(alert.id)
        self.assertEqual(alert.alert_type, 'BREAKOUT')
        self.assertEqual(alert.canslim_grade, 'A')
        self.assertIsNotNone(alert.alert_time)
    
    def test_create_position_alert(self):
        """Test creating a position alert."""
        # First create a position to link the alert to
        from data.repositories.position_repo import PositionRepository
        pos_repo = PositionRepository(self.session)
        position = pos_repo.create(
            symbol='AAPL',
            pivot=200.0,
            state=1  # In position
        )
        self.session.flush()
        
        alert = self.repo.create_position_alert(
            symbol='AAPL',
            alert_type='PYRAMID',
            alert_subtype='PY1_READY',
            price=205.0,
            position_id=position.id,
            state=1,
            pnl_pct=2.5
        )
        
        self.assertEqual(alert.alert_type, 'PYRAMID')
        self.assertEqual(alert.pnl_pct_at_alert, 2.5)
    
    def test_get_recent(self):
        """Test getting recent alerts."""
        self.repo.create_breakout_alert('TSLA', 250.0, 245.0, grade='B', score=15)
        self.repo.create_breakout_alert('MSFT', 405.0, 400.0, grade='A', score=20)
        self.session.commit()
        
        recent = self.repo.get_recent(limit=10)
        self.assertEqual(len(recent), 2)
    
    def test_check_cooldown(self):
        """Test cooldown checking."""
        self.repo.create_breakout_alert('AMD', 155.0, 150.0, grade='A', score=18)
        self.session.commit()
        
        # Should be in cooldown
        in_cooldown = self.repo.check_cooldown('AMD', 'BREAKOUT', cooldown_minutes=60)
        self.assertTrue(in_cooldown)
        
        # Different type should not be in cooldown
        in_cooldown = self.repo.check_cooldown('AMD', 'PYRAMID', cooldown_minutes=60)
        self.assertFalse(in_cooldown)
    
    def test_mark_sent(self):
        """Test marking alert as sent."""
        alert = self.repo.create_breakout_alert('GOOG', 155.0, 150.0, grade='A', score=20)
        self.session.commit()
        
        self.repo.mark_sent(alert, channel='breakout-alerts', message_id='123456')
        
        self.assertTrue(alert.discord_sent)
        self.assertIsNotNone(alert.discord_sent_at)
        self.assertEqual(alert.discord_channel, 'breakout-alerts')
    
    def test_get_unsent(self):
        """Test getting unsent alerts."""
        alert1 = self.repo.create_breakout_alert('META', 500.0, 490.0, grade='A', score=22)
        alert2 = self.repo.create_breakout_alert('NFLX', 650.0, 640.0, grade='B', score=14)
        self.repo.mark_sent(alert2)
        self.session.commit()
        
        unsent = self.repo.get_unsent()
        self.assertEqual(len(unsent), 1)
        self.assertEqual(unsent[0].symbol, 'META')


class TestMarketRegimeRepository(unittest.TestCase):
    """Tests for MarketRegimeRepository class."""
    
    def setUp(self):
        """Set up test database and repository."""
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = MarketRegimeRepository(self.session)
    
    def tearDown(self):
        """Clean up."""
        self.session.close()
        self.db.close()
    
    def test_create_daily_regime(self):
        """Test creating a daily regime."""
        regime = self.repo.create_daily_regime(
            regime_date=date.today(),
            regime='BULLISH',
            regime_score=65,
            distribution_days={'spy': 2, 'qqq': 3, 'total': 5},
            recommended_exposure=4
        )
        
        self.assertEqual(regime.regime, 'BULLISH')
        self.assertEqual(regime.distribution_days_total, 5)
        self.assertEqual(regime.recommended_exposure, 4)
    
    def test_get_current(self):
        """Test getting current regime."""
        self.repo.create_daily_regime(
            regime_date=date.today(),
            regime='NEUTRAL',
            regime_score=0
        )
        self.session.commit()
        
        current = self.repo.get_current()
        self.assertIsNotNone(current)
        self.assertEqual(current.regime, 'NEUTRAL')
    
    def test_upsert(self):
        """Test upsert functionality."""
        # Create initial
        self.repo.upsert(
            regime_date=date.today(),
            regime='BULLISH',
            regime_score=50
        )
        self.session.commit()
        
        # Update
        self.repo.upsert(
            regime_date=date.today(),
            regime='BEARISH',
            regime_score=-30
        )
        self.session.commit()
        
        # Should only have one record
        regimes = self.repo.get_recent(days=1)
        self.assertEqual(len(regimes), 1)
        self.assertEqual(regimes[0].regime, 'BEARISH')


class TestConfigRepository(unittest.TestCase):
    """Tests for ConfigRepository class."""
    
    def setUp(self):
        """Set up test database and repository."""
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = ConfigRepository(self.session)
    
    def tearDown(self):
        """Clean up."""
        self.session.close()
        self.db.close()
    
    def test_get_default_config(self):
        """Test getting default configuration."""
        value = self.repo.get('service.poll_interval_breakout')
        self.assertEqual(value, '60')
    
    def test_get_typed(self):
        """Test getting typed values."""
        self.repo.set('test.int', 42, value_type='integer')
        self.repo.set('test.float', 3.14, value_type='float')
        self.repo.set('test.bool', True, value_type='boolean')
        self.session.commit()
        
        self.assertEqual(self.repo.get_int('test.int'), 42)
        self.assertAlmostEqual(self.repo.get_float('test.float'), 3.14)
        self.assertTrue(self.repo.get_bool('test.bool'))
    
    def test_get_by_category(self):
        """Test getting config by category."""
        configs = self.repo.get_by_category('service')
        self.assertGreater(len(configs), 0)
        self.assertIn('service.poll_interval_breakout', configs)
    
    def test_set_and_update(self):
        """Test setting and updating config."""
        self.repo.set('custom.setting', 'value1')
        self.session.commit()
        
        self.assertEqual(self.repo.get('custom.setting'), 'value1')
        
        self.repo.set('custom.setting', 'value2')
        self.session.commit()
        
        self.assertEqual(self.repo.get('custom.setting'), 'value2')


class TestRepositoryManager(unittest.TestCase):
    """Tests for RepositoryManager class."""
    
    def setUp(self):
        """Set up test database."""
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repos = RepositoryManager(self.session)
    
    def tearDown(self):
        """Clean up."""
        self.session.close()
        self.db.close()
    
    def test_repository_access(self):
        """Test accessing repositories through manager."""
        self.assertIsInstance(self.repos.positions, PositionRepository)
        self.assertIsInstance(self.repos.alerts, AlertRepository)
        self.assertIsInstance(self.repos.snapshots, SnapshotRepository)
        self.assertIsInstance(self.repos.outcomes, OutcomeRepository)
        self.assertIsInstance(self.repos.market_regime, MarketRegimeRepository)
        self.assertIsInstance(self.repos.config, ConfigRepository)
    
    def test_cross_repository_operations(self):
        """Test operations spanning multiple repositories."""
        # Create a position
        position = self.repos.positions.create(
            symbol='TEST',
            pivot=100.0,
            pattern='Test Pattern'
        )
        self.session.commit()
        
        # Create an alert for it
        alert = self.repos.alerts.create_breakout_alert(
            symbol='TEST',
            price=105.0,
            pivot=100.0,
            position_id=position.id,
            grade='A',
            score=20
        )
        self.session.commit()
        
        # Verify relationship
        alerts = self.repos.alerts.get_by_position(position.id)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].symbol, 'TEST')


if __name__ == '__main__':
    unittest.main(verbosity=2)
