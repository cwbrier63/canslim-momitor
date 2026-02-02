"""
Health Checker - Health score and earnings alerts.

Alerts:
- CRITICAL: Health score below 50
- EARNINGS: Earnings approaching with P&L-based recommendation
- LATE_STAGE: Stage 4+ risk warning
"""

from typing import List, Dict, Any
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData
from canslim_monitor.utils.health_calculator import HealthCalculator, HealthRating
from canslim_monitor.utils.discord_formatters import build_health_embed, build_position_embed

from .base_checker import BaseChecker, PositionContext


class HealthChecker(BaseChecker):
    """
    Check positions for health concerns and earnings proximity.
    
    Uses the existing HealthCalculator for scoring, then
    generates alerts based on threshold crossings.
    """
    
    @property
    def name(self) -> str:
        return "health"
    
    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        super().__init__(config, logger)
        
        # Health config
        health_config = config.get('health', {}) if config else {}
        self.time_threshold_days = health_config.get('time_threshold_days', 60)
        self.deep_base_threshold = health_config.get('deep_base_threshold', 35.0)
        
        # Earnings config
        earnings_config = config.get('earnings', {}) if config else {}
        self.earnings_warning_days = earnings_config.get('warning_days', 14)
        self.earnings_critical_days = earnings_config.get('critical_days', 5)
        self.earnings_negative_threshold = earnings_config.get('negative_threshold', 0.0)
        self.earnings_reduce_threshold = earnings_config.get('reduce_threshold', 10.0)
        
        # Initialize health calculator
        self.health_calc = HealthCalculator(
            time_threshold_days=self.time_threshold_days,
            deep_base_threshold=self.deep_base_threshold,
            earnings_warning_days=self.earnings_critical_days,
            earnings_negative_threshold=self.earnings_negative_threshold,
            earnings_reduce_threshold=self.earnings_reduce_threshold,
        )
        
        # Extended from pivot config
        # IBD Rule: Don't chase stocks more than 5% above proper buy point
        extended_config = config.get('extended', {}) if config else {}
        self.extended_warning_pct = extended_config.get('warning_pct', 5.0)  # 5% above pivot
        self.extended_danger_pct = extended_config.get('danger_pct', 10.0)  # 10%+ very extended
        
        # Track previous health scores for change detection
        self._previous_health: Dict[str, int] = {}
    
    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """Check for health concerns."""
        if not self.should_check(context):
            return []
        
        alerts = []
        
        # Get position attributes with defaults
        tp1_pct = 20.0
        base_depth = 0
        if position is not None:
            tp1_pct = getattr(position, 'tp1_pct', None) or 20.0
            base_depth = getattr(position, 'base_depth', None) or 0
        
        # Calculate current health
        health_result = self.health_calc.calculate(
            state=context.state,
            days_in_position=context.days_in_position,
            current_pnl_pct=context.pnl_pct,
            tp1_pct=tp1_pct,
            current_price=context.current_price,
            ma_21ema=context.ma_21 or 0,
            ma_50=context.ma_50 or 0,
            ma_200=context.ma_200 or 0,
            ad_rating=context.ad_rating or "",
            base_stage=context.base_stage,
            base_depth=base_depth,
            days_to_earnings=context.days_to_earnings or 0,
        )
        
        # Check for critical health
        critical_alert = self._check_health_critical(context, health_result)
        if critical_alert:
            alerts.append(critical_alert)
        
        # Check earnings proximity
        earnings_alert = self._check_earnings(context)
        if earnings_alert:
            alerts.append(earnings_alert)
        
        # Check late stage warning
        late_stage_alert = self._check_late_stage(context)
        if late_stage_alert:
            alerts.append(late_stage_alert)
        
        # Check extended from pivot
        extended_alert = self._check_extended_from_pivot(context)
        if extended_alert:
            alerts.append(extended_alert)
        
        # Update previous health tracking
        self._previous_health[context.symbol] = health_result.score
        
        return alerts
    
    def _check_health_critical(self, context: PositionContext, health_result) -> AlertData:
        """Check for critical health score."""
        if health_result.rating != HealthRating.CRITICAL:
            return None

        # Check if this is a new crossing into critical
        previous_score = self._previous_health.get(context.symbol, 100)
        if previous_score < 50:  # Already was critical
            if self.is_on_cooldown(context.symbol, AlertSubtype.CRITICAL):
                return None

        # Format warning codes (short)
        warning_codes = ", ".join(health_result.warning_codes[:3])

        # Build compact embed format
        line2 = f"Health: {health_result.score}/100 | {warning_codes}"
        message = build_health_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            subtype='CRITICAL',
            line2_data=line2,
            action="Consider reducing or exiting",
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
            priority='P0',
        )

        self.set_cooldown(context.symbol, AlertSubtype.CRITICAL)

        return self.create_alert(
            context=context,
            alert_type=AlertType.HEALTH,
            subtype=AlertSubtype.CRITICAL,
            message=message,
            action=health_result.action,
            priority="P0",
        )
    
    def _check_earnings(self, context: PositionContext) -> AlertData:
        """
        Check for earnings proximity with P&L-based recommendation.

        IBD Gap Fix: Different advice based on P&L position.
        """
        if context.days_to_earnings is None:
            return None

        # Determine urgency level
        if context.days_to_earnings > self.earnings_warning_days:
            return None

        if self.is_on_cooldown(context.symbol, AlertSubtype.EARNINGS):
            return None

        is_critical = context.days_to_earnings <= self.earnings_critical_days

        # P&L-based recommendation (IBD gap fix)
        recommendation = self._get_earnings_recommendation(context.pnl_pct)

        priority = "P0" if is_critical else "P1"

        # Build context description
        if context.pnl_pct >= self.earnings_reduce_threshold:
            earnings_context = "Up - can hold with stop"
        elif context.pnl_pct >= self.earnings_negative_threshold:
            earnings_context = "Near BE - sell to avoid gap risk"
        else:
            earnings_context = "Down - exit before ER"

        # Build compact embed format
        line2 = f"Earnings in {context.days_to_earnings} days | {earnings_context}"
        message = build_health_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            subtype='EARNINGS',
            line2_data=line2,
            action=recommendation['action'],
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
            priority=priority,
        )

        self.set_cooldown(context.symbol, AlertSubtype.EARNINGS)

        return self.create_alert(
            context=context,
            alert_type=AlertType.HEALTH,
            subtype=AlertSubtype.EARNINGS,
            message=message,
            action=recommendation['action'],
            priority=priority,
        )
    
    def _get_earnings_recommendation(self, pnl_pct: float) -> Dict[str, str]:
        """
        Get P&L-based earnings recommendation.
        
        IBD Gap Fix: Different advice based on profit/loss position.
        """
        if pnl_pct >= self.earnings_reduce_threshold:
            return {
                'action': 'HOLD WITH TRAILING STOP',
                'reason': f"Position is up {pnl_pct:.1f}%. Consider holding through "
                         f"with a trailing stop to protect gains."
            }
        elif pnl_pct >= self.earnings_negative_threshold:
            return {
                'action': 'SELL BEFORE EARNINGS',
                'reason': f"Position near breakeven ({pnl_pct:+.1f}%). "
                         f"Gap down risk outweighs potential upside."
            }
        else:
            return {
                'action': 'EXIT BEFORE EARNINGS',
                'reason': f"Position is down {pnl_pct:.1f}%. "
                         f"Don't add earnings risk to an already losing position."
            }
    
    def _check_late_stage(self, context: PositionContext) -> AlertData:
        """Check for late-stage base warning."""
        if context.base_stage < 4:
            return None

        if self.is_on_cooldown(context.symbol, AlertSubtype.LATE_STAGE):
            return None

        # Build compact embed format
        line2 = f"Stage: {context.base_stage} | Higher failure rate"
        message = build_health_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            subtype='LATE_STAGE',
            line2_data=line2,
            action="Tighter stops, take profits earlier",
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
            priority='P2',
        )

        self.set_cooldown(context.symbol, AlertSubtype.LATE_STAGE)

        return self.create_alert(
            context=context,
            alert_type=AlertType.HEALTH,
            subtype=AlertSubtype.LATE_STAGE,
            message=message,
            action="USE TIGHTER STOPS",
            priority="P2",
        )
    
    def _check_extended_from_pivot(self, context: PositionContext) -> AlertData:
        """
        Check if price is extended from pivot buy point.

        IBD Rule: Don't chase stocks more than 5% above the proper buy point.
        Most breakouts that succeed pull back to the buy zone within a few days.
        """
        if context.pivot_price is None or context.pivot_price <= 0:
            return None

        if self.is_on_cooldown(context.symbol, AlertSubtype.EXTENDED):
            return None

        # Calculate extension from pivot
        pct_above_pivot = ((context.current_price - context.pivot_price) / context.pivot_price) * 100

        # Only alert if extended above warning threshold
        if pct_above_pivot < self.extended_warning_pct:
            return None

        is_danger = pct_above_pivot >= self.extended_danger_pct
        priority = "P1" if is_danger else "P2"

        # Different advice based on how extended
        if is_danger:
            action = "No new buys - wait for pullback"
        else:
            action = "No new buys - wait for pullback to add"

        # Build compact embed format
        line2 = f"Extension: +{pct_above_pivot:.1f}% above pivot (max 5%)"
        message = build_health_embed(
            symbol=context.symbol,
            price=context.current_price,
            entry_price=context.entry_price,
            pnl_pct=context.pnl_pct,
            subtype='EXTENDED',
            line2_data=line2,
            action=action,
            ma_21=context.ma_21,
            ma_50=context.ma_50,
            days_in_position=context.days_in_position,
            market_regime=context.market_regime,
            priority=priority,
        )

        self.set_cooldown(context.symbol, AlertSubtype.EXTENDED)

        return self.create_alert(
            context=context,
            alert_type=AlertType.HEALTH,
            subtype=AlertSubtype.EXTENDED,
            message=message,
            action=action,
            priority=priority,
        )
