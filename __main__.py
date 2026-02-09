"""
CANSLIM Monitor - Main Launcher
Entry point for the CANSLIM Position Manager application.

Usage:
    python -m canslim_monitor gui                    # Launch Kanban GUI
    python -m canslim_monitor import <file>          # Import from Excel
    python -m canslim_monitor service                # Run monitoring service
    python -m canslim_monitor demo                   # Run demo
    python -m canslim_monitor earnings               # Update earnings dates
    python -m canslim_monitor regime status          # Show regime status
    python -m canslim_monitor regime seed --start 2024-01-01  # Seed historical data
    python -m canslim_monitor test_position          # Test position monitor
    python -m canslim_monitor test_position --live   # Live validation
"""

import sys
import argparse
import logging
from pathlib import Path


# Default paths
DEFAULT_DB_PATH = 'canslim_positions.db'


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )


def cmd_gui(args):
    """Launch the Kanban GUI."""
    from canslim_monitor.data.database import init_database
    from canslim_monitor.gui import launch_gui
    from canslim_monitor.utils.config import load_config
    
    # Load config first (so we can get database path from it if not specified)
    config_path = args.config
    if config_path:
        print(f"Loading config from: {config_path}")
    config = load_config(config_path)
    
    # Database path: CLI arg > config file > default
    db_path = args.database or config.get('database', {}).get('path') or DEFAULT_DB_PATH
    
    # Initialize database if needed
    if not Path(db_path).exists():
        print(f"Creating new database: {db_path}")
        init_database(db_path)
    
    print(f"Launching GUI with database: {db_path}")
    launch_gui(db_path)


def cmd_import(args):
    """Import from Excel file."""
    from canslim_monitor.data.database import init_database
    from canslim_monitor.migration.excel_importer import ExcelImporter
    
    if not args.file:
        print("Error: Excel file path required")
        print("Usage: python -m canslim_monitor import <excel_file>")
        return 1
    
    excel_path = Path(args.file)
    if not excel_path.exists():
        print(f"Error: File not found: {excel_path}")
        return 1
    
    db_path = args.database or DEFAULT_DB_PATH
    
    print(f"Importing from: {excel_path}")
    print(f"Database: {db_path}")
    
    # Initialize database
    init_database(db_path)
    
    # Run import
    importer = ExcelImporter(str(excel_path), db_path)
    stats = importer.run(clear_existing=args.clear)
    
    print(importer.get_summary())
    return 0


def cmd_service(args):
    """Run the monitoring service or manage it via service_main.py."""
    action = getattr(args, 'action', 'start')
    
    # Map our actions to service_main commands
    action_map = {
        'start': 'start' if getattr(args, 'background', False) else 'run',
        'stop': 'stop',
        'status': 'status',
    }
    
    cmd = action_map.get(action, 'run')
    
    # Build argv for service_main
    import sys
    sys.argv = ['service_main', cmd]
    
    if args.config:
        sys.argv.extend(['-c', args.config])
    if args.database:
        sys.argv.extend(['-d', args.database])
    
    # Import and run service_main
    from canslim_monitor.service.service_main import main as service_main
    return service_main()




def cmd_demo(args):
    """Run the demo."""
    from canslim_monitor.demo import main
    main()


