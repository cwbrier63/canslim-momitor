"""
CANSLIM Monitor - Database Migration
Add MarketSurge Beta Interface Fields

Run: python add_marketsurge_v2_fields.py [database_path]
Default: canslim_monitor.db

Changes:
- Adds industry_rank (replaces group_rank)
- Adds RS trend fields (rs_3mo, rs_6mo)
- Adds institutional tracking (funds_qtr_chg, ibd_fund_count)
- Adds breakout quality metrics (breakout_vol_pct, breakout_price_pct)
- Adds market context fields
- Migrates existing group_rank data to industry_rank
"""

import sqlite3
from datetime import datetime
import sys
import os


def column_exists(cursor, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def add_column_if_not_exists(cursor, table: str, column: str, col_type: str) -> str:
    """Add column if it doesn't exist. Returns status message."""
    if column_exists(cursor, table, column):
        return f"⏭️  {table}.{column} already exists"
    
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    return f"✅ Added {table}.{column}"


def migrate(db_path: str):
    """Add new columns for MarketSurge v2 data capture."""
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    print(f"="*60)
    print(f"CANSLIM Monitor - MarketSurge v2 Migration")
    print(f"Database: {db_path}")
    print(f"Started: {datetime.now().isoformat()}")
    print(f"="*60)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # =========================================================================
    # POSITION TABLE
    # =========================================================================
    print("\n📊 POSITIONS TABLE")
    print("-"*40)
    
    position_columns = [
        # Industry & Sector Data
        ("industry_rank", "INTEGER"),           # 1-197, replaces group_rank
        ("industry_stock_count", "INTEGER"),    # Stocks in industry group
        ("industry_eps_rank", "TEXT"),          # "3 of 38" format
        ("industry_rs_rank", "TEXT"),           # "10 of 38" format
        
        # RS Trend Data
        ("rs_3mo", "INTEGER"),                  # 3-month RS rating
        ("rs_6mo", "INTEGER"),                  # 6-month RS rating
        
        # Additional Ratings
        ("smr_rating", "TEXT"),                 # Sales/Margin/ROE: A-E
        
        # Institutional Data (enhanced)
        ("funds_qtr_chg", "INTEGER"),           # Change vs prior quarter
        ("ibd_fund_count", "INTEGER"),          # IBD Mutual Fund Index holdings
        
        # Breakout Quality
        ("breakout_vol_pct", "REAL"),           # Volume % on breakout
        ("breakout_price_pct", "REAL"),         # Price % on breakout
        
        # Market Context at Entry
        ("entry_market_exposure", "TEXT"),      # IBD exposure level
        ("entry_dist_days", "INTEGER"),         # Distribution day count
    ]
    
    for col_name, col_type in position_columns:
        status = add_column_if_not_exists(cursor, "positions", col_name, col_type)
        print(status)
    
    # =========================================================================
    # ALERT TABLE
    # =========================================================================
    print("\n🔔 ALERTS TABLE")
    print("-"*40)
    
    alert_columns = [
        # Industry context at alert time
        ("industry_rank_at_alert", "INTEGER"),
        ("rs_3mo_at_alert", "INTEGER"),
        ("rs_6mo_at_alert", "INTEGER"),
        
        # Institutional context at alert time
        ("fund_count_at_alert", "INTEGER"),
        ("funds_qtr_chg_at_alert", "INTEGER"),
        
        # Breakout quality metrics
        ("breakout_vol_pct", "REAL"),
        ("breakout_price_pct", "REAL"),
        
        # Market context at alert time
        ("market_exposure_at_alert", "TEXT"),
        ("dist_days_at_alert", "INTEGER"),
    ]
    
    for col_name, col_type in alert_columns:
        status = add_column_if_not_exists(cursor, "alerts", col_name, col_type)
        print(status)
    
    # =========================================================================
    # OUTCOMES TABLE
    # =========================================================================
    print("\n📈 OUTCOMES TABLE")
    print("-"*40)
    
    outcome_columns = [
        # Industry context at entry
        ("industry_rank_at_entry", "INTEGER"),
        ("rs_3mo_at_entry", "INTEGER"),
        ("rs_6mo_at_entry", "INTEGER"),
        
        # Institutional context at entry
        ("fund_count_at_entry", "INTEGER"),
        ("funds_qtr_chg_at_entry", "INTEGER"),
        ("ibd_fund_count_at_entry", "INTEGER"),
        
        # Breakout quality
        ("breakout_vol_pct", "REAL"),
        ("breakout_price_pct", "REAL"),
        
        # Market context at entry
        ("market_exposure_at_entry", "TEXT"),
        ("dist_days_at_entry", "INTEGER"),
    ]
    
    for col_name, col_type in outcome_columns:
        status = add_column_if_not_exists(cursor, "outcomes", col_name, col_type)
        print(status)
    
    # =========================================================================
    # DATA MIGRATION: group_rank -> industry_rank
    # =========================================================================
    print("\n🔄 DATA MIGRATION")
    print("-"*40)
    
    if column_exists(cursor, "positions", "group_rank"):
        cursor.execute("""
            UPDATE positions 
            SET industry_rank = group_rank 
            WHERE group_rank IS NOT NULL 
              AND group_rank > 0
              AND (industry_rank IS NULL OR industry_rank = 0)
        """)
        migrated = cursor.rowcount
        if migrated > 0:
            print(f"✅ Migrated {migrated} group_rank values to industry_rank")
        else:
            print("⏭️  No group_rank data to migrate")
    else:
        print("⏭️  No group_rank column found (OK for new databases)")
    
    # =========================================================================
    # COMMIT AND CLOSE
    # =========================================================================
    conn.commit()
    conn.close()
    
    print("\n" + "="*60)
    print(f"✅ Migration completed successfully!")
    print(f"   Finished: {datetime.now().isoformat()}")
    print("="*60)
    
    return True


def show_schema(db_path: str, table: str):
    """Display current table schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    
    print(f"\n{table} schema:")
    print("-"*50)
    for row in cursor.fetchall():
        cid, name, dtype, notnull, default, pk = row
        print(f"  {name:<30} {dtype}")
    
    conn.close()


if __name__ == "__main__":
    # Get database path from command line or use default
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # Try common locations
        candidates = [
            "canslim_monitor.db",
            "canslim_monitor/canslim_monitor.db",
            "../canslim_monitor.db",
        ]
        db_path = None
        for candidate in candidates:
            if os.path.exists(candidate):
                db_path = candidate
                break
        
        if not db_path:
            print("Usage: python add_marketsurge_v2_fields.py [database_path]")
            print("\nNo database found in common locations:")
            for c in candidates:
                print(f"  - {c}")
            sys.exit(1)
    
    # Run migration
    success = migrate(db_path)
    
    if success and "--show-schema" in sys.argv:
        show_schema(db_path, "positions")
        show_schema(db_path, "alerts")
        show_schema(db_path, "outcomes")
    
    sys.exit(0 if success else 1)
