"""
Discord Formatters - Position Alert Embed Builder

Provides consistent 4-line compact format for all position alerts:
Line 1: Price & P&L
Line 2: Alert-specific data
Line 3: MA Distances (21 EMA, 50 MA)
Line 4: Trend direction and duration

Based on Discord_Position_Alert_Design_Spec_v2.md
"""

import json
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any


# Color scheme by alert category
EMBED_COLORS = {
    'STOP': 0xE74C3C,      # Red
    'PROFIT': 0xF1C40F,    # Gold
    'PYRAMID': 0x3498DB,   # Blue
    'ADD': 0x2ECC71,       # Green
    'TECHNICAL': 0xE67E22, # Orange
    'HEALTH': 0xE67E22,    # Orange
    'CRITICAL': 0xE74C3C,  # Red (special case for critical health)
}

# Emoji mapping for subtypes
POSITION_EMOJIS = {
    # Stop Alerts
    "HARD_STOP": "\U0001F6D1",      # 🛑
    "WARNING": "\u26A0\uFE0F",       # ⚠️
    "STOP_WARNING": "\u26A0\uFE0F",  # ⚠️
    "TRAILING_STOP": "\U0001F4C9",   # 📉

    # Profit Alerts
    "TP1": "\U0001F4B0",             # 💰
    "TP2": "\U0001F3C6",             # 🏆
    "EIGHT_WEEK_HOLD": "\u23F3",     # ⏳

    # Pyramid Alerts
    "PY1_READY": "\U0001F4C8",       # 📈
    "PY1_EXTENDED": "\u2757\uFE0F",  # ❗
    "PY2_READY": "\U0001F4C8",       # 📈
    "PY2_EXTENDED": "\u2757\uFE0F",  # ❗
    "PULLBACK": "\U0001F3AF",        # 🎯

    # Add Alerts
    "EMA_21_PULLBACK": "\U0001F3AF", # 🎯
    "MA_50_BOUNCE": "\U0001F3AF",    # 🎯

    # Technical Alerts
    "MA_50_WARNING": "\u26A1",       # ⚡
    "MA_50_SELL": "\U0001F4C9",      # 📉
    "EMA_21_SELL": "\U0001F4C9",     # 📉
    "TEN_WEEK_SELL": "\U0001F4C9",   # 📉
    "CLIMAX_TOP": "\U0001F6A8",      # 🚨

    # Health Alerts
    "CRITICAL": "\U0001F6A8",        # 🚨
    "EXTENDED": "\u2757\uFE0F",      # ❗
    "EARNINGS": "\U0001F4C5",        # 📅
    "LATE_STAGE": "\u26A0\uFE0F",    # ⚠️
    "HEALTH_WARNING": "\u26A0\uFE0F", # ⚠️
}

# Trend indicators
TREND_SYMBOLS = {
    'UPTREND': "\u2197",      # ↗
    'DOWNTREND': "\u2198",    # ↘
    'SIDEWAYS': "\u2194",     # ↔
    'PARABOLIC': "\u2B06",    # ⬆
    'STALLING': "\u23F8",     # ⏸
}

# Priority labels
PRIORITY_LABELS = {
    'P0': 'IMMEDIATE ACTION',
    'P1': 'ACTION NEEDED',
    'P2': 'MONITOR',
}


def calculate_ma_distance(price: float, ma_value: Optional[float]) -> Optional[float]:
    """Calculate percentage distance from a moving average."""
    if not ma_value or ma_value <= 0:
        return None
    return ((price - ma_value) / ma_value) * 100


