# Market Regime Thread Documentation

## Overview

The **RegimeThread** monitors overall market conditions using IBD's distribution day methodology. It provides market regime classification that other threads use to adjust their behavior - particularly suppressing breakout and pyramid alerts during market corrections.

**Key Characteristics:**
- **Scope:** Market indices (SPY/QQQ) and overnight futures (ES/NQ/YM)
- **Frequency:** Checks every 5 minutes (configurable)
- **Morning Alert:** Daily at 8:30 AM ET
- **Output:** Discord alerts to `market` channel + regime state for other threads

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          REGIME THREAD CYCLE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    MORNING ANALYSIS (8:30 AM ET)                      │   │
│  │                                                                       │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │   Polygon    │  │    IBKR      │  │   Database   │                │   │
│  │  │  SPY/QQQ     │  │   Futures    │  │   D-Days     │                │   │
│  │  │   Bars       │  │  ES/NQ/YM    │  │   History    │                │   │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │   │
│  │         │                 │                 │                         │   │
│  │         └────────────────┬┴─────────────────┘                         │   │
│  │                          ▼                                            │   │
│  │                 ┌────────────────────┐                                │   │
│  │                 │  DISTRIBUTION DAY  │                                │   │
│  │                 │     TRACKER        │                                │   │
│  │                 │  ───────────────── │                                │   │
│  │                 │  • Count D-Days    │                                │   │
│  │                 │  • Check Expiry    │                                │   │
│  │                 │  • Calculate Trend │                                │   │
│  │                 └─────────┬──────────┘                                │   │
│  │                           │                                           │   │
│  │                           ▼                                           │   │
│  │                 ┌────────────────────┐                                │   │
│  │                 │    FTD TRACKER     │                                │   │
│  │                 │  ───────────────── │                                │   │
│  │                 │  • Rally Attempts  │                                │   │
│  │                 │  • FTD Detection   │                                │   │
│  │                 │  • Phase Tracking  │                                │   │
│  │                 └─────────┬──────────┘                                │   │
│  │                           │                                           │   │
│  │                           ▼                                           │   │
│  │                 ┌────────────────────┐                                │   │
│  │                 │   REGIME SCORER    │                                │   │
│  │                 │  ───────────────── │                                │   │
│  │                 │  • Composite Score │                                │   │
│  │                 │  • Entry Risk      │                                │   │
│  │                 │  • Classification  │                                │   │
│  │                 └─────────┬──────────┘                                │   │
│  │                           │                                           │   │
│  └───────────────────────────┼──────────────────────────────────────────┘   │
│                              │                                               │
│                              ▼                                               │
│         ┌────────────────────────────────────────────────────────┐          │
│         │               OUTPUT & INTEGRATION                      │          │
│         │                                                         │          │
│         │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │          │
│         │  │   Database   │  │   Discord    │  │    Other     │  │          │
│         │  │   Storage    │  │    Alert     │  │   Threads    │  │          │
│         │  └──────────────┘  └──────────────┘  └──────────────┘  │          │
│         │                                                         │          │
│         └────────────────────────────────────────────────────────┘          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Market Phases

IBD defines four primary market phases:

```
                    ┌─────────────────────┐
                    │ CONFIRMED_UPTREND   │
                    │    0-4 D-Days       │
                    │   Green Light ✓     │
                    └─────────┬───────────┘
                              │
              D-Days increase to 5+
                              │
                              ▼
                    ┌─────────────────────┐
                    │ UPTREND_PRESSURE    │
                    │    5-6 D-Days       │
                    │   Yellow Caution    │
                    └─────────┬───────────┘
                              │
              D-Days increase to 7+
              OR FTD fails
                              │
                              ▼
                    ┌─────────────────────┐
                    │    CORRECTION       │◄─────────────────┐
                    │    7+ D-Days        │                   │
                    │   Red - No Buys     │                   │
                    └─────────┬───────────┘                   │
                              │                               │
                 First up day after low                       │
                              │                               │
                              ▼                               │
                    ┌─────────────────────┐                   │
                    │   RALLY_ATTEMPT     │                   │
                    │  Day 1-3 of Rally   │───────────────────┘
                    │   Watch and Wait    │   Rally fails
                    └─────────┬───────────┘   (undercuts low)
                              │
              Day 4+ with 1.25%+ gain
              on higher volume (FTD)
                              │
                              ▼
                    ┌─────────────────────┐
                    │ CONFIRMED_UPTREND   │
                    └─────────────────────┘
```

