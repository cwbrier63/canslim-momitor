"""
CANSLIM Monitor - Pivot Status Calculator
==========================================
Determines pivot freshness for filtering stale setups.

Pivot Status Definitions:
    FRESH:    Price within buy zone (< 5% above pivot) and set within 10 days
    AGING:    5-15% above pivot OR 10-30 days since pivot was set
    STALE:    > 30 days since pivot was set
    EXTENDED: > 15% above pivot (may still be tradeable on pullback)
"""

from datetime import date, timedelta
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class PivotAnalysis:
    """Result of pivot status analysis."""
    status: str  # FRESH, AGING, STALE, EXTENDED
    distance_pct: float  # Current % above/below pivot
    days_since_set: int  # Days since pivot was set
    message: str  # Human-readable status message
    is_actionable: bool  # True if setup is still tradeable
    
    @property
    def emoji(self) -> str:
        """Get status emoji."""
        return {
            'FRESH': '🟢',
            'AGING': '🟡', 
            'STALE': '⚪',
            'EXTENDED': '🔴',
        }.get(self.status, '⚪')


def calculate_pivot_status(
    current_price: float,
    pivot_price: float,
    pivot_set_date: Optional[date] = None,
    buy_zone_max_pct: float = 5.0,
    fresh_max_days: int = 10,
    stale_min_days: int = 30,
    extended_threshold_pct: float = 15.0,
) -> PivotAnalysis:
    """
    Calculate pivot freshness status.
    
    Args:
        current_price: Current stock price
        pivot_price: Pivot/breakout price
        pivot_set_date: Date when pivot was set (None = unknown)
        buy_zone_max_pct: Maximum % above pivot for buy zone (default 5%)
        fresh_max_days: Days to be considered "fresh" (default 10)
        stale_min_days: Days to be considered "stale" (default 30)
        extended_threshold_pct: % above pivot to be "extended" (default 15%)
    
    Returns:
        PivotAnalysis with status, metrics, and message
    """
    if not pivot_price or pivot_price <= 0:
        return PivotAnalysis(
            status='UNKNOWN',
            distance_pct=0.0,
            days_since_set=0,
            message='No valid pivot price',
            is_actionable=False
        )
    
    # Calculate distance from pivot
    distance_pct = ((current_price - pivot_price) / pivot_price) * 100
    
    # Calculate days since pivot was set
    if pivot_set_date:
        days_since_set = (date.today() - pivot_set_date).days
    else:
        days_since_set = 999  # Unknown = assume very old
    
    # Determine status based on rules
    # Priority: EXTENDED > STALE > AGING > FRESH
    
    if distance_pct > extended_threshold_pct:
        # Extended beyond reasonable buy zone
        status = 'EXTENDED'
        is_actionable = False
        if days_since_set < 999:
            message = f"Extended +{distance_pct:.1f}% (set {days_since_set}d ago) - wait for pullback"
        else:
            message = f"Extended +{distance_pct:.1f}% - wait for pullback"
    
    elif days_since_set >= stale_min_days:
        # Old pivot regardless of distance
        status = 'STALE'
        is_actionable = distance_pct <= buy_zone_max_pct  # Still actionable if in buy zone
        message = f"Pivot set {days_since_set}d ago - consider updating or removing"
    
    elif distance_pct > buy_zone_max_pct or days_since_set > fresh_max_days:
        # Aging - somewhat extended or getting old
        status = 'AGING'
        is_actionable = distance_pct <= extended_threshold_pct
        if distance_pct > buy_zone_max_pct:
            message = f"Above buy zone (+{distance_pct:.1f}%) - monitor for re-entry"
        else:
            message = f"Pivot set {days_since_set}d ago - still valid"
    
    elif distance_pct < 0:
        # Below pivot - not broken out yet
        status = 'FRESH'
        is_actionable = True
        message = f"Below pivot ({distance_pct:.1f}%) - watching for breakout"
    
    else:
        # Fresh - in buy zone and recently set
        status = 'FRESH'
        is_actionable = True
        message = f"In buy zone (+{distance_pct:.1f}%) - actionable"
    
    return PivotAnalysis(
        status=status,
        distance_pct=distance_pct,
        days_since_set=days_since_set if days_since_set < 999 else -1,
        message=message,
        is_actionable=is_actionable
    )


def format_pivot_status_alert(analysis: PivotAnalysis, include_warning: bool = True) -> str:
    """
    Format pivot status for Discord alert.
    
    Args:
        analysis: PivotAnalysis result
        include_warning: Whether to include warning text for non-fresh pivots
    
    Returns:
        Formatted string for alert message
    """
    if analysis.status == 'FRESH':
        return ""  # No need to warn about fresh pivots
    
    if not include_warning:
        return f"{analysis.emoji} Pivot Status: {analysis.status}"
    
    lines = [f"{analysis.emoji} **PIVOT STATUS: {analysis.status}**"]
    
    if analysis.days_since_set > 0:
        lines.append(f"   Set {analysis.days_since_set} days ago")
    
    if analysis.status == 'EXTENDED':
        lines.append(f"   ⚠️ {analysis.message}")
    elif analysis.status == 'STALE':
        lines.append(f"   ⚠️ {analysis.message}")
    elif analysis.status == 'AGING':
        lines.append(f"   ℹ️ {analysis.message}")
    
    return '\n'.join(lines)


# Quick test
if __name__ == '__main__':
    print("Testing pivot status calculator...\n")
    
    test_cases = [
        # (current_price, pivot, pivot_date, description)
        (102.0, 100.0, date.today() - timedelta(days=5), "Fresh - in buy zone, recent"),
        (108.0, 100.0, date.today() - timedelta(days=5), "Aging - above buy zone"),
        (105.0, 100.0, date.today() - timedelta(days=25), "Aging - old but in zone"),
        (105.0, 100.0, date.today() - timedelta(days=45), "Stale - very old"),
        (125.0, 100.0, date.today() - timedelta(days=10), "Extended - way above"),
        (56.63, 7.29, date.today() - timedelta(days=60), "Extended + Stale (HUT example)"),
        (99.0, 100.0, date.today() - timedelta(days=3), "Fresh - below pivot"),
    ]
    
    for price, pivot, pivot_date, desc in test_cases:
        analysis = calculate_pivot_status(price, pivot, pivot_date)
        print(f"{desc}:")
        print(f"  Price: ${price:.2f}, Pivot: ${pivot:.2f}")
        print(f"  Status: {analysis.emoji} {analysis.status}")
        print(f"  Distance: {analysis.distance_pct:+.1f}%")
        print(f"  Days: {analysis.days_since_set}")
        print(f"  Actionable: {analysis.is_actionable}")
        print(f"  Message: {analysis.message}")
        print()
