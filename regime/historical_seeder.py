"""
Historical Seeder for Market Regime Data

Seeds the database with historical market regime data as if the regime
system had been running on past days. Useful for:
- Initial database population
- Backtesting regime accuracy
- Analyzing historical market phases

Usage:
    python -m regime.historical_seeder --start 2024-01-01 --end 2024-12-31

    # Or programmatically:
    from regime.historical_seeder import HistoricalSeeder

    seeder = HistoricalSeeder(db_session, config)
    seeder.seed_range(start_date, end_date)
"""

import logging
import argparse
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)


@dataclass
class SeedResult:
    """Result of seeding operation."""
    start_date: date
    end_date: date
    days_processed: int
    d_days_created: int
    regime_alerts_created: int
    phase_changes_recorded: int
    ftds_detected: int
    errors: List[str]

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class HistoricalSeeder:
    """
    Seeds historical market regime data into the database.

    Processes each trading day sequentially, calculating:
    - Distribution days for SPY and QQQ
    - Follow-Through Day signals
    - Market phase transitions
    - Regime scores and alerts
    """

    def __init__(
        self,
        db_session: Session,
        config: Dict = None,
        polygon_api_key: str = None,
        use_indices: bool = False
    ):
        """
        Initialize the seeder.

        Args:
            db_session: SQLAlchemy session
            config: Configuration dict
            polygon_api_key: Polygon.io API key (optional)
            use_indices: Use index data instead of ETFs
        """
        self.db = db_session
        self.config = config or {}
        self.polygon_api_key = polygon_api_key
        self.use_indices = use_indices

        # Lazy-loaded components
        self._dist_tracker = None
        self._ftd_tracker = None
        self._phase_manager = None
        self._calculator = None

    def reset_components(self):
        """Reset cached components to force re-initialization."""
        self._dist_tracker = None
        self._ftd_tracker = None
        self._phase_manager = None
        self._calculator = None
        logger.info("Seeder components reset")

    def _get_components(self):
        """Initialize regime components."""
        from .distribution_tracker import DistributionDayTracker
        from .ftd_tracker import FollowThroughDayTracker
        from .market_phase_manager import MarketPhaseManager
        from .market_regime import MarketRegimeCalculator

        dist_config = self.config.get('distribution_days', {})

        if self._dist_tracker is None:
            self._dist_tracker = DistributionDayTracker(
                db_session=self.db,
                decline_threshold=dist_config.get('decline_threshold'),
                lookback_days=dist_config.get('lookback_days', 25),
                rally_expiration_pct=dist_config.get('rally_expiration_pct', 5.0),
                min_volume_increase_pct=dist_config.get('min_volume_increase_pct'),
                decline_rounding_decimals=dist_config.get('decline_rounding_decimals'),
                enable_stalling=dist_config.get('enable_stalling'),
                use_indices=self.use_indices
            )

        if self._ftd_tracker is None:
            self._ftd_tracker = FollowThroughDayTracker(
                db_session=self.db,
                ftd_min_gain=self.config.get('ftd_min_gain', 1.25),
                ftd_earliest_day=self.config.get('ftd_earliest_day', 4)
            )

        if self._phase_manager is None:
            phase_config = self.config.get('market_phase', {})
            thresholds = {
                'pressure_min_ddays': phase_config.get('pressure_threshold', 5),
                'correction_min_ddays': phase_config.get('correction_threshold', 7),
                'confirmed_max_ddays': phase_config.get('confirmed_max_ddays', 4),
            }
            self._phase_manager = MarketPhaseManager(
                db_session=self.db,
                thresholds=thresholds
            )

        if self._calculator is None:
            self._calculator = MarketRegimeCalculator(
                self.config.get('market_regime', {})
            )

        return self._dist_tracker, self._ftd_tracker, self._phase_manager, self._calculator

    def _fetch_historical_data(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, List]:
        """
        Fetch historical daily bars for SPY and QQQ.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dict with 'SPY' and 'QQQ' lists of DailyBar
        """
        from .historical_data import fetch_spy_qqq_daily, DailyBar

        # Calculate lookback to ensure we have enough history
        # Need at least 35 days before start_date for calculations
        lookback_start = start_date - timedelta(days=60)
        total_days = (end_date - lookback_start).days + 1

        logger.info(f"Fetching {total_days} days of historical data...")

        api_config = {
            'polygon': {
                'api_key': self.polygon_api_key or
                          self.config.get('market_data', {}).get('api_key') or
                          self.config.get('polygon', {}).get('api_key')
            }
        }

        data = fetch_spy_qqq_daily(
            lookback_days=total_days,
            config=api_config,
            use_indices=self.use_indices,
            end_date=end_date
        )

        return data

    def _get_trading_days(
        self,
        spy_bars: List,
        start_date: date,
        end_date: date
    ) -> List[date]:
        """
        Get list of trading days in range from actual market data.

        Args:
            spy_bars: List of SPY DailyBar objects
            start_date: Start of range
            end_date: End of range

        Returns:
            List of trading dates
        """
        trading_days = []
        for bar in spy_bars:
            bar_date = bar.date
            if isinstance(bar_date, datetime):
                bar_date = bar_date.date()
            if start_date <= bar_date <= end_date:
                trading_days.append(bar_date)

        return sorted(trading_days)

    def _get_bars_through_date(
        self,
        all_bars: List,
        through_date: date,
        lookback: int = 35
    ) -> List:
        """
        Get bars up to and including a specific date.

        Args:
            all_bars: All historical bars
            through_date: Date to include up to
            lookback: Number of days to include before

        Returns:
            List of bars ending on through_date
        """
        result = []
        for bar in all_bars:
            bar_date = bar.date
            if isinstance(bar_date, datetime):
                bar_date = bar_date.date()
            if bar_date <= through_date:
                result.append(bar)

        # Return only the last `lookback` days
        return result[-lookback:] if len(result) > lookback else result

    def seed_range(
        self,
        start_date: date,
        end_date: date,
        verbose: bool = True
    ) -> SeedResult:
        """
        Seed historical regime data for a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            verbose: Print progress updates

        Returns:
            SeedResult with statistics
        """
        from .models_regime import (
            MarketRegimeAlert, DistributionDay, DDayTrend,
            PhaseChangeType
        )
        from .market_regime import (
            DistributionData, OvernightData, FTDData,
            create_overnight_data, calculate_entry_risk_score
        )

        result = SeedResult(
            start_date=start_date,
            end_date=end_date,
            days_processed=0,
            d_days_created=0,
            regime_alerts_created=0,
            phase_changes_recorded=0,
            ftds_detected=0,
            errors=[]
        )

        # Reset and get fresh components
        self.reset_components()
        dist_tracker, ftd_tracker, phase_manager, calculator = self._get_components()

        # Force phase manager to start from CORRECTION for clean historical seeding
        # This ensures we detect all phase transitions from scratch
        from .ftd_tracker import MarketPhase
        phase_manager._current_phase = MarketPhase.CORRECTION
        phase_manager._phase_start_date = None
        logger.info("Phase manager reset to CORRECTION for historical seeding")

        # Fetch all historical data
        if verbose:
            print(f"Fetching historical data from {start_date} to {end_date}...")

        try:
            all_data = self._fetch_historical_data(start_date, end_date)
            spy_bars_all = all_data.get('SPY', [])
            qqq_bars_all = all_data.get('QQQ', [])

            if not spy_bars_all or not qqq_bars_all:
                result.errors.append("Failed to fetch historical data")
                return result

            if verbose:
                print(f"Fetched {len(spy_bars_all)} SPY bars, {len(qqq_bars_all)} QQQ bars")

        except Exception as e:
            result.errors.append(f"Data fetch error: {e}")
            return result

        # Get trading days in range
        trading_days = self._get_trading_days(spy_bars_all, start_date, end_date)

        if verbose:
            print(f"Processing {len(trading_days)} trading days...")

        prior_score = None

        for i, current_date in enumerate(trading_days):
            try:
                # Get bars up to this date
                spy_bars = self._get_bars_through_date(spy_bars_all, current_date)
                qqq_bars = self._get_bars_through_date(qqq_bars_all, current_date)

                if len(spy_bars) < 5 or len(qqq_bars) < 5:
                    if verbose:
                        print(f"  {current_date}: Skipping - insufficient data")
                    continue

                # Calculate distribution days (also creates/updates D-day records)
                combined_dist = dist_tracker.get_combined_data(
                    spy_bars, qqq_bars, current_date=current_date
                )

                # Track new D-days created
                result.d_days_created += combined_dist.total_new_d_days

                # Check FTD status
                ftd_status = ftd_tracker.get_market_phase_status(
                    spy_bars, qqq_bars,
                    spy_d_count=combined_dist.spy_count,
                    qqq_d_count=combined_dist.qqq_count
                )

                if ftd_status.any_ftd_today:
                    result.ftds_detected += 1

                # Check phase transitions
                phase_transition = phase_manager.update_phase(
                    dist_data=combined_dist,
                    ftd_data=ftd_status,
                    current_date=current_date
                )

                if phase_transition and phase_transition.phase_changed:
                    result.phase_changes_recorded += 1

                # Build FTD data
                trading_day_list = [bar.date for bar in spy_bars]
                rally_histogram = ftd_tracker.build_rally_histogram(trading_day_list)

                ftd_data = FTDData(
                    market_phase=ftd_status.phase.value,
                    in_rally_attempt=(ftd_status.spy_status.in_rally_attempt or
                                     ftd_status.qqq_status.in_rally_attempt),
                    rally_day=max(ftd_status.spy_status.rally_day,
                                 ftd_status.qqq_status.rally_day),
                    has_confirmed_ftd=(ftd_status.spy_status.has_confirmed_ftd or
                                      ftd_status.qqq_status.has_confirmed_ftd),
                    ftd_still_valid=(ftd_status.spy_status.ftd_still_valid or
                                    ftd_status.qqq_status.ftd_still_valid),
                    days_since_ftd=ftd_status.days_since_last_ftd,
                    ftd_today=ftd_status.any_ftd_today,
                    rally_failed_today=ftd_status.any_rally_failed,
                    ftd_score_adjustment=ftd_status.ftd_score_adjustment,
                    rally_histogram=rally_histogram
                )

                # Build distribution data
                dist_data = DistributionData(
                    spy_count=combined_dist.spy_count,
                    qqq_count=combined_dist.qqq_count,
                    spy_5day_delta=combined_dist.spy_5day_delta,
                    qqq_5day_delta=combined_dist.qqq_5day_delta,
                    trend=combined_dist.trend,
                    spy_dates=combined_dist.spy_dates,
                    qqq_dates=combined_dist.qqq_dates
                )

                # Use neutral overnight data for historical
                overnight = create_overnight_data(0.0, 0.0, 0.0)

                # Calculate regime score
                score = calculator.calculate_regime(
                    dist_data, overnight, prior_score, ftd_data=ftd_data
                )

                # Set timestamp to the date being processed
                score.timestamp = datetime.combine(current_date, datetime.min.time())

                # Calculate entry risk
                entry_risk_score, entry_risk_level = calculate_entry_risk_score(
                    overnight, dist_data, ftd_data
                )
                score.entry_risk_score = entry_risk_score
                score.entry_risk_level = entry_risk_level

                # Save to database
                self._save_regime_alert(score, current_date)
                result.regime_alerts_created += 1

                # Save market status snapshot
                # Use the phase from phase_manager (tracks transitions correctly)
                self._save_market_status(
                    current_date,
                    phase_manager.current_phase,
                    ftd_status,
                    combined_dist
                )

                # Update prior score for next iteration
                prior_score = score
                result.days_processed += 1

                if verbose and (i + 1) % 10 == 0:
                    print(f"  Processed {i + 1}/{len(trading_days)} days...")

            except Exception as e:
                error_msg = f"Error processing {current_date}: {e}"
                result.errors.append(error_msg)
                logger.error(error_msg, exc_info=True)

        if verbose:
            print(f"\nSeeding complete!")
            print(f"  Days processed: {result.days_processed}")
            print(f"  D-days created: {result.d_days_created}")
            print(f"  Regime alerts: {result.regime_alerts_created}")
            print(f"  Phase changes: {result.phase_changes_recorded}")
            print(f"  FTDs detected: {result.ftds_detected}")
            if result.errors:
                print(f"  Errors: {len(result.errors)}")

        return result

    def _save_regime_alert(self, score, alert_date: date):
        """Save a regime alert to the database."""
        from .models_regime import MarketRegimeAlert

        dist = score.distribution_data
        overnight = score.overnight_data

        # Format D-day dates
        spy_dates_str = ','.join(d.isoformat() for d in (dist.spy_dates or []))
        qqq_dates_str = ','.join(d.isoformat() for d in (dist.qqq_dates or []))

        # Check for existing
        existing = self.db.query(MarketRegimeAlert).filter(
            MarketRegimeAlert.date == alert_date
        ).first()

        if existing:
            # Update existing record
            existing.spy_d_count = dist.spy_count
            existing.qqq_d_count = dist.qqq_count
            existing.spy_5day_delta = dist.spy_5day_delta
            existing.qqq_5day_delta = dist.qqq_5day_delta
            existing.d_day_trend = dist.trend
            existing.spy_d_dates = spy_dates_str
            existing.qqq_d_dates = qqq_dates_str
            existing.es_change_pct = overnight.es_change_pct
            existing.nq_change_pct = overnight.nq_change_pct
            existing.ym_change_pct = overnight.ym_change_pct
            existing.composite_score = score.composite_score
            existing.regime = score.regime
            existing.market_phase = score.market_phase
            existing.prior_regime = score.prior_regime
            existing.prior_score = score.prior_score
            existing.entry_risk_score = score.entry_risk_score
            existing.entry_risk_level = score.entry_risk_level

            if score.ftd_data:
                existing.in_rally_attempt = score.ftd_data.in_rally_attempt
                existing.rally_day = score.ftd_data.rally_day
                existing.has_confirmed_ftd = score.ftd_data.has_confirmed_ftd
                existing.days_since_ftd = score.ftd_data.days_since_ftd
        else:
            # Create new record
            alert = MarketRegimeAlert(
                date=alert_date,
                spy_d_count=dist.spy_count,
                qqq_d_count=dist.qqq_count,
                spy_5day_delta=dist.spy_5day_delta,
                qqq_5day_delta=dist.qqq_5day_delta,
                d_day_trend=dist.trend,
                spy_d_dates=spy_dates_str,
                qqq_d_dates=qqq_dates_str,
                es_change_pct=overnight.es_change_pct,
                nq_change_pct=overnight.nq_change_pct,
                ym_change_pct=overnight.ym_change_pct,
                composite_score=score.composite_score,
                regime=score.regime,
                market_phase=score.market_phase,
                prior_regime=score.prior_regime,
                prior_score=score.prior_score,
                entry_risk_score=score.entry_risk_score,
                entry_risk_level=score.entry_risk_level
            )

            if score.ftd_data:
                alert.in_rally_attempt = score.ftd_data.in_rally_attempt
                alert.rally_day = score.ftd_data.rally_day
                alert.has_confirmed_ftd = score.ftd_data.has_confirmed_ftd
                alert.days_since_ftd = score.ftd_data.days_since_ftd

            self.db.add(alert)

        self.db.commit()

    def _save_market_status(
        self,
        status_date: date,
        phase,  # MarketPhase
        ftd_status,  # MarketPhaseStatus from ftd_tracker
        dist_data  # CombinedDistributionData
    ):
        """
        Save daily market status snapshot for historical tracking.

        Args:
            status_date: Date of the status
            phase: Current market phase
            ftd_status: FTD tracker status
            dist_data: Distribution day data
        """
        from .ftd_tracker import MarketStatus

        # Check for existing
        existing = self.db.query(MarketStatus).filter(
            MarketStatus.date == status_date
        ).first()

        if existing:
            # Update existing
            existing.phase = phase
            existing.in_rally_attempt = (
                ftd_status.spy_status.in_rally_attempt or
                ftd_status.qqq_status.in_rally_attempt
            )
            existing.rally_day = max(
                ftd_status.spy_status.rally_day,
                ftd_status.qqq_status.rally_day
            )
            existing.has_confirmed_ftd = (
                ftd_status.spy_status.has_confirmed_ftd or
                ftd_status.qqq_status.has_confirmed_ftd
            )
            existing.last_ftd_date = (
                ftd_status.spy_status.last_ftd_date or
                ftd_status.qqq_status.last_ftd_date
            )
            existing.days_since_ftd = ftd_status.days_since_last_ftd
            existing.spy_d_count = dist_data.spy_count
            existing.qqq_d_count = dist_data.qqq_count
        else:
            # Create new
            status = MarketStatus(
                date=status_date,
                phase=phase,
                in_rally_attempt=(
                    ftd_status.spy_status.in_rally_attempt or
                    ftd_status.qqq_status.in_rally_attempt
                ),
                rally_day=max(
                    ftd_status.spy_status.rally_day,
                    ftd_status.qqq_status.rally_day
                ),
                has_confirmed_ftd=(
                    ftd_status.spy_status.has_confirmed_ftd or
                    ftd_status.qqq_status.has_confirmed_ftd
                ),
                last_ftd_date=(
                    ftd_status.spy_status.last_ftd_date or
                    ftd_status.qqq_status.last_ftd_date
                ),
                days_since_ftd=ftd_status.days_since_last_ftd,
                spy_d_count=dist_data.spy_count,
                qqq_d_count=dist_data.qqq_count
            )
            self.db.add(status)

        self.db.commit()

    def clear_historical_data(
        self,
        start_date: date = None,
        end_date: date = None,
        confirm: bool = False
    ) -> int:
        """
        Clear historical regime data from database.

        Args:
            start_date: Start of range to clear (None = all)
            end_date: End of range to clear (None = all)
            confirm: Must be True to actually delete

        Returns:
            Number of records deleted
        """
        if not confirm:
            logger.warning("clear_historical_data called without confirm=True")
            return 0

        from .models_regime import (
            MarketRegimeAlert, DistributionDay,
            DistributionDayCount, MarketPhaseHistory
        )
        from .ftd_tracker import RallyAttempt, FollowThroughDay, MarketStatus

        deleted = 0

        tables = [
            MarketRegimeAlert,
            DistributionDay,
            DistributionDayCount,
            MarketPhaseHistory,
            RallyAttempt,
            FollowThroughDay,
            MarketStatus
        ]

        for table in tables:
            try:
                query = self.db.query(table)

                if start_date and hasattr(table, 'date'):
                    query = query.filter(table.date >= start_date)
                if end_date and hasattr(table, 'date'):
                    query = query.filter(table.date <= end_date)

                count = query.delete(synchronize_session=False)
                deleted += count
                logger.info(f"Deleted {count} records from {table.__tablename__}")

            except Exception as e:
                logger.warning(f"Could not clear {table.__tablename__}: {e}")

        self.db.commit()
        return deleted


