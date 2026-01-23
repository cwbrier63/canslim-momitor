"""
Migration: Add realized_pnl column to positions table

Run this script to add the realized_pnl column if it doesn't exist.

Usage:
    python migration_add_realized_pnl.py --db "C:/Trading/canslim_monitor/canslim_positions.db"
"""

import argparse
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path


def check_column_exists(cursor, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def add_realized_pnl_column(db_path: str, backup: bool = True):
    """Add realized_pnl column to positions table."""
    
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        return False
    
    # Create backup
    if backup:
        backup_path = db_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        print(f"Creating backup: {backup_path}")
        shutil.copy(db_path, backup_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        if check_column_exists(cursor, 'positions', 'realized_pnl'):
            print("Column 'realized_pnl' already exists. No changes needed.")
            return True
        
        # Add the column
        print("Adding 'realized_pnl' column to positions table...")
        cursor.execute("""
            ALTER TABLE positions 
            ADD COLUMN realized_pnl REAL DEFAULT NULL
        """)
        
        conn.commit()
        print("SUCCESS: Column 'realized_pnl' added successfully.")
        
        # Verify
        if check_column_exists(cursor, 'positions', 'realized_pnl'):
            print("VERIFIED: Column exists in table.")
            return True
        else:
            print("ERROR: Column verification failed.")
            return False
        
    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Add realized_pnl column to positions table")
    parser.add_argument('--db', required=True, help="Path to SQLite database")
    parser.add_argument('--no-backup', action='store_true', help="Skip backup creation")
    
    args = parser.parse_args()
    
    success = add_realized_pnl_column(args.db, backup=not args.no_backup)
    
    if success:
        print("\n" + "="*60)
        print("NEXT STEPS:")
        print("="*60)
        print("""
1. Update your Position model (models.py) to include:
   
   realized_pnl = Column(Float, nullable=True, default=None)

2. The GUI table will now show:
   - 'Dist %' - Distance from pivot (computed: ((last_price - pivot) / pivot) * 100)
   - 'Unreal %' - Unrealized P&L % (current_pnl_pct from database)
   - 'Realized $' - Realized P&L in dollars (from realized_pnl column)

3. To record realized P&L when closing a position:
   - Calculate: (exit_price - avg_cost) * shares_sold
   - Store in position.realized_pnl
""")
    
    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
