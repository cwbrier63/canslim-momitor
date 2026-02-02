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
from canslim_monitor.utils.discord_formatters import build_pyramid_embed, build_position_embed

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

        # Calculate pyramid zone
        zone_low = context.entry_price
        zone_high = context.entry_price * 1.05

        # Build compact embed format
        message = build_pyramid_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            pyramid_level="PY1",
            zone_low=zone_low,
            zone_high=zone_high,
            volume_ratio=context.volume_ratio,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
        )

        self.set_cooldown(context.symbol, AlertSubtype.P1_READY)

        return self.create_alert(
            context=context,
            alert_type=AlertType.PYRAMID,
            subtype=AlertSubtype.P1_READY,
            message=message,
            action="ADD 25% TO POSITION",
            priority="P1",
        )
    
    def _check_py1_extended(self, context: PositionContext) -> AlertData:
        """Check if extended beyond PY1 zone."""
        if self.is_on_cooldown(context.symbol, AlertSubtype.P1_EXTENDED):
            return None

        ext_pct = context.pnl_pct - 5.0  # How far past 5% zone

        # Build compact embed format
        line2 = f"Extended: +{ext_pct:.1f}% above PY1 zone (0-5%)"
        message = build_position_embed(
            alert_type='PYRAMID',
            subtype='PY1_EXTENDED',
            symbol=context.symbol,
            price=context.current_price,
            pnl_pct=context.pnl_pct,
            entry_price=context.entry_price,
            line2_data=line2,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            action="Wait for pullback to 21 EMA to add",
            priority='P2',
            market_regime=context.market_regime,
            custom_title=f"PY1 EXTENDED: {context.symbol}",
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

        # Calculate pyramid zone
        zone_low = context.entry_price * 1.05
        zone_high = context.entry_price * 1.10

        # Build compact embed format
        message = build_pyramid_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            pyramid_level="PY2",
            zone_low=zone_low,
            zone_high=zone_high,
            volume_ratio=context.volume_ratio,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
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

        ext_pct = context.pnl_pct - 10.0  # How far past 10% zone

        # Build compact embed format
        line2 = f"Extended: +{ext_pct:.1f}% above PY2 zone (5-10%)"
        message = build_position_embed(
            alert_type='PYRAMID',
            subtype='PY2_EXTENDED',
            symbol=context.symbol,
            price=context.current_price,
            pnl_pct=context.pnl_pct,
            entry_price=context.entry_price,
            line2_data=line2,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            action="Do not chase - position building complete",
            priority='P2',
            market_regime=context.market_regime,
            custom_title=f"PY2 EXTENDED: {context.symbol}",
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

        # Volume description
        vol_desc = "Light" if context.volume_ratio < 1.0 else "Normal" if context.volume_ratio < 1.5 else "Heavy"

        # Build compact embed format
        line2 = f"21 EMA: ${context.ma_21:.2f} | Distance: {distance_pct:.1f}%"
        message = build_position_embed(
            alert_type='ADD',
            subtype='PULLBACK',
            symbol=context.symbol,
            price=context.current_price,
            pnl_pct=context.pnl_pct,
            entry_price=context.entry_price,
            line2_data=line2,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            action=f"Consider adding if volume stays light ({vol_desc})",
            priority='P1',
            market_regime=context.market_regime,
            custom_title=f"PULLBACK TO 21 EMA: {context.symbol}",
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
