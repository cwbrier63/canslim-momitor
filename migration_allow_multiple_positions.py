#!/usr/bin/env python3
"""
Migration: Allow Multiple Positions per Symbol

Problem: UNIQUE(symbol, portfolio) prevents re-trading the same stock after closing a position.
Solution: Remove the constraint. The primary key (id) is sufficient for uniqueness.

Optional: Add UNIQUE(symbol, portfolio, watch_date) to prevent accidental duplicates on same day.

Run this migration AFTER backing up your database!
"""

import sqlite3
import shutil
from datetime import datetime
from pathlib import Path


def backup_database(db_path: str) -> str:
    """Create timestamped backup before migration."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"
    shutil.copy2(db_path, backup_path)
    print(f"✓ Backup created: {backup_path}")
    return backup_path


def check_current_constraints(conn: sqlite3.Connection) -> None:
    """Show current table structure."""
    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE name='positions' AND type='table'")
    result = cursor.fetchone()
    if result:
        print("\nCurrent positions table schema:")
        print("-" * 60)
        print(result[0])
        print("-" * 60)


def migrate_positions_table(conn: sqlite3.Connection, add_watch_date_constraint: bool = True) -> None:
    """
    Rebuild positions table without UNIQUE(symbol, portfolio).
    
    SQLite doesn't support DROP CONSTRAINT, so we need to:
    1. Create new table without the constraint
    2. Copy data
    3. Drop old table
    4. Rename new table
    5. Recreate indexes
    """
    
    print("\n📋 Starting migration...")
    
    # Get existing column info
    cursor = conn.execute("PRAGMA table_info(positions)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    print(f"✓ Found {len(column_names)} columns in positions table")
    
    # Build column list for the new table (preserving all columns)
    columns_sql = ", ".join(column_names)
    
    # Define the new constraint - either with watch_date or none
    if add_watch_date_constraint:
        new_constraint = "UNIQUE(symbol, portfolio, watch_date)"
        print(f"✓ New constraint: {new_constraint}")
    else:
        new_constraint = None
        print("✓ No unique constraint on symbol/portfolio (relying on id only)")
    
    # Step 1: Get the current CREATE TABLE statement
    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE name='positions' AND type='table'")
    original_sql = cursor.fetchone()[0]
    
    # Step 2: Modify the SQL - replace UNIQUE(symbol, portfolio) with new constraint
    import re
    
    # Remove the old UNIQUE constraint
    # Pattern matches: UNIQUE(symbol, portfolio) with optional whitespace
    modified_sql = re.sub(
        r',?\s*UNIQUE\s*\(\s*symbol\s*,\s*portfolio\s*\)',
        '',
        original_sql,
        flags=re.IGNORECASE
    )
    
    # Clean up any trailing comma before closing paren
    modified_sql = re.sub(r',\s*\)', ')', modified_sql)
    
    # Add new constraint if specified
    if new_constraint:
        # Insert before the closing paren
        modified_sql = re.sub(
            r'\)$',
            f',\n    {new_constraint}\n)',
            modified_sql.strip()
        )
    
    # Change table name to positions_new
    modified_sql = modified_sql.replace('CREATE TABLE positions', 'CREATE TABLE positions_new', 1)
    
    print("\n📝 New table schema:")
    print("-" * 60)
    print(modified_sql)
    print("-" * 60)
    
    # Step 3: Execute the migration
    try:
        # Create new table
        conn.execute(modified_sql)
        print("✓ Created positions_new table")
        
        # Copy all data
        conn.execute(f"INSERT INTO positions_new SELECT {columns_sql} FROM positions")
        row_count = conn.execute("SELECT COUNT(*) FROM positions_new").fetchone()[0]
        print(f"✓ Copied {row_count} rows to new table")
        
        # Drop old table
        conn.execute("DROP TABLE positions")
        print("✓ Dropped old positions table")
        
        # Rename new table
        conn.execute("ALTER TABLE positions_new RENAME TO positions")
        print("✓ Renamed positions_new to positions")
        
        # Recreate indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_state ON positions(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_portfolio ON positions(portfolio)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_needs_sync ON positions(needs_sheet_sync)")
        print("✓ Recreated indexes")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise


def verify_migration(conn: sqlite3.Connection) -> None:
    """Verify the migration was successful."""
    print("\n🔍 Verifying migration...")
    
    # Check table structure
    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE name='positions' AND type='table'")
    result = cursor.fetchone()
    
    if 'UNIQUE(symbol, portfolio)' in result[0] and 'watch_date' not in result[0]:
        print("❌ Old constraint still present!")
        return False
    
    # Check row count
    count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    print(f"✓ positions table has {count} rows")
    
    # Check for any LLY records
    lly_records = conn.execute(
        "SELECT id, portfolio, state, watch_date FROM positions WHERE symbol='LLY'"
    ).fetchall()
    
    if lly_records:
        print(f"\n📊 Existing LLY records:")
        for rec in lly_records:
            print(f"   id={rec[0]}, portfolio={rec[1]}, state={rec[2]}, watch_date={rec[3]}")
    
    print("\n✅ Verification passed - you can now add new LLY positions!")
    return True


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Migration to allow multiple positions per symbol")
    parser.add_argument(
        "--db", 
        default="c:/trading/canslim_monitor/canslim_positions.db",
        help="Path to database file"
    )
    parser.add_argument(
        "--no-watch-date-constraint",
        action="store_true",
        help="Don't add UNIQUE(symbol, portfolio, watch_date) - rely only on id"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true", 
        help="Show what would happen without making changes"
    )
    
    args = parser.parse_args()
    
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1
    
    print(f"📂 Database: {db_path}")
    
    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - no changes will be made")
        conn = sqlite3.connect(str(db_path))
        check_current_constraints(conn)
        conn.close()
        return 0
    
    # Create backup
    backup_path = backup_database(str(db_path))
    
    # Connect and migrate
    conn = sqlite3.connect(str(db_path))
    
    try:
        check_current_constraints(conn)
        migrate_positions_table(conn, add_watch_date_constraint=not args.no_watch_date_constraint)
        verify_migration(conn)
    finally:
        conn.close()
    
    print(f"\n💾 If anything goes wrong, restore from: {backup_path}")
    return 0


if __name__ == "__main__":
    exit(main())
