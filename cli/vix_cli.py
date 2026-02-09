"""
CBOE VIX Index CLI Tool
========================

Standalone CLI for fetching and displaying VIX data.

Usage:
    python -m cli.vix_cli current              # Fetch and display current VIX
    python -m cli.vix_cli history --days 30     # Show stored VIX history from DB
    python -m cli.vix_cli seed --days 365       # Backfill VIX data into DB
"""

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from regime.vix_client import VixClient, classify_vix


def load_config() -> dict:
    """Load config from user_config.yaml or config.yaml."""
    base_dir = Path(__file__).parent.parent
    for path in [base_dir / 'user_config.yaml', base_dir / 'config.yaml']:
        if path.exists():
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
    return {}


def cmd_current(args, config):
    """Fetch and display the current VIX level."""
    print("\nFetching CBOE VIX Index...")

    client = VixClient.from_config(config)
    data = client.fetch_current()

    if not data:
        print("ERROR: Could not fetch VIX data.")
        print("Yahoo Finance API may be temporarily unavailable.")
        return 1

    rating = classify_vix(data.close)

    print(f"\n{'='*50}")
    print(f"  CBOE Volatility Index (VIX)")
    print(f"{'='*50}")
    print(f"  Level:    {data.close:.2f}")
    print(f"  Rating:   {rating}")

    if data.previous_close > 0:
        delta = data.close - data.previous_close
        pct = (delta / data.previous_close) * 100
        print(f"  Previous: {data.previous_close:.2f} ({delta:+.2f}, {pct:+.1f}%)")

    # Visual gauge (0-50 range for VIX)
    print(f"\n  {'='*40}")
    gauge_pos = int(min(data.close, 50) / 50 * 38)
    gauge = '.' * 38
    gauge = gauge[:gauge_pos] + '#' + gauge[gauge_pos + 1:]
    print(f"  [{gauge}]")
    print(f"  Low                              Extreme")
    print(f"  {'='*40}\n")

    if args.verbose:
        print("Fetching historical data...")
        history = client.fetch_historical(days=30)
        if history:
            print(f"\n  Recent History (last 10 days):")
            print(f"  {'Date':<12} {'Close':>7}  Rating")
            print(f"  {'-'*40}")
            for dt, close in history[-10:]:
                r = classify_vix(close)
                print(f"  {dt.isoformat():<12} {close:>7.2f}  {r}")

    return 0


def cmd_history(args, config):
    """Show stored VIX history from the database."""
    db_path = config.get('database', {}).get('path', 'canslim_positions.db')

    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if the column exists
    cursor.execute("PRAGMA table_info(market_regime_alerts)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'vix_close' not in columns:
        print("ERROR: vix_close column not found. Run migration first:")
        print('  python -m migrations.add_vix_columns --db "<path>"')
        conn.close()
        return 1

    days = args.days or 30
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    cursor.execute("""
        SELECT date, vix_close, vix_previous_close,
               composite_score, regime
        FROM market_regime_alerts
        WHERE date >= ? AND vix_close IS NOT NULL
        ORDER BY date DESC
    """, (cutoff,))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"\nNo VIX data found in the last {days} days.")
        print("Run 'python -m cli.vix_cli seed' to backfill VIX data.")
        return 0

    print(f"\n{'='*70}")
    print(f"  VIX History (last {days} days)")
    print(f"{'='*70}")
    print(f"  {'Date':<12} {'VIX':>7} {'Prev':>7} {'Chg':>7} {'Rating':<15} {'Regime':>8}")
    print(f"  {'-'*60}")

    for row in rows:
        dt, vix, prev, comp_score, regime = row
        vix_str = f"{vix:.2f}" if vix else "--"
        prev_str = f"{prev:.2f}" if prev else "--"
        chg_str = f"{vix - prev:+.2f}" if vix and prev else "--"
        rating = classify_vix(vix) if vix else "--"
        regime_str = regime or "--"
        print(f"  {dt:<12} {vix_str:>7} {prev_str:>7} {chg_str:>7} {rating:<15} {regime_str:>8}")

    print(f"\n  Total records: {len(rows)}")
    print(f"{'='*70}\n")

    return 0


def cmd_seed(args, config):
    """Backfill VIX historical data into existing regime alerts."""
    db_path = config.get('database', {}).get('path', 'canslim_positions.db')

    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        return 1

    days = args.days or 365

    print(f"\nSeeding VIX data for last {days} days...")
    print("Fetching historical data from Yahoo Finance...")

    client = VixClient.from_config(config)
    history = client.fetch_historical(days=days)

    if not history:
        print("ERROR: Could not fetch historical VIX data.")
        return 1

    print(f"  Got {len(history)} historical data points")

    # Build date -> (close, previous_close) mapping
    vix_by_date = {}
    for i, (dt, close) in enumerate(history):
        prev_close = history[i - 1][1] if i > 0 else None
        vix_by_date[dt.isoformat()] = (close, prev_close)

    # Update database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check column exists
    cursor.execute("PRAGMA table_info(market_regime_alerts)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'vix_close' not in columns:
        print("ERROR: vix_close column not found. Run migration first:")
        print('  python -m migrations.add_vix_columns --db "<path>"')
        conn.close()
        return 1

    # Get existing alerts without VIX data
    cursor.execute("""
        SELECT date FROM market_regime_alerts
        WHERE vix_close IS NULL
        ORDER BY date
    """)
    missing_dates = [row[0] for row in cursor.fetchall()]

    updated = 0
    for dt in missing_dates:
        if dt in vix_by_date:
            close, prev_close = vix_by_date[dt]
            cursor.execute("""
                UPDATE market_regime_alerts
                SET vix_close = ?, vix_previous_close = ?
                WHERE date = ?
            """, (close, prev_close, dt))
            updated += 1

    conn.commit()
    conn.close()

    print(f"\n  Updated {updated} records out of {len(missing_dates)} missing")
    print(f"  Historical data points available: {len(vix_by_date)}")

    if updated > 0:
        print(f"\nSEED COMPLETE: {updated} records backfilled.")
    else:
        print("\nNo records needed updating.")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="CBOE VIX Index CLI Tool"
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Enable verbose output'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # current command
    subparsers.add_parser('current', help='Fetch and display current VIX')

    # history command
    history_parser = subparsers.add_parser('history', help='Show stored VIX history from DB')
    history_parser.add_argument(
        '--days', type=int, default=30,
        help='Number of days to show (default: 30)'
    )

    # seed command
    seed_parser = subparsers.add_parser('seed', help='Backfill historical VIX data into DB')
    seed_parser.add_argument(
        '--days', type=int, default=365,
        help='Number of days to seed (default: 365)'
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    if not args.command:
        parser.print_help()
        return 1

    config = load_config()

    if args.command == 'current':
        return cmd_current(args, config)
    elif args.command == 'history':
        return cmd_history(args, config)
    elif args.command == 'seed':
        return cmd_seed(args, config)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    exit(main())
