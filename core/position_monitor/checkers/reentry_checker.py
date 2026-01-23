"""
Re-entry Checker - MA bounce and pivot retest alerts.

Alerts:
- MA_BOUNCE: Price bounced off 21 EMA or 50 MA (add opportunity)
- PIVOT_RETEST: Price retested original pivot point and held
- PULLBACK_ENTRY: Price pulled back to buy zone (0-5% above pivot)

These are ADD signals for existing positions or re-entry signals
for recently exited positions.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData

from .base_checker import BaseChecker, PositionContext


class ReentryChecker(BaseChecker):
    """
    Check for re-entry and add opportunities.
    
    IBD Rules for adding to positions:
    - Pullback to 21 EMA in strong uptrend
    - Bounce off 50 MA with volume
    - Retest of original pivot point
    - 3-weeks tight pattern (future)
    """
    
    @property
    def name(self) -> str:
        return "reentry"
    
    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        super().__init__(config, logger)
        
        # Re-entry config
        reentry_config = config.get('reentry', {}) if config else {}
        
        # MA bounce thresholds
        self.ema_21_bounce_pct = reentry_config.get('ema_21_bounce_pct', 1.0)  # Within 1% of 21 EMA
        self.ma_50_bounce_pct = reentry_config.get('ma_50_bounce_pct', 1.5)   # Within 1.5% of 50 MA
        self.bounce_volume_min = reentry_config.get('bounce_volume_min', 1.0)  # At least avg volume
        
        # Pivot retest
        self.pivot_retest_pct = reentry_config.get('pivot_retest_pct', 2.0)  # Within 2% of pivot
        
        # Buy zone
        self.buy_zone_max_pct = reentry_config.get('buy_zone_max_pct', 5.0)  # 5% above pivot
        
        # Track previous prices for bounce detection
        self._previous_prices: Dict[str, List[float]] = {}
        self._bounce_detected: Dict[str, datetime] = {}  # Track recent bounces
    
    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """Check for re-entry opportunities."""
        if not self.should_check(context):
            return []
        
        alerts = []
        
        # Only check if position has room to add (not full)
        if context.state >= 3:  # Full position, no more adds
            return []
        
        # Check 21 EMA bounce
        ema_bounce = self._check_21ema_bounce(context)
        if ema_bounce:
            alerts.append(ema_bounce)
        
        # Check 50 MA bounce
        ma_bounce = self._check_50ma_bounce(context)
        if ma_bounce:
            alerts.append(ma_bounce)
        
        # Check pivot retest
        pivot_retest = self._check_pivot_retest(context)
        if pivot_retest:
            alerts.append(pivot_retest)
        
        # Check pullback to buy zone
        pullback = self._check_pullback_to_buy_zone(context)
        if pullback:
            alerts.append(pullback)
        
        # Update price tracking
        self._update_price_tracking(context)
        
        return alerts
    
    def _check_21ema_bounce(self, context: PositionContext) -> Optional[AlertData]:
        """
        Check for bounce off 21 EMA.
        
        IBD Rule: In a strong uptrend, pullbacks to 21 EMA can be add points.
        Best after stock has shown 10%+ gain from entry.
        """
        if context.ma_21 is None:
            return None
        
        if self.is_on_cooldown(context.symbol, AlertSubtype.EMA_21):
            return None
        
        # Only consider if stock is performing (up 5%+ from entry)
        if context.pnl_pct < 5.0:
            return None
        
        # Calculate distance from 21 EMA
        pct_from_21ema = ((context.current_price - context.ma_21) / context.ma_21) * 100
        
        # Must be near 21 EMA (within threshold)
        if abs(pct_from_21ema) > self.ema_21_bounce_pct:
            return None
        
        # Check for bounce pattern (was below, now at or above)
        if not self._detect_bounce(context.symbol, context.ma_21):
            return None
        
        # Volume should be at least average
        if context.volume_ratio < self.bounce_volume_min:
            return None
        
        message = (
            f"📈 21 EMA BOUNCE - ADD OPPORTUNITY\n\n"
            f"Price: {self.format_price(context.current_price)}\n"
            f"21 EMA: {self.format_price(context.ma_21)}\n"
            f"Distance: {pct_from_21ema:+.1f}%\n"
            f"Volume: {context.volume_ratio:.1f}x average\n\n"
            f"Current P&L: {self.format_pct(context.pnl_pct)}\n"
            f"State: {context.state} (room to add)\n\n"
            f"▶ POTENTIAL ADD POINT\n\n"
            f"IBD Rule: In strong uptrends, pullbacks to 21 EMA\n"
            f"can be excellent add points. Confirm with:\n"
            f"• Volume increasing on bounce\n"
            f"• Market in confirmed uptrend\n"
            f"• RS line holding up"
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.EMA_21)
        self._bounce_detected[context.symbol] = datetime.now()
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.ADD,
            subtype=AlertSubtype.EMA_21,
            message=message,
            action="CONSIDER ADD - 21 EMA BOUNCE",
            priority="P2",
        )
    
    def _check_50ma_bounce(self, context: PositionContext) -> Optional[AlertData]:
        """
        Check for bounce off 50 MA.
        
        IBD Rule: The 50-day MA is key support. A bounce with volume
        after a controlled pullback is often a strong add point.
        """
        if context.ma_50 is None:
            return None
        
        if self.is_on_cooldown(context.symbol, AlertSubtype.PULLBACK):
            return None
        
        # Only consider if stock is performing (up 8%+ from entry)
        if context.pnl_pct < 8.0:
            return None
        
        # Calculate distance from 50 MA
        pct_from_50ma = ((context.current_price - context.ma_50) / context.ma_50) * 100
        
        # Must be near 50 MA (within threshold)
        if pct_from_50ma < 0 or pct_from_50ma > self.ma_50_bounce_pct:
            return None
        
        # Check for bounce pattern
        if not self._detect_bounce(context.symbol, context.ma_50):
            return None
        
        # Volume should be increasing on bounce
        if context.volume_ratio < 1.2:  # Want above average volume
            return None
        
        message = (
            f"📈 50 MA BOUNCE - ADD OPPORTUNITY\n\n"
            f"Price: {self.format_price(context.current_price)}\n"
            f"50 MA: {self.format_price(context.ma_50)}\n"
            f"Distance: +{pct_from_50ma:.1f}% above 50 MA\n"
            f"Volume: {context.volume_ratio:.1f}x average\n\n"
            f"Current P&L: {self.format_pct(context.pnl_pct)}\n"
            f"State: {context.state} (room to add)\n\n"
            f"▶ STRONG ADD OPPORTUNITY\n\n"
            f"IBD Rule: 50 MA bounces with volume are high-probability\n"
            f"add points. The 50 MA acts as institutional support.\n"
            f"• Best when market is in confirmed uptrend\n"
            f"• Use smaller add size than initial entry"
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.PULLBACK)
        self._bounce_detected[context.symbol] = datetime.now()
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.ADD,
            subtype=AlertSubtype.PULLBACK,
            message=message,
            action="ADD - 50 MA BOUNCE",
            priority="P1",
        )
    
    def _check_pivot_retest(self, context: PositionContext) -> Optional[AlertData]:
        """
        Check for retest of original pivot point.
        
        Many successful breakouts pull back to test the pivot.
        This can be a second-chance entry point.
        """
        if context.pivot_price is None or context.pivot_price <= 0:
            return None
        
        if self.is_on_cooldown(context.symbol, AlertSubtype.IN_BUY_ZONE):
            return None
        
        # Calculate distance from pivot
        pct_from_pivot = ((context.current_price - context.pivot_price) / context.pivot_price) * 100
        
        # Must be near pivot (within threshold, and above it)
        if pct_from_pivot < 0 or pct_from_pivot > self.pivot_retest_pct:
            return None
        
        # Should have been higher at some point (actual retest, not first touch)
        if context.max_gain_pct < 5.0:
            return None
        
        message = (
            f"🔄 PIVOT RETEST - ADD OPPORTUNITY\n\n"
            f"Price: {self.format_price(context.current_price)}\n"
            f"Pivot: {self.format_price(context.pivot_price)}\n"
            f"Distance: +{pct_from_pivot:.1f}% above pivot\n\n"
            f"Max Gain Was: +{context.max_gain_pct:.1f}%\n"
            f"Current P&L: {self.format_pct(context.pnl_pct)}\n\n"
            f"▶ SECOND-CHANCE ENTRY\n\n"
            f"IBD Rule: Many successful breakouts pull back to\n"
            f"test the pivot point. This retest can be a lower-risk\n"
            f"entry point with a tighter stop.\n"
            f"• Set stop just below pivot\n"
            f"• Smaller position size than initial"
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.IN_BUY_ZONE)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.ADD,
            subtype=AlertSubtype.IN_BUY_ZONE,
            message=message,
            action="CONSIDER ADD - PIVOT RETEST",
            priority="P2",
        )
    
    def _check_pullback_to_buy_zone(self, context: PositionContext) -> Optional[AlertData]:
        """
        Check for pullback into the buy zone (0-5% above pivot).
        
        If stock ran up and pulled back into the buy zone,
        this may be an add opportunity.
        """
        if context.pivot_price is None or context.pivot_price <= 0:
            return None
        
        # Use a different subtype for general buy zone vs specific pivot retest
        if self.is_on_cooldown(context.symbol, AlertSubtype.PULLBACK):
            return None
        
        # Calculate distance from pivot
        pct_from_pivot = ((context.current_price - context.pivot_price) / context.pivot_price) * 100
        
        # Must be in buy zone (0-5% above pivot)
        if pct_from_pivot < 0 or pct_from_pivot > self.buy_zone_max_pct:
            return None
        
        # Must have been extended at some point (>5% above pivot)
        if context.max_gain_pct < 7.0:
            return None
        
        # Skip if we already alerted on pivot retest (which is more specific)
        if pct_from_pivot <= self.pivot_retest_pct:
            return None
        
        message = (
            f"📍 PULLBACK TO BUY ZONE\n\n"
            f"Price: {self.format_price(context.current_price)}\n"
            f"Pivot: {self.format_price(context.pivot_price)}\n"
            f"Buy Zone: {self.format_price(context.pivot_price)} - "
            f"{self.format_price(context.pivot_price * 1.05)}\n"
            f"Current Position: +{pct_from_pivot:.1f}% above pivot\n\n"
            f"Max Gain Was: +{context.max_gain_pct:.1f}%\n"
            f"Current P&L: {self.format_pct(context.pnl_pct)}\n\n"
            f"▶ ADD OPPORTUNITY\n\n"
            f"Stock pulled back from extended levels into\n"
            f"the optimal buy zone. Consider adding if:\n"
            f"• Volume is constructive (not heavy selling)\n"
            f"• Market is supportive\n"
            f"• RS line holding up"
        )
        
        self.set_cooldown(context.symbol, AlertSubtype.PULLBACK)
        
        return self.create_alert(
            context=context,
            alert_type=AlertType.ADD,
            subtype=AlertSubtype.PULLBACK,
            message=message,
            action="CONSIDER ADD - IN BUY ZONE",
            priority="P2",
        )
    
    def _detect_bounce(self, symbol: str, ma_level: float) -> bool:
        """
        Detect if price bounced off a moving average.
        
        Requires price history to see if we touched/crossed
        the MA and are now moving away from it.
        """
        prices = self._previous_prices.get(symbol, [])
        
        if len(prices) < 2:
            return False
        
        # Check if recent prices touched or went below MA
        touched_ma = False
        for price in prices[-3:]:  # Look at last 3 prices
            if price <= ma_level * 1.01:  # Within 1% or below
                touched_ma = True
                break
        
        return touched_ma
    
    def _update_price_tracking(self, context: PositionContext):
        """Update price history for bounce detection."""
        symbol = context.symbol
        
        if symbol not in self._previous_prices:
            self._previous_prices[symbol] = []
        
        self._previous_prices[symbol].append(context.current_price)
        
        # Keep only last 10 prices
        if len(self._previous_prices[symbol]) > 10:
            self._previous_prices[symbol] = self._previous_prices[symbol][-10:]
