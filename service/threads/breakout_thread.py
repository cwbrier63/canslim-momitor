"""
CANSLIM Monitor - Breakout Thread
================================
Monitors State 0 (watchlist) positions for pivot breakouts.
Generates alerts via Discord with full scoring and position sizing.

Phase 2 Implementation - January 2026
Updated: Card A compact alert format
Updated: Dynamic scoring for consistent grades with GUI
"""

import logging
import json
from typing import Optional, List, Any, Dict
from datetime import datetime, date, time, timedelta
import pytz

from .base_thread import BaseThread
from ...data.models import Position, MarketRegime
from ...services.alert_service import (
    AlertService, AlertType, AlertSubtype, AlertContext
)
from ...utils.scoring_engine import ScoringEngine, ScoringResult
from ...utils.position_sizer import PositionSizer, PositionSizeResult
from ...utils.pivot_status import calculate_pivot_status, PivotAnalysis, format_pivot_status_alert

# Dynamic scoring imports
try:
    from ...utils.scoring import CANSLIMScorer
    DYNAMIC_SCORING_AVAILABLE = True
except ImportError:
    DYNAMIC_SCORING_AVAILABLE = False

try:
    from ...services.volume_service import VolumeService
    VOLUME_SERVICE_AVAILABLE = True
except ImportError:
    VOLUME_SERVICE_AVAILABLE = False

try:
    from ...services.technical_data_service import TechnicalDataService
    TECHNICAL_SERVICE_AVAILABLE = True
except ImportError:
    TECHNICAL_SERVICE_AVAILABLE = False


