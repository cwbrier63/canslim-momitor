"""
Test Market Regime Alert - Standalone Runner

Runs the market regime analysis outside the Windows service
and optionally sends a Discord alert.

Usage:
    # Dry run (print alert, don't send)
    python test_regime_alert.py

    # Send actual alert
    python test_regime_alert.py --send

    # Verbose output
    python test_regime_alert.py -v

    # Use specific config
    python test_regime_alert.py --config user_config.yaml
"""

import argparse
import logging
import sys
from datetime import datetime, date
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Fix Unicode output on Windows (emojis in Discord alerts)
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML files."""
    import yaml

    config = {}

    # Load base config
    base_config_path = project_root / 'config.yaml'
    if base_config_path.exists():
        with open(base_config_path, 'r') as f:
            config = yaml.safe_load(f) or {}

    # Load user config (overrides base)
    user_config_path = project_root / 'user_config.yaml'
    if user_config_path.exists():
        with open(user_config_path, 'r') as f:
            user_config = yaml.safe_load(f) or {}
            # Deep merge
            for key, value in user_config.items():
                if isinstance(value, dict) and key in config:
                    config[key].update(value)
                else:
                    config[key] = value

    # Load specified config (highest priority)
    if config_path:
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, 'r') as f:
                override_config = yaml.safe_load(f) or {}
                for key, value in override_config.items():
                    if isinstance(value, dict) and key in config:
                        config[key].update(value)
                    else:
                        config[key] = value

    return config


def create_db_session(config: dict):
    """Create database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = config.get('database', {}).get('path', 'canslim_monitor.db')
    engine = create_engine(f'sqlite:///{db_path}')

    # Ensure tables exist
    from regime.models_regime import Base as RegimeBase
    from regime.ftd_tracker import Base as FTDBase

    RegimeBase.metadata.create_all(engine)
    FTDBase.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    return Session()


