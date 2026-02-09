"""
CLI tool to import backtest data.

Usage:
    python -m canslim_monitor.cli.import_backtest
    python -m canslim_monitor.cli.import_backtest --backtest-db C:/Trading/backtest_training.db
    python -m canslim_monitor.cli.import_backtest --overwrite
    python -m canslim_monitor.cli.import_backtest --dry-run
"""

import argparse
import sys
from pathlib import Path

# Add parent to path if running directly
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from canslim_monitor.data.database import init_database
from canslim_monitor.core.learning.backtest_importer import BacktestImporter, get_backtest_summary


def main():
    parser = argparse.ArgumentParser(description='Import backtest data into CANSLIM outcomes')
    parser.add_argument(
        '--main-db',
        default='C:/Trading/canslim_monitor/canslim_positions.db',
        help='Path to main CANSLIM database'
    )
    parser.add_argument(
        '--backtest-db',
        default='C:/Trading/backtest_training.db',
        help='Path to backtest training database'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Delete existing SwingTrader outcomes before importing'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be imported without writing'
    )

    args = parser.parse_args()

    # Validate paths
    if not Path(args.main_db).exists():
        print(f"ERROR: Main database not found: {args.main_db}")
        sys.exit(1)
    if not Path(args.backtest_db).exists():
        print(f"ERROR: Backtest database not found: {args.backtest_db}")
        print("The backtest_training.db is created by running the Polygon factor calculator.")
        sys.exit(1)

    print(f"Main DB: {args.main_db}")
    print(f"Backtest DB: {args.backtest_db}")
    print(f"Overwrite: {args.overwrite}")
    print()

    if args.dry_run:
        # Just show counts from backtest DB
        print("DRY RUN - Showing backtest database summary:")
        print()

        summary = get_backtest_summary(args.backtest_db)

        if 'error' in summary:
            print(f"ERROR: {summary['error']}")
            return

        print(f"Total trades in backtest DB: {summary.get('total_trades', 0)}")
        print(f"Trades with outcomes: {summary.get('trades_with_outcomes', 0)}")
        print(f"Average return: {summary.get('avg_return_pct', 0):.2f}%")
        print(f"Date range: {summary.get('date_range', {}).get('start')} to {summary.get('date_range', {}).get('end')}")
        print()
        print("Outcome distribution:")
        for outcome, count in summary.get('outcome_distribution', {}).items():
            print(f"  {outcome}: {count}")

        return

    # Run import
    db = init_database(args.main_db)
    importer = BacktestImporter(db, args.backtest_db)

    print("Starting import...")
    stats = importer.import_all(overwrite=args.overwrite)
    print()
    print(importer.get_summary_report())


if __name__ == '__main__':
    main()