### Phase Definitions

| Phase | D-Days | FTD Status | Exposure | Meaning |
|-------|--------|------------|----------|---------|
| **CONFIRMED_UPTREND** | 0-4 | Valid | 80-100% | Full buying mode |
| **UPTREND_PRESSURE** | 5-6 | Valid but stressed | 60-80% | Be selective |
| **RALLY_ATTEMPT** | N/A | In progress | 40-60% | Wait for FTD |
| **CORRECTION** | 7+ | None | 0-40% | Defensive posture |

---

## Distribution Days

### Definition

A distribution day (D-Day) occurs when:
1. Major index (SPY or QQQ) closes **DOWN ≥ 0.2%** from prior close
2. Volume is **HIGHER** than prior day's volume

This indicates institutional selling (distribution).

### Example

```
Date        Close    Change   Volume      Prior Vol   D-Day?
─────────────────────────────────────────────────────────────
Jan 28      $480.50  -0.35%   95M         90M         ✓ YES
Jan 29      $482.20  +0.35%   85M         95M         No (up day)
Jan 30      $481.00  -0.25%   80M         85M         No (lower vol)
Jan 31      $478.50  -0.52%   110M        80M         ✓ YES
```

### Tracking

The system maintains a **rolling 25-day window** of distribution days:

```python
class DistributionDay:
    symbol: str           # SPY or QQQ
    date: date
    close_price: float
    change_pct: float     # e.g., -0.35
    volume: int
    prior_volume: int
    expiry_date: date     # 25 trading days out
    expired_by: str       # 'time', 'rally', or null
```

### Expiration Rules

Distribution days expire (and count decreases) when:

1. **TIME**: 25 trading days have passed
2. **RALLY**: Index rallies 5%+ above the D-day's close price

```python
def check_expiration(d_day, current_price, current_date):
    # Time expiration
    if trading_days_since(d_day.date) >= 25:
        return expire(d_day, reason='time')

    # Rally expiration
    rally_pct = (current_price - d_day.close_price) / d_day.close_price
    if rally_pct >= 0.05:  # 5%
        return expire(d_day, reason='rally')
```

### 5-Day Trend

The system calculates a 5-day trend to show direction:

```python
def calculate_trend(current_count, count_5_days_ago):
    delta = current_count - count_5_days_ago

    if delta < 0:
        return "IMPROVING"      # D-days declining
    elif delta > 0:
        return "WORSENING"      # D-days increasing
    else:
        if current_count <= 3:
            return "HEALTHY"    # Low and stable
        elif current_count <= 5:
            return "STABLE"     # Moderate and stable
        else:
            return "ELEVATED_STABLE"  # High but stable
```

---

## Follow-Through Day (FTD)

### Definition

A Follow-Through Day is a strong up day that signals a potential new uptrend:

**Requirements:**
- Must be **Day 4 or later** of a rally attempt
- Major index gains **≥ 1.25%** (conservative) or 1.5% (traditional)
- Volume **higher** than prior day

### Rally Attempt Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        RALLY ATTEMPT LIFECYCLE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CORRECTION          DAY 1              DAY 2-3            DAY 4+            │
│  ──────────          ─────              ───────            ─────             │
│                                                                              │
│  New Low      →    First Up Day   →   Hold Above Low   →  FTD Eligible      │
│  Made              Establishes         Rally continues    If gain ≥ 1.25%   │
│                    "Rally Low"         if no undercut     + higher volume   │
│                                                           = New Uptrend!    │
│                                                                              │
│                           │                    │                             │
│                           │                    │  Undercut Rally Low         │
│                           │                    │         │                   │
│                           ▼                    ▼         ▼                   │
│                      Rally Low           RALLY FAILED                        │
│                      Established         Back to Correction                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### FTD Tracking

