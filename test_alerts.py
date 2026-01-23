"""
CANSLIM Alert System - Test Script
Generate sample alerts to test Discord notifications.

Usage:
    1. Set your Discord webhook URL below
    2. Run: python test_alerts.py
    
You'll see alerts appear in your Discord channel!
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time

# ============================================================================
# CONFIGURATION - Set your Discord webhook URL here!
# ============================================================================

DISCORD_WEBHOOK_URL = ""  # <-- PASTE YOUR WEBHOOK URL HERE

# ============================================================================


@dataclass
class MockPosition:
    """Mock position for testing."""
    id: int
    symbol: str
    state: float
    pivot: float
    entry_price: float
    stop_loss: float
    grade: str
    pattern: str
    stage: int
    depth: float
    target_shares: int
    current_shares: int
    position_pct: float
    avg_cost: float
    total_invested: float
    initial_shares: int
    pyramid1_shares: Optional[int] = None
    pyramid2_shares: Optional[int] = None
    eight_week_hold_active: bool = False
    eight_week_hold_end: Optional[datetime] = None
    power_move_pct: Optional[float] = None
    power_move_weeks: Optional[int] = None


# Sample positions for testing
SAMPLE_POSITIONS = {
    "NVDA": MockPosition(
        id=1,
        symbol="NVDA",
        state=0,
        pivot=145.50,
        entry_price=None,
        stop_loss=135.50,
        grade="A",
        pattern="Cup w/Handle",
        stage=1,
        depth=18.5,
        target_shares=100,
        current_shares=0,
        position_pct=0,
        avg_cost=0,
        total_invested=0,
        initial_shares=50,
    ),
    "AAPL": MockPosition(
        id=2,
        symbol="AAPL",
        state=1,
        pivot=185.00,
        entry_price=185.50,
        stop_loss=172.00,
        grade="B+",
        pattern="Flat Base",
        stage=2,
        depth=12.0,
        target_shares=80,
        current_shares=40,
        position_pct=50,
        avg_cost=185.50,
        total_invested=7420.00,
        initial_shares=40,
    ),
    "MSFT": MockPosition(
        id=3,
        symbol="MSFT",
        state=3,
        pivot=410.00,
        entry_price=412.00,
        stop_loss=383.00,
        grade="A-",
        pattern="Double Bottom",
        stage=1,
        depth=15.0,
        target_shares=60,
        current_shares=60,
        position_pct=100,
        avg_cost=415.25,
        total_invested=24915.00,
        initial_shares=30,
        pyramid1_shares=15,
        pyramid2_shares=15,
    ),
    "GOOGL": MockPosition(
        id=4,
        symbol="GOOGL",
        state=4,
        pivot=165.00,
        entry_price=167.50,
        stop_loss=155.00,
        grade="A",
        pattern="Cup w/Handle",
        stage=1,
        depth=22.0,
        target_shares=100,
        current_shares=100,
        position_pct=100,
        avg_cost=169.80,
        total_invested=16980.00,
        initial_shares=50,
        pyramid1_shares=25,
        pyramid2_shares=25,
        eight_week_hold_active=True,
        eight_week_hold_end=datetime.now() + timedelta(days=38),
        power_move_pct=21.5,
        power_move_weeks=2,
    ),
}


def test_discord_connection(webhook_url: str) -> bool:
    """Test if Discord webhook is working."""
    import requests
    
    test_embed = {
        "title": "🧪 CANSLIM Alert System Test",
        "description": "Connection successful! Your alerts will appear here.",
        "color": 0x2ECC71,
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }
    
    try:
        response = requests.post(
            webhook_url,
            json={"embeds": [test_embed]},
            timeout=10
        )
        return response.status_code == 204
    except Exception as e:
        print(f"Connection failed: {e}")
        return False


def send_sample_alert(webhook_url: str, embed: dict) -> bool:
    """Send an alert embed to Discord."""
    import requests
    
    try:
        response = requests.post(
            webhook_url,
            json={"embeds": [embed]},
            timeout=10
        )
        return response.status_code == 204
    except Exception as e:
        print(f"Send failed: {e}")
        return False


def generate_breakout_embed(position: MockPosition, price: float, volume_ratio: float) -> dict:
    """Generate a breakout alert embed."""
    
    if volume_ratio >= 1.4:
        title = f"🚀 {position.symbol} - BREAKOUT CONFIRMED"
        color = 0x2ECC71
        vol_note = f"with {volume_ratio:.1f}x average volume"
    else:
        title = f"⚠️ {position.symbol} - BREAKOUT SUPPRESSED"
        color = 0x90EE90
        vol_note = f"but volume is light ({volume_ratio:.1f}x)"
    
    shares = position.initial_shares
    cost = shares * price
    
    return {
        "title": title,
        "description": f"{position.symbol} broke out above ${position.pivot:.2f} pivot {vol_note}",
        "color": color,
        "fields": [
            {"name": "Price", "value": f"${price:.2f}", "inline": True},
            {"name": "Grade", "value": position.grade, "inline": True},
            {"name": "Volume", "value": f"{volume_ratio:.1f}x avg", "inline": True},
            {"name": "Pattern", "value": position.pattern, "inline": True},
            {"name": "Stage", "value": str(position.stage), "inline": True},
            {"name": "Depth", "value": f"{position.depth:.1f}%", "inline": True},
            {"name": "▶ Action", "value": f"Buy {shares} shares (50% initial)", "inline": False},
            {"name": "Est. Cost", "value": f"${cost:,.2f}", "inline": True},
            {"name": "Stop Loss", "value": f"${position.stop_loss:.2f}", "inline": True},
            {"name": "Market", "value": "CONFIRMED UPTREND", "inline": True},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def generate_pyramid_embed(position: MockPosition, price: float, level: int) -> dict:
    """Generate a pyramid alert embed."""
    
    gain_pct = (price - position.entry_price) / position.entry_price * 100
    
    if level == 1:
        shares = position.target_shares // 4
        new_pct = 75
    else:
        shares = position.target_shares - position.current_shares
        new_pct = 100
    
    # Calculate new avg cost
    current_cost = position.current_shares * position.avg_cost
    add_cost = shares * price
    new_shares = position.current_shares + shares
    new_avg = (current_cost + add_cost) / new_shares
    
    return {
        "title": f"📈 {position.symbol} - PYRAMID {level} READY",
        "description": f"{position.symbol} in Pyramid {level} zone ({gain_pct:.1f}% above entry)",
        "color": 0x3498DB,
        "fields": [
            {"name": "Price", "value": f"${price:.2f}", "inline": True},
            {"name": "Entry", "value": f"${position.entry_price:.2f}", "inline": True},
            {"name": "Gain", "value": f"+{gain_pct:.1f}%", "inline": True},
            {"name": "Current", "value": f"{position.current_shares} shares @ ${position.avg_cost:.2f}", "inline": False},
            {"name": "▶ Action", "value": f"Add {shares} shares (brings to {new_pct}%)", "inline": False},
            {"name": "Add Cost", "value": f"${add_cost:,.2f}", "inline": True},
            {"name": "New Avg Cost", "value": f"~${new_avg:.2f}", "inline": True},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def generate_tp1_embed(position: MockPosition, price: float) -> dict:
    """Generate TP1 alert embed."""
    
    gain_pct = (price - position.avg_cost) / position.avg_cost * 100
    
    if position.eight_week_hold_active:
        return {
            "title": f"⏳ {position.symbol} - TP1 SUPPRESSED (8-WEEK HOLD)",
            "description": f"{position.symbol} hit 20% but 8-week hold rule is ACTIVE",
            "color": 0xF39C12,
            "fields": [
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "Avg Cost", "value": f"${position.avg_cost:.2f}", "inline": True},
                {"name": "Gain", "value": f"+{gain_pct:.1f}%", "inline": True},
                {"name": "Power Move", "value": f"+{position.power_move_pct:.1f}% in {position.power_move_weeks} weeks", "inline": False},
                {"name": "▶ Action", "value": "HOLD - Do not sell", "inline": False},
                {"name": "Hold Expires", "value": position.eight_week_hold_end.strftime("%b %d, %Y"), "inline": True},
                {"name": "Days Left", "value": str((position.eight_week_hold_end - datetime.now()).days), "inline": True},
                {"name": "⚠️ Note", "value": "Hard stop still active", "inline": False},
            ],
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "CANSLIM Monitor v2.0"},
        }
    else:
        shares = position.current_shares // 3
        remaining = position.current_shares - shares
        profit = shares * (price - position.avg_cost)
        
        return {
            "title": f"💰 {position.symbol} - TP1 TRIGGERED",
            "description": f"{position.symbol} hit 20% profit target",
            "color": 0x2ECC71,
            "fields": [
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "Avg Cost", "value": f"${position.avg_cost:.2f}", "inline": True},
                {"name": "Gain", "value": f"+{gain_pct:.1f}%", "inline": True},
                {"name": "▶ Action", "value": f"Sell {shares} shares (1/3 of position)", "inline": False},
                {"name": "Remaining", "value": f"{remaining} shares", "inline": True},
                {"name": "Locked Profit", "value": f"${profit:,.2f}", "inline": True},
                {"name": "Next Target", "value": f"TP2 @ ${position.avg_cost * 1.25:.2f} (+25%)", "inline": False},
            ],
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "CANSLIM Monitor v2.0"},
        }


def generate_stop_embed(position: MockPosition, price: float, is_warning: bool = False) -> dict:
    """Generate stop alert embed."""
    
    loss_pct = (price - position.avg_cost) / position.avg_cost * 100
    
    if is_warning:
        distance = (price - position.stop_loss) / position.stop_loss * 100
        return {
            "title": f"⚡ {position.symbol} - STOP WARNING",
            "description": f"⚠️ {position.symbol} approaching stop level!",
            "color": 0xE67E22,
            "fields": [
                {"name": "Current", "value": f"${price:.2f}", "inline": True},
                {"name": "Stop", "value": f"${position.stop_loss:.2f}", "inline": True},
                {"name": "Distance", "value": f"{distance:.1f}%", "inline": True},
                {"name": "▶ Action", "value": "REVIEW NOW", "inline": False},
            ],
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "CANSLIM Monitor v2.0"},
        }
    else:
        return {
            "title": f"🛑 {position.symbol} - HARD STOP HIT",
            "description": f"🛑 {position.symbol} STOP BREACHED at ${price:.2f}",
            "color": 0xE74C3C,
            "fields": [
                {"name": "Stop Level", "value": f"${position.stop_loss:.2f}", "inline": True},
                {"name": "Current", "value": f"${price:.2f}", "inline": True},
                {"name": "Loss", "value": f"{loss_pct:.1f}%", "inline": True},
                {"name": "▶ Action", "value": "EXIT NOW - Sell all shares", "inline": False},
                {"name": "Shares to Sell", "value": str(position.current_shares), "inline": True},
            ],
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "CANSLIM Monitor v2.0"},
        }


def generate_ma_sell_embed(position: MockPosition, price: float, ma_value: float, ma_type: str) -> dict:
    """Generate MA sell alert embed."""
    
    return {
        "title": f"🔻 {position.symbol} - {ma_type} SELL",
        "description": f"{position.symbol} CLOSED BELOW {ma_type.replace('_', ' ')} on volume",
        "color": 0xE74C3C if "SELL" in ma_type else 0xE67E22,
        "fields": [
            {"name": "Close", "value": f"${price:.2f}", "inline": True},
            {"name": ma_type.replace("_", " "), "value": f"${ma_value:.2f}", "inline": True},
            {"name": "Volume", "value": "1.5x avg", "inline": True},
            {"name": "▶ Action", "value": "SELL - Confirmed break", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def generate_breakout_card_embed(
    symbol: str = "STX",
    subtype: str = "EXTENDED",
    grade: str = "B+",
    score: int = 12,
    rs_rating: int = 98,
    pattern: str = "Ascending Base",
    stage: str = "2(2)",
    price: float = 327.89,
    pivot: float = 308.93,
    buy_zone_pct: float = 5.0,
    volume_ratio: float = 1.4,
    market_regime: str = "BEARISH",
    is_stale: bool = True,
    stale_days: int = 999
) -> dict:
    """
    Generate breakout alert as Discord embed with compact description.
    
    Format:
    - Title: Emoji + Alert Type + Symbol
    - Description: 3 compact pipe-separated lines
    - Footer: Market regime + warnings
    - Color: Based on subtype
    """
    buy_zone_top = pivot * (1 + buy_zone_pct / 100)
    distance_pct = ((price - pivot) / pivot) * 100
    
    # Volume display
    vol_str = f"{volume_ratio:.1f}x" if volume_ratio > 0.01 else "--"
    
    # Determine color and title based on subtype
    subtype_upper = subtype.upper().replace(" ", "_")
    if subtype_upper == "CONFIRMED":
        color = 0x00FF00  # Green
        title = f"🚀 BREAKOUT: {symbol}"
    elif subtype_upper == "EXTENDED":
        color = 0xFF0000  # Red
        title = f"⚠️ EXTENDED: {symbol}"
    elif subtype_upper == "SUPPRESSED":
        color = 0xFF0000  # Red
        title = f"⛔ SUPPRESSED: {symbol}"
    elif subtype_upper == "IN_BUY_ZONE":
        color = 0xFFFF00  # Yellow
        title = f"✅ BUY ZONE: {symbol}"
    elif subtype_upper == "APPROACHING":
        color = 0x0099FF  # Blue
        title = f"👀 APPROACHING: {symbol}"
    else:
        color = 0x808080  # Gray
        title = f"📢 ALERT: {symbol}"
    
    # Build compact 3-line description
    line1 = f"{grade} ({score}) | RS {rs_rating} | {pattern} {stage}"
    line2 = f"${price:.2f} ({distance_pct:+.1f}%) | Pivot ${pivot:.2f}"
    line3 = f"Zone: ${pivot:.2f} - ${buy_zone_top:.2f} | Vol {vol_str}"
    
    description = f"{line1}\n{line2}\n{line3}"
    
    # Build footer with market regime and warnings
    footer_parts = []
    
    regime_upper = market_regime.upper()
    if regime_upper in ("BEARISH", "CORRECTION", "DOWNTREND"):
        footer_parts.append("🐻 Bearish")
    elif regime_upper in ("BULLISH", "CONFIRMED_UPTREND"):
        footer_parts.append("🐂 Bullish")
    else:
        footer_parts.append(f"➖ {regime_upper.title()}")
    
    if is_stale:
        footer_parts.append(f"⚠️ Stale ({stale_days}d)")
    
    footer_text = " • ".join(footer_parts)
    
    # Build embed
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": footer_text},
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    return embed


def generate_card_message(
    symbol: str = "STX",
    subtype: str = "EXTENDED",
    grade: str = "B+",
    score: int = 12,
    rs_rating: int = 98,
    pattern: str = "Ascending Base",
    stage: str = "2(2)",
    price: float = 327.89,
    pivot: float = 308.93,
    buy_zone_pct: float = 5.0,
    volume_ratio: float = 1.4,
    market_regime: str = "BEARISH",
    is_stale: bool = True,
    stale_days: int = 999
) -> str:
    """
    DEPRECATED - Use generate_breakout_embed() instead.
    Kept for backward compatibility.
    """
    buy_zone_top = pivot * (1 + buy_zone_pct / 100)
    distance_pct = ((price - pivot) / pivot) * 100
    
    # Determine color bar and emoji based on subtype
    subtype_upper = subtype.upper().replace(" ", "_")
    if subtype_upper == "CONFIRMED":
        color_bar = "🟢"
        header_emoji = "🚀"
    elif subtype_upper in ("EXTENDED", "SUPPRESSED"):
        color_bar = "🔴"
        header_emoji = "⛔" if subtype_upper == "SUPPRESSED" else "⚠️"
    elif subtype_upper == "IN_BUY_ZONE":
        color_bar = "🟡"
        header_emoji = "✅"
    elif subtype_upper == "APPROACHING":
        color_bar = "🔵"
        header_emoji = "👀"
    else:
        color_bar = "⚪"
        header_emoji = "📢"
    
    # Volume display - hide if data issue
    vol_str = f"{volume_ratio:.1f}x" if volume_ratio > 0.01 else "--"
    
    # Build warning flags
    warnings = []
    
    if subtype_upper == "EXTENDED":
        warnings.append("Do not chase")
    elif subtype_upper == "SUPPRESSED":
        warnings.append("Mkt correction")
    
    regime_upper = market_regime.upper()
    if regime_upper in ("BEARISH", "CORRECTION", "DOWNTREND"):
        warnings.append("Bearish")
    elif regime_upper in ("BULLISH", "CONFIRMED_UPTREND"):
        warnings.append("Bullish")
    else:
        warnings.append(regime_upper.title())
    
    if is_stale:
        warnings.append(f"Stale {stale_days}d")
    
    # Build card with colored bar prefix on each line
    line1 = f"{symbol} {subtype}"
    line2 = f"{grade} ({score}) | RS {rs_rating} | {pattern} {stage}"
    line3 = f"${price:.2f} ({distance_pct:+.1f}%) | Pivot ${pivot:.2f}"
    line4 = f"Zone: ${pivot:.2f} - ${buy_zone_top:.2f} | Vol {vol_str}"
    line5 = " | ".join(warnings) if warnings else ""
    
    card = f"""{header_emoji} **{symbol} - {subtype}**
{color_bar} `{line1}`
{color_bar} `{line2}`
{color_bar} `{line3}`
{color_bar} `{line4}`
{color_bar} `{line5}`
Time: {datetime.now().strftime('%H:%M:%S ET')}"""
    
    return card
    
    card = f"""{header_emoji} **{symbol} - {subtype}**
{color_bar} `{line1}`
{color_bar} `{line2}`
{color_bar} `{line3}`
{color_bar} `{line4}`
{color_bar} `{line5}`
Time: {datetime.now().strftime('%H:%M:%S ET')}"""
    
    return card


def generate_card_message_simple(
    symbol: str = "STX",
    subtype: str = "EXTENDED",
    grade: str = "B+",
    score: int = 12,
    rs_rating: int = 98,
    pattern: str = "Ascending Base",
    stage: str = "2(2)",
    price: float = 327.89,
    pivot: float = 308.93,
    buy_zone_pct: float = 5.0,
    volume_ratio: float = 1.4,
    market_regime: str = "BEARISH",
    is_stale: bool = True,
    stale_days: int = 999
) -> str:
    """
    Simple card format without ANSI (fallback if ANSI doesn't render).
    Uses emoji prefix for color indication.
    """
    buy_zone_top = pivot * (1 + buy_zone_pct / 100)
    distance_pct = ((price - pivot) / pivot) * 100
    
    # Determine status emoji based on subtype
    subtype_upper = subtype.upper().replace(" ", "_")
    if subtype_upper == "CONFIRMED":
        status_emoji = "🟢"  # Go
    elif subtype_upper in ("EXTENDED", "SUPPRESSED"):
        status_emoji = "🔴"  # No go
    elif subtype_upper == "IN_BUY_ZONE":
        status_emoji = "🟡"  # Maybe
    elif subtype_upper == "APPROACHING":
        status_emoji = "🔵"  # Watch
    else:
        status_emoji = "⚪"
    
    # Volume display
    vol_str = f"{volume_ratio:.1f}x" if volume_ratio > 0.01 else "--"
    
    # Warnings
    warnings = []
    regime_upper = market_regime.upper()
    if regime_upper in ("BEARISH", "CORRECTION", "DOWNTREND"):
        warnings.append("🐻 Bearish")
    elif regime_upper in ("BULLISH", "CONFIRMED_UPTREND"):
        warnings.append("🐂 Bullish")
    
    if is_stale:
        warnings.append(f"⚠️ Stale {stale_days}d")
    
    warning_line = " • ".join(warnings) if warnings else ""
    
    card = f"""{status_emoji} **{symbol} - {subtype}**
```
{grade} ({score}) | RS {rs_rating} | {pattern} {stage}
${price:.2f} ({distance_pct:+.1f}%) | Pivot ${pivot:.2f}
Zone: ${pivot:.2f} - ${buy_zone_top:.2f} | Vol {vol_str}
```
{warning_line}
Time: {datetime.now().strftime('%H:%M:%S ET')}"""
    
    return card


def send_card_message(webhook_url: str, message: str) -> bool:
    """Send a plain text card message to Discord."""
    import requests
    
    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=10
        )
        return response.status_code == 204
    except Exception as e:
        print(f"Send failed: {e}")
        return False


def generate_market_embed(status: str, spy_price: float, d_days: int, subtype: str) -> dict:
    """Generate market alert embed."""
    
    if subtype == "CORRECTION":
        title = "🛑 SPY - MARKET CORRECTION STARTED"
        description = "Distribution day cluster detected. Market now in CORRECTION.\nNEW BREAKOUT ALERTS BLOCKED until Follow-Through Day."
        color = 0xE74C3C
        action = "Reduce exposure, no new entries"
    elif subtype == "FTD":
        title = "🎯 SPY - FOLLOW-THROUGH DAY"
        description = "Follow-Through Day CONFIRMED. New uptrend beginning."
        color = 0x2ECC71
        action = "Resume taking new entries"
    else:
        title = "📉 SPY - MARKET WEAK"
        description = f"Distribution day cluster detected. {d_days} D-days in recent sessions."
        color = 0x3498DB
        action = "Review positions, tighten stops"
    
    return {
        "title": title,
        "description": description,
        "color": color,
        "fields": [
            {"name": "SPY", "value": f"${spy_price:.2f}", "inline": True},
            {"name": "Status", "value": status, "inline": True},
            {"name": "D-Days", "value": f"{d_days}/5", "inline": True},
            {"name": "▶ Action", "value": action, "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def run_demo(webhook_url: str):
    """Run a demo of all alert types."""
    
    print("\n" + "="*60)
    print("CANSLIM Alert System - Demo Mode")
    print("="*60)
    
    alerts_to_send = [
        ("Breakout Confirmed", generate_breakout_embed(SAMPLE_POSITIONS["NVDA"], 147.25, 2.3)),
        ("Breakout Suppressed", generate_breakout_embed(SAMPLE_POSITIONS["NVDA"], 146.00, 0.8)),
        ("Pyramid 1 Ready", generate_pyramid_embed(SAMPLE_POSITIONS["AAPL"], 190.12, 1)),
        ("Pyramid 2 Ready", generate_pyramid_embed(SAMPLE_POSITIONS["AAPL"], 194.78, 2)),
        ("TP1 Triggered", generate_tp1_embed(SAMPLE_POSITIONS["MSFT"], 498.30)),
        ("TP1 Suppressed (8WK)", generate_tp1_embed(SAMPLE_POSITIONS["GOOGL"], 205.00)),
        ("Stop Warning", generate_stop_embed(SAMPLE_POSITIONS["AAPL"], 174.50, is_warning=True)),
        ("Hard Stop Hit", generate_stop_embed(SAMPLE_POSITIONS["AAPL"], 171.00, is_warning=False)),
        ("50 MA Sell", generate_ma_sell_embed(SAMPLE_POSITIONS["MSFT"], 398.00, 405.50, "50_MA")),
        ("Market Correction", generate_market_embed("CORRECTION", 485.20, 5, "CORRECTION")),
        ("Follow-Through Day", generate_market_embed("CONFIRMED_UPTREND", 495.80, 0, "FTD")),
    ]
    
    print(f"\nSending {len(alerts_to_send)} sample alerts...\n")
    
    for i, (name, embed) in enumerate(alerts_to_send, 1):
        print(f"[{i}/{len(alerts_to_send)}] Sending: {name}...", end=" ")
        
        if send_sample_alert(webhook_url, embed):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        
        # Rate limit - wait between messages
        if i < len(alerts_to_send):
            time.sleep(1.5)
    
    print("\n" + "="*60)
    print("Demo complete! Check your Discord channel.")
    print("="*60 + "\n")


def run_single_alert(webhook_url: str, alert_type: str):
    """Send a single alert for testing."""
    
    # Embed-based breakout cards (matches position card style)
    if alert_type == "card":
        print("Sending breakout embed (EXTENDED - red bar)...")
        embed = generate_breakout_card_embed()
        if send_sample_alert(webhook_url, embed):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        return
    
    if alert_type == "card_confirmed":
        print("Sending breakout embed (CONFIRMED - green bar)...")
        embed = generate_breakout_card_embed(
            symbol="CRWD", subtype="CONFIRMED", grade="A", score=18,
            rs_rating=95, pattern="Cup w/Handle", stage="1(1)",
            price=425.80, pivot=416.25, volume_ratio=1.65,
            market_regime="BULLISH", is_stale=False
        )
        if send_sample_alert(webhook_url, embed):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        return
    
    if alert_type == "card_buyzone":
        print("Sending breakout embed (IN_BUY_ZONE - yellow bar)...")
        embed = generate_breakout_card_embed(
            symbol="NOW", subtype="IN BUY ZONE", grade="A-", score=17,
            rs_rating=92, pattern="Flat Base", stage="2(1)",
            price=1125.50, pivot=1105.00, volume_ratio=1.15,
            market_regime="NEUTRAL", is_stale=False
        )
        if send_sample_alert(webhook_url, embed):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        return
    
    if alert_type == "card_approaching":
        print("Sending breakout embed (APPROACHING - blue bar)...")
        embed = generate_breakout_card_embed(
            symbol="AAPL", subtype="APPROACHING", grade="B+", score=15,
            rs_rating=88, pattern="Double Bottom", stage="1(2)",
            price=184.50, pivot=185.00, volume_ratio=1.2,
            market_regime="BULLISH", is_stale=False
        )
        if send_sample_alert(webhook_url, embed):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        return
    
    if alert_type == "card_bad_vol":
        print("Sending breakout embed with bad volume data...")
        embed = generate_breakout_card_embed(
            symbol="TEST", subtype="EXTENDED", grade="B", score=14,
            rs_rating=88, pattern="Double Bottom", stage="1(2)",
            price=55.20, pivot=52.00, volume_ratio=0.0,  # Bad volume!
            market_regime="BEARISH", is_stale=True, stale_days=45
        )
        if send_sample_alert(webhook_url, embed):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        return
    
    if alert_type == "card_all":
        print("Sending all 4 breakout embed types for comparison...")
        embeds = [
            ("CONFIRMED (green bar)", generate_breakout_card_embed(
                symbol="CRWD", subtype="CONFIRMED", grade="A", score=18,
                rs_rating=95, pattern="Cup w/Handle", stage="1(1)",
                price=425.80, pivot=416.25, volume_ratio=1.65,
                market_regime="BULLISH", is_stale=False
            )),
            ("IN_BUY_ZONE (yellow bar)", generate_breakout_card_embed(
                symbol="NOW", subtype="IN BUY ZONE", grade="A-", score=17,
                rs_rating=92, pattern="Flat Base", stage="2(1)",
                price=1125.50, pivot=1105.00, volume_ratio=1.15,
                market_regime="NEUTRAL", is_stale=False
            )),
            ("APPROACHING (blue bar)", generate_breakout_card_embed(
                symbol="AAPL", subtype="APPROACHING", grade="B+", score=15,
                rs_rating=88, pattern="Double Bottom", stage="1(2)",
                price=184.50, pivot=185.00, volume_ratio=1.2,
                market_regime="BULLISH", is_stale=False
            )),
            ("EXTENDED (red bar)", generate_breakout_card_embed(
                symbol="STX", subtype="EXTENDED", grade="B+", score=12,
                rs_rating=98, pattern="Ascending Base", stage="2(2)",
                price=327.89, pivot=308.93, volume_ratio=1.4,
                market_regime="BEARISH", is_stale=True, stale_days=999
            )),
        ]
        for name, embed in embeds:
            print(f"  Sending {name}...", end=" ")
            if send_sample_alert(webhook_url, embed):
                print("✅")
            else:
                print("❌")
            time.sleep(1.5)
        return
    
    # Legacy text card formats (deprecated)
    if alert_type == "card_text":
        print("Sending legacy text card format...")
        message = generate_card_message()
        if send_card_message(webhook_url, message):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        return
    
    if alert_type == "card_simple":
        print("Sending Card A simple format (emoji prefix)...")
        message = generate_card_message_simple()
        if send_card_message(webhook_url, message):
            print("✅ Sent!")
        else:
            print("❌ Failed!")
        return
    
    embeds = {
        "breakout": generate_breakout_embed(SAMPLE_POSITIONS["NVDA"], 147.25, 2.3),
        "pyramid": generate_pyramid_embed(SAMPLE_POSITIONS["AAPL"], 190.12, 1),
        "tp1": generate_tp1_embed(SAMPLE_POSITIONS["MSFT"], 498.30),
        "8week": generate_tp1_embed(SAMPLE_POSITIONS["GOOGL"], 205.00),
        "stop": generate_stop_embed(SAMPLE_POSITIONS["AAPL"], 171.00),
        "warning": generate_stop_embed(SAMPLE_POSITIONS["AAPL"], 174.50, is_warning=True),
        "ma_sell": generate_ma_sell_embed(SAMPLE_POSITIONS["MSFT"], 398.00, 405.50, "50_MA"),
        "market": generate_market_embed("CORRECTION", 485.20, 5, "CORRECTION"),
        "ftd": generate_market_embed("CONFIRMED_UPTREND", 495.80, 0, "FTD"),
    }
    
    if alert_type not in embeds:
        print(f"Unknown alert type: {alert_type}")
        print(f"\nLegacy embed formats: {', '.join(embeds.keys())}")
        print(f"\nBreakout card embeds (with colored sidebar):")
        print(f"  card           - EXTENDED example (red bar)")
        print(f"  card_confirmed - CONFIRMED breakout (green bar)")
        print(f"  card_buyzone   - IN BUY ZONE (yellow bar)")  
        print(f"  card_approaching - APPROACHING pivot (blue bar)")
        print(f"  card_bad_vol   - Bad volume shows '--'")
        print(f"  card_all       - Send all 4 types for comparison")
        return
    
    print(f"Sending {alert_type} alert...")
    if send_sample_alert(webhook_url, embeds[alert_type]):
        print("✅ Sent!")
    else:
        print("❌ Failed!")


def main():
    """Main entry point."""
    
    # Check for webhook URL
    webhook_url = DISCORD_WEBHOOK_URL
    
    if not webhook_url:
        print("\n" + "="*60)
        print("ERROR: No Discord webhook URL configured!")
        print("="*60)
        print("\nTo use this test script:")
        print("1. Create a Discord webhook in your server")
        print("   (Server Settings → Integrations → Webhooks → New Webhook)")
        print("2. Copy the webhook URL")
        print("3. Paste it in the DISCORD_WEBHOOK_URL variable at the top of this file")
        print("\nAlternatively, run with: python test_alerts.py YOUR_WEBHOOK_URL")
        print("="*60 + "\n")
        
        if len(sys.argv) > 1:
            webhook_url = sys.argv[1]
        else:
            return
    
    # Override from command line if provided
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        webhook_url = sys.argv[1]
    
    print("\n" + "="*60)
    print("CANSLIM Alert System - Test Mode")
    print("="*60)
    
    # Test connection
    print("\nTesting Discord connection...", end=" ")
    if not test_discord_connection(webhook_url):
        print("❌ Failed!")
        print("Check your webhook URL and try again.")
        return
    print("✅ Connected!")
    
    # Check for specific alert type argument
    if len(sys.argv) > 2:
        alert_type = sys.argv[2].lower()
        run_single_alert(webhook_url, alert_type)
    else:
        # Run full demo
        print("\nRunning full demo in 3 seconds...")
        print("(Press Ctrl+C to cancel)")
        time.sleep(3)
        run_demo(webhook_url)


if __name__ == "__main__":
    main()
