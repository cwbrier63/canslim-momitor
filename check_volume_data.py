"""
Check if watchlist positions have avg_volume_50d populated.

Usage:
    python check_volume_data.py
    python check_volume_data.py --database C:\Trading\canslim_positions.db
"""

import sys
import argparse
from datetime import datetime

# Fix for Python 3.10+ asyncio
import asyncio
if sys.version_info >= (3, 10):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


def check_volume_data(db_path: str = "C:/Trading/canslim_positions.db"):
    """Check volume data status for all watchlist positions."""
    
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
    except ImportError:
        print("ERROR: SQLAlchemy not installed")
        return
    
    print("=" * 70)
    print("VOLUME DATA CHECK")
    print("=" * 70)
    print(f"Database: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Connect to database
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        Session = sessionmaker(bind=engine)
        session = Session()
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        return
    
    # Query watchlist positions (state=0)
    try:
        result = session.execute(text("""
            SELECT symbol, avg_volume_50d, volume_updated_at, pivot, rs_rating
            FROM positions 
            WHERE state = 0
            ORDER BY symbol
        """))
        rows = result.fetchall()
    except Exception as e:
        print(f"ERROR: Query failed: {e}")
        print("\nTrying alternative query (maybe column doesn't exist)...")
        try:
            result = session.execute(text("""
                SELECT symbol, pivot, rs_rating
                FROM positions 
                WHERE state = 0
                ORDER BY symbol
            """))
            rows = result.fetchall()
            print("\n⚠️  avg_volume_50d column may not exist in your database!")
            print("    Run: python -m canslim_monitor.services.volume_service update")
            for row in rows:
                print(f"    {row[0]}: pivot=${row[1]:.2f}, RS={row[2]}")
            return
        except Exception as e2:
            print(f"ERROR: {e2}")
            return
    
    # Analyze results
    print(f"\nWatchlist Positions (state=0): {len(rows)}")
    print("-" * 70)
    print(f"{'Symbol':<8} {'Avg Vol 50d':>15} {'Updated':>20} {'Pivot':>10} {'RS':>5}")
    print("-" * 70)
    
    missing_volume = []
    has_volume = []
    
    for row in rows:
        symbol = row[0]
        avg_vol = row[1]
        updated = row[2]
        pivot = row[3]
        rs = row[4]
        
        if avg_vol and avg_vol > 0:
            has_volume.append(symbol)
            vol_str = f"{avg_vol:,}"
            updated_str = str(updated)[:19] if updated else "Never"
        else:
            missing_volume.append(symbol)
            vol_str = "❌ MISSING"
            updated_str = "Never"
        
        print(f"{symbol:<8} {vol_str:>15} {updated_str:>20} ${pivot:>8.2f} {rs or '--':>5}")
    
    print("-" * 70)
    print(f"\nSUMMARY:")
    print(f"  ✓ Has avg_volume_50d: {len(has_volume)} positions")
    print(f"  ❌ Missing avg_volume_50d: {len(missing_volume)} positions")
    
    if missing_volume:
        print(f"\n⚠️  Positions missing volume data: {', '.join(missing_volume)}")
        print(f"\nTo fix, run:")
        print(f"    python -m canslim_monitor.services.volume_service update")
    else:
        print(f"\n✓ All positions have volume data!")
    
    # Check historical bars table
    print("\n" + "-" * 70)
    print("HISTORICAL BARS CHECK")
    print("-" * 70)
    
    try:
        result = session.execute(text("""
            SELECT symbol, COUNT(*) as bar_count, 
                   MIN(bar_date) as oldest, MAX(bar_date) as newest
            FROM historical_bars
            GROUP BY symbol
            ORDER BY symbol
        """))
        bar_rows = result.fetchall()
        
        if bar_rows:
            print(f"{'Symbol':<8} {'Bars':>8} {'Oldest':>12} {'Newest':>12}")
            print("-" * 45)
            for row in bar_rows:
                print(f"{row[0]:<8} {row[1]:>8} {str(row[2]):>12} {str(row[3]):>12}")
        else:
            print("❌ No historical bars found!")
            print("\nRun: python -m canslim_monitor.services.volume_service update")
    except Exception as e:
        print(f"⚠️  Historical bars table may not exist: {e}")
    
    session.close()
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description='Check volume data in database')
    parser.add_argument('--database', '-d', default='C:/Trading/canslim_positions.db',
                        help='Database path')
    args = parser.parse_args()
    
    check_volume_data(args.database)


if __name__ == '__main__':
    main()