```python
class FollowThroughDay:
    date: date
    symbol: str              # SPY or QQQ
    gain_pct: float          # The FTD gain (e.g., 1.8%)
    volume_ratio: float      # vs prior day
    rally_day_number: int    # Day 4, 5, 6...
    ftd_low: float           # Price level to watch
    is_failed: bool          # Has FTD been undercut?
    failed_date: date        # When it failed
```

### FTD Failure

An FTD fails when the index closes below either:
- The rally low (price that started the rally)
- The FTD day's low

```python
def check_ftd_failure(ftd, current_close):
    if current_close < ftd.ftd_low:
        return mark_failed(ftd)
    if current_close < rally_low:
        return mark_failed(ftd)
```

---

## Regime Score Calculation

### Weighted Composite Score

The system calculates a composite score from multiple factors:

| Component | Weight | Score Range | Description |
|-----------|--------|-------------|-------------|
| SPY D-Days | 25% | -2 to +2 | SPY distribution count |
| QQQ D-Days | 25% | -2 to +2 | QQQ distribution count |
| D-Day Trend | 20% | -1 to +1 | 5-day trend direction |
| ES Futures | 10% | -1 to +1 | Overnight S&P futures |
| NQ Futures | 10% | -1 to +1 | Overnight Nasdaq futures |
| YM Futures | 10% | -1 to +1 | Overnight Dow futures |

### D-Day Scoring

```python
def score_distribution_count(count):
    if count <= 3:
        return +2.0   # Confirmed uptrend
    elif count <= 5:
        return +0.5   # Mild pressure
    elif count <= 7:
        return -0.5   # Under pressure
    else:
        return -2.0   # Correction
```

### Overnight Futures Scoring

```python
def score_futures(change_pct):
    if change_pct >= 0.25:
        return +1.0   # Bullish
    elif change_pct <= -0.25:
        return -1.0   # Bearish
    else:
        return 0.0    # Neutral
```

### Trend Scoring

```python
def score_trend(trend):
    scores = {
        'IMPROVING': +1.0,
        'HEALTHY': +0.5,
        'STABLE': 0.0,
        'ELEVATED_STABLE': -0.5,
        'WORSENING': -1.0
    }
    return scores.get(trend, 0.0)
```

### FTD Adjustment

Additional adjustment based on FTD status:

| Condition | Adjustment |
|-----------|------------|
| FTD today | +0.50 |
| FTD from pressure (recovery) | +0.40 |
| Valid FTD ≤5 days old | +0.30 |
| Active rally attempt | +0.10 |
| Rally failed today | -0.30 |

### Final Classification

```python
def classify_regime(composite_score):
    if composite_score >= 0.50:
        return "BULLISH"
    elif composite_score >= -0.65:
        return "NEUTRAL"
    else:
        return "BEARISH"
```

---

## Entry Risk Assessment

A separate **tactical layer** assesses TODAY's favorability for new entries:

### Components

| Factor | Weight | Score Range |
|--------|--------|-------------|
| Overnight Futures | 40% | -0.40 to +0.40 |
| D-Day Trend | 35% | -0.35 to +0.35 |
| D-Day Count | 25% | -0.25 to +0.25 |
| FTD Bonus | +0.50 max | Contextual |

### Risk Levels

| Level | Score | Meaning |
|-------|-------|---------|
| **LOW** | ≥ +0.75 | Favorable for entries |
| **MODERATE** | +0.25 to +0.75 | Be selective |
| **ELEVATED** | -0.24 to +0.24 | Caution warranted |
| **HIGH** | < -0.24 | Avoid new entries |

---

## Integration with Other Threads

### How Regime Data is Shared

The RegimeThread stores regime data in the database, which other threads read:

```python
# RegimeThread saves:
class MarketRegimeAlert:
    timestamp: datetime
    regime: str              # BULLISH, NEUTRAL, BEARISH
    phase: str               # CONFIRMED_UPTREND, etc.
    entry_risk: str          # LOW, MODERATE, ELEVATED, HIGH
    composite_score: float
    spy_d_days: int
    qqq_d_days: int
    trend: str
```

