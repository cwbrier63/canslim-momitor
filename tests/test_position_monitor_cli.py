#!/usr/bin/env python
"""
Position Monitor CLI Tester

Tests the position monitor checkers with simulated data.
No database, IBKR, or Discord required.

Usage (from C:\\trading):
    python -m canslim_monitor.tests.test_position_monitor_cli
    
Examples:
    # Test all scenarios
    python -m canslim_monitor.tests.test_position_monitor_cli
    
    # Test specific scenario
    python -m canslim_monitor.tests.test_position_monitor_cli --scenario stop
    
    # Interactive mode
    python -m canslim_monitor.tests.test_position_monitor_cli --interactive
    
    # Test level calculator only
    python -m canslim_monitor.tests.test_position_monitor_cli --levels
"""

import sys
import os
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional

# =============================================================================
# PATH SETUP - Handle running from C:\trading root level
# =============================================================================
# When run as: python -m canslim_monitor.tests.test_position_monitor_cli
# The current working directory should be C:\trading (parent of canslim_monitor)

script_dir = os.path.dirname(os.path.abspath(__file__))
package_dir = os.path.dirname(script_dir)  # canslim_monitor
root_dir = os.path.dirname(package_dir)    # C:\trading

# Add root to path if not already there
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Import from canslim_monitor package
from canslim_monitor.core.position_monitor import PositionMonitor, PositionContext
from canslim_monitor.services.alert_service import AlertData
from canslim_monitor.utils.level_calculator import LevelCalculator, PositionLevels


# =============================================================================
# TEST CONFIGURATION (simulates user_config.yaml position_monitoring section)
# =============================================================================

TEST_CONFIG = {
    'stop_loss': {
        'base_pct': 7.0,
        'warning_buffer_pct': 2.0,
        'stage_multipliers': {1: 1.0, 2: 0.85, 3: 0.70, 4: 0.60, 5: 0.50}
    },
    'trailing_stop': {
        'activation_pct': 15.0,
        'trail_pct': 8.0,
    },
    'pyramid': {
        'py1_min_pct': 0.0,
        'py1_max_pct': 5.0,
        'py2_min_pct': 5.0,
        'py2_max_pct': 10.0,
        'min_bars_since_entry': 2,
        'pullback_ema_tolerance': 1.0,
    },
    'eight_week_hold': {
        'gain_threshold_pct': 20.0,
        'trigger_window_days': 21,
        'hold_weeks': 8,
    },
    'technical': {
        'ma_50_warning_pct': 2.0,
        'ma_50_volume_confirm': 1.5,
        'ema_21_consecutive_days': 1,  # Trigger on first violation for testing
    },
    'health': {
        'time_threshold_days': 60,
        'deep_base_threshold': 35.0,
    },
    'earnings': {
        'warning_days': 14,
        'critical_days': 5,
        'negative_threshold': 0.0,
        'reduce_threshold': 10.0,
    },
    'cooldowns': {
        'hard_stop': 0,
        'stop_warning': 120,
        'tp1': 1440,
        'tp2': 1440,
        'eight_week_hold': 10080,
        'pyramid': 240,
        'ma_50_warning': 1440,
        'ma_50_sell': 1440,
        'ema_21_sell': 1440,
        'ten_week_sell': 10080,
        'health_critical': 60,
        'earnings': 1440,
        'late_stage': 10080,
    }
}


# =============================================================================
# TEST SCENARIOS
# =============================================================================

