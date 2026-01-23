"""
Pyramid Checker - Position building alerts.

Alerts:
- P1_READY: In first add zone (0-5%)
- P1_EXTENDED: Beyond PY1 zone  
- P2_READY: In second add zone (5-10%)
- P2_EXTENDED: Beyond PY2 zone
- PULLBACK: Pullback to 21 EMA
"""

from typing import List, Dict, Any
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData
from canslim_monitor.utils.level_calculator import LevelCalculator

from .base_checker import BaseChecker, PositionContext


class PyramidChecker(BaseChecker):
    """
    Check positions for pyramid entry opportunities.
    
    Implements IBD pyramiding methodology:
    - Add in small increments as position works
    - PY1: 0-5% above entry (state 1 -> 2)
    - PY2: 5-10% above entry (state 2 -> 3)
    - Pullback entries near 21 EMA
    """
    
    @property
    def name(self) -> str:
        return "pyramid"
    
    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        super().__init__(config, logger)
        self.level_calc = LevelCalculator(config)
        
        # Pyramid config
        pyramid_config = config.get('pyramid', {}) if config else {}
        self.min_bars_since_entry = pyramid_config.get('min_bars_since_entry', 2)
        self.pullback_ema_tolerance = pyramid_config.get('pullback_ema_tolerance', 1.0)
    
    def should_check(self, context: PositionContext) -> bool:
        """Only check profitable positions in building states."""
        if context.state < 1 or context.state > 3:
            return False
        if context.pnl_pct <= 0:
            return False
        if context.days_in_position < self.min_bars_since_entry:
            return False
        return True
    
    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """Check for pyramid entry opportunities."""
        if not self.should_check(context):
            return []
        
        alerts = []
        
        # Get pyramid status
        status = self.level_calc.get_pyramid_status(
            entry_price=context.entry_price,
            current_price=context.current_price,
            state=context.state,
            py1_done=context.py1_done,
            py2_done=context.py2_done,
        )
        
        # Check PY1 alerts (state 1)
        if context.state == 1 and not context.py1_done:
            if status['py1_ready']:
                alert = self._check_py1_ready(context)
                if alert:
                    alerts.append(alert)
            elif status['py1_extended']:
                alert = self._check_py1_extended(context)
                if alert:
                    alerts.append(alert)
        
        # Check PY2 alerts (state 2)
        if context.state == 2 and not context.py2_done:
            if status['py2_ready']:
                alert = self._check_py2_ready(context)
                if alert:
                    alerts.append(alert)
            elif status['py2_extended']:
                alert = self._check_py2_extended(context)
                if alert:
                    alerts.append(alert)
        
        # Check pullback to 21 EMA (any building state)
        if context.state >= 1 and context.state <= 3:
            pullback_alert = self._check_pullback(context)
            if pullback_alert:
                alerts.append(pullback_alert)
        
        return alerts
    
    def _check_py1_ready(self, context: PositionContext) -> AlertData:
        """Check if ready for first pyramid add."""
        if self.is_on_cooldown(context.symbol, AlertSubtype.P1_READY):
            return None
        
        # Calculate add size (half of initial position)
        add_shares = int(context.shares * 0.5)
        add_value = add_shares * context.current_price
        
        message = (
            f"📈 PY1 ADD ZONE\n\n"
            f"Price: {self.format_price(context.current_price)} "
            f"({self.format_pct(context.pnl_pct)} from entry)\n"
            f"Entry: {self.format_price(context.entry_price)}\n"
            f"Zone: 0-5% above entry\n\n"
            f"▶ ADD TO POSITION\n"
            f"   Suggested: {add_shares} shares (~50% of initial)\n"
            f"   Cost: {self.format_price(add_value)}\n\n"
            f"IBD Rule: Pyramid in small increments as position works."
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.P1_READY)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.PYRAMID,
            subtype=AlertSubtype.P1_READY,
            message=message,
            action="ADD TO POSITION",
            priority="P1",
        )
    
    def _check_py1_extended(self, context: PositionContext) -> AlertData:
        """Check if extended beyond PY1 zone."""
        if self.is_on_cooldown(context.symbol, AlertSubtype.P1_EXTENDED):
            return None
        
        message = (
            f"📈 EXTENDED BEYOND PY1 ZONE\n\n"
            f"Price: {self.format_price(context.current_price)} "
            f"({self.format_pct(context.pnl_pct)} from entry)\n"
            f"PY1 Zone: 0-5% above entry\n\n"
            f"Position has moved past ideal PY1 add zone.\n"
            f"Wait for pullback or continue to PY2 zone."
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.P1_EXTENDED)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.PYRAMID,
            subtype=AlertSubtype.P1_EXTENDED,
            message=message,
            action="WAIT FOR PULLBACK",
            priority="P2",
        )
    
    def _check_py2_ready(self, context: PositionContext) -> AlertData:
        """Check if ready for second pyramid add."""
        if self.is_on_cooldown(context.symbol, AlertSubtype.P2_READY):
            return None
        
        # Calculate add size (25% of current position)
        add_shares = int(context.shares * 0.25)
        add_value = add_shares * context.current_price
        
        message = (
            f"📈📈 PY2 ADD ZONE\n\n"
            f"Price: {self.format_price(context.current_price)} "
            f"({self.format_pct(context.pnl_pct)} from entry)\n"
            f"Entry: {self.format_price(context.entry_price)}\n"
            f"Zone: 5-10% above entry\n\n"
            f"▶ FINAL ADD OPPORTUNITY\n"
            f"   Suggested: {add_shares} shares (~25% of current)\n"
            f"   Cost: {self.format_price(add_value)}\n\n"
            f"This is typically the final add point for position building."
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.P2_READY)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.PYRAMID,
            subtype=AlertSubtype.P2_READY,
            message=message,
            action="FINAL ADD OPPORTUNITY",
            priority="P1",
        )
    
    def _check_py2_extended(self, context: PositionContext) -> AlertData:
        """Check if extended beyond PY2 zone."""
        if self.is_on_cooldown(context.symbol, AlertSubtype.P2_EXTENDED):
            return None
        
        message = (
            f"📈 EXTENDED BEYOND PY2 ZONE\n\n"
            f"Price: {self.format_price(context.current_price)} "
            f"({self.format_pct(context.pnl_pct)} from entry)\n"
            f"PY2 Zone: 5-10% above entry\n\n"
            f"Position has moved past add zones.\n"
            f"Do not chase - position building complete."
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.P2_EXTENDED)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.PYRAMID,
            subtype=AlertSubtype.P2_EXTENDED,
            message=message,
            action="DO NOT CHASE",
            priority="P2",
        )
    
    def _check_pullback(self, context: PositionContext) -> AlertData:
        """Check for pullback to 21 EMA."""
        if context.ma_21 is None:
            return None
        
        if self.is_on_cooldown(context.symbol, AlertSubtype.PULLBACK):
            return None
        
        # Check if price is within tolerance of 21 EMA
        distance_pct = abs((context.current_price - context.ma_21) / context.ma_21 * 100)
        
        if distance_pct > self.pullback_ema_tolerance:
            return None
        
        # Must be above 21 EMA (or touching it from above)
        if context.current_price < context.ma_21 * 0.99:  # 1% below is too much
            return None
        
        message = (
            f"📈 PULLBACK TO 21 EMA\n\n"
            f"Price: {self.format_price(context.current_price)}\n"
            f"21 EMA: {self.format_price(context.ma_21)}\n"
            f"Distance: {distance_pct:.1f}%\n\n"
            f"▶ POTENTIAL ADD POINT\n"
            f"   Consider adding if volume is light on pullback\n\n"
            f"IBD Rule: Pullbacks to the 21-day EMA on light volume "
            f"can be good add points in a strong position."
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.PULLBACK)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.ADD,
            subtype=AlertSubtype.PULLBACK,
            message=message,
            action="POTENTIAL ADD POINT",
            priority="P1",
        )
