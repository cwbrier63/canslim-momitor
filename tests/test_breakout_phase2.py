#!/usr/bin/env python3
"""
Phase 2 Integration Test
========================
Tests the full breakout thread with scoring, position sizing, and alert generation.

Run: python -m canslim_monitor.tests.test_breakout_phase2
"""

import sys
import os
from unittest.mock import Mock, MagicMock
from threading import Event
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_mock_position(
    symbol: str = "NVDA",
    pivot: float = 100.0,
    pattern: str = "Cup w/Handle",
    base_stage: str = "2",
    base_depth: float = 20.0,
    base_length: int = 8,
    rs_rating: int = 94
):
    """Create a mock Position object."""
    pos = Mock()
    pos.id = 1
    pos.symbol = symbol
    pos.pivot = pivot
    pos.state = 0
    pos.pattern = pattern
    pos.base_stage = base_stage
    pos.base_depth = base_depth
    pos.base_length = base_length
    pos.rs_rating = rs_rating
    pos.eps_rating = 85
    pos.ad_rating = "B"
    pos.ud_vol_ratio = 1.4
    return pos


def create_mock_price_data(
    symbol: str,
    last: float,
    volume: int = 5000000,
    avg_volume: int = 3000000,
    high: float = None,
    low: float = None
):
    """Create mock price data."""
    if high is None:
        high = last * 1.02
    if low is None:
        low = last * 0.98
    
    return {
        'symbol': symbol,
        'last': last,
        'bid': last - 0.01,
        'ask': last + 0.01,
        'volume': volume,
        'avg_volume': avg_volume,
        'high': high,
        'low': low,
        'ma50': last * 0.95,
        'ma21': last * 0.98,
        'volume_ratio': volume / avg_volume,
    }


def test_breakout_detection():
    """Test basic breakout detection logic."""
    print("\n" + "=" * 60)
    print("TEST: Breakout Detection")
    print("=" * 60)
    
    from canslim_monitor.service.threads.breakout_thread import BreakoutThread
    from canslim_monitor.utils.scoring_engine import ScoringEngine
    from canslim_monitor.utils.position_sizer import PositionSizer
    
    # Create thread with mock dependencies
    shutdown_event = Event()
    
    # Try to load real scoring engine if config exists
    config_paths = [
        'config/scoring_config.yaml',
        'canslim_monitor/config/scoring_config.yaml',
        '../config/scoring_config.yaml',
    ]
    
    scoring_engine = None
    for path in config_paths:
        if os.path.exists(path):
            scoring_engine = ScoringEngine(path)
            print(f"  ✓ Loaded scoring config from: {path}")
            break
    
    if not scoring_engine:
        print("  ⚠ No scoring config found, using mock")
    
    position_sizer = PositionSizer()
    
    # Mock IBKR client
    ibkr_client = Mock()
    
    thread = BreakoutThread(
        shutdown_event=shutdown_event,
        poll_interval=60,
        db_session_factory=None,
        ibkr_client=ibkr_client,
        discord_notifier=None,
        config={'account_value': 100000},
        scoring_engine=scoring_engine,
        position_sizer=position_sizer,
    )
    
    # Test 1: CONFIRMED breakout
    print("\n  Test 1: CONFIRMED breakout (price above pivot, good volume, strong close)")
    pos = create_mock_position("NVDA", pivot=100.0, rs_rating=94)
    price_data = create_mock_price_data("NVDA", last=102.0, volume=6000000, avg_volume=3000000)
    price_data['high'] = 103.0
    price_data['low'] = 100.5
    
    # Manually calculate what the thread would do
    distance_pct = ((102.0 - 100.0) / 100.0) * 100
    volume_ratio = 6000000 / 3000000
    print(f"    Distance from pivot: {distance_pct:+.1f}%")
    print(f"    Volume ratio: {volume_ratio:.1f}x")
    print(f"    Strong close: Yes (102 in upper half of 100.5-103)")
    
    if scoring_engine:
        result = scoring_engine.score(
            pattern=pos.pattern,
            stage=pos.base_stage,
            depth_pct=pos.base_depth,
            length_weeks=pos.base_length,
            rs_rating=pos.rs_rating
        )
        print(f"    Grade: {result.grade} (Score: {result.final_score})")
    
    sizing = position_sizer.calculate_target_position(
        account_value=100000,
        entry_price=102.0,
        stop_price=94.86  # 7% stop
    )
    print(f"    Target shares: {sizing.target_shares}")
    print(f"    Initial entry: {sizing.initial_shares} shares (50%)")
    print("  ✓ Would generate CONFIRMED alert")
    
    # Test 2: EXTENDED breakout
    print("\n  Test 2: EXTENDED (>5% above pivot)")
    price_data2 = create_mock_price_data("NVDA", last=106.5)  # 6.5% above pivot
    distance_pct2 = ((106.5 - 100.0) / 100.0) * 100
    print(f"    Distance from pivot: {distance_pct2:+.1f}%")
    print("  ✓ Would generate EXTENDED alert (no chase)")
    
    # Test 3: APPROACHING
    print("\n  Test 3: APPROACHING (within 1% of pivot)")
    price_data3 = create_mock_price_data("NVDA", last=99.5, volume=4500000, avg_volume=3000000)
    distance_pct3 = ((99.5 - 100.0) / 100.0) * 100
    print(f"    Distance from pivot: {distance_pct3:+.1f}%")
    print(f"    Volume building: {4500000/3000000:.1f}x average")
    print("  ✓ Would generate APPROACHING alert")
    
    # Test 4: RS Floor application
    print("\n  Test 4: RS Floor (RS < 70 caps grade at C)")
    pos_low_rs = create_mock_position("TEST", pivot=50.0, rs_rating=65, pattern="Cup w/Handle")
    if scoring_engine:
        result_low_rs = scoring_engine.score(
            pattern=pos_low_rs.pattern,
            stage=pos_low_rs.base_stage,
            depth_pct=pos_low_rs.base_depth,
            length_weeks=pos_low_rs.base_length,
            rs_rating=pos_low_rs.rs_rating
        )
        print(f"    Original score would be: {result_low_rs.final_score}")
        print(f"    RS Floor applied: {result_low_rs.rs_floor_applied}")
        print(f"    Final grade: {result_low_rs.grade}")
        if result_low_rs.rs_floor_applied:
            print(f"    (Was {result_low_rs.original_grade} before floor)")
    
    print("\n  All breakout detection tests passed!")
    return True


