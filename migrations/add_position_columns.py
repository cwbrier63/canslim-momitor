"""
Migration: Add missing columns to positions table

Adds columns that may be missing from older databases:
- pivot_set_date
- canslim_grade (renamed from entry_grade)
- ma_50, ma_21, ma_200, ma_10_week

Run: python -m canslim_monitor.migrations.add_position_columns
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str = None):
    """Add missing columns to positions table."""
    
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
        cursor.execute("PRAGMA table_info(positions)")
        existing_columns = {col[1] for col in cursor.fetchall()}
        
        print(f"Existing columns: {len(existing_columns)}")
        
        # Columns to add with their types - comprehensive list
        columns_to_add = [
            # Pivot tracking
            ('pivot_set_date', 'DATE'),
            ('pivot_distance_pct', 'FLOAT'),
            ('pivot_status', 'VARCHAR(15)'),
            
            # CANSLIM scoring
            ('canslim_grade', 'VARCHAR(5)'),
            
            # Moving averages
            ('ma_50', 'FLOAT'),
            ('ma_21', 'FLOAT'),
            ('ma_200', 'FLOAT'),
            ('ma_10_week', 'FLOAT'),
            
            # Entry tracking (in case missing)
            ('e1_shares', 'INTEGER DEFAULT 0'),
            ('e1_price', 'FLOAT'),
            ('e1_date', 'DATE'),
            ('e2_shares', 'INTEGER DEFAULT 0'),
            ('e2_price', 'FLOAT'),
            ('e2_date', 'DATE'),
            ('e3_shares', 'INTEGER DEFAULT 0'),
            ('e3_price', 'FLOAT'),
            ('e3_date', 'DATE'),
            
            # Take profit tracking
            ('tp1_sold', 'INTEGER DEFAULT 0'),
            ('tp1_price', 'FLOAT'),
            ('tp1_date', 'DATE'),
            ('tp2_sold', 'INTEGER DEFAULT 0'),
            ('tp2_price', 'FLOAT'),
            ('tp2_date', 'DATE'),
            
            # Pyramid tracking
            ('py1_done', 'BOOLEAN DEFAULT 0'),
            ('py2_done', 'BOOLEAN DEFAULT 0'),
            
            # Volume tracking
            ('avg_volume_50d', 'INTEGER'),
            ('volume_updated_at', 'DATETIME'),
            
            # Health tracking
            ('health_score', 'INTEGER'),
            ('health_rating', 'VARCHAR(10)'),
            
            # Sheet sync
            ('sheet_row_id', 'VARCHAR(50)'),
            ('last_sheet_sync', 'DATETIME'),
            ('needs_sheet_sync', 'BOOLEAN DEFAULT 1'),
        ]
        
        changes = []
        
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}")
                    changes.append(f"{col_name} ({col_type})")
                    print(f"  Added column: {col_name}")
                except sqlite3.OperationalError as e:
                    print(f"  Error adding {col_name}: {e}")
            else:
                print(f"  Column exists: {col_name}")
        
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
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = migrate(db_path)
    sys.exit(0 if success else 1)