def create_test_scenarios() -> Dict[str, Dict[str, Any]]:
    """Create test scenarios for different alert conditions."""
    return {
        # Stop Loss Scenarios
        'stop_hard': {
            'description': 'Price at hard stop (-7%)',
            'context': PositionContext.from_test_data(
                symbol="NVDA",
                current_price=93.0,
                entry_price=100.0,
                state=1,
                shares=100,
                base_stage=1,
                days_in_position=15,
            ),
            'expected_alerts': ['HARD_STOP'],
        },
        'stop_warning': {
            'description': 'Price approaching stop (-5.5%)',
            'context': PositionContext.from_test_data(
                symbol="AMD",
                current_price=94.5,
                entry_price=100.0,
                state=1,
                shares=100,
                base_stage=1,
                days_in_position=10,
            ),
            'expected_alerts': ['WARNING'],
        },
        'stop_trailing': {
            'description': 'Trailing stop triggered (was +20%, now +10%)',
            'context': PositionContext.from_test_data(
                symbol="AAPL",
                current_price=110.0,
                entry_price=100.0,
                state=3,
                shares=100,
                base_stage=1,
                days_in_position=30,
                max_price=122.0,  # Was at +22%
                max_gain_pct=22.0,
            ),
            'expected_alerts': ['TRAILING_STOP'],
        },
        
        # Profit Scenarios
        'profit_tp1': {
            'description': 'TP1 target reached (+21%)',
            'context': PositionContext.from_test_data(
                symbol="MSFT",
                current_price=121.0,
                entry_price=100.0,
                state=2,
                shares=100,
                base_stage=1,
                days_in_position=20,
                tp1_pct=20.0,
            ),
            'expected_alerts': ['TP1'],
        },
        'profit_tp2': {
            'description': 'TP2 target reached (+27%)',
            'context': PositionContext.from_test_data(
                symbol="GOOG",
                current_price=127.0,
                entry_price=100.0,
                state=3,
                shares=100,
                base_stage=1,
                days_in_position=35,
                tp1_sold=25,  # Already sold at TP1
                tp2_pct=25.0,
            ),
            'expected_alerts': ['TP2'],
        },
        'profit_8week': {
            'description': '8-week hold activation (+22% in 10 days)',
            'context': PositionContext.from_test_data(
                symbol="META",
                current_price=122.0,
                entry_price=100.0,
                state=2,
                shares=100,
                base_stage=1,
                days_in_position=10,
                days_since_breakout=10,
            ),
            'expected_alerts': ['8_WEEK_HOLD'],
        },
        
        # Pyramid Scenarios
        'pyramid_py1': {
            'description': 'PY1 zone (+3%)',
            'context': PositionContext.from_test_data(
                symbol="TSLA",
                current_price=103.0,
                entry_price=100.0,
                state=1,
                shares=100,
                base_stage=1,
                days_in_position=5,
            ),
            'expected_alerts': ['P1_READY'],
        },
        'pyramid_py2': {
            'description': 'PY2 zone (+7%)',
            'context': PositionContext.from_test_data(
                symbol="AMZN",
                current_price=107.0,
                entry_price=100.0,
                state=2,
                shares=150,
                base_stage=1,
                days_in_position=10,
            ),
            'expected_alerts': ['P2_READY'],
        },
        'pyramid_pullback': {
            'description': 'Pullback to 21 EMA',
            'context': PositionContext.from_test_data(
                symbol="CRM",
                current_price=103.0,
                entry_price=100.0,
                state=2,
                shares=150,
                base_stage=1,
                days_in_position=15,
                ma_21=102.5,  # Price near 21 EMA
            ),
            'expected_alerts': ['PULLBACK'],
        },
        
        # MA Scenarios
        'ma_50_warning': {
            'description': 'Approaching 50 MA from above',
            'context': PositionContext.from_test_data(
                symbol="NFLX",
                current_price=101.0,
                entry_price=100.0,
                state=2,
                shares=100,
                base_stage=2,
                days_in_position=25,
                ma_50=100.0,  # 1% above 50 MA
            ),
            'expected_alerts': ['50_MA_WARNING'],
        },
        'ma_50_sell': {
            'description': 'Below 50 MA with heavy volume',
            'context': PositionContext.from_test_data(
                symbol="ADBE",
                current_price=97.0,
                entry_price=100.0,
                state=2,
                shares=100,
                base_stage=2,
                days_in_position=30,
                ma_50=100.0,  # Below 50 MA
                volume_ratio=1.8,  # Heavy volume
            ),
            'expected_alerts': ['50_MA_SELL'],
        },
        
        # Health Scenarios
        'health_earnings': {
            'description': 'Earnings in 5 days (losing position)',
            'context': PositionContext.from_test_data(
                symbol="SHOP",
                current_price=97.0,
                entry_price=100.0,
                state=2,
                shares=100,
                base_stage=2,
                days_in_position=40,
                days_to_earnings=5,
            ),
            'expected_alerts': ['EARNINGS'],
        },
        'health_late_stage': {
            'description': 'Late stage base (Stage 4)',
            'context': PositionContext.from_test_data(
                symbol="COIN",
                current_price=102.0,
                entry_price=100.0,
                state=1,
                shares=100,
                base_stage=4,
                days_in_position=3,
            ),
            'expected_alerts': ['LATE_STAGE'],
        },
        
        # =================================================================
        # ADDITIONAL TEST SCENARIOS FOR FULL COVERAGE
        # =================================================================
        
        # Pyramid Extended Scenarios
        'pyramid_py1_extended': {
            'description': 'PY1 Extended - Price beyond py1 zone (>5%)',
            'context': PositionContext.from_test_data(
                symbol="ROKU",
                current_price=106.0,  # +6% - beyond py1 zone
                entry_price=100.0,
                state=1,  # State 1 - haven't pyramided yet
                shares=100,
                base_stage=1,
                days_in_position=5,
                py1_done=False,
            ),
            'expected_alerts': ['P1_EXTENDED'],
        },
        'pyramid_py2_extended': {
            'description': 'PY2 Extended - Price beyond py2 zone (>10%)',
            'context': PositionContext.from_test_data(
                symbol="SQ",
                current_price=112.0,  # +12% - beyond py2 zone
                entry_price=100.0,
                state=2,  # State 2 - first pyramid done
                shares=150,
                base_stage=1,
                days_in_position=12,
                py1_done=True,
                py2_done=False,
            ),
            'expected_alerts': ['P2_EXTENDED'],
        },
        
        # MA Technical Scenarios
        'ma_21_ema_sell': {
            'description': '21 EMA Sell - Late stage, consecutive closes below 21 EMA',
            'context': PositionContext.from_test_data(
                symbol="PANW",
                current_price=97.0,  # Below 21 EMA
                entry_price=100.0,
                state=4,  # State 4+ required for this alert
                shares=100,
                base_stage=2,
                days_in_position=45,
                ma_21=100.0,  # Price below 21 EMA
            ),
            'expected_alerts': ['21_EMA_SELL'],
        },
        'ma_10_week_sell': {
            'description': '10-Week MA Sell - Weekly close below 10-week line',
            'context': PositionContext.from_test_data(
                symbol="DDOG",
                current_price=95.0,  # Below 10-week MA
                entry_price=100.0,
                state=3,
                shares=100,
                base_stage=2,
                days_in_position=50,
                ma_10_week=100.0,  # Price below 10-week
            ),
            'expected_alerts': ['10_WEEK_SELL'],
        },
        'ma_climax_top': {
            'description': 'Climax Top - Exhaustion pattern with heavy volume',
            'context': PositionContext.from_test_data(
                symbol="SMCI",
                current_price=118.0,  # +18% gain (above min 15%)
                entry_price=100.0,
                state=3,
                shares=100,
                base_stage=1,
                days_in_position=30,
                volume_ratio=3.0,  # 3x average (above 2.5x threshold)
                day_open=115.0,  # Gap up
                day_high=122.0,  # Wide spread
                day_low=116.0,
                prev_close=112.0,  # 2.7% gap up
            ),
            'expected_alerts': ['CLIMAX_TOP'],
        },
        
        # Health Scenarios
        'health_critical': {
            'description': 'Critical Health Score - Multiple warning factors',
            'context': PositionContext.from_test_data(
                symbol="SNAP",
                current_price=90.0,  # Below all MAs
                entry_price=100.0,
                state=2,
                shares=100,
                base_stage=4,  # Late stage adds risk
                days_in_position=65,  # Over 60 days
                ma_21=95.0,  # Below 21 EMA
                ma_50=97.0,  # Below 50 MA (2 pts)
                ma_200=92.0,  # Below 200 MA (3 pts)
                ad_rating="D",  # Bad A/D rating (2 pts)
            ),
            'expected_alerts': ['CRITICAL'],
        },
        'health_extended': {
            'description': 'Extended from Pivot - Price >5% above pivot',
            'context': PositionContext.from_test_data(
                symbol="UBER",
                current_price=108.0,  # +8% from pivot
                entry_price=100.0,
                pivot_price=100.0,
                state=1,
                shares=100,
                base_stage=1,
                days_in_position=5,
            ),
            'expected_alerts': ['EXTENDED'],
        },
        
        # Re-entry / Add Scenarios
        'add_21_ema_bounce': {
            'description': '21 EMA Pullback - Add opportunity (tests PULLBACK from PyramidChecker)',
            'context': PositionContext.from_test_data(
                symbol="NET",
                current_price=105.5,  # +5.5% gain, near 21 EMA
                entry_price=100.0,
                state=2,
                shares=100,
                base_stage=1,
                days_in_position=20,
                ma_21=105.0,  # Price within 1% of 21 EMA
                volume_ratio=1.2,  # Above average volume
            ),
            # Note: 21_EMA requires _detect_bounce history tracking, so we test PULLBACK instead
            'expected_alerts': ['PULLBACK'],
        },
        
        # No Alert Scenarios
        'no_alert_healthy': {
            'description': 'Healthy position, no alerts expected',
            'context': PositionContext.from_test_data(
                symbol="PLTR",
                current_price=104.0,  # +4% - within extended threshold (5%)
                entry_price=100.0,
                state=3,  # State 3 - done pyramiding
                shares=150,
                base_stage=1,
                days_in_position=20,
                py1_done=True,  # Already pyramided
                py2_done=True,  # Already pyramided
                ma_50=95.0,
                ma_21=102.0,
            ),
            'expected_alerts': [],
        },
    }