### BreakoutThread Integration

The BreakoutThread reads regime data to suppress alerts during corrections:

```python
# In BreakoutThread._check_position():

# Get current market regime
regime = self._get_market_regime()  # Reads from DB

# Check if we should suppress
if self._should_suppress(regime, alert_subtype):
    if alert_subtype == AlertSubtype.CONFIRMED:
        # Convert CONFIRMED to SUPPRESSED
        return create_alert(
            subtype=AlertSubtype.SUPPRESSED,
            message="Breakout suppressed - market in correction",
            priority="P2"
        )
    elif alert_subtype == AlertSubtype.APPROACHING:
        # Skip APPROACHING alerts entirely in correction
        if suppress_approaching_in_correction:
            return None
```

**Suppression Rules:**

| Alert Type | Normal Behavior | In Correction/Bearish |
|------------|-----------------|----------------------|
| CONFIRMED | Fire with P1 | → SUPPRESSED (P2) |
| APPROACHING | Fire with P2 | → Filtered out |
| IN_BUY_ZONE | Fire with P1 | → Fire (reduced priority) |
| EXTENDED | Fire with P2 | → Fire normally |

### PositionThread Integration

The PositionThread uses regime for pyramid suppression:

```python
# In PyramidChecker:

def check(context):
    # Get regime from context (passed from PositionThread)
    if context.market_regime == "BEARISH":
        # Suppress pyramid alerts
        if subtype in [P1_READY, P2_READY, PULLBACK]:
            return create_alert(
                subtype=AlertSubtype.SUPPRESSED,
                priority="P2",
                message="Pyramid suppressed - market bearish"
            )
```

**Position Alert Suppression:**

| Alert | Normal | In Correction |
|-------|--------|---------------|
| P1_READY | Fire | → SUPPRESSED |
| P2_READY | Fire | → SUPPRESSED |
| PULLBACK | Fire | → SUPPRESSED |
| HARD_STOP | Fire | → Fire (never suppress) |
| TP1 | Fire | → Fire (always take profits) |

### Configuration

```yaml
alerts:
  enable_suppression: true               # Master switch

  breakout:
    suppress_in_correction: true         # Suppress CONFIRMED
    suppress_approaching_in_correction: true  # Filter APPROACHING
```

---

## Morning Alert Format

Daily alert sent at 8:30 AM ET:

```
🌅 MORNING MARKET REGIME ALERT
Tuesday, February 3, 2026 • 08:30 AM ET

═══════════════════════════════════════════════════════════

📊 IBD STATUS: 🟢 Confirmed Uptrend | 80-100%
Updated today - Overall environment supports new positions

═══════════════════════════════════════════════════════════

📊 D-DAY COUNT (25-Day Rolling)
┌─────────┬─────┬───────┬─────────────────┐
│ Index   │ Cnt │ 5d Δ  │ Trend           │
├─────────┼─────┼───────┼─────────────────┤
│ SPY     │  2  │  -1   │ IMPROVING       │
│ QQQ     │  3  │  -2   │ IMPROVING       │
└─────────┴─────┴───────┴─────────────────┘

🟢 Trend: IMPROVING

D-Day Distribution (25 days):
[░░░░░░░░░░░░▓░░░░░░▓░░░░░]
            ^        ^
         D-Day    D-Day

═══════════════════════════════════════════════════════════

🌙 OVERNIGHT FUTURES
┌─────────────────────────────────────┐
│ ES +0.45% │ NQ +0.32% │ YM +0.52%   │
│  🟢        │  🟢        │  🟢        │
└─────────────────────────────────────┘

═══════════════════════════════════════════════════════════

📈 REGIME SCORE BREAKDOWN

Composite Score: +0.68
[████████████████░░░░] +0.68

Components:
  SPY D-Days (2):     +2.00 × 25% = +0.50
  QQQ D-Days (3):     +2.00 × 25% = +0.50
  Trend (IMPROVING):  +1.00 × 20% = +0.20
  ES Futures (+0.45): +1.00 × 10% = +0.10
  NQ Futures (+0.32): +1.00 × 10% = +0.10
  YM Futures (+0.52): +1.00 × 10% = +0.10
  ─────────────────────────────────────
  Subtotal:                         +1.50
  FTD Bonus (valid):               -0.00
  ─────────────────────────────────────
  Final Score:                      +0.68

Classification: 🟢 BULLISH

═══════════════════════════════════════════════════════════

📊 MARKET PHASE

Current Phase: CONFIRMED_UPTREND
FTD: Jan 15, 2026 (+1.8%, Day 4)
Status: Valid (not failed)

═══════════════════════════════════════════════════════════

⚠️ ENTRY RISK ASSESSMENT

Risk Level: 🟢 LOW (+0.85)
────────────────────────────────────
Favorable conditions for new entries

Components:
  Overnight Futures: +0.40 (strong bullish)
  D-Day Trend:       +0.35 (improving)
  D-Day Count:       +0.25 (low)
  FTD Context:       +0.15 (recent valid)

═══════════════════════════════════════════════════════════

📋 COMBINED GUIDANCE

Strategic (IBD):
✅ Confirmed Uptrend - green light for buying

Tactical (Today):
✅ Entry Risk LOW - act on quality setups

Recommendations:
→ Act on A and B grade breakout setups
→ Use standard position sizing
→ Continue to hold existing winners

═══════════════════════════════════════════════════════════

📈 TREND CONTEXT

Prior Score: +0.35 → Current: +0.68
Direction: IMPROVING (+0.33)
```

