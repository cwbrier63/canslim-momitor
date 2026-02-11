"""
Migration: Backfill e1_date, e2_date, e3_date for existing positions.

For positions that have entry shares/price but no entry date:
- e1_date: Use entry_date or breakout_date
- e2_date: Use entry_date (approximate, since exact E2 date wasn't tracked)
- e3_date: Use entry_date (approximate)

Run: python migrations/backfill_entry_dates.py
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
    """Backfill entry dates for existing positions."""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Running migration on: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Backfill e1_date from entry_date or breakout_date
    cursor.execute("""
        SELECT COUNT(*) FROM positions
        WHERE e1_shares IS NOT NULL AND e1_shares > 0
        AND e1_date IS NULL
    """)
    e1_count = cursor.fetchone()[0]
    print(f"Positions needing e1_date backfill: {e1_count}")

    if e1_count > 0:
        cursor.execute("""
            UPDATE positions
            SET e1_date = COALESCE(entry_date, breakout_date)
            WHERE e1_shares IS NOT NULL AND e1_shares > 0
            AND e1_date IS NULL
            AND (entry_date IS NOT NULL OR breakout_date IS NOT NULL)
        """)
        print(f"  Updated {cursor.rowcount} rows with e1_date")

    # Backfill e2_date from entry_date (best approximation available)
    cursor.execute("""
        SELECT COUNT(*) FROM positions
        WHERE e2_shares IS NOT NULL AND e2_shares > 0
        AND e2_date IS NULL
    """)
    e2_count = cursor.fetchone()[0]
    print(f"Positions needing e2_date backfill: {e2_count}")

    if e2_count > 0:
        cursor.execute("""
            UPDATE positions
            SET e2_date = COALESCE(entry_date, breakout_date)
            WHERE e2_shares IS NOT NULL AND e2_shares > 0
            AND e2_date IS NULL
            AND (entry_date IS NOT NULL OR breakout_date IS NOT NULL)
        """)
        print(f"  Updated {cursor.rowcount} rows with e2_date")

    # Backfill e3_date from entry_date (best approximation available)
    cursor.execute("""
        SELECT COUNT(*) FROM positions
        WHERE e3_shares IS NOT NULL AND e3_shares > 0
        AND e3_date IS NULL
    """)
    e3_count = cursor.fetchone()[0]
    print(f"Positions needing e3_date backfill: {e3_count}")

    if e3_count > 0:
        cursor.execute("""
            UPDATE positions
            SET e3_date = COALESCE(entry_date, breakout_date)
            WHERE e3_shares IS NOT NULL AND e3_shares > 0
            AND e3_date IS NULL
            AND (entry_date IS NOT NULL OR breakout_date IS NOT NULL)
        """)
        print(f"  Updated {cursor.rowcount} rows with e3_date")

    conn.commit()

    # Summary
    cursor.execute("""
        SELECT symbol, e1_date, e2_date, e3_date
        FROM positions
        WHERE e1_shares IS NOT NULL AND e1_shares > 0
        ORDER BY entry_date DESC
        LIMIT 10
    """)
    rows = cursor.fetchall()
    print(f"\nSample positions after backfill:")
    for symbol, e1, e2, e3 in rows:
        print(f"  {symbol}: e1={e1}, e2={e2}, e3={e3}")

    conn.close()
    print("\nDone!")


if __name__ == '__main__':
    run_migration()