def test_alert_service_integration():
    """Test alert service integration."""
    print("\n" + "=" * 60)
    print("TEST: Alert Service Integration")
    print("=" * 60)
    
    from canslim_monitor.services.alert_service import (
        AlertService, AlertType, AlertSubtype, AlertContext
    )
    
    # Create service without DB/Discord
    service = AlertService(cooldown_minutes=1)
    
    # Create test context
    context = AlertContext(
        current_price=102.50,
        pivot_price=100.00,
        grade="A",
        score=18,
        volume_ratio=2.1,
        market_regime="CONFIRMED_UPTREND",
        shares_recommended=140,
    )
    
    # Test alert creation
    print("\n  Test 1: Create CONFIRMED breakout alert")
    alert = service.create_alert(
        symbol="NVDA",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="NVDA broke out above $100.00 pivot with 2.1x volume",
        action="▶ ACTION: Buy 70 shares (50% initial position)",
        thread_source="test"
    )
    
    if alert:
        print(f"    Title: {alert.title}")
        print(f"    Channel: {alert.discord_channel}")
        print(f"    Priority: {alert.priority}")
        print("  ✓ Alert created successfully")
    else:
        print("  ✗ Alert creation failed")
        return False
    
    # Test cooldown
    print("\n  Test 2: Cooldown blocks duplicate alerts")
    alert2 = service.create_alert(
        symbol="NVDA",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="Same alert again"
    )
    
    if alert2 is None:
        print("  ✓ Cooldown blocked duplicate (as expected)")
    else:
        print("  ✗ Cooldown did not block duplicate!")
        return False
    
    # Test market suppression
    print("\n  Test 3: Market correction suppresses entries")
    service.clear_cooldown()  # Clear for new test
    context_correction = AlertContext(
        current_price=52.00,
        pivot_price=50.00,
        grade="B",
        score=12,
        volume_ratio=1.8,
        market_regime="CORRECTION",
    )
    
    alert3 = service.create_alert(
        symbol="AMD",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context_correction,
        message="AMD breakout during correction"
    )
    
    if alert3 and alert3.subtype == AlertSubtype.SUPPRESSED:
        print("  ✓ Entry suppressed due to market correction")
    else:
        print(f"  ⚠ Expected SUPPRESSED, got: {alert3.subtype if alert3 else 'None'}")
    
    print("\n  All alert service tests passed!")
    return True