---

## Phase Change Alerts

When market phase transitions, a special alert is sent:

```
🔄 MARKET PHASE CHANGE
─────────────────────────────────────
UPTREND_PRESSURE → CONFIRMED_UPTREND
Change Type: UPGRADE ⬆️
─────────────────────────────────────
Trigger: Distribution day expired (time)
SPY D-Days: 5 → 4
QQQ D-Days: 5 → 4
─────────────────────────────────────
New Phase: Confirmed buying conditions
```

---

## YAML Configuration Reference

### Complete Regime Config

```yaml
# Market Regime Settings
market_regime:
  enabled: true
  alert_time: "08:30"            # Morning alert time (ET)
  use_indices: false              # true = SPX/COMP, false = SPY/QQQ

# Distribution Day Settings
distribution_days:
  decline_threshold: -0.2         # % decline to qualify as D-day
  lookback_days: 25               # Rolling window size
  rally_expiration_pct: 5.0       # % rally to expire D-day
  trend_comparison_days: 5        # Days for trend calculation
  enable_stalling: false          # Include stalling days
  stalling_max_gain: 0.4          # Max gain for stalling day

# FTD Settings
ftd_settings:
  ftd_min_gain: 1.25              # Minimum gain for FTD (%)
  ftd_earliest_day: 4             # Earliest day for FTD

# Market Phase Thresholds
market_phase:
  pressure_threshold: 5           # D-days for UPTREND_PRESSURE
  correction_threshold: 7         # D-days for CORRECTION

# Scoring Weights
market_regime_scoring:
  weights:
    spy_distribution: 0.25
    qqq_distribution: 0.25
    distribution_trend: 0.20
    overnight_es: 0.10
    overnight_nq: 0.10
    overnight_ym: 0.10

# Service Interval
service:
  poll_intervals:
    market: 300                   # 5 minutes
```

---

## Database Schema

### Key Tables

| Table | Purpose |
|-------|---------|
| `distribution_days` | Individual D-day records |
| `distribution_day_counts` | Daily snapshots for trend |
| `rally_attempts` | Rally tracking |
| `follow_through_days` | Confirmed FTDs |
| `market_regime_alerts` | Daily regime snapshots |
| `market_phase_history` | Phase transition audit |
| `ibd_exposure_current` | Current IBD status (manual) |

### DistributionDay Table

```sql
CREATE TABLE distribution_days (
    id INTEGER PRIMARY KEY,
    symbol TEXT,              -- SPY or QQQ
    date DATE,
    close_price REAL,
    change_pct REAL,
    volume INTEGER,
    prior_volume INTEGER,
    expiry_date DATE,
    expired_by TEXT,          -- 'time', 'rally', null
    created_at DATETIME
);
```