def run_regime_analysis(config: dict, session, verbose: bool = False):
    """
    Run the full regime analysis.

    Returns:
        RegimeScore or None
    """
    from regime.distribution_tracker import DistributionDayTracker
    from regime.ftd_tracker import FollowThroughDayTracker
    from regime.market_regime import (
        MarketRegimeCalculator, DistributionData, FTDData,
        create_overnight_data, calculate_entry_risk_score
    )
    from regime.market_phase_manager import MarketPhaseManager
    from regime.historical_data import fetch_spy_qqq_daily
    from regime.models_regime import MarketRegimeAlert, DDayTrend

    # Initialize components
    dist_config = config.get('distribution_days', {})
    use_indices = config.get('market_regime', {}).get('use_indices', False)

    dist_tracker = DistributionDayTracker(
        db_session=session,
        decline_threshold=dist_config.get('decline_threshold'),
        lookback_days=dist_config.get('lookback_days', 25),
        rally_expiration_pct=dist_config.get('rally_expiration_pct', 5.0),
        use_indices=use_indices
    )

    ftd_tracker = FollowThroughDayTracker(
        db_session=session,
        ftd_min_gain=config.get('ftd_min_gain', 1.25),
        ftd_earliest_day=config.get('ftd_earliest_day', 4)
    )

    phase_config = config.get('market_phase', {})
    phase_manager = MarketPhaseManager(
        db_session=session,
        thresholds={
            'pressure_min_ddays': phase_config.get('pressure_threshold', 5),
            'correction_min_ddays': phase_config.get('correction_threshold', 7),
            'confirmed_max_ddays': phase_config.get('confirmed_max_ddays', 4),
        }
    )

    calculator = MarketRegimeCalculator(config.get('market_regime', {}))

    # Fetch historical data
    if verbose:
        print("Fetching market data...")

    api_config = {
        'polygon': {
            'api_key': config.get('market_data', {}).get('api_key') or
                      config.get('polygon', {}).get('api_key')
        }
    }

    data = fetch_spy_qqq_daily(
        lookback_days=35,
        config=api_config,
        use_indices=use_indices
    )

    spy_bars = data.get('SPY', [])
    qqq_bars = data.get('QQQ', [])

    if not spy_bars or not qqq_bars:
        print("ERROR: Failed to fetch market data")
        return None

    if verbose:
        print(f"  Fetched {len(spy_bars)} SPY bars, {len(qqq_bars)} QQQ bars")
        print(f"  Date range: {spy_bars[0].date} to {spy_bars[-1].date}")

    # Calculate distribution days
    if verbose:
        print("\nCalculating distribution days...")

    combined_dist = dist_tracker.get_combined_data(spy_bars, qqq_bars)

    if verbose:
        print(f"  SPY: {combined_dist.spy_count} D-days (5-day delta: {combined_dist.spy_5day_delta:+d})")
        print(f"  QQQ: {combined_dist.qqq_count} D-days (5-day delta: {combined_dist.qqq_5day_delta:+d})")
        print(f"  Trend: {combined_dist.trend.value}")
        if combined_dist.had_expirations:
            print(f"  Expirations today: SPY={combined_dist.spy_expired_today}, QQQ={combined_dist.qqq_expired_today}")

    # Check FTD status
    if verbose:
        print("\nChecking Follow-Through Day status...")

    ftd_status = ftd_tracker.get_market_phase_status(
        spy_bars, qqq_bars,
        spy_d_count=combined_dist.spy_count,
        qqq_d_count=combined_dist.qqq_count
    )

    if verbose:
        print(f"  Market Phase: {ftd_status.phase.value}")
        print(f"  SPY Rally Day: {ftd_status.spy_status.rally_day}")
        print(f"  QQQ Rally Day: {ftd_status.qqq_status.rally_day}")
        if ftd_status.any_ftd_today:
            print("  🎉 FOLLOW-THROUGH DAY TODAY!")
        if ftd_status.ftd_from_pressure and ftd_status.ftd_from_pressure.triggered:
            print("  📈 FTD from pressure detected!")

    # Check phase transitions
    if verbose:
        print("\nChecking phase transitions...")

    phase_transition = phase_manager.update_phase(
        dist_data=combined_dist,
        ftd_data=ftd_status
    )

    if phase_transition.phase_changed:
        print(f"  ⚠️ PHASE CHANGE: {phase_transition.previous_phase.value} -> {phase_transition.current_phase.value}")
        print(f"     Reason: {phase_transition.trigger_reason}")

    # Build FTD data for calculator
    trading_days = [bar.date for bar in spy_bars]
    rally_histogram = ftd_tracker.build_rally_histogram(trading_days)

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

    # Build distribution data for calculator
    dist_data = DistributionData(
        spy_count=combined_dist.spy_count,
        qqq_count=combined_dist.qqq_count,
        spy_5day_delta=combined_dist.spy_5day_delta,
        qqq_5day_delta=combined_dist.qqq_5day_delta,
        trend=combined_dist.trend,
        spy_dates=combined_dist.spy_dates,
        qqq_dates=combined_dist.qqq_dates
    )

    # Use neutral overnight data (we don't have IBKR in test mode)
    overnight = create_overnight_data(0.0, 0.0, 0.0)

    # Get prior regime for trend
    prior_score = None
    try:
        prior = session.query(MarketRegimeAlert).filter(
            MarketRegimeAlert.date < date.today()
        ).order_by(MarketRegimeAlert.date.desc()).first()

        if prior:
            from regime.models_regime import TrendType
            prior_dist = DistributionData(
                spy_count=prior.spy_d_count,
                qqq_count=prior.qqq_d_count,
                spy_5day_delta=prior.spy_5day_delta or 0,
                qqq_5day_delta=prior.qqq_5day_delta or 0,
                trend=prior.d_day_trend or DDayTrend.STABLE
            )
            from regime.market_regime import OvernightData, RegimeScore
            prior_overnight = OvernightData(
                es_change_pct=0, es_trend=TrendType.NEUTRAL,
                nq_change_pct=0, nq_trend=TrendType.NEUTRAL,
                ym_change_pct=0, ym_trend=TrendType.NEUTRAL
            )
            prior_score = RegimeScore(
                composite_score=prior.composite_score,
                regime=prior.regime,
                distribution_data=prior_dist,
                overnight_data=prior_overnight,
                component_scores={},
                timestamp=datetime.combine(prior.date, datetime.min.time())
            )
    except Exception as e:
        if verbose:
            print(f"  Could not load prior regime: {e}")

    # Calculate regime score
    if verbose:
        print("\nCalculating regime score...")

    score = calculator.calculate_regime(
        dist_data, overnight, prior_score, ftd_data=ftd_data
    )

    # Calculate entry risk
    entry_risk_score, entry_risk_level = calculate_entry_risk_score(
        overnight, dist_data, ftd_data
    )
    score.entry_risk_score = entry_risk_score
    score.entry_risk_level = entry_risk_level

    if verbose:
        print(f"\n{'='*50}")
        print("REGIME ANALYSIS RESULTS")
        print(f"{'='*50}")
        print(f"  Regime: {score.regime.value}")
        print(f"  Composite Score: {score.composite_score:+.2f}")
        print(f"  Market Phase: {score.market_phase}")
        print(f"  Entry Risk: {entry_risk_level.value} ({entry_risk_score:+.2f})")
        if score.prior_regime:
            print(f"  Prior Regime: {score.prior_regime.value}")
            print(f"  Trend: {score.regime_trend}")
        print(f"{'='*50}")

    return score, phase_transition, combined_dist


