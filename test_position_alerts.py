"""
Position Alert Test Tool
========================
Manually test position monitoring alerts outside market hours.

Usage:
    python test_position_alerts.py                    # List positions, pick one to test
    python test_position_alerts.py --symbol NVDA      # Test specific symbol
    python test_position_alerts.py --symbol NVDA --scenario stop  # Test stop scenario
    python test_position_alerts.py --send             # Actually send to Discord

Scenarios:
    stop      - Simulate price near/at stop loss
    profit    - Simulate TP1/TP2 targets hit
    pyramid   - Simulate pyramid add zones
    ma        - Simulate MA violations
    health    - Simulate health warnings
    all       - Run all scenarios
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# Add parent directory to path (so canslim_monitor package is importable)
project_root = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(project_root)
sys.path.insert(0, parent_dir)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('test_alerts')


def load_config():
    """Load configuration."""
    import yaml
    config_path = os.path.join(project_root, 'user_config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def get_database(config):
    """Get database connection."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = config.get('database', {}).get('path', 'canslim_positions.db')
    engine = create_engine(f'sqlite:///{db_path}')
    Session = sessionmaker(bind=engine)
    return Session


def get_positions(session_factory, state_filter: Optional[int] = None):
    """Get positions from database."""
    from canslim_monitor.data.models import Position

    session = session_factory()
    try:
        query = session.query(Position)
        if state_filter is not None:
            query = query.filter(Position.state == state_filter)
        else:
            query = query.filter(Position.state >= 1)  # Active positions

        positions = query.all()
        # Detach from session
        for pos in positions:
            session.expunge(pos)
        return positions
    finally:
        session.close()


def build_mock_context(
    position,
    price_override: float = None,
    pnl_override: float = None,
    ma_21: float = None,
    ma_50: float = None,
    volume_ratio: float = 1.0,
    days_to_earnings: int = None,
    market_regime: str = "NEUTRAL",
):
    """Build a mock PositionContext for testing."""
    from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext

    entry_price = position.avg_cost or position.pivot or 100.0
    current_price = price_override or position.pivot or entry_price

    if pnl_override is not None:
        current_price = entry_price * (1 + pnl_override / 100)

    pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

    # Default MAs based on price
    if ma_21 is None:
        ma_21 = current_price * 0.98  # 2% below by default
    if ma_50 is None:
        ma_50 = current_price * 0.95  # 5% below by default

    # Parse base stage
    base_stage = 1
    if position.base_stage:
        try:
            stage_str = str(position.base_stage)[0]
            if stage_str.isdigit():
                base_stage = int(stage_str)
        except:
            pass

    # Calculate days in position
    days_in_position = 0
    if position.entry_date:
        days_in_position = (datetime.now().date() - position.entry_date).days

    days_since_breakout = 0
    if position.breakout_date:
        days_since_breakout = (datetime.now().date() - position.breakout_date).days

    return PositionContext(
        symbol=position.symbol,
        position_id=position.id,
        current_price=current_price,
        entry_price=entry_price,
        pivot_price=position.pivot or entry_price,
        shares=position.total_shares or 100,
        state=position.state,
        pnl_pct=pnl_pct,
        pnl_dollars=pnl_pct * (position.total_shares or 100) * entry_price / 100,
        max_price=current_price * 1.1 if pnl_pct > 0 else current_price,
        max_gain_pct=max(pnl_pct, 0) + 5,
        ma_21=ma_21,
        ma_50=ma_50,
        ma_200=current_price * 0.85,
        ma_10_week=current_price * 0.92,
        volume_ratio=volume_ratio,
        rs_rating=position.rs_rating or 85,
        ad_rating=position.ad_rating or "B",
        base_stage=base_stage,
        days_in_position=days_in_position,
        days_since_breakout=days_since_breakout,
        eight_week_hold_active=getattr(position, 'eight_week_hold_active', False),
        py1_done=getattr(position, 'py1_done', False),
        py2_done=getattr(position, 'py2_done', False),
        tp1_sold=getattr(position, 'tp1_sold', 0) or 0,
        tp2_sold=getattr(position, 'tp2_sold', 0) or 0,
        days_to_earnings=days_to_earnings,
        health_score=80,
        health_rating="HEALTHY",
        canslim_grade=position.entry_grade or "B",
        canslim_score=position.entry_score or 15,
        market_regime=market_regime,
        day_open=current_price * 0.99,
        day_high=current_price * 1.02,
        day_low=current_price * 0.97,
        prev_close=current_price * 0.995,
    )