### MarketRegimeAlert Table

```sql
CREATE TABLE market_regime_alerts (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    regime TEXT,              -- BULLISH, NEUTRAL, BEARISH
    phase TEXT,               -- CONFIRMED_UPTREND, etc.
    entry_risk TEXT,          -- LOW, MODERATE, ELEVATED, HIGH
    composite_score REAL,
    spy_d_days INTEGER,
    qqq_d_days INTEGER,
    trend TEXT,
    overnight_es REAL,
    overnight_nq REAL,
    overnight_ym REAL
);
```

---

## Troubleshooting

### Morning Alert Not Firing

1. **Check time:** Alert fires at 8:30 AM ET
2. **Check config:** `market_regime.enabled: true`
3. **Check Discord webhook:** `webhooks.market` configured
4. **Check logs:** Look for regime thread errors

### D-Day Count Seems Wrong

1. **Verify data source:** Check Polygon API connection
2. **Check volume data:** D-days require higher volume
3. **Check expiration:** D-days expire after 25 days or 5% rally
4. **Manual verification:** Compare with MarketSmith/IBD

### FTD Not Detected

1. **Check rally day:** Must be Day 4+
2. **Check gain:** Must be ≥1.25%
3. **Check volume:** Must be higher than prior day
4. **Check if rally failed:** May have undercut low

### Breakout Alerts Being Suppressed Unexpectedly

1. **Check regime:** View current regime in GUI or Discord
2. **Check suppression config:** `enable_suppression: true`
3. **Verify D-day count:** May have crossed into correction

### Futures Data Missing

1. **Check IBKR connection:** Futures need market data subscription
2. **Check time:** Futures may not be trading
3. **Fallback:** System uses neutral (0) if futures unavailable

---

## CLI Commands

### Service Control

**Start the service (includes RegimeThread):**
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

### Seed Historical Regime Data

**IMPORTANT:** Before using the learning system or analyzing historical performance, you should seed historical regime data. This populates:
- Distribution days for SPY/QQQ
- Market phase history (CONFIRMED_UPTREND, CORRECTION, etc.)
- Follow-Through Days (FTDs) and rally attempts
- Daily regime scores and alerts

**Quick Command (Recommended):**
```bash
# Check current regime status
python -m canslim_monitor regime

# Seed 1 year of historical data (uses config file for DB and API key)
python -m canslim_monitor regime seed --start 2024-01-01

# Seed specific date range
python -m canslim_monitor regime seed --start 2024-01-01 --end 2024-12-31

# Clear existing data before re-seeding
python -m canslim_monitor regime seed --start 2024-01-01 --clear

# Use custom config
python -m canslim_monitor -c user_config.yaml regime seed --start 2024-01-01
```

**Direct Module Access (Alternative):**
```bash
# Seed with direct module invocation
python -m canslim_monitor.regime.historical_seeder \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --config user_config.yaml

# Seed with explicit API key
python -m canslim_monitor.regime.historical_seeder \
    --start 2024-01-01 \
    --api-key YOUR_POLYGON_API_KEY

# Clear existing data before re-seeding (avoid duplicates)
python -m canslim_monitor.regime.historical_seeder \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --clear

# Use actual indices (SPX/COMP) instead of ETFs (SPY/QQQ)
python -m canslim_monitor.regime.historical_seeder \
    --start 2024-01-01 \
    --use-indices

# Custom database path
python -m canslim_monitor.regime.historical_seeder \
    --start 2024-01-01 \
    --db C:/Trading/canslim_monitor/canslim_positions.db
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--start` | Yes | Start date (YYYY-MM-DD) |
| `--end` | No | End date (YYYY-MM-DD), defaults to yesterday |
| `--db` | No | Database path (default: from config or canslim_monitor.db) |
| `--config` | No | Config file path for API key and settings |
| `--api-key` | No | Polygon.io API key (overrides config) |
| `--clear` | No | Clear existing data in range before seeding |
| `--use-indices` | No | Use SPX/COMP instead of SPY/QQQ |
| `--verbose`, `-v` | No | Verbose output (default: enabled) |

