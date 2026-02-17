"""
CANSLIM Monitor - Database Migration
Add Company Info Fields + Backfill from Polygon API

Run: python -m migrations.add_company_info [database_path]
Default: canslim_monitor.db

Changes:
- Adds company_name, industry, sector columns to positions table
- Backfills existing positions via Polygon /v3/reference/tickers/{symbol}
"""

import sqlite3
import time
import sys
import os
from datetime import datetime


def column_exists(cursor, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def add_column_if_not_exists(cursor, table: str, column: str, col_type: str) -> str:
    """Add column if it doesn't exist. Returns status message."""
    if column_exists(cursor, table, column):
        return f"  Already exists: {table}.{column}"
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    return f"  Added: {table}.{column}"


def backfill_from_polygon(cursor, api_key: str, base_url: str):
    """Backfill company_name, industry, sector for all positions missing data."""
    cursor.execute(
        "SELECT id, symbol FROM positions WHERE company_name IS NULL"
    )
    rows = cursor.fetchall()
    if not rows:
        print("  No positions need backfilling")
        return 0

    print(f"  Found {len(rows)} positions to backfill")

    # Import PolygonClient
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from integrations.polygon_client import PolygonClient
        client = PolygonClient(api_key=api_key, base_url=base_url)
    except Exception as e:
        print(f"  Could not create PolygonClient: {e}")
        return 0

    updated = 0
    for pos_id, symbol in rows:
        try:
            details = client.get_ticker_details(symbol)
            if details:
                cursor.execute(
                    "UPDATE positions SET company_name=?, industry=?, sector=? WHERE id=?",
                    (details.get('name'), details.get('industry'), details.get('sector'), pos_id)
                )
                print(f"    {symbol}: {details.get('name', '?')} | {details.get('industry', '?')} | {details.get('sector', '?')}")
                updated += 1
            else:
                print(f"    {symbol}: No data returned")

            # Rate limit: Polygon Starter = 5 calls/min
            time.sleep(0.5)

        except Exception as e:
            print(f"    {symbol}: Error - {e}")

    return updated


def migrate(db_path: str):
    """Add company info columns and backfill from Polygon."""
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return False

    print("=" * 60)
    print("CANSLIM Monitor - Add Company Info Migration")
    print(f"Database: {db_path}")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Step 1: Add columns
    print("\nStep 1: Add columns to positions table")
    print("-" * 40)
    columns = [
        ("company_name", "TEXT"),
        ("industry", "TEXT"),
        ("sector", "TEXT"),
    ]
    for col_name, col_type in columns:
        status = add_column_if_not_exists(cursor, "positions", col_name, col_type)
        print(status)

    conn.commit()

    # Step 2: Backfill from Polygon API
    print("\nStep 2: Backfill from Polygon API")
    print("-" * 40)

    # Load API key from config
    api_key = None
    base_url = 'https://api.polygon.io'
    try:
        import yaml
        config_paths = ['user_config.yaml', 'config.yaml']
        for cp in config_paths:
            full_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), cp)
            if os.path.exists(full_path):
                with open(full_path, 'r') as f:
                    cfg = yaml.safe_load(f) or {}
                md = cfg.get('market_data', {})
                pg = cfg.get('polygon', {})
                api_key = md.get('api_key') or pg.get('api_key') or api_key
                base_url = md.get('base_url') or pg.get('base_url') or base_url
                if api_key:
                    break
    except Exception as e:
        print(f"  Config load error: {e}")

    if not api_key:
        print("  No API key found in config - skipping backfill")
        print("  Run again after configuring market_data.api_key in user_config.yaml")
    else:
        print(f"  API key: {api_key[:8]}...")
        updated = backfill_from_polygon(cursor, api_key, base_url)
        conn.commit()
        print(f"\n  Backfilled {updated} positions")

    conn.close()

    print("\n" + "=" * 60)
    print("Migration complete!")
    print("=" * 60)
    return True


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'canslim_monitor.db'
    migrate(db_path)
