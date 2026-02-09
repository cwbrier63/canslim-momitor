# Breakout Thread Documentation

## Overview

The **BreakoutThread** is a background service that monitors **State 0 (Watchlist)** positions for pivot breakouts. It runs continuously during market hours, checking each watchlist position against its pivot price and generating Discord alerts when breakout conditions are detected.

**Key Characteristics:**
- **Scope:** Only monitors State 0 positions (watchlist)
- **Frequency:** Checks every 60 seconds (configurable)
- **Hours:** Market hours only (9:30 AM - 4:00 PM ET)
- **Output:** Discord alerts via webhooks

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         BREAKOUT THREAD CYCLE                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   Database   │───▶│  Position    │───▶│    IBKR      │              │
│  │  State = 0   │    │   Loop       │    │  Get Price   │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│                             │                    │                      │
│                             ▼                    ▼                      │
│                      ┌──────────────┐    ┌──────────────┐              │
│                      │   Polygon    │    │  Calculate   │              │
│                      │  Get MAs     │───▶│  Metrics     │              │
│                      └──────────────┘    └──────────────┘              │
│                                                 │                       │
│                                                 ▼                       │
│                      ┌──────────────────────────────────┐              │
│                      │     DETERMINE ALERT TYPE         │              │
│                      │  CONFIRMED | BUY_ZONE | EXTENDED │              │
│                      │  APPROACHING | SUPPRESSED        │              │
│                      └──────────────────────────────────┘              │
│                                                 │                       │
│                                                 ▼                       │
│                      ┌──────────────────────────────────┐              │
│                      │        APPLY FILTERS             │              │
│                      │  Grade | Volume | Extension      │              │
│                      └──────────────────────────────────┘              │
│                                                 │                       │
│                                                 ▼                       │
│                      ┌──────────────────────────────────┐              │
│                      │      AlertService → Discord      │              │
│                      │    (with cooldown management)    │              │
│                      └──────────────────────────────────┘              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Alert Types

### Summary Table

| Alert Type | Emoji | Color | When Triggered | Action |
|------------|-------|-------|----------------|--------|
| **CONFIRMED** | 🚀 | Green | Valid breakout with volume | BUY within buy zone |
| **IN_BUY_ZONE** | ✅ | Yellow | In zone but weak confirmation | WATCH for volume |
| **EXTENDED** | ⚠️ | Red | Beyond buy zone | DO NOT CHASE |
| **APPROACHING** | 👀 | Blue | Near pivot | PREPARE for breakout |
| **SUPPRESSED** | ⛔ | Red | Breakout during correction | WAIT for market |

### Detailed Trigger Conditions

#### 🚀 CONFIRMED Breakout
A valid breakout signal - the strongest buy indicator.