def run_stop_scenario(position, config, send_discord=False):
    """Test stop-related alerts."""
    from canslim_monitor.core.position_monitor.checkers.stop_checker import StopChecker
    from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext

    print("\n" + "="*60)
    print(f"STOP SCENARIO: {position.symbol}")
    print("="*60)

    checker = StopChecker(config.get('position_monitoring', {}), logger)

    entry = position.avg_cost or position.pivot or 100

    # Test 1: Stop Warning (approaching stop)
    print("\n--- Test 1: Stop Warning (price near stop) ---")
    context = build_mock_context(position, pnl_override=-5.5)  # -5.5% (approaching 7% stop)
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 2: Hard Stop Hit
    print("\n--- Test 2: Hard Stop Hit ---")
    context = build_mock_context(position, pnl_override=-7.5)  # -7.5% (past stop)
    # Reset cooldown for testing
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 3: Trailing Stop (was up, now pulled back)
    print("\n--- Test 3: Trailing Stop ---")
    context = build_mock_context(position, pnl_override=8.0)  # +8% but max was +18%
    context = PositionContext(
        **{**context.__dict__, 'max_gain_pct': 18.0, 'max_price': entry * 1.18}
    )
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)


def run_profit_scenario(position, config, send_discord=False):
    """Test profit-related alerts."""
    from canslim_monitor.core.position_monitor.checkers.profit_checker import ProfitChecker
    from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext

    print("\n" + "="*60)
    print(f"PROFIT SCENARIO: {position.symbol}")
    print("="*60)

    checker = ProfitChecker(config.get('position_monitoring', {}), logger)

    # Test 1: TP1 Hit
    print("\n--- Test 1: TP1 Hit (+20%) ---")
    context = build_mock_context(position, pnl_override=22.0)
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 2: TP2 Hit
    print("\n--- Test 2: TP2 Hit (+25%) ---")
    context = build_mock_context(position, pnl_override=27.0)
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 3: 8-Week Hold Rule
    print("\n--- Test 3: 8-Week Hold Rule (+20% in <3 weeks) ---")
    context = build_mock_context(position, pnl_override=22.0)
    # Simulate recent breakout
    context = PositionContext(**{**context.__dict__, 'days_since_breakout': 15})
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)


def run_pyramid_scenario(position, config, send_discord=False):
    """Test pyramid-related alerts."""
    from canslim_monitor.core.position_monitor.checkers.pyramid_checker import PyramidChecker
    from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext

    print("\n" + "="*60)
    print(f"PYRAMID SCENARIO: {position.symbol}")
    print("="*60)

    checker = PyramidChecker(config.get('position_monitoring', {}), logger)

    # Test 1: PY1 Ready (0-5% zone)
    print("\n--- Test 1: PY1 Ready (+3%) ---")
    context = build_mock_context(position, pnl_override=3.0)
    context = PositionContext(**{**context.__dict__, 'state': 1, 'days_in_position': 5})
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 2: PY1 Extended
    print("\n--- Test 2: PY1 Extended (+7%) ---")
    context = build_mock_context(position, pnl_override=7.0)
    context = PositionContext(**{**context.__dict__, 'state': 1, 'days_in_position': 5})
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 3: PY2 Ready (5-10% zone)
    print("\n--- Test 3: PY2 Ready (+7%) ---")
    context = build_mock_context(position, pnl_override=7.0)
    context = PositionContext(**{**context.__dict__, 'state': 2, 'days_in_position': 10, 'py1_done': True})
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 4: Pullback to 21 EMA
    print("\n--- Test 4: Pullback to 21 EMA ---")
    entry = position.avg_cost or position.pivot or 100
    price = entry * 1.05
    context = build_mock_context(position, price_override=price, ma_21=price * 1.005)  # Price near 21 EMA
    context = PositionContext(**{**context.__dict__, 'state': 2, 'days_in_position': 15})
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)


