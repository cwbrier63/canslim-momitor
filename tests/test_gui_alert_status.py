"""
Test GUI Alert Status Display Feature

Tests that position cards correctly display the latest alert
from the historical alerts table with proper color coding.
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAlertSeverity(unittest.TestCase):
    """Test AlertService severity classification."""
    
    def test_critical_severity_alerts(self):
        """Critical alerts should be classified correctly."""
        from services.alert_service import AlertService
        
        critical_alerts = [
            ("STOP", "HARD_STOP"),
            ("STOP", "TRAILING_STOP"),
            ("TECHNICAL", "50_MA_SELL"),
            ("TECHNICAL", "21_EMA_SELL"),
            ("TECHNICAL", "10_WEEK_SELL"),
            ("TECHNICAL", "CLIMAX_TOP"),
            ("HEALTH", "CRITICAL"),
        ]
        
        for alert_type, subtype in critical_alerts:
            severity = AlertService.get_alert_severity(alert_type, subtype)
            self.assertEqual(severity, "critical", 
                f"{alert_type}.{subtype} should be critical, got {severity}")
    
    def test_warning_severity_alerts(self):
        """Warning alerts should be classified correctly."""
        from services.alert_service import AlertService
        
        warning_alerts = [
            ("STOP", "WARNING"),
            ("TECHNICAL", "50_MA_WARNING"),
            ("HEALTH", "EXTENDED"),
            ("HEALTH", "EARNINGS"),
            ("HEALTH", "LATE_STAGE"),
            ("BREAKOUT", "EXTENDED"),
            ("BREAKOUT", "SUPPRESSED"),
        ]
        
        for alert_type, subtype in warning_alerts:
            severity = AlertService.get_alert_severity(alert_type, subtype)
            self.assertEqual(severity, "warning",
                f"{alert_type}.{subtype} should be warning, got {severity}")
    
    def test_profit_severity_alerts(self):
        """Profit alerts should be classified correctly."""
        from services.alert_service import AlertService
        
        profit_alerts = [
            ("PROFIT", "TP1"),
            ("PROFIT", "TP2"),
            ("PROFIT", "8_WEEK_HOLD"),
        ]
        
        for alert_type, subtype in profit_alerts:
            severity = AlertService.get_alert_severity(alert_type, subtype)
            self.assertEqual(severity, "profit",
                f"{alert_type}.{subtype} should be profit, got {severity}")
    
    def test_info_severity_alerts(self):
        """Info alerts should be classified correctly."""
        from services.alert_service import AlertService
        
        info_alerts = [
            ("BREAKOUT", "CONFIRMED"),
            ("BREAKOUT", "IN_BUY_ZONE"),
            ("BREAKOUT", "APPROACHING"),
            ("PYRAMID", "P1_READY"),
            ("PYRAMID", "P2_READY"),
            ("ADD", "PULLBACK"),
        ]
        
        for alert_type, subtype in info_alerts:
            severity = AlertService.get_alert_severity(alert_type, subtype)
            self.assertEqual(severity, "info",
                f"{alert_type}.{subtype} should be info, got {severity}")
    
    def test_unknown_alert_returns_neutral(self):
        """Unknown alerts should return neutral severity."""
        from services.alert_service import AlertService
        
        severity = AlertService.get_alert_severity("UNKNOWN", "UNKNOWN")
        self.assertEqual(severity, "neutral")
    
    def test_severity_colors(self):
        """Severity colors should be valid hex codes."""
        from services.alert_service import AlertService
        
        severities = ["critical", "warning", "profit", "info", "neutral"]
        
        for severity in severities:
            color = AlertService.get_severity_color(severity)
            self.assertTrue(color.startswith("#"), f"{severity} color should be hex")
            self.assertEqual(len(color), 7, f"{severity} color should be 7 chars")


class TestPositionCardAlertDisplay(unittest.TestCase):
    """Test PositionCard alert display methods."""
    
    def test_format_alert_text_known_types(self):
        """Known alert types should have friendly names."""
        from gui.position_card import PositionCard
        
        # Create a minimal card for testing
        card = PositionCard(
            position_id=1,
            symbol="TEST",
            state=1
        )
        
        # Test known types
        self.assertIn("Stop Hit", card._format_alert_text("STOP", "HARD_STOP"))
        self.assertIn("TP1 Hit", card._format_alert_text("PROFIT", "TP1"))
        self.assertIn("P1 Ready", card._format_alert_text("PYRAMID", "P1_READY"))
        self.assertIn("Breakout", card._format_alert_text("BREAKOUT", "CONFIRMED"))
    
    def test_format_alert_text_unknown_types(self):
        """Unknown alert types should show raw type.subtype."""
        from gui.position_card import PositionCard
        
        card = PositionCard(
            position_id=1,
            symbol="TEST",
            state=1
        )
        
        result = card._format_alert_text("UNKNOWN", "TYPE")
        self.assertEqual(result, "UNKNOWN.TYPE")
    
    def test_format_alert_time_recent(self):
        """Recent alerts should show minutes ago."""
        from gui.position_card import PositionCard
        
        card = PositionCard(
            position_id=1,
            symbol="TEST",
            state=1
        )
        
        # 5 minutes ago
        recent_time = (datetime.now() - timedelta(minutes=5)).isoformat()
        result = card._format_alert_time(recent_time)
        self.assertIn("m ago", result)
    
    def test_format_alert_time_hours(self):
        """Alerts from hours ago should show hours."""
        from gui.position_card import PositionCard
        
        card = PositionCard(
            position_id=1,
            symbol="TEST",
            state=1
        )
        
        # 3 hours ago
        hours_ago = (datetime.now() - timedelta(hours=3)).isoformat()
        result = card._format_alert_time(hours_ago)
        self.assertIn("h ago", result)
    
    def test_format_alert_time_days(self):
        """Alerts from days ago should show days."""
        from gui.position_card import PositionCard
        
        card = PositionCard(
            position_id=1,
            symbol="TEST",
            state=1
        )
        
        # 2 days ago
        days_ago = (datetime.now() - timedelta(days=2)).isoformat()
        result = card._format_alert_time(days_ago)
        self.assertIn("d ago", result)
    
    def test_severity_emoji_mapping(self):
        """Severity emojis should be correct."""
        from gui.position_card import PositionCard
        
        card = PositionCard(
            position_id=1,
            symbol="TEST",
            state=1
        )
        
        self.assertEqual(card._get_severity_emoji("critical"), "🔴")
        self.assertEqual(card._get_severity_emoji("warning"), "🟡")
        self.assertEqual(card._get_severity_emoji("profit"), "🟢")
        self.assertEqual(card._get_severity_emoji("info"), "🔵")
        self.assertEqual(card._get_severity_emoji("neutral"), "⚪")


class TestAlertServiceLatestAlert(unittest.TestCase):
    """Test AlertService methods for fetching latest alerts."""
    
    def test_get_latest_alert_for_position_no_db(self):
        """Should return None when no database configured."""
        from services.alert_service import AlertService
        
        service = AlertService(db_session_factory=None)
        result = service.get_latest_alert_for_position(1)
        self.assertIsNone(result)
    
    def test_get_latest_alerts_for_positions_empty_list(self):
        """Should return empty dict for empty position list."""
        from services.alert_service import AlertService
        
        service = AlertService(db_session_factory=MagicMock())
        result = service.get_latest_alerts_for_positions([])
        self.assertEqual(result, {})


def run_tests():
    """Run all GUI alert tests."""
    print("=" * 60)
    print("GUI ALERT STATUS DISPLAY TESTS")
    print("=" * 60)
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestAlertSeverity))
    suite.addTests(loader.loadTestsFromTestCase(TestPositionCardAlertDisplay))
    suite.addTests(loader.loadTestsFromTestCase(TestAlertServiceLatestAlert))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failed: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Total:  {result.testsRun}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
