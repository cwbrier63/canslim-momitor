"""
IBKR Volume Data Diagnostic Tool
================================
Tests what volume data IBKR returns in different modes.

Run this to diagnose why volume shows as "--" in alerts.

Usage:
    python test_ibkr_volume.py
    python test_ibkr_volume.py --symbol AAPL
    python test_ibkr_volume.py --port 7497  # TWS paper trading
"""

import sys
import time
import argparse
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

# Fix for Python 3.10+ asyncio event loop issue
# Must be done BEFORE importing ib_insync
if sys.version_info >= (3, 10):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

def test_ibkr_volume(
    host: str = "127.0.0.1",
    port: int = 4001,
    client_id: int = 99,
    symbols: list = None
):
    """
    Test IBKR market data to diagnose volume issues.
    """
    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("ERROR: ib_insync not installed. Run: pip install ib_insync")
        return
    
    symbols = symbols or ["AAPL", "NVDA", "SPY", "MSFT", "IBKR"]
    
    print("=" * 70)
    print("IBKR VOLUME DATA DIAGNOSTIC")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Host: {host}:{port}")
    print(f"Client ID: {client_id}")
    print(f"Symbols: {', '.join(symbols)}")
    print("=" * 70)
    
    # Connect to IBKR
    ib = IB()
    
    try:
        print("\n[1] Connecting to IBKR...")
        ib.connect(host, port, clientId=client_id)
        print(f"    ✓ Connected!")
        print(f"    Server Version: {ib.client.serverVersion()}")
        
        # Check account info
        accounts = ib.managedAccounts()
        print(f"    Accounts: {accounts}")
        
    except Exception as e:
        print(f"    ✗ Connection failed: {e}")
        print("\n    Make sure:")
        print("    - TWS or IB Gateway is running")
        print("    - API connections are enabled in TWS/Gateway settings")
        print(f"    - Port {port} is correct (4001=Gateway Paper, 7497=TWS Paper)")
        return
    
    print("\n" + "-" * 70)
    print("[2] TESTING SNAPSHOT MODE (what breakout_thread uses)")
    print("-" * 70)
    
    for symbol in symbols:
        print(f"\n  {symbol}:")
        test_snapshot_mode(ib, symbol)
    
    print("\n" + "-" * 70)
    print("[3] TESTING SNAPSHOT WITH VOLUME TICK TYPES")
    print("-" * 70)
    
    for symbol in symbols:
        print(f"\n  {symbol}:")
        test_snapshot_with_volume_ticks(ib, symbol)
    
    print("\n" + "-" * 70)
    print("[4] TESTING STREAMING MODE (subscription-based)")
    print("-" * 70)
    
    # Only test one symbol for streaming to avoid data limits
    test_streaming_mode(ib, symbols[0])
    
    print("\n" + "-" * 70)
    print("[5] TESTING HISTORICAL DATA (for comparison)")
    print("-" * 70)
    
    avg_volumes = test_historical_data(ib, symbols[0])
    
    print("\n" + "-" * 70)
    print("[6] SIMULATING BREAKOUT THREAD RVOL CALCULATION")
    print("-" * 70)
    
    # Get the average volume from historical data for RVOL calc
    hist_avg_vol = avg_volumes.get(symbols[0], 500000) if avg_volumes else 500000
    
    for symbol in symbols[:3]:  # Test first 3 symbols
        print(f"\n  {symbol}:")
        simulate_breakout_thread_rvol(ib, symbol, hist_avg_vol)
    
    # Disconnect
    print("\n" + "=" * 70)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 70)
    
    ib.disconnect()


def safe_str(val) -> str:
    """Convert value to string, handling NaN and None."""
    if val is None:
        return "None"
    if isinstance(val, float):
        if val != val:  # NaN check
            return "NaN"
        return f"{val:,.2f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def test_snapshot_mode(ib, symbol: str):
    """Test basic snapshot mode (True, False)."""
    from ib_insync import Stock
    
    try:
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        
        if not contract.conId:
            print(f"    ✗ Contract qualification failed")
            return
        
        # Request snapshot (snapshot=True, regulatorySnapshot=False)
        ticker = ib.reqMktData(contract, '', True, False)
        
        # Wait for data
        ib.sleep(2.0)
        
        print(f"    last:      {safe_str(ticker.last)}")
        print(f"    close:     {safe_str(ticker.close)}")
        print(f"    bid:       {safe_str(ticker.bid)}")
        print(f"    ask:       {safe_str(ticker.ask)}")
        print(f"    volume:    {safe_str(ticker.volume)} {'<-- PROBLEM!' if ticker.volume is None or (isinstance(ticker.volume, float) and ticker.volume != ticker.volume) else ''}")
        print(f"    avVolume:  {safe_str(ticker.avVolume)}")
        print(f"    high:      {safe_str(ticker.high)}")
        print(f"    low:       {safe_str(ticker.low)}")
        print(f"    open:      {safe_str(ticker.open)}")
        
        # Cancel
        ib.cancelMktData(contract)
        
    except Exception as e:
        print(f"    ✗ Error: {e}")