def send_discord_alert(
    config: dict,
    score,
    dry_run: bool = True,
    verbose: bool = False
):
    """Send Discord alert."""
    from regime.discord_regime import DiscordRegimeNotifier
    from regime.models_regime import IBDMarketStatus, IBDExposureCurrent

    discord_config = config.get('discord', {})
    webhooks = discord_config.get('webhooks', {})

    webhook_url = (
        webhooks.get('regime_webhook_url') or
        webhooks.get('market') or
        discord_config.get('regime_webhook_url') or
        discord_config.get('webhook_url')
    )

    if not webhook_url and not dry_run:
        print("ERROR: No Discord webhook URL configured")
        return False

    notifier = DiscordRegimeNotifier(webhook_url=webhook_url)

    # Default IBD exposure (in a real scenario, load from DB)
    ibd_status = IBDMarketStatus.CONFIRMED_UPTREND
    ibd_min, ibd_max = IBDExposureCurrent.get_default_exposure(ibd_status)

    if verbose:
        print(f"\n{'='*50}")
        print("DISCORD ALERT")
        print(f"{'='*50}")
        if dry_run:
            print("Mode: DRY RUN (not sending)")
        else:
            print("Mode: SENDING")
        print(f"Webhook: {webhook_url[:50]}..." if webhook_url else "No webhook")

    success = notifier.send_regime_alert(
        score,
        verbose=True,
        dry_run=dry_run,
        ibd_status=ibd_status,
        ibd_exposure_min=ibd_min,
        ibd_exposure_max=ibd_max,
        ibd_updated_at=None
    )

    if not dry_run:
        if success:
            print("✅ Alert sent successfully!")
        else:
            print("❌ Failed to send alert")

    return success


def send_phase_change_alert(
    config: dict,
    phase_transition,
    dist_data,
    dry_run: bool = True,
    verbose: bool = False
):
    """Send phase change alert if there was a transition."""
    if not phase_transition.phase_changed:
        if verbose:
            print("\nNo phase change to alert.")
        return True

    from regime.discord_regime import DiscordRegimeNotifier
    from regime.models_regime import MarketPhaseHistory

    discord_config = config.get('discord', {})
    webhooks = discord_config.get('webhooks', {})

    webhook_url = (
        webhooks.get('regime_webhook_url') or
        webhooks.get('market') or
        discord_config.get('regime_webhook_url') or
        discord_config.get('webhook_url')
    )

    if not webhook_url and not dry_run:
        print("ERROR: No Discord webhook URL configured")
        return False

    notifier = DiscordRegimeNotifier(webhook_url=webhook_url)

    # Create MarketPhaseHistory object for the alert
    phase_history = MarketPhaseHistory(
        phase_date=date.today(),
        previous_phase=phase_transition.previous_phase.value,
        new_phase=phase_transition.current_phase.value,
        change_type=phase_transition.change_type.value,
        trigger_reason=phase_transition.trigger_reason,
        spy_dday_count=dist_data.spy_count,
        qqq_dday_count=dist_data.qqq_count,
        total_dday_count=dist_data.spy_count + dist_data.qqq_count,
        spy_expired_today=getattr(dist_data, 'spy_expired_today', 0),
        qqq_expired_today=getattr(dist_data, 'qqq_expired_today', 0)
    )

    if verbose:
        print(f"\n{'='*50}")
        print("PHASE CHANGE ALERT")
        print(f"{'='*50}")
        print(f"  {phase_transition.previous_phase.value} -> {phase_transition.current_phase.value}")
        print(f"  Type: {phase_transition.change_type.value}")
        if dry_run:
            print("Mode: DRY RUN")

    success = notifier.send_phase_change_alert(
        phase_history=phase_history,
        dist_data=dist_data,
        dry_run=dry_run
    )

    return success


def main():
    parser = argparse.ArgumentParser(
        description="Test Market Regime Alert - Standalone Runner"
    )
    parser.add_argument(
        '--send',
        action='store_true',
        help='Actually send the Discord alert (default: dry run)'
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config file (overrides default)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=True,
        help='Verbose output'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Quiet mode (minimal output)'
    )
    parser.add_argument(
        '--phase-only',
        action='store_true',
        help='Only send phase change alert (if any)'
    )
    parser.add_argument(
        '--regime-only',
        action='store_true',
        help='Only send regime alert (skip phase change)'
    )

    args = parser.parse_args()

    verbose = not args.quiet
    dry_run = not args.send

    # Setup logging
    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("="*60)
    print("MARKET REGIME TEST")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'SEND ALERTS' if not dry_run else 'DRY RUN'}")
    print("="*60)

    # Load config
    config = load_config(args.config)

    if verbose:
        print(f"\nConfig loaded from: {args.config or 'config.yaml + user_config.yaml'}")

    # Create DB session
    session = create_db_session(config)

    try:
        # Run analysis
        result = run_regime_analysis(config, session, verbose=verbose)

        if result is None:
            print("\nERROR: Analysis failed")
            return 1

        score, phase_transition, dist_data = result

        # Send alerts
        if not args.phase_only:
            send_discord_alert(config, score, dry_run=dry_run, verbose=verbose)

        if not args.regime_only:
            send_phase_change_alert(
                config, phase_transition, dist_data,
                dry_run=dry_run, verbose=verbose
            )

        print("\n" + "="*60)
        print("TEST COMPLETE")
        print("="*60)

        if dry_run:
            print("\nTo actually send alerts, run with --send flag:")
            print("  python test_regime_alert.py --send")

        return 0

    except Exception as e:
        print(f"\nERROR: {e}")
        logging.exception("Test failed")
        return 1

    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