class BreakoutThread(BaseThread):
    """
    Monitors watchlist positions for breakout conditions.
    
    Scope: State 0 positions only
    Checks:
        - Price vs pivot point
        - Volume vs 50-day average (40%+ for confirmed)
        - Close position in day's range (strong close)
        - Extended beyond 5% buy zone
        - Market exposure level (suppress in correction)
    Actions:
        - Score setup using ScoringEngine
        - Calculate position size using PositionSizer
        - Generate BREAKOUT alerts via AlertService → Discord
        - Log breakout candidates
    
    Volume Thresholds (IBD methodology):
        - CONFIRMED: 1.4x (40% above average) - required for valid breakout
        - APPROACHING/IN_BUY_ZONE: 1.0x (average) - shows interest
        
    Market Regime Suppression:
        - CONFIRMED → SUPPRESSED when market in correction
        - APPROACHING alerts blocked in correction (optional)
    """
    
    # Breakout conditions from TrendSpider V3.6 + IBD methodology
    VOLUME_THRESHOLD_CONFIRMED = 1.4   # 40% above average for confirmed breakout
    VOLUME_THRESHOLD_MINIMUM = 1.0     # At least average volume for any alert
    BUY_ZONE_MAX_PCT = 5.0             # Max % above pivot to still be in buy zone
    APPROACHING_PCT = 1.0              # Within 1% of pivot = approaching
    STRONG_CLOSE_THRESHOLD = 0.5       # Close > midpoint of day's range
    
    def __init__(
        self,
        shutdown_event,
        poll_interval: int = 60,
        db_session_factory=None,
        ibkr_client=None,
        discord_notifier=None,
        config: Dict[str, Any] = None,
        logger: Optional[logging.Logger] = None,
        # Phase 2 dependencies
        scoring_engine: Optional[ScoringEngine] = None,
        position_sizer: Optional[PositionSizer] = None,
        alert_service: Optional[AlertService] = None,
        # Dynamic scoring dependencies
        volume_service: Optional['VolumeService'] = None,
        canslim_scorer: Optional['CANSLIMScorer'] = None,
    ):
        super().__init__(
            name="breakout",
            shutdown_event=shutdown_event,
            poll_interval=poll_interval,
            logger=logger or logging.getLogger('canslim.breakout')
        )
        
        self.db_session_factory = db_session_factory
        self.ibkr_client = ibkr_client
        self.discord_notifier = discord_notifier
        self.config = config or {}
        
        # Phase 2 dependencies
        self.scoring_engine = scoring_engine
        self.position_sizer = position_sizer
        self.alert_service = alert_service
        
        # Dynamic scoring dependencies
        self.volume_service = volume_service
        self.canslim_scorer = canslim_scorer
        
        # Cache for SPY data (for RS Trend calculation)
        self._spy_df_cache = None
        self._spy_df_cache_time: Optional[datetime] = None
        self._spy_cache_duration = timedelta(hours=4)
        
        # Volume thresholds from config - fully configurable per alert type
        # Set to 0 to disable volume requirement for that alert type
        
        # CONFIRMED breakout: IBD standard is 40% above average (1.4x)
        self.volume_threshold_confirmed = self.config.get(
            'volume_threshold_confirmed', self.VOLUME_THRESHOLD_CONFIRMED
        )
        
        # IN_BUY_ZONE: Default 0 to catch all stocks in buy zone regardless of volume
        self.volume_threshold_buy_zone = self.config.get(
            'volume_threshold_buy_zone', 0.0
        )
        
        # APPROACHING: Default 0 to catch all stocks approaching pivot
        self.volume_threshold_approaching = self.config.get(
            'volume_threshold_approaching', 0.0
        )

        # EXTENDED: Default 0 to catch all extended stocks regardless of volume
        self.volume_threshold_extended = self.config.get(
            'volume_threshold_extended', 0.0
        )
        
        # Legacy support: if old thresholds are set, use them
        if 'volume_threshold_minimum' in self.config:
            # Apply legacy minimum to buy_zone and approaching if not explicitly set
            legacy_min = self.config['volume_threshold_minimum']
            if 'volume_threshold_buy_zone' not in self.config:
                self.volume_threshold_buy_zone = legacy_min
            if 'volume_threshold_approaching' not in self.config:
                self.volume_threshold_approaching = legacy_min
        
        if 'volume_threshold' in self.config:
            # Even older legacy support
            legacy = self.config['volume_threshold']
            if 'volume_threshold_buy_zone' not in self.config:
                self.volume_threshold_buy_zone = legacy
            if 'volume_threshold_approaching' not in self.config:
                self.volume_threshold_approaching = legacy
        
        # Buy zone and approaching thresholds
        self.buy_zone_max_pct = self.config.get('buy_zone_max_pct', self.BUY_ZONE_MAX_PCT)
        self.approaching_pct = self.config.get('approaching_pct', self.APPROACHING_PCT)
        
        # Position sizing config
        self.account_value = self.config.get('account_value', 100000)
        self.stop_loss_pct = self.config.get('stop_loss_pct', 7.0)
        
        # Alert filtering options (to reduce noise)
        # max_extended_pct: Filter out EXTENDED alerts beyond this % from pivot
        # Set to 0 to disable extended alerts entirely, or high value (e.g., 100) to allow all
        self.max_extended_pct = self.config.get('max_extended_pct', 7.0)

        # min_avg_volume: Minimum 50-day average volume for alerts (IBD standard is 400K-500K)
        # Set to 0 to disable filter, or 500000 for IBD-compliant liquidity
        self.min_avg_volume = self.config.get('min_avg_volume', 0)

        # min_alert_grade: Only send alerts for setups with this grade or better
        # Valid grades: A, B, C, D, F (A is best) - also handles +/- modifiers
        # Set to 'F' to allow all, 'C' to filter out D and F grades
        self.min_alert_grade = self.config.get('min_alert_grade', 'D').upper()
        
        # Grade ranking for comparison (higher = better)
        # Base grades + modifiers: A+=5.3, A=5, A-=4.7, B+=4.3, B=4, etc.
        self._grade_base_ranks = {'A': 5, 'B': 4, 'C': 3, 'D': 2, 'F': 1}
        
        # Market regime suppression options
        self.suppress_in_correction = self.config.get('suppress_in_correction', True)
        self.suppress_approaching_in_correction = self.config.get(
            'suppress_approaching_in_correction', True
        )
        
        # Cache for market regime
        self._market_regime_cache: Optional[str] = None
        self._market_regime_cache_time: Optional[datetime] = None

        # Initialize TechnicalDataService for MA data
        if TECHNICAL_SERVICE_AVAILABLE:
            # Get Polygon API key from config
            market_data_config = self.config.get('market_data', {})
            polygon_config = self.config.get('polygon', {})
            polygon_key = market_data_config.get('api_key', '') or polygon_config.get('api_key', '')
            self.technical_service = TechnicalDataService(
                polygon_api_key=polygon_key,
                cache_duration_hours=4,
                logger=logging.getLogger('canslim.breakout_technical'),
            )
        else:
            self.technical_service = None
    
    def _should_run(self) -> bool:
        """Only run during market hours."""
        return self._is_market_hours()
    
    def _do_work(self):
        """Check all State 0 positions for breakouts."""
        self.logger.debug("Starting breakout check cycle")
        
        try:
            # Get watchlist positions
            positions = self._get_watchlist_positions()
            
            if not positions:
                self.logger.debug("No State 0 positions to monitor")
                return
            
            self.logger.info(f"Checking {len(positions)} watchlist positions for breakouts")
            
            # Update market regime cache
            self._update_market_regime()
            
            # Check each position
            breakout_count = 0
            positions_to_update = []  # Track positions with updated pivot status
            
            for pos in positions:
                try:
                    result = self._check_position(pos)
                    if result:
                        breakout_count += 1
                    # Track position for pivot status update (only if attributes exist)
                    if hasattr(pos, 'pivot_status') and getattr(pos, 'pivot_status', None):
                        positions_to_update.append({
                            'id': pos.id,
                            'pivot_distance_pct': getattr(pos, 'pivot_distance_pct', None),
                            'pivot_status': getattr(pos, 'pivot_status', None)
                        })
                except Exception as e:
                    self.logger.warning(f"Error checking {pos.symbol}: {e}")
            
            # Save pivot status updates to database
            if positions_to_update:
                self._save_pivot_status_updates(positions_to_update)
            
            if breakout_count > 0:
                self.logger.info(f"Breakout cycle complete: {breakout_count} alerts generated")
            else:
                self.logger.debug("Breakout check cycle complete - no alerts")
            
        except Exception as e:
            self.logger.error(f"Error in breakout cycle: {e}", exc_info=True)
            raise
    
    def _get_watchlist_positions(self) -> List[Position]:
        """Get all State 0 positions from database."""
        if not self.db_session_factory:
            self.logger.warning("No database session factory configured")
            return []
        
        try:
            session = self.db_session_factory()
            try:
                # Query State 0 positions with valid pivots
                positions = (
                    session.query(Position)
                    .filter(Position.state == 0)
                    .filter(Position.pivot.isnot(None))
                    .filter(Position.pivot > 0)
                    .all()
                )
                
                # Detach from session by expunging and loading attributes
                # This allows us to use them after session closes
                for pos in positions:
                    session.expunge(pos)
                
                return positions
                
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error(f"Error fetching watchlist: {e}")
            return []
    
    def _save_pivot_status_updates(self, updates: List[Dict]) -> None:
        """
        Save pivot status updates to database.
        
        Args:
            updates: List of dicts with id, pivot_distance_pct, pivot_status
        """
        if not self.db_session_factory or not updates:
            return
        
        try:
            session = self.db_session_factory()
            try:
                for update in updates:
                    session.query(Position).filter(
                        Position.id == update['id']
                    ).update({
                        'pivot_distance_pct': update['pivot_distance_pct'],
                        'pivot_status': update['pivot_status']
                    })
                session.commit()
                self.logger.debug(f"Updated pivot status for {len(updates)} positions")
            finally:
                session.close()
        except Exception as e:
            self.logger.warning(f"Error saving pivot status updates: {e}")
    
    def _check_position(self, pos: Position) -> Optional[bool]:
        """
        Check a single position for breakout conditions.
        
        Returns True if an alert was generated, None otherwise.
        """
        symbol = pos.symbol
        pivot = pos.pivot
        
        if not symbol or not pivot or pivot <= 0:
            return None
        
        # 1. Get current price and volume data from IBKR
        price_data = self._get_price_data(symbol)
        if not price_data:
            self.logger.debug(f"{symbol}: No price data available")
            return None

        current_price = price_data.get('last', 0)
        if current_price <= 0:
            return None

        volume = price_data.get('volume', 0)
        high = price_data.get('high', current_price)
        low = price_data.get('low', current_price)

        # 2. Get average volume FIRST (needed for validity check)
        avg_volume = getattr(pos, 'avg_volume_50d', None)
        if not avg_volume or avg_volume <= 0:
            avg_volume = price_data.get('avg_volume', 0)
        if not avg_volume or avg_volume <= 0:
            avg_volume = 500000  # Default

        # 1b. Check if IBKR volume seems valid by comparing to expected volume at this time
        # IBKR snapshot mode often returns 0 or garbage values
        volume_available = price_data.get('volume_available', False)

        # Calculate expected volume at this time of day (rough estimate)
        et_tz = pytz.timezone('America/New_York')
        now_et = datetime.now(et_tz)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if now_et > market_open:
            elapsed_minutes = (now_et - market_open).total_seconds() / 60
            day_fraction = min(elapsed_minutes / 390, 1.0)
            expected_volume = avg_volume * day_fraction
        else:
            expected_volume = avg_volume * 0.1  # Pre-market: expect 10%

        # Volume is suspect if it's less than 5% of expected, or below 1000 shares
        volume_seems_invalid = (
            not volume_available or
            volume < 1000 or
            (expected_volume > 10000 and volume < expected_volume * 0.05)
        )

        # Fetch MA data from TechnicalDataService and merge into price_data
        if self.technical_service:
            try:
                tech_data = self.technical_service.get_technical_data(symbol)
                if tech_data:
                    # Use EMA 21 if available, otherwise SMA 21
                    price_data['ma21'] = tech_data.get('ema_21') or tech_data.get('ma_21', 0)
                    price_data['ma50'] = tech_data.get('ma_50', 0)
                    price_data['ma200'] = tech_data.get('ma_200', 0)
            except Exception as e:
                self.logger.debug(f"{symbol}: Could not fetch MA data: {e}")

        if volume_seems_invalid and self.volume_service:
            self.logger.info(f"{symbol}: IBKR volume={volume:,} (expected ~{int(expected_volume):,}), trying Massive...")
            intraday = self._get_intraday_volume_fallback(symbol)
            if intraday and intraday.get('cumulative_volume', 0) > volume:
                volume = intraday.get('cumulative_volume', 0)
                # Also use Massive data for high/low if available
                if intraday.get('high', 0) > 0:
                    high = intraday['high']
                if intraday.get('low', 0) > 0 and intraday.get('low') != float('inf'):
                    low = intraday['low']
                self.logger.info(f"{symbol}: Using Massive volume={volume:,} (bars={intraday.get('bars_count', 0)})")
            else:
                self.logger.debug(f"{symbol}: Massive returned no improvement")
        elif volume_seems_invalid:
            self.logger.warning(f"{symbol}: IBKR volume={volume:,} (suspect), no volume_service")

        # 3. Calculate metrics
        distance_pct = ((current_price - pivot) / pivot) * 100
        
        # Calculate time-adjusted volume ratio (RVOL)
        # This compares current volume to expected volume at this time of day
        volume_ratio = self._calculate_rvol(volume, avg_volume)
        
        # Strong close: price in upper half of day's range
        day_range = high - low
        strong_close = day_range <= 0 or (current_price - low) / day_range >= self.STRONG_CLOSE_THRESHOLD
        
        # 2b. Calculate pivot status for stale pivot tracking
        # Use getattr for pivot_set_date in case column doesn't exist yet
        pivot_set_date = getattr(pos, 'pivot_set_date', None)
        pivot_analysis = calculate_pivot_status(
            current_price=current_price,
            pivot_price=pivot,
            pivot_set_date=pivot_set_date,
            buy_zone_max_pct=self.buy_zone_max_pct,
            extended_threshold_pct=self.buy_zone_max_pct * 3  # 15% if buy zone is 5%
        )
        
        # Update position with current pivot status (will be saved at end of cycle)
        # Only update if the attribute exists on the model
        if hasattr(pos, 'pivot_distance_pct'):
            pos.pivot_distance_pct = distance_pct
        if hasattr(pos, 'pivot_status'):
            pos.pivot_status = pivot_analysis.status
        
        # 3. Determine breakout conditions with tiered volume thresholds
        above_pivot = current_price > pivot
        in_buy_zone = above_pivot and distance_pct <= self.buy_zone_max_pct
        is_extended = distance_pct > self.buy_zone_max_pct
        is_approaching = -self.approaching_pct <= distance_pct <= 0
        
        # Volume checks - configurable per alert type (0 = no volume requirement)
        has_confirmed_volume = volume_ratio >= self.volume_threshold_confirmed  # Default 1.4x
        has_buy_zone_volume = (
            self.volume_threshold_buy_zone <= 0 or  # 0 = no requirement
            volume_ratio >= self.volume_threshold_buy_zone
        )
        has_approaching_volume = (
            self.volume_threshold_approaching <= 0 or  # 0 = no requirement
            volume_ratio >= self.volume_threshold_approaching
        )
        has_extended_volume = (
            self.volume_threshold_extended <= 0 or  # 0 = no requirement
            volume_ratio >= self.volume_threshold_extended
        )
        
        # Market regime check for suppression
        market_in_correction = self._is_market_in_correction()
        
        self.logger.debug(
            f"{symbol}: price=${current_price:.2f}, pivot=${pivot:.2f}, "
            f"dist={distance_pct:+.2f}%, vol={volume_ratio:.1f}x (avg={avg_volume:,}), "
            f"strong_close={strong_close}, pivot_status={pivot_analysis.status}, "
            f"market_correction={market_in_correction}"
        )
        
        # 4. Generate appropriate alert with market regime awareness
        alert_generated = False
        
        # CONFIRMED breakout: above pivot, in buy zone, 40%+ volume, strong close
        if above_pivot and in_buy_zone and has_confirmed_volume and strong_close:
            alert_generated = self._create_breakout_alert(
                pos, price_data, distance_pct, volume_ratio,
                subtype=AlertSubtype.CONFIRMED,
                pivot_analysis=pivot_analysis
            )
        
        # IN_BUY_ZONE: above pivot, in buy zone, meets buy zone volume threshold
        # (weak close or volume below confirmed threshold)
        elif above_pivot and in_buy_zone and has_buy_zone_volume:
            alert_generated = self._create_breakout_alert(
                pos, price_data, distance_pct, volume_ratio,
                subtype=AlertSubtype.IN_BUY_ZONE,
                pivot_analysis=pivot_analysis
            )
        
        # EXTENDED: beyond buy zone, must meet extended volume threshold
        # Filter by max_extended_pct to reduce noise from stocks too far extended
        elif is_extended and has_extended_volume:
            if distance_pct <= self.max_extended_pct:
                alert_generated = self._create_breakout_alert(
                    pos, price_data, distance_pct, volume_ratio,
                    subtype=AlertSubtype.EXTENDED,
                    pivot_analysis=pivot_analysis
                )
            else:
                self.logger.debug(
                    f"{symbol}: EXTENDED alert filtered - {distance_pct:.1f}% > max {self.max_extended_pct}%"
                )
        
        # APPROACHING: near pivot, meets approaching volume threshold
        # Optionally suppress in correction to reduce noise
        elif is_approaching and has_approaching_volume:
            if market_in_correction and self.suppress_approaching_in_correction:
                self.logger.debug(f"{symbol}: APPROACHING suppressed due to market correction")
            else:
                alert_generated = self._create_breakout_alert(
                    pos, price_data, distance_pct, volume_ratio,
                    subtype=AlertSubtype.APPROACHING,
                    pivot_analysis=pivot_analysis
                )
        
        return alert_generated if alert_generated else None
    
    def _create_breakout_alert(
        self,
        pos: Position,
        price_data: Dict,
        distance_pct: float,
        volume_ratio: float,
        subtype: AlertSubtype,
        pivot_analysis: Optional[PivotAnalysis] = None
    ) -> bool:
        """
        Create a breakout alert with full scoring and sizing.

        Returns True if alert was created successfully.
        """
        symbol = pos.symbol
        current_price = price_data.get('last', 0)
        pivot = pos.pivot

        # Filter: Check minimum average volume (IBD liquidity requirement)
        avg_volume = getattr(pos, 'avg_volume_50d', 0) or 0
        if self.min_avg_volume > 0 and avg_volume < self.min_avg_volume:
            self.logger.debug(
                f"{symbol}: Alert filtered - avg volume {avg_volume:,} < min {self.min_avg_volume:,}"
            )
            return False

        # Get market regime for scoring adjustments
        market_regime = self._market_regime_cache or "UNKNOWN"
        
        # Score the setup - prefer dynamic scoring if available
        scoring_result: Optional[ScoringResult] = None
        static_score = 0
        dynamic_score = 0
        grade = ""
        
        # Try dynamic scoring first (matches GUI behavior)
        if self.canslim_scorer and self.volume_service:
            try:
                # Get historical data for the symbol
                daily_df = self.volume_service.get_dataframe(symbol, days=200)
                
                # Get SPY data for RS Trend calculation (cached)
                spy_df = self._get_spy_dataframe()
                
                if daily_df is not None and len(daily_df) >= 50:
                    # Build position data dict
                    position_data = {
                        'symbol': symbol,
                        'pattern': pos.pattern or "Unknown",
                        'base_stage': pos.base_stage or "1",
                        'base_depth': pos.base_depth or 20,
                        'base_length': pos.base_length or 7,
                        'rs_rating': pos.rs_rating,
                        'eps_rating': pos.eps_rating,
                        'comp_rating': pos.comp_rating,
                        'ad_rating': pos.ad_rating,
                        'ud_vol_ratio': pos.ud_vol_ratio,
                        'fund_count': pos.fund_count,
                        'industry_rank': pos.industry_rank,
                    }
                    
                    # Calculate score WITH dynamic factors
                    total_score, grade, details = self.canslim_scorer.calculate_score_with_dynamic(
                        position_data=position_data,
                        daily_df=daily_df,
                        index_df=spy_df,
                        market_regime=market_regime
                    )
                    
                    static_score = details.get('static_score', 0)
                    dynamic_score = details.get('dynamic_score', 0)
                    
                    self.logger.info(
                        f"{symbol}: Dynamic Score - Grade={grade}, "
                        f"Total={total_score} (Static={static_score} + Dynamic={dynamic_score})"
                    )
                    
                    # Create a ScoringResult-like object for compatibility
                    scoring_result = type('ScoringResult', (), {
                        'grade': grade,
                        'final_score': total_score,
                        'static_score': static_score,
                        'dynamic_score': dynamic_score,
                    })()
                else:
                    self.logger.debug(f"{symbol}: Insufficient historical data for dynamic scoring")
                    
            except Exception as e:
                self.logger.warning(f"Error in dynamic scoring for {symbol}: {e}")
        
        # Fallback to static scoring if dynamic scoring not available or failed
        if scoring_result is None and self.scoring_engine:
            try:
                scoring_result = self.scoring_engine.score(
                    pattern=pos.pattern or "Unknown",
                    stage=pos.base_stage or "1",
                    depth_pct=pos.base_depth or 20,
                    length_weeks=pos.base_length or 7,
                    rs_rating=pos.rs_rating
                )
                self.logger.debug(
                    f"{symbol}: Static Score - Grade={scoring_result.grade}, "
                    f"Score={scoring_result.final_score}"
                )
            except Exception as e:
                self.logger.warning(f"Error scoring {symbol}: {e}")
        
        # Filter by minimum grade requirement
        alert_grade = scoring_result.grade if scoring_result else ""
        alert_grade_rank = self._get_grade_rank(alert_grade)
        min_grade_rank = self._get_grade_rank(self.min_alert_grade)
        
        if alert_grade_rank < min_grade_rank:
            self.logger.debug(
                f"{symbol}: Alert filtered - Grade {alert_grade} below minimum {self.min_alert_grade}"
            )
            return False
        
        # Calculate position sizing if we have a position sizer
        sizing_result: Optional[PositionSizeResult] = None
        if self.position_sizer and current_price > 0:
            try:
                stop_price = current_price * (1 - self.stop_loss_pct / 100)
                sizing_result = self.position_sizer.calculate_target_position(
                    account_value=self.account_value,
                    entry_price=current_price,
                    stop_price=stop_price
                )
            except Exception as e:
                self.logger.warning(f"Error calculating position size for {symbol}: {e}")
        
        # Check market regime for suppression
        if subtype == AlertSubtype.CONFIRMED and self._is_market_in_correction():
            subtype = AlertSubtype.SUPPRESSED
            self.logger.info(f"{symbol}: Breakout suppressed due to market correction")
        
        # Build alert context
        context = AlertContext(
            current_price=current_price,
            pivot_price=pivot,
            volume_ratio=volume_ratio,
            grade=scoring_result.grade if scoring_result else (pos.entry_grade or ""),
            score=scoring_result.final_score if scoring_result else (pos.entry_score or 0),
            static_score=scoring_result.static_score if scoring_result else 0,
            dynamic_score=scoring_result.dynamic_score if scoring_result else 0,
            market_regime=market_regime,
            shares_recommended=sizing_result.initial_shares if sizing_result else 0,
            position_value=sizing_result.initial_value if sizing_result else 0,
            ma_50=price_data.get('ma50', 0),
            ma_21=price_data.get('ma21', 0),
            ma_200=price_data.get('ma200', 0),
            state_at_alert=0,  # Watching
        )
        
        # Build compact card message
        message = self._build_breakout_card(
            pos, price_data, distance_pct, volume_ratio, 
            scoring_result, pivot_analysis, subtype, market_regime
        )
        
        # Action is now embedded in the card, but we can still pass it separately
        action = ""  # Action is part of the card now
        
        # Create alert via AlertService
        if self.alert_service:
            alert = self.alert_service.create_alert(
                symbol=symbol,
                alert_type=AlertType.BREAKOUT,
                subtype=subtype,
                context=context,
                position_id=pos.id,
                message=message,
                action=action,
                thread_source="breakout_thread"
            )
            
            if alert:
                self.increment_message_count()
                self.logger.info(
                    f"BREAKOUT ALERT: {symbol} - {subtype.value} "
                    f"(Grade: {context.grade}, Price: ${current_price:.2f})"
                )
                return True
        else:
            # Fallback: direct Discord notification
            self._send_direct_discord_alert(
                pos, price_data, distance_pct, volume_ratio,
                scoring_result, sizing_result, subtype, message, action
            )
            return True
        
        return False
    
    def _build_breakout_card(
        self,
        pos: Position,
        price_data: Dict,
        distance_pct: float,
        volume_ratio: float,
        scoring_result: Optional[ScoringResult],
        pivot_analysis: Optional[PivotAnalysis],
        subtype: AlertSubtype,
        market_regime: str
    ) -> str:
        """
        Build breakout alert as Discord embed with compact description.
        
        Format:
        - Title: Emoji + Alert Type + Symbol
        - Description: 3 compact pipe-separated lines
        - Footer: Market regime + warnings
        - Color: Based on subtype (Green/Red/Yellow/Blue)
        
        Returns JSON string with EMBED: prefix for alert_service to detect.
        """
        symbol = pos.symbol
        current_price = price_data.get('last', 0)
        pivot = pos.pivot
        buy_zone_top = pivot * (1 + self.buy_zone_max_pct / 100)
        
        # Get values with defaults
        grade = scoring_result.grade if scoring_result else "--"
        score = scoring_result.final_score if scoring_result else 0
        rs_rating = pos.rs_rating or "--"
        pattern = pos.pattern or "Unknown"
        stage = pos.base_stage or "?"
        
        # Format stage display
        base_count = getattr(pos, 'base_count', None)
        if base_count and stage:
            stage_display = f"{stage}({base_count})"
        else:
            stage_display = str(stage) if stage else "?"
        
        # Volume display - show RVOL and average volume for validation
        volume_available = price_data.get('volume_available', False)
        raw_volume = price_data.get('volume', 0)
        avg_vol = getattr(pos, 'avg_volume_50d', 0) or 0

        # Format average volume (K for thousands, M for millions)
        def format_volume(vol):
            if vol >= 1_000_000:
                return f"{vol/1_000_000:.1f}M"
            elif vol >= 1_000:
                return f"{vol/1_000:.0f}K"
            else:
                return str(vol)

        avg_vol_str = format_volume(avg_vol) if avg_vol > 0 else "?"

        if not volume_available or raw_volume == 0:
            vol_str = f"N/A | Avg {avg_vol_str}"
        elif volume_ratio < 0.01:
            vol_str = f"0.0x | Avg {avg_vol_str}"
        else:
            vol_str = f"{volume_ratio:.1f}x | Avg {avg_vol_str}"
        
        # Determine color and title based on subtype
        if subtype == AlertSubtype.CONFIRMED:
            color = 0x00FF00  # Green
            title = f"🚀 BREAKOUT: {symbol}"
        elif subtype == AlertSubtype.EXTENDED:
            color = 0xFF0000  # Red
            title = f"⚠️ EXTENDED: {symbol}"
        elif subtype == AlertSubtype.SUPPRESSED:
            color = 0xFF0000  # Red
            title = f"⛔ SUPPRESSED: {symbol}"
        elif subtype == AlertSubtype.IN_BUY_ZONE:
            color = 0xFFFF00  # Yellow
            title = f"✅ BUY ZONE: {symbol}"
        elif subtype == AlertSubtype.APPROACHING:
            color = 0x0099FF  # Blue
            title = f"👀 APPROACHING: {symbol}"
        else:
            color = 0x808080  # Gray
            title = f"📢 ALERT: {symbol}"
        
        # Get MA values for technical context
        ma_21 = price_data.get('ma21', 0)
        ma_50 = price_data.get('ma50', 0)

        # Calculate MA distances
        ema_21_dist = ((current_price - ma_21) / ma_21 * 100) if ma_21 and ma_21 > 0 else None
        ma_50_dist = ((current_price - ma_50) / ma_50 * 100) if ma_50 and ma_50 > 0 else None

        # Format MA distance string
        def format_ma_dist(dist):
            if dist is None:
                return "N/A"
            return f"{dist:+.1f}%"

        # Determine trend based on price vs MAs
        if ma_21 and ma_50 and ma_21 > 0 and ma_50 > 0:
            above_21 = current_price > ma_21
            above_50 = current_price > ma_50
            if above_21 and above_50:
                trend_str = "↗ Uptrend"
            elif not above_21 and not above_50:
                trend_str = "↘ Downtrend"
            else:
                trend_str = "→ Sideways"
        else:
            trend_str = "→ Unknown"

        # Build compact 4-line description
        line1 = f"{grade} ({score}) | RS {rs_rating} | {pattern} {stage_display}"
        line2 = f"${current_price:.2f} ({distance_pct:+.1f}%) | Pivot ${pivot:.2f}"
        line3 = f"Zone: ${pivot:.2f} - ${buy_zone_top:.2f} | Vol {vol_str}"
        line4 = f"21 EMA: {format_ma_dist(ema_21_dist)} | 50 MA: {format_ma_dist(ma_50_dist)}"

        description = f"{line1}\n{line2}\n{line3}\n{line4}\nTrend: {trend_str}"
        
        # Build footer with market regime and warnings
        footer_parts = []
        
        regime_upper = market_regime.upper() if market_regime else "UNKNOWN"
        if regime_upper in ("BEARISH", "CORRECTION", "DOWNTREND"):
            footer_parts.append("🐻 Bearish")
        elif regime_upper in ("BULLISH", "CONFIRMED_UPTREND"):
            footer_parts.append("🐂 Bullish")
        else:
            footer_parts.append(f"➖ {regime_upper.title()}")
        
        # Stale pivot warning - only show if pivot is genuinely old (60+ days)
        # Don't show for unknown dates (999) or recently set pivots
        if pivot_analysis and pivot_analysis.days_since_set and pivot_analysis.days_since_set < 999:
            if pivot_analysis.days_since_set > 90:
                footer_parts.append(f"⚠️ Stale ({pivot_analysis.days_since_set}d)")
            elif pivot_analysis.days_since_set > 60:
                footer_parts.append("⚠️ Stale pivot")
        
        footer_text = " • ".join(footer_parts)
        
        # Build embed
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "footer": {"text": footer_text},
            "timestamp": datetime.utcnow().isoformat(),  # Discord requires UTC timestamps
        }
        
        # Return as JSON string with marker prefix
        return "EMBED:" + json.dumps(embed)
    
    def _build_breakout_message(
        self,
        pos: Position,
        price_data: Dict,
        distance_pct: float,
        volume_ratio: float,
        scoring_result: Optional[ScoringResult],
        pivot_analysis: Optional[PivotAnalysis] = None
    ) -> str:
        """
        Build the main breakout message body.
        
        DEPRECATED: Use _build_breakout_card() instead.
        Kept for backward compatibility with direct Discord alerts.
        """
        symbol = pos.symbol
        current_price = price_data.get('last', 0)
        pivot = pos.pivot
        buy_zone_top = pivot * (1 + self.buy_zone_max_pct / 100)
        
        # Volume confirmation status
        vol_confirmed = volume_ratio >= self.volume_threshold_confirmed
        vol_emoji = "✅" if vol_confirmed else "⚠️"
        vol_status = "CONFIRMED" if vol_confirmed else "BELOW 40%"
        
        lines = [
            f"{symbol} broke out above ${pivot:.2f} pivot",
            "",
            f"Price: ${current_price:.2f} ({distance_pct:+.1f}% from pivot)",
            f"Pivot: ${pivot:.2f} | Buy Zone: ${pivot:.2f} - ${buy_zone_top:.2f}",
            f"Volume: {volume_ratio:.1f}x avg {vol_emoji} ({vol_status})",
        ]
        
        # Add pivot status warning for non-fresh pivots
        if pivot_analysis and pivot_analysis.status != 'FRESH':
            pivot_warning = format_pivot_status_alert(pivot_analysis, include_warning=True)
            if pivot_warning:
                lines.extend(["", pivot_warning])
        
        if scoring_result:
            lines.extend([
                "",
                f"📊 SETUP QUALITY: {scoring_result.grade} (Score: {scoring_result.final_score})",
                f"   Pattern: {pos.pattern or 'Unknown'} | "
                f"Stage {pos.base_stage or '?'} | RS: {pos.rs_rating or 'N/A'}",
            ])
            
            if scoring_result.rs_floor_applied:
                lines.append(f"   ⚠️ RS Floor applied (RS < 70, was {scoring_result.original_grade})")
        
        return "\n".join(lines)
    
    def _build_action_message(
        self,
        pos: Position,
        scoring_result: Optional[ScoringResult],
        sizing_result: Optional[PositionSizeResult],
        subtype: AlertSubtype,
        current_price: float
    ) -> str:
        """Build the action recommendation."""
        if subtype == AlertSubtype.EXTENDED:
            return "⏸️ EXTENDED: Do not chase - wait for pullback to buy zone"
        
        if subtype == AlertSubtype.SUPPRESSED:
            return "⏸️ SUPPRESSED: Market in correction - observe only"
        
        if subtype == AlertSubtype.APPROACHING:
            return "👀 WATCH: Approaching pivot - prepare for breakout"
        
        if subtype == AlertSubtype.IN_BUY_ZONE:
            if sizing_result:
                return (
                    f"⚠️ IN BUY ZONE (weak close)\n"
                    f"   Consider: {sizing_result.initial_shares} shares if close strengthens"
                )
            return "⚠️ IN BUY ZONE: Monitor for stronger close"
        
        # CONFIRMED breakout
        if sizing_result:
            stop_price = current_price * (1 - self.stop_loss_pct / 100)
            return (
                f"▶ ACTION: Buy {sizing_result.initial_shares} shares (50% initial position)\n"
                f"   Target Full Position: {sizing_result.target_shares} shares\n"
                f"   Stop Loss: ${stop_price:.2f} ({self.stop_loss_pct}% risk)"
            )
        
        return "▶ ACTION: Consider entry within buy zone"
    
    def _send_direct_discord_alert(
        self,
        pos: Position,
        price_data: Dict,
        distance_pct: float,
        volume_ratio: float,
        scoring_result: Optional[ScoringResult],
        sizing_result: Optional[PositionSizeResult],
        subtype: AlertSubtype,
        message: str,
        action: str
    ):
        """Fallback: Send alert directly via Discord notifier."""
        if not self.discord_notifier:
            self.logger.warning("No Discord notifier configured")
            return
        
        symbol = pos.symbol
        
        # The message is already the card format, just add timestamp
        full_message = f"{message}\nTime: {datetime.now().strftime('%H:%M:%S ET')}"
        
        try:
            self.discord_notifier.send_message(full_message)
            self.increment_message_count()
            self.logger.info(f"Direct Discord alert sent for {symbol}")
        except Exception as e:
            self.logger.error(f"Failed to send Discord alert: {e}")
    
    def _get_price_data(self, symbol: str) -> Optional[Dict]:
        """Get current price data from IBKR."""
        if not self.ibkr_client:
            return None
        
        try:
            # Try to use the enriched method that includes MAs
            if hasattr(self.ibkr_client, 'get_quote_with_technicals'):
                return self.ibkr_client.get_quote_with_technicals(symbol)
            elif hasattr(self.ibkr_client, 'get_quote'):
                return self.ibkr_client.get_quote(symbol)
            else:
                # Raw IB connection - use reqMktData with thread-safe approach
                from ib_insync import Stock
                
                def safe_float(val, default=0.0):
                    if val is None or (isinstance(val, float) and val != val):
                        return default
                    return float(val)
                
                contract = Stock(symbol, 'SMART', 'USD')
                
                # Use synchronous qualification - ensure we're in IB's event loop context
                # by letting ib_insync handle the async internally via sleep()
                try:
                    # First, give the event loop a chance to process
                    self.ibkr_client.sleep(0)
                    
                    # Qualify the contract - this schedules into the event loop
                    qualified = self.ibkr_client.qualifyContracts(contract)
                    
                    if not qualified or not qualified[0].conId:
                        self.logger.debug(f"{symbol}: Contract qualification failed")
                        return None
                    
                    # Request snapshot data (True = snapshot, no subscription needed)
                    # NOTE: Generic tick types (like '233') are NOT compatible with snapshot mode
                    ticker = self.ibkr_client.reqMktData(contract, '', True, False)
                    
                    # Wait for data to arrive - this processes the event loop
                    self.ibkr_client.sleep(2.0)  # Increased wait time for reliable data
                    
                except Exception as qual_error:
                    self.logger.debug(f"{symbol}: IBKR operation failed: {qual_error}")
                    return None
                
                # Extract price data
                last_price = safe_float(ticker.last) or safe_float(ticker.close)
                if last_price <= 0:
                    # Try bid/ask midpoint as fallback
                    bid = safe_float(ticker.bid)
                    ask = safe_float(ticker.ask)
                    if bid > 0 and ask > 0:
                        last_price = (bid + ask) / 2
                
                if last_price <= 0:
                    self.logger.debug(f"{symbol}: No valid price data received")
                    return None
                
                # Debug logging for volume data
                raw_volume = ticker.volume
                raw_avg_volume = ticker.avVolume
                self.logger.debug(
                    f"{symbol}: IBKR raw data - volume={raw_volume}, avVolume={raw_avg_volume}, "
                    f"last={ticker.last}, close={ticker.close}"
                )
                
                return {
                    'symbol': symbol,
                    'last': last_price,
                    'bid': safe_float(ticker.bid),
                    'ask': safe_float(ticker.ask),
                    'volume': int(safe_float(ticker.volume)),
                    'avg_volume': int(safe_float(ticker.avVolume, 500000)),
                    'high': safe_float(ticker.high),
                    'low': safe_float(ticker.low),
                    'volume_available': ticker.volume is not None and not (isinstance(ticker.volume, float) and ticker.volume != ticker.volume),
                }
                
        except Exception as e:
            self.logger.debug(f"Could not get price data for {symbol}: {e}")
            return None

    def _get_intraday_volume_fallback(self, symbol: str) -> Optional[Dict]:
        """
        Get intraday volume from Massive/Polygon when IBKR returns 0.

        Uses minute aggregates (15-min delayed with Stocks Starter tier).

        Args:
            symbol: Stock symbol

        Returns:
            Dict with cumulative_volume, high, low, etc. or None
        """
        if not self.volume_service:
            self.logger.debug(f"{symbol}: No volume_service available")
            return None

        if not hasattr(self.volume_service, 'polygon_client'):
            self.logger.debug(f"{symbol}: volume_service has no polygon_client attribute")
            return None

        try:
            polygon_client = self.volume_service.polygon_client
            if not polygon_client:
                self.logger.debug(f"{symbol}: polygon_client is None")
                return None

            # Use the new intraday endpoint
            if hasattr(polygon_client, 'get_intraday_volume'):
                result = polygon_client.get_intraday_volume(symbol)
                if result:
                    self.logger.debug(f"{symbol}: Got intraday data: {result.get('cumulative_volume', 0):,} volume")
                return result
            else:
                self.logger.warning(f"{symbol}: polygon_client missing get_intraday_volume method")

        except Exception as e:
            self.logger.error(f"{symbol}: Intraday volume fallback failed: {e}", exc_info=True)

        return None

    def _calculate_rvol(self, current_volume: int, avg_daily_volume: int) -> float:
        """
        Calculate Relative Volume (RVOL) - time-adjusted volume ratio.
        
        Compares current intraday volume to expected volume at this time of day,
        based on the assumption that volume accumulates proportionally throughout
        the trading session.
        
        Args:
            current_volume: Today's volume so far
            avg_daily_volume: 50-day average full-day volume
            
        Returns:
            RVOL ratio (1.0 = normal, >1.0 = above average, <1.0 = below average)
        """
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
        
        # Total trading minutes in a day
        total_trading_minutes = 390  # 6.5 hours * 60
        
        # Calculate elapsed minutes since market open
        if now_et < market_open:
            # Pre-market - use small fraction to avoid division issues
            elapsed_minutes = 1
        elif now_et > market_close:
            # After hours - use full day
            elapsed_minutes = total_trading_minutes
        else:
            # During market hours
            elapsed_minutes = (now_et - market_open).total_seconds() / 60
            elapsed_minutes = max(1, elapsed_minutes)  # Minimum 1 minute
        
        # Calculate what fraction of the day has elapsed
        day_fraction = min(elapsed_minutes / total_trading_minutes, 1.0)
        
        # Expected volume at this time of day
        expected_volume = avg_daily_volume * day_fraction
        
        # Calculate RVOL
        if expected_volume > 0:
            rvol = current_volume / expected_volume
        else:
            rvol = 0.0
        
        return round(rvol, 2)
    
    def _get_grade_rank(self, grade: str) -> float:
        """
        Get numeric rank for a grade, handling +/- modifiers.
        
        Examples:
            A+ -> 5.3, A -> 5.0, A- -> 4.7
            B+ -> 4.3, B -> 4.0, B- -> 3.7
            C+ -> 3.3, C -> 3.0, C- -> 2.7
            D+ -> 2.3, D -> 2.0, D- -> 1.7
            F -> 1.0
            
        Returns:
            Numeric rank (higher = better), 0 if grade not recognized
        """
        if not grade or grade in ('--', ''):
            return 0.0
        
        grade = grade.upper().strip()
        
        # Extract base letter and modifier
        if len(grade) >= 1:
            base_letter = grade[0]
            modifier = grade[1:] if len(grade) > 1 else ''
        else:
            return 0.0
        
        # Get base rank
        base_rank = self._grade_base_ranks.get(base_letter, 0)
        if base_rank == 0:
            return 0.0
        
        # Apply modifier
        if modifier == '+':
            return base_rank + 0.3
        elif modifier == '-':
            return base_rank - 0.3
        else:
            return float(base_rank)
    
    def _get_spy_dataframe(self) -> Optional['pd.DataFrame']:
        """
        Get SPY historical data for RS Trend calculation.
        Caches result for 4 hours to minimize database queries.
        
        Returns:
            DataFrame with SPY OHLCV data, or None if unavailable
        """
        # Check cache validity
        if (self._spy_df_cache is not None and 
            self._spy_df_cache_time and
            (datetime.now() - self._spy_df_cache_time) < self._spy_cache_duration):
            return self._spy_df_cache
        
        # Fetch fresh SPY data
        if self.volume_service:
            try:
                self._spy_df_cache = self.volume_service.get_dataframe('SPY', days=200)
                self._spy_df_cache_time = datetime.now()
                
                if self._spy_df_cache is not None:
                    self.logger.debug(f"Cached SPY data: {len(self._spy_df_cache)} bars")
                    
            except Exception as e:
                self.logger.warning(f"Could not fetch SPY data for RS Trend: {e}")
                self._spy_df_cache = None
        
        return self._spy_df_cache
    
    def _update_market_regime(self):
        """Update cached market regime from database."""
        # Cache for 5 minutes
        if (self._market_regime_cache_time and
            (datetime.now() - self._market_regime_cache_time).total_seconds() < 300):
            return

        if not self.db_session_factory:
            return

        try:
            session = self.db_session_factory()
            try:
                # Use MarketRegimeAlert (same as position_thread) for consistency
                from canslim_monitor.regime.models_regime import MarketRegimeAlert
                from sqlalchemy import desc

                # Get most recent regime alert
                latest = (
                    session.query(MarketRegimeAlert)
                    .order_by(desc(MarketRegimeAlert.date))
                    .first()
                )

                if latest and latest.regime:
                    self._market_regime_cache = latest.regime.value
                    self._market_regime_cache_time = datetime.now()
                    self.logger.debug(f"Market regime updated: {latest.regime.value}")

            finally:
                session.close()

        except Exception as e:
            self.logger.warning(f"Could not fetch market regime: {e}")
    
    def _is_market_in_correction(self) -> bool:
        """Check if market is in correction mode."""
        if not self._market_regime_cache:
            return False
        
        regime_upper = self._market_regime_cache.upper()
        return regime_upper in ("CORRECTION", "BEARISH", "DOWNTREND")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get thread statistics including breakout-specific info."""
        stats = super().get_stats()
        stats.update({
            'volume_threshold_confirmed': self.volume_threshold_confirmed,
            'volume_threshold_buy_zone': self.volume_threshold_buy_zone,
            'volume_threshold_approaching': self.volume_threshold_approaching,
            'volume_threshold_extended': self.volume_threshold_extended,
            'buy_zone_max_pct': self.buy_zone_max_pct,
            'market_regime': self._market_regime_cache,
            'suppress_in_correction': self.suppress_in_correction,
            'has_scoring_engine': self.scoring_engine is not None,
            'has_position_sizer': self.position_sizer is not None,
            'has_alert_service': self.alert_service is not None,
            'has_volume_service': self.volume_service is not None,
        })
        return stats