**All conditions must be true:**
- Price is above pivot
- Price is within buy zone (0% to +5% above pivot)
- Volume ratio ≥ 1.4x (40% above 50-day average)
- Strong close (price in upper half of day's range)
- Market NOT in correction (or becomes SUPPRESSED)

```
Example: NVDA breaks out at $135.50
- Pivot: $131.25
- Distance: +3.2% (within 5% buy zone) ✓
- Volume: 1.8x average ✓
- Close: Near day's high ✓
→ CONFIRMED breakout
```

#### ✅ IN_BUY_ZONE
Stock is above pivot and in the buy zone, but lacking full confirmation.

**Conditions:**
- Price is above pivot
- Price is within buy zone (0% to +5%)
- Volume ratio ≥ `volume_threshold_buy_zone` (default: 0 = no requirement)
- Does NOT meet CONFIRMED criteria (weak close OR low volume)

```
Example: AAPL at $185.20
- Pivot: $180.00
- Distance: +2.9% (in buy zone) ✓
- Volume: 0.9x (below 1.4x threshold)
→ IN_BUY_ZONE (needs volume confirmation)
```

#### ⚠️ EXTENDED
Stock has moved beyond the safe buy zone - chasing is risky.

**Conditions:**
- Price is more than 5% above pivot
- Distance ≤ `max_extended_pct` (default: 7%)
- Alerts beyond `max_extended_pct` are filtered out entirely

```
Example: MSFT at $425.00
- Pivot: $400.00
- Distance: +6.25% (beyond 5% buy zone)
→ EXTENDED (wait for pullback)
```

#### 👀 APPROACHING
Stock is near its pivot point - prepare for potential breakout.

**Conditions:**
- Price is within 1% below pivot (configurable via `approaching_pct`)
- Volume ratio ≥ `volume_threshold_approaching` (default: 0)
- NOT suppressed by market correction (if `suppress_approaching_in_correction` is true)

```
Example: GOOGL at $174.50
- Pivot: $175.00
- Distance: -0.3% (within 1% of pivot)
→ APPROACHING (prepare for breakout)
```

#### ⛔ SUPPRESSED
Would be a CONFIRMED breakout, but market conditions are unfavorable.

**Conditions:**
- Meets all CONFIRMED criteria
- Market regime is BEARISH or CORRECTION

```
Example: META breaks out with volume during market correction
→ SUPPRESSED (wait for market confirmation)
```

---

## Filtering System

Alerts pass through multiple filter stages to reduce noise and ensure quality signals.

### Filter Pipeline

```
Position → Volume Filter → Extension Filter → Grade Filter → Cooldown → Discord
              │                  │                │              │
              │                  │                │              │
         min_avg_volume    max_extended_pct   min_alert_grade  cooldown_minutes
         threshold_*
```

### 1. Volume Filters

Control which alerts fire based on relative volume (RVOL).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `volume_threshold_confirmed` | 1.4 | RVOL required for CONFIRMED (1.4 = 40% above average) |
| `volume_threshold_buy_zone` | 0.0 | RVOL required for IN_BUY_ZONE (0 = disabled) |
| `volume_threshold_approaching` | 0.0 | RVOL required for APPROACHING (0 = disabled) |
| `min_avg_volume` | 500000 | Minimum 50-day average volume for ANY alert |

**RVOL Calculation:**
```
RVOL = (Current Intraday Volume) / (Expected Volume at This Time)

Where:
  Expected Volume = (50-day Avg Volume) × (Minutes Since Open / 390)
```

### 2. Extension Filter

Prevents alerts on stocks that have moved too far from their pivot.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_extended_pct` | 7.0 | Maximum % above pivot for EXTENDED alerts |

**Behavior:**
- Stocks 5-7% above pivot → EXTENDED alert fires
- Stocks >7% above pivot → No alert (filtered out)
- Set to 0 to disable EXTENDED alerts entirely
- Set to 100 to allow all EXTENDED alerts

### 3. Grade Filter

Only sends alerts for setups meeting a minimum quality threshold.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_alert_grade` | C | Minimum grade for alerts (A > B > C > D > F) |

**Grade Hierarchy:**
```
A+ > A > A- > B+ > B > B- > C+ > C > C- > D+ > D > D- > F
```

**Example:** With `min_alert_grade: C`, only A, B, and C grades will alert.

### 4. Market Regime Suppression

Controls behavior during market corrections.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `suppress_in_correction` | true | Convert CONFIRMED → SUPPRESSED in corrections |
| `suppress_approaching_in_correction` | true | Block APPROACHING alerts in corrections |

---

## Cooldown System

Prevents alert spam by limiting how often the same alert can fire.

### How It Works

1. When an alert fires, it's recorded: `(symbol, alert_type, subtype) → timestamp`
2. Subsequent identical alerts are blocked until cooldown expires
3. Each symbol/type/subtype combination tracks cooldowns independently

### Configuration

```yaml
alerts:
  enable_cooldown: true      # Master switch (false = all alerts pass)
  cooldown_minutes: 60       # Default cooldown period
```

### Examples

```
10:00 AM - NVDA CONFIRMED fires → Alert sent
10:15 AM - NVDA CONFIRMED fires → BLOCKED (cooldown active)
10:30 AM - NVDA IN_BUY_ZONE fires → Alert sent (different subtype)
11:00 AM - NVDA CONFIRMED fires → Alert sent (cooldown expired)
```

---

## Discord Alert Format

### Alert Structure

```
🚀 BREAKOUT: NVDA
─────────────────────────────────────
B+ (14) | RS 94 | Cup w/Handle 2(2)
$135.50 (+3.2%) | Pivot $131.25
Zone: $131.25 - $137.81 | Vol 1.8x | Avg 25.3M
21 EMA: +2.1% | 50 MA: +5.3%
Trend: ↗ Uptrend
─────────────────────────────────────
🐂 Bullish • Today at 10:30 AM
```

### Field Explanations

| Line | Content | Description |
|------|---------|-------------|
| Title | `🚀 BREAKOUT: NVDA` | Alert type + symbol |
| Line 1 | `B+ (14) \| RS 94 \| Cup w/Handle 2(2)` | Grade (score) \| RS Rating \| Pattern Stage(Count) |
| Line 2 | `$135.50 (+3.2%) \| Pivot $131.25` | Current price (% from pivot) \| Pivot price |
| Line 3 | `Zone: $131.25 - $137.81 \| Vol 1.8x \| Avg 25.3M` | Buy zone range \| RVOL \| Avg volume |
| Line 4 | `21 EMA: +2.1% \| 50 MA: +5.3%` | Distance from moving averages |
| Line 5 | `Trend: ↗ Uptrend` | Price trend vs MAs |
| Footer | `🐂 Bullish • Today at 10:30 AM` | Market regime \| Timestamp |

### Trend Indicators

| Indicator | Meaning |
|-----------|---------|
| ↗ Uptrend | Price above both 21 EMA and 50 MA |
| ↘ Downtrend | Price below both 21 EMA and 50 MA |
| → Sideways | Price between the two MAs |
| → Unknown | MA data not available |

### Footer Warnings

| Warning | Condition |
|---------|-----------|
| `⚠️ Stale pivot` | Pivot set 60-90 days ago |
| `⚠️ Stale (XXd)` | Pivot set 90+ days ago |
| `🐻 Bearish` | Market in correction |
| `🐂 Bullish` | Market confirmed uptrend |

---

## YAML Configuration Reference

### Location
All breakout settings are in `user_config.yaml` under the `alerts.breakout` section.

### Complete Configuration

```yaml
# Service timing
service:
  poll_intervals:
    breakout: 60           # Seconds between checks (default: 60)

# Alert settings
alerts:
  # Cooldown settings
  enable_cooldown: true    # Enable/disable cooldown filtering
  cooldown_minutes: 60     # Minutes between same alert for same symbol
  enable_suppression: true # Enable market regime suppression

  # Breakout-specific settings
  breakout:
    # === VOLUME THRESHOLDS ===
    # RVOL = Relative Volume (current / expected at this time)
    # Set to 0 to disable volume requirement for that alert type

    volume_threshold_confirmed: 1.4    # RVOL for CONFIRMED (40% above avg)
    volume_threshold_buy_zone: 0.0     # RVOL for IN_BUY_ZONE (0 = no filter)
    volume_threshold_approaching: 0.0  # RVOL for APPROACHING (0 = no filter)

    # === PRICE ZONE THRESHOLDS ===
    buy_zone_pct: 5              # Max % above pivot = "buy zone" (default: 5)
    approaching_pct: 2           # Within X% below pivot = "approaching" (default: 2)
    max_extended_pct: 7.0        # Max % for EXTENDED alerts (default: 7)
                                 # Stocks beyond this are filtered out entirely

    # === QUALITY FILTERS ===
    min_alert_grade: C           # Minimum grade for alerts (A, B, C, D, F)
    min_avg_volume: 500000       # Minimum 50-day avg volume (0 = no filter)

    # === MARKET REGIME ===
    # (These may be in root config or alerts section)
    # suppress_in_correction: true
    # suppress_approaching_in_correction: true
```

### Parameter Details

#### Volume Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `volume_threshold_confirmed` | float | 1.4 | 0.0 - 5.0 | RVOL multiplier for CONFIRMED breakouts |
| `volume_threshold_buy_zone` | float | 0.0 | 0.0 - 5.0 | RVOL multiplier for IN_BUY_ZONE |
| `volume_threshold_approaching` | float | 0.0 | 0.0 - 5.0 | RVOL multiplier for APPROACHING |
| `min_avg_volume` | int | 500000 | 0 - 10000000 | Minimum 50-day average volume |

#### Price Zone Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `buy_zone_pct` | float | 5.0 | 1.0 - 15.0 | Max % above pivot for buy zone |
| `approaching_pct` | float | 2.0 | 0.5 - 5.0 | Max % below pivot for approaching |
| `max_extended_pct` | float | 7.0 | 0.0 - 100.0 | Max % for EXTENDED alerts |

#### Quality Parameters

| Parameter | Type | Default | Values | Description |
|-----------|------|---------|--------|-------------|
| `min_alert_grade` | string | "C" | A, B, C, D, F | Minimum grade to alert |

---

## Tuning Guide

### Scenario: Too Many Alerts

**Problem:** Alert channel is flooded with low-quality signals.

**Solutions:**
```yaml
alerts:
  breakout:
    min_alert_grade: B           # Only alert A and B grades
    min_avg_volume: 1000000      # Only liquid stocks (1M+ avg volume)
    max_extended_pct: 5.0        # No EXTENDED alerts (only buy zone)
    volume_threshold_buy_zone: 1.0  # Require at least average volume
```

### Scenario: Missing Good Setups

**Problem:** Not seeing alerts for valid breakouts.

**Solutions:**
```yaml
alerts:
  breakout:
    min_alert_grade: D           # Allow more grades through
    min_avg_volume: 0            # No volume filter
    volume_threshold_buy_zone: 0 # Alert all buy zone entries
    volume_threshold_approaching: 0  # Alert all approaching
```

### Scenario: Alert Spam (Same Stock Repeatedly)

**Problem:** Same stock alerting multiple times per hour.

**Solutions:**
```yaml
alerts:
  enable_cooldown: true
  cooldown_minutes: 120          # 2-hour cooldown between same alerts
```

### Scenario: Want Pullback Alerts on Extended Stocks

**Problem:** Extended stocks filtered out, missing pullback entries.

**Solutions:**
```yaml
alerts:
  breakout:
    max_extended_pct: 15.0       # Allow alerts up to 15% extended
```

---

## Troubleshooting

### Alert Not Firing

**Check these in order:**

1. **Is position State 0?** Only watchlist positions are monitored.
2. **Does position have a valid pivot?** Pivot must be > 0.
3. **Is price data available?** Check IBKR connection.
4. **Is it market hours?** Thread only runs 9:30 AM - 4:00 PM ET.
5. **Check filters:**
   - Grade above `min_alert_grade`?
   - Avg volume above `min_avg_volume`?
   - Distance within `max_extended_pct`?
   - Volume above threshold for alert type?
6. **Check cooldown:** Same alert may have fired recently.

### MA Data Showing N/A

**Causes:**
- Polygon API key not configured
- API rate limit exceeded
- Symbol not found in Polygon

**Solution:** Check `market_data.api_key` in config.

### All Pivots Showing as "Stale"

**Cause:** `pivot_set_date` was backfilled from `watch_date`.

**Solution:** Update pivot in GUI to reset `pivot_set_date` to today.

---

## CLI Commands

### Service Control

**Start the service (includes BreakoutThread):**
```bash
# Run in foreground (for debugging)
python -m canslim_monitor service start

# Run as Windows service
python -m canslim_monitor service start -b

# Check service status
python -m canslim_monitor service status

# Stop service
python -m canslim_monitor service stop
```

### Force Breakout Check

Trigger an immediate breakout check cycle via IPC:

```bash
# Using Python to send IPC command
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'FORCE_CHECK'})
print(result)
"
```

### Check Thread Status

```bash
# Get breakout thread status
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'GET_THREAD_STATUS', 'thread': 'breakout'})
print(f'State: {result[\"state\"]}')
print(f'Messages sent: {result[\"message_count\"]}')
print(f'Last check: {result[\"last_check\"]}')
"
```

### Test Breakout Scenarios

```bash
# Test breakout logic without live service
python -m canslim_monitor test_position -s breakout

# Test with live positions from database
python -m canslim_monitor test_position --live

# Test with live IBKR prices
python -m canslim_monitor test_position --live --ibkr

# Test specific symbol
python -m canslim_monitor test_position --live --symbol NVDA

# Test and send real Discord alerts
python -m canslim_monitor test_position --live --discord
```

### Reload Configuration

Reload breakout config without restarting service:

```bash
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'RELOAD_CONFIG'})
print(result)
"
```

### IPC Commands Reference

| Command | Description |
|---------|-------------|
| `GET_STATUS` | Get full service status including breakout thread |
| `GET_THREAD_STATUS` | Get specific thread status (`thread: 'breakout'`) |
| `FORCE_CHECK` | Trigger immediate breakout check cycle |
| `RELOAD_CONFIG` | Reload configuration from YAML |
| `RESET_COUNTERS` | Reset message/error counters |
| `SHUTDOWN` | Gracefully stop service |

### Example: Monitor Breakout Thread

```bash
# Watch breakout thread status every 30 seconds
while true; do
    python -c "
from canslim_monitor.service.ipc_client import IPCClient
from datetime import datetime
client = IPCClient()
result = client.send_command({'type': 'GET_THREAD_STATUS', 'thread': 'breakout'})
print(f'{datetime.now()}: {result[\"state\"]} - {result[\"message_count\"]} alerts')
" 2>/dev/null
    sleep 30
done
```

---

## Related Files

| File | Purpose |
|------|---------|
| `service/threads/breakout_thread.py` | Main breakout monitoring logic |
| `services/alert_service.py` | Alert creation, cooldowns, Discord routing |
| `services/technical_data_service.py` | Fetches MA data from Polygon |
| `utils/pivot_status.py` | Pivot staleness calculation |
| `user_config.yaml` | Configuration file |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial implementation |
| 1.1 | Feb 2026 | Added MA data display (21 EMA, 50 MA) |
| 1.2 | Feb 2026 | Fixed stale pivot threshold (30d → 60d) |
