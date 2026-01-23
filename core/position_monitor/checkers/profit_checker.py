"""
Profit Checker - Profit taking alerts.

Alerts:
- TP1: 20% profit target reached
- TP2: 25%+ profit target reached  
- 8_WEEK_HOLD: Suppress TP1 for big winners
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData

from .base_checker import BaseChecker, PositionContext


class ProfitChecker(BaseChecker):
    """
    Check positions for profit taking opportunities.
    
    Implements IBD profit-taking rules:
    - Take 20-25% profits on the way up
    - 8-week hold rule for big winners (20%+ in 3 weeks)
    """
    
    @property
    def name(self) -> str:
        return "profit"
    
    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        super().__init__(config, logger)
        
        # 8-week hold config
        eight_week_config = config.get('eight_week_hold', {}) if config else {}
        self.eight_week_gain_threshold = eight_week_config.get('gain_threshold_pct', 20.0)
        self.eight_week_trigger_window = eight_week_config.get('trigger_window_days', 21)
        self.eight_week_hold_weeks = eight_week_config.get('hold_weeks', 8)
        
        # Profit target config (can override position-level settings)
        self.default_tp1_pct = 20.0
        self.default_tp2_pct = 25.0
    
    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """Check for profit taking conditions."""
        if not self.should_check(context):
            return []
        
        alerts = []
        
        # Check 8-week hold activation first
        eight_week_alert = self._check_eight_week_activation(position, context)
        if eight_week_alert:
            alerts.append(eight_week_alert)
        
        # Check if TP1 is suppressed by 8-week hold
        tp1_suppressed = self._is_tp1_suppressed(context)
        
        # Check TP1 (unless suppressed)
        if not tp1_suppressed:
            tp1_alert = self._check_tp1(position, context)
            if tp1_alert:
                alerts.append(tp1_alert)
        
        # Check TP2
        tp2_alert = self._check_tp2(position, context)
        if tp2_alert:
            alerts.append(tp2_alert)
        
        return alerts
    
    def _check_eight_week_activation(
        self,
        position: Position,
        context: PositionContext,
    ) -> AlertData:
        """Check if 8-week hold rule should activate."""
        # Already active
        if context.eight_week_hold_active:
            return None
        
        # Check cooldown
        if self.is_on_cooldown(context.symbol, AlertSubtype.EIGHT_WEEK_HOLD):
            return None
        
        # Check criteria: 20%+ gain within 3 weeks of breakout
        if context.pnl_pct < self.eight_week_gain_threshold:
            return None
        
        if context.days_since_breakout > self.eight_week_trigger_window:
            return None
        
        # Calculate hold end date
        hold_end_date = datetime.now().date() + timedelta(weeks=self.eight_week_hold_weeks)
        weeks_remaining = self.eight_week_hold_weeks
        
        message = (
            f"🏆 8-WEEK HOLD RULE ACTIVATED!\n\n"
            f"Gain: {self.format_pct(context.pnl_pct)} in {context.days_since_breakout} days\n"
            f"This qualifies as a potential BIG WINNER.\n\n"
            f"▶ HOLD for {weeks_remaining} more weeks\n"
            f"   Target Hold Until: {hold_end_date.strftime('%b %d, %Y')}\n\n"
            f"During 8-week hold:\n"
            f"• TP1 alerts SUPPRESSED (don't sell early)\n"
            f"• Use 10-week MA as guide (not daily)\n"
            f"• Hard stop still active for capital protection\n\n"
            f"IBD Rule: Stocks that gain 20%+ in 3 weeks often become the biggest winners."
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.EIGHT_WEEK_HOLD)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.PROFIT,
            subtype=AlertSubtype.EIGHT_WEEK_HOLD,
            message=message,
            action="HOLD - 8-Week Rule Active",
            priority="P0",
        )
    
    def _is_tp1_suppressed(self, context: PositionContext) -> bool:
        """Check if TP1 is suppressed by 8-week hold."""
        if not context.eight_week_hold_active:
            return False
        
        if context.eight_week_hold_end_date is None:
            return False
        
        return datetime.now().date() < context.eight_week_hold_end_date
    
    def _check_tp1(
        self,
        position: Position,
        context: PositionContext,
    ) -> AlertData:
        """Check if TP1 target reached."""
        # Skip if already sold at TP1
        if context.tp1_sold > 0:
            return None
        
        # Check cooldown
        if self.is_on_cooldown(context.symbol, AlertSubtype.TP1):
            return None
        
        # Get TP1 target
        tp1_pct = self.default_tp1_pct
        if position is not None:
            tp1_pct = getattr(position, 'tp1_pct', None) or self.default_tp1_pct
        
        if context.pnl_pct < tp1_pct:
            return None
        
        # Calculate sell recommendation (25% of position)
        shares_to_sell = int(context.shares * 0.25)
        sell_value = shares_to_sell * context.current_price
        profit_locked = shares_to_sell * (context.current_price - context.entry_price)
        
        message = (
            f"💰 TP1 TARGET REACHED!\n\n"
            f"Gain: {self.format_pct(context.pnl_pct)}\n"
            f"Price: {self.format_price(context.current_price)}\n"
            f"Entry: {self.format_price(context.entry_price)}\n\n"
            f"▶ SELL 25% OF POSITION\n"
            f"   Shares to Sell: {shares_to_sell} of {context.shares}\n"
            f"   Proceeds: {self.format_price(sell_value)}\n"
            f"   Profit Locked: {self.format_dollars(profit_locked)}\n\n"
            f"After selling:\n"
            f"• Raise stop to breakeven on remaining shares\n"
            f"• Let winners run\n\n"
            f"IBD Rule: Take some profits on the way up to lock in gains."
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.TP1)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.PROFIT,
            subtype=AlertSubtype.TP1,
            message=message,
            action="SELL 25% OF POSITION",
            priority="P1",
        )
    
    def _check_tp2(
        self,
        position: Position,
        context: PositionContext,
    ) -> AlertData:
        """Check if TP2 target reached."""
        # Skip if already sold at TP2
        if context.tp2_sold > 0:
            return None
        
        # Check cooldown
        if self.is_on_cooldown(context.symbol, AlertSubtype.TP2):
            return None
        
        # Get TP2 target
        tp2_pct = self.default_tp2_pct
        if position is not None:
            tp2_pct = getattr(position, 'tp2_pct', None) or self.default_tp2_pct
        
        if context.pnl_pct < tp2_pct:
            return None
        
        # Calculate sell recommendation (25% of remaining - was 40% then 33%)
        # IBD adjustment: More conservative to let winners run
        remaining_shares = context.shares - (context.tp1_sold or 0)
        shares_to_sell = int(remaining_shares * 0.25)
        sell_value = shares_to_sell * context.current_price
        profit_locked = shares_to_sell * (context.current_price - context.entry_price)
        
        message = (
            f"💰💰 TP2 TARGET REACHED!\n\n"
            f"Gain: {self.format_pct(context.pnl_pct)}\n"
            f"Price: {self.format_price(context.current_price)}\n"
            f"Entry: {self.format_price(context.entry_price)}\n\n"
            f"▶ SELL 25% OF REMAINING\n"
            f"   Shares to Sell: {shares_to_sell} of {remaining_shares} remaining\n"
            f"   Proceeds: {self.format_price(sell_value)}\n"
            f"   Profit Locked: {self.format_dollars(profit_locked)}\n\n"
            f"After selling:\n"
            f"• Consider trailing stop on final portion\n"
            f"• Use 10-week MA as guide for remaining shares"
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.TP2)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.PROFIT,
            subtype=AlertSubtype.TP2,
            message=message,
            action="SELL 25% OF REMAINING",
            priority="P1",
        )