def test_snapshot_with_volume_ticks(ib, symbol: str):
    """Test snapshot with specific volume tick types."""
    from ib_insync import Stock
    
    try:
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        
        if not contract.conId:
            print(f"    ✗ Contract qualification failed")
            return
        
        # Request with volume-specific generic tick types:
        # 100 = Option Volume
        # 101 = Option Open Interest  
        # 104 = Historical Volatility
        # 106 = Implied Volatility
        # 162 = Index Future Premium
        # 165 = Misc Stats
        # 221 = Mark Price
        # 225 = Auction values
        # 233 = RT Volume (Real-Time Volume)
        # 236 = Shortable
        # 256 = Inventory
        # 258 = Fundamental Ratios
        # 411 = RT Historical Volatility
        
        tick_types = '233'  # RT Volume
        
        ticker = ib.reqMktData(contract, tick_types, True, False)
        
        # Wait longer for volume data
        ib.sleep(3.0)
        
        print(f"    Tick types requested: '{tick_types}'")
        print(f"    last:      {safe_str(ticker.last)}")
        print(f"    volume:    {safe_str(ticker.volume)} {'<-- PROBLEM!' if ticker.volume is None or (isinstance(ticker.volume, float) and ticker.volume != ticker.volume) else ''}")
        print(f"    avVolume:  {safe_str(ticker.avVolume)}")
        
        # Check if there's any RT volume data
        if hasattr(ticker, 'rtVolume'):
            print(f"    rtVolume:  {safe_str(ticker.rtVolume)}")
        
        # Look at all ticks received
        if ticker.ticks:
            print(f"    Ticks received: {len(ticker.ticks)}")
            for tick in ticker.ticks[-5:]:  # Show last 5
                print(f"      - {tick}")
        else:
            print(f"    Ticks received: 0 <-- No tick data!")
        
        # Cancel
        ib.cancelMktData(contract)
        
    except Exception as e:
        print(f"    ✗ Error: {e}")


def test_streaming_mode(ib, symbol: str):
    """Test streaming mode (non-snapshot)."""
    from ib_insync import Stock
    
    print(f"\n  {symbol} (streaming for 5 seconds):")
    
    try:
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        
        if not contract.conId:
            print(f"    ✗ Contract qualification failed")
            return
        
        # Request streaming data (snapshot=False)
        ticker = ib.reqMktData(contract, '233', False, False)
        
        # Collect updates for 5 seconds
        print(f"    Waiting for streaming updates...")
        
        volume_readings = []
        for i in range(10):
            ib.sleep(0.5)
            vol = ticker.volume
            volume_readings.append(vol)
            
            if i == 0 or (i + 1) % 5 == 0:
                print(f"    [{i*0.5:.1f}s] volume={safe_str(vol)}, last={safe_str(ticker.last)}")
        
        # Check if volume ever populated
        valid_volumes = [v for v in volume_readings if v is not None and not (isinstance(v, float) and v != v)]
        
        if valid_volumes:
            print(f"    ✓ Got {len(valid_volumes)} valid volume readings")
            print(f"    Final volume: {safe_str(valid_volumes[-1])}")
        else:
            print(f"    ✗ No valid volume data received in streaming mode either!")
        
        # Cancel
        ib.cancelMktData(contract)
        
    except Exception as e:
        print(f"    ✗ Error: {e}")


def test_historical_data(ib, symbol: str) -> dict:
    """Test historical data as baseline comparison."""
    from ib_insync import Stock
    
    print(f"\n  {symbol} (last 5 daily bars):")
    avg_volumes = {}
    
    try:
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        
        if not contract.conId:
            print(f"    ✗ Contract qualification failed")
            return avg_volumes
        
        # Request historical data
        bars = ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr='5 D',
            barSizeSetting='1 day',
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1
        )
        
        if bars:
            print(f"    ✓ Got {len(bars)} bars")
            print(f"    {'Date':<12} {'Close':>10} {'Volume':>15}")
            print(f"    {'-'*12} {'-'*10} {'-'*15}")
            for bar in bars[-5:]:
                print(f"    {str(bar.date):<12} {bar.close:>10.2f} {bar.volume:>15,}")
            
            # Calculate 5-day average
            avg_vol = sum(b.volume for b in bars) / len(bars)
            print(f"\n    5-day avg volume: {avg_vol:,.0f}")
            avg_volumes[symbol] = int(avg_vol)
        else:
            print(f"    ✗ No historical data returned")
        
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    return avg_volumes


