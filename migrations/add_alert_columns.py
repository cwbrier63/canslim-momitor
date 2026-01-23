"""
Migration: Add all missing columns to alerts table

Adds columns that may be missing from older databases.

Run: python -m canslim_monitor.migrations.add_alert_columns
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str = None):
    """Add missing columns to alerts table."""
    
    if db_path is None:
        db_path = Path(__file__).parent.parent / "canslim_monitor.db"
    
    db_path = Path(db_path)
    
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return False
    
    print(f"Migrating database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check existing columns
        cursor.execute("PRAGMA table_info(alerts)")
        existing_columns = {col[1] for col in cursor.fetchall()}
        
        print(f"Existing columns: {len(existing_columns)}")
        
        # Comprehensive list of all Alert columns
        columns_to_add = [
            # Core message fields
            ('message', 'TEXT'),
            ('action', 'VARCHAR(100)'),
            
            # Acknowledgment
            ('acknowledged', 'BOOLEAN DEFAULT 0'),
            ('acknowledged_at', 'DATETIME'),
            
            # Position state at alert time
            ('state_at_alert', 'INTEGER'),
            ('pivot_at_alert', 'FLOAT'),
            ('avg_cost_at_alert', 'FLOAT'),
            ('pnl_pct_at_alert', 'FLOAT'),
            
            # Technical indicators
            ('ma50', 'FLOAT'),
            ('ma21', 'FLOAT'),
            ('ma200', 'FLOAT'),
            ('volume_ratio', 'FLOAT'),
            
            # Health tracking
            ('health_score', 'INTEGER'),
            ('health_rating', 'VARCHAR(10)'),
            
            # Market context
            ('market_regime', 'VARCHAR(30)'),
            ('spy_price', 'FLOAT'),
            
            # CANSLIM scoring
            ('canslim_grade', 'VARCHAR(5)'),
            ('canslim_score', 'INTEGER'),
            ('static_score', 'INTEGER'),
            ('dynamic_score', 'INTEGER'),
            ('score_details', 'TEXT'),
            
            # Execution info
            ('exec_verdict', 'VARCHAR(20)'),
            ('adv', 'INTEGER'),
            ('spread_pct', 'FLOAT'),
            ('est_slippage', 'FLOAT'),
            
            # Discord tracking
            ('discord_channel', 'VARCHAR(50)'),
            ('discord_sent', 'BOOLEAN DEFAULT 0'),
            ('discord_message_id', 'VARCHAR(50)'),
            ('discord_sent_at', 'DATETIME'),
            
            # User action tracking
            ('user_action', 'VARCHAR(20)'),
            ('user_action_time', 'DATETIME'),
            
            # Timestamps
            ('created_at', 'DATETIME'),
        ]
        
        changes = []
        
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE alerts ADD COLUMN {col_name} {col_type}")
                    changes.append(col_name)
                    print(f"  Added column: {col_name}")
                except sqlite3.OperationalError as e:
                    print(f"  Error adding {col_name}: {e}")
            else:
                print(f"  Column exists: {col_name}")
        
        conn.commit()
        
        if changes:
            print(f"\n✅ Migration complete. Added {len(changes)} column(s).")
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
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = migrate(db_path)
    sys.exit(0 if success else 1)