def main():
    """Command-line interface for historical seeding."""
    parser = argparse.ArgumentParser(
        description="Seed historical market regime data"
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD), defaults to yesterday"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="canslim_monitor.db",
        help="Database path"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Config file path"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Polygon.io API key"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing data in range before seeding"
    )
    parser.add_argument(
        "--use-indices",
        action="store_true",
        help="Use index data instead of ETFs"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=True,
        help="Verbose output"
    )

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        end_date = date.today() - timedelta(days=1)

    # Load config
    config = {}
    if args.config:
        import yaml
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)

    # Set API key
    if args.api_key:
        config.setdefault('polygon', {})['api_key'] = args.api_key

    # Determine database path:
    # 1. Use --db if explicitly provided (not the default)
    # 2. Otherwise use database.path from config
    # 3. Otherwise use the default
    db_path = args.db
    if args.db == "canslim_monitor.db" and config.get('database', {}).get('path'):
        db_path = config['database']['path']
        print(f"Using database from config: {db_path}")

    # Setup logging
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create database session
    from .models_regime import Base
    from .ftd_tracker import Base as FTDBase

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    FTDBase.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    # Create seeder
    seeder = HistoricalSeeder(
        db_session=session,
        config=config,
        polygon_api_key=args.api_key,
        use_indices=args.use_indices
    )

    # Clear if requested
    if args.clear:
        print(f"Clearing existing data from {start_date} to {end_date}...")
        deleted = seeder.clear_historical_data(
            start_date=start_date,
            end_date=end_date,
            confirm=True
        )
        print(f"Deleted {deleted} records")

    # Run seeding
    print(f"\nSeeding regime data from {start_date} to {end_date}...")
    result = seeder.seed_range(start_date, end_date, verbose=args.verbose)

    # Print results
    print("\n" + "="*50)
    print("SEEDING COMPLETE")
    print("="*50)
    print(f"Date range: {result.start_date} to {result.end_date}")
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

    session.close()
    return 0 if result.success else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