def simulate_breakout_thread_rvol(ib, symbol: str, default_avg_vol: int = 500000):
    """Simulate exactly what breakout_thread does to calculate RVOL."""
    from ib_insync import Stock
    
    try:
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        
        if not contract.conId:
            print(f"    ✗ Contract qualification failed")
            return
        
        # This is exactly what breakout_thread does (basic snapshot, no generic ticks)
        ticker = ib.reqMktData(contract, '', True, False)
        ib.sleep(2.0)
        
        def safe_float(val, default=0.0):
            if val is None or (isinstance(val, float) and val != val):
                return default
            return float(val)
        
        volume = int(safe_float(ticker.volume))
        ibkr_avg_volume = int(safe_float(ticker.avVolume, 0))
        
        print(f"    Raw IBKR data:")
        print(f"      ticker.volume = {ticker.volume} -> {volume:,}")
        print(f"      ticker.avVolume = {ticker.avVolume} -> {ibkr_avg_volume:,}")
        
        # Simulate the avg_volume fallback logic from breakout_thread
        # In real code: avg_volume = pos.avg_volume_50d or price_data['avg_volume'] or 500000
        pos_avg_volume_50d = None  # Simulating if position doesn't have this set
        
        if pos_avg_volume_50d and pos_avg_volume_50d > 0:
            avg_volume = pos_avg_volume_50d
            avg_volume_source = "pos.avg_volume_50d"
        elif ibkr_avg_volume > 0:
            avg_volume = ibkr_avg_volume
            avg_volume_source = "IBKR avVolume"
        else:
            avg_volume = default_avg_vol
            avg_volume_source = f"default ({default_avg_vol:,})"
        
        print(f"      Using avg_volume = {avg_volume:,} (from {avg_volume_source})")
        
        # Now calculate RVOL
        rvol = test_rvol_calculation(volume, avg_volume)
        
        # Determine display
        if rvol > 0.01:
            vol_display = f"{rvol:.1f}x"
        else:
            vol_display = "--"
        
        print(f"\n    RESULT: Vol display would be: '{vol_display}'")
        
        if vol_display == "--":
            print(f"    ⚠️  Volume shows '--' because:")
            if volume == 0:
                print(f"       - current_volume is 0")
            elif avg_volume == 0:
                print(f"       - avg_volume is 0")
            elif rvol <= 0.01:
                print(f"       - RVOL ({rvol:.4f}) is <= 0.01 threshold")
        
        ib.cancelMktData(contract)
        
    except Exception as e:
        print(f"    ✗ Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='IBKR Volume Data Diagnostic Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python test_ibkr_volume.py
    python test_ibkr_volume.py --symbol AAPL --symbol NVDA
    python test_ibkr_volume.py --port 7497  # TWS paper trading
    python test_ibkr_volume.py --port 4001  # IB Gateway paper trading
        """
    )
    
    parser.add_argument('--host', default='127.0.0.1', help='IBKR host')
    parser.add_argument('--port', type=int, default=4001, help='IBKR port (4001=Gateway, 7497=TWS)')
    parser.add_argument('--client-id', type=int, default=99, help='Client ID')
    parser.add_argument('--symbol', '-s', action='append', help='Symbol to test (can specify multiple)')
    
    args = parser.parse_args()
    
    symbols = args.symbol if args.symbol else None
    
    test_ibkr_volume(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        symbols=symbols
    )


def test_rvol_calculation(current_volume: int, avg_daily_volume: int) -> float:
    """Simulate the RVOL calculation from breakout_thread."""
    import pytz
    
    if not avg_daily_volume or avg_daily_volume <= 0:
        return 0.0
    
    if not current_volume or current_volume <= 0:
        return 0.0
    
    # Get current time in ET
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.now(et_tz)
    
    # Market hours: 9:30 AM - 4:00 PM ET
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    
    total_trading_minutes = 390  # 6.5 hours * 60
    
    if now_et < market_open:
        elapsed_minutes = 1
    elif now_et > market_close:
        elapsed_minutes = total_trading_minutes
    else:
        elapsed_minutes = (now_et - market_open).total_seconds() / 60
        elapsed_minutes = max(1, elapsed_minutes)
    
    day_fraction = min(elapsed_minutes / total_trading_minutes, 1.0)
    expected_volume = avg_daily_volume * day_fraction
    
    if expected_volume > 0:
        rvol = current_volume / expected_volume
    else:
        rvol = 0.0
    
    print(f"      RVOL Calculation Debug:")
    print(f"        Now (ET): {now_et.strftime('%H:%M:%S')}")
    print(f"        Elapsed minutes: {elapsed_minutes:.1f}")
    print(f"        Day fraction: {day_fraction:.3f}")
    print(f"        Current volume: {current_volume:,}")
    print(f"        Avg daily volume: {avg_daily_volume:,}")
    print(f"        Expected volume at this time: {expected_volume:,.0f}")
    print(f"        RVOL: {rvol:.2f}x")
    
    return rvol


if __name__ == '__main__':
    main()