def run_ma_scenario(position, config, send_discord=False):
    """Test MA-related alerts."""
    from canslim_monitor.core.position_monitor.checkers.ma_checker import MAChecker
    from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext

    print("\n" + "="*60)
    print(f"MA SCENARIO: {position.symbol}")
    print("="*60)

    checker = MAChecker(config.get('position_monitoring', {}), logger)

    entry = position.avg_cost or position.pivot or 100

    # Test 1: 50 MA Warning
    print("\n--- Test 1: 50 MA Warning (approaching) ---")
    price = entry * 1.02
    context = build_mock_context(position, price_override=price, ma_50=price * 1.015)  # 1.5% above 50 MA
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 2: 50 MA Sell (below with volume)
    print("\n--- Test 2: 50 MA Sell (below with volume) ---")
    price = entry * 0.98
    context = build_mock_context(position, price_override=price, ma_50=price * 1.02, volume_ratio=1.8)
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 3: 21 EMA Sell (late stage)
    print("\n--- Test 3: 21 EMA Sell (late stage) ---")
    price = entry * 1.15
    context = build_mock_context(position, price_override=price, ma_21=price * 1.02)
    context = PositionContext(**{**context.__dict__, 'state': 4, 'base_stage': 4})
    checker._ema_violation_counts[position.symbol] = 3  # Simulate consecutive violations
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 4: Climax Top
    print("\n--- Test 4: Climax Top ---")
    price = entry * 1.25
    context = build_mock_context(position, price_override=price, pnl_override=25.0, volume_ratio=3.0)
    context = PositionContext(**{
        **context.__dict__,
        'day_high': price * 1.05,
        'day_low': price * 0.96,
        'day_open': price * 1.03,
        'prev_close': price * 0.98,
    })
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)


def run_health_scenario(position, config, send_discord=False):
    """Test health-related alerts."""
    from canslim_monitor.core.position_monitor.checkers.health_checker import HealthChecker
    from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext

    print("\n" + "="*60)
    print(f"HEALTH SCENARIO: {position.symbol}")
    print("="*60)

    checker = HealthChecker(config.get('position_monitoring', {}), logger)

    # Test 1: Earnings Warning
    print("\n--- Test 1: Earnings Warning (10 days) ---")
    context = build_mock_context(position, pnl_override=5.0, days_to_earnings=10)
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 2: Earnings Critical (losing position)
    print("\n--- Test 2: Earnings Critical (losing, 3 days) ---")
    context = build_mock_context(position, pnl_override=-3.0, days_to_earnings=3)
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 3: Late Stage Warning
    print("\n--- Test 3: Late Stage Warning (Stage 4) ---")
    context = build_mock_context(position, pnl_override=5.0)
    context = PositionContext(**{**context.__dict__, 'base_stage': 4})
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)

    # Test 4: Extended from Pivot
    print("\n--- Test 4: Extended from Pivot (+8%) ---")
    entry = position.avg_cost or position.pivot or 100
    pivot = position.pivot or entry
    price = pivot * 1.08  # 8% above pivot
    context = build_mock_context(position, price_override=price)
    context = PositionContext(**{**context.__dict__, 'pivot_price': pivot})
    checker._cooldowns = {}
    alerts = checker.check(position, context)
    display_alerts(alerts, send_discord, config)


def display_alerts(alerts: List, send_discord: bool, config: Dict):
    """Display alerts and optionally send to Discord."""
    if not alerts:
        print("  No alerts generated")
        return

    for alert in alerts:
        print(f"\n  Alert: {alert.alert_type.value} / {alert.subtype.value}")
        print(f"  Priority: {alert.priority}")
        print(f"  Action: {alert.action}")
        print("-" * 40)

        # Check if it's an embed format
        if alert.message.startswith("EMBED:"):
            import json
            embed_json = alert.message[6:]
            embed = json.loads(embed_json)
            print(f"  Title: {embed.get('title', 'N/A')}")
            print(f"  Description:\n{embed.get('description', 'N/A')}")
            print(f"  Footer: {embed.get('footer', {}).get('text', 'N/A')}")
            print(f"  Color: {hex(embed.get('color', 0))}")
        else:
            print(f"  Message:\n{alert.message[:500]}...")

        if send_discord:
            send_to_discord(alert, config)


