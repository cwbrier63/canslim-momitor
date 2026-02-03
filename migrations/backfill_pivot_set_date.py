"""
Migration: Backfill pivot_set_date for existing positions.

For positions that have a pivot but no pivot_set_date:
- Use watch_date if available
- Otherwise use today's date

Run: python migrations/backfill_pivot_set_date.py
"""

import sqlite3
from pathlib import Path
from datetime import date
import sys


def get_db_path() -> Path:
    """Get database path from config or use default."""
    default_path = Path("c:/trading/canslim_monitor/canslim_positions.db")
    return default_path


def run_migration():
    """Backfill pivot_set_date for existing positions."""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Running migration on: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count positions needing update
    cursor.execute("""
        SELECT COUNT(*) FROM positions
        WHERE pivot IS NOT NULL AND pivot > 0
        AND pivot_set_date IS NULL
    """)
    count = cursor.fetchone()[0]
    print(f"  Found {count} positions with pivot but no pivot_set_date")

    if count == 0:
        print("  Nothing to update")
        conn.close()
        return

    # Update using watch_date where available
    cursor.execute("""
        UPDATE positions
        SET pivot_set_date = watch_date
        WHERE pivot IS NOT NULL AND pivot > 0
        AND pivot_set_date IS NULL
        AND watch_date IS NOT NULL
    """)
    updated_with_watch_date = cursor.rowcount
    print(f"  Updated {updated_with_watch_date} positions using watch_date")

    # Update remaining with today's date
    today = date.today().isoformat()
    cursor.execute(f"""
        UPDATE positions
        SET pivot_set_date = '{today}'
        WHERE pivot IS NOT NULL AND pivot > 0
        AND pivot_set_date IS NULL
    """)
    updated_with_today = cursor.rowcount
    print(f"  Updated {updated_with_today} positions using today's date ({today})")

    conn.commit()
    conn.close()

    print(f"\nMigration complete. Total updated: {updated_with_watch_date + updated_with_today}")


def verify_migration():
    """Verify the migration was successful."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count positions still needing update
    cursor.execute("""
        SELECT COUNT(*) FROM positions
        WHERE pivot IS NOT NULL AND pivot > 0
        AND pivot_set_date IS NULL
    """)
    remaining = cursor.fetchone()[0]

    # Count positions with pivot_set_date
    cursor.execute("""
        SELECT COUNT(*) FROM positions
        WHERE pivot_set_date IS NOT NULL
    """)
    with_date = cursor.fetchone()[0]

    conn.close()

    if remaining == 0:
        print(f"VERIFICATION PASSED - All positions with pivot now have pivot_set_date ({with_date} total)")
        return True
    else:
        print(f"VERIFICATION FAILED - {remaining} positions still missing pivot_set_date")
        return False


def show_sample():
    """Show sample of updated positions."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT symbol, pivot, pivot_set_date, watch_date, state
        FROM positions
        WHERE pivot_set_date IS NOT NULL
        ORDER BY pivot_set_date DESC
        LIMIT 10
    """)
    rows = cursor.fetchall()

    print("\nSample positions with pivot_set_date:")
    print("-" * 70)
    print(f"{'Symbol':<10} {'Pivot':>10} {'Pivot Set':>12} {'Watch Date':>12} {'State':>6}")
    print("-" * 70)
    for row in rows:
        symbol, pivot, pivot_set_date, watch_date, state = row
        print(f"{symbol:<10} ${pivot:>9.2f} {pivot_set_date or 'NULL':>12} {watch_date or 'NULL':>12} {state:>6}")

    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("CANSLIM Monitor - Backfill pivot_set_date Migration")
    print("=" * 60)

    run_migration()
    print()
    verify_migration()
    show_sample()
