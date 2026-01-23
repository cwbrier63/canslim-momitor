"""
Migration: Add acknowledged columns to alerts table

Run this once to add the acknowledged and acknowledged_at columns
to existing databases.

Usage:
    python -m canslim_monitor.migrations.add_alert_acknowledged <db_path>
"""

import sys
import sqlite3
from pathlib import Path


def migrate(db_path: str):
    """Add acknowledged columns to alerts table."""
    print(f"Migrating database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(alerts)")
        columns = {row[1] for row in cursor.fetchall()}
        
        if 'acknowledged' not in columns:
            print("  Adding 'acknowledged' column...")
            cursor.execute("""
                ALTER TABLE alerts 
                ADD COLUMN acknowledged BOOLEAN DEFAULT FALSE
            """)
            print("  ✓ Added 'acknowledged' column")
        else:
            print("  'acknowledged' column already exists")
        
        if 'acknowledged_at' not in columns:
            print("  Adding 'acknowledged_at' column...")
            cursor.execute("""
                ALTER TABLE alerts 
                ADD COLUMN acknowledged_at DATETIME
            """)
            print("  ✓ Added 'acknowledged_at' column")
        else:
            print("  'acknowledged_at' column already exists")
        
        # Create index for unacknowledged alerts
        print("  Creating index for unacknowledged alerts...")
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_unacknowledged 
                ON alerts(acknowledged, position_id)
            """)
            print("  ✓ Created index")
        except sqlite3.OperationalError as e:
            if "already exists" in str(e):
                print("  Index already exists")
            else:
                raise
        
        conn.commit()
        print("\n✓ Migration complete!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        raise
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2:
        # Default path
        default_path = r"C:\Trading\canslim_monitor\data\canslim_monitor.db"
        if Path(default_path).exists():
            db_path = default_path
        else:
            print("Usage: python -m canslim_monitor.migrations.add_alert_acknowledged <db_path>")
            sys.exit(1)
    else:
        db_path = sys.argv[1]
    
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)
    
    migrate(db_path)


if __name__ == "__main__":
    main()
