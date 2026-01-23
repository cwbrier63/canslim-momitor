#!/usr/bin/env python3
"""
CANSLIM Alert Demo - Standalone Test Script
============================================

This script sends sample alerts to Discord WITHOUT any database or complex setup.
Just add your webhook URL and run!

Usage:
    python alert_demo.py YOUR_WEBHOOK_URL
    
Or edit the WEBHOOK_URL variable below and run:
    python alert_demo.py
"""

import requests
from datetime import datetime, timedelta
import time
import sys

# ============================================================================
# CONFIGURATION - Set your Discord webhook URL here (or pass as argument)
# ============================================================================
WEBHOOK_URL = ""  # Paste your webhook URL here
# ============================================================================


def send_embed(webhook_url: str, embed: dict) -> bool:
    """Send an embed to Discord."""
    try:
        r = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        return r.status_code == 204
    except Exception as e:
        print(f"Error: {e}")
        return False


def breakout_confirmed():
    """NVDA Breakout Confirmed alert."""
    return {
        "title": "🚀 NVDA - BREAKOUT CONFIRMED",
        "description": "NVDA broke out above $145.50 pivot with 2.3x average volume",
        "color": 0x2ECC71,  # Green
        "fields": [
            {"name": "Price", "value": "$147.25", "inline": True},
            {"name": "Grade", "value": "A", "inline": True},
            {"name": "Volume", "value": "2.3x avg", "inline": True},
            {"name": "Pattern", "value": "Cup w/Handle", "inline": True},
            {"name": "Stage", "value": "1", "inline": True},
            {"name": "Depth", "value": "18.5%", "inline": True},
            {"name": "▶ Action", "value": "Buy 50 shares (50% initial)", "inline": False},
            {"name": "Est. Cost", "value": "$7,362", "inline": True},
            {"name": "Stop Loss", "value": "$135.50 (7.2%)", "inline": True},
            {"name": "Market", "value": "CONFIRMED UPTREND", "inline": True},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def breakout_suppressed():
    """TSLA Breakout Suppressed alert."""
    return {
        "title": "⚠️ TSLA - BREAKOUT SUPPRESSED",
        "description": "TSLA broke out above $275.00 pivot but volume is light (0.8x)",
        "color": 0x90EE90,  # Light green
        "fields": [
            {"name": "Price", "value": "$277.50", "inline": True},
            {"name": "Grade", "value": "B", "inline": True},
            {"name": "Volume", "value": "0.8x avg ⚠️", "inline": True},
            {"name": "Pattern", "value": "Double Bottom", "inline": True},
            {"name": "Stage", "value": "2", "inline": True},
            {"name": "Depth", "value": "22%", "inline": True},
            {"name": "▶ Action", "value": "WAIT for volume confirmation", "inline": False},
            {"name": "Note", "value": "Low volume breakouts have higher failure rate", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def pyramid_1_ready():
    """AAPL Pyramid 1 alert."""
    return {
        "title": "📈 AAPL - PYRAMID 1 READY",
        "description": "AAPL in Pyramid 1 zone (2.5% above entry)",
        "color": 0x3498DB,  # Blue
        "fields": [
            {"name": "Price", "value": "$190.12", "inline": True},
            {"name": "Entry", "value": "$185.50", "inline": True},
            {"name": "Gain", "value": "+2.5%", "inline": True},
            {"name": "Current Holdings", "value": "40 shares @ $185.50", "inline": False},
            {"name": "▶ Action", "value": "Add 20 shares (brings to 75%)", "inline": False},
            {"name": "Add Cost", "value": "$3,802", "inline": True},
            {"name": "New Avg Cost", "value": "~$187.04", "inline": True},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def pyramid_2_ready():
    """AAPL Pyramid 2 alert."""
    return {
        "title": "📈 AAPL - PYRAMID 2 READY",
        "description": "AAPL in Pyramid 2 zone (5.0% above entry)",
        "color": 0x3498DB,  # Blue
        "fields": [
            {"name": "Price", "value": "$194.78", "inline": True},
            {"name": "Entry", "value": "$185.50", "inline": True},
            {"name": "Gain", "value": "+5.0%", "inline": True},
            {"name": "Current Holdings", "value": "60 shares @ $187.04", "inline": False},
            {"name": "▶ Action", "value": "Add 20 shares (FULL position)", "inline": False},
            {"name": "Add Cost", "value": "$3,896", "inline": True},
            {"name": "New Avg Cost", "value": "~$188.96", "inline": True},
            {"name": "🎯 FULL POSITION", "value": "80 shares achieved!", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def tp1_triggered():
    """MSFT TP1 alert."""
    return {
        "title": "💰 MSFT - TP1 TRIGGERED",
        "description": "MSFT hit 20% profit target",
        "color": 0x2ECC71,  # Green
        "fields": [
            {"name": "Price", "value": "$498.30", "inline": True},
            {"name": "Avg Cost", "value": "$415.25", "inline": True},
            {"name": "Gain", "value": "+20.0%", "inline": True},
            {"name": "▶ Action", "value": "Sell 20 shares (1/3 of position)", "inline": False},
            {"name": "Remaining", "value": "40 shares", "inline": True},
            {"name": "Locked Profit", "value": "$1,661", "inline": True},
            {"name": "Next Target", "value": "TP2 @ $519.06 (+25%)", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def eight_week_hold():
    """GOOGL 8-Week Hold alert."""
    hold_end = datetime.now() + timedelta(days=38)
    return {
        "title": "⏳ GOOGL - 8-WEEK HOLD TRIGGERED",
        "description": "GOOGL gained 21.5% in 2 weeks. 8-week hold rule activated.",
        "color": 0xF39C12,  # Orange
        "fields": [
            {"name": "Price", "value": "$205.00", "inline": True},
            {"name": "Entry", "value": "$167.50", "inline": True},
            {"name": "Gain", "value": "+22.4%", "inline": True},
            {"name": "Power Move", "value": "+21.5% in 2 weeks", "inline": False},
            {"name": "▶ Action", "value": "HOLD - Do not sell TP1", "inline": False},
            {"name": "Hold Until", "value": hold_end.strftime("%b %d, %Y"), "inline": True},
            {"name": "Days Left", "value": "38", "inline": True},
            {"name": "⚠️ Note", "value": "Hard stop at $155.00 still ACTIVE", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def stop_warning():
    """AMZN Stop Warning alert."""
    return {
        "title": "⚡ AMZN - STOP WARNING",
        "description": "⚠️ AMZN approaching stop level!",
        "color": 0xE67E22,  # Orange
        "fields": [
            {"name": "Current", "value": "$186.50", "inline": True},
            {"name": "Stop", "value": "$183.00", "inline": True},
            {"name": "Distance", "value": "1.9%", "inline": True},
            {"name": "▶ Action", "value": "REVIEW NOW - Prepare to exit if breached", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def hard_stop():
    """META Hard Stop alert."""
    return {
        "title": "🛑 META - HARD STOP HIT",
        "description": "🛑 META STOP BREACHED at $485.00",
        "color": 0xE74C3C,  # Red
        "fields": [
            {"name": "Stop Level", "value": "$488.00", "inline": True},
            {"name": "Current", "value": "$485.00", "inline": True},
            {"name": "Loss", "value": "-7.2%", "inline": True},
            {"name": "▶ Action", "value": "EXIT NOW - Sell all shares", "inline": False},
            {"name": "Shares to Sell", "value": "45", "inline": True},
            {"name": "Est. Loss", "value": "$1,575", "inline": True},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def ma_50_sell():
    """CRM 50 MA Sell alert."""
    return {
        "title": "🔻 CRM - 50 MA SELL",
        "description": "CRM CLOSED BELOW 50-DAY MA on 1.5x volume",
        "color": 0xE74C3C,  # Red
        "fields": [
            {"name": "Close", "value": "$298.00", "inline": True},
            {"name": "50-Day MA", "value": "$305.50", "inline": True},
            {"name": "Volume", "value": "1.5x avg", "inline": True},
            {"name": "▶ Action", "value": "SELL - Confirmed break with volume", "inline": False},
            {"name": "Shares to Sell", "value": "35", "inline": True},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def market_correction():
    """Market Correction alert."""
    return {
        "title": "🛑 SPY - MARKET CORRECTION STARTED",
        "description": "Distribution day cluster detected. Market now in CORRECTION.\nNEW BREAKOUT ALERTS BLOCKED until Follow-Through Day.",
        "color": 0xE74C3C,  # Red
        "fields": [
            {"name": "SPY", "value": "$485.20", "inline": True},
            {"name": "Status", "value": "CORRECTION", "inline": True},
            {"name": "D-Days", "value": "5/5 ⚠️", "inline": True},
            {"name": "▶ Action", "value": "Reduce exposure, no new entries", "inline": False},
            {"name": "Suggestion", "value": "Raise cash, tighten all stops", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def follow_through_day():
    """Follow-Through Day alert."""
    return {
        "title": "🎯 SPY - FOLLOW-THROUGH DAY",
        "description": "Follow-Through Day CONFIRMED! New uptrend beginning.",
        "color": 0x2ECC71,  # Green
        "fields": [
            {"name": "SPY", "value": "$495.80", "inline": True},
            {"name": "Status", "value": "CONFIRMED UPTREND", "inline": True},
            {"name": "Gain", "value": "+1.8%", "inline": True},
            {"name": "Volume", "value": "Above average ✓", "inline": True},
            {"name": "Rally Day", "value": "4", "inline": True},
            {"name": "▶ Action", "value": "Resume taking new entries!", "inline": False},
            {"name": "Focus", "value": "Look for A+ setups with proper bases", "inline": False},
        ],
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }


def run_demo(webhook_url: str):
    """Run full demo of all alert types."""
    
    alerts = [
        ("Breakout Confirmed (NVDA)", breakout_confirmed()),
        ("Breakout Suppressed (TSLA)", breakout_suppressed()),
        ("Pyramid 1 Ready (AAPL)", pyramid_1_ready()),
        ("Pyramid 2 Ready (AAPL)", pyramid_2_ready()),
        ("TP1 Triggered (MSFT)", tp1_triggered()),
        ("8-Week Hold (GOOGL)", eight_week_hold()),
        ("Stop Warning (AMZN)", stop_warning()),
        ("Hard Stop Hit (META)", hard_stop()),
        ("50 MA Sell (CRM)", ma_50_sell()),
        ("Market Correction", market_correction()),
        ("Follow-Through Day", follow_through_day()),
    ]
    
    print(f"\n{'='*60}")
    print("CANSLIM Alert System - Demo")
    print(f"{'='*60}")
    print(f"\nSending {len(alerts)} sample alerts to Discord...\n")
    
    success = 0
    for i, (name, embed) in enumerate(alerts, 1):
        print(f"[{i:2}/{len(alerts)}] {name}...", end=" ", flush=True)
        
        if send_embed(webhook_url, embed):
            print("✅")
            success += 1
        else:
            print("❌")
        
        # Rate limit
        if i < len(alerts):
            time.sleep(1.2)
    
    print(f"\n{'='*60}")
    print(f"Done! {success}/{len(alerts)} alerts sent successfully.")
    print(f"{'='*60}\n")


def main():
    # Get webhook URL
    url = WEBHOOK_URL
    
    if len(sys.argv) > 1:
        url = sys.argv[1]
    
    if not url or not url.startswith("http"):
        print("""
╔══════════════════════════════════════════════════════════════╗
║           CANSLIM Alert Demo - Setup Required                 ║
╠══════════════════════════════════════════════════════════════╣
║                                                               ║
║  To use this script, you need a Discord webhook URL.          ║
║                                                               ║
║  Option 1: Pass as argument                                   ║
║    python alert_demo.py https://discord.com/api/webhooks/...  ║
║                                                               ║
║  Option 2: Edit this file                                     ║
║    Set WEBHOOK_URL at the top of the file                     ║
║                                                               ║
║  How to create a webhook:                                     ║
║    1. Go to your Discord server                               ║
║    2. Server Settings → Integrations → Webhooks               ║
║    3. Click "New Webhook"                                     ║
║    4. Copy the webhook URL                                    ║
║                                                               ║
╚══════════════════════════════════════════════════════════════╝
""")
        return
    
    # Test connection first
    print("\nTesting Discord connection...", end=" ", flush=True)
    test_embed = {
        "title": "🧪 Connection Test",
        "description": "CANSLIM Alert System connected successfully!",
        "color": 0x2ECC71,
        "timestamp": datetime.now().isoformat(),
        "footer": {"text": "CANSLIM Monitor v2.0"},
    }
    
    if not send_embed(url, test_embed):
        print("❌ Failed!")
        print("Check your webhook URL and try again.")
        return
    
    print("✅ Connected!")
    
    # Run demo
    print("\nStarting demo in 3 seconds... (Ctrl+C to cancel)")
    time.sleep(3)
    run_demo(url)


if __name__ == "__main__":
    main()