def cmd_earnings(args):
    """Update earnings dates from Polygon/Massive."""
    from canslim_monitor.utils.config import load_config
    from canslim_monitor.data.database import get_database
    # Import directly from file to avoid IBKR/asyncio issues in __init__.py
    from canslim_monitor.integrations.polygon_client import PolygonClient
    from canslim_monitor.services.earnings_service import EarningsService
    
    print("=" * 60)
    print("EARNINGS DATE UPDATE")
    print("=" * 60)
    
    # Load config
    config = load_config(args.config)
    
    # Get Polygon/Massive config
    market_data_config = config.get('market_data', {})
    polygon_config = config.get('polygon', {})
    
    api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
    base_url = market_data_config.get('base_url') or polygon_config.get('base_url', 'https://api.polygon.io')
    
    if not api_key:
        print("❌ No API key configured")
        print("   Add market_data.api_key to user_config.yaml")
        return 1
    
    provider = market_data_config.get('provider', 'polygon')
    if 'massive' in base_url.lower():
        provider = 'massive'
    
    print(f"Provider: {provider}")
    print(f"Base URL: {base_url}")
    
    # Create Polygon client
    polygon_client = PolygonClient(
        api_key=api_key,
        base_url=base_url,
        timeout=market_data_config.get('timeout', 30)
    )
    
    # Test connection
    print("\nTesting API connection...")
    if not polygon_client.test_connection():
        print("❌ API connection failed")
        return 1
    print("✅ API connection successful")
    
    # Get database
    db_path = args.database or config.get('database', {}).get('path')
    db = get_database(db_path=db_path)
    print(f"Database: {db.db_path}")
    
    # Create service
    service = EarningsService(
        session_factory=db.get_new_session,
        polygon_client=polygon_client
    )
    
    # Check upcoming earnings mode
    if args.check:
        print(f"\nUpcoming earnings (next {args.days} days):")
        print("-" * 50)
        upcoming = service.check_upcoming_earnings(days=args.days)
        
        if not upcoming:
            print("No positions with upcoming earnings")
        else:
            print(f"{'Symbol':<8} {'Earnings':<12} {'Days':<6} {'P&L %':<8}")
            print("-" * 40)
            for p in upcoming:
                print(f"{p['symbol']:<8} {str(p['earnings_date']):<12} {p['days_until']:<6} {p['pnl_pct']:+.1f}%")
        return 0
    
    # Single symbol mode
    if args.symbol:
        print(f"\nLooking up earnings for {args.symbol.upper()}...")
        earnings_date = polygon_client.get_next_earnings_date(args.symbol)
        
        if earnings_date:
            print(f"✅ Found: {earnings_date}")
            if service.update_earnings_date(args.symbol, earnings_date):
                print("✅ Database updated")
            else:
                print("⚠️  No active positions found for this symbol")
        else:
            print("❌ No earnings date found")
        return 0
    
    # Update all positions
    print(f"\nUpdating earnings for all active positions...")
    if args.force:
        print("   (Force mode: updating all regardless of existing data)")
    
    results = service.update_all_positions(force=args.force)
    
    print("\n" + "-" * 50)
    print("RESULTS")
    print("-" * 50)
    print(f"Symbols checked: {results['symbols_checked']}")
    print(f"Updated:         {results['updated']}")
    print(f"Skipped:         {results['skipped']}")
    print(f"Not found:       {results['not_found']}")
    print(f"Errors:          {results['errors']}")
    print("=" * 60)
    
    return 0