**Output Example:**
```
Seeding regime data from 2024-01-01 to 2024-12-31...

Processing 2024-01-02... SPY D-days: 2, QQQ D-days: 3
Processing 2024-01-03... SPY D-days: 2, QQQ D-days: 3
Processing 2024-01-04... New D-day: SPY -0.35%
...

==================================================
SEEDING COMPLETE
==================================================
Date range: 2024-01-01 to 2024-12-31
Days processed: 252
Distribution days created: 47
Regime alerts created: 252
Phase changes recorded: 8
FTDs detected: 3
```

**What Gets Seeded:**

| Data Type | Table | Description |
|-----------|-------|-------------|
| Distribution Days | `distribution_days` | Each D-day with date, change %, volume |
| D-Day Counts | `distribution_day_counts` | Daily snapshots for trend analysis |
| Regime Alerts | `market_regime_alerts` | Daily regime score and classification |
| Phase History | `market_phase_history` | Phase transitions over time |
| Rally Attempts | `rally_attempts` | Rally tracking during corrections |
| FTDs | `follow_through_days` | Confirmed follow-through days |

**Why This Matters for Learning:**

The learning system uses `market_regime_at_entry` to analyze how regime affects trade outcomes:
- Trades entered during CONFIRMED_UPTREND vs CORRECTION
- Impact of D-day count on success rates
- FTD timing correlation with breakout success

Without historical regime data, the learning system cannot:
- Calculate regime-based factor correlations
- Optimize market_regime weight in scoring
- Provide regime context for historical backtests

**Recommended Seeding Strategy:**

```bash
# 1. Seed at least 2 years for robust learning
python -m canslim_monitor.regime.historical_seeder \
    --start 2023-01-01 \
    --config user_config.yaml

# 2. After initial seed, the service maintains current data
python -m canslim_monitor service start

# 3. If you need to reseed (e.g., after config changes):
python -m canslim_monitor.regime.historical_seeder \
    --start 2024-01-01 \
    --clear \
    --config user_config.yaml
```

### Get Current Market Regime

Query the current market regime via IPC:

```bash
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'GET_REGIME'})
print(f'Regime: {result[\"regime\"]}')
print(f'Exposure Range: {result[\"exposure\"][0]}-{result[\"exposure\"][1]}%')
"
```

### Check Regime Thread Status

```bash
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'GET_THREAD_STATUS', 'thread': 'market'})
print(f'State: {result[\"state\"]}')
print(f'Alerts sent: {result[\"message_count\"]}')
print(f'Last check: {result[\"last_check\"]}')
"
```

### Force Regime Analysis

Trigger an immediate regime analysis via IPC:

```bash
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'FORCE_CHECK'})
print('Regime analysis triggered')
print(result)
"
```

### View Distribution Day History

Query distribution days from the database:

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.regime.models_regime import DistributionDay
from datetime import datetime, timedelta

db = Database('canslim_positions.db')
session = db.get_new_session()

# Get D-days from last 25 trading days
cutoff = datetime.now() - timedelta(days=35)
d_days = session.query(DistributionDay).filter(
    DistributionDay.date >= cutoff,
    DistributionDay.expired_by.is_(None)
).order_by(DistributionDay.date.desc()).all()

print('Active Distribution Days:')
print('-' * 50)
for d in d_days:
    print(f'{d.symbol} {d.date}: {d.change_pct:+.2f}% vol={d.volume:,}')