# =============================================================================
# CLI FUNCTIONS
# =============================================================================

def print_header(text: str, char: str = "="):
    """Print formatted header."""
    print(f"\n{char * 60}")
    print(f" {text}")
    print(char * 60)


def print_alert(alert: AlertData):
    """Print formatted alert."""
    emoji = {
        'STOP': '🛑',
        'PROFIT': '💰',
        'PYRAMID': '📈',
        'ADD': '📈',
        'TECHNICAL': '📉',
        'HEALTH': '⚠️',
    }.get(alert.alert_type.value if hasattr(alert.alert_type, 'value') else str(alert.alert_type), '📊')
    
    # Get subtype value
    subtype = alert.subtype.value if hasattr(alert.subtype, 'value') else str(alert.subtype)
    alert_type = alert.alert_type.value if hasattr(alert.alert_type, 'value') else str(alert.alert_type)
    
    print(f"\n{emoji} [{alert.priority}] {alert.symbol} - {subtype}")
    print(f"   Type: {alert_type}")
    print(f"   Action: {alert.action}")
    
    # Access context attributes
    ctx = alert.context
    print(f"   Price: ${ctx.current_price:.2f} | Entry: ${ctx.avg_cost:.2f} | P&L: {ctx.pnl_pct:+.1f}%")
    print(f"   ---")
    for line in alert.message.split('\n')[:5]:  # First 5 lines
        print(f"   {line}")


