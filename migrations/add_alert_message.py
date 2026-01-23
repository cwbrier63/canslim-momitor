"""
Migration: Add message and action columns to alerts table

Adds columns to store the full alert message and recommended action
for historical analysis and ML training.

Run: python -m canslim_monitor.migrations.add_alert_message
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str = None):
    """Add message and action columns to alerts table."""
    
    if db_path is None:
        # Default path
        db_path = Path(__file__).parent.parent / "canslim_monitor.db"
    
    db_path = Path(db_path)
    
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return False
    
    print(f"Migrating database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(alerts)")
        columns = {col[1] for col in cursor.fetchall()}
        
        changes = []
        
        # Add message column
        if 'message' not in columns:
            cursor.execute("""
                ALTER TABLE alerts 
                ADD COLUMN message TEXT
            """)
            changes.append("message (TEXT)")
            print("  Added column: message")
        else:
            print("  Column exists: message")
        
        # Add action column
        if 'action' not in columns:
            cursor.execute("""
                ALTER TABLE alerts 
                ADD COLUMN action VARCHAR(100)
            """)
            changes.append("action (VARCHAR(100))")
            print("  Added column: action")
        else:
            print("  Column exists: action")
        
        conn.commit()
        
        if changes:
            print(f"\n✅ Migration complete. Added {len(changes)} column(s):")
            for c in changes:
                print(f"   - {c}")
        else:
            print("\n✅ No changes needed - all columns already exist.")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


if __name__ == "__main__":
    # Allow passing db path as argument
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = migrate(db_path)
    sys.exit(0 if success else 1)