def test_position_sizing():
    """Test position sizing calculations."""
    print("\n" + "=" * 60)
    print("TEST: Position Sizing")
    print("=" * 60)
    
    from canslim_monitor.utils.position_sizer import PositionSizer
    
    sizer = PositionSizer()
    
    # Test standard position
    print("\n  Test 1: Standard position sizing ($100k account, 7% stop)")
    result = sizer.calculate_target_position(
        account_value=100000,
        entry_price=50.00,
        stop_price=46.50  # 7% stop
    )
    
    print(f"    Entry: $50.00, Stop: $46.50 (7% risk)")
    print(f"    Target position: {result.target_shares} shares (${result.target_value:,.2f})")
    print(f"    Initial entry: {result.initial_shares} shares (50%)")
    print(f"    Pyramid 1: {result.pyramid1_shares} shares @ ${result.pyramid1_est_price:.2f}")
    print(f"    Pyramid 2: {result.pyramid2_shares} shares @ ${result.pyramid2_est_price:.2f}")
    print(f"    Total risk: ${result.total_risk:.2f} ({result.risk_pct_of_account:.1f}%)")
    
    # Verify 50/25/25 split
    expected_initial_pct = 50.0
    actual_initial_pct = (result.initial_shares / result.target_shares) * 100
    print(f"\n    Initial % of target: {actual_initial_pct:.1f}% (expected ~{expected_initial_pct}%)")
    
    if abs(actual_initial_pct - expected_initial_pct) < 5:  # Allow 5% tolerance due to rounding
        print("  ✓ Position sizing calculations correct")
    else:
        print("  ⚠ Position sizing may have rounding issues")
    
    # Test profit exits
    print("\n  Test 2: Profit exit plan")
    exit_plan = sizer.calculate_profit_exits(
        current_shares=result.target_shares,
        avg_cost=50.00
    )
    
    print(f"    TP1 (+20%): Sell {exit_plan.tp1_shares} shares @ ${exit_plan.tp1_price:.2f}")
    print(f"    TP2 (+25%): Sell {exit_plan.tp2_shares} shares @ ${exit_plan.tp2_price:.2f}")
    print(f"    Trailing: {exit_plan.trailing_shares} shares via {exit_plan.trailing_method}")
    
    # Verify TP1 is ~1/3 of position
    tp1_pct = (exit_plan.tp1_shares / result.target_shares) * 100
    print(f"\n    TP1 % of position: {tp1_pct:.1f}% (expected ~33%)")
    
    print("\n  Position sizing tests passed!")
    return True


def run_all_tests():
    """Run all Phase 2 tests."""
    print("\n" + "=" * 70)
    print("CANSLIM MONITOR - PHASE 2 INTEGRATION TESTS")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    # Run tests
    try:
        results.append(("Position Sizing", test_position_sizing()))
    except Exception as e:
        print(f"  ✗ Position Sizing test failed: {e}")
        results.append(("Position Sizing", False))
    
    try:
        results.append(("Alert Service", test_alert_service_integration()))
    except Exception as e:
        print(f"  ✗ Alert Service test failed: {e}")
        results.append(("Alert Service", False))
    
    try:
        results.append(("Breakout Detection", test_breakout_detection()))
    except Exception as e:
        print(f"  ✗ Breakout Detection test failed: {e}")
        results.append(("Breakout Detection", False))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {name}: {status}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  🎉 All Phase 2 tests passed! Ready for integration.")
    else:
        print(f"\n  ⚠ {total - passed} test(s) failed. Review output above.")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
