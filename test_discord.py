"""
Quick diagnostic script to test Discord webhook configuration.
Run from: C:\Trading\canslim_monitor

Usage:
    python test_discord.py
"""

import yaml
import requests
import json
import sys
import os

def test_discord():
    # Load config
    config_paths = [
        'user_config.yaml',
        'config/config.yaml',
    ]
    
    config = None
    for path in config_paths:
        if os.path.exists(path):
            print(f"Loading config from: {path}")
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
            break
    
    if not config:
        print("ERROR: No config file found!")
        return
    
    discord_config = config.get('discord', {})
    
    if not discord_config:
        print("ERROR: No 'discord' section in config!")
        return
    
    print("\n=== Discord Configuration ===")
    print(f"Keys found: {list(discord_config.keys())}")
    
    # Check for specific webhooks
    webhook_url = discord_config.get('webhook_url')
    breakout_webhook_url = discord_config.get('breakout_webhook_url')
    regime_webhook_url = discord_config.get('regime_webhook_url')
    market_webhook_url = discord_config.get('market_webhook_url')
    
    print(f"\nwebhook_url (default): {'CONFIGURED' if webhook_url else 'NOT CONFIGURED'}")
    print(f"breakout_webhook_url: {'CONFIGURED' if breakout_webhook_url else 'NOT CONFIGURED'}")
    print(f"regime_webhook_url: {'CONFIGURED' if regime_webhook_url else 'NOT CONFIGURED'}")
    print(f"market_webhook_url: {'CONFIGURED' if market_webhook_url else 'NOT CONFIGURED'}")
    
    # Determine which webhook to test
    test_webhook = breakout_webhook_url or webhook_url
    
    if not test_webhook:
        print("\nERROR: No webhook URL configured! Need either 'webhook_url' or 'breakout_webhook_url'")
        return
    
    # Show webhook preview (masked for security)
    preview = test_webhook[:50] + "..." if len(test_webhook) > 50 else test_webhook
    print(f"\nTesting webhook: {preview}")
    
    # Test with a simple message
    print("\n=== Testing Plain Text Message ===")
    test_message = {"content": "🧪 CANSLIM Monitor Discord Test - Plain text"}
    
    try:
        response = requests.post(test_webhook, json=test_message, timeout=10)
        print(f"Status: {response.status_code}")
        if response.status_code == 204:
            print("✅ Plain text message sent successfully!")
        else:
            print(f"❌ Error: {response.text}")
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    # Test with an embed (like breakout alerts)
    print("\n=== Testing Embed Message ===")
    embed = {
        "title": "🧪 CANSLIM Test Embed",
        "description": "Grade: A (16) | RS 95 | Cup w/Handle\n$100.00 (+5.0%) | Pivot $95.00\nZone: $95.00 - $99.75 | Vol 1.5x",
        "color": 0x00FF00,  # Green
        "footer": {"text": "🐂 Bullish • Test Alert"},
    }
    
    embed_payload = {
        "username": "CANSLIM Monitor",
        "embeds": [embed]
    }
    
    try:
        response = requests.post(test_webhook, json=embed_payload, timeout=10)
        print(f"Status: {response.status_code}")
        if response.status_code == 204:
            print("✅ Embed message sent successfully!")
        else:
            print(f"❌ Error: {response.text}")
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    print("\n=== Recommendation ===")
    if not breakout_webhook_url and webhook_url:
        print("Your config uses 'webhook_url' as default.")
        print("The breakout system should fall back to this, but you could also add:")
        print("  breakout_webhook_url: <your webhook URL>")
        print("to your discord config section for explicit configuration.")

if __name__ == "__main__":
    test_discord()
