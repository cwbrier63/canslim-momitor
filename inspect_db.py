"""
Inspect SQLite database schema.

Usage:
    python inspect_db.py
    python inspect_db.py --database C:/Trading/canslim_positions.db
"""

import sys
import argparse
import sqlite3
from pathlib import Path


def inspect_database(db_path: str):
    """List all tables and their columns."""
    
    print("=" * 70)
    print("DATABASE INSPECTION")
    print("=" * 70)
    print(f"Database: {db_path}")
    
    # Check if file exists
    if not Path(db_path).exists():
        print(f"\n❌ ERROR: Database file not found!")
        print(f"\nLooking for .db files in C:\\Trading\\...")
        
        trading_dir = Path("C:/Trading")
        if trading_dir.exists():
            db_files = list(trading_dir.glob("*.db"))
            if db_files:
                print(f"Found {len(db_files)} database files:")
                for f in db_files:
                    print(f"  - {f}")
            else:
                print("  No .db files found in C:\\Trading\\")
        return
    
    print(f"File size: {Path(db_path).stat().st_size:,} bytes")
    print("=" * 70)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        if not tables:
            print("\n❌ No tables found in database!")
            return
        
        print(f"\nTables found: {len(tables)}")
        print("-" * 70)
        
        for (table_name,) in tables:
            print(f"\n📋 TABLE: {table_name}")
            print("-" * 40)
            
            # Get columns
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            print(f"  {'Column':<25} {'Type':<15} {'Nullable':<10}")
            print(f"  {'-'*25} {'-'*15} {'-'*10}")
            for col in columns:
                col_id, name, col_type, not_null, default, pk = col
                nullable = "NOT NULL" if not_null else "NULL"
                pk_str = " (PK)" if pk else ""
                print(f"  {name:<25} {col_type:<15} {nullable:<10}{pk_str}")
            
            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"\n  Row count: {count:,}")
            
            # Show sample data if small
            if count > 0 and count <= 20:
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
                rows = cursor.fetchall()
                if rows:
                    print(f"\n  Sample data (first 5 rows):")
                    col_names = [col[1] for col in columns]
                    # Truncate long values
                    for row in rows:
                        row_str = str(row)
                        if len(row_str) > 100:
                            row_str = row_str[:100] + "..."
                        print(f"    {row_str}")
        
        conn.close()
        print("\n" + "=" * 70)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(description='Inspect SQLite database')
    parser.add_argument('--database', '-d', default='C:/Trading/canslim_positions.db',
                        help='Database path')
    args = parser.parse_args()
    
    inspect_database(args.database)


if __name__ == '__main__':
    main()
