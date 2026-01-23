"""
Test Position Thread - Bypass Market Hours
==========================================
Runs position monitoring cycle against all positions in database,
bypassing market hours check. Uses IBKR for live prices.

Run: python -m canslim_monitor.tests.run_position_cycle
"""

import sys
import asyncio

# CRITICAL: Create event loop BEFORE importing ib_insync
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import logging
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('run_position_cycle')

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def run_cycle(db_override: str = None):
    """Run a single position monitoring cycle."""
    
    print("=" * 70)
    print("POSITION MONITORING CYCLE - BYPASS MARKET HOURS")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Import after path setup
    from canslim_monitor.data.database import DatabaseManager
    from canslim_monitor.data.models import Position, Alert
    from canslim_monitor.utils.config import get_config
    from canslim_monitor.core.position_monitor import PositionMonitor, PositionContext
    from canslim_monitor.services.alert_service import AlertService
    from canslim_monitor.services.technical_data_service import TechnicalDataService
    
    # Load config
    config = get_config()
    
    # Setup database - use override, then config, then default
    if db_override:
        db_path = Path(db_override)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
    else:
        db_config = config.get('database', {})
        db_path = db_config.get('path', 'canslim_monitor.db')
        
        # Handle relative paths
        if not Path(db_path).is_absolute():
            db_path = Path(__file__).parent.parent / db_path
        else:
            db_path = Path(db_path)
    
    print(f"\nDatabase: {db_path}")
    
    if not db_path.exists():
        print(f"❌ Database not found!")
        return False
    
    db = DatabaseManager(str(db_path))
    session = db.get_new_session()
    
    # Get all positions (state >= 1 for active, state = 0 for watchlist)
    active_positions = session.query(Position).filter(Position.state >= 1).all()
    watchlist_positions = session.query(Position).filter(Position.state == 0).all()
    
    print(f"\n📊 Positions in database:")
    print(f"   Active (state >= 1): {len(active_positions)}")
    print(f"   Watchlist (state = 0): {len(watchlist_positions)}")
    
    if not active_positions:
        print("\n⚠️  No active positions to monitor. Checking watchlist for breakouts...")
    
    # Connect to IBKR
    print("\n📡 Connecting to IBKR...")
    try:
        from canslim_monitor.integrations.ibkr_client import IBKRClient
        
        ibkr_config = config.get('ibkr', {})
        host = ibkr_config.get('host', '127.0.0.1')
        port = ibkr_config.get('port', 4001)
        client_id = ibkr_config.get('client_id_base', 20) + 9  # Use offset to avoid conflicts
        
        print(f"   Host: {host}:{port}, Client ID: {client_id}")
        
        ibkr = IBKRClient(
            host=host,
            port=port,
            client_id=client_id,
            logger=logging.getLogger('ibkr'),
        )
        
        if not ibkr.connect():
            print("❌ Could not connect to IBKR. Is TWS/Gateway running?")
            return False
        
        print("✅ Connected to IBKR")
        
    except Exception as e:
        print(f"❌ IBKR connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    try:
        # Setup AlertService (no Discord, no cooldown for testing)
        print("\n🔧 Setting up AlertService...")
        alert_service = AlertService(
            db_session_factory=db.get_new_session,
            discord_notifier=None,
            cooldown_minutes=60,
            enable_cooldown=False,  # Disable for testing
            enable_suppression=False,  # Disable market suppression
            logger=logging.getLogger('alerts'),
        )
        
        # Setup TechnicalDataService
        market_data_config = config.get('market_data', {})
        polygon_key = market_data_config.get('api_key', '')
        
        if polygon_key:
            print(f"   Polygon API key: {polygon_key[:8]}...")
        else:
            print("   ⚠️  No Polygon/Massive API key configured")
        
        technical_service = TechnicalDataService(
            polygon_api_key=polygon_key,
            cache_duration_hours=1,
            logger=logging.getLogger('technical'),
        )
        
        # Setup PositionMonitor
        pm_config = config.get('position_monitoring', {})
        monitor = PositionMonitor(
            config=pm_config,
            logger=logging.getLogger('position_monitor'),
        )
        
        all_alerts = []
        
        # =====================================================
        # PART 1: Check Active Positions
        # =====================================================
        if active_positions:
            print("\n" + "=" * 70)
            print("PART 1: ACTIVE POSITION MONITORING")
            print("=" * 70)
            
            symbols = [p.symbol for p in active_positions]
            print(f"\nSymbols: {', '.join(symbols)}")
            
            # Get prices from IBKR
            print("\n📈 Fetching prices...")
            price_data = {}
            for symbol in symbols:
                try:
                    quote = ibkr.get_quote(symbol)
                    if quote and quote.get('last'):
                        price = quote['last']
                        price_data[symbol] = {
                            'price': price,
                            'volume_ratio': 1.0,  # Would need streaming for real-time
                            'max_price': price,
                            'max_gain_pct': 0,
                        }
                        print(f"   {symbol}: ${price:.2f}")
                    else:
                        print(f"   {symbol}: No price")
                except Exception as e:
                    print(f"   {symbol}: Error - {e}")
            
            # Get technical data from Polygon
            print("\n📊 Fetching technical data...")
            technical_data = {}
            if polygon_key:
                technical_data = technical_service.get_multiple(symbols)
                for symbol, data in technical_data.items():
                    ma50 = data.get('ma_50', 'N/A')
                    ma21 = data.get('ma_21', 'N/A')
                    print(f"   {symbol}: MA50=${ma50}, MA21=${ma21}")
            else:
                print("   ⚠️  No Polygon API key - using position data for MAs")
                for p in active_positions:
                    technical_data[p.symbol] = {
                        'ma_50': p.ma_50,
                        'ma_21': p.ma_21,
                        'ma_200': p.ma_200,
                    }
            
            # Merge volume ratio into technical data
            for symbol in price_data:
                if symbol not in technical_data:
                    technical_data[symbol] = {}
                technical_data[symbol]['volume_ratio'] = price_data[symbol].get('volume_ratio', 1.0)
                technical_data[symbol]['max_price'] = price_data[symbol].get('max_price')
                technical_data[symbol]['max_gain_pct'] = price_data[symbol].get('max_gain_pct', 0)
            
            # Run monitoring cycle
            print("\n🔄 Running position monitor cycle...")
            result = monitor.run_cycle(active_positions, price_data, technical_data)
            
            print(f"\n📊 Results:")
            print(f"   Positions checked: {result.positions_checked}")
            print(f"   Alerts generated: {result.alerts_generated}")
            print(f"   Cycle time: {result.cycle_time_ms:.1f}ms")
            
            if result.errors:
                print(f"\n⚠️  Errors:")
                for err in result.errors:
                    print(f"   - {err}")
            
            # Process alerts
            if result.alerts:
                print(f"\n🔔 Position Alerts Generated:")
                print("-" * 70)
                
                for alert in result.alerts:
                    print(f"\n📌 {alert.symbol} - {alert.alert_type.value}/{alert.subtype.value}")
                    print(f"   Action: {alert.action}")
                    
                    # Show message preview
                    if alert.message:
                        lines = alert.message.split('\n')[:3]
                        for line in lines:
                            if line.strip():
                                print(f"   {line}")
                    
                    # Save to database
                    saved = alert_service.create_alert(
                        symbol=alert.symbol,
                        alert_type=alert.alert_type,
                        subtype=alert.subtype,
                        context=alert.context,
                        position_id=alert.position_id,
                        message=alert.message,
                        action=alert.action,
                        thread_source=alert.thread_source,
                        force=True,
                    )
                    
                    if saved:
                        print(f"   ✅ Saved to database")
                        all_alerts.append(alert)
                    else:
                        print(f"   ❌ Failed to save")
            else:
                print("\n✅ No position alerts generated")
        
        # =====================================================
        # PART 2: Check Watchlist for Breakouts
        # =====================================================
        if watchlist_positions:
            print("\n" + "=" * 70)
            print("PART 2: BREAKOUT DETECTION (WATCHLIST)")
            print("=" * 70)
            
            from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertContext
            
            watchlist_symbols = [p.symbol for p in watchlist_positions]
            print(f"\nSymbols: {', '.join(watchlist_symbols)}")
            
            # Fetch technical data for watchlist
            print("\n📊 Fetching technical data for watchlist...")
            watchlist_technical = {}
            if polygon_key:
                watchlist_technical = technical_service.get_multiple(watchlist_symbols)
                fetched = len([s for s in watchlist_technical if watchlist_technical[s].get('ma_50')])
                print(f"   Got MAs for {fetched}/{len(watchlist_symbols)} symbols")
            
            # Get prices and check for breakouts
            print("\n📈 Fetching prices...")
            for p in watchlist_positions:
                symbol = p.symbol
                pivot = p.pivot
                
                if not pivot:
                    print(f"   {symbol}: No pivot set, skipping")
                    continue
                
                try:
                    quote = ibkr.get_quote(symbol)
                    if not quote or not quote.get('last'):
                        print(f"   {symbol}: No price")
                        continue
                    
                    price = quote['last']
                    pct_from_pivot = ((price - pivot) / pivot) * 100
                    
                    # Get MAs for this symbol
                    tech = watchlist_technical.get(symbol, {})
                    ma_50 = tech.get('ma_50') or p.ma_50 or 0
                    ma_21 = tech.get('ma_21') or p.ma_21 or 0
                    ma_200 = tech.get('ma_200') or p.ma_200 or 0
                    
                    print(f"   {symbol}: ${price:.2f} | Pivot: ${pivot:.2f} | {pct_from_pivot:+.1f}%")
                    
                    # Determine breakout status
                    alert_subtype = None
                    message = ""
                    action = ""
                    volume_ratio = 1.0  # Assume for now
                    
                    if pct_from_pivot > 5:
                        alert_subtype = AlertSubtype.EXTENDED
                        message = f"""⚠️ EXTENDED - AVOID CHASING

Price: ${price:.2f} (+{pct_from_pivot:.1f}% above pivot)
Pivot: ${pivot:.2f}
Buy Zone: ${pivot:.2f} - ${pivot * 1.05:.2f}

▶ ACTION: DO NOT CHASE

Stock has moved beyond the 5% buy zone.
Wait for pullback to 21 EMA or new base formation."""
                        action = "DO NOT CHASE"
                        
                    elif pct_from_pivot > 0:
                        # In buy zone - treat as confirmed for testing
                        alert_subtype = AlertSubtype.CONFIRMED
                        stop = pivot * 0.93
                        message = f"""🚀 BREAKOUT - IN BUY ZONE

Price: ${price:.2f} (+{pct_from_pivot:.1f}% above pivot)
Pivot: ${pivot:.2f}
Buy Zone: ${pivot:.2f} - ${pivot * 1.05:.2f}

▶ ACTION: EVALUATE ENTRY
   Grade: {p.entry_grade or 'N/A'} | Score: {p.entry_score or 'N/A'}
   Stop: ${stop:.2f} (-7% from pivot)

Stock is in buy zone. Confirm volume before entry."""
                        action = "EVALUATE ENTRY"
                        
                    elif pct_from_pivot > -2:
                        alert_subtype = AlertSubtype.APPROACHING
                        message = f"""👀 APPROACHING PIVOT

Price: ${price:.2f} ({pct_from_pivot:+.1f}% from pivot)
Pivot: ${pivot:.2f}
Distance: {abs(pct_from_pivot):.1f}%

▶ ACTION: PREPARE FOR ENTRY

Stock is within 2% of breakout point.
Calculate position size and be ready."""
                        action = "PREPARE FOR ENTRY"
                    
                    if alert_subtype:
                        print(f"      🔔 {alert_subtype.value}")
                        
                        context = AlertContext(
                            current_price=price,
                            pivot_price=pivot,
                            volume_ratio=volume_ratio,
                            grade=p.entry_grade or "",
                            score=p.entry_score or 0,
                            market_regime="TEST_MODE",
                            ma_50=ma_50,
                            ma_21=ma_21,
                            ma_200=ma_200,
                            state_at_alert=0,  # Watching
                        )
                        
                        saved = alert_service.create_alert(
                            symbol=symbol,
                            alert_type=AlertType.BREAKOUT,
                            subtype=alert_subtype,
                            context=context,
                            position_id=p.id,
                            message=message,
                            action=action,
                            thread_source="breakout_thread",
                            force=True,
                        )
                        
                        if saved:
                            print(f"      ✅ Saved")
                            all_alerts.append(saved)
                    
                except Exception as e:
                    print(f"   {symbol}: Error - {e}")
        
        # =====================================================
        # SUMMARY
        # =====================================================
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Total alerts created: {len(all_alerts)}")
        
        # Verify in database
        session2 = db.get_new_session()
        recent = session2.query(Alert).filter(
            Alert.alert_time >= datetime.now().replace(hour=0, minute=0, second=0)
        ).order_by(Alert.alert_time.desc()).all()
        
        print(f"\nAlerts in database today: {len(recent)}")
        print("\nRecent alerts:")
        for a in recent[:10]:
            has_msg = "✅" if a.message else "❌"
            has_act = "✅" if a.action else "❌"
            print(f"   {a.alert_time.strftime('%H:%M:%S')} {a.symbol:6} {a.alert_type:10} {a.alert_subtype:15} msg={has_msg} act={has_act}")
        
        session2.close()
        
        print("\n✅ Test complete!")
        return True
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return False
        
    finally:
        try:
            ibkr.disconnect()
            print("\n📡 Disconnected from IBKR")
        except:
            pass
        session.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test position monitoring cycle')
    parser.add_argument('--db', type=str, help='Database path (overrides config)')
    args = parser.parse_args()
    
    success = run_cycle(db_override=args.db)
    sys.exit(0 if success else 1)
