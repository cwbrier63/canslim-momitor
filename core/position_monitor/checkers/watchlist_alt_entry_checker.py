"""
Watchlist Alternative Entry Checker - MA bounce alerts for extended watchlist items.

Monitors watchlist positions (state=0) that are:
1. Extended from pivot (>5% above pivot)
2. Pulling back to key moving averages (21 EMA, 50 MA)
3. Showing volume and reversal characteristics

Alerts:
- ALT_ENTRY | MA_BOUNCE: Price near 21 EMA or 50 MA after being extended
- ALT_ENTRY | PIVOT_RETEST: Price returned to original pivot zone
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData
from canslim_monitor.utils.discord_formatters import build_alt_entry_embed

from .base_checker import BaseChecker, PositionContext


class WatchlistAltEntryChecker(BaseChecker):
    """
    Check watchlist items for alternative entry opportunities.

    IBD Rules for alternative entries on watchlist:
    - Stock must be EXTENDED (>5% above pivot) first
    - Pullback to 21 EMA or 50 MA with volume
    - First/second test of MA is highest probability
    - Must be in confirmed market uptrend
    """

    @property
    def name(self) -> str:
        return "watchlist_alt_entry"

    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        super().__init__(config, logger)

        # Alt entry config
        alt_config = config.get('alt_entry', {}) if config else {}

        # Must be extended before we watch for pullback
        self.min_extension_pct = alt_config.get('min_extension_pct', 5.0)  # >5% above pivot

        # MA bounce thresholds
        self.ema_21_bounce_pct = alt_config.get('ema_21_bounce_pct', 1.5)  # Within 1.5% of 21 EMA
        self.ma_50_bounce_pct = alt_config.get('ma_50_bounce_pct', 2.0)   # Within 2% of 50 MA
        self.bounce_volume_min = alt_config.get('bounce_volume_min', 0.7)  # At least 70% avg volume

        # Pivot retest
        self.pivot_retest_pct = alt_config.get('pivot_retest_pct', 3.0)  # Within 3% of pivot (buy zone)

        # Cooldown hours
        self.cooldown_hours = alt_config.get('cooldown_hours', 4)

        # Track which symbols have been marked as extended
        self._extended_symbols: Dict[str, datetime] = {}

        # Track MA test counts per symbol
        self._ma_test_counts: Dict[str, int] = {}

    def should_check(self, context: PositionContext) -> bool:
        """Only check watchlist positions (state 0)."""
        return context.state == 0

    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """Check watchlist items for alternative entry opportunities."""
        if not self.should_check(context):
            return []

        # Need pivot price for calculations
        pivot = context.pivot_price
        if not pivot or pivot <= 0:
            return []

        alerts = []

        # Calculate distance from pivot
        pct_from_pivot = ((context.current_price - pivot) / pivot) * 100

        # First, check if stock is/was extended
        is_currently_extended = pct_from_pivot > self.min_extension_pct
        was_extended = context.symbol in self._extended_symbols

        # Mark as extended if currently extended
        if is_currently_extended:
            self._extended_symbols[context.symbol] = datetime.now()
            self.logger.debug(
                f"{context.symbol}: Marked as EXTENDED ({pct_from_pivot:.1f}% above pivot)"
            )
            return []  # Don't alert when extended, wait for pullback

        # Only check for pullback if it WAS extended previously
        if not was_extended:
            return []

        # Check how long ago it was extended (expire after 30 days)
        extended_date = self._extended_symbols[context.symbol]
        days_since_extended = (datetime.now() - extended_date).days
        if days_since_extended > 30:
            del self._extended_symbols[context.symbol]
            self._ma_test_counts.pop(context.symbol, None)
            return []

        # Now check for pullback entries

        # Check 21 EMA pullback
        ema_alert = self._check_21ema_pullback(context, pivot, pct_from_pivot)
        if ema_alert:
            alerts.append(ema_alert)

        # Check 50 MA pullback (only if no 21 EMA alert to avoid duplicate)
        if not ema_alert:
            ma_alert = self._check_50ma_pullback(context, pivot, pct_from_pivot)
            if ma_alert:
                alerts.append(ma_alert)

        # Check pivot retest (only if no MA alerts)
        if not alerts:
            pivot_alert = self._check_pivot_retest(context, pivot, pct_from_pivot)
            if pivot_alert:
                alerts.append(pivot_alert)

        return alerts

    def _check_21ema_pullback(
        self,
        context: PositionContext,
        pivot: float,
        pct_from_pivot: float
    ) -> Optional[AlertData]:
        """
        Check for pullback to 21 EMA on watchlist item.

        IBD Rule: After a stock extends from pivot, a pullback to
        21 EMA offers a lower-risk entry point.
        """
        if context.ma_21 is None or context.ma_21 <= 0:
            return None

        if self.is_on_cooldown(context.symbol, AlertSubtype.MA_BOUNCE):
            return None

        # Calculate distance from 21 EMA
        pct_from_21ema = ((context.current_price - context.ma_21) / context.ma_21) * 100

        # Must be near 21 EMA (within threshold, slightly above or below)
        if abs(pct_from_21ema) > self.ema_21_bounce_pct:
            return None

        # 21 EMA must be above pivot (uptrend)
        if context.ma_21 < pivot:
            return None

        # Volume should be reasonable (not bone dry)
        if context.volume_ratio < self.bounce_volume_min:
            return None

        # Increment MA test count
        test_count = self._ma_test_counts.get(context.symbol, 0) + 1
        self._ma_test_counts[context.symbol] = test_count

        # First/second test is highest probability
        probability = "HIGH" if test_count <= 2 else "MODERATE"

        line2 = f"21 EMA: ${context.ma_21:.2f} ({pct_from_21ema:+.1f}%) | Test #{test_count} ({probability})"
        message = build_alt_entry_embed(
            symbol=context.symbol,
            price=context.current_price,
            pivot_price=pivot,
            subtype='MA_BOUNCE',
            line2_data=line2,
            action=f"BUY - 21 EMA pullback (Test #{test_count})",
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            market_regime=context.market_regime,
            priority='P1',
            custom_title=f"ALT ENTRY - 21 EMA: {context.symbol}",
        )

        self.set_cooldown(context.symbol, AlertSubtype.MA_BOUNCE)

        return self.create_alert(
            context=context,
            alert_type=AlertType.ALT_ENTRY,
            subtype=AlertSubtype.MA_BOUNCE,
            message=message,
            action=f"BUY - 21 EMA pullback (Test #{test_count})",
            priority="P1",
        )

    def _check_50ma_pullback(
        self,
        context: PositionContext,
        pivot: float,
        pct_from_pivot: float
    ) -> Optional[AlertData]:
        """
        Check for pullback to 50 MA on watchlist item.

        IBD Rule: The 50-day MA is key support. A pullback to this
        level after extension is a strong alternative entry.
        """
        if context.ma_50 is None or context.ma_50 <= 0:
            return None

        # Use different cooldown key for 50 MA
        cooldown_key = f"{context.symbol}_50MA_BOUNCE"
        if cooldown_key in self._cooldowns:
            if datetime.now() < self._cooldowns[cooldown_key]:
                return None

        # Calculate distance from 50 MA
        pct_from_50ma = ((context.current_price - context.ma_50) / context.ma_50) * 100

        # Must be near 50 MA (within threshold)
        if abs(pct_from_50ma) > self.ma_50_bounce_pct:
            return None

        # 50 MA must be above or near pivot (uptrend)
        ma_50_vs_pivot = ((context.ma_50 - pivot) / pivot) * 100
        if ma_50_vs_pivot < -5:  # 50 MA more than 5% below pivot is bearish
            return None

        # Volume should be reasonable
        if context.volume_ratio < self.bounce_volume_min:
            return None

        # Increment MA test count
        test_count = self._ma_test_counts.get(context.symbol, 0) + 1
        self._ma_test_counts[context.symbol] = test_count

        probability = "HIGH" if test_count <= 2 else "MODERATE"

        line2 = f"50 MA: ${context.ma_50:.2f} ({pct_from_50ma:+.1f}%) | Test #{test_count} ({probability})"
        message = build_alt_entry_embed(
            symbol=context.symbol,
            price=context.current_price,
            pivot_price=pivot,
            subtype='MA_BOUNCE',
            line2_data=line2,
            action=f"BUY - 50 MA pullback (Test #{test_count})",
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            market_regime=context.market_regime,
            priority='P1',
            custom_title=f"ALT ENTRY - 50 MA: {context.symbol}",
        )

        # Set cooldown
        self._cooldowns[cooldown_key] = datetime.now() + timedelta(hours=self.cooldown_hours)

        return self.create_alert(
            context=context,
            alert_type=AlertType.ALT_ENTRY,
            subtype=AlertSubtype.MA_BOUNCE,
            message=message,
            action=f"BUY - 50 MA pullback (Test #{test_count})",
            priority="P1",
        )

    def _check_pivot_retest(
        self,
        context: PositionContext,
        pivot: float,
        pct_from_pivot: float
    ) -> Optional[AlertData]:
        """
        Check for retest of original pivot.

        IBD Rule: Price returning to the original pivot zone
        after extending is a potential re-entry point.
        """
        if self.is_on_cooldown(context.symbol, AlertSubtype.PIVOT_RETEST):
            return None

        # Must be near pivot (within buy zone: 0% to pivot_retest_pct above)
        if pct_from_pivot < -1.0 or pct_from_pivot > self.pivot_retest_pct:
            return None

        # Volume should be reasonable
        if context.volume_ratio < self.bounce_volume_min:
            return None

        buy_zone_top = pivot * (1 + 0.05)  # 5% buy zone

        line2 = f"Pivot: ${pivot:.2f} ({pct_from_pivot:+.1f}%) | Zone: ${pivot:.2f}-${buy_zone_top:.2f}"
        message = build_alt_entry_embed(
            symbol=context.symbol,
            price=context.current_price,
            pivot_price=pivot,
            subtype='PIVOT_RETEST',
            line2_data=line2,
            action="BUY - Pivot retest entry",
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            market_regime=context.market_regime,
            priority='P1',
            custom_title=f"ALT ENTRY - PIVOT RETEST: {context.symbol}",
        )

        self.set_cooldown(context.symbol, AlertSubtype.PIVOT_RETEST)

        return self.create_alert(
            context=context,
            alert_type=AlertType.ALT_ENTRY,
            subtype=AlertSubtype.PIVOT_RETEST,
            message=message,
            action="BUY - Pivot retest entry",
            priority="P1",
        )

    def clear_extended_tracking(self, symbol: str = None):
        """
        Clear extended tracking for a symbol or all symbols.

        Call this when a position transitions from watchlist to active.
        """
        if symbol:
            self._extended_symbols.pop(symbol, None)
            self._ma_test_counts.pop(symbol, None)
        else:
            self._extended_symbols.clear()
            self._ma_test_counts.clear()