def cmd_regime(args):
    """Manage market regime data (seed historical data)."""
    action = getattr(args, 'action', 'status')

    if action == 'seed':
        from datetime import datetime, timedelta
        from canslim_monitor.utils.config import load_config

        # Validate dates
        if not args.start:
            print("Error: --start date required for seeding")
            print("Usage: python -m canslim_monitor regime seed --start 2024-01-01")
            return 1

        try:
            start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error: Invalid start date format: {args.start}")
            print("Use YYYY-MM-DD format")
            return 1

        if args.end:
            try:
                end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
            except ValueError:
                print(f"Error: Invalid end date format: {args.end}")
                return 1
        else:
            end_date = datetime.now().date() - timedelta(days=1)

        # Load config
        config = load_config(args.config)

        # Database path
        db_path = args.database or config.get('database', {}).get('path') or DEFAULT_DB_PATH

        print("=" * 60)
        print("HISTORICAL REGIME SEEDING")
        print("=" * 60)
        print(f"Database: {db_path}")
        print(f"Date range: {start_date} to {end_date}")
        if args.clear:
            print("Mode: Clear existing data before seeding")

        # Show D-day tuning parameters
        dist_config = config.get('distribution_days', {})
        print(f"\nD-Day Parameters:")
        print(f"  decline_threshold:        {dist_config.get('decline_threshold', -0.2)}")
        print(f"  min_volume_increase_pct:  {dist_config.get('min_volume_increase_pct', 2.0)}")
        print(f"  decline_rounding_decimals:{dist_config.get('decline_rounding_decimals', 2)}")
        print(f"  enable_stalling:          {dist_config.get('enable_stalling', False)}")
        print()

        # Import and run seeder
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from canslim_monitor.regime.historical_seeder import HistoricalSeeder
        from canslim_monitor.regime.models_regime import Base
        from canslim_monitor.regime.ftd_tracker import Base as FTDBase

        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        FTDBase.metadata.create_all(engine)

        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            seeder = HistoricalSeeder(
                db_session=session,
                config=config,
                use_indices=args.use_indices
            )

            if args.clear:
                print(f"Clearing existing data from {start_date} to {end_date}...")
                deleted = seeder.clear_historical_data(
                    start_date=start_date,
                    end_date=end_date,
                    confirm=True
                )
                print(f"Deleted {deleted} records\n")

            print(f"Seeding regime data...")
            result = seeder.seed_range(start_date, end_date, verbose=True)

            print("\n" + "=" * 60)
            print("SEEDING COMPLETE")
            print("=" * 60)
            print(f"Days processed: {result.days_processed}")
            print(f"Distribution days created: {result.d_days_created}")
            print(f"Regime alerts created: {result.regime_alerts_created}")
            print(f"Phase changes recorded: {result.phase_changes_recorded}")
            print(f"FTDs detected: {result.ftds_detected}")

            if result.errors:
                print(f"\nErrors ({len(result.errors)}):")
                for error in result.errors[:10]:
                    print(f"  - {error}")
                if len(result.errors) > 10:
                    print(f"  ... and {len(result.errors) - 10} more")

            # Backfill CNN Fear & Greed data into seeded regime alerts
            fg_config = config.get('market_regime', {}).get('fear_greed', {})
            if fg_config.get('enabled', True):
                print("\nBackfilling CNN Fear & Greed data...")
                try:
                    from canslim_monitor.regime.fear_greed_client import FearGreedClient, classify_score
                    from canslim_monitor.regime.models_regime import MarketRegimeAlert
                    client = FearGreedClient.from_config(config)
                    days_diff = (end_date - start_date).days + 1
                    history = client.fetch_historical(days=min(days_diff, 365))
                    if history:
                        # Build date->score map (convert datetime to date for matching)
                        fg_map = {}
                        for h in history:
                            d = h.date.date() if hasattr(h.date, 'date') else h.date
                            fg_map[d] = h
                        # Update regime alerts that lack F&G data
                        alerts = session.query(MarketRegimeAlert).filter(
                            MarketRegimeAlert.date >= start_date,
                            MarketRegimeAlert.date <= end_date,
                            MarketRegimeAlert.fear_greed_score.is_(None)
                        ).all()
                        updated = 0
                        for alert in alerts:
                            fg = fg_map.get(alert.date)
                            if not fg:
                                # Try adjacent days (CNN timestamps may shift by 1)
                                fg = fg_map.get(alert.date - timedelta(days=1))
                            if fg:
                                alert.fear_greed_score = fg.score
                                alert.fear_greed_rating = classify_score(fg.score)
                                updated += 1
                        session.commit()
                        print(f"  F&G backfill: {updated} records updated ({len(history)} historical points available)")
                    else:
                        print("  F&G backfill: no historical data returned from API")
                except Exception as e:
                    print(f"  F&G backfill failed (non-critical): {e}")

            return 0 if result.success else 1
        finally:
            session.close()

    elif action == 'status':
        # Show current regime status
        from canslim_monitor.utils.config import load_config
        from canslim_monitor.data.database import get_database

        config = load_config(args.config)
        db_path = args.database or config.get('database', {}).get('path') or DEFAULT_DB_PATH

        print("=" * 60)
        print("MARKET REGIME STATUS")
        print("=" * 60)
        print(f"Database: {db_path}")
        print()

        # Query regime data
        from sqlalchemy import create_engine, func
        from sqlalchemy.orm import sessionmaker
        from canslim_monitor.regime.models_regime import DistributionDay, MarketPhaseHistory

        engine = create_engine(f"sqlite:///{db_path}")
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            # Count distribution days
            d_day_count = session.query(func.count(DistributionDay.id)).scalar() or 0

            # Get date range
            first_d_day = session.query(func.min(DistributionDay.date)).scalar()
            last_d_day = session.query(func.max(DistributionDay.date)).scalar()

            # Count phase history
            phase_count = session.query(func.count(MarketPhaseHistory.id)).scalar() or 0

            print(f"Distribution Days: {d_day_count}")
            if first_d_day and last_d_day:
                print(f"Date Range: {first_d_day} to {last_d_day}")
            print(f"Phase History Records: {phase_count}")

            # Show recent phase
            latest_phase = session.query(MarketPhaseHistory)\
                .order_by(MarketPhaseHistory.phase_date.desc())\
                .first()

            if latest_phase:
                print(f"\nCurrent Phase: {latest_phase.new_phase}")
                print(f"Since: {latest_phase.phase_date}")

            # Show latest regime alert with F&G data
            from canslim_monitor.regime.models_regime import MarketRegimeAlert
            latest_alert = session.query(MarketRegimeAlert)\
                .order_by(MarketRegimeAlert.date.desc())\
                .first()

            if latest_alert:
                print(f"\nLatest Regime Alert: {latest_alert.date}")
                print(f"  Composite Score: {latest_alert.composite_score:+.2f}" if latest_alert.composite_score is not None else "  Composite Score: --")
                print(f"  Regime: {latest_alert.regime.value if latest_alert.regime else '--'}")
                print(f"  D-Days: SPY={latest_alert.spy_d_count or 0}, QQQ={latest_alert.qqq_d_count or 0}")

                if latest_alert.fear_greed_score is not None:
                    print(f"\n  CNN Fear & Greed:")
                    print(f"    Score: {latest_alert.fear_greed_score:.1f} — {latest_alert.fear_greed_rating or 'N/A'}")
                    if latest_alert.fear_greed_previous is not None:
                        delta = latest_alert.fear_greed_score - latest_alert.fear_greed_previous
                        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
                        print(f"    Previous: {latest_alert.fear_greed_previous:.0f} ({arrow} {abs(delta):.0f})")
                else:
                    print(f"\n  CNN Fear & Greed: Not available")
                    print(f"    Run 'python -m cli.fear_greed_cli seed' to backfill")

            return 0
        finally:
            session.close()

    else:
        print(f"Unknown action: {action}")
        return 1


