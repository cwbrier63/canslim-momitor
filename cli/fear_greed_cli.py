"""
CNN Fear & Greed Index CLI Tool
================================

Standalone CLI for fetching and displaying CNN's Fear & Greed Index data.

Usage:
    python -m cli.fear_greed_cli current              # Fetch and display current score
    python -m cli.fear_greed_cli history --days 30     # Show stored history from DB
    python -m cli.fear_greed_cli seed --days 90        # Backfill F&G data into DB
"""

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

import yaml

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from regime.fear_greed_client import FearGreedClient, classify_score


def load_config() -> dict:
    """Load config from user_config.yaml or config.yaml."""
    base_dir = Path(__file__).parent.parent
    for path in [base_dir / 'user_config.yaml', base_dir / 'config.yaml']:
        if path.exists():
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
    return {}


def cmd_current(args, config):
    """Fetch and display the current Fear & Greed Index."""
    print("\nFetching CNN Fear & Greed Index...")

    client = FearGreedClient.from_config(config)
    data = client.fetch_current()

    if not data:
        print("ERROR: Could not fetch Fear & Greed data.")
        print("The CNN API may be temporarily unavailable.")
        return 1

    # Display current score
    print(f"\n{'='*50}")
    print(f"  CNN Fear & Greed Index")
    print(f"{'='*50}")
    print(f"  Score:    {data.score:.0f} / 100")
    print(f"  Rating:   {data.rating}")
    print(f"  Updated:  {data.timestamp.strftime('%Y-%m-%d %H:%M') if data.timestamp else 'N/A'}")

    if data.previous_close > 0:
        delta = data.score - data.previous_close
        print(f"\n  Previous Close: {data.previous_close:.0f} ({delta:+.0f})")
    if data.one_week_ago > 0:
        print(f"  1 Week Ago:     {data.one_week_ago:.0f}")
    if data.one_month_ago > 0:
        print(f"  1 Month Ago:    {data.one_month_ago:.0f}")
    if data.one_year_ago > 0:
        print(f"  1 Year Ago:     {data.one_year_ago:.0f}")

    # Visual gauge
    print(f"\n  {'='*40}")
    gauge_pos = int(data.score / 100 * 38)
    gauge = '.' * 38
    gauge = gauge[:gauge_pos] + '#' + gauge[gauge_pos+1:]
    print(f"  [{gauge}]")
    print(f"  Extreme Fear              Extreme Greed")
    print(f"  {'='*40}\n")

    # Historical data
    if args.verbose:
        print("Fetching historical data...")
        history = client.fetch_historical(days=30)
        if history:
            print(f"\n  Recent History (last 10 days):")
            print(f"  {'Date':<12} {'Score':>6}  Rating")
            print(f"  {'-'*40}")
            for point in history[:10]:
                rating = classify_score(point.score)
                print(f"  {point.date.strftime('%Y-%m-%d'):<12} {point.score:>6.0f}  {rating}")

    return 0


def cmd_history(args, config):
    """Show stored Fear & Greed history from the database."""
    db_path = config.get('database', {}).get('path', 'canslim_positions.db')

    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if the column exists
    cursor.execute("PRAGMA table_info(market_regime_alerts)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'fear_greed_score' not in columns:
        print("ERROR: fear_greed_score column not found. Run migration first:")
        print("  python -m migrations.add_fear_greed_columns --db <path>")
        conn.close()
        return 1

    days = args.days or 30
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    cursor.execute("""
        SELECT date, fear_greed_score, fear_greed_rating,
               composite_score, regime
        FROM market_regime_alerts
        WHERE date >= ? AND fear_greed_score IS NOT NULL
        ORDER BY date DESC
    """, (cutoff,))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"\nNo Fear & Greed data found in the last {days} days.")
        print("Run the regime analysis to start collecting F&G data.")
        return 0

    print(f"\n{'='*70}")
    print(f"  Fear & Greed History (last {days} days)")
    print(f"{'='*70}")
    print(f"  {'Date':<12} {'F&G':>5} {'Rating':<15} {'Regime':>8} {'Score':>7}")
    print(f"  {'-'*60}")

    for row in rows:
        dt, fg_score, fg_rating, comp_score, regime = row
        fg_str = f"{fg_score:.0f}" if fg_score else "--"
        rating_str = fg_rating or "--"
        comp_str = f"{comp_score:+.2f}" if comp_score else "--"
        regime_str = regime or "--"
        print(f"  {dt:<12} {fg_str:>5} {rating_str:<15} {regime_str:>8} {comp_str:>7}")

    print(f"\n  Total records: {len(rows)}")
    print(f"{'='*70}\n")

    return 0


def cmd_seed(args, config):
    """Backfill Fear & Greed historical data into existing regime alerts."""
    db_path = config.get('database', {}).get('path', 'canslim_positions.db')

    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        return 1

    days = args.days or 90

    print(f"\nSeeding Fear & Greed data for last {days} days...")
    print("Fetching historical data from CNN...")

    client = FearGreedClient.from_config(config)
    history = client.fetch_historical(days=days)

    if not history:
        print("ERROR: Could not fetch historical F&G data.")
        return 1

    print(f"  Got {len(history)} historical data points")

    # Build date -> score mapping
    fg_by_date = {}
    for point in history:
        date_str = point.date.strftime('%Y-%m-%d')
        fg_by_date[date_str] = point.score

    # Update database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check column exists
    cursor.execute("PRAGMA table_info(market_regime_alerts)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'fear_greed_score' not in columns:
        print("ERROR: fear_greed_score column not found. Run migration first.")
        conn.close()
        return 1

    # Get existing alerts without F&G data
    cursor.execute("""
        SELECT date FROM market_regime_alerts
        WHERE fear_greed_score IS NULL
        ORDER BY date
    """)
    missing_dates = [row[0] for row in cursor.fetchall()]

    updated = 0
    for dt in missing_dates:
        if dt in fg_by_date:
            score = fg_by_date[dt]
            rating = classify_score(score)
            cursor.execute("""
                UPDATE market_regime_alerts
                SET fear_greed_score = ?, fear_greed_rating = ?
                WHERE date = ?
            """, (score, rating, dt))
            updated += 1

    conn.commit()
    conn.close()

    print(f"\n  Updated {updated} records out of {len(missing_dates)} missing")
    print(f"  Historical data points available: {len(fg_by_date)}")

    if updated > 0:
        print(f"\nSEED COMPLETE: {updated} records backfilled.")
    else:
        print("\nNo records needed updating.")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="CNN Fear & Greed Index CLI Tool"
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Enable verbose output'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # current command
    current_parser = subparsers.add_parser('current', help='Fetch and display current F&G score')

    # history command
    history_parser = subparsers.add_parser('history', help='Show stored F&G history from DB')
    history_parser.add_argument(
        '--days', type=int, default=30,
        help='Number of days to show (default: 30)'
    )

    # seed command
    seed_parser = subparsers.add_parser('seed', help='Backfill historical F&G data into DB')
    seed_parser.add_argument(
        '--days', type=int, default=90,
        help='Number of days to seed (default: 90)'
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
