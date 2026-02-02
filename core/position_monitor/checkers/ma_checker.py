"""
MA Checker - Moving average violation alerts.

Alerts:
- 50_MA_WARNING: Approaching 50-day MA
- 50_MA_SELL: Close below 50 MA with volume (IBD gap fix)
- 21_EMA_SELL: Late-stage 21 EMA violation
- 10_WEEK_SELL: Weekly close below 10-week MA
"""

from typing import List, Dict, Any
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData
from canslim_monitor.utils.discord_formatters import (
    build_ma_warning_embed,
    build_ma_sell_embed,
    build_position_embed,
)

from .base_checker import BaseChecker, PositionContext


class MAChecker(BaseChecker):
    """
    Check positions for moving average violations.
    
    Implements IBD sell rules around moving averages:
    - 50-day MA is key support level
    - Volume confirmation required for sell signals
    - 21 EMA more relevant for late-stage positions
    - 10-week MA for longer-term positions
    """
    
    @property
    def name(self) -> str:
        return "ma"
    
    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        super().__init__(config, logger)
        
        # Technical config
        tech_config = config.get('technical', {}) if config else {}
        self.ma_50_warning_pct = tech_config.get('ma_50_warning_pct', 2.0)
        self.ma_50_volume_confirm = tech_config.get('ma_50_volume_confirm', 1.5)
        self.ema_21_consecutive_days = tech_config.get('ema_21_consecutive_days', 2)
        
        # Climax top config
        # IBD: Climax tops occur with largest spread, heaviest volume, often a gap
        climax_config = config.get('climax_top', {}) if config else {}
        self.climax_volume_threshold = climax_config.get('volume_threshold', 2.5)  # 2.5x avg volume
        self.climax_spread_pct = climax_config.get('spread_pct', 4.0)  # 4% spread high-low
        self.climax_gap_pct = climax_config.get('gap_pct', 2.0)  # 2% gap up open
        self.climax_min_gain = climax_config.get('min_gain_pct', 15.0)  # Must be up 15%+ to consider
        
        # Track consecutive closes below 21 EMA
        self._ema_violation_counts: Dict[str, int] = {}
    
    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """Check for MA violations."""
        if not self.should_check(context):
            return []
        
        alerts = []
        
        # Check 50 MA sell (requires volume confirmation - IBD gap fix)
        ma50_sell = self._check_50ma_sell(context)
        if ma50_sell:
            alerts.append(ma50_sell)
            return alerts  # P0 alert, return early
        
        # Check 50 MA warning
        ma50_warning = self._check_50ma_warning(context)
        if ma50_warning:
            alerts.append(ma50_warning)
        
        # Check 21 EMA sell (late stage only)
        ema21_sell = self._check_21ema_sell(context)
        if ema21_sell:
            alerts.append(ema21_sell)
        
        # Check 10-week MA sell
        ten_week_sell = self._check_10week_sell(context)
        if ten_week_sell:
            alerts.append(ten_week_sell)
        
        # Check for climax top
        climax_alert = self._check_climax_top(context)
        if climax_alert:
            alerts.append(climax_alert)
        
        return alerts
    
    def _check_50ma_sell(self, context: PositionContext) -> AlertData:
        """
        Check for close below 50 MA with volume.

        IBD Gap Fix: Requires volume confirmation (1.5x average).
        A close below 50 MA on light volume is less concerning.
        """
        if context.ma_50 is None:
            return None

        # Must be below 50 MA
        if context.current_price >= context.ma_50:
            return None

        # Must have volume confirmation (IBD gap fix)
        if context.volume_ratio < self.ma_50_volume_confirm:
            return None

        # Build compact embed format
        message = build_ma_sell_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            ma_type="50 MA",
            ma_value=context.ma_50,
            volume_ratio=context.volume_ratio,
            subtype='MA_50_SELL',
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
        )

        return self.create_alert(
            context=context,
            alert_type=AlertType.TECHNICAL,
            subtype=AlertSubtype.MA_50_SELL,
            message=message,
            action="SELL - VOLUME CONFIRMED",
            priority="P0",
        )
    
    def _check_50ma_warning(self, context: PositionContext) -> AlertData:
        """Check if approaching 50 MA."""
        if context.ma_50 is None:
            return None

        if self.is_on_cooldown(context.symbol, AlertSubtype.MA_50_WARNING):
            return None

        # Calculate distance to 50 MA
        distance_pct = ((context.current_price - context.ma_50) / context.current_price) * 100

        # Only warn if approaching from above
        if context.current_price <= context.ma_50:
            return None

        if distance_pct > self.ma_50_warning_pct:
            return None

        # Build compact embed format
        message = build_ma_warning_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            ma_type="50 MA",
            ma_value=context.ma_50,
            distance_pct=distance_pct,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
        )

        self.set_cooldown(context.symbol, AlertSubtype.MA_50_WARNING)

        return self.create_alert(
            context=context,
            alert_type=AlertType.TECHNICAL,
            subtype=AlertSubtype.MA_50_WARNING,
            message=message,
            action="WATCH FOR SUPPORT",
            priority="P1",
        )
    
    def _check_21ema_sell(self, context: PositionContext) -> AlertData:
        """
        Check for late-stage 21 EMA violation.

        For state 4+ positions, 2 consecutive closes below 21 EMA
        is a sell signal (more sensitive than 50 MA for late stage).
        """
        if context.ma_21 is None:
            return None

        # Only for late-stage positions (state 4+)
        if context.state < 4:
            return None

        symbol = context.symbol

        # Check if below 21 EMA
        if context.current_price >= context.ma_21:
            # Reset violation count
            self._ema_violation_counts[symbol] = 0
            return None

        # Increment violation count
        self._ema_violation_counts[symbol] = self._ema_violation_counts.get(symbol, 0) + 1

        # Need consecutive violations
        if self._ema_violation_counts[symbol] < self.ema_21_consecutive_days:
            return None

        if self.is_on_cooldown(symbol, AlertSubtype.EMA_21_SELL):
            return None

        # Build compact embed format
        message = build_ma_sell_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            ma_type="21 EMA",
            ma_value=context.ma_21,
            volume_ratio=context.volume_ratio,
            subtype='EMA_21_SELL',
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
        )

        self.set_cooldown(symbol, AlertSubtype.EMA_21_SELL)

        return self.create_alert(
            context=context,
            alert_type=AlertType.TECHNICAL,
            subtype=AlertSubtype.EMA_21_SELL,
            message=message,
            action="SELL - LATE STAGE",
            priority="P1",
        )
    
    def _check_10week_sell(self, context: PositionContext) -> AlertData:
        """
        Check for close below 10-week MA.

        IBD Gap Fix: This is a weekly sell rule (TrendSpider only has daily).
        The 10-week MA is key for longer-term positions, especially
        during 8-week hold periods.
        """
        if context.ma_10_week is None:
            return None

        if self.is_on_cooldown(context.symbol, AlertSubtype.TEN_WEEK_SELL):
            return None

        # Must be below 10-week MA
        if context.current_price >= context.ma_10_week:
            return None

        # Build compact embed format
        message = build_ma_sell_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            ma_type="10 Week",
            ma_value=context.ma_10_week,
            volume_ratio=context.volume_ratio,
            subtype='TEN_WEEK_SELL',
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
        )

        self.set_cooldown(context.symbol, AlertSubtype.TEN_WEEK_SELL)

        return self.create_alert(
            context=context,
            alert_type=AlertType.TECHNICAL,
            subtype=AlertSubtype.TEN_WEEK_SELL,
            message=message,
            action="SELL - WEEKLY BREAKDOWN",
            priority="P0",
        )
    
    def _check_climax_top(self, context: PositionContext) -> AlertData:
        """
        Check for climax top (exhaustion) pattern.

        IBD Climax Top Characteristics:
        - Largest single-day price spread in the entire run
        - Heaviest volume in weeks
        - Often gaps up on open
        - May reverse and close near the low

        This is a P0 sell signal as it often marks the end of a run.
        """
        # Need minimum gain to even consider climax top
        if context.pnl_pct < self.climax_min_gain:
            return None

        if self.is_on_cooldown(context.symbol, AlertSubtype.CLIMAX_TOP):
            return None

        # Calculate climax indicators
        climax_signals = []
        climax_score = 0

        # 1. Volume exhaustion (very heavy volume)
        if context.volume_ratio >= self.climax_volume_threshold:
            climax_signals.append(f"Vol {context.volume_ratio:.1f}x")
            climax_score += 30

        # 2. Large spread (if intraday data available)
        spread_pct = 0
        if context.day_high and context.day_low and context.day_low > 0:
            spread_pct = ((context.day_high - context.day_low) / context.day_low) * 100
            if spread_pct >= self.climax_spread_pct:
                climax_signals.append(f"Spread {spread_pct:.1f}%")
                climax_score += 25

        # 3. Gap up open (if data available)
        gap_pct = 0
        if context.day_open and context.prev_close and context.prev_close > 0:
            gap_pct = ((context.day_open - context.prev_close) / context.prev_close) * 100
            if gap_pct >= self.climax_gap_pct:
                climax_signals.append(f"Gap +{gap_pct:.1f}%")
                climax_score += 25

        # 4. Reversal (close near low after being up)
        if context.day_high and context.day_low and context.current_price:
            day_range = context.day_high - context.day_low
            if day_range > 0:
                close_position = (context.current_price - context.day_low) / day_range
                if close_position < 0.3:  # Closed in lower 30% of range
                    climax_signals.append("Reversal")
                    climax_score += 20

        # Need minimum score to trigger alert
        if climax_score < 50:  # Need at least 2 signals
            return None

        # Determine urgency
        is_high_conviction = climax_score >= 75
        priority = "P0" if is_high_conviction else "P1"

        # Build compact embed format
        signals_str = " | ".join(climax_signals) if climax_signals else "Multiple signals"
        line2 = f"Signals: {signals_str} ({climax_score}%)"
        message = build_position_embed(
            alert_type='TECHNICAL',
            subtype='CLIMAX_TOP',
            symbol=context.symbol,
            price=context.current_price,
            pnl_pct=context.pnl_pct,
            entry_price=context.entry_price,
            line2_data=line2,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            max_gain_pct=context.max_gain_pct,
            action="Sell 50-100% on climax run",
            priority=priority,
            market_regime=context.market_regime,
            custom_title=f"CLIMAX TOP WARNING: {context.symbol}",
        )

        self.set_cooldown(context.symbol, AlertSubtype.CLIMAX_TOP)

        return self.create_alert(
            context=context,
            alert_type=AlertType.TECHNICAL,
            subtype=AlertSubtype.CLIMAX_TOP,
            message=message,
            action="SELL 50%+ - CLIMAX TOP",
            priority=priority,
        )
