"""
Check avg_volume_50d status in positions table.

Usage:
    python check_avg_volume.py
    python check_avg_volume.py --database canslim_monitor.db
"""

import sys
import argparse
import sqlite3
from pathlib import Path


def check_avg_volume(db_path: str):
    """Check avg_volume_50d for all positions."""
    
    print("=" * 70)
    print("AVG_VOLUME_50D CHECK")
    print("=" * 70)
    print(f"Database: {db_path}")
    
    if not Path(db_path).exists():
        print(f"\n❌ File not found!")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if positions table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
        if not cursor.fetchone():
            print("\n❌ No 'positions' table found!")
            return
        
        # Get all position data relevant to volume
        cursor.execute("""
            SELECT symbol, state, pivot, avg_volume_50d, volume_updated_at, rs_rating
            FROM positions
            ORDER BY state, symbol
        """)
        rows = cursor.fetchall()
        
        if not rows:
            print("\n❌ No positions found!")
            return
        
        print(f"\nPositions: {len(rows)}")
        print("-" * 70)
        print(f"{'Symbol':<8} {'State':<6} {'Pivot':>10} {'AvgVol50d':>15} {'Updated':>20} {'RS':>5}")
        print("-" * 70)
        
        missing = []
        has_volume = []
        
        for row in rows:
            symbol, state, pivot, avg_vol, updated, rs = row
            
            state_str = "Watch" if state == 0 else f"Pos {state}"
            pivot_str = f"${pivot:.2f}" if pivot else "--"
            rs_str = str(rs) if rs else "--"
            
            if avg_vol and avg_vol > 0:
                has_volume.append(symbol)
                vol_str = f"{avg_vol:,}"
                updated_str = str(updated)[:16] if updated else "Never"
            else:
                missing.append(symbol)
                vol_str = "❌ MISSING"
                updated_str = "Never"
            
            print(f"{symbol:<8} {state_str:<6} {pivot_str:>10} {vol_str:>15} {updated_str:>20} {rs_str:>5}")
        
        print("-" * 70)
        print(f"\nSUMMARY:")
        print(f"  ✓ Has avg_volume_50d: {len(has_volume)}")
        print(f"  ❌ Missing avg_volume_50d: {len(missing)}")
        
        if missing:
            print(f"\n⚠️  Missing volume: {', '.join(missing)}")
            print(f"\nThis is why alerts show 'Vol --'!")
            print(f"\nTo fix, run:")
            print(f"    python -m canslim_monitor.services.volume_service update")
        
        conn.close()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description='Check avg_volume_50d in positions')
    parser.add_argument('--database', '-d', 
                        default='C:/Trading/canslim_monitor/canslim_monitor.db',
                        help='Database path')
    args = parser.parse_args()
    
    check_avg_volume(args.database)


if __name__ == '__main__':
    main()
