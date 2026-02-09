# CANSLIM Monitor Operations Guide

## Complete System Documentation

**Version:** 1.0
**Last Updated:** February 2026

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Position Lifecycle & State Machine](#2-position-lifecycle--state-machine)
3. [Service Architecture](#3-service-architecture)
4. [Breakout Thread](#4-breakout-thread)
5. [Position Thread](#5-position-thread)
6. [Market Regime Thread](#6-market-regime-thread)
7. [Alert Service & Discord](#7-alert-service--discord)
8. [Configuration Reference](#8-configuration-reference)
9. [Operations & Troubleshooting](#9-operations--troubleshooting)

---

# 1. Introduction

## What is CANSLIM Monitor?

CANSLIM Monitor is a comprehensive stock position management system built around William O'Neil's IBD (Investor's Business Daily) methodology. It provides:

- **Watchlist Monitoring** - Track setups and alert on breakouts
- **Position Management** - Guide through pyramiding, profit taking, and exits
- **Market Regime Analysis** - Track distribution days and market health
- **Automated Alerts** - Discord notifications for actionable signals

## Core Workflow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        CANSLIM MONITOR WORKFLOW                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

  WATCHLIST                    POSITION BUILDING              PROFIT TAKING
  ─────────                    ─────────────────              ─────────────
  ┌─────────┐                 ┌─────────┐  ┌─────────┐       ┌─────────┐
  │ State 0 │  breakout       │ State 1 │  │ State 2 │       │ State 4 │
  │ WATCHING│────────────────▶│ ENTRY 1 │─▶│ ENTRY 2 │──┐    │ TP1 HIT │
  └─────────┘  (1/3 pos)      └─────────┘  └─────────┘  │    └─────────┘
       │                           │            │       │         │
       │                           └────────────┼───────┼─────────┼──────────┐
       │                                        │       │         │          │
       │                              ┌─────────┘       │         ▼          │
       │                              │                 │   ┌─────────┐      │
       │                              ▼                 │   │ State 5 │      │
       │                        ┌─────────┐             │   │ TP2 HIT │      │
       │                        │ State 3 │◀────────────┘   └─────────┘      │
       │                        │FULL POS │                      │           │
       │                        └─────────┘                      │           │
       │                              │                          ▼           │
       │                              │                    ┌─────────┐       │
       │                              └───────────────────▶│ State 6 │◀──────┘
       │                                                   │TRAILING │
       │                                                   └─────────┘
       │                                                        │
       │            ┌───────────────────────────────────────────┘
       │            │
       ▼            ▼
  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │State -1 │  │State-1.5│  │State -2 │
  │ CLOSED  │  │RE-ENTRY │  │STOP OUT │
  └─────────┘  │  WATCH  │  └─────────┘
               └─────────┘
                    │
                    └─────────────▶ Back to State 1 (Re-entry)
```

## IBD Methodology Alignment

| IBD Concept | System Implementation |
|-------------|----------------------|
| **Base Patterns** | Pattern field (Cup w/Handle, Flat Base, etc.) |
| **Pivot Point** | Pivot price for breakout detection |
| **Relative Strength** | RS Rating (90+ preferred) |
| **EPS Rating** | Stored for scoring |
| **Distribution Days** | Regime thread tracks D-days on SPY/QQQ |
| **Follow-Through Day** | FTD detection in regime analysis |
| **7-8% Stop Loss** | Configurable hard stop per position |
| **Pyramid Strategy** | States 1→2→3 with add zones |
| **Profit Taking** | TP1 (20%), TP2 (25%+), Trailing |
| **8-Week Hold Rule** | Suppress TP1 for fast movers |

---

# 2. Position Lifecycle & State Machine

## State Overview

### Active States (Positions in Progress)

| State | Name | Color | Description | Your Action |
|-------|------|-------|-------------|-------------|
| **0** | WATCHING | Cyan | On watchlist, awaiting breakout | Wait for breakout signal |
| **1** | ENTRY_1 | Green | Initial position (first entry) | Watch for pyramid opportunity |
| **2** | ENTRY_2 | Teal | First pyramid added | Watch for second pyramid |
| **3** | FULL_POSITION | Dark Green | Full position established | Hold and manage |
| **4** | TP1_HIT | Yellow | First profit target (20%) | Trail stop on remainder |
| **5** | TP2_HIT | Orange | Second profit target (25%+) | Consider closing |
| **6** | TRAILING | Purple | Trailing stop active | Let winners run |

### Exit States

| State | Name | Color | Description | Purpose |
|-------|------|-------|-------------|---------|
| **-1.5** | WATCHING_EXITED | Purple | Previously owned, monitoring | Watch for re-entry opportunity |
| **-1** | CLOSED | Gray | Position manually closed | Archive |
| **-2** | STOPPED_OUT | Red | Closed at stop loss | Review and learn |

---

## State Transitions

### Forward Progression (Normal Path)

```
0 (Watching) → 1 (Entry 1) → 2 (Entry 2) → 3 (Full) → 4 (TP1) → 5 (TP2) → 6 (Trailing)
```

### Entry Transitions (Building Position)

#### State 0 → State 1: Initial Buy
**Trigger:** Breakout alert CONFIRMED with volume

**Required Fields:**
- `e1_shares` - Shares purchased (typically 1/3 of target)
- `e1_price` - Entry price
- `stop_price` - Technical stop level (typically -7% to -8%)

**What Happens:**
- BreakoutThread detects price above pivot with 40%+ volume
- Alert fires with position sizing recommendation
- User executes trade and logs in GUI

#### State 1 → State 2: First Pyramid
**Trigger:** PYRAMID/P1_READY alert (0-5% gain zone)

**Required Fields:**
- `e2_shares` - Additional shares
- `e2_price` - Add price

**Conditions:**
- Price in 0-5% zone above entry
- Position profitable (PnL > 0)
- At least 2 days since entry
- Volume supporting move

#### State 2 → State 3: Full Position
**Trigger:** PYRAMID/P2_READY alert (5-10% gain zone)

**Required Fields:**
- `e3_shares` - Final add shares
- `e3_price` - Add price

**Conditions:**
- Price in 5-10% zone above entry
- At least 2 days since last pyramid
- Full position now established

### Profit Taking Transitions

#### State 3 → State 4: First Profit Target (TP1)
**Trigger:** PROFIT/TP1 alert (20% gain)

**Required Fields:**
- `tp1_sold` - Shares sold (typically 1/3)
- `tp1_price` - Sale price

**Action:** Sell 1/3 of position to lock in gains

#### State 4 → State 5: Second Profit Target (TP2)
**Trigger:** PROFIT/TP2 alert (25%+ gain)

**Required Fields:**
- `tp2_sold` - Shares sold (another 1/3)
- `tp2_price` - Sale price

**Action:** Sell another 1/3, keep final 1/3 for trailing

#### State 5 → State 6: Trailing Stop Mode
**Trigger:** Manual or when trailing stop logic activates

**What Happens:**
- Trailing stop trails 8% below daily highs
- Activates after 15%+ maximum gain
- Lets winners run with protection

### Exit Transitions

#### Any Active State → State -1: Manual Close
**Use For:**
- Taking all profits
- Earnings exit
- Manual decision
- Climax top detected

**Required Fields:**
- `close_date` - Exit date
- `close_price` - Exit price
- `close_reason` - Why (TP1_HIT, CLIMAX_TOP, MANUAL, etc.)

#### Any Active State → State -2: Stopped Out
**Trigger:** STOP/HARD_STOP alert

**What Happens:**
- Price hit or breached stop level
- Position closed at loss
- Recorded for learning

#### Any Active State → State -1.5: Re-entry Watch
**Use For:**
- Stop out but setup may improve
- Technical exit but fundamentals still good
- Want to re-enter on pullback

**What Happens:**
- Position shares cleared
- Original pivot preserved
- Monitored for MA bounce or pivot retest
- Expires after 60 days

### Re-entry from State -1.5

#### State -1.5 → State 1: Re-enter Position
**Trigger:** ALT_ENTRY/MA_BOUNCE or ALT_ENTRY/PIVOT_RETEST

**Conditions:**
- Stock bounces off 21 EMA or 50 MA
- Or retests original pivot point
- Within 60 days of exit

**Required Fields:**
- `e1_shares` - New position shares
- `e1_price` - New entry price
- `stop_price` - New stop level

---

## Skip Transitions (Faster Progression)

Sometimes price action justifies skipping states:

| Skip | When | Example |
|------|------|---------|
| 1 → 3 | Quick pyramids | Both adds done same day |
| 1 → 4 | Skip pyramids, take profit | Price ran before adds |
| 3 → 5 | Skip TP1, take larger profit | Price at 30%, take both |
| 3 → 6 | Move to trailing | Want to let winner run |
| 4 → 6 | From TP1 to trailing | After TP1, just trail rest |

---

## Kanban Board Display

The GUI displays states as columns:

```
┌───────────┬───────────┬───────────┬───────────┬───────────┬───────────┬───────────┐
│ Watching  │ Entry 1   │ Entry 2   │ Full Pos  │ TP1 Hit   │ TP2 Hit   │ Trailing  │
│  (0)      │  (1)      │  (2)      │  (3)      │  (4)      │  (5)      │  (6)      │
├───────────┼───────────┼───────────┼───────────┼───────────┼───────────┼───────────┤
│  NVDA     │  AAPL     │  MSFT     │  GOOGL    │  META     │           │  AMZN     │
│  AMD      │           │           │           │           │           │           │
│  SMCI     │           │           │           │           │           │           │
└───────────┴───────────┴───────────┴───────────┴───────────┴───────────┴───────────┘
```

**Closed Panel (collapsed by default):**
- State -2 (Stopped Out) - Red cards
- State -1 (Closed) - Gray cards
- State -1.5 (Re-entry Watch) - Purple cards

---

# 3. Service Architecture

## Overview

The CANSLIM Monitor runs as a Windows service with multiple worker threads:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SERVICE CONTROLLER                                     │
│                                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Breakout   │  │   Position   │  │    Regime    │  │ Maintenance  │         │
│  │    Thread    │  │    Thread    │  │    Thread    │  │    Thread    │         │
│  │   (60s)      │  │   (30s)      │  │   (300s)     │  │   (5:00PM)   │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
│         │                 │                 │                 │                  │
│         └─────────────────┴────────┬────────┴─────────────────┘                  │
│                                    │                                             │
│                           ┌────────┴────────┐                                    │
│                           │  Shared Resources                                    │
│                           │  ───────────────                                     │
│                           │  • IBKR Client                                       │
│                           │  • Discord Notifier                                  │
│                           │  • Database Sessions                                 │
│                           │  • Polygon API Client                                │
│                           │  • Alert Service                                     │
│                           │  • Scoring Engine                                    │
│                           └─────────────────┘                                    │
│                                    │                                             │
│                           ┌────────┴────────┐                                    │
│                           │    IPC Server   │◄───── GUI Communication            │
│                           └─────────────────┘                                    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Thread Responsibilities

| Thread | Poll Interval | Monitors | Alerts |
|--------|---------------|----------|--------|
| **Breakout** | 60s | State 0 (watchlist) | Breakout signals |
| **Position** | 30s | States 1-6 (active) | Stops, profits, pyramids, health |
| **Regime** | 300s | Market indices | D-days, FTD, regime changes |
| **Maintenance** | Once/day | Database | Volume updates, earnings, cleanup |

## Service Commands

```bash
# Run in foreground (debugging)
python -m canslim_monitor.service.service_main run

# Install as Windows service
python -m canslim_monitor.service.service_main install

# Control service
python -m canslim_monitor.service.service_main start
python -m canslim_monitor.service.service_main stop
python -m canslim_monitor.service.service_main status
```

## Shared Resources

### IBKR Client
- Real-time price data during market hours
- Overnight futures data (ES, NQ, YM)
- Auto-reconnection with exponential backoff

### Database
- SQLite database for all position data
- Session-per-thread pattern for thread safety
- Automatic backups daily

### Discord Notifier
- Webhook integration for alerts
- Rate limiting (30 requests/minute)
- Channel routing by alert type

### Polygon API
- Moving average data (21 EMA, 50 MA, 200 MA)
- Volume averages
- Earnings dates

---

# 4. Breakout Thread

**Full documentation:** See [docs/BREAKOUT_THREAD.md](BREAKOUT_THREAD.md)

## Summary

The BreakoutThread monitors **State 0 (Watchlist)** positions for pivot breakouts during market hours.

### Alert Types

| Alert | Emoji | When Triggered | Action |
|-------|-------|----------------|--------|
| **CONFIRMED** | 🚀 | Above pivot, in buy zone, 40%+ volume | BUY |
| **IN_BUY_ZONE** | ✅ | Above pivot, weak volume | WATCH |
| **EXTENDED** | ⚠️ | >5% above pivot | DO NOT CHASE |
| **APPROACHING** | 👀 | Within 2% of pivot | PREPARE |
| **SUPPRESSED** | ⛔ | Breakout during correction | WAIT |

### Key Configuration

```yaml
alerts:
  breakout:
    volume_threshold_confirmed: 1.4    # 40% above average for CONFIRMED
    buy_zone_pct: 5                    # Max % above pivot for buy zone
    approaching_pct: 2                 # Within 2% triggers APPROACHING
    max_extended_pct: 7.0              # Filter alerts beyond 7%
    min_alert_grade: C                 # Minimum setup grade
    min_avg_volume: 500000             # Minimum 50-day avg volume
```

---

# 5. Position Thread

## Overview

The PositionThread monitors **State 1-6 (active positions)** for stop losses, profit targets, and health conditions.

## Checker Classes

The Position Monitor uses 7 specialized checkers:

```
PositionMonitor
├── StopChecker        (P0 - Capital Protection)
├── ProfitChecker      (P1 - Profit Taking)
├── PyramidChecker     (P1 - Position Building)
├── MAChecker          (P0/P1 - Technical Violations)
├── HealthChecker      (P0/P2 - Position Health)
├── ReentryChecker     (P1/P2 - Add Opportunities)
└── WatchlistAltEntry  (P1 - Watchlist Pullbacks)
```

---

## 5.1 StopChecker (P0 - Capital Protection)

**Priority:** P0 (Immediate - exit position now)

The most critical checker. Protects capital by alerting on stop loss conditions.

### Alerts

| Alert | Condition | Cooldown | Action |
|-------|-----------|----------|--------|
| **HARD_STOP** | Price ≤ stop level | None | EXIT IMMEDIATELY |
| **TRAILING_STOP** | State 4+ AND price ≤ trailing stop | None | SELL TO LOCK PROFIT |
| **WARNING** | Within 2% of stop | 60 min | WATCH CLOSELY |

### Trailing Stop Logic

**Activation Conditions:**
- Position in State 4+ (TP1 hit and beyond)
- Maximum gain reached 15%+

**Calculation:**
```
trailing_stop = max_price × (1 - trail_pct)
trailing_stop = max(trailing_stop, entry_price)  # Never below entry
```

**Example:**
```
Entry: $100
Max Price: $125 (25% gain)
Trail %: 8%
Trailing Stop: $125 × 0.92 = $115 (locked 15% gain)
```

### Configuration

```yaml
position_monitoring:
  stop_loss:
    base_pct: 7.0              # Default stop loss percentage
    warning_buffer_pct: 2.0    # Distance for warning alert
  trailing_stop:
    activation_pct: 15.0       # Gain needed to activate
    trail_pct: 8.0             # Trail distance from max
```

---

## 5.2 ProfitChecker (P1 - Profit Taking)

### Alerts

| Alert | Condition | Cooldown | Action |
|-------|-----------|----------|--------|
| **TP1** | PnL ≥ 20% AND tp1_sold = 0 | 60 min | SELL 1/3 |
| **TP2** | PnL ≥ 25% AND tp2_sold = 0 | 60 min | SELL 1/3 |
| **EIGHT_WEEK_HOLD** | 20%+ gain within 21 days | 60 min | HOLD - BIG WINNER |

### 8-Week Hold Rule

This is the IBD rule for potential big winners:

**Trigger:** Position gains 20%+ within 3 weeks (21 days) of breakout

**Effect:** Suppresses TP1 alert - suggests holding for at least 8 weeks

**Rationale:** Stocks that move 20% quickly often become 100%+ winners

### Configuration

```yaml
position_monitoring:
  eight_week_hold:
    gain_threshold_pct: 20.0    # Gain needed
    trigger_window_days: 21     # Must be within this many days
    hold_weeks: 8               # Suggested hold period
```

---

## 5.3 PyramidChecker (P1 - Position Building)

### Alerts

| Alert | Condition | States | Cooldown | Action |
|-------|-----------|--------|----------|--------|
| **P1_READY** | 0-5% gain zone | 1 | 60 min | ADD 1/3 |
| **P1_EXTENDED** | >5% above entry | 1 | 60 min | WAIT - TOO EXTENDED |
| **P2_READY** | 5-10% gain zone | 2 | 60 min | ADD 1/3 |
| **P2_EXTENDED** | >10% above entry | 2 | 60 min | WAIT |
| **PULLBACK** | Within 1% of 21 EMA | 1-3 | 60 min | ADD ON PULLBACK |

### Pyramid Zones

```
Entry Price: $100
├── P1 Zone: $100.00 - $105.00 (0-5%)
│   └── Alert: P1_READY
├── Gap Zone: $105.00 - $110.00 (5-10%)
│   └── Alert: P2_READY
└── Extended: > $110.00 (>10%)
    └── Alert: EXTENDED (wait for pullback)
```

### Pre-Conditions

Pyramid alerts only fire if:
- Position is profitable (PnL > 0)
- At least 2 days since entry
- Previous pyramid not already done

### Configuration

```yaml
position_monitoring:
  pyramid:
    py1_min_pct: 0.0         # Start of P1 zone
    py1_max_pct: 5.0         # End of P1 zone
    py2_min_pct: 5.0         # Start of P2 zone
    py2_max_pct: 10.0        # End of P2 zone
    min_bars_since_entry: 2  # Days before pyramiding
    pullback_ema_tolerance: 1.0  # EMA proximity for pullback
```

---

## 5.4 MAChecker (P0/P1 - Technical Violations)

### Alerts

| Alert | Condition | Cooldown | Priority | Action |
|-------|-----------|----------|----------|--------|
| **MA_50_SELL** | Close < 50 MA AND volume ≥ 1.5x | None | P0 | SELL |
| **MA_50_WARNING** | Within 2% of 50 MA | 60 min | P1 | WATCH |
| **EMA_21_SELL** | State 4+ AND 2 closes < 21 EMA | 60 min | P1 | SELL |
| **TEN_WEEK_SELL** | Close < 10-week MA | 60 min | P0 | SELL |
| **CLIMAX_TOP** | Exhaustion signals | 60 min | P0/P1 | SELL |

### MA 50 Breakdown

IBD rule: A close below the 50-day MA on above-average volume is a sell signal.

**Conditions:**
- Price closes below 50-day moving average
- Volume ≥ 1.5x the 50-day average volume

### Climax Top Detection

Detects potential exhaustion/distribution patterns:

**Signals (scored):**
- Volume 2.5x+ average = 30 points
- Price spread 4%+ (high-low) = 25 points
- Gap up 2%+ at open = 25 points
- Reversal (close in lower 30%) = 20 points

**Alert Triggers:**
- Score ≥ 50: P1 alert (warning)
- Score ≥ 75: P0 alert (act now)

### Configuration

```yaml
position_monitoring:
  technical:
    ma_50_warning_pct: 2.0         # Distance for warning
    ma_50_volume_confirm: 1.5      # Volume multiplier for breakdown
    ema_21_consecutive_days: 2     # Closes needed for sell
```

---

## 5.5 HealthChecker (Position Quality)

### Alerts

| Alert | Condition | Cooldown | Priority | Action |
|-------|-----------|----------|----------|--------|
| **CRITICAL** | Health score < 50 | 60 min | P0 | REVIEW |
| **EARNINGS** | Earnings within 14 days | 60 min | P0/P1 | SEE GUIDANCE |
| **LATE_STAGE** | Base stage ≥ 4 | 60 min | P2 | CAUTION |
| **EXTENDED** | >5% above pivot | 60 min | P1/P2 | WATCH |

### Health Score

Calculated from multiple factors:
- Days in position vs progress
- RS rating trend
- Volume characteristics
- Distance from stop
- Base stage

**Interpretation:**
- 80-100: Healthy position
- 60-80: Monitor closely
- 50-60: Concern, review needed
- <50: Critical, take action

### Earnings Guidance (P&L-Based)

The earnings alert provides specific guidance based on current P&L:

| P&L | Recommendation |
|-----|----------------|
| ≥ 10% | HOLD WITH TRAILING STOP |
| 0% to 10% | SELL BEFORE EARNINGS |
| < 0% | EXIT BEFORE EARNINGS |

### Configuration

```yaml
position_monitoring:
  health:
    time_threshold_days: 60      # Days before time warning
    tp1_progress_threshold: 0.5  # Expected progress to TP1
    deep_base_threshold: 35.0    # Deep base warning
    ud_ratio_warning: 0.8        # Up/Down volume warning
  earnings:
    warning_days: 14             # Days before earnings warning
    critical_days: 5             # P0 alert threshold
    negative_threshold: 0.0      # Breakeven threshold
    reduce_threshold: 10.0       # Safe to hold threshold
```

---

## 5.6 ReentryChecker (Add Opportunities)

Finds add opportunities for **State 1-2** positions (not full yet).

### Alerts

| Alert | Condition | States | Cooldown | Action |
|-------|-----------|--------|----------|--------|
| **EMA_21** | Within 1% of 21 EMA AND up 5%+ | 1-2 | 60 min | ADD ON DIP |
| **PULLBACK** | Within 1.5% of 50 MA AND up 8%+ | 1-2 | 60 min | ADD ON DIP |
| **IN_BUY_ZONE** | Near pivot AND max gain 5%+ | 1-2 | 60 min | ADD |

### Configuration

```yaml
alerts:
  alt_entry:
    ema_21_bounce_pct: 1.5       # EMA proximity
    ma_50_bounce_pct: 2.0        # MA proximity
    bounce_volume_min: 0.7       # Min volume for bounce
    pivot_retest_pct: 3.0        # Pivot proximity
```

---

## 5.7 WatchlistAltEntryChecker (State 0 Pullbacks)

Finds alternative entry opportunities for **State 0 (watchlist)** positions that extended and pulled back.

### Alerts

| Alert | Condition | Cooldown | Action |
|-------|-----------|----------|--------|
| **MA_BOUNCE** | 21 EMA bounce after 5%+ extension | 4 hours | BUY ON BOUNCE |
| **MA_BOUNCE** | 50 MA bounce after 5%+ extension | 4 hours | BUY ON BOUNCE |
| **PIVOT_RETEST** | Back in buy zone after extension | 4 hours | BUY RETEST |

### Logic

1. Stock broke out and extended 5%+ above pivot (too late to chase)
2. Stock pulls back to 21 EMA, 50 MA, or retests pivot
3. Alert fires for alternative entry opportunity
4. Expires after 30 days

### Configuration

```yaml
alerts:
  alt_entry:
    min_extension_pct: 5.0       # Must extend 5%+ first
    ema_21_bounce_pct: 1.5       # Within 1.5% of EMA
    ma_50_bounce_pct: 2.0        # Within 2% of MA
    bounce_volume_min: 0.7       # Volume can be lighter
    pivot_retest_pct: 3.0        # Within 3% of pivot
    cooldown_hours: 4
```

---

## Alert Priority Summary

### P0 (Immediate - Red - Act Now)

- STOP/HARD_STOP
- STOP/TRAILING_STOP
- TECHNICAL/MA_50_SELL
- TECHNICAL/TEN_WEEK_SELL
- TECHNICAL/CLIMAX_TOP (score ≥ 75)
- HEALTH/CRITICAL
- HEALTH/EARNINGS (≤ 5 days)

### P1 (Normal - Blue - Actionable)

- BREAKOUT/CONFIRMED
- PYRAMID/P1_READY
- PYRAMID/P2_READY
- PROFIT/TP1
- PROFIT/TP2
- STOP/WARNING
- TECHNICAL/MA_50_WARNING
- TECHNICAL/EMA_21_SELL
- ADD/PULLBACK
- ALT_ENTRY/MA_BOUNCE
- ALT_ENTRY/PIVOT_RETEST

### P2 (Informational - Gray)

- BREAKOUT/APPROACHING
- PYRAMID/P1_EXTENDED
- PYRAMID/P2_EXTENDED
- PROFIT/EIGHT_WEEK_HOLD
- HEALTH/LATE_STAGE
- HEALTH/EXTENDED (5-10%)

---

# 6. Market Regime Thread

## Overview

The RegimeThread monitors market conditions using IBD's distribution day methodology.

## Market Phases

| Phase | D-Days | Meaning | Exposure |
|-------|--------|---------|----------|
| **CONFIRMED_UPTREND** | 0-4 | Valid FTD, low distribution | 80-100% |
| **UPTREND_PRESSURE** | 5-6 | FTD valid but under pressure | 60-80% |
| **RALLY_ATTEMPT** | N/A | No FTD, rally in progress | 40-60% |
| **CORRECTION** | 7+ | No valid FTD | 0-40% |

## Distribution Days

### Definition

A distribution day occurs when:
- Major index (SPY or QQQ) closes DOWN ≥ 0.2%
- Volume is HIGHER than prior day

### Tracking

- Rolling 25-day window
- D-days expire after 25 trading days
- D-days expire when index rallies 5%+ from the D-day close

### 5-Day Trend

```
Trend Calculation:
delta = current_count - count_5_days_ago

IMPROVING:       delta < 0 (D-days declining)
WORSENING:       delta > 0 (D-days increasing)
HEALTHY:         delta = 0 AND count ≤ 3
STABLE:          delta = 0 AND count 4-5
ELEVATED_STABLE: delta = 0 AND count ≥ 6
```

## Follow-Through Day (FTD)

### Definition

A Follow-Through Day signals a potential new uptrend:
- Must be Day 4+ of a rally attempt
- Major index gains ≥ 1.25%
- Volume higher than prior day

### Rally Attempt Lifecycle

```
Day 1: First up day after new low
Day 2-3: Market must hold above rally low
Day 4+: Eligible for FTD
        If gain ≥ 1.25% on higher volume → FTD confirmed
        Market moves to CONFIRMED_UPTREND
```

## Regime Score

Weighted composite score from -1.5 to +1.5:

| Component | Weight | Score Range |
|-----------|--------|-------------|
| SPY D-Days | 25% | -2 to +2 |
| QQQ D-Days | 25% | -2 to +2 |
| D-Day Trend | 20% | -1 to +1 |
| ES Futures | 10% | -1 to +1 |
| NQ Futures | 10% | -1 to +1 |
| YM Futures | 10% | -1 to +1 |

**Interpretation:**
- ≥ +0.50: BULLISH (full exposure)
- -0.65 to +0.50: NEUTRAL (selective)
- ≤ -0.65: BEARISH (defensive)

## Entry Risk Assessment

Daily tactical assessment for new entries:

| Risk Level | Score | Meaning |
|------------|-------|---------|
| LOW | ≥ +0.75 | Favorable for entries |
| MODERATE | +0.25 to +0.75 | Be selective |
| ELEVATED | -0.24 to +0.24 | Caution warranted |
| HIGH | < -0.24 | Avoid new entries |

## Morning Alert

Daily alert at 8:30 AM ET includes:

```
🌅 MORNING MARKET REGIME ALERT

📊 IBD STATUS: Confirmed Uptrend | 80-100%

📊 D-DAY COUNT (25-Day Rolling)
SPY: 2 D-days (5d Δ: -1) IMPROVING
QQQ: 3 D-days (5d Δ: -2) IMPROVING

🌙 OVERNIGHT FUTURES
ES +0.45% | NQ +0.32% | YM +0.52%

⚠️ ENTRY RISK: LOW (+0.85)
Favorable for new entries

📋 GUIDANCE
✅ Green light for breakout entries
→ Act on A and B grade setups
```

## Configuration

```yaml
market_regime:
  enabled: true
  alert_time: "08:30"
  use_indices: false           # true = SPX/COMP, false = SPY/QQQ

distribution_days:
  decline_threshold: -0.2      # % decline to qualify
  lookback_days: 25            # Rolling window
  rally_expiration_pct: 5.0    # % rally to expire D-day
  enable_stalling: false       # Stalling day detection
```

---

# 7. Alert Service & Discord

## Alert Routing

Alerts are routed to different Discord channels:

| Channel | Alert Types |
|---------|-------------|
| **breakout** | BREAKOUT, ALT_ENTRY |
| **position** | STOP, PROFIT, PYRAMID, ADD, TECHNICAL, HEALTH |
| **market** | MARKET, regime changes |
| **system** | Service status, errors |

## Cooldown System

Prevents alert spam:

```yaml
alerts:
  enable_cooldown: true
  cooldown_minutes: 60         # Default cooldown

# Per-alert-type cooldowns in position_monitoring section
position_monitoring:
  cooldowns:
    hard_stop: 0               # No cooldown (always fire)
    stop_warning: 120          # 2 hours
    trailing_stop: 0           # No cooldown
    tp1: 1440                  # 24 hours
    tp2: 1440                  # 24 hours
    pyramid: 240               # 4 hours
    ma_50_warning: 1440        # 24 hours
    ma_50_sell: 1440           # 24 hours
    earnings: 1440             # 24 hours
```

## Market Suppression

During market corrections, certain alerts are suppressed:

**Suppressed to SUPPRESSED subtype:**
- BREAKOUT/CONFIRMED → BREAKOUT/SUPPRESSED
- PYRAMID/P1_READY → Converted to suppressed
- PYRAMID/P2_READY → Converted to suppressed

**Configuration:**

```yaml
alerts:
  enable_suppression: true
```

## Discord Webhook Setup

```yaml
discord:
  webhooks:
    breakout: "https://discord.com/api/webhooks/..."
    position: "https://discord.com/api/webhooks/..."
    market: "https://discord.com/api/webhooks/..."
    system: "https://discord.com/api/webhooks/..."
    rate_limit: 30             # Requests per minute
```

---

# 8. Configuration Reference

## Complete YAML Structure

```yaml
# =============================================================================
# SERVICE CONFIGURATION
# =============================================================================
service:
  poll_intervals:
    breakout: 60               # Watchlist check interval (seconds)
    position: 30               # Position check interval (seconds)
    market: 300                # Regime check interval (seconds)
  market_hours_only: true      # Only run during market hours
  market_open: "09:30"         # Market open time (ET)
  market_close: "16:00"        # Market close time (ET)
  timezone: "America/New_York"

# =============================================================================
# IBKR CONNECTION
# =============================================================================
ibkr:
  host: 127.0.0.1
  port: 4001                   # TWS: 7497, Gateway: 4001
  client_id_base: 20
  timeout: 30
  max_retries: 3
  reconnect:
    enabled: true
    initial_delay: 30
    gateway_restart_delay: 180
    max_delay: 300
    backoff_factor: 1.5
    max_attempts: 0            # 0 = unlimited
    health_check_interval: 30

# =============================================================================
# MARKET DATA (Polygon/Massive)
# =============================================================================
market_data:
  provider: massive            # or "polygon"
  api_key: "YOUR_API_KEY"
  base_url: "https://api.polygon.io"
  timeout: 30
  rate_limit_delay: 0.1

# =============================================================================
# DISCORD WEBHOOKS
# =============================================================================
discord:
  webhooks:
    breakout: "https://discord.com/api/webhooks/..."
    position: "https://discord.com/api/webhooks/..."
    market: "https://discord.com/api/webhooks/..."
    system: "https://discord.com/api/webhooks/..."
    rate_limit: 30

# =============================================================================
# DATABASE
# =============================================================================
database:
  path: "c:/trading/canslim_monitor/canslim_positions.db"
  backup_interval: 86400       # Daily backup
  backup_retain: 7             # Keep 7 backups

# =============================================================================
# ALERTS - GLOBAL
# =============================================================================
alerts:
  enable_cooldown: true
  cooldown_minutes: 60
  enable_suppression: true     # Suppress during corrections

  # Breakout-specific
  breakout:
    volume_threshold_confirmed: 1.4    # 40% above average
    volume_threshold_buy_zone: 0.0     # No requirement
    volume_threshold_approaching: 0.0  # No requirement
    buy_zone_pct: 5                    # 0-5% above pivot
    approaching_pct: 2                 # Within 2% of pivot
    max_extended_pct: 7.0              # Filter beyond 7%
    min_alert_grade: C                 # Minimum grade
    min_avg_volume: 500000             # Minimum 50-day volume

  # Alternative entry
  alt_entry:
    min_extension_pct: 5.0
    ema_21_bounce_pct: 1.5
    ma_50_bounce_pct: 2.0
    bounce_volume_min: 0.7
    pivot_retest_pct: 3.0
    cooldown_hours: 4

# =============================================================================
# POSITION MANAGEMENT
# =============================================================================
position_management:
  default_stop_pct: 7.0
  default_tp1_pct: 20.0
  default_tp2_pct: 25.0
  pyramid_1_pct: 2.5           # Add zone start
  pyramid_2_pct: 5.0           # Add zone 2 start
  max_extension_pct: 10.0

# =============================================================================
# POSITION MONITORING
# =============================================================================
position_monitoring:
  # Stop Loss
  stop_loss:
    base_pct: 7.0
    warning_buffer_pct: 2.0
    stage_multipliers:
      1: 1.0                   # Stage 1: full stop
      2: 0.85                  # Stage 2: tighter
      3: 0.7                   # Stage 3: tighter
      4: 0.6                   # Stage 4: tighter
      5: 0.5                   # Stage 5: tightest

  # Trailing Stop
  trailing_stop:
    activation_pct: 15.0       # Gain needed to activate
    trail_pct: 8.0             # Trail below max

  # Pyramid
  pyramid:
    py1_min_pct: 0.0
    py1_max_pct: 5.0
    py2_min_pct: 5.0
    py2_max_pct: 10.0
    min_bars_since_entry: 2
    pullback_ema_tolerance: 1.0

  # 8-Week Hold
  eight_week_hold:
    gain_threshold_pct: 20.0
    trigger_window_days: 21
    hold_weeks: 8

  # Technical
  technical:
    ma_50_warning_pct: 2.0
    ma_50_volume_confirm: 1.5
    ema_21_consecutive_days: 2

  # Health
  health:
    time_threshold_days: 60
    tp1_progress_threshold: 0.5
    deep_base_threshold: 35.0
    ud_ratio_warning: 0.8

  # Earnings
  earnings:
    warning_days: 14
    critical_days: 5
    negative_threshold: 0.0
    reduce_threshold: 10.0

  # Cooldowns (minutes)
  cooldowns:
    hard_stop: 0
    stop_warning: 120
    trailing_stop: 0
    tp1: 1440
    tp2: 1440
    eight_week_hold: 10080
    pyramid: 240
    ma_50_warning: 1440
    ma_50_sell: 1440
    ema_21_sell: 1440
    ten_week_sell: 10080
    health_warning: 60
    health_critical: 60
    earnings: 1440
    late_stage: 10080

# =============================================================================
# MARKET REGIME
# =============================================================================
market_regime:
  enabled: true
  alert_time: "08:30"
  use_indices: false

distribution_days:
  decline_threshold: -0.2
  lookback_days: 25
  rally_expiration_pct: 5.0
  enable_stalling: false

# =============================================================================
# SCORING
# =============================================================================
scoring:
  use_learned_weights: false
  rs_floor: 70
  weights:
    pattern_base_type: 10
    stage_adjustment: -5
    base_depth: -3
    base_length: 2
    prior_uptrend: 3
    rs_rating: 4
    rs_90_plus: 5
    rs_95_plus: 8
    eps_rating: 2
    comp_rating: 1
    ad_rating_bonus: 5
    ad_rating_penalty: -8
    ud_vol_ratio: 3
    volume_at_pivot: 5
    market_bullish: 3
    market_bearish: -5
  thresholds:
    A_plus: 25
    A: 18
    B: 10
    C: 0

# =============================================================================
# MAINTENANCE
# =============================================================================
maintenance:
  run_hour: 17
  run_minute: 0
  enable_volume_update: true
  enable_earnings_update: true
  enable_cleanup: true

# =============================================================================
# LOGGING
# =============================================================================
logging:
  base_dir: "C:/Trading/canslim_monitor/logs"
  level: DEBUG
  retention_days: 30
  console_level: INFO
  categories:
    service: DEBUG
    breakout: DEBUG
    position: DEBUG
    market: DEBUG
    ibkr: DEBUG
    discord: DEBUG
    database: INFO
    gui: INFO

# =============================================================================
# GUI
# =============================================================================
gui:
  price_refresh_interval: 300
  futures_refresh_interval: 300
  service_status_interval: 60
```

---

# 9. Operations & Troubleshooting

## Starting the System

### 1. Start IBKR Gateway/TWS
- Open IB Gateway or Trader Workstation
- Login with your credentials
- Ensure API connections are enabled (port 4001 or 7497)

### 2. Start the Service
```bash
# Option A: Run in console (for debugging)
python -m canslim_monitor.service.service_main run

# Option B: Start as Windows service
python -m canslim_monitor.service.service_main start
```

### 3. Start the GUI
```bash
python -m canslim_monitor gui
```

## Common Issues

### No Breakout Alerts

**Check in order:**

1. **Position in State 0?** Only watchlist items are monitored
2. **Pivot set?** Pivot must be > 0
3. **Market hours?** Thread only runs 9:30 AM - 4:00 PM ET
4. **IBKR connected?** Check service status
5. **Grade above minimum?** Default is C
6. **Volume above minimum?** Default is 500,000
7. **Cooldown active?** Check if same alert fired recently

### No Position Alerts

**Check in order:**

1. **Position in State 1-6?** Only active positions monitored
2. **Price data available?** Check IBKR connection
3. **Market hours?** Thread only runs during market
4. **Cooldown active?** Many alerts have 24-hour cooldown

### MA Data Showing N/A

**Causes:**
- Polygon API key not configured
- API rate limit exceeded
- Symbol not found

**Solution:**
```yaml
market_data:
  api_key: "YOUR_VALID_KEY"
```

### All Pivots Showing "Stale"

**Cause:** Pivots set more than 60 days ago

**Solution:** Update pivot in GUI to reset `pivot_set_date`

### Trailing Stop Not Firing

**Requirements:**
- Position must be State 4+ (TP1 hit)
- Maximum gain must have reached 15%+
- Current price must be 8%+ below max

### Discord Alerts Not Arriving

1. Check webhook URLs in config
2. Check rate limit (30/minute)
3. Check Discord channel permissions
4. Check service logs for errors

## Service Monitoring

### Check Service Status
```bash
python -m canslim_monitor.service.service_main status
```

### View Logs
```
C:\Trading\canslim_monitor\logs\
├── service_YYYYMMDD.log
├── breakout_YYYYMMDD.log
├── position_YYYYMMDD.log
└── market_YYYYMMDD.log
```

### GUI Status Bar

The GUI shows real-time service status:
- Thread states (running/waiting/error)
- Message counts
- Last check times
- IBKR connection status

## Database Backup

Automatic daily backups at 5 PM ET:
```
C:\Trading\canslim_monitor\backups\
├── canslim_positions_20260201.db
├── canslim_positions_20260202.db
└── ...
```

## Emergency Procedures

### Stop All Alerts
```bash
# Stop the service
python -m canslim_monitor.service.service_main stop
```

### Reset Cooldowns
Delete cooldown entries from database or restart service.

### Revert Configuration
Keep a backup of `user_config.yaml` before changes.

---

## Quick Reference Card

### Alert Priority Guide

| Priority | Color | Meaning | Response |
|----------|-------|---------|----------|
| **P0** | Red | Capital at risk | Act immediately |
| **P1** | Blue | Action recommended | Review and act |
| **P2** | Gray | Information | Note for later |

### State Progression

```
0 → 1 → 2 → 3 → 4 → 5 → 6
│   │   │   │   │   │   │
│   │   │   │   │   │   └── Trailing Stop
│   │   │   │   │   └────── TP2 Hit (25%)
│   │   │   │   └────────── TP1 Hit (20%)
│   │   │   └────────────── Full Position (3 entries)
│   │   └────────────────── Entry 2 (2nd add)
│   └────────────────────── Entry 1 (initial)
└────────────────────────── Watching
```

### Key Thresholds

| Metric | Default | Purpose |
|--------|---------|---------|
| Stop Loss | -7% | Capital protection |
| Warning | -5% | Early warning |
| P1 Zone | 0-5% | First pyramid |
| P2 Zone | 5-10% | Second pyramid |
| TP1 | 20% | First profit |
| TP2 | 25% | Second profit |
| Trailing | 15%/8% | Activate/Trail |
| Buy Zone | 0-5% | Above pivot |
| Extended | >7% | Don't chase |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Feb 2026 | Initial documentation |

---

## Related Documents

- [BREAKOUT_THREAD.md](BREAKOUT_THREAD.md) - Detailed breakout monitoring
- [README.md](../README.md) - Project overview

---

*CANSLIM Monitor - Systematic Position Management*