def run_scenario(monitor: PositionMonitor, name: str, scenario: Dict[str, Any]) -> bool:
    """Run a single test scenario."""
    print(f"\n{'─' * 50}")
    print(f"Scenario: {name}")
    print(f"Description: {scenario['description']}")
    
    context = scenario['context']
    expected = set(scenario['expected_alerts'])
    
    print(f"Input: {context.symbol} @ ${context.current_price:.2f} "
          f"(entry: ${context.entry_price:.2f}, state: {context.state})")
    
    # Run check
    alerts = monitor.check_position(context)
    
    # Extract subtype values for comparison (handle enum or string)
    actual = set()
    for a in alerts:
        if hasattr(a.subtype, 'value'):
            actual.add(a.subtype.value)
        else:
            actual.add(str(a.subtype))
    
    # Check results - expected should be SUBSET of actual (or equal)
    # This allows for multiple alerts being generated correctly
    if len(expected) == 0:
        # For "no alert" tests, actual must also be empty
        passed = len(actual) == 0
    else:
        # Expected alerts should all be present in actual
        passed = expected.issubset(actual)
    
    if passed:
        print(f"✅ PASS - Expected: {sorted(expected)}, Got: {sorted(actual)}")
    else:
        print(f"❌ FAIL - Expected: {sorted(expected)}, Got: {sorted(actual)}")
    
    # Show alerts
    for alert in alerts:
        print_alert(alert)
    
    return passed