def cmd_test_position(args):
    """Run position monitor tests."""
    from canslim_monitor.tests.test_position_monitor_cli import (
        PositionMonitor, PositionContext, LevelCalculator,
        create_test_scenarios, run_all_scenarios, run_interactive,
        test_level_calculator, print_header, TEST_CONFIG,
        run_live_validation
    )
    
    # Test level calculator only
    if args.levels:
        test_level_calculator()
        return 0
    
    # Live validation mode
    if args.live:
        return run_live_validation(
            use_ibkr=args.ibkr,
            symbol_filter=args.symbol,
            verbose=args.verbose,
            send_discord=args.discord
        )
    
    # Create monitor
    monitor = PositionMonitor(config=TEST_CONFIG)
    
    # Interactive mode
    if args.interactive:
        run_interactive(monitor)
        return 0
    
    # Get scenarios
    scenarios = create_test_scenarios()
    
    # Filter by scenario type
    if args.scenario:
        filter_key = args.scenario.lower()
        scenarios = {
            k: v for k, v in scenarios.items()
            if filter_key in k.lower()
        }
        if not scenarios:
            print(f"No scenarios matching '{args.scenario}'")
            return 1
    
    # Run tests
    failures = run_all_scenarios(monitor, scenarios)
    
    return 1 if failures > 0 else 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='CANSLIM Position Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  gui            Launch the Kanban GUI
  import         Import positions from Excel
  service        Run the monitoring service
  earnings       Update earnings dates from Polygon/Massive
  regime         Manage market regime data (seed historical)
  test_position  Test the position monitor
  demo           Run the demo

Examples:
  python -m canslim_monitor gui
  python -m canslim_monitor gui -c user_config.yaml
  python -m canslim_monitor import positions.xlsx
  python -m canslim_monitor import positions.xlsx --clear
  python -m canslim_monitor service
  python -m canslim_monitor -c my_config.yaml service

  # Earnings management
  python -m canslim_monitor earnings                 # Update all
  python -m canslim_monitor earnings --check         # Show upcoming
  python -m canslim_monitor earnings --symbol NVDA   # Single symbol

  # Market regime management
  python -m canslim_monitor regime                   # Show status
  python -m canslim_monitor regime status            # Show status
  python -m canslim_monitor regime seed --start 2024-01-01  # Seed from date
  python -m canslim_monitor regime seed --start 2024-01-01 --end 2024-12-31
  python -m canslim_monitor regime seed --start 2024-01-01 --clear  # Replace data

  # Position monitor testing
  python -m canslim_monitor test_position              # Run test scenarios
  python -m canslim_monitor test_position -i           # Interactive mode
  python -m canslim_monitor test_position -s stop      # Test stop scenarios
  python -m canslim_monitor test_position --live       # Validate real positions
  python -m canslim_monitor test_position --live --ibkr  # With live prices