def send_to_discord(alert, config: Dict):
    """Send alert to Discord."""
    try:
        from canslim_monitor.integrations.discord_notifier import DiscordNotifier

        discord_config = config.get('discord', {})
        webhooks = discord_config.get('webhooks', {})

        notifier = DiscordNotifier(
            webhooks=webhooks,
            default_webhook=webhooks.get('position'),
        )

        # Position alerts go to position channel
        if alert.message.startswith("EMBED:"):
            import json
            embed_json = alert.message[6:]
            embed = json.loads(embed_json)
            notifier.send(embed=embed, channel='position')
        else:
            notifier.send(
                content=alert.message,
                channel='position',
            )

        print("  [SENT TO DISCORD]")

    except Exception as e:
        print(f"  [DISCORD ERROR: {e}]")


def list_positions(session_factory):
    """List available positions for testing."""
    positions = get_positions(session_factory)

    print("\n" + "="*60)
    print("AVAILABLE POSITIONS FOR TESTING")
    print("="*60)
    print(f"{'Symbol':<8} {'State':<6} {'Entry':<10} {'Pivot':<10} {'Stage':<6}")
    print("-" * 50)

    for pos in positions:
        entry = pos.avg_cost or pos.pivot or 0
        pivot = pos.pivot or 0
        stage = pos.base_stage or "?"
        print(f"{pos.symbol:<8} {pos.state:<6} ${entry:<9.2f} ${pivot:<9.2f} {stage:<6}")

    return positions


def main():
    parser = argparse.ArgumentParser(
        description='Test position monitoring alerts outside market hours',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Scenarios:
  stop      Simulate stop loss alerts (warning, hard stop, trailing)
  profit    Simulate profit alerts (TP1, TP2, 8-week hold)
  pyramid   Simulate pyramid alerts (PY1, PY2, pullback)
  ma        Simulate MA alerts (50 MA, 21 EMA, climax top)
  health    Simulate health alerts (earnings, late stage, extended)
  all       Run all scenarios

Examples:
  python test_position_alerts.py                         # List positions
  python test_position_alerts.py --symbol NVDA           # Test all scenarios for NVDA
  python test_position_alerts.py --symbol NVDA --scenario stop
  python test_position_alerts.py --symbol NVDA --send    # Send to Discord
        """
    )

    parser.add_argument('--symbol', '-s', help='Symbol to test')
    parser.add_argument('--scenario', '-c',
                       choices=['stop', 'profit', 'pyramid', 'ma', 'health', 'all'],
                       default='all', help='Scenario to run')
    parser.add_argument('--send', action='store_true',
                       help='Actually send alerts to Discord')
    parser.add_argument('--list', '-l', action='store_true',
                       help='Just list positions')

    args = parser.parse_args()

    # Load config and database
    config = load_config()
    session_factory = get_database(config)

    # List mode
    if args.list or not args.symbol:
        positions = list_positions(session_factory)
        if not args.symbol:
            print("\nUse --symbol <SYMBOL> to test a specific position")
            print("Use --scenario <scenario> to test specific alert types")
            print("Use --send to actually send alerts to Discord")
        return

    # Get the position
    positions = get_positions(session_factory)
    position = next((p for p in positions if p.symbol.upper() == args.symbol.upper()), None)

    if not position:
        print(f"Position not found: {args.symbol}")
        print("Available positions:")
        list_positions(session_factory)
        return 1

    print(f"\nTesting alerts for: {position.symbol}")
    print(f"State: {position.state}, Entry: ${position.avg_cost or position.pivot:.2f}")
    print(f"Send to Discord: {args.send}")

    # Run scenarios
    scenarios = {
        'stop': run_stop_scenario,
        'profit': run_profit_scenario,
        'pyramid': run_pyramid_scenario,
        'ma': run_ma_scenario,
        'health': run_health_scenario,
    }

    if args.scenario == 'all':
        for name, func in scenarios.items():
            func(position, config, args.send)
    else:
        scenarios[args.scenario](position, config, args.send)

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)


if __name__ == '__main__':
    sys.exit(main() or 0)
