"""
CANSLIM Monitor - Market Regime Thread
Service thread wrapper for the ported Market Regime subsystem.

Integrates the comprehensive regime analysis system with the service framework:
- Distribution day tracking (SPY/QQQ)
- Follow-Through Day detection
- Rally attempt monitoring
- Overnight futures analysis
- Weighted regime scoring
- Discord morning brief

Schedule:
- Morning analysis at 8:30 AM ET (7:30 AM CT)
- Optional intraday updates during market hours

This wraps the ported MarketRegime-MonitorSystem components for service use.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any

from ..service.threads.base_thread import BaseThread

# Import regime components
from .models_regime import (
    RegimeType, DDayTrend, MarketRegimeAlert,
    IBDMarketStatus, EntryRiskLevel, IBDExposureCurrent,
    PhaseChangeType, MarketPhaseHistory,
    create_regime_tables, Base
)
from .distribution_tracker import DistributionDayTracker, CombinedDistributionData
from .ftd_tracker import FollowThroughDayTracker, MarketPhaseStatus, MarketPhase
from .market_regime import (
    MarketRegimeCalculator, DistributionData, OvernightData,
    FTDData, RegimeScore, create_overnight_data,
    calculate_entry_risk_score
)
from .market_phase_manager import MarketPhaseManager
from .historical_data import fetch_spy_qqq_daily, DailyBar
from .discord_regime import DiscordRegimeNotifier

logger = logging.getLogger(__name__)


class RegimeThread(BaseThread):
    """
    Service thread for market regime analysis.
    
    Wraps the ported MarketRegime-MonitorSystem for integration
    with the CANSLIM Monitor Windows service.
    
    Features:
    - Full IBD-style distribution day tracking
    - Follow-Through Day detection with rally attempt monitoring
    - Overnight futures analysis (ES, NQ, YM) when IBKR available
    - Weighted composite scoring with configurable weights
    - Discord morning brief with detailed breakdown
    - Database persistence for historical analysis
    """
    
    DEFAULT_ALERT_TIME = "08:30"  # 8:30 AM ET (7:30 AM CT)
    
    def __init__(
        self,
        shutdown_event,
        poll_interval: int = 300,  # 5 minutes
        db_session_factory=None,
        polygon_client=None,
        ibkr_client=None,
        discord_notifier=None,
        config: Dict[str, Any] = None,
        logger: Optional[logging.Logger] = None,
        # Provider abstraction layer (Phase 6)
        historical_provider=None,
        futures_provider=None,
    ):
        super().__init__(
            name="regime",
            shutdown_event=shutdown_event,
            poll_interval=poll_interval,
            logger=logger or logging.getLogger('canslim.regime')
        )
        
        self.db_session_factory = db_session_factory
        self.polygon_client = polygon_client
        self.ibkr_client = ibkr_client
        self.discord_notifier = discord_notifier
        self.config = config or {}

        # Provider abstraction layer — prefers providers over raw clients
        self.historical_provider = historical_provider
        self.futures_provider = futures_provider
        
        # Parse regime-specific config
        regime_config = self.config.get('market_regime', {})
        self.alert_time = regime_config.get('alert_time', self.DEFAULT_ALERT_TIME)
        self.use_indices = regime_config.get('use_indices', False)
        self.enabled = regime_config.get('enabled', True)
        
        # State tracking
        self._last_analysis_date: Optional[date] = None
        self._last_regime_score: Optional[RegimeScore] = None
        
        # Components (lazy initialized)
        self._distribution_tracker: Optional[DistributionDayTracker] = None
        self._ftd_tracker: Optional[FollowThroughDayTracker] = None
        self._calculator: Optional[MarketRegimeCalculator] = None
        self._discord_regime: Optional[DiscordRegimeNotifier] = None
        self._phase_manager: Optional[MarketPhaseManager] = None

        # Ensure regime tables exist
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Ensure regime database tables exist."""
        if self.db_session_factory:
            try:
                session = self.db_session_factory()
                engine = session.get_bind()
                Base.metadata.create_all(engine)
                session.close()
                self.logger.info("Regime tables verified")
            except Exception as e:
                self.logger.warning(f"Could not verify regime tables: {e}")
    
    def _get_components(self):
        """Lazy initialize components."""
        if not self.db_session_factory:
            return None, None, None, None

        session = self.db_session_factory()

        if self._distribution_tracker is None:
            dist_config = self.config.get('distribution_days', {})
            self._distribution_tracker = DistributionDayTracker(
                db_session=session,
                decline_threshold=dist_config.get('decline_threshold'),
                lookback_days=dist_config.get('lookback_days'),
                rally_expiration_pct=dist_config.get('rally_expiration_pct'),
                trend_comparison_days=dist_config.get('trend_comparison_days'),
                enable_stalling=dist_config.get('enable_stalling', False),
                min_volume_increase_pct=dist_config.get('min_volume_increase_pct'),
                decline_rounding_decimals=dist_config.get('decline_rounding_decimals'),
                use_indices=self.use_indices
            )

        if self._ftd_tracker is None:
            self._ftd_tracker = FollowThroughDayTracker(
                db_session=session,
                ftd_min_gain=self.config.get('ftd_min_gain', 1.25),
                ftd_earliest_day=self.config.get('ftd_earliest_day', 4)
            )

        if self._calculator is None:
            self._calculator = MarketRegimeCalculator(self.config.get('market_regime', {}))

        if self._phase_manager is None:
            phase_config = self.config.get('market_phase', {})
            thresholds = {
                'pressure_min_ddays': phase_config.get('pressure_threshold', 5),
                'correction_min_ddays': phase_config.get('correction_threshold', 7),
                'confirmed_max_ddays': phase_config.get('confirmed_max_ddays', 4),
            }
            self._phase_manager = MarketPhaseManager(
                db_session=session,
                thresholds=thresholds
            )

        return self._distribution_tracker, self._ftd_tracker, self._calculator, self._phase_manager
    
    def _is_in_morning_window(self) -> bool:
        """
        Check if we're in the morning analysis window.
        Returns True if current time is between alert_time and alert_time + 1 hour.
        """
        try:
            import pytz
            et = pytz.timezone('US/Eastern')
            now = datetime.now(et)
            tz_used = "pytz/US/Eastern"
        except ImportError:
            self.logger.warning("pytz not available - using local time (may cause timing issues)")
            now = datetime.now()
            tz_used = "local"

        target_hour, target_minute = map(int, self.alert_time.split(':'))
        current_minutes = now.hour * 60 + now.minute
        target_minutes = target_hour * 60 + target_minute
        window_end_minutes = target_minutes + 60  # 1 hour window after target

        in_window = target_minutes <= current_minutes <= window_end_minutes

        self.logger.debug(
            f"Morning window check: time={now.hour}:{now.minute:02d} ({tz_used}), "
            f"target={self.alert_time}, current_min={current_minutes}, "
            f"target_min={target_minutes}, window_end={window_end_minutes}, "
            f"in_window={in_window}"
        )

        return in_window

    def _should_run(self) -> bool:
        """
        Determine if we should run analysis.

        Primary run: 8 AM ET (configurable)
        Intraday: Optional updates during market hours
        """
        if not self.enabled:
            self.logger.debug("Regime thread disabled via config")
            return False

        try:
            import pytz
            et = pytz.timezone('US/Eastern')
            now = datetime.now(et)
            tz_used = "pytz/US/Eastern"
        except ImportError:
            self.logger.warning("pytz not available - using local time (may cause timing issues)")
            now = datetime.now()
            tz_used = "local"

        # Skip weekends and holidays
        if not self._is_trading_day():
            self.logger.debug(f"Skipping - not a trading day (weekday={now.weekday()})")
            return False

        # Parse alert time
        target_hour, target_minute = map(int, self.alert_time.split(':'))

        # Morning analysis window: from target time to target + 1 hour
        # Must be AT or AFTER the target time, not before
        current_minutes = now.hour * 60 + now.minute
        target_minutes = target_hour * 60 + target_minute
        window_end_minutes = target_minutes + 60  # 1 hour window after target

        if target_minutes <= current_minutes <= window_end_minutes:
            # Only run once per day for morning analysis
            if self._last_analysis_date == now.date():
                self.logger.debug(f"Morning analysis already completed for {now.date()}")
                return False
            self.logger.info(
                f"Morning analysis window active - time={now.hour}:{now.minute:02d} ({tz_used}), "
                f"target={self.alert_time}, will run morning analysis"
            )
            return True

        # During market hours, can run for intraday updates (but NOT morning analysis)
        if 9 <= now.hour <= 16:
            self.logger.debug(f"Market hours - intraday check only (hour={now.hour})")
            return True

        self.logger.debug(
            f"Outside run window - time={now.hour}:{now.minute:02d} ({tz_used}), "
            f"current_min={current_minutes}, target_min={target_minutes}, "
            f"alert_time={self.alert_time}"
        )
        return False
    
    def _do_work(self):
        """Perform regime analysis."""
        try:
            import pytz
            et = pytz.timezone('US/Eastern')
            now = datetime.now(et)
            tz_used = "pytz/US/Eastern"
        except ImportError:
            self.logger.warning("pytz not available in _do_work - using local time")
            now = datetime.now()
            tz_used = "local"

        today = now.date()

        # Morning analysis (runs once per day, ONLY in morning window)
        if self._last_analysis_date != today:
            # CRITICAL: Double-check we're in the morning window before running
            # This prevents analysis from running during market hours if it was missed
            if not self._is_in_morning_window():
                self.logger.info(
                    f"Skipping morning analysis - outside morning window "
                    f"(time={now.hour}:{now.minute:02d} {tz_used}, target={self.alert_time}). "
                    f"Analysis will run tomorrow at {self.alert_time} ET."
                )
                # Mark as done for today to prevent repeated log spam
                self._last_analysis_date = today
                return

            self.logger.info(
                f"Running morning regime analysis at {now.hour}:{now.minute:02d} {tz_used}"
            )
            score = self._run_full_analysis()

            if score:
                self._last_regime_score = score
                self._last_analysis_date = today

                # Send Discord alert
                self._send_discord_alert(score)

            return

        # Intraday - could add lighter weight updates here
        self.logger.debug("Intraday regime check (no action)")
    
    def _run_full_analysis(self) -> Optional[RegimeScore]:
        """
        Run complete regime analysis.

        Steps:
        1. Fetch historical data from Polygon/Massive
        2. Calculate distribution days
        3. Check for Follow-Through Day
        4. Get overnight futures (if IBKR available)
        5. Evaluate market phase transitions
        6. Calculate weighted regime score
        7. Save to database
        """
        dist_tracker, ftd_tracker, calculator, phase_manager = self._get_components()

        if not all([dist_tracker, ftd_tracker, calculator]):
            self.logger.error("Could not initialize regime components")
            return None
        
        try:
            # Step 1: Fetch historical data
            self.logger.info(f"Fetching market data (use_indices={self.use_indices})...")

            spy_bars, qqq_bars = self._fetch_market_bars()

            if not spy_bars or not qqq_bars:
                self.logger.error("Failed to fetch market data")
                return None
            
            self.logger.info(f"Fetched {len(spy_bars)} SPY bars, {len(qqq_bars)} QQQ bars")
            
            # Step 2: Calculate distribution days
            self.logger.info("Calculating distribution days...")
            combined_dist = dist_tracker.get_combined_data(spy_bars, qqq_bars)
            
            self.logger.info(
                f"Distribution: SPY={combined_dist.spy_count}, "
                f"QQQ={combined_dist.qqq_count}, Trend={combined_dist.trend.value}"
            )
            
            # Step 3: Check FTD status
            self.logger.info("Checking Follow-Through Day status...")
            ftd_status = ftd_tracker.get_market_phase_status(
                spy_bars, qqq_bars,
                spy_d_count=combined_dist.spy_count,
                qqq_d_count=combined_dist.qqq_count
            )
            
            self.logger.info(f"Market Phase: {ftd_status.phase.value}")

            # Step 3b: Check for phase transitions using MarketPhaseManager
            phase_transition = None
            if phase_manager:
                phase_transition = phase_manager.update_phase(
                    dist_data=combined_dist,
                    ftd_data=ftd_status
                )

                if phase_transition and phase_transition.phase_changed:
                    self.logger.info(
                        f"Phase transition: {phase_transition.previous_phase.value} -> "
                        f"{phase_transition.current_phase.value} ({phase_transition.change_type.value})"
                    )

                    # Send phase change alert - create MarketPhaseHistory for Discord
                    phase_history = MarketPhaseHistory(
                        phase_date=date.today(),
                        previous_phase=phase_transition.previous_phase.value,
                        new_phase=phase_transition.current_phase.value,
                        change_type=phase_transition.change_type.value,
                        trigger_reason=phase_transition.trigger_reason,
                        spy_dday_count=combined_dist.spy_count,
                        qqq_dday_count=combined_dist.qqq_count,
                        total_dday_count=combined_dist.spy_count + combined_dist.qqq_count,
                        spy_expired_today=getattr(combined_dist, 'spy_expired_today', 0),
                        qqq_expired_today=getattr(combined_dist, 'qqq_expired_today', 0)
                    )
                    self._send_phase_change_alert(phase_history, combined_dist)

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
            
            # Step 4: Get overnight futures (if IBKR available)
            overnight = self._get_overnight_data()
            
            # Step 5: Build distribution data for calculator
            dist_data = DistributionData(
                spy_count=combined_dist.spy_count,
                qqq_count=combined_dist.qqq_count,
                spy_5day_delta=combined_dist.spy_5day_delta,
                qqq_5day_delta=combined_dist.qqq_5day_delta,
                trend=combined_dist.trend,
                spy_dates=combined_dist.spy_dates,
                qqq_dates=combined_dist.qqq_dates
            )
            
            # Get prior regime for trend calculation
            prior_score = self._get_prior_regime()
            
            # Step 6: Calculate regime score
            score = calculator.calculate_regime(
                dist_data, overnight, prior_score, ftd_data=ftd_data
            )
            
            # Step 7: Calculate entry risk (tactical layer)
            entry_risk_score, entry_risk_level = calculate_entry_risk_score(
                overnight, dist_data, ftd_data
            )
            score.entry_risk_score = entry_risk_score
            score.entry_risk_level = entry_risk_level

            # Step 8: Fetch CNN Fear & Greed Index (display only)
            fear_greed_data = self._get_fear_greed_data()
            score.fear_greed_data = fear_greed_data

            # Step 9: Fetch VIX data (display only)
            vix_data = self._get_vix_data()
            if vix_data:
                score.vix_close = vix_data.close
                score.vix_previous_close = vix_data.previous_close

            self.logger.info(
                f"Regime: {score.regime.value} "
                f"(score: {score.composite_score:+.2f}, "
                f"entry_risk: {entry_risk_level.value})"
            )
            
            # Save to database
            self._save_regime_alert(score)
            
            return score
            
        except Exception as e:
            self.logger.error(f"Error in regime analysis: {e}", exc_info=True)
            return None
    
    def _fetch_market_bars(self):
        """Fetch SPY/QQQ daily bars via historical provider (or legacy fallback).

        Returns:
            (spy_bars, qqq_bars) — lists of DailyBar objects.
        """
        # Prefer provider abstraction — uses throttled, health-tracked connection
        if self.historical_provider and self.historical_provider.is_connected():
            try:
                spy_raw = self.historical_provider.get_daily_bars('SPY', days=35)
                qqq_raw = self.historical_provider.get_daily_bars('QQQ', days=35)

                # Convert canonical Bar → DailyBar for regime components
                spy_bars = [
                    DailyBar(date=b.bar_date, open=b.open, high=b.high,
                             low=b.low, close=b.close, volume=b.volume)
                    for b in spy_raw
                ]
                qqq_bars = [
                    DailyBar(date=b.bar_date, open=b.open, high=b.high,
                             low=b.low, close=b.close, volume=b.volume)
                    for b in qqq_raw
                ]
                self.logger.info(
                    f"Fetched via historical provider: {len(spy_bars)} SPY, {len(qqq_bars)} QQQ bars"
                )
                return spy_bars, qqq_bars
            except Exception as e:
                self.logger.warning(f"Historical provider failed: {e}, falling back to legacy fetch")

        # Legacy fallback — creates its own MassiveHistoricalClient from config
        api_config = {
            'polygon': {
                'api_key': self.config.get('market_data', {}).get('api_key') or
                           self.config.get('polygon', {}).get('api_key')
            }
        }
        data = fetch_spy_qqq_daily(
            lookback_days=35,
            config=api_config,
            use_indices=self.use_indices
        )
        return data.get('SPY', []), data.get('QQQ', [])

    def _get_overnight_data(self) -> OvernightData:
        """Get overnight futures data via futures provider (or IBKR fallback)."""
        # Prefer provider abstraction
        if self.futures_provider and self.futures_provider.is_connected():
            try:
                snapshot = self.futures_provider.get_futures_snapshot()
                self.logger.info(
                    f"Overnight futures (provider): ES={snapshot.es_change:+.2f}%, "
                    f"NQ={snapshot.nq_change:+.2f}%, YM={snapshot.ym_change:+.2f}%"
                )
                return create_overnight_data(
                    snapshot.es_change, snapshot.nq_change, snapshot.ym_change
                )
            except Exception as e:
                self.logger.warning(f"Futures provider failed: {e}, falling back to raw client")

        # Legacy fallback — direct IBKR client
        if not self.ibkr_client:
            self.logger.debug("No IBKR client - skipping futures data")
            return create_overnight_data(0.0, 0.0, 0.0)

        if not self.ibkr_client.is_connected():
            self.logger.warning("IBKR not connected - skipping futures data")
            return create_overnight_data(0.0, 0.0, 0.0)

        try:
            from .ibkr_futures import get_futures_snapshot

            es_change, nq_change, ym_change = get_futures_snapshot(self.ibkr_client)

            self.logger.info(f"Overnight futures: ES={es_change:+.2f}%, NQ={nq_change:+.2f}%, YM={ym_change:+.2f}%")

            return create_overnight_data(es_change, nq_change, ym_change)

        except ImportError as e:
            self.logger.warning(f"ibkr_futures module not available: {e}")
            return create_overnight_data(0.0, 0.0, 0.0)
        except Exception as e:
            self.logger.warning(f"Could not get overnight futures: {e}")
            return create_overnight_data(0.0, 0.0, 0.0)
    
    def _get_fear_greed_data(self):
        """Fetch CNN Fear & Greed Index data (non-critical, returns None on failure)."""
        fg_config = self.config.get('market_regime', {}).get('fear_greed', {})
        if not fg_config.get('enabled', True):
            self.logger.debug("CNN Fear & Greed disabled in config")
            return None

        try:
            from .fear_greed_client import FearGreedClient
            client = FearGreedClient.from_config(self.config)
            data = client.fetch_current()
            if data:
                self.logger.info(
                    f"CNN F&G: {data.score:.0f} ({data.rating})"
                    f"{f', prev: {data.previous_close:.0f}' if data.previous_close else ''}"
                )
            return data
        except Exception as e:
            self.logger.warning(f"Could not fetch Fear & Greed data: {e}")
            return None

    def _get_vix_data(self):
        """Fetch VIX data (non-critical, returns None on failure)."""
        vix_config = self.config.get('market_regime', {}).get('vix', {})
        if not vix_config.get('enabled', True):
            self.logger.debug("VIX data disabled in config")
            return None

        try:
            from .vix_client import VixClient
            client = VixClient.from_config(self.config, ibkr_client=self.ibkr_client)
            data = client.fetch_current()
            if data:
                self.logger.info(
                    f"VIX: {data.close:.2f}"
                    f"{f' (prev: {data.previous_close:.2f})' if data.previous_close else ''}"
                )
            return data
        except Exception as e:
            self.logger.warning(f"Could not fetch VIX data: {e}")
            return None

    def _get_prior_regime(self) -> Optional[RegimeScore]:
        """Get the prior day's regime score for trend calculation."""
        if self._last_regime_score:
            return self._last_regime_score
        
        if not self.db_session_factory:
            return None
        
        try:
            session = self.db_session_factory()
            
            prior = session.query(MarketRegimeAlert).filter(
                MarketRegimeAlert.date < date.today()
            ).order_by(MarketRegimeAlert.date.desc()).first()
            
            session.close()
            
            if prior:
                # Reconstruct a minimal RegimeScore for comparison
                from .models_regime import TrendType
                
                dist = DistributionData(
                    spy_count=prior.spy_d_count,
                    qqq_count=prior.qqq_d_count,
                    spy_5day_delta=prior.spy_5day_delta or 0,
                    qqq_5day_delta=prior.qqq_5day_delta or 0,
                    trend=prior.d_day_trend or DDayTrend.STABLE
                )
                
                overnight = OvernightData(
                    es_change_pct=prior.es_change_pct or 0,
                    es_trend=TrendType.NEUTRAL,
                    nq_change_pct=prior.nq_change_pct or 0,
                    nq_trend=TrendType.NEUTRAL,
                    ym_change_pct=prior.ym_change_pct or 0,
                    ym_trend=TrendType.NEUTRAL
                )
                
                return RegimeScore(
                    composite_score=prior.composite_score,
                    regime=prior.regime,
                    distribution_data=dist,
                    overnight_data=overnight,
                    component_scores={},
                    timestamp=datetime.combine(prior.date, datetime.min.time())
                )
            
        except Exception as e:
            self.logger.warning(f"Could not get prior regime: {e}")
        
        return None
    
    def _get_ibd_exposure(self) -> tuple:
        """
        Get current IBD exposure settings from database.
        
        Returns:
            Tuple of (IBDMarketStatus, exposure_min, exposure_max, updated_at)
            Returns defaults if not set.
        """
        defaults = (IBDMarketStatus.CONFIRMED_UPTREND, 80, 100, None)
        
        if not self.db_session_factory:
            return defaults
        
        try:
            session = self.db_session_factory()
            
            # Check if IBDExposureCurrent table exists and has data
            try:
                current = session.query(IBDExposureCurrent).filter(
                    IBDExposureCurrent.id == 1
                ).first()
                
                if current:
                    self.logger.debug(
                        f"Loaded IBD exposure: {current.market_status.value} "
                        f"{current.exposure_min}-{current.exposure_max}%"
                    )
                    session.close()
                    return (
                        current.market_status,
                        current.exposure_min,
                        current.exposure_max,
                        current.updated_at
                    )
            except Exception as e:
                # Table might not exist yet
                self.logger.debug(f"IBDExposureCurrent table not available: {e}")
            
            session.close()
            
        except Exception as e:
            self.logger.warning(f"Could not get IBD exposure: {e}")
        
        return defaults
    
    def _save_regime_alert(self, score: RegimeScore):
        """Save regime alert to database."""
        if not self.db_session_factory:
            return
        
        try:
            session = self.db_session_factory()
            
            dist = score.distribution_data
            overnight = score.overnight_data
            
            # Format D-day dates
            spy_dates_str = ','.join(d.isoformat() for d in (dist.spy_dates or []))
            qqq_dates_str = ','.join(d.isoformat() for d in (dist.qqq_dates or []))
            
            alert = MarketRegimeAlert(
                date=score.timestamp.date(),
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
                spy_d_score=score.component_scores.get('spy_distribution'),
                qqq_d_score=score.component_scores.get('qqq_distribution'),
                trend_score=score.component_scores.get('distribution_trend'),
                es_score=score.component_scores.get('overnight_es'),
                nq_score=score.component_scores.get('overnight_nq'),
                ym_score=score.component_scores.get('overnight_ym'),
                ftd_adjustment=score.component_scores.get('ftd_adjustment'),
                market_phase=score.market_phase,
                composite_score=score.composite_score,
                regime=score.regime,
                prior_regime=score.prior_regime,
                prior_score=score.prior_score,
                regime_changed=(score.prior_regime != score.regime if score.prior_regime else False)
            )
            
            # FTD data
            if score.ftd_data:
                alert.in_rally_attempt = score.ftd_data.in_rally_attempt
                alert.rally_day = score.ftd_data.rally_day
                alert.has_confirmed_ftd = score.ftd_data.has_confirmed_ftd
                alert.ftd_date = score.ftd_data.spy_ftd_date or score.ftd_data.qqq_ftd_date
                alert.days_since_ftd = score.ftd_data.days_since_ftd
            
            # Entry risk data (tactical layer)
            alert.entry_risk_score = score.entry_risk_score
            alert.entry_risk_level = score.entry_risk_level

            # CNN Fear & Greed data
            if score.fear_greed_data:
                alert.fear_greed_score = score.fear_greed_data.score
                alert.fear_greed_rating = score.fear_greed_data.rating
                alert.fear_greed_previous = score.fear_greed_data.previous_close
                alert.fear_greed_timestamp = score.fear_greed_data.timestamp

            # VIX data
            if score.vix_close is not None:
                alert.vix_close = score.vix_close
                alert.vix_previous_close = score.vix_previous_close

            # Check for existing record
            existing = session.query(MarketRegimeAlert).filter(
                MarketRegimeAlert.date == alert.date
            ).first()
            
            if existing:
                # Preserve auxiliary fields if new alert has None (API may have failed)
                preserve_fields = {
                    'fear_greed_score', 'fear_greed_rating', 'fear_greed_previous', 'fear_greed_timestamp',
                    'vix_close', 'vix_previous_close',
                }
                for key, value in alert.__dict__.items():
                    if not key.startswith('_') and key != 'id':
                        if key in preserve_fields and value is None:
                            continue  # Don't overwrite existing data with None
                        setattr(existing, key, value)
            else:
                session.add(alert)
            
            session.commit()
            session.close()
            
            self.logger.info(f"Saved regime alert for {alert.date}")
            
        except Exception as e:
            self.logger.error(f"Error saving regime alert: {e}")
    
    def _send_discord_alert(self, score: RegimeScore):
        """Send regime alert via Discord."""
        # Try the dedicated regime notifier first
        discord_config = self.config.get('discord', {})
        webhooks = discord_config.get('webhooks', {})
        
        # Look for regime webhook in multiple locations for backwards compatibility
        webhook_url = (
            webhooks.get('regime_webhook_url') or  # discord.webhooks.regime_webhook_url
            webhooks.get('market') or              # discord.webhooks.market (fallback)
            discord_config.get('regime_webhook_url') or  # discord.regime_webhook_url (legacy)
            discord_config.get('webhook_url') or
            discord_config.get('market_webhook')
        )
        
        if webhook_url:
            try:
                if self._discord_regime is None:
                    self._discord_regime = DiscordRegimeNotifier(webhook_url=webhook_url)
                
                # Load IBD exposure from database
                ibd_status, ibd_min, ibd_max, ibd_updated = self._get_ibd_exposure()
                
                success = self._discord_regime.send_regime_alert(
                    score,
                    verbose=True,
                    ibd_status=ibd_status,
                    ibd_exposure_min=ibd_min,
                    ibd_exposure_max=ibd_max,
                    ibd_updated_at=ibd_updated,
                    fear_greed_data=score.fear_greed_data,
                    vix_close=score.vix_close,
                    vix_previous_close=score.vix_previous_close,
                )
                
                if success:
                    self.increment_message_count()
                    self.logger.info("Regime alert sent to Discord")
                    
                    # Update database
                    if self.db_session_factory:
                        session = self.db_session_factory()
                        alert = session.query(MarketRegimeAlert).filter(
                            MarketRegimeAlert.date == score.timestamp.date()
                        ).first()
                        if alert:
                            alert.alert_sent = True
                            alert.alert_sent_at = datetime.now()
                            alert.alert_channel = 'discord'
                            # Also save IBD exposure snapshot
                            alert.ibd_market_status = ibd_status
                            alert.ibd_exposure_min = ibd_min
                            alert.ibd_exposure_max = ibd_max
                            alert.ibd_exposure_updated_at = ibd_updated
                            alert.entry_risk_level = score.entry_risk_level
                            alert.entry_risk_score = score.entry_risk_score
                            session.commit()
                        session.close()
                
                return
                
            except Exception as e:
                self.logger.error(f"Error with regime notifier: {e}")
        
        # Fallback to generic discord notifier
        if self.discord_notifier:
            try:
                message = self._format_simple_alert(score)
                self.discord_notifier.send_message(message, channel='market')
                self.increment_message_count()
                self.logger.info("Regime alert sent via generic notifier")
            except Exception as e:
                self.logger.error(f"Error sending Discord alert: {e}")

    def _send_phase_change_alert(
        self,
        phase_history: MarketPhaseHistory,
        dist_data: CombinedDistributionData = None
    ):
        """Send phase change alert via Discord."""
        discord_config = self.config.get('discord', {})
        webhooks = discord_config.get('webhooks', {})

        # Look for regime webhook
        webhook_url = (
            webhooks.get('regime_webhook_url') or
            webhooks.get('market') or
            discord_config.get('regime_webhook_url') or
            discord_config.get('webhook_url')
        )

        if not webhook_url:
            self.logger.debug("No webhook URL configured for phase change alerts")
            return

        try:
            if self._discord_regime is None:
                self._discord_regime = DiscordRegimeNotifier(webhook_url=webhook_url)

            success = self._discord_regime.send_phase_change_alert(
                phase_history=phase_history,
                dist_data=dist_data
            )

            if success:
                self.increment_message_count()
                self.logger.info(
                    f"Phase change alert sent: {phase_history.previous_phase} -> "
                    f"{phase_history.new_phase}"
                )

        except Exception as e:
            self.logger.error(f"Error sending phase change alert: {e}")

    def _send_ftd_alert(
        self,
        ftd_date: date,
        gain_pct: float,
        volume_pct: float = None,
        from_pressure: bool = False
    ):
        """Send FTD alert via Discord."""
        discord_config = self.config.get('discord', {})
        webhooks = discord_config.get('webhooks', {})

        webhook_url = (
            webhooks.get('regime_webhook_url') or
            webhooks.get('market') or
            discord_config.get('regime_webhook_url') or
            discord_config.get('webhook_url')
        )

        if not webhook_url:
            return

        try:
            if self._discord_regime is None:
                self._discord_regime = DiscordRegimeNotifier(webhook_url=webhook_url)

            success = self._discord_regime.send_ftd_alert(
                ftd_date=ftd_date,
                ftd_gain_pct=gain_pct,
                volume_pct=volume_pct,
                from_pressure=from_pressure
            )

            if success:
                self.increment_message_count()
                self.logger.info(f"FTD alert sent for {ftd_date}")

        except Exception as e:
            self.logger.error(f"Error sending FTD alert: {e}")

    def _format_simple_alert(self, score: RegimeScore) -> str:
        """Format a simple alert for generic Discord notifier."""
        regime_emoji = {
            RegimeType.BULLISH: "🟢",
            RegimeType.NEUTRAL: "🟡",
            RegimeType.BEARISH: "🔴",
        }
        
        emoji = regime_emoji.get(score.regime, "⚪")
        dist = score.distribution_data
        
        min_exp, max_exp = self._calculator.get_exposure_percentage(
            score.regime, dist.total_count, score.market_phase
        ) if self._calculator else (50, 75)
        
        message = f"""
{emoji} **MORNING MARKET REGIME** - {score.timestamp.strftime('%A, %B %d, %Y')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Regime:** {score.regime.value}
**Score:** {score.composite_score:+.2f}
**Market Phase:** {score.market_phase}

📊 **Distribution Days (25-day window)**
• SPY: {dist.spy_count} ({dist.spy_5day_delta:+d} vs 5 days ago)
• QQQ: {dist.qqq_count} ({dist.qqq_5day_delta:+d} vs 5 days ago)
• Trend: {dist.trend.value}

💰 **Suggested Exposure:** {min_exp}-{max_exp}%
"""
        
        if score.ftd_data:
            if score.ftd_data.ftd_today:
                message += "\n🎉 **FOLLOW-THROUGH DAY TODAY!**\n"
            elif score.ftd_data.in_rally_attempt:
                message += f"\n📈 **Rally Attempt:** Day {score.ftd_data.rally_day}\n"
            elif score.ftd_data.ftd_still_valid:
                message += f"\n✅ **FTD Valid** ({score.ftd_data.days_since_ftd} days ago)\n"
        
        return message
    
    # Public API methods
    
    def get_current_regime(self) -> Optional[str]:
        """Get the current market regime."""
        if self._last_regime_score:
            return self._last_regime_score.regime.value
        return None
    
    def get_exposure_recommendation(self) -> tuple:
        """Get recommended exposure range."""
        if self._last_regime_score and self._calculator:
            dist = self._last_regime_score.distribution_data
            return self._calculator.get_exposure_percentage(
                self._last_regime_score.regime,
                dist.total_count,
                self._last_regime_score.market_phase
            )
        return (50, 75)  # Default
    
    def force_analysis(self) -> Optional[RegimeScore]:
        """Force immediate regime analysis (for testing/manual triggers)."""
        return self._run_full_analysis()
