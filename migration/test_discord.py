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
    print(f"Top-level keys: {list(discord_config.keys())}")
    
    # Get webhooks dict (new convention)
    webhooks_config = discord_config.get('webhooks', {})
    print(f"Webhook channels: {list(webhooks_config.keys())}")
    
    # Check each channel
    print("\n=== Channel Webhooks ===")
    channels = ['breakout', 'position', 'market', 'system']
    for channel in channels:
        url = webhooks_config.get(channel)
        status = 'CONFIGURED' if url else 'NOT CONFIGURED'
        print(f"  {channel}: {status}")
    
    # Check for legacy/incorrect keys
    print("\n=== Checking for Issues ===")
    issues = []
    
    # Check for typo
    if webhooks_config.get('breakoutbreakout_webhook_url'):
        issues.append("TYPO: 'breakoutbreakout_webhook_url' should be 'breakout'")
    
    # Check for _webhook_url suffix (old convention)
    for key in webhooks_config.keys():
        if '_webhook_url' in key:
            issues.append(f"OLD NAMING: '{key}' should not have '_webhook_url' suffix")
    
    # Check for rate_limit in wrong place
    if webhooks_config.get('rate_limit'):
        issues.append("MISPLACED: 'rate_limit' should be under 'discord:', not 'discord.webhooks:'")
    
    if issues:
        print("  ❌ Issues found:")
        for issue in issues:
            print(f"     - {issue}")
    else:
        print("  ✅ No naming issues found")
    
    # Determine which webhook to test
    test_webhook = webhooks_config.get('breakout') or discord_config.get('default_webhook')
    
    if not test_webhook:
        print("\n❌ ERROR: No 'breakout' webhook configured!")
        print("   Add to your config:")
        print("   discord:")
        print("     webhooks:")
        print("       breakout: \"https://discord.com/api/webhooks/...\"")
        return
    
    # Show webhook preview (masked for security)
    preview = test_webhook[:60] + "..." if len(test_webhook) > 60 else test_webhook
    print(f"\n=== Testing Breakout Webhook ===")
    print(f"URL: {preview}")
    
    # Test with a simple embed (like breakout alerts send)
    embed = {
        "title": "🧪 CANSLIM Test - Breakout Alert",
        "description": "A (16) | RS 95 | Cup w/Handle 1\n$100.00 (+5.0%) | Pivot $95.00\nZone: $95.00 - $99.75 | Vol 1.5x",
        "color": 0x00FF00,  # Green
        "footer": {"text": "🐂 Bullish • Test Alert"},
    }
    
    embed_payload = {
        "username": "CANSLIM Monitor",
        "embeds": [embed]
    }
    
    try:
        response = requests.post(test_webhook, json=embed_payload, timeout=10)
        print(f"HTTP Status: {response.status_code}")
        if response.status_code == 204:
            print("✅ SUCCESS! Check your Discord channel for the test message.")
        else:
            print(f"❌ Error: {response.text}")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_discord()