print(f'\\nTotal: SPY={len([d for d in d_days if d.symbol==\"SPY\"])}, QQQ={len([d for d in d_days if d.symbol==\"QQQ\"])}')
session.close()
"
```

### View Rally/FTD Status

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.regime.models_regime import RallyAttempt, FollowThroughDay
from datetime import datetime, timedelta

db = Database('canslim_positions.db')
session = db.get_new_session()

# Check for active rally
rally = session.query(RallyAttempt).filter(
    RallyAttempt.status == 'active'
).order_by(RallyAttempt.start_date.desc()).first()

if rally:
    print(f'Active Rally: Started {rally.start_date}, Day {rally.day_count}')
    print(f'Rally Low: \${rally.rally_low:.2f}')
else:
    print('No active rally attempt')

# Check recent FTD
ftd = session.query(FollowThroughDay).filter(
    FollowThroughDay.is_failed == False
).order_by(FollowThroughDay.date.desc()).first()

if ftd:
    print(f'\\nLast Valid FTD: {ftd.date}')
    print(f'Gain: {ftd.gain_pct:+.2f}%, Volume Ratio: {ftd.volume_ratio:.2f}x')
else:
    print('\\nNo valid FTD')

session.close()
"
```

### Test Regime Scenarios

```bash
# Test regime thread logic (if test command supports it)
python -m canslim_monitor test_position -s regime -v
```

### Reload Configuration

Reload regime config without restarting service:

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
| `GET_STATUS` | Get full service status including regime thread |
| `GET_THREAD_STATUS` | Get specific thread status (`thread: 'market'`) |
| `GET_REGIME` | Get current regime and exposure recommendation |
| `FORCE_CHECK` | Trigger immediate regime analysis |
| `RELOAD_CONFIG` | Reload configuration from YAML |

### Monitor Regime Thread

```bash
# Watch regime status every 5 minutes
while true; do
    python -c "
from canslim_monitor.service.ipc_client import IPCClient
from datetime import datetime
client = IPCClient()
regime = client.send_command({'type': 'GET_REGIME'})
status = client.send_command({'type': 'GET_THREAD_STATUS', 'thread': 'market'})
print(f'{datetime.now()}: {regime[\"regime\"]} ({regime[\"exposure\"][0]}-{regime[\"exposure\"][1]}%) - {status[\"state\"]}')
" 2>/dev/null
    sleep 300
done
```

### Example: Check Before Trading

Quick script to run before market open:

```bash
#!/bin/bash
# morning_check.sh - Run before market open

echo "=== CANSLIM Morning Check ==="
echo ""

python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()

# Get regime
regime = client.send_command({'type': 'GET_REGIME'})
print(f'Market Regime: {regime[\"regime\"]}')
print(f'Exposure Range: {regime[\"exposure\"][0]}-{regime[\"exposure\"][1]}%')
print('')

# Get service status
status = client.send_command({'type': 'GET_STATUS'})
if status.get('service_running'):
    print('Service: Running ✓')
    print(f'IBKR: {\"Connected ✓\" if status.get(\"ibkr_connected\") else \"Disconnected ✗\"}')
else:
    print('Service: NOT RUNNING ✗')
"
```

---

## Related Files

| File | Purpose |
|------|---------|
| `regime/regime_thread.py` | Main regime monitoring logic |
| `regime/distribution_tracker.py` | D-day counting and tracking |
| `regime/ftd_tracker.py` | Rally and FTD detection |
| `regime/market_regime.py` | Regime scoring and classification |
| `regime/market_phase_manager.py` | Phase transition management |
| `regime/discord_regime.py` | Discord alert formatting |
| `regime/models_regime.py` | Database models |

---

## Quick Reference

### D-Day Thresholds

| D-Days | Phase | Action |
|--------|-------|--------|
| 0-4 | CONFIRMED_UPTREND | Buy freely |
| 5-6 | UPTREND_PRESSURE | Be selective |
| 7+ | CORRECTION | No new buys |

### Regime Classification

| Score | Regime | Exposure |
|-------|--------|----------|
| ≥ +0.50 | BULLISH | 80-100% |
| -0.65 to +0.50 | NEUTRAL | 40-80% |
| ≤ -0.65 | BEARISH | 0-40% |

### Entry Risk Levels

| Risk | Score | Action |
|------|-------|--------|
| LOW | ≥ +0.75 | Act on setups |
| MODERATE | +0.25 to +0.75 | Be selective |
| ELEVATED | -0.24 to +0.24 | Caution |
| HIGH | < -0.24 | Avoid entries |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Feb 2026 | Initial documentation |