def run_all_scenarios(monitor: PositionMonitor, scenarios: Dict[str, Dict]) -> int:
    """Run all test scenarios."""
    print_header("POSITION MONITOR CLI TEST")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Checkers: {[c.name for c in monitor.checkers]}")
    
    passed = 0
    failed = 0
    
    for name, scenario in scenarios.items():
        # Clear cooldowns between scenarios
        monitor.clear_cooldowns()
        
        if run_scenario(monitor, name, scenario):
            passed += 1
        else:
            failed += 1
    
    print_header("TEST RESULTS")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total:  {passed + failed}")
    
    return failed


def run_interactive(monitor: PositionMonitor):
    """Interactive mode for testing custom scenarios."""
    print_header("INTERACTIVE MODE")
    print("Enter position data to test alerts.")
    print("Type 'quit' to exit.\n")
    
    while True:
        try:
            symbol = input("Symbol (e.g., NVDA): ").strip().upper()
            if symbol.lower() == 'quit':
                break
            
            current_price = float(input("Current price: "))
            entry_price = float(input("Entry price: "))
            state = int(input("State (1-5): "))
            shares = int(input("Shares: "))
            
            # Optional fields
            base_stage = int(input("Base stage (1-5) [1]: ") or "1")
            days = int(input("Days in position [10]: ") or "10")
            
            ma_50_str = input("50 MA (blank to skip): ")
            ma_50 = float(ma_50_str) if ma_50_str else None
            
            ma_21_str = input("21 EMA (blank to skip): ")
            ma_21 = float(ma_21_str) if ma_21_str else None
            
            # Build context
            context = PositionContext.from_test_data(
                symbol=symbol,
                current_price=current_price,
                entry_price=entry_price,
                state=state,
                shares=shares,
                base_stage=base_stage,
                days_in_position=days,
                ma_50=ma_50,
                ma_21=ma_21,
            )
            
            # Check
            monitor.clear_cooldowns()
            alerts = monitor.check_position(context)
            
            print(f"\n{'─' * 40}")
            print(f"Alerts generated: {len(alerts)}")
            
            for alert in alerts:
                print_alert(alert)
            
            if not alerts:
                print("No alerts triggered.")
            
            print()
            
        except ValueError as e:
            print(f"Invalid input: {e}")
        except KeyboardInterrupt:
            break
    
    print("\nExiting interactive mode.")


