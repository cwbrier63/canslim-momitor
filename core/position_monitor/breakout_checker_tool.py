"""
Breakout Checker Tool - Run breakout checks without side effects.

This tool allows running breakout detection against watchlist (State 0) positions
for status checking purposes. It does NOT store alerts in the database
or send Discord notifications - purely for display in the GUI.

Also runs WatchlistAltEntryChecker to detect MA pullback opportunities
on stocks that were previously extended.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
import logging
import pytz

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData
from canslim_monitor.utils.pivot_status import calculate_pivot_status, PivotAnalysis
from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext
from canslim_monitor.core.position_monitor.checkers.watchlist_alt_entry_checker import WatchlistAltEntryChecker


class BreakoutCheckerTool:
    """
    Run breakout checks against a watchlist position without side effects.

    Used by the GUI to show current breakout status without storing alerts
    in the database or sending Discord notifications.
    """

    # Breakout conditions from IBD methodology
    VOLUME_THRESHOLD_CONFIRMED = 1.4   # 40% above average for confirmed breakout
    BUY_ZONE_MAX_PCT = 5.0             # Max % above pivot to still be in buy zone
    APPROACHING_PCT = 1.0              # Within 1% of pivot = approaching
    STRONG_CLOSE_THRESHOLD = 0.5       # Close > midpoint of day's range

    # Severity mapping for display colors
    SEVERITY_MAP = {
        AlertSubtype.CONFIRMED: 'profit',      # Green - valid breakout
        AlertSubtype.SUPPRESSED: 'critical',   # Red - suppressed by market
        AlertSubtype.IN_BUY_ZONE: 'info',      # Blue - in zone but weak
        AlertSubtype.APPROACHING: 'info',      # Blue - near pivot
        AlertSubtype.EXTENDED: 'warning',      # Amber - too far extended
    }

    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        """
        Initialize the breakout checker tool.

        Args:
            config: Configuration dict (from user_config.yaml)
            logger: Logger instance
        """
        self.config = config or {}
        self.logger = logger or logging.getLogger('canslim.breakout_checker_tool')

        # Load thresholds from config with defaults
        self.volume_threshold_confirmed = self.config.get(
            'volume_threshold_confirmed', self.VOLUME_THRESHOLD_CONFIRMED
        )
        self.buy_zone_max_pct = self.config.get('buy_zone_max_pct', self.BUY_ZONE_MAX_PCT)
        self.approaching_pct = self.config.get('approaching_pct', self.APPROACHING_PCT)
        self.max_extended_pct = self.config.get('max_extended_pct', 15.0)

        # Initialize WatchlistAltEntryChecker for MA pullback alerts
        alt_entry_config = self.config.get('alt_entry', {})
        self.alt_entry_checker = WatchlistAltEntryChecker(
            config={'alt_entry': alt_entry_config},
            logger=logging.getLogger('canslim.watchlist_alt_entry_tool')
        )

    def check_position(
        self,
        position: Position,
        current_price: float,
        volume: int = 0,
        avg_volume: int = 0,
        high: float = 0,
        low: float = 0,
        market_regime: str = "",
        technical_data: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run breakout checks against a watchlist position and return alert data.

        Args:
            position: Position ORM model (must be State 0)
            current_price: Real-time price
            volume: Today's volume so far
            avg_volume: 50-day average volume
            high: Today's high
            low: Today's low
            market_regime: Current market regime string
            technical_data: Dict with MA values (ma_21, ma_50, etc.) for alt entry checks

        Returns:
            List of alert dicts ready for display (breakout status + alt entry opportunities)
        """
        if current_price <= 0:
            self.logger.warning(f"Invalid price for {position.symbol}: {current_price}")
            return []

        pivot = position.pivot
        if not pivot or pivot <= 0:
            self.logger.debug(f"{position.symbol}: No valid pivot set")
            return []

        # Use position's stored avg_volume if not provided
        if not avg_volume or avg_volume <= 0:
            avg_volume = getattr(position, 'avg_volume_50d', 0) or 500000

        # Use current price for high/low if not provided
        if high <= 0:
            high = current_price
        if low <= 0:
            low = current_price

        # Calculate metrics
        distance_pct = ((current_price - pivot) / pivot) * 100
        volume_ratio = self._calculate_rvol(volume, avg_volume)

        # Strong close: price in upper half of day's range
        day_range = high - low
        strong_close = day_range <= 0 or (current_price - low) / day_range >= self.STRONG_CLOSE_THRESHOLD

        # Calculate pivot status
        pivot_set_date = getattr(position, 'pivot_set_date', None)
        pivot_analysis = calculate_pivot_status(
            current_price=current_price,
            pivot_price=pivot,
            pivot_set_date=pivot_set_date,
            buy_zone_max_pct=self.buy_zone_max_pct,
            extended_threshold_pct=self.buy_zone_max_pct * 3
        )

        # Determine breakout conditions
        above_pivot = current_price > pivot
        in_buy_zone = above_pivot and distance_pct <= self.buy_zone_max_pct
        is_extended = distance_pct > self.buy_zone_max_pct
        is_approaching = -self.approaching_pct <= distance_pct <= 0
        below_approaching = distance_pct < -self.approaching_pct

        # Volume checks
        has_confirmed_volume = volume_ratio >= self.volume_threshold_confirmed

        # Market regime check
        market_in_correction = self._is_market_in_correction(market_regime)

        self.logger.debug(
            f"{position.symbol}: price=${current_price:.2f}, pivot=${pivot:.2f}, "
            f"dist={distance_pct:+.2f}%, vol={volume_ratio:.1f}x, "
            f"strong_close={strong_close}, market_correction={market_in_correction}"
        )

        alerts = []

        # CONFIRMED breakout: above pivot, in buy zone, 40%+ volume, strong close
        if above_pivot and in_buy_zone and has_confirmed_volume and strong_close:
            subtype = AlertSubtype.SUPPRESSED if market_in_correction else AlertSubtype.CONFIRMED
            alerts.append(self._create_alert(
                position, current_price, distance_pct, volume_ratio,
                subtype, pivot_analysis, market_regime, avg_volume
            ))

        # IN_BUY_ZONE: above pivot, in buy zone, but weak close or low volume
        elif above_pivot and in_buy_zone:
            alerts.append(self._create_alert(
                position, current_price, distance_pct, volume_ratio,
                AlertSubtype.IN_BUY_ZONE, pivot_analysis, market_regime, avg_volume
            ))

        # EXTENDED: beyond buy zone
        elif is_extended and distance_pct <= self.max_extended_pct:
            alerts.append(self._create_alert(
                position, current_price, distance_pct, volume_ratio,
                AlertSubtype.EXTENDED, pivot_analysis, market_regime, avg_volume
            ))

        # APPROACHING: near pivot
        elif is_approaching:
            alerts.append(self._create_alert(
                position, current_price, distance_pct, volume_ratio,
                AlertSubtype.APPROACHING, pivot_analysis, market_regime, avg_volume
            ))

        # BELOW PIVOT: not at breakout yet (informational)
        elif below_approaching:
            # Create a custom "BELOW_PIVOT" status alert
            alerts.append(self._create_below_pivot_alert(
                position, current_price, distance_pct, volume_ratio,
                pivot_analysis, market_regime, avg_volume
            ))

        # Also check for alternative entry opportunities (MA pullbacks)
        alt_entry_alerts = self._check_alt_entry(
            position, current_price, volume_ratio, technical_data
        )
        alerts.extend(alt_entry_alerts)

        return alerts

    def _check_alt_entry(
        self,
        position: Position,
        current_price: float,
        volume_ratio: float,
        technical_data: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Check for alternative entry opportunities using WatchlistAltEntryChecker.

        This detects MA pullback entries on stocks that were previously extended.
        """
        if not technical_data:
            return []

        # Clear cooldowns so we always get fresh results in the tool
        self.alt_entry_checker._cooldowns.clear()

        # Build PositionContext for the checker
        # For watching positions, use e1_price or avg_cost (may be None)
        entry_price = position.e1_price or position.avg_cost or 0
        context = PositionContext(
            symbol=position.symbol,
            position_id=position.id,
            state=position.state or 0,
            current_price=current_price,
            entry_price=entry_price,
            pivot_price=position.pivot or 0,
            pnl_pct=0,  # Watchlist doesn't have P&L
            shares=position.total_shares or 0,
            volume_ratio=volume_ratio,
            ma_21=technical_data.get('ma_21') or technical_data.get('ema_21'),
            ma_50=technical_data.get('ma_50'),
            ma_200=technical_data.get('ma_200'),
        )

        # Run the checker
        alert_data_list = self.alt_entry_checker.check(position, context)

        # Convert AlertData objects to display dicts
        result = []
        for alert_data in alert_data_list:
            result.append(self._convert_alert_data(alert_data, position, current_price, technical_data))

        return result

    def _convert_alert_data(
        self,
        alert_data: AlertData,
        position: Position,
        current_price: float,
        technical_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Convert AlertData object to dict format for display."""
        pivot = position.pivot or 0
        buy_zone_top = pivot * (1 + self.buy_zone_max_pct / 100) if pivot else 0

        return {
            'id': None,
            'symbol': position.symbol,
            'position_id': position.id,
            'alert_type': alert_data.alert_type.value,
            'subtype': alert_data.subtype.value,
            'alert_time': datetime.now().isoformat(),
            'price': current_price,
            'pnl_pct_at_alert': ((current_price - pivot) / pivot * 100) if pivot else 0,
            'pivot_at_alert': pivot,
            'severity': 'info',  # Alt entries are informational/opportunity
            'acknowledged': False,
            'message': alert_data.message,
            'action': alert_data.action,
            'volume_ratio': alert_data.context.volume_ratio if alert_data.context else 0,
            'avg_volume': getattr(position, 'avg_volume_50d', 0) or 500000,
            'market_regime': '',
            'grade': getattr(position, 'grade', '') or '',
            'score': getattr(position, 'score', 0) or 0,
            'pattern': position.pattern or 'Unknown',
            'base_stage': position.base_stage or '?',
            'rs_rating': position.rs_rating,
            'buy_zone_low': pivot,
            'buy_zone_high': buy_zone_top,
            'ma_21': technical_data.get('ma_21') or technical_data.get('ema_21') if technical_data else None,
            'ma_50': technical_data.get('ma_50') if technical_data else None,
        }

    def _create_alert(
        self,
        position: Position,
        current_price: float,
        distance_pct: float,
        volume_ratio: float,
        subtype: AlertSubtype,
        pivot_analysis: PivotAnalysis,
        market_regime: str,
        avg_volume: int,
    ) -> Dict[str, Any]:
        """Create alert dict in format expected by AlertTableWidget."""
        pivot = position.pivot
        buy_zone_top = pivot * (1 + self.buy_zone_max_pct / 100)

        # Build message based on subtype
        if subtype == AlertSubtype.CONFIRMED:
            message = f"Breakout confirmed above ${pivot:.2f} pivot with {volume_ratio:.1f}x volume"
            action = "BUY within buy zone"
        elif subtype == AlertSubtype.SUPPRESSED:
            message = f"Breakout above ${pivot:.2f} but SUPPRESSED due to market correction"
            action = "WAIT for market to confirm uptrend"
        elif subtype == AlertSubtype.IN_BUY_ZONE:
            message = f"In buy zone (${pivot:.2f} - ${buy_zone_top:.2f}) but weak close or volume"
            action = "WATCH for volume confirmation"
        elif subtype == AlertSubtype.EXTENDED:
            message = f"Extended {distance_pct:.1f}% above pivot - beyond buy zone"
            action = "DO NOT CHASE - wait for pullback"
        elif subtype == AlertSubtype.APPROACHING:
            message = f"Approaching pivot at ${pivot:.2f} ({distance_pct:+.1f}%)"
            action = "PREPARE for potential breakout"
        else:
            message = f"Breakout status: {subtype.value}"
            action = ""

        # Add pivot staleness warning
        if pivot_analysis and pivot_analysis.days_since_set and pivot_analysis.days_since_set > 60:
            message += f" (⚠️ Stale pivot: {pivot_analysis.days_since_set} days old)"

        return {
            'id': None,  # No database ID
            'symbol': position.symbol,
            'position_id': position.id,
            'alert_type': AlertType.BREAKOUT.value,
            'subtype': subtype.value,
            'alert_time': datetime.now().isoformat(),
            'price': current_price,
            'pnl_pct_at_alert': distance_pct,  # Distance from pivot for watchlist
            'pivot_at_alert': pivot,
            'severity': self.SEVERITY_MAP.get(subtype, 'neutral'),
            'acknowledged': False,
            'message': message,
            'action': action,
            'volume_ratio': volume_ratio,
            'avg_volume': avg_volume,
            'market_regime': market_regime,
            'grade': getattr(position, 'grade', '') or '',
            'score': getattr(position, 'score', 0) or 0,
            'pattern': position.pattern or 'Unknown',
            'base_stage': position.base_stage or '?',
            'rs_rating': position.rs_rating,
            'buy_zone_low': pivot,
            'buy_zone_high': buy_zone_top,
        }

    def _create_below_pivot_alert(
        self,
        position: Position,
        current_price: float,
        distance_pct: float,
        volume_ratio: float,
        pivot_analysis: PivotAnalysis,
        market_regime: str,
        avg_volume: int,
    ) -> Dict[str, Any]:
        """Create informational alert for stocks below pivot."""
        pivot = position.pivot
        buy_zone_top = pivot * (1 + self.buy_zone_max_pct / 100)

        message = f"Below pivot at ${pivot:.2f} ({distance_pct:+.1f}%)"
        action = "WAIT for price to approach pivot"

        return {
            'id': None,
            'symbol': position.symbol,
            'position_id': position.id,
            'alert_type': AlertType.BREAKOUT.value,
            'subtype': 'BELOW_PIVOT',  # Custom subtype for display
            'alert_time': datetime.now().isoformat(),
            'price': current_price,
            'pnl_pct_at_alert': distance_pct,
            'pivot_at_alert': pivot,
            'severity': 'neutral',
            'acknowledged': False,
            'message': message,
            'action': action,
            'volume_ratio': volume_ratio,
            'avg_volume': avg_volume,
            'market_regime': market_regime,
            'grade': getattr(position, 'grade', '') or '',
            'score': getattr(position, 'score', 0) or 0,
            'pattern': position.pattern or 'Unknown',
            'base_stage': position.base_stage or '?',
            'rs_rating': position.rs_rating,
            'buy_zone_low': pivot,
            'buy_zone_high': buy_zone_top,
        }

    def _calculate_rvol(self, current_volume: int, avg_daily_volume: int) -> float:
        """
        Calculate Relative Volume (RVOL) - time-adjusted volume ratio.

        Compares current intraday volume to expected volume at this time of day.
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
            elapsed_minutes = 1
        elif now_et > market_close:
            elapsed_minutes = total_trading_minutes
        else:
            elapsed_minutes = (now_et - market_open).total_seconds() / 60
            elapsed_minutes = max(1, elapsed_minutes)

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

    def _is_market_in_correction(self, market_regime: str) -> bool:
        """Check if market is in correction mode."""
        if not market_regime:
            return False
        regime_upper = market_regime.upper()
        return regime_upper in ("CORRECTION", "BEARISH", "DOWNTREND")

    def get_status_summary(
        self,
        position: Position,
        current_price: float,
        volume: int = 0,
        avg_volume: int = 0,
        high: float = 0,
        low: float = 0,
        market_regime: str = "",
        technical_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Get a quick summary of breakout status.

        Returns:
            Dict with status, message, and alert details
        """
        alerts = self.check_position(
            position, current_price, volume, avg_volume, high, low, market_regime, technical_data
        )

        if not alerts:
            return {
                'status': 'unknown',
                'message': 'No breakout status available',
                'alerts': [],
            }

        alert = alerts[0]  # Usually just one alert for breakout
        subtype = alert.get('subtype', '')

        if subtype == 'CONFIRMED':
            status = 'breakout'
        elif subtype == 'SUPPRESSED':
            status = 'suppressed'
        elif subtype == 'IN_BUY_ZONE':
            status = 'buy_zone'
        elif subtype == 'EXTENDED':
            status = 'extended'
        elif subtype == 'APPROACHING':
            status = 'approaching'
        else:
            status = 'below_pivot'

        return {
            'status': status,
            'message': alert.get('message', ''),
            'action': alert.get('action', ''),
            'alerts': alerts,
        }
