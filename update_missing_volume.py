"""
Update avg_volume_50d for positions missing volume data.

Usage:
    python update_missing_volume.py
    python update_missing_volume.py --database canslim_positions.db
"""

import sys
import argparse
import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import time

# Fix for Python 3.10+ asyncio
import asyncio
if sys.version_info >= (3, 10):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


def get_polygon_bars(api_key: str, symbol: str, days: int = 60) -> list:
    """Fetch daily bars from Polygon API."""
    import requests
    
    end_date = date.today() - timedelta(days=1)  # Yesterday (free tier delay)
    start_date = end_date - timedelta(days=int(days * 1.5) + 10)
    
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}"
    params = {
        'apiKey': api_key,
        'adjusted': 'true',
        'sort': 'asc',
        'limit': days + 20
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'OK' and data.get('results'):
                return data['results']
        elif response.status_code == 429:
            print(f"    Rate limited - waiting 60s...")
            time.sleep(60)
            return get_polygon_bars(api_key, symbol, days)
        else:
            print(f"    API error {response.status_code}: {response.text[:100]}")
    except Exception as e:
        print(f"    Request error: {e}")
    
    return []


def calculate_avg_volume(bars: list, days: int = 50) -> int:
    """Calculate average volume from bars."""
    if not bars:
        return 0
    
    # Get most recent N bars
    recent = bars[-days:] if len(bars) > days else bars
    
    if not recent:
        return 0
    
    total_vol = sum(b.get('v', 0) for b in recent)
    return int(total_vol / len(recent))


def update_missing_volume(db_path: str, api_key: str = None):
    """Update avg_volume_50d for positions that are missing it."""
    
    print("=" * 70)
    print("UPDATE MISSING VOLUME DATA")
    print("=" * 70)
    print(f"Database: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not Path(db_path).exists():
        print(f"\n❌ Database not found!")
        return
    
    # Get API key from config if not provided
    if not api_key:
        # Try to load from user_config.yaml
        try:
            import yaml
            config_paths = [
                Path(db_path).parent / 'user_config.yaml',
                Path(db_path).parent / 'canslim_monitor' / 'user_config.yaml',
                Path.cwd() / 'user_config.yaml',
                Path.cwd() / 'canslim_monitor' / 'user_config.yaml',
            ]
            
            for config_path in config_paths:
                if config_path.exists():
                    with open(config_path) as f:
                        config = yaml.safe_load(f)
                    
                    # Try market_data section first, then polygon
                    api_key = config.get('market_data', {}).get('api_key')
                    if not api_key:
                        api_key = config.get('polygon', {}).get('api_key')
                    
                    if api_key:
                        print(f"API key loaded from: {config_path}")
                        break
        except Exception as e:
            print(f"Could not load config: {e}")
    
    if not api_key:
        print("\n❌ No API key provided!")
        print("\nProvide via:")
        print("  1. --api-key YOUR_KEY")
        print("  2. user_config.yaml -> market_data.api_key")
        return
    
    print("=" * 70)
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Find positions missing volume
    cursor.execute("""
        SELECT id, symbol, pivot, state
        FROM positions
        WHERE avg_volume_50d IS NULL OR avg_volume_50d <= 0
        ORDER BY state, symbol
    """)
    missing = cursor.fetchall()
    
    if not missing:
        print("\n✓ All positions have volume data!")
        conn.close()
        return
    
    print(f"\nPositions missing volume: {len(missing)}")
    print("-" * 70)
    
    updated = 0
    failed = []
    
    for pos_id, symbol, pivot, state in missing:
        state_str = "Watch" if state == 0 else f"Pos {state}"
        print(f"\n  {symbol} ({state_str}):")
        
        # Fetch from Polygon
        print(f"    Fetching 50-day data from Polygon...")
        bars = get_polygon_bars(api_key, symbol, days=60)
        
        if not bars:
            print(f"    ❌ No data returned")
            failed.append(symbol)
            time.sleep(0.5)  # Rate limit
            continue
        
        # Calculate average
        avg_vol = calculate_avg_volume(bars, days=50)
        
        if avg_vol <= 0:
            print(f"    ❌ Could not calculate average")
            failed.append(symbol)
            time.sleep(0.5)
            continue
        
        # Update database
        cursor.execute("""
            UPDATE positions
            SET avg_volume_50d = ?,
                volume_updated_at = ?
            WHERE id = ?
        """, (avg_vol, datetime.now().isoformat(), pos_id))
        
        conn.commit()
        print(f"    ✓ Updated: {avg_vol:,}")
        updated += 1
        
        # Also store historical bars if table exists
        try:
            for bar in bars:
                bar_date = datetime.fromtimestamp(bar['t'] / 1000).date()
                cursor.execute("""
                    INSERT OR REPLACE INTO historical_bars 
                    (symbol, bar_date, open, high, low, close, volume, vwap, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    bar_date.isoformat(),
                    bar.get('o'),
                    bar.get('h'),
                    bar.get('l'),
                    bar.get('c'),
                    bar.get('v'),
                    bar.get('vw'),
                    datetime.now().isoformat()
                ))
            conn.commit()
            print(f"    ✓ Stored {len(bars)} historical bars")
        except Exception as e:
            print(f"    (Could not store bars: {e})")
        
        time.sleep(0.5)  # Rate limit between symbols
    
    conn.close()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  ✓ Updated: {updated}")
    print(f"  ❌ Failed: {len(failed)}")
    
    if failed:
        print(f"\nFailed symbols: {', '.join(failed)}")
        print("These may be delisted or have invalid symbols.")
    
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description='Update missing volume data')
    parser.add_argument('--database', '-d', 
                        default='C:/Trading/canslim_monitor/canslim_positions.db',
                        help='Database path')
    parser.add_argument('--api-key', '-k',
                        help='Polygon API key (or set in user_config.yaml)')
    args = parser.parse_args()
    
    update_missing_volume(args.database, args.api_key)


if __name__ == '__main__':
    main()