def test_level_calculator():
    """Test level calculator separately."""
    print_header("LEVEL CALCULATOR TEST")
    
    calc = LevelCalculator(TEST_CONFIG)
    
    # Test Stage 1
    levels = calc.calculate_levels(100.0, base_stage=1)
    print(f"\nStage 1 ($100 entry):")
    print(f"  Hard Stop: ${levels.hard_stop:.2f} (-7.0%)")
    print(f"  Warning:   ${levels.warning_stop:.2f} (-5.0%)")
    print(f"  TP1:       ${levels.tp1:.2f} (+20%)")
    print(f"  TP2:       ${levels.tp2:.2f} (+25%)")
    print(f"  PY1 Zone:  ${levels.py1_min:.2f} - ${levels.py1_max:.2f}")
    print(f"  PY2 Zone:  ${levels.py2_min:.2f} - ${levels.py2_max:.2f}")
    
    # Test Stage 4 (tighter stop)
    levels4 = calc.calculate_levels(100.0, base_stage=4)
    print(f"\nStage 4 ($100 entry) - Tighter Stop:")
    print(f"  Hard Stop: ${levels4.hard_stop:.2f} ({((levels4.hard_stop - 100) / 100) * 100:.1f}%)")
    
    # Test trailing stop
    trailing = calc.calculate_trailing_stop(100.0, 120.0, 18.0)
    print(f"\nTrailing Stop (entry $100, max $120, gain 18%):")
    print(f"  Trailing Stop: ${trailing:.2f} (8% from max)")
    
    print("\n✅ Level Calculator OK")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Position Monitor CLI Tester',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                    # Run all tests
    %(prog)s --scenario stop    # Run stop-related tests
    %(prog)s --interactive      # Interactive mode
    %(prog)s --levels           # Test level calculator only
        """
    )
    parser.add_argument(
        '--scenario', '-s',
        help='Run specific scenario (stop, profit, pyramid, ma, health)'
    )
    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='Run in interactive mode'
    )
    parser.add_argument(
        '--levels', '-l',
        action='store_true',
        help='Test level calculator only'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Test live positions from database (validation mode)'
    )
    parser.add_argument(
        '--ibkr',
        action='store_true',
        help='Use live IBKR prices (requires TWS/Gateway running)'
    )
    parser.add_argument(
        '--symbol',
        help='Filter to specific symbol in live mode'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    # Test level calculator
    if args.levels:
        test_level_calculator()
        return 0
    
    # Live validation mode
    if args.live:
        return run_live_validation(
            use_ibkr=args.ibkr,
            symbol_filter=args.symbol,
            verbose=args.verbose
        )
    
    # Create monitor
    monitor = PositionMonitor(config=TEST_CONFIG)
    
    # Interactive mode
    if args.interactive:
        run_interactive(monitor)
        return 0
    
    # Get scenarios
    scenarios = create_test_scenarios()
    
    # Filter by scenario type
    if args.scenario:
        filter_key = args.scenario.lower()
        scenarios = {
            k: v for k, v in scenarios.items()
            if filter_key in k.lower()
        }
        if not scenarios:
            print(f"No scenarios matching '{args.scenario}'")
            return 1
    
    # Run tests
    failures = run_all_scenarios(monitor, scenarios)
    
    return 1 if failures > 0 else 0


# =============================================================================
# DISCORD HELPER
# =============================================================================

def send_alert_to_discord(notifier, alert: AlertData) -> bool:
    """
    Send an AlertData to Discord using the appropriate format.
    
    Args:
        notifier: DiscordNotifier instance
        alert: AlertData from position monitor
        
    Returns:
        True if sent successfully
    """
    from datetime import datetime
    
    # Color mapping
    COLORS = {
        'red': 0xFF0000,
        'orange': 0xFFA500,
        'yellow': 0xFFFF00,
        'green': 0x00FF00,
        'blue': 0x0000FF,
    }
    
    # Determine color based on priority
    if alert.priority == 'P0':
        color = COLORS['red']
    elif alert.priority == 'P1':
        color = COLORS['orange']
    else:
        color = COLORS['green']
    
    # Build emoji prefix
    emoji_map = {
        'STOP': '🛑',
        'PROFIT': '💰',
        'PYRAMID': '📈',
        'HEALTH': '⚠️',
        'MA': '📊',
    }
    emoji = emoji_map.get(alert.alert_type, '📌')
    
    # Build title
    title = f"{emoji} [{alert.priority}] {alert.symbol} - {alert.subtype}"
    
    # Build fields - use correct attribute names from AlertData
    fields = [
        {'name': 'Action', 'value': alert.action or 'N/A', 'inline': False},
        {'name': 'Price', 'value': f"${alert.current_price:.2f}", 'inline': True},
        {'name': 'Entry', 'value': f"${alert.entry_price:.2f}", 'inline': True},
        {'name': 'P&L', 'value': f"{alert.pnl_pct:+.1f}%", 'inline': True},
    ]
    
    # Add message as details
    if alert.message:
        msg_text = alert.message
        if len(msg_text) > 1024:
            msg_text = msg_text[:1020] + "..."
        fields.append({'name': 'Details', 'value': msg_text, 'inline': False})
    
    embed = {
        'title': title,
        'color': color,
        'fields': fields,
        'timestamp': datetime.utcnow().isoformat(),
        'footer': {'text': f'Position Monitor | {alert.alert_type}'}
    }
    
    return notifier.send(embed=embed, channel='position')


# =============================================================================
# LIVE VALIDATION MODE
# =============================================================================

def run_live_validation(
    use_ibkr: bool = False,
    symbol_filter: str = None,
    verbose: bool = False,
    send_discord: bool = False
) -> int:
    """
    Validate position monitor against real positions in database.
    
    Args:
        use_ibkr: If True, connect to IBKR for live prices
        symbol_filter: If provided, only test this symbol
        verbose: Enable verbose output
        send_discord: If True, actually send alerts to Discord
        
    Returns:
        0 on success, 1 on error
    """
    print_header("LIVE POSITION VALIDATION")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'IBKR Live Prices' if use_ibkr else 'Database Last Price'}")
    if symbol_filter:
        print(f"Filter: {symbol_filter}")
    if send_discord:
        print(f"Discord: ENABLED - Alerts will be sent!")
    print()
    
    # Load config
    try:
        from canslim_monitor.utils.config import load_config
        config = load_config()
        pm_config = config.get('position_monitoring', TEST_CONFIG)
        db_path = config.get('database', {}).get('path')
    except Exception as e:
        print(f"⚠️  Could not load config, using defaults: {e}")
        pm_config = TEST_CONFIG
        db_path = None
    
    # Initialize Discord notifier if sending
    discord_notifier = None
    if send_discord:
        try:
            from canslim_monitor.integrations.discord_notifier import DiscordNotifier
            discord_config = config.get('discord', {})
            webhooks = discord_config.get('webhooks', {})
            position_webhook = webhooks.get('position')
            
            if position_webhook:
                discord_notifier = DiscordNotifier(webhooks=webhooks)
                print(f"✅ Discord notifier initialized")
            else:
                print(f"⚠️  No position webhook configured - alerts will NOT be sent")
                send_discord = False
        except Exception as e:
            print(f"⚠️  Discord setup failed: {e}")
            send_discord = False
    
    # Connect to database using path from config
    try:
        from canslim_monitor.data.database import get_database
        from canslim_monitor.data.repositories import PositionRepository
        
        db = get_database(db_path=db_path)
        print(f"Database: {db.db_path}")
        session = db.get_new_session()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1
    
    # Get IBKR client if requested
    ibkr_client = None
    if use_ibkr:
        try:
            from canslim_monitor.integrations.ibkr_client import IBKRClient
            from canslim_monitor.utils.config import get_ibkr_config
            
            ibkr_config = get_ibkr_config()
            print(f"Connecting to IBKR at {ibkr_config.get('host')}:{ibkr_config.get('port')}...")
            
            ibkr_client = IBKRClient(
                host=ibkr_config.get('host', '127.0.0.1'),
                port=ibkr_config.get('port', 7497),
                client_id=ibkr_config.get('client_id', 10),
            )
            
            if not ibkr_client.connect():
                print("⚠️  IBKR connection failed, falling back to database prices")
                ibkr_client = None
            else:
                print("✅ IBKR connected")
        except Exception as e:
            print(f"⚠️  IBKR setup failed: {e}")
            print("   Falling back to database prices")
            ibkr_client = None
    
    print()
    
    # Get active positions using ORM
    try:
        repo = PositionRepository(session)
        positions = repo.get_in_position()  # state >= 1
        
        if symbol_filter:
            positions = [p for p in positions if p.symbol.upper() == symbol_filter.upper()]
        
        if not positions:
            print("No active positions found.")
            session.close()
            return 0
        
        print(f"Found {len(positions)} active position(s)")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Failed to fetch positions: {e}")
        session.close()
        return 1
    
    # Create position monitor
    monitor = PositionMonitor(config=pm_config)
    
    # Track results
    total_alerts = 0
    positions_with_alerts = 0
    all_alerts: List[AlertData] = []
    
    # Process each position
    for position in positions:
        print(f"\n{'─' * 60}")
        print(f"📊 {position.symbol} (State {position.state})")
        
        # Get price
        current_price = None
        price_source = "unknown"
        
        if ibkr_client:
            try:
                current_price = ibkr_client.get_price(position.symbol)
                if current_price:
                    price_source = "IBKR"
            except Exception as e:
                if verbose:
                    print(f"   IBKR price fetch failed: {e}")
        
        if not current_price:
            current_price = position.last_price
            price_source = "database"
        
        if not current_price:
            current_price = position.avg_cost or position.pivot
            price_source = "entry (no current price)"
        
        if not current_price:
            print(f"   ⚠️  No price available, skipping")
            continue
        
        # Calculate P&L
        entry_price = position.avg_cost or position.pivot or current_price
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        total_shares = position.total_shares or 0
        
        print(f"   Entry: ${entry_price:.2f} | Current: ${current_price:.2f} ({price_source})")
        print(f"   P&L: {pnl_pct:+.1f}% | Shares: {total_shares}")
        if position.pattern:
            print(f"   Pattern: {position.pattern} | Stage: {position.base_stage or 'N/A'}")
        
        # Build technical data
        technical_data = {
            'max_price': current_price,  # We don't have max tracking yet
            'max_gain_pct': max(0, pnl_pct),
            'ma_21': None,
            'ma_50': None,
            'ma_200': None,
            'ma_10_week': None,
            'volume_ratio': 1.0,
        }
        
        # Build context using ORM model
        try:
            context = PositionContext.from_position(
                position=position,
                current_price=current_price,
                technical_data=technical_data,
            )
        except Exception as e:
            print(f"   ⚠️  Failed to build context: {e}")
            continue
        
        # Run checkers
        monitor.clear_cooldowns(position.symbol)  # Clear cooldowns for clean test
        alerts = monitor.check_position(context)
        
        if alerts:
            positions_with_alerts += 1
            total_alerts += len(alerts)
            all_alerts.extend(alerts)
            
            print(f"\n   🔔 {len(alerts)} ALERT(S) WOULD FIRE:")
            for alert in alerts:
                print_discord_preview(alert, indent=6)
                
                # Send to Discord if enabled
                if send_discord and discord_notifier:
                    try:
                        send_alert_to_discord(discord_notifier, alert)
                        print(f"      ✅ Sent to Discord")
                    except Exception as e:
                        print(f"      ❌ Discord send failed: {e}")
        else:
            print(f"\n   ✅ No alerts")
    
    # Cleanup
    session.close()
    if ibkr_client:
        try:
            ibkr_client.disconnect()
        except:
            pass
    
    # Summary
    print("\n" + "=" * 60)
    print_header("VALIDATION SUMMARY")
    print(f"Positions checked: {len(positions)}")
    print(f"Positions with alerts: {positions_with_alerts}")
    print(f"Total alerts: {total_alerts}")
    
    if all_alerts:
        # Group by priority
        p0_alerts = [a for a in all_alerts if a.priority == "P0"]
        p1_alerts = [a for a in all_alerts if a.priority == "P1"]
        p2_alerts = [a for a in all_alerts if a.priority == "P2"]
        
        print(f"\nBy Priority:")
        print(f"  🔴 P0 (Immediate): {len(p0_alerts)}")
        print(f"  🟡 P1 (Actionable): {len(p1_alerts)}")
        print(f"  🟢 P2 (Informational): {len(p2_alerts)}")
        
        # Group by type
        print(f"\nBy Type:")
        type_counts = {}
        for alert in all_alerts:
            type_counts[alert.alert_type] = type_counts.get(alert.alert_type, 0) + 1
        for atype, count in sorted(type_counts.items()):
            print(f"  {atype}: {count}")
        
        if p0_alerts:
            print(f"\n⚠️  {len(p0_alerts)} P0 ALERT(S) REQUIRE IMMEDIATE ATTENTION:")
            for alert in p0_alerts:
                print(f"   • {alert.symbol}: {alert.subtype} - {alert.action}")
    
    return 0


def print_discord_preview(alert: AlertData, indent: int = 0):
    """Print alert formatted as it would appear in Discord."""
    pad = " " * indent
    
    # Priority emoji
    priority_emoji = {
        'P0': '🔴',
        'P1': '🟡', 
        'P2': '🟢',
    }.get(alert.priority, '⚪')
    
    # Type emoji
    type_emoji = {
        'STOP': '🛑',
        'PROFIT': '💰',
        'PYRAMID': '📈',
        'ADD': '📈',
        'TECHNICAL': '📉',
        'HEALTH': '⚠️',
    }.get(alert.alert_type, '📊')
    
    print(f"{pad}┌{'─' * 50}")
    print(f"{pad}│ {priority_emoji} [{alert.priority}] {type_emoji} {alert.symbol} - {alert.subtype}")
    print(f"{pad}│ Action: {alert.action}")
    print(f"{pad}│ Price: ${alert.current_price:.2f} | Entry: ${alert.entry_price:.2f} | P&L: {alert.pnl_pct:+.1f}%")
    print(f"{pad}│")
    
    # Show first few lines of message
    for i, line in enumerate(alert.message.split('\n')[:4]):
        print(f"{pad}│ {line}")
    
    print(f"{pad}└{'─' * 50}")


if __name__ == "__main__":
    sys.exit(main())
