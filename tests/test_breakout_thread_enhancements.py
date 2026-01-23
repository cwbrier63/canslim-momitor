"""
Test script for Phase 3.5: Breakout Thread Enhancements.

Tests:
1. Volume threshold 1.4x for confirmed breakouts
2. Volume threshold 1.0x for IN_BUY_ZONE alerts
3. Market regime suppression
4. Time-adjusted RVOL calculation
5. APPROACHING suppression in correction

Usage:
    python -m canslim_monitor.tests.test_breakout_thread_enhancements
"""

import logging
from datetime import datetime
from unittest.mock import MagicMock, patch
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test.breakout')


def test_volume_thresholds():
    """Test that volume thresholds are properly configured."""
    print("\n" + "=" * 60)
    print("TEST 1: Volume Thresholds")
    print("=" * 60)
    
    from canslim_monitor.service.threads.breakout_thread import BreakoutThread
    
    # Create thread with default config
    thread = BreakoutThread(
        shutdown_event=MagicMock(),
        config={}
    )
    
    print(f"\n📊 Default Volume Thresholds:")
    print(f"   CONFIRMED threshold: {thread.volume_threshold_confirmed}x")
    print(f"   MINIMUM threshold: {thread.volume_threshold_minimum}x")
    
    if thread.volume_threshold_confirmed == 1.4:
        print(f"\n   ✅ CONFIRMED threshold is 1.4x (40% above avg)")
    else:
        print(f"\n   ❌ CONFIRMED threshold should be 1.4x, got {thread.volume_threshold_confirmed}")
        return False
    
    if thread.volume_threshold_minimum == 1.0:
        print(f"   ✅ MINIMUM threshold is 1.0x (at least average)")
    else:
        print(f"   ❌ MINIMUM threshold should be 1.0x, got {thread.volume_threshold_minimum}")
        return False
    
    # Test custom config
    custom_thread = BreakoutThread(
        shutdown_event=MagicMock(),
        config={
            'volume_threshold_confirmed': 1.5,
            'volume_threshold_minimum': 0.8
        }
    )
    
    print(f"\n📊 Custom Config Test:")
    print(f"   CONFIRMED: {custom_thread.volume_threshold_confirmed}x (expected 1.5x)")
    print(f"   MINIMUM: {custom_thread.volume_threshold_minimum}x (expected 0.8x)")
    
    if custom_thread.volume_threshold_confirmed == 1.5 and custom_thread.volume_threshold_minimum == 0.8:
        print(f"\n   ✅ Custom thresholds applied correctly")
        return True
    else:
        print(f"\n   ❌ Custom thresholds not applied correctly")
        return False


def test_rvol_calculation():
    """Test time-adjusted RVOL calculation."""
    print("\n" + "=" * 60)
    print("TEST 2: Time-Adjusted RVOL Calculation")
    print("=" * 60)
    
    from canslim_monitor.service.threads.breakout_thread import BreakoutThread
    
    thread = BreakoutThread(
        shutdown_event=MagicMock(),
        config={}
    )
    
    # Test RVOL calculation
    avg_daily_volume = 1_000_000
    
    # Test cases
    test_cases = [
        (500_000, "half-day volume"),
        (1_000_000, "full-day volume"),
        (1_500_000, "1.5x volume"),
    ]
    
    print(f"\n📊 RVOL Calculations (avg daily vol: {avg_daily_volume:,}):")
    
    for current_vol, description in test_cases:
        rvol = thread._calculate_rvol(current_vol, avg_daily_volume)
        print(f"   {description}: {current_vol:,} → RVOL = {rvol:.2f}x")
    
    # Test edge cases
    print(f"\n📊 Edge Cases:")
    
    # Zero volume
    rvol_zero = thread._calculate_rvol(0, avg_daily_volume)
    print(f"   Zero volume: {rvol_zero:.2f}x (expected 0.0)")
    
    # Zero avg volume
    rvol_no_avg = thread._calculate_rvol(1000, 0)
    print(f"   Zero avg volume: {rvol_no_avg:.2f}x (expected 0.0)")
    
    if rvol_zero == 0.0 and rvol_no_avg == 0.0:
        print(f"\n   ✅ Edge cases handled correctly")
        return True
    else:
        print(f"\n   ❌ Edge cases not handled correctly")
        return False


