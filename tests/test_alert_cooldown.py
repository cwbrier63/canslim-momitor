"""
CANSLIM Monitor - Alert Cooldown Unit Tests
=============================================
Tests for the alert cooldown feature switch.

Test Cases:
1. Cooldown DISABLED (default) - all alerts pass through
2. Cooldown ENABLED - duplicate alerts filtered
3. Cooldown respects symbol boundaries
4. Cooldown respects type/subtype boundaries
5. Cooldown expires after configured time
6. Force flag bypasses cooldown
7. Clear cooldown functionality

Run: python -m canslim_monitor.tests.test_alert_cooldown
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from canslim_monitor.services.alert_service import (
    AlertService,
    AlertType,
    AlertSubtype,
    AlertContext,
    AlertData
)


class TestAlertCooldownDisabled(unittest.TestCase):
    """Test cooldown behavior when DISABLED (default)."""
    
    def setUp(self):
        """Create service with cooldown DISABLED."""
        self.service = AlertService(
            cooldown_minutes=60,
            enable_cooldown=False,  # Disabled
            enable_suppression=False  # Disable suppression for clean testing
        )
        self.context = AlertContext(
            current_price=100.0,
            pivot_price=95.0,
            grade="A",
            score=18,
            market_regime="CONFIRMED_UPTREND"
        )
    
    def test_first_alert_passes(self):
        """First alert should always pass."""
        alert = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="Test alert"
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.symbol, "TEST")
    
    def test_duplicate_alert_passes_when_disabled(self):
        """Duplicate alert should pass when cooldown is disabled."""
        # First alert
        alert1 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="First alert"
        )
        self.assertIsNotNone(alert1)
        
        # Second alert (same symbol, type, subtype) - should PASS
        alert2 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="Second alert"
        )
        self.assertIsNotNone(alert2)
        self.assertEqual(alert2.message, "Second alert")
    
    def test_multiple_rapid_alerts_pass(self):
        """Multiple rapid alerts should all pass when cooldown disabled."""
        alerts = []
        for i in range(5):
            alert = self.service.create_alert(
                symbol="RAPID",
                alert_type=AlertType.STOP,
                subtype=AlertSubtype.WARNING,
                context=self.context,
                message=f"Alert {i+1}"
            )
            alerts.append(alert)
        
        # All 5 should have been created
        self.assertEqual(len([a for a in alerts if a is not None]), 5)


class TestAlertCooldownEnabled(unittest.TestCase):
    """Test cooldown behavior when ENABLED."""
    
    def setUp(self):
        """Create service with cooldown ENABLED."""
        self.service = AlertService(
            cooldown_minutes=60,
            enable_cooldown=True,  # Enabled
            enable_suppression=False
        )
        self.context = AlertContext(
            current_price=100.0,
            pivot_price=95.0,
            grade="A",
            score=18,
            market_regime="CONFIRMED_UPTREND"
        )
    
    def test_first_alert_passes(self):
        """First alert should pass even with cooldown enabled."""
        alert = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="Test alert"
        )
        self.assertIsNotNone(alert)
    
    def test_duplicate_alert_blocked_when_enabled(self):
        """Duplicate alert should be blocked when cooldown is enabled."""
        # First alert
        alert1 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="First alert"
        )
        self.assertIsNotNone(alert1)
        
        # Second alert (same symbol, type, subtype) - should be BLOCKED
        alert2 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="Second alert"
        )
        self.assertIsNone(alert2)
    
    def test_different_symbol_not_blocked(self):
        """Different symbol should not be affected by cooldown."""
        # First symbol
        alert1 = self.service.create_alert(
            symbol="NVDA",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="NVDA alert"
        )
        self.assertIsNotNone(alert1)
        
        # Different symbol - should PASS
        alert2 = self.service.create_alert(
            symbol="AMD",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="AMD alert"
        )
        self.assertIsNotNone(alert2)
    
    def test_different_type_not_blocked(self):
        """Different alert type for same symbol should not be blocked."""
        # Breakout alert
        alert1 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="Breakout alert"
        )
        self.assertIsNotNone(alert1)
        
        # Stop alert for same symbol - should PASS
        alert2 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.STOP,
            subtype=AlertSubtype.WARNING,
            context=self.context,
            message="Stop alert"
        )
        self.assertIsNotNone(alert2)
    
    def test_different_subtype_not_blocked(self):
        """Different subtype for same symbol/type should not be blocked."""
        # CONFIRMED breakout
        alert1 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="Confirmed breakout"
        )
        self.assertIsNotNone(alert1)
        
        # APPROACHING breakout - should PASS
        alert2 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.APPROACHING,
            context=self.context,
            message="Approaching breakout"
        )
        self.assertIsNotNone(alert2)
    
    def test_force_flag_bypasses_cooldown(self):
        """Force flag should bypass cooldown check."""
        # First alert
        alert1 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.STOP,
            subtype=AlertSubtype.HARD_STOP,
            context=self.context,
            message="First stop alert"
        )
        self.assertIsNotNone(alert1)
        
        # Second alert with force=True - should PASS
        alert2 = self.service.create_alert(
            symbol="TEST",
            alert_type=AlertType.STOP,
            subtype=AlertSubtype.HARD_STOP,
            context=self.context,
            message="Forced stop alert",
            force=True
        )
        self.assertIsNotNone(alert2)


class TestCooldownExpiration(unittest.TestCase):
    """Test cooldown expiration behavior."""
    
    def test_cooldown_expires_after_configured_time(self):
        """Alert should pass after cooldown period expires."""
        service = AlertService(
            cooldown_minutes=5,  # 5 minutes
            enable_cooldown=True,
            enable_suppression=False
        )
        context = AlertContext(current_price=100.0)
        
        # First alert
        alert1 = service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=context,
            message="First alert"
        )
        self.assertIsNotNone(alert1)
        
        # Manually set cooldown cache to 6 minutes ago
        key = ("TEST", "BREAKOUT", "CONFIRMED")
        service._cooldown_cache[key] = datetime.now() - timedelta(minutes=6)
        
        # Second alert - should PASS (cooldown expired)
        alert2 = service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=context,
            message="Second alert after expiry"
        )
        self.assertIsNotNone(alert2)
    
    def test_cooldown_not_expired_within_period(self):
        """Alert should be blocked within cooldown period."""
        service = AlertService(
            cooldown_minutes=10,  # 10 minutes
            enable_cooldown=True,
            enable_suppression=False
        )
        context = AlertContext(current_price=100.0)
        
        # First alert
        alert1 = service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=context,
            message="First alert"
        )
        self.assertIsNotNone(alert1)
        
        # Manually set cooldown cache to 5 minutes ago (still within 10 min cooldown)
        key = ("TEST", "BREAKOUT", "CONFIRMED")
        service._cooldown_cache[key] = datetime.now() - timedelta(minutes=5)
        
        # Second alert - should be BLOCKED (still in cooldown)
        alert2 = service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=context,
            message="Second alert"
        )
        self.assertIsNone(alert2)


class TestClearCooldown(unittest.TestCase):
    """Test cooldown clearing functionality."""
    
    def setUp(self):
        """Create service with cooldown enabled."""
        self.service = AlertService(
            cooldown_minutes=60,
            enable_cooldown=True,
            enable_suppression=False
        )
        self.context = AlertContext(current_price=100.0)
    
    def test_clear_cooldown_for_symbol(self):
        """Clearing cooldown for specific symbol allows new alerts."""
        # Create alert
        alert1 = self.service.create_alert(
            symbol="CLEAR_TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="First alert"
        )
        self.assertIsNotNone(alert1)
        
        # Verify blocked
        alert2 = self.service.create_alert(
            symbol="CLEAR_TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="Blocked alert"
        )
        self.assertIsNone(alert2)
        
        # Clear cooldown for this symbol
        self.service.clear_cooldown("CLEAR_TEST")
        
        # Now should pass
        alert3 = self.service.create_alert(
            symbol="CLEAR_TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=self.context,
            message="After clear"
        )
        self.assertIsNotNone(alert3)
    
    def test_clear_all_cooldowns(self):
        """Clearing all cooldowns allows all new alerts."""
        # Create alerts for multiple symbols
        for symbol in ["AAA", "BBB", "CCC"]:
            self.service.create_alert(
                symbol=symbol,
                alert_type=AlertType.BREAKOUT,
                subtype=AlertSubtype.CONFIRMED,
                context=self.context,
                message=f"{symbol} alert"
            )
        
        # Verify all blocked
        for symbol in ["AAA", "BBB", "CCC"]:
            alert = self.service.create_alert(
                symbol=symbol,
                alert_type=AlertType.BREAKOUT,
                subtype=AlertSubtype.CONFIRMED,
                context=self.context,
                message=f"{symbol} blocked"
            )
            self.assertIsNone(alert)
        
        # Clear all cooldowns
        self.service.clear_cooldown()
        
        # All should pass now
        for symbol in ["AAA", "BBB", "CCC"]:
            alert = self.service.create_alert(
                symbol=symbol,
                alert_type=AlertType.BREAKOUT,
                subtype=AlertSubtype.CONFIRMED,
                context=self.context,
                message=f"{symbol} after clear"
            )
            self.assertIsNotNone(alert)


class TestCooldownWithSuppression(unittest.TestCase):
    """Test cooldown interacts correctly with market suppression."""
    
    def test_suppression_and_cooldown_both_apply(self):
        """Both suppression and cooldown can apply to same alert."""
        service = AlertService(
            cooldown_minutes=60,
            enable_cooldown=True,
            enable_suppression=True
        )
        context = AlertContext(
            current_price=100.0,
            market_regime="CORRECTION"
        )
        
        # First alert - should be SUPPRESSED (not CONFIRMED)
        alert1 = service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=context,
            message="First alert"
        )
        self.assertIsNotNone(alert1)
        self.assertEqual(alert1.subtype, AlertSubtype.SUPPRESSED)
        
        # Second alert - cooldown key is based on ORIGINAL subtype (CONFIRMED)
        # So this should be blocked by cooldown
        alert2 = service.create_alert(
            symbol="TEST",
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.CONFIRMED,
            context=context,
            message="Second alert"
        )
        self.assertIsNone(alert2)


class TestAlertServiceDefaults(unittest.TestCase):
    """Test default behavior of AlertService."""
    
    def test_default_cooldown_disabled(self):
        """Default should be cooldown DISABLED."""
        service = AlertService()
        self.assertFalse(service.enable_cooldown)
    
    def test_default_cooldown_minutes(self):
        """Default cooldown minutes should be 60."""
        service = AlertService()
        self.assertEqual(service.cooldown_minutes, 60)


# =============================================================================
# Test Runner
# =============================================================================

def run_tests():
    """Run all cooldown tests with verbose output."""
    print("=" * 70)
    print("ALERT COOLDOWN UNIT TESTS")
    print("=" * 70)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestAlertCooldownDisabled))
    suite.addTests(loader.loadTestsFromTestCase(TestAlertCooldownEnabled))
    suite.addTests(loader.loadTestsFromTestCase(TestCooldownExpiration))
    suite.addTests(loader.loadTestsFromTestCase(TestClearCooldown))
    suite.addTests(loader.loadTestsFromTestCase(TestCooldownWithSuppression))
    suite.addTests(loader.loadTestsFromTestCase(TestAlertServiceDefaults))
    
    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print()
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
    print("=" * 70)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