Config search order:
  1. -c <path> (command line)
  2. canslim_monitor/user_config.yaml
  3. canslim_monitor/config/config.yaml
        """
    )
    
    parser.add_argument(
        '-d', '--database',
        help=f'Database path (default: {DEFAULT_DB_PATH})'
    )
    parser.add_argument(
        '-c', '--config',
        help='Path to config YAML file (default: user_config.yaml)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # GUI command
    gui_parser = subparsers.add_parser('gui', help='Launch Kanban GUI')
    
    # Import command
    import_parser = subparsers.add_parser('import', help='Import from Excel')
    import_parser.add_argument('file', help='Excel file to import')
    import_parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear existing positions before import'
    )
    
    # Service command
    service_parser = subparsers.add_parser('service', help='Run monitoring service')
    service_parser.add_argument(
        'action',
        nargs='?',
        default='start',
        choices=['start', 'stop', 'status'],
        help='Service action (default: start)'
    )
    service_parser.add_argument(
        '--background', '-b',
        action='store_true',
        help='Start as Windows Service (background) instead of console'
    )
    
    # Earnings command
    earnings_parser = subparsers.add_parser('earnings', help='Update earnings dates from Polygon/Massive')
    earnings_parser.add_argument('--force', '-f', action='store_true',
                                  help='Force update even if earnings date already set')
    earnings_parser.add_argument('--symbol', '-s', type=str,
                                  help='Update single symbol only')
    earnings_parser.add_argument('--check', action='store_true',
                                  help='Check upcoming earnings (no update)')
    earnings_parser.add_argument('--days', type=int, default=14,
                                  help='Days ahead to check for upcoming earnings')
    
    # Demo command
    demo_parser = subparsers.add_parser('demo', help='Run demo')

    # Regime command
    regime_parser = subparsers.add_parser('regime', help='Manage market regime data')
    regime_parser.add_argument(
        'action',
        nargs='?',
        default='status',
        choices=['seed', 'status'],
        help='Action: seed (load historical data) or status (show current state)'
    )
    regime_parser.add_argument(
        '--start',
        type=str,
        help='Start date for seeding (YYYY-MM-DD)'
    )
    regime_parser.add_argument(
        '--end',
        type=str,
        help='End date for seeding (YYYY-MM-DD), defaults to yesterday'
    )
    regime_parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear existing data in range before seeding'
    )
    regime_parser.add_argument(
        '--use-indices',
        action='store_true',
        help='Use index data (^GSPC, ^IXIC) instead of ETFs (SPY, QQQ)'
    )
    
    # Test Position command
    test_parser = subparsers.add_parser('test_position', help='Test position monitor')
    test_parser.add_argument(
        '-s', '--scenario',
        help='Run specific scenario (stop, profit, pyramid, ma, health)'
    )
    test_parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='Run in interactive mode'
    )
    test_parser.add_argument(
        '-l', '--levels',
        action='store_true',
        help='Test level calculator only'
    )
    test_parser.add_argument(
        '--live',
        action='store_true',
        help='Validate real positions from database'
    )
    test_parser.add_argument(
        '--ibkr',
        action='store_true',
        help='Use live IBKR prices (requires TWS/Gateway)'
    )
    test_parser.add_argument(
        '--symbol',
        help='Filter to specific symbol in live mode'
    )
    test_parser.add_argument(
        '--discord',
        action='store_true',
        help='Actually send alerts to Discord (use with --live)'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    if args.command == 'gui':
        cmd_gui(args)
    elif args.command == 'import':
        sys.exit(cmd_import(args))
    elif args.command == 'service':
        cmd_service(args)
    elif args.command == 'earnings':
        sys.exit(cmd_earnings(args))
    elif args.command == 'demo':
        cmd_demo(args)
    elif args.command == 'regime':
        sys.exit(cmd_regime(args))
    elif args.command == 'test_position':
        sys.exit(cmd_test_position(args))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