def test_market_regime_suppression():
    """Test market regime suppression logic."""
    print("\n" + "=" * 60)
    print("TEST 3: Market Regime Suppression")
    print("=" * 60)
    
    from canslim_monitor.service.threads.breakout_thread import BreakoutThread
    
    thread = BreakoutThread(
        shutdown_event=MagicMock(),
        config={'suppress_in_correction': True}
    )
    
    # Test regime detection
    test_regimes = [
        ("CORRECTION", True),
        ("BEARISH", True),
        ("DOWNTREND", True),
        ("CONFIRMED_UPTREND", False),
        ("RALLY_ATTEMPT", False),
        ("BULLISH", False),
        (None, False),
    ]
    
    print(f"\n📊 Market Regime Detection:")
    all_correct = True
    
    for regime, expected_correction in test_regimes:
        thread._market_regime_cache = regime
        is_correction = thread._is_market_in_correction()
        status = "✅" if is_correction == expected_correction else "❌"
        print(f"   {status} {regime or 'None'}: is_correction={is_correction} (expected {expected_correction})")
        if is_correction != expected_correction:
            all_correct = False
    
    if all_correct:
        print(f"\n   ✅ Market regime detection working correctly")
        return True
    else:
        print(f"\n   ❌ Market regime detection has errors")
        return False


def test_suppression_config():
    """Test suppression configuration options."""
    print("\n" + "=" * 60)
    print("TEST 4: Suppression Configuration")
    print("=" * 60)
    
    from canslim_monitor.service.threads.breakout_thread import BreakoutThread
    
    # Test default config
    thread_default = BreakoutThread(
        shutdown_event=MagicMock(),
        config={}
    )
    
    print(f"\n📊 Default Suppression Config:")
    print(f"   suppress_in_correction: {thread_default.suppress_in_correction}")
    print(f"   suppress_approaching_in_correction: {thread_default.suppress_approaching_in_correction}")
    
    # Test custom config
    thread_custom = BreakoutThread(
        shutdown_event=MagicMock(),
        config={
            'suppress_in_correction': False,
            'suppress_approaching_in_correction': False
        }
    )
    
    print(f"\n📊 Custom Config (both False):")
    print(f"   suppress_in_correction: {thread_custom.suppress_in_correction}")
    print(f"   suppress_approaching_in_correction: {thread_custom.suppress_approaching_in_correction}")
    
    if (thread_default.suppress_in_correction == True and 
        thread_custom.suppress_in_correction == False):
        print(f"\n   ✅ Suppression config working correctly")
        return True
    else:
        print(f"\n   ❌ Suppression config not working")
        return False


def test_get_stats():
    """Test get_stats returns correct volume thresholds."""
    print("\n" + "=" * 60)
    print("TEST 5: get_stats() Method")
    print("=" * 60)
    
    from canslim_monitor.service.threads.breakout_thread import BreakoutThread
    
    thread = BreakoutThread(
        shutdown_event=MagicMock(),
        config={}
    )
    
    stats = thread.get_stats()
    
    print(f"\n📊 Stats returned:")
    print(f"   volume_threshold_confirmed: {stats.get('volume_threshold_confirmed')}")
    print(f"   volume_threshold_minimum: {stats.get('volume_threshold_minimum')}")
    print(f"   suppress_in_correction: {stats.get('suppress_in_correction')}")
    print(f"   market_regime: {stats.get('market_regime')}")
    
    if 'volume_threshold_confirmed' in stats and 'volume_threshold_minimum' in stats:
        print(f"\n   ✅ get_stats() returns correct fields")
        return True
    else:
        print(f"\n   ❌ get_stats() missing volume threshold fields")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("PHASE 3.5: BREAKOUT THREAD ENHANCEMENT TESTS")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    tests = [
        ("Volume Thresholds", test_volume_thresholds),
        ("RVOL Calculation", test_rvol_calculation),
        ("Market Regime Suppression", test_market_regime_suppression),
        ("Suppression Config", test_suppression_config),
        ("get_stats() Method", test_get_stats),
    ]
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"Test '{name}' failed with error: {e}", exc_info=True)
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status}: {name}")
    
    print(f"\n   Total: {passed}/{total} passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
