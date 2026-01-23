"""
Test script for Market Regime Discord alerts.

Run from C:\\Trading:
    python canslim_monitor/regime/test_regime_alert.py
"""

import logging
import sys
import os

# Add parent directory to path so we can import canslim_monitor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('regime_test')

def main():
    print("=" * 60)
    print("MARKET REGIME - MANUAL TEST")
    print("=" * 60)
    
    # Change to Trading directory for config loading
    original_dir = os.getcwd()
    trading_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.chdir(trading_dir)
    print(f"Working directory: {os.getcwd()}")
    
    # Load config - check user_config FIRST
    config_paths = [
        'canslim_monitor/user_config.yaml',  # User settings (priority)
        'user_config.yaml',
        'canslim_monitor/config.yaml',       # Default fallback
        'config.yaml',
    ]
    
    config = {}
    config_path = None
    for path in config_paths:
        if os.path.exists(path):
            config_path = path
            break
    
    if config_path:
        import yaml
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
        print(f"✓ Loaded config from: {config_path}")
    else:
        print("⚠ No config file found, using defaults")
    
    # Check for Discord webhook - handle both config structures
    discord_config = config.get('discord', {})
    webhook_url = (
        discord_config.get('regime_webhook_url') or 
        discord_config.get('market_webhook_url') or
        discord_config.get('webhook_url') or
        discord_config.get('webhooks', {}).get('market')  # Nested structure
    )
    
    if webhook_url:
        print(f"✓ Discord webhook found: ...{webhook_url[-20:]}")
    else:
        print("⚠ No Discord webhook configured - alert won't be sent")
        print("  Add to your config:")
        print("    discord:")
        print("      regime_webhook_url: 'https://discord.com/api/webhooks/...'")
    
    # Check for Polygon API key
    polygon_key = (
        config.get('market_data', {}).get('api_key') or
        config.get('polygon', {}).get('api_key') or
        os.environ.get('POLYGON_API_KEY') or
        os.environ.get('MASSIVE_API_KEY')
    )
    
    if polygon_key:
        print(f"✓ Polygon API key found: {polygon_key[:10]}...")
    else:
        print("⚠ No Polygon API key - cannot fetch market data")
        print("  Add to your config:")
        print("    market_data:")
        print("      api_key: 'your-polygon-api-key'")
        return
    
    print("\n" + "-" * 60)
    print("Running regime analysis...")
    print("-" * 60 + "\n")
    
    try:
        # Import regime components using full package path
        from canslim_monitor.regime.historical_data import fetch_spy_qqq_daily
        from canslim_monitor.regime.distribution_tracker import DistributionDayTracker
        from canslim_monitor.regime.ftd_tracker import (
            FollowThroughDayTracker,
            # Import SQLAlchemy models to register with Base
            RallyAttempt, FollowThroughDay, MarketStatus
        )
        from canslim_monitor.regime.market_regime import (
            MarketRegimeCalculator, DistributionData, 
            FTDData, create_overnight_data
        )
        from canslim_monitor.regime.discord_regime import DiscordRegimeNotifier
        
        # Import models from models_regime
        from canslim_monitor.regime.models_regime import (
            Base, RegimeType, DDayTrend,
            DistributionDay, DistributionDayCount, DistributionDayOverride,
            OvernightTrend, MarketRegimeAlert
        )
        
        # Create in-memory session for testing
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        
        engine = create_engine('sqlite:///:memory:')
        # Create ALL tables (now that all models are imported)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        print("✓ Components initialized (all tables created)")
        
        # Fetch market data
        print("\nFetching SPY/QQQ data from Polygon...")
        api_config = {'polygon': {'api_key': polygon_key}}
        data = fetch_spy_qqq_daily(lookback_days=35, config=api_config)
        
        spy_bars = data.get('SPY', [])
        qqq_bars = data.get('QQQ', [])
        
        if not spy_bars or not qqq_bars:
            print("✗ Failed to fetch market data")
            return
        
        print(f"✓ Fetched {len(spy_bars)} SPY bars, {len(qqq_bars)} QQQ bars")
        print(f"  Latest: SPY ${spy_bars[-1].close:.2f}, QQQ ${qqq_bars[-1].close:.2f}")
        
        # Calculate distribution days
        print("\nCalculating distribution days...")
        dist_tracker = DistributionDayTracker(db_session=session)
        combined = dist_tracker.get_combined_data(spy_bars, qqq_bars)
        
        print(f"✓ Distribution Days:")
        print(f"  SPY: {combined.spy_count} (Δ5d: {combined.spy_5day_delta:+d})")
        print(f"  QQQ: {combined.qqq_count} (Δ5d: {combined.qqq_5day_delta:+d})")
        print(f"  Trend: {combined.trend.value}")
        
        # Check FTD status
        print("\nChecking Follow-Through Day status...")
        ftd_tracker = FollowThroughDayTracker(db_session=session)
        ftd_status = ftd_tracker.get_market_phase_status(
            spy_bars, qqq_bars,
            spy_d_count=combined.spy_count,
            qqq_d_count=combined.qqq_count
        )
        
        print(f"✓ Market Phase: {ftd_status.phase.value}")
        if ftd_status.any_ftd_today:
            print("  🎉 FOLLOW-THROUGH DAY TODAY!")
        
        # Build rally histogram
        trading_days = [bar.date for bar in spy_bars]
        rally_histogram = ftd_tracker.build_rally_histogram(trading_days)
        
        # Create FTD data
        ftd_data = FTDData(
            market_phase=ftd_status.phase.value,
            in_rally_attempt=(ftd_status.spy_status.in_rally_attempt or 
                              ftd_status.qqq_status.in_rally_attempt),
            rally_day=max(ftd_status.spy_status.rally_day, ftd_status.qqq_status.rally_day),
            has_confirmed_ftd=(ftd_status.spy_status.has_confirmed_ftd or 
                               ftd_status.qqq_status.has_confirmed_ftd),
            ftd_still_valid=(ftd_status.spy_status.ftd_still_valid or 
                             ftd_status.qqq_status.ftd_still_valid),
            days_since_ftd=ftd_status.days_since_last_ftd,
            ftd_today=ftd_status.any_ftd_today,
            rally_failed_today=ftd_status.any_rally_failed,
            ftd_score_adjustment=ftd_status.ftd_score_adjustment,
            spy_ftd_date=ftd_status.spy_status.last_ftd_date,
            qqq_ftd_date=ftd_status.qqq_status.last_ftd_date,
            rally_histogram=rally_histogram,
            failed_rally_count=rally_histogram.failed_count,
            successful_ftd_count=rally_histogram.success_count
        )
        
        # Calculate regime
        print("\nCalculating regime score...")
        calculator = MarketRegimeCalculator(config.get('market_regime', {}))
        
        dist_data = DistributionData(
            spy_count=combined.spy_count,
            qqq_count=combined.qqq_count,
            spy_5day_delta=combined.spy_5day_delta,
            qqq_5day_delta=combined.qqq_5day_delta,
            trend=combined.trend,
            spy_dates=combined.spy_dates,
            qqq_dates=combined.qqq_dates
        )
        
        overnight = create_overnight_data(0.0, 0.0, 0.0)  # No IBKR for test
        
        score = calculator.calculate_regime(dist_data, overnight, None, ftd_data=ftd_data)
        
        min_exp, max_exp = calculator.get_exposure_percentage(score.regime, dist_data.total_count)
        
        print(f"✓ Regime: {score.regime.value}")
        print(f"  Composite Score: {score.composite_score:+.2f}")
        print(f"  Suggested Exposure: {min_exp}-{max_exp}%")
        
        # Send Discord alert
        if webhook_url:
            print("\n" + "-" * 60)
            print("Sending Discord alert...")
            print("-" * 60)
            
            notifier = DiscordRegimeNotifier(webhook_url=webhook_url)
            success = notifier.send_regime_alert(score, verbose=True)
            
            if success:
                print("\n✓ Discord alert sent successfully!")
            else:
                print("\n✗ Failed to send Discord alert")
        else:
            print("\n⚠ Skipping Discord (no webhook configured)")
        
        print("\n" + "=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        print(f"\n✗ Error: {e}")
    finally:
        os.chdir(original_dir)


if __name__ == '__main__':
    main()
