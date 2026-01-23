"""
CANSLIM Monitor - Breakout Thread
================================
Monitors State 0 (watchlist) positions for pivot breakouts.
Generates alerts via Discord with full scoring and position sizing.

Phase 2 Implementation - January 2026
"""

import logging
from typing import Optional, List, Any, Dict
from datetime import datetime, date, time
import pytz

from .base_thread import BaseThread
from ...data.models import Position, MarketRegime
from ...services.alert_service import (
    AlertService, AlertType, AlertSubtype, AlertContext
)
from ...utils.scoring_engine import ScoringEngine, ScoringResult
from ...utils.position_sizer import PositionSizer, PositionSizeResult
from ...utils.pivot_status import calculate_pivot_status, PivotAnalysis, format_pivot_status_alert


class BreakoutThread(BaseThread):
    """
    Monitors watchlist positions for breakout conditions.
    
    Scope: State 0 positions only
    Checks:
        - Price vs pivot point
        - Volume vs 50-day average
        - Close position in day's range (strong close)
        - Extended beyond 5% buy zone
        - Market exposure level
    Actions:
        - Score setup using ScoringEngine
        - Calculate position size using PositionSizer
        - Generate BREAKOUT alerts via AlertService → Discord
        - Log breakout candidates
    """
    
    # Breakout conditions from TrendSpider V3.6
    VOLUME_THRESHOLD_DEFAULT = 1.0      # 100% of average (1.5x for strong)
    BUY_ZONE_MAX_PCT = 5.0              # Max % above pivot to still be in buy zone
    APPROACHING_PCT = 1.0               # Within 1% of pivot = approaching
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
        
        # Configuration from config dict
        self.volume_threshold = self.config.get('volume_threshold', self.VOLUME_THRESHOLD_DEFAULT)
        self.buy_zone_max_pct = self.config.get('buy_zone_max_pct', self.BUY_ZONE_MAX_PCT)
        self.approaching_pct = self.config.get('approaching_pct', self.APPROACHING_PCT)
        self.account_value = self.config.get('account_value', 100000)
        self.stop_loss_pct = self.config.get('stop_loss_pct', 7.0)
        
        # Cache for market regime
        self._market_regime_cache: Optional[str] = None
        self._market_regime_cache_time: Optional[datetime] = None
    
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
        
        # 2. Get average volume - prefer stored 50d avg from Polygon, fallback to IBKR
        avg_volume = getattr(pos, 'avg_volume_50d', None)
        if not avg_volume or avg_volume <= 0:
            # Fallback to IBKR avg_volume (often unreliable)
            avg_volume = price_data.get('avg_volume', 0)
        if not avg_volume or avg_volume <= 0:
            # Last resort: use reasonable default
            avg_volume = 500000
        
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
        
        # 3. Determine breakout condition
        above_pivot = current_price > pivot
        in_buy_zone = above_pivot and distance_pct <= self.buy_zone_max_pct
        is_extended = distance_pct > self.buy_zone_max_pct
        is_approaching = -self.approaching_pct <= distance_pct <= 0
        has_volume = volume_ratio >= self.volume_threshold
        
        self.logger.debug(
            f"{symbol}: price=${current_price:.2f}, pivot=${pivot:.2f}, "
            f"dist={distance_pct:+.2f}%, vol={volume_ratio:.1f}x (avg={avg_volume:,}), "
            f"strong_close={strong_close}, pivot_status={pivot_analysis.status}"
        )
        
        # 4. Generate appropriate alert
        alert_generated = False
        
        if above_pivot and in_buy_zone and has_volume and strong_close:
            # CONFIRMED breakout - full scoring and position sizing
            alert_generated = self._create_breakout_alert(
                pos, price_data, distance_pct, volume_ratio,
                subtype=AlertSubtype.CONFIRMED,
                pivot_analysis=pivot_analysis
            )
        
        elif above_pivot and in_buy_zone and has_volume and not strong_close:
            # Good volume but weak close - still worth noting
            alert_generated = self._create_breakout_alert(
                pos, price_data, distance_pct, volume_ratio,
                subtype=AlertSubtype.IN_BUY_ZONE,
                pivot_analysis=pivot_analysis
            )
        
        elif is_extended:
            # Extended beyond buy zone
            alert_generated = self._create_breakout_alert(
                pos, price_data, distance_pct, volume_ratio,
                subtype=AlertSubtype.EXTENDED,
                pivot_analysis=pivot_analysis
            )
        
        elif is_approaching and has_volume:
            # Approaching pivot with volume building
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
        
        # Score the setup if we have a scoring engine
        scoring_result: Optional[ScoringResult] = None
        if self.scoring_engine:
            try:
                scoring_result = self.scoring_engine.score(
                    pattern=pos.pattern or "Unknown",
                    stage=pos.base_stage or "1",
                    depth_pct=pos.base_depth or 20,
                    length_weeks=pos.base_length or 7,
                    rs_rating=pos.rs_rating
                )
                self.logger.debug(
                    f"{symbol}: Grade={scoring_result.grade}, "
                    f"Score={scoring_result.final_score}"
                )
            except Exception as e:
                self.logger.warning(f"Error scoring {symbol}: {e}")
        
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
        market_regime = self._market_regime_cache or "UNKNOWN"
        if subtype == AlertSubtype.CONFIRMED and self._is_market_in_correction():
            subtype = AlertSubtype.SUPPRESSED
            self.logger.info(f"{symbol}: Breakout suppressed due to market correction")
        
        # Build alert context
        context = AlertContext(
            current_price=current_price,
            pivot_price=pivot,
            volume_ratio=volume_ratio,
            grade=scoring_result.grade if scoring_result else "",
            score=scoring_result.final_score if scoring_result else 0,
            static_score=scoring_result.static_score if scoring_result else 0,
            dynamic_score=scoring_result.dynamic_score if scoring_result else 0,
            market_regime=market_regime,
            shares_recommended=sizing_result.initial_shares if sizing_result else 0,
            position_value=sizing_result.initial_value if sizing_result else 0,
            ma_50=price_data.get('ma50', 0),
            ma_21=price_data.get('ma21', 0),
            state_at_alert=0,  # Watching
        )
        
        # Build message
        message = self._build_breakout_message(
            pos, price_data, distance_pct, volume_ratio, scoring_result, pivot_analysis
        )
        
        # Build action recommendation
        action = self._build_action_message(
            pos, scoring_result, sizing_result, subtype, current_price
        )
        
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
    
    def _build_breakout_message(
        self,
        pos: Position,
        price_data: Dict,
        distance_pct: float,
        volume_ratio: float,
        scoring_result: Optional[ScoringResult],
        pivot_analysis: Optional[PivotAnalysis] = None
    ) -> str:
        """Build the main breakout message body."""
        symbol = pos.symbol
        current_price = price_data.get('last', 0)
        pivot = pos.pivot
        buy_zone_top = pivot * (1 + self.buy_zone_max_pct / 100)
        
        lines = [
            f"{symbol} broke out above ${pivot:.2f} pivot with {volume_ratio:.1f}x average volume",
            "",
            f"Price: ${current_price:.2f} ({distance_pct:+.1f}% from pivot)",
            f"Pivot: ${pivot:.2f} | Buy Zone: ${pivot:.2f} - ${buy_zone_top:.2f}",
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
                f"Stage {pos.base_stage or '?'}`| RS: {pos.rs_rating or 'N/A'}",
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
        current_price = price_data.get('last', 0)
        
        # Build emoji based on subtype
        emoji_map = {
            AlertSubtype.CONFIRMED: "🚀",
            AlertSubtype.SUPPRESSED: "⏸️",
            AlertSubtype.EXTENDED: "⚠️",
            AlertSubtype.APPROACHING: "👀",
            AlertSubtype.IN_BUY_ZONE: "📈",
        }
        emoji = emoji_map.get(subtype, "📢")
        
        full_message = (
            f"{emoji} **{symbol} - BREAKOUT {subtype.value}**\n\n"
            f"{message}\n\n"
            f"{action}\n\n"
            f"Market: {self._market_regime_cache or 'Unknown'}\n"
            f"Time: {datetime.now().strftime('%H:%M:%S ET')}"
        )
        
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
                    ticker = self.ibkr_client.reqMktData(contract, '', True, False)
                    
                    # Wait for data to arrive - this processes the event loop
                    self.ibkr_client.sleep(1.0)
                    
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
                
                return {
                    'symbol': symbol,
                    'last': last_price,
                    'bid': safe_float(ticker.bid),
                    'ask': safe_float(ticker.ask),
                    'volume': int(safe_float(ticker.volume)),
                    'avg_volume': int(safe_float(ticker.avVolume, 500000)),
                    'high': safe_float(ticker.high),
                    'low': safe_float(ticker.low),
                }
                
        except Exception as e:
            self.logger.debug(f"Could not get price data for {symbol}: {e}")
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
                # Get most recent market regime
                regime = (
                    session.query(MarketRegime)
                    .order_by(MarketRegime.regime_date.desc())
                    .first()
                )
                
                if regime:
                    self._market_regime_cache = regime.regime
                    self._market_regime_cache_time = datetime.now()
                    self.logger.debug(f"Market regime updated: {regime.regime}")
                    
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
            'volume_threshold': self.volume_threshold,
            'buy_zone_max_pct': self.buy_zone_max_pct,
            'market_regime': self._market_regime_cache,
            'has_scoring_engine': self.scoring_engine is not None,
            'has_position_sizer': self.position_sizer is not None,
            'has_alert_service': self.alert_service is not None,
        })
        return stats
