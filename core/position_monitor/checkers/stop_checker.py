"""
Stop Checker - Capital protection alerts (P0 priority).

Alerts:
- HARD_STOP: Price at/below stop level
- WARNING: Price approaching stop
- TRAILING: Trailing stop triggered
"""

from typing import List, Dict, Any
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData
from canslim_monitor.utils.level_calculator import LevelCalculator
from canslim_monitor.utils.discord_formatters import (
    build_stop_warning_embed,
    build_hard_stop_embed,
    build_position_embed,
)

from .base_checker import BaseChecker, PositionContext


class StopChecker(BaseChecker):
    """
    Check positions for stop loss conditions.
    
    Priority: P0 (immediate action required)
    
    This is the most critical checker - capital protection
    takes precedence over all other alerts.
    """
    
    @property
    def name(self) -> str:
        return "stop"
    
    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        super().__init__(config, logger)
        self.level_calc = LevelCalculator(config)
        
        # Config
        stop_config = config.get('stop_loss', {}) if config else {}
        self.warning_buffer_pct = stop_config.get('warning_buffer_pct', 2.0)
        
        trailing_config = config.get('trailing_stop', {}) if config else {}
        self.trailing_activation_pct = trailing_config.get('activation_pct', 15.0)
        self.trailing_trail_pct = trailing_config.get('trail_pct', 8.0)
    
    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """Check for stop loss conditions."""
        if not self.should_check(context):
            return []
        
        alerts = []
        
        # Get hard_stop_pct from position or use default
        hard_stop_pct = None
        if position is not None:
            hard_stop_pct = getattr(position, 'hard_stop_pct', None)
        
        # Calculate levels
        levels = self.level_calc.calculate_levels(
            context.entry_price,
            context.base_stage,
            hard_stop_pct=hard_stop_pct,
        )
        
        # Check hard stop (P0 - highest priority)
        hard_stop_alert = self._check_hard_stop(context, levels.hard_stop)
        if hard_stop_alert:
            alerts.append(hard_stop_alert)
            return alerts  # Don't check other conditions if hard stop hit
        
        # Check trailing stop if activated
        trailing_alert = self._check_trailing_stop(context)
        if trailing_alert:
            alerts.append(trailing_alert)
            return alerts  # Trailing stop is also P0
        
        # Check stop warning (P1)
        warning_alert = self._check_stop_warning(context, levels.hard_stop)
        if warning_alert:
            alerts.append(warning_alert)
        
        return alerts
    
    def _check_hard_stop(
        self,
        context: PositionContext,
        hard_stop: float,
    ) -> AlertData:
        """Check if price hit hard stop."""
        if context.current_price > hard_stop:
            return None

        # Always fire hard stop - no cooldown
        loss_pct = context.pnl_pct
        loss_dollars = context.pnl_dollars

        # Build compact embed format
        message = build_hard_stop_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            stop_price=hard_stop,
            pnl_pct=loss_pct,
            loss_dollars=loss_dollars,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
        )

        return self.create_alert(
            context=context,
            alert_type=AlertType.STOP,
            subtype=AlertSubtype.HARD_STOP,
            message=message,
            action="EXIT POSITION",
            priority="P0",
        )
    
    def _check_trailing_stop(self, context: PositionContext) -> AlertData:
        """Check if trailing stop triggered."""
        # Check if trailing stop should be active
        if context.max_gain_pct < self.trailing_activation_pct:
            return None

        # Calculate trailing stop from max price
        trailing_stop = context.max_price * (1 - self.trailing_trail_pct / 100)

        # Ensure trailing stop is above entry
        trailing_stop = max(trailing_stop, context.entry_price)

        if context.current_price > trailing_stop:
            return None

        gain_locked = ((trailing_stop - context.entry_price) / context.entry_price) * 100

        # Build compact embed format
        line2 = f"Trail Stop: ${trailing_stop:.2f} | Max: ${context.max_price:.2f} (+{context.max_gain_pct:.1f}%)"
        message = build_position_embed(
            alert_type='STOP',
            subtype='TRAILING_STOP',
            symbol=context.symbol,
            price=context.current_price,
            pnl_pct=context.pnl_pct,
            entry_price=context.entry_price,
            line2_data=line2,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            max_gain_pct=context.max_gain_pct,
            action=f"Sell to lock +{gain_locked:.1f}% gain",
            priority='P0',
            market_regime=context.market_regime,
            custom_title=f"TRAILING STOP HIT: {context.symbol}",
        )

        return self.create_alert(
            context=context,
            alert_type=AlertType.STOP,
            subtype=AlertSubtype.TRAILING_STOP,
            message=message,
            action="SELL TO LOCK IN PROFITS",
            priority="P0",
        )
    
    def _check_stop_warning(
        self,
        context: PositionContext,
        hard_stop: float,
    ) -> AlertData:
        """Check if price approaching stop."""
        if self.is_on_cooldown(context.symbol, AlertSubtype.WARNING):
            return None

        # Calculate distance to stop
        distance_to_stop = ((context.current_price - hard_stop) / context.current_price) * 100

        # Only warn if within 2% of stop
        if distance_to_stop > self.warning_buffer_pct:
            return None

        # Build compact embed format
        message = build_stop_warning_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            stop_price=hard_stop,
            distance_pct=distance_to_stop,
            pnl_pct=context.pnl_pct,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
        )

        self.set_cooldown(context.symbol, AlertSubtype.WARNING)

        return self.create_alert(
            context=context,
            alert_type=AlertType.STOP,
            subtype=AlertSubtype.WARNING,
            message=message,
            action="WATCH CLOSELY",
            priority="P0",
        )