def calculate_trend(
    current_price: float,
    ma_21: Optional[float],
    ma_50: Optional[float],
    days_in_position: int = 0,
    max_gain_pct: float = 0,
) -> Tuple[str, int]:
    """
    Calculate trend direction and estimate duration.

    Returns:
        Tuple of (trend_display, estimated_days)
        trend_display: e.g., "↗ Uptrend" or "↘ Downtrend"
    """
    if not ma_21 or not ma_50:
        return f"{TREND_SYMBOLS['SIDEWAYS']} Unknown", 0

    above_21 = current_price > ma_21
    above_50 = current_price > ma_50

    # Check for parabolic (>25% above 50 MA)
    if ma_50 > 0:
        extension_pct = ((current_price - ma_50) / ma_50) * 100
        if extension_pct > 25:
            return f"{TREND_SYMBOLS['PARABOLIC']} Parabolic", days_in_position

    if above_21 and above_50:
        return f"{TREND_SYMBOLS['UPTREND']} Uptrend", days_in_position
    elif not above_21 and not above_50:
        # Use days_in_position as a rough estimate
        return f"{TREND_SYMBOLS['DOWNTREND']} Downtrend", max(1, days_in_position // 3)
    else:
        return f"{TREND_SYMBOLS['SIDEWAYS']} Sideways", max(1, days_in_position // 2)


def format_ma_distance(dist: Optional[float]) -> str:
    """Format MA distance with +/- sign."""
    if dist is None:
        return "N/A"
    sign = "+" if dist >= 0 else ""
    return f"{sign}{dist:.1f}%"


def build_position_embed(
    alert_type: str,
    subtype: str,
    symbol: str,
    price: float,
    pnl_pct: float,
    entry_price: float,
    line2_data: str,
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    days_in_position: int = 0,
    max_gain_pct: float = 0,
    action: str = "",
    priority: str = "P1",
    market_regime: str = "UNKNOWN",
    custom_title: Optional[str] = None,
) -> str:
    """
    Build Discord embed for position alert with P&L, MAs, and trend.

    Args:
        alert_type: Category (STOP, PROFIT, PYRAMID, ADD, TECHNICAL, HEALTH)
        subtype: Specific alert type (HARD_STOP, TP1, etc.)
        symbol: Stock symbol
        price: Current price
        pnl_pct: Profit/loss percentage
        entry_price: Entry price
        line2_data: Alert-specific info for line 2
        ma_21: 21 EMA value
        ma_50: 50 MA value
        days_in_position: Days since entry
        max_gain_pct: Max gain achieved
        action: Action recommendation
        priority: P0/P1/P2
        market_regime: Current market regime
        custom_title: Override default title

    Returns:
        JSON string with "EMBED:" prefix for AlertService
    """
    # Determine color
    if subtype in ('CRITICAL', 'HARD_STOP'):
        color = EMBED_COLORS['CRITICAL']
    else:
        color = EMBED_COLORS.get(alert_type, 0x808080)

    # Get emoji
    emoji = POSITION_EMOJIS.get(subtype, "\U0001F4E2")  # 📢 default

    # Build title
    if custom_title:
        title = f"{emoji} {custom_title}"
    else:
        subtype_display = subtype.replace('_', ' ')
        title = f"{emoji} {subtype_display}: {symbol}"

    # Calculate MA distances
    ema_21_dist = calculate_ma_distance(price, ma_21)
    ma_50_dist = calculate_ma_distance(price, ma_50)

    # Calculate trend
    trend_str, trend_days = calculate_trend(
        price, ma_21, ma_50, days_in_position, max_gain_pct
    )

    # Build 4-line description
    pnl_sign = "+" if pnl_pct >= 0 else ""
    line1 = f"${price:.2f} ({pnl_sign}{pnl_pct:.1f}%) | Entry: ${entry_price:.2f}"
    line2 = line2_data
    line3 = f"21 EMA: {format_ma_distance(ema_21_dist)} | 50 MA: {format_ma_distance(ma_50_dist)}"
    line4 = f"Trend: {trend_str} ({trend_days} days)" if trend_days > 0 else f"Trend: {trend_str}"

    # Build description with action
    if action:
        description = f"{line1}\n{line2}\n{line3}\n{line4}\n\n\u25B6 **{action}**"
    else:
        description = f"{line1}\n{line2}\n{line3}\n{line4}"

    # Build footer
    priority_label = PRIORITY_LABELS.get(priority, priority)

    # Market regime display
    regime_upper = market_regime.upper() if market_regime else "UNKNOWN"
    if regime_upper in ("BEARISH", "CORRECTION", "DOWNTREND"):
        regime_display = "\U0001F43B Bearish"  # 🐻
    elif regime_upper in ("BULLISH", "CONFIRMED_UPTREND"):
        regime_display = "\U0001F402 Bullish"  # 🐂
    else:
        regime_display = f"\u2796 {regime_upper.title()}"  # ➖

    footer_text = f"{priority} \u2022 {priority_label} \u2022 {regime_display}"

    embed = {
        'title': title,
        'description': description,
        'color': color,
        'footer': {'text': footer_text},
        'timestamp': datetime.utcnow().isoformat(),
    }

    return "EMBED:" + json.dumps(embed)


# Convenience builders for common alert types

def build_stop_warning_embed(
    symbol: str,
    price: float,
    entry_price: float,
    stop_price: float,
    distance_pct: float,
    pnl_pct: float,
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    days_in_position: int = 0,
    market_regime: str = "",
) -> str:
    """Build embed for stop warning alert."""
    line2 = f"Stop: ${stop_price:.2f} | Distance: {distance_pct:.1f}%"
    return build_position_embed(
        alert_type='STOP',
        subtype='STOP_WARNING',
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_in_position,
        action="Consider tightening stop or preparing to exit",
        priority='P0',
        market_regime=market_regime,
    )


def build_hard_stop_embed(
    symbol: str,
    price: float,
    entry_price: float,
    stop_price: float,
    pnl_pct: float,
    loss_dollars: float,
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    days_in_position: int = 0,
    market_regime: str = "",
) -> str:
    """Build embed for hard stop hit alert."""
    line2 = f"Stop: ${stop_price:.2f} | Loss: ${abs(loss_dollars):,.0f}"
    return build_position_embed(
        alert_type='STOP',
        subtype='HARD_STOP',
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_in_position,
        action="EXIT POSITION",
        priority='P0',
        market_regime=market_regime,
    )


def build_profit_embed(
    symbol: str,
    price: float,
    entry_price: float,
    pnl_pct: float,
    target_name: str,  # "TP1" or "TP2"
    target_pct: float,  # 20 or 40
    days_held: int,
    action: str,
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    market_regime: str = "",
) -> str:
    """Build embed for profit target alert."""
    line2 = f"Target: +{target_pct:.0f}% | Held: {days_held} days"
    return build_position_embed(
        alert_type='PROFIT',
        subtype=target_name,
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_held,
        action=action,
        priority='P1',
        market_regime=market_regime,
        custom_title=f"{target_name} HIT (+{target_pct:.0f}%): {symbol}",
    )


def build_eight_week_hold_embed(
    symbol: str,
    price: float,
    entry_price: float,
    pnl_pct: float,
    days_held: int,
    rs_rating: Optional[int],
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    market_regime: str = "",
    hold_until=None,
) -> str:
    """Build embed for 8-week hold rule alert."""
    rs_str = str(rs_rating) if rs_rating else "N/A"
    hold_str = f" | Hold until: {hold_until.strftime('%m/%d/%Y')}" if hold_until else ""
    line2 = f"Days held: {days_held} | RS: {rs_str}{hold_str}"
    action = "Hold through 8 weeks unless sharp break"
    if hold_until:
        action = f"Hold until {hold_until.strftime('%m/%d')} unless sharp break below 10-wk MA"
    return build_position_embed(
        alert_type='PROFIT',
        subtype='EIGHT_WEEK_HOLD',
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_held,
        action=action,
        priority='P2',
        market_regime=market_regime,
        custom_title=f"8-WEEK HOLD RULE: {symbol}",
    )


def build_pyramid_embed(
    symbol: str,
    price: float,
    entry_price: float,
    pnl_pct: float,
    pyramid_level: str,  # "PY1" or "PY2"
    zone_low: float,
    zone_high: float,
    volume_ratio: float,
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    days_in_position: int = 0,
    market_regime: str = "",
) -> str:
    """Build embed for pyramid opportunity alert."""
    subtype = f"{pyramid_level}_READY"
    line2 = f"Add zone: ${zone_low:.2f}-${zone_high:.2f} | Vol: {volume_ratio:.1f}x"
    add_pct = "25%" if pyramid_level == "PY1" else "15%"
    return build_position_embed(
        alert_type='PYRAMID',
        subtype=subtype,
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_in_position,
        action=f"Add {add_pct} to position above ${zone_low:.2f}",
        priority='P1',
        market_regime=market_regime,
        custom_title=f"PYRAMID {pyramid_level[-1]} READY: {symbol}",
    )


def build_ma_warning_embed(
    symbol: str,
    price: float,
    entry_price: float,
    pnl_pct: float,
    ma_type: str,  # "50 MA" or "21 EMA"
    ma_value: float,
    distance_pct: float,
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    days_in_position: int = 0,
    market_regime: str = "",
) -> str:
    """Build embed for MA warning alert."""
    line2 = f"{ma_type}: ${ma_value:.2f} | Distance: {distance_pct:.1f}%"
    return build_position_embed(
        alert_type='TECHNICAL',
        subtype='MA_50_WARNING',
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_in_position,
        action=f"Watch for close below {ma_type}",
        priority='P1',
        market_regime=market_regime,
    )


def build_ma_sell_embed(
    symbol: str,
    price: float,
    entry_price: float,
    pnl_pct: float,
    ma_type: str,  # "50 MA" or "21 EMA" or "10 Week"
    ma_value: float,
    volume_ratio: float,
    subtype: str,  # MA_50_SELL, EMA_21_SELL, TEN_WEEK_SELL
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    days_in_position: int = 0,
    market_regime: str = "",
) -> str:
    """Build embed for MA sell signal alert."""
    vol_desc = "HEAVY" if volume_ratio > 1.5 else "Normal"
    line2 = f"{ma_type}: ${ma_value:.2f} | Vol: {volume_ratio:.1f}x ({vol_desc})"

    if subtype == 'EMA_21_SELL':
        action = "Sell portion - late stage position"
        priority = 'P1'
    else:
        action = "Sell 50% or entire position"
        priority = 'P0'

    return build_position_embed(
        alert_type='TECHNICAL',
        subtype=subtype,
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_in_position,
        action=action,
        priority=priority,
        market_regime=market_regime,
        custom_title=f"{ma_type.upper()} SELL: {symbol}",
    )


def build_health_embed(
    symbol: str,
    price: float,
    entry_price: float,
    pnl_pct: float,
    subtype: str,  # CRITICAL, EXTENDED, EARNINGS, LATE_STAGE
    line2_data: str,
    action: str,
    ma_21: Optional[float] = None,
    ma_50: Optional[float] = None,
    days_in_position: int = 0,
    market_regime: str = "",
    priority: str = 'P1',
) -> str:
    """Build embed for health-related alerts."""
    return build_position_embed(
        alert_type='HEALTH',
        subtype=subtype,
        symbol=symbol,
        price=price,
        pnl_pct=pnl_pct,
        entry_price=entry_price,
        line2_data=line2_data,
        ma_21=ma_21,
        ma_50=ma_50,
        days_in_position=days_in_position,
        action=action,
        priority=priority,
        market_regime=market_regime,
    )
