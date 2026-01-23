"""
CANSLIM Monitor - Health Calculator
====================================
Calculates position health score based on IBD methodology.

Health score components (from TrendSpider V3.6):
- Time warnings (60+ days without progress)
- Moving average position (below 50MA, below 200MA)
- Volume patterns (distribution days)
- A/D Rating concerns (D or E ratings)
- Up/Down Volume Ratio
- Base stage (late stage penalty)
- Earnings proximity (with P&L consideration)
- Base depth (too deep warning)

Version: 1.0
Created: January 15, 2026
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from datetime import datetime, date


class HealthRating(Enum):
    """Health rating categories."""
    HEALTHY = "HEALTHY"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class HealthWarning:
    """Individual health warning component."""
    code: str           # Short code (e.g., "<50MA")
    description: str    # Human-readable description
    score: int          # Points added to health score
    category: str       # Category (time, technical, fundamental, etc.)
    severity: str       # low, medium, high


@dataclass
class HealthResult:
    """Complete health assessment result."""
    # Overall assessment
    score: int
    rating: HealthRating
    primary_warning: str        # Most important warning
    
    # Individual components
    warnings: List[HealthWarning]
    warning_codes: List[str]    # Short codes for display
    
    # Recommendations
    action: str                 # HOLD, REDUCE, SELL
    urgency: str               # low, medium, high
    
    # Colors for UI
    color: str                 # Text color
    bg_color: str              # Background color
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'score': self.score,
            'rating': self.rating.value,
            'primary_warning': self.primary_warning,
            'warnings': [
                {
                    'code': w.code,
                    'description': w.description,
                    'score': w.score,
                    'category': w.category,
                    'severity': w.severity
                } for w in self.warnings
            ],
            'warning_codes': self.warning_codes,
            'action': self.action,
            'urgency': self.urgency,
            'color': self.color,
            'bg_color': self.bg_color
        }


class HealthCalculator:
    """
    Calculate position health score.
    
    Score thresholds:
    - HEALTHY: 0-1 points
    - CAUTION: 2-3 points
    - WARNING: 4-5 points
    - CRITICAL: 6+ points
    """
    
    # Rating thresholds
    CAUTION_THRESHOLD = 2
    WARNING_THRESHOLD = 4
    CRITICAL_THRESHOLD = 6
    
    # Colors for UI
    COLORS = {
        HealthRating.HEALTHY: ("#00FF00", "#003300"),    # Green
        HealthRating.CAUTION: ("#FFFF00", "#666600"),    # Yellow
        HealthRating.WARNING: ("#FFA500", "#664400"),    # Orange
        HealthRating.CRITICAL: ("#FF0000", "#660000"),   # Red
    }
    
    def __init__(
        self,
        time_threshold_days: int = 60,
        tp1_progress_threshold: float = 0.5,
        deep_base_threshold: float = 35.0,
        earnings_warning_days: int = 5,
        earnings_negative_threshold: float = 0.0,
        earnings_reduce_threshold: float = 10.0,
        ud_ratio_warning: float = 0.8,
    ):
        """
        Initialize health calculator.
        
        Args:
            time_threshold_days: Days without progress before warning
            tp1_progress_threshold: % of TP1 that should be achieved
            deep_base_threshold: Base depth % considered "too deep"
            earnings_warning_days: Days before earnings to trigger warning
            earnings_negative_threshold: P&L % below which earnings is SELL
            earnings_reduce_threshold: P&L % below which earnings is REDUCE
            ud_ratio_warning: Up/Down ratio below which to warn
        """
        self.time_threshold_days = time_threshold_days
        self.tp1_progress_threshold = tp1_progress_threshold
        self.deep_base_threshold = deep_base_threshold
        self.earnings_warning_days = earnings_warning_days
        self.earnings_negative_threshold = earnings_negative_threshold
        self.earnings_reduce_threshold = earnings_reduce_threshold
        self.ud_ratio_warning = ud_ratio_warning
    
    def calculate(
        self,
        # Position data
        state: int,
        days_in_position: int,
        current_pnl_pct: float,
        tp1_pct: float = 20.0,
        
        # Price/MA data
        current_price: float = 0,
        ma_21ema: float = 0,
        ma_50: float = 0,
        ma_200: float = 0,
        
        # Volume data
        current_volume: int = 0,
        avg_volume_50: int = 0,
        is_down_day: bool = False,
        
        # MarketSurge data
        ad_rating: str = "",
        ud_vol_ratio: float = 0,
        base_stage: int = 1,
        base_depth: float = 0,
        
        # Earnings
        days_to_earnings: int = 0,
    ) -> HealthResult:
        """
        Calculate comprehensive health score.
        
        Args:
            state: Position state (1-6 for active positions)
            days_in_position: Days since entry
            current_pnl_pct: Current P&L percentage
            tp1_pct: TP1 target percentage
            current_price: Current stock price
            ma_21ema: 21-day EMA value
            ma_50: 50-day MA value
            ma_200: 200-day MA value
            current_volume: Today's volume
            avg_volume_50: 50-day average volume
            is_down_day: True if close < previous close
            ad_rating: A/D Rating (A-E)
            ud_vol_ratio: Up/Down Volume Ratio
            base_stage: Base stage number (1-5)
            base_depth: Base depth percentage
            days_to_earnings: Days until earnings (0 if unknown)
        
        Returns:
            HealthResult with complete assessment
        """
        warnings = []
        primary_warning = ""
        
        # Only calculate for active positions (state 1-6)
        if state < 1:
            return HealthResult(
                score=0,
                rating=HealthRating.HEALTHY,
                primary_warning="",
                warnings=[],
                warning_codes=[],
                action="N/A",
                urgency="none",
                color="#00FF00",
                bg_color="#003300"
            )
        
        # =====================================================================
        # TIME WARNINGS
        # =====================================================================
        expected_progress = tp1_pct * self.tp1_progress_threshold
        
        if (days_in_position > self.time_threshold_days and 
            current_pnl_pct < expected_progress and
            state <= 3):  # Only for building positions
            warnings.append(HealthWarning(
                code="60d no progress",
                description=f"60+ days in position with <{expected_progress:.0f}% gain",
                score=2,
                category="time",
                severity="medium"
            ))
            if not primary_warning:
                primary_warning = "60+ DAYS NO PROGRESS"
        
        # =====================================================================
        # MOVING AVERAGE WARNINGS
        # =====================================================================
        if current_price > 0:
            # Below 50 MA
            if ma_50 > 0 and current_price < ma_50:
                warnings.append(HealthWarning(
                    code="<50MA",
                    description="Price below 50-day moving average",
                    score=2,
                    category="technical",
                    severity="high"
                ))
                primary_warning = "BELOW 50 MA"
            
            # Below 200 MA (more severe)
            if ma_200 > 0 and current_price < ma_200:
                warnings.append(HealthWarning(
                    code="<200MA",
                    description="Price below 200-day moving average",
                    score=3,
                    category="technical",
                    severity="high"
                ))
                primary_warning = "BELOW 200 MA"
        
        # =====================================================================
        # VOLUME/DISTRIBUTION WARNINGS
        # =====================================================================
        if is_down_day and avg_volume_50 > 0 and current_volume > avg_volume_50 * 1.5:
            warnings.append(HealthWarning(
                code="DistDay",
                description="Distribution day detected (down on high volume)",
                score=2,
                category="volume",
                severity="medium"
            ))
            if not primary_warning:
                primary_warning = "DISTRIBUTION DAY"
        
        # =====================================================================
        # A/D RATING WARNINGS
        # =====================================================================
        if ad_rating:
            ad_upper = ad_rating.upper()
            if ad_upper == "E":
                warnings.append(HealthWarning(
                    code="A/D:E",
                    description="Heavy distribution (A/D Rating: E)",
                    score=3,
                    category="fundamental",
                    severity="high"
                ))
                if not primary_warning:
                    primary_warning = "HEAVY DISTRIBUTION (A/D: E)"
            elif ad_upper == "D":
                warnings.append(HealthWarning(
                    code="A/D:D",
                    description="Distribution detected (A/D Rating: D)",
                    score=2,
                    category="fundamental",
                    severity="medium"
                ))
        
        # =====================================================================
        # UP/DOWN VOLUME RATIO
        # =====================================================================
        if ud_vol_ratio > 0 and ud_vol_ratio < self.ud_ratio_warning:
            warnings.append(HealthWarning(
                code="U/D<0.8",
                description=f"Weak up/down volume ratio ({ud_vol_ratio:.2f})",
                score=1,
                category="volume",
                severity="low"
            ))
        
        # =====================================================================
        # BASE STAGE WARNINGS
        # =====================================================================
        if base_stage >= 4:
            warnings.append(HealthWarning(
                code="LateStage",
                description=f"Late stage base (Stage {base_stage})",
                score=2,
                category="fundamental",
                severity="medium"
            ))
            if not primary_warning:
                primary_warning = "LATE STAGE BASE"
        
        # =====================================================================
        # EARNINGS WARNINGS
        # =====================================================================
        if days_to_earnings > 0 and days_to_earnings <= self.earnings_warning_days:
            if current_pnl_pct < self.earnings_negative_threshold:
                warnings.append(HealthWarning(
                    code="ERneg",
                    description=f"Earnings in {days_to_earnings}d with negative P&L",
                    score=3,
                    category="earnings",
                    severity="high"
                ))
                primary_warning = "EARNINGS - NEGATIVE P&L"
            elif current_pnl_pct < self.earnings_reduce_threshold:
                warnings.append(HealthWarning(
                    code="ER<10%",
                    description=f"Earnings in {days_to_earnings}d with <10% profit cushion",
                    score=2,
                    category="earnings",
                    severity="medium"
                ))
        
        # =====================================================================
        # BASE DEPTH WARNINGS
        # =====================================================================
        if base_depth > self.deep_base_threshold:
            warnings.append(HealthWarning(
                code="TooDeep",
                description=f"Base too deep ({base_depth:.0f}%)",
                score=3,
                category="fundamental",
                severity="high"
            ))
            if not primary_warning:
                primary_warning = "BASE TOO DEEP"
        
        # =====================================================================
        # CALCULATE TOTAL SCORE AND RATING
        # =====================================================================
        total_score = sum(w.score for w in warnings)
        
        if total_score >= self.CRITICAL_THRESHOLD:
            rating = HealthRating.CRITICAL
            action = "SELL"
            urgency = "high"
        elif total_score >= self.WARNING_THRESHOLD:
            rating = HealthRating.WARNING
            action = "REDUCE"
            urgency = "medium"
        elif total_score >= self.CAUTION_THRESHOLD:
            rating = HealthRating.CAUTION
            action = "MONITOR"
            urgency = "low"
        else:
            rating = HealthRating.HEALTHY
            action = "HOLD"
            urgency = "none"
        
        # Get colors
        color, bg_color = self.COLORS[rating]
        
        # Build warning codes list
        warning_codes = [w.code for w in warnings]
        
        # Set primary warning if not already set
        if not primary_warning and warnings:
            primary_warning = " + ".join(warning_codes[:2])
        
        return HealthResult(
            score=total_score,
            rating=rating,
            primary_warning=primary_warning,
            warnings=warnings,
            warning_codes=warning_codes,
            action=action,
            urgency=urgency,
            color=color,
            bg_color=bg_color
        )
    
    def format_health_banner(self, result: HealthResult) -> str:
        """
        Format health warning for Discord alert.
        
        Args:
            result: HealthResult from calculate()
        
        Returns:
            Formatted warning string
        """
        if result.score < self.CAUTION_THRESHOLD:
            return ""
        
        emoji = {
            HealthRating.CAUTION: "⚠️",
            HealthRating.WARNING: "⚠️",
            HealthRating.CRITICAL: "🚨"
        }.get(result.rating, "")
        
        codes = ", ".join(result.warning_codes[:3])
        
        return f"{emoji} HEALTH: {result.rating.value} ({result.score}) - {codes}"
    
    def format_action_recommendation(self, result: HealthResult) -> str:
        """
        Format action recommendation for Discord alert.
        
        Args:
            result: HealthResult from calculate()
        
        Returns:
            Formatted action string
        """
        if result.action == "SELL":
            return f"🚨 ACTION RECOMMENDED: {result.action}\n   {result.primary_warning}"
        elif result.action == "REDUCE":
            return f"⚠️ ACTION RECOMMENDED: {result.action}\n   {result.primary_warning}"
        else:
            return ""


# =============================================================================
# 8-WEEK HOLD RULE CHECKER
# =============================================================================

class EightWeekHoldChecker:
    """
    Check and manage 8-week hold rule.
    
    IBD Rule: If a stock gains 20%+ within 1-3 weeks of breakout,
    hold for 8 weeks minimum to capture potential big winner.
    
    Exceptions:
    - If stock cuts into principal (falls below entry), sell
    - Hard stop always remains active for capital protection
    """
    
    def __init__(
        self,
        gain_threshold_pct: float = 20.0,
        trigger_window_weeks: int = 3,
        hold_period_weeks: int = 8
    ):
        """
        Initialize 8-week hold checker.
        
        Args:
            gain_threshold_pct: Minimum gain to trigger rule (default 20%)
            trigger_window_weeks: Weeks from breakout to trigger (default 3)
            hold_period_weeks: Weeks to hold (default 8)
        """
        self.gain_threshold_pct = gain_threshold_pct
        self.trigger_window_weeks = trigger_window_weeks
        self.hold_period_weeks = hold_period_weeks
    
    def check_trigger(
        self,
        gain_from_pivot_pct: float,
        weeks_since_breakout: int
    ) -> bool:
        """
        Check if 8-week hold rule should trigger.
        
        Args:
            gain_from_pivot_pct: Current gain from breakout pivot
            weeks_since_breakout: Weeks since breakout date
        
        Returns:
            True if 8-week hold should be activated
        """
        return (
            gain_from_pivot_pct >= self.gain_threshold_pct and
            weeks_since_breakout <= self.trigger_window_weeks
        )
    
    def calculate_hold_status(
        self,
        is_active: bool,
        weeks_since_breakout: int,
        current_pnl_pct: float = 0
    ) -> Dict[str, Any]:
        """
        Calculate 8-week hold status.
        
        Args:
            is_active: Whether 8-week hold is currently active
            weeks_since_breakout: Weeks since breakout date
            current_pnl_pct: Current P&L percentage from avg cost
        
        Returns:
            Dict with hold status information
        """
        if not is_active:
            return {
                'active': False,
                'weeks_remaining': 0,
                'suppress_tp1': False,
                'recommendation': 'Normal profit rules apply'
            }
        
        weeks_remaining = max(0, self.hold_period_weeks - weeks_since_breakout)
        
        # Check if should exit early due to cutting into principal
        if current_pnl_pct < 0:
            return {
                'active': True,
                'weeks_remaining': weeks_remaining,
                'suppress_tp1': False,  # Allow selling
                'override_reason': 'cutting_into_principal',
                'recommendation': 'SELL - Stock cutting into principal despite power move'
            }
        
        if weeks_remaining > 0:
            return {
                'active': True,
                'weeks_remaining': weeks_remaining,
                'suppress_tp1': True,
                'recommendation': f'HOLD - {weeks_remaining} weeks remaining in 8-week hold'
            }
        else:
            return {
                'active': True,
                'weeks_remaining': 0,
                'suppress_tp1': False,  # Allow normal TP after expiry
                'recommendation': '8-week hold complete - Resume normal profit rules'
            }


# =============================================================================
# STANDALONE TESTING
# =============================================================================

def main():
    """Test the health calculator."""
    calc = HealthCalculator()
    
    print("=" * 60)
    print("HEALTH CALCULATOR TEST")
    print("=" * 60)
    
    # Test case 1: Healthy position
    print("\n--- Test 1: Healthy Position ---")
    result = calc.calculate(
        state=1,
        days_in_position=15,
        current_pnl_pct=8.5,
        current_price=52.00,
        ma_50=48.00,
        ma_200=42.00,
        ad_rating="B",
        base_stage=1
    )
    print(f"Score: {result.score}")
    print(f"Rating: {result.rating.value}")
    print(f"Action: {result.action}")
    
    # Test case 2: Warning - below 50 MA with distribution
    print("\n--- Test 2: Warning Position ---")
    result = calc.calculate(
        state=2,
        days_in_position=45,
        current_pnl_pct=3.2,
        current_price=47.00,
        ma_50=50.00,
        ma_200=42.00,
        current_volume=2000000,
        avg_volume_50=1000000,
        is_down_day=True,
        ad_rating="D",
        base_stage=3
    )
    print(f"Score: {result.score}")
    print(f"Rating: {result.rating.value}")
    print(f"Primary Warning: {result.primary_warning}")
    print(f"Warnings: {result.warning_codes}")
    print(f"Action: {result.action}")
    print(f"\nDiscord Banner: {calc.format_health_banner(result)}")
    
    # Test case 3: Critical - below 200 MA, earnings, late stage
    print("\n--- Test 3: Critical Position ---")
    result = calc.calculate(
        state=3,
        days_in_position=75,
        current_pnl_pct=-2.5,
        tp1_pct=20.0,
        current_price=38.00,
        ma_50=45.00,
        ma_200=48.00,
        ad_rating="E",
        base_stage=4,
        base_depth=42,
        days_to_earnings=3
    )
    print(f"Score: {result.score}")
    print(f"Rating: {result.rating.value}")
    print(f"Primary Warning: {result.primary_warning}")
    print(f"Warnings: {result.warning_codes}")
    print(f"Action: {result.action}")
    print(f"\nDiscord Banner: {calc.format_health_banner(result)}")
    print(f"Recommendation: {calc.format_action_recommendation(result)}")
    
    # Test 8-week hold
    print("\n" + "=" * 60)
    print("8-WEEK HOLD RULE TEST")
    print("=" * 60)
    
    hold_checker = EightWeekHoldChecker()
    
    # Check trigger
    print("\n--- Trigger Check ---")
    print(f"+22% in week 2: {hold_checker.check_trigger(22.0, 2)}")  # True
    print(f"+18% in week 2: {hold_checker.check_trigger(18.0, 2)}")  # False
    print(f"+25% in week 5: {hold_checker.check_trigger(25.0, 5)}")  # False (too late)
    
    # Check status
    print("\n--- Hold Status ---")
    status = hold_checker.calculate_hold_status(True, 4, 15.0)
    print(f"Week 4, +15%: {status['recommendation']}")
    
    status = hold_checker.calculate_hold_status(True, 4, -3.0)
    print(f"Week 4, -3%: {status['recommendation']}")


if __name__ == "__main__":
    main()
