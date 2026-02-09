# Position Thread Documentation

## Overview

The **PositionThread** is a background service that monitors **State 1-6 (active positions)** for stop losses, profit targets, pyramiding opportunities, technical violations, and health conditions. It runs continuously during market hours, checking each active position and generating Discord alerts when action is required.

**Key Characteristics:**
- **Scope:** Only monitors States 1-6 (active positions, not watchlist)
- **Frequency:** Checks every 30 seconds (configurable)
- **Hours:** Market hours only (9:30 AM - 4:00 PM ET)
- **Output:** Discord alerts via webhooks to `position` channel

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         POSITION THREAD CYCLE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Database   │───▶│  Position    │───▶│    IBKR      │                   │
│  │  State 1-6   │    │   Loop       │    │  Get Price   │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│                             │                    │                           │
│                             ▼                    ▼                           │
│                      ┌──────────────┐    ┌──────────────┐                   │
│                      │   Polygon    │    │   Build      │                   │
│                      │  Get MAs     │───▶│   Context    │                   │
│                      └──────────────┘    └──────────────┘                   │
│                                                 │                            │
│                                                 ▼                            │
│         ┌───────────────────────────────────────────────────────────┐       │
│         │              POSITION MONITOR (7 Checkers)                 │       │
│         ├───────────────────────────────────────────────────────────┤       │
│         │                                                            │       │
│         │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │       │
│         │  │    Stop     │  │   Profit    │  │   Pyramid   │        │       │
│         │  │   Checker   │  │   Checker   │  │   Checker   │        │       │
│         │  │    (P0)     │  │    (P1)     │  │    (P1)     │        │       │
│         │  └─────────────┘  └─────────────┘  └─────────────┘        │       │
│         │                                                            │       │
│         │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │       │
│         │  │     MA      │  │   Health    │  │  Re-entry   │        │       │
│         │  │   Checker   │  │   Checker   │  │   Checker   │        │       │
│         │  │  (P0/P1)    │  │  (P0/P2)    │  │  (P1/P2)    │        │       │
│         │  └─────────────┘  └─────────────┘  └─────────────┘        │       │
│         │                                                            │       │
│         │  ┌─────────────┐                                          │       │
│         │  │  Watchlist  │  (State 0 only - Alt entries)            │       │
│         │  │  Alt Entry  │                                          │       │
│         │  └─────────────┘                                          │       │
│         │                                                            │       │
│         └───────────────────────────────────────────────────────────┘       │
│                                                 │                            │
│                                                 ▼                            │
│                      ┌──────────────────────────────────────┐               │
│                      │      AlertService → Discord          │               │
│                      │    (with cooldown & suppression)     │               │
│                      └──────────────────────────────────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Position Context

Each position is evaluated with a rich context object:

```python
@dataclass
class PositionContext:
    # Identity
    symbol: str
    position_id: int
    state: int                    # 1-6

    # Prices
    current_price: float
    entry_price: float            # avg_cost or e1_price
    stop_price: float
    pivot: float
    max_price: float              # Highest price reached

    # P&L
    pnl_pct: float                # Current unrealized P&L
    pnl_dollars: float
    max_gain_pct: float           # Peak gain percentage

    # Technical
    ma_21: float                  # 21-day EMA
    ma_50: float                  # 50-day MA
    ma_200: float                 # 200-day MA
    volume_ratio: float           # Current vs average

    # Position Details
    total_shares: int
    days_in_position: int
    base_stage: int               # 1-4+

    # Profit Taking Status
    tp1_sold: int                 # Shares sold at TP1
    tp2_sold: int                 # Shares sold at TP2

    # Market Context
    market_regime: str            # BULLISH, NEUTRAL, BEARISH

    # Dates
    entry_date: date
    earnings_date: date
```

---

## Checker Classes

### Priority System

| Priority | Color | Meaning | Response Time |
|----------|-------|---------|---------------|
| **P0** | Red | Capital at risk | Act immediately |
| **P1** | Blue | Action recommended | Review and act today |
| **P2** | Gray | Informational | Note for later |

---

## 1. StopChecker (P0 - Capital Protection)

The most critical checker. Protects capital by alerting on stop loss conditions.

### Alerts

| Subtype | Condition | Cooldown | Priority |
|---------|-----------|----------|----------|
| **HARD_STOP** | `price ≤ stop_level` | None | P0 |
| **TRAILING_STOP** | State 4+ AND `price ≤ trailing_stop` | None | P0 |
| **WARNING** | Within 2% of stop | 120 min | P0 |

### Hard Stop Logic

```python
def _check_hard_stop(context, hard_stop):
    if context.current_price <= hard_stop:
        # ALWAYS fire - no cooldown on capital protection
        return HARD_STOP alert
```

**Discord Format:**
```
🛑 HARD STOP HIT: NVDA
─────────────────────────────────────
$142.50 (-8.2%) | Entry $155.25
Stop: $143.00 | Loss: -$1,275
21 EMA: -2.1% | 50 MA: -5.3%
Days in Position: 12
─────────────────────────────────────
⚠️ P0 PRIORITY • EXIT POSITION
```

### Trailing Stop Logic

**Activation Requirements:**
1. Position must be State 4+ (TP1 hit)
2. Maximum gain must have reached 15%+

**Calculation:**
```python
trailing_stop = max_price × (1 - trail_pct / 100)
trailing_stop = max(trailing_stop, entry_price)  # Never below entry

# Example:
# Entry: $100, Max: $125 (25% gain), Trail: 8%
# Trailing Stop = $125 × 0.92 = $115 (locks 15% gain)
```

**Why State 4+ Requirement:**
- States 1-3 are building position (pyramiding)
- Trailing stops during building phase would exit too early
- After TP1 (State 4+), position is profitable and should be protected

**Discord Format:**
```
📉 TRAILING STOP HIT: AAPL
─────────────────────────────────────
$182.50 (+12.3%) | Entry $162.50
Trail Stop: $184.00 | Max: $200.00 (+23.1%)
Gain Locked: +13.2%
21 EMA: +1.5% | 50 MA: +8.2%
─────────────────────────────────────
💰 P0 PRIORITY • SELL TO LOCK PROFITS
```

### Warning Alert

Fires when price approaches stop level:

```python
distance_to_stop = ((price - hard_stop) / price) × 100

if distance_to_stop <= warning_buffer_pct:  # Default: 2%
    return WARNING alert
```

### Configuration

```yaml
position_monitoring:
  stop_loss:
    base_pct: 7.0                # Default stop loss percentage
    warning_buffer_pct: 2.0      # Distance for warning alert
    stage_multipliers:           # Tighter stops for later stages
      1: 1.0                     # Stage 1: 7%
      2: 0.85                    # Stage 2: 5.95%
      3: 0.7                     # Stage 3: 4.9%
      4: 0.6                     # Stage 4: 4.2%
      5: 0.5                     # Stage 5: 3.5%

  trailing_stop:
    activation_pct: 15.0         # Gain needed to activate
    trail_pct: 8.0               # Trail distance from max

  cooldowns:
    hard_stop: 0                 # No cooldown (always fire)
    stop_warning: 120            # 2 hours
    trailing_stop: 0             # No cooldown
```

---

## 2. ProfitChecker (P1 - Profit Taking)

Alerts when profit targets are reached.

### Alerts

| Subtype | Condition | Cooldown | Priority |
|---------|-----------|----------|----------|
| **TP1** | PnL ≥ 20% AND tp1_sold = 0 | 1440 min | P1 |
| **TP2** | PnL ≥ 25% AND tp2_sold = 0 | 1440 min | P1 |
| **EIGHT_WEEK_HOLD** | 20%+ in ≤21 days | 10080 min | P2 |

### TP1 Logic (20% Target)

```python
def _check_tp1(context):
    tp1_target = position.tp1_pct or default_tp1_pct  # 20%

    if context.pnl_pct >= tp1_target and context.tp1_sold == 0:
        # Check 8-week hold rule first
        if _should_suppress_for_eight_week(context):
            return EIGHT_WEEK_HOLD alert
        return TP1 alert
```

**Discord Format:**
```
🎯 TP1 REACHED: META
─────────────────────────────────────
$520.00 (+21.3%) | Entry $428.50
Target: +20% | Shares: 150
Suggested Sell: 50 shares (1/3)
21 EMA: +4.2% | 50 MA: +12.5%
─────────────────────────────────────
💰 TAKE PARTIAL PROFITS
```

### TP2 Logic (25% Target)

```python
def _check_tp2(context):
    tp2_target = position.tp2_pct or default_tp2_pct  # 25%

    if context.pnl_pct >= tp2_target and context.tp2_sold == 0:
        return TP2 alert
```

### 8-Week Hold Rule

IBD's rule for big winners: If a stock gains 20%+ within 3 weeks of breakout, hold for at least 8 weeks.

**Trigger Conditions:**
- Position gains 20%+
- Within 21 calendar days of breakout
- NOT already past the 8-week mark

**Effect:**
- Suppresses TP1 alert
- Generates EIGHT_WEEK_HOLD informational alert
- Encourages holding for potentially larger gains

```python
def _check_eight_week_hold(context):
    days_since_breakout = (today - breakout_date).days

    if context.pnl_pct >= 20.0 and days_since_breakout <= 21:
        # Fast mover - potential big winner
        return EIGHT_WEEK_HOLD alert (suppresses TP1)
```

**Discord Format:**
```
⏳ 8-WEEK HOLD RULE: SMCI
─────────────────────────────────────
$892.00 (+24.5%) | Entry $716.50
Breakout: 12 days ago
Rule: Hold until Week 8 (Apr 15)
─────────────────────────────────────
📈 POTENTIAL BIG WINNER - HOLD
```

### Configuration

```yaml
position_monitoring:
  eight_week_hold:
    gain_threshold_pct: 20.0     # Gain needed
    trigger_window_days: 21      # Must be within 3 weeks
    hold_weeks: 8                # Suggested hold period

  cooldowns:
    tp1: 1440                    # 24 hours
    tp2: 1440                    # 24 hours
    eight_week_hold: 10080       # 7 days

position_management:
  default_tp1_pct: 20.0          # Default TP1 target
  default_tp2_pct: 25.0          # Default TP2 target
```

---

## 3. PyramidChecker (P1 - Position Building)

Alerts for adding to winning positions.

### Alerts

| Subtype | Condition | States | Cooldown | Priority |
|---------|-----------|--------|----------|----------|
| **P1_READY** | 0-5% gain zone | 1 | 240 min | P1 |
| **P1_EXTENDED** | >5% above entry | 1 | 240 min | P2 |
| **P2_READY** | 5-10% gain zone | 2 | 240 min | P1 |
| **P2_EXTENDED** | >10% above entry | 2 | 240 min | P2 |
| **PULLBACK** | Within 1% of 21 EMA | 1-3 | 240 min | P1 |

### Pyramid Zones

```
Entry Price: $100.00
│
├── $100.00 - $105.00  →  P1 Zone (0-5%)
│   └── Alert: P1_READY "Add first pyramid"
│
├── $105.00 - $110.00  →  P2 Zone (5-10%)
│   └── Alert: P2_READY "Add second pyramid"
│
└── > $110.00          →  Extended (>10%)
    └── Alert: EXTENDED "Wait for pullback"
```

### Pre-Conditions

Pyramid alerts only fire if ALL conditions met:
1. Position is profitable (PnL > 0)
2. At least 2 bars (days) since entry
3. Previous pyramid not already completed
4. Not in market correction (optional suppression)

```python
def should_check(context):
    if context.state not in [1, 2, 3]:
        return False  # Only pyramid during building phase
    if context.pnl_pct <= 0:
        return False  # Must be profitable
    if context.days_in_position < min_bars_since_entry:
        return False  # Give position time to work
    return True
```

### P1_READY Logic (State 1 → 2)

```python
def _check_p1(context):
    if context.state != 1:
        return None
    if context.e2_shares > 0:  # Already pyramided
        return None

    gain_pct = context.pnl_pct

    if 0 <= gain_pct <= 5.0:
        return P1_READY alert
    elif gain_pct > 5.0:
        return P1_EXTENDED alert
```

**Discord Format:**
```
🔺 PYRAMID P1 READY: GOOGL
─────────────────────────────────────
$175.50 (+3.2%) | Entry $170.00
Zone: 0-5% above entry ✓
Current Position: 100 shares
Suggested Add: 100 shares (2/3 total)
21 EMA: +1.8% | 50 MA: +5.5%
─────────────────────────────────────
📈 ADD TO WINNING POSITION
```

### Pullback Entry Logic

Alternative add opportunity when price pulls back to moving average:

```python
def _check_pullback(context):
    if context.state not in [1, 2, 3]:
        return None

    # Calculate distance from 21 EMA
    ema_distance = abs((context.current_price - context.ma_21) / context.ma_21) * 100

    if ema_distance <= pullback_ema_tolerance:  # Within 1%
        return PULLBACK alert
```

**Discord Format:**
```
📉 PULLBACK ENTRY: MSFT
─────────────────────────────────────
$415.00 (+6.8%) | Entry $388.50
21 EMA: $413.25 (+0.4% away)
Healthy pullback to support
─────────────────────────────────────
📈 ADD ON DIP TO 21 EMA
```

### Configuration

```yaml
position_monitoring:
  pyramid:
    py1_min_pct: 0.0             # Start of P1 zone
    py1_max_pct: 5.0             # End of P1 zone
    py2_min_pct: 5.0             # Start of P2 zone
    py2_max_pct: 10.0            # End of P2 zone
    min_bars_since_entry: 2      # Days before pyramiding
    pullback_ema_tolerance: 1.0  # Within 1% of EMA

  cooldowns:
    pyramid: 240                 # 4 hours
```

---

## 4. MAChecker (P0/P1 - Technical Violations)

Monitors moving average violations per IBD methodology.

### Alerts

| Subtype | Condition | Cooldown | Priority |
|---------|-----------|----------|----------|
| **MA_50_SELL** | Close < 50 MA AND volume ≥ 1.5x | 1440 min | P0 |
| **MA_50_WARNING** | Within 2% of 50 MA | 1440 min | P1 |
| **EMA_21_SELL** | State 4+ AND 2 closes < 21 EMA | 1440 min | P1 |
| **TEN_WEEK_SELL** | Close < 10-week MA | 10080 min | P0 |
| **CLIMAX_TOP** | Exhaustion signals detected | 60 min | P0/P1 |

### MA 50 Breakdown (IBD Sell Rule)

A close below the 50-day moving average on above-average volume is a classic IBD sell signal.

```python
def _check_ma_50_breakdown(context):
    if context.current_price >= context.ma_50:
        return None  # Still above 50 MA

    # Must have volume confirmation
    if context.volume_ratio < ma_50_volume_confirm:  # 1.5x
        return None  # Volume too light

    return MA_50_SELL alert (P0)
```

**Discord Format:**
```
🔻 50 MA BREAKDOWN: AMD
─────────────────────────────────────
$142.50 (-2.3% below 50 MA)
50 MA: $145.85 | Volume: 1.8x avg
Entry: $135.00 (+5.6%)
─────────────────────────────────────
🛑 P0 PRIORITY • SELL SIGNAL
```

### MA 50 Warning

Early warning before breakdown:

```python
def _check_ma_50_warning(context):
    if context.current_price < context.ma_50:
        return None  # Already below - different alert

    distance = ((context.current_price - context.ma_50) / context.ma_50) * 100

    if distance <= ma_50_warning_pct:  # 2%
        return MA_50_WARNING alert
```

### 21 EMA Sell (For Profitable Positions)

For positions that have taken profits (State 4+), two consecutive closes below 21 EMA is a sell signal.

```python
def _check_ema_21_sell(context):
    if context.state < 4:
        return None  # Only for TP1+ positions

    # Track consecutive closes below 21 EMA
    if context.consecutive_closes_below_21ema >= 2:
        return EMA_21_SELL alert
```

### Climax Top Detection

Detects potential exhaustion/distribution patterns using multiple signals:

**Scoring System:**

| Signal | Points | Description |
|--------|--------|-------------|
| Volume 2.5x+ | 30 | Unusual volume spike |
| Spread 4%+ | 25 | Wide high-low range |
| Gap up 2%+ | 25 | Gap up at open |
| Reversal | 20 | Close in lower 30% of range |

```python
def _check_climax_top(context):
    if context.pnl_pct < climax_min_gain:  # 15%
        return None  # Only for winners

    score = 0

    if context.volume_ratio >= 2.5:
        score += 30
    if context.spread_pct >= 4.0:
        score += 25
    if context.gap_pct >= 2.0:
        score += 25
    if context.close_position <= 0.3:  # Lower 30%
        score += 20

    if score >= 75:
        return CLIMAX_TOP alert (P0)
    elif score >= 50:
        return CLIMAX_TOP alert (P1)
```

**Discord Format:**
```
🔥 CLIMAX TOP DETECTED: NVDA
─────────────────────────────────────
$525.00 (+45.2%) | Entry $361.50
Volume: 3.2x avg | Spread: 5.8%
Gap Up: +2.5% | Reversal Close
Score: 85 (STRONG SIGNAL)
─────────────────────────────────────
⚠️ P0 PRIORITY • EXHAUSTION PATTERN
```

### Configuration

```yaml
position_monitoring:
  technical:
    ma_50_warning_pct: 2.0           # Distance for warning
    ma_50_volume_confirm: 1.5        # Volume for breakdown
    ema_21_consecutive_days: 2       # Closes needed

  cooldowns:
    ma_50_warning: 1440              # 24 hours
    ma_50_sell: 1440                 # 24 hours
    ema_21_sell: 1440                # 24 hours
    ten_week_sell: 10080             # 7 days
```

---

## 5. HealthChecker (P0/P2 - Position Quality)

Monitors overall position health and special situations.

### Alerts

| Subtype | Condition | Cooldown | Priority |
|---------|-----------|----------|----------|
| **CRITICAL** | Health score < 50 | 60 min | P0 |
| **EARNINGS** | Earnings within 14 days | 1440 min | P0/P1 |
| **LATE_STAGE** | Base stage ≥ 4 | 10080 min | P2 |
| **EXTENDED** | >5% above pivot | 60 min | P1/P2 |

### Health Score Calculation

Composite score from multiple factors:

```python
def calculate_health_score(context):
    score = 100

    # Time in position vs progress
    expected_progress = context.days_in_position / time_threshold_days
    actual_progress = context.pnl_pct / tp1_target
    if actual_progress < expected_progress * 0.5:
        score -= 20  # Lagging

    # Distance from stop
    stop_distance = ((context.current_price - context.stop_price) / context.current_price)
    if stop_distance < 0.03:  # Within 3% of stop
        score -= 25

    # RS rating trend
    if context.rs_rating < 70:
        score -= 15

    # Volume characteristics
    if context.ud_vol_ratio < ud_ratio_warning:
        score -= 10

    return max(0, min(100, score))
```

**Interpretation:**
- 80-100: Healthy position
- 60-80: Monitor closely
- 50-60: Concern, review needed
- <50: Critical, take action

### Earnings Alert

Provides P&L-based guidance for earnings:

```python
def _check_earnings(context):
    if not context.earnings_date:
        return None

    days_to_earnings = (context.earnings_date - today).days

    if days_to_earnings > earnings_warning_days:  # 14
        return None

    # Determine priority based on proximity
    priority = "P0" if days_to_earnings <= earnings_critical_days else "P1"

    # Determine action based on P&L
    if context.pnl_pct >= reduce_threshold:  # 10%+
        action = "HOLD WITH TRAILING STOP"
    elif context.pnl_pct >= negative_threshold:  # 0%+
        action = "SELL BEFORE EARNINGS"
    else:
        action = "EXIT BEFORE EARNINGS"

    return EARNINGS alert with action
```

**Discord Format:**
```
📅 EARNINGS APPROACHING: CRM
─────────────────────────────────────
Earnings: Feb 28 (5 days)
Current P&L: +12.5%
─────────────────────────────────────
💡 RECOMMENDATION: HOLD WITH TRAILING STOP
   (Up > 10%, protected by trailing)
```

### Late Stage Warning

Alerts on later-stage bases (4th stage or higher) which have lower success rates:

```python
def _check_late_stage(context):
    if context.base_stage >= 4:
        return LATE_STAGE alert (P2)
```

### Configuration

```yaml
position_monitoring:
  health:
    time_threshold_days: 60          # Days before time warning
    tp1_progress_threshold: 0.5      # Expected progress ratio
    deep_base_threshold: 35.0        # Deep base warning %
    ud_ratio_warning: 0.8            # Up/Down volume warning

  earnings:
    warning_days: 14                 # Days before earnings warning
    critical_days: 5                 # P0 alert threshold
    negative_threshold: 0.0          # Breakeven threshold
    reduce_threshold: 10.0           # Safe to hold threshold

  cooldowns:
    health_warning: 60               # 1 hour
    health_critical: 60              # 1 hour
    earnings: 1440                   # 24 hours
    late_stage: 10080                # 7 days
```

---

## 6. ReentryChecker (P1/P2 - Add Opportunities)

Finds add opportunities for positions not yet at full size.

### Alerts

| Subtype | Condition | States | Cooldown | Priority |
|---------|-----------|--------|----------|----------|
| **EMA_21** | Within 1% of 21 EMA, up 5%+ | 1-2 | 60 min | P2 |
| **PULLBACK** | Within 1.5% of 50 MA, up 8%+ | 1-2 | 60 min | P1 |
| **IN_BUY_ZONE** | Near pivot, was up 5%+ | 1-2 | 60 min | P2 |

### Logic

```python
def check(context):
    if context.state > 2:
        return None  # Already full position
    if context.pnl_pct <= 0:
        return None  # Must be profitable

    # Check 21 EMA bounce
    ema_distance = abs((price - ma_21) / ma_21) * 100
    if ema_distance <= 1.0 and context.pnl_pct >= 5.0:
        return EMA_21 alert

    # Check 50 MA bounce
    ma_distance = abs((price - ma_50) / ma_50) * 100
    if ma_distance <= 1.5 and context.pnl_pct >= 8.0:
        return PULLBACK alert
```

---

## 7. WatchlistAltEntryChecker (State 0 - Pullback Entries)

Monitors State 0 (watchlist) for alternative entry opportunities after extension.

### Alerts

| Subtype | Condition | Cooldown | Priority |
|---------|-----------|----------|----------|
| **MA_BOUNCE** | 21 EMA bounce after 5%+ extension | 4 hours | P1 |
| **MA_BOUNCE** | 50 MA bounce after 5%+ extension | 4 hours | P1 |
| **PIVOT_RETEST** | Back in buy zone after extension | 4 hours | P1 |

### Logic

The idea: If you missed the initial breakout and the stock extended beyond the buy zone, wait for it to pull back to support.

```python
def check(context):
    if context.state != 0:
        return None  # Watchlist only

    # Stock must have been extended first
    if context.max_extension_pct < 5.0:
        return None  # Never extended enough

    # Check if now pulled back to support
    if _near_21_ema(context):
        return MA_BOUNCE alert
    if _near_50_ma(context):
        return MA_BOUNCE alert
    if _in_buy_zone(context):
        return PIVOT_RETEST alert
```

**Discord Format:**
```
📉 MA BOUNCE ENTRY: COST
─────────────────────────────────────
$892.00 (+1.2% from pivot)
Was Extended: +7.5% from pivot
Now: Bounced off 21 EMA ($885.50)
─────────────────────────────────────
📈 ALTERNATIVE ENTRY OPPORTUNITY
```

### Configuration

```yaml
alerts:
  alt_entry:
    min_extension_pct: 5.0           # Must extend 5%+ first
    ema_21_bounce_pct: 1.5           # Within 1.5% of EMA
    ma_50_bounce_pct: 2.0            # Within 2% of MA
    bounce_volume_min: 0.7           # Volume can be lighter
    pivot_retest_pct: 3.0            # Within 3% of pivot
    cooldown_hours: 4
```

---

## Market Regime Suppression

During market corrections, certain alerts are suppressed to prevent false signals:

### Suppressed Alerts

| Alert | Normal Behavior | In Correction |
|-------|-----------------|---------------|
| PYRAMID/P1_READY | Fire normally | Suppressed |
| PYRAMID/P2_READY | Fire normally | Suppressed |
| PYRAMID/PULLBACK | Fire normally | Suppressed |

### Logic

```python
def create_alert(context, alert_type, subtype, ...):
    if should_suppress(context.market_regime, alert_type, subtype):
        # Convert to suppressed version
        subtype = AlertSubtype.SUPPRESSED
        priority = "P2"  # Demote priority
```

### Configuration

```yaml
alerts:
  enable_suppression: true
```

---

## Discord Channel Routing

All Position Thread alerts go to the `position` channel:

```yaml
discord:
  webhooks:
    position: "https://discord.com/api/webhooks/..."
```

---

## YAML Configuration Reference

### Complete Position Monitoring Config

```yaml
position_monitoring:
  # Stop Loss
  stop_loss:
    base_pct: 7.0
    warning_buffer_pct: 2.0
    stage_multipliers:
      1: 1.0
      2: 0.85
      3: 0.7
      4: 0.6
      5: 0.5

  # Trailing Stop
  trailing_stop:
    activation_pct: 15.0
    trail_pct: 8.0

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
```

---

## Troubleshooting

### Stop Alerts Not Firing

1. **Is position State 1-6?** Only active positions monitored
2. **Is IBKR connected?** Check service status
3. **Is it market hours?** Thread runs 9:30 AM - 4:00 PM ET
4. **Check stop level:** Is stop_price set correctly?

### Trailing Stop Not Triggering

1. **Is position State 4+?** Must have taken TP1
2. **Did max gain reach 15%?** Activation threshold
3. **Is price 8%+ below max?** Trail distance

### Profit Alerts Not Firing

1. **Check cooldown:** TP alerts have 24-hour cooldown
2. **Check tp1_sold/tp2_sold:** Already marked as sold?
3. **Check actual P&L:** May be slightly below target

### Pyramid Alerts Not Firing

1. **Check state:** Must be 1-3
2. **Check profitability:** Must be profitable
3. **Check days_in_position:** Must be ≥2 days
4. **Check cooldown:** 4-hour cooldown between alerts

---

## CLI Commands

### Service Control

**Start the service (includes PositionThread):**
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

### Test Position Scenarios

The `test_position` command allows testing all position monitor checkers:

```bash
# Run all test scenarios (stop, profit, pyramid, ma, health)
python -m canslim_monitor test_position

# Test specific scenario
python -m canslim_monitor test_position -s stop      # Stop loss scenarios
python -m canslim_monitor test_position -s profit    # Profit target scenarios
python -m canslim_monitor test_position -s pyramid   # Pyramid add scenarios
python -m canslim_monitor test_position -s ma        # Moving average scenarios
python -m canslim_monitor test_position -s health    # Health check scenarios

# Interactive mode for manual testing
python -m canslim_monitor test_position -i

# Test level calculator only
python -m canslim_monitor test_position -l
```

### Test with Live Data

```bash
# Validate against real positions in database
python -m canslim_monitor test_position --live

# Use live IBKR prices (requires TWS/Gateway)
python -m canslim_monitor test_position --live --ibkr

# Test specific symbol
python -m canslim_monitor test_position --live --symbol AAPL

# Test and send real Discord alerts
python -m canslim_monitor test_position --live --discord

# Verbose output
python -m canslim_monitor test_position --live -v
```

### Force Position Check

Trigger an immediate position check cycle via IPC:

```bash
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()

# Force check all positions
result = client.send_command({'type': 'FORCE_CHECK'})
print(result)

# Force check specific symbol
result = client.send_command({
    'type': 'FORCE_CHECK',
    'data': {'symbol': 'NVDA'}
})
print(result)
"
```

### Check Thread Status

```bash
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'GET_THREAD_STATUS', 'thread': 'position'})
print(f'State: {result[\"state\"]}')
print(f'Alerts sent: {result[\"message_count\"]}')
print(f'Errors: {result[\"error_count\"]}')
print(f'Last check: {result[\"last_check\"]}')
print(f'Avg cycle time: {result[\"avg_cycle_ms\"]:.0f}ms')
"
```

### Update Earnings Dates

```bash
# Update earnings for all active positions
python -m canslim_monitor earnings

# Check upcoming earnings (read-only)
python -m canslim_monitor earnings --check

# Check next 30 days
python -m canslim_monitor earnings --check --days 30

# Update single symbol
python -m canslim_monitor earnings --symbol NVDA

# Force update even if date exists
python -m canslim_monitor earnings --force
```

### IPC Commands Reference

| Command | Description |
|---------|-------------|
| `GET_STATUS` | Get full service status including position thread |
| `GET_THREAD_STATUS` | Get specific thread status (`thread: 'position'`) |
| `FORCE_CHECK` | Trigger immediate position check cycle |
| `RELOAD_CONFIG` | Reload configuration from YAML |
| `RESET_COUNTERS` | Reset message/error counters |

### Test Scenario Examples

**Stop Loss Scenarios:**
```bash
python -m canslim_monitor test_position -s stop -v
```
Tests:
- Hard stop hit (price at/below stop)
- Stop warning (within 2% of stop)
- Trailing stop (State 4+, 15%+ gain, 8% trail)

**Profit Target Scenarios:**
```bash
python -m canslim_monitor test_position -s profit -v
```
Tests:
- TP1 hit (20% gain)
- TP2 hit (25% gain)
- 8-week hold rule (20% in 21 days)

**Pyramid Scenarios:**
```bash
python -m canslim_monitor test_position -s pyramid -v
```
Tests:
- P1 ready (0-5% zone)
- P2 ready (5-10% zone)
- Extended warnings
- Pullback to 21 EMA

**MA Breakdown Scenarios:**
```bash
python -m canslim_monitor test_position -s ma -v
```
Tests:
- 50 MA breakdown with volume
- 50 MA warning (within 2%)
- 21 EMA consecutive closes
- Climax top detection

### Monitor Position Thread

```bash
# Watch position thread status in real-time
watch -n 30 'python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({\"type\": \"GET_THREAD_STATUS\", \"thread\": \"position\"})
print(f\"State: {result.get(\"state\", \"unknown\")}  Alerts: {result.get(\"message_count\", 0)}  Errors: {result.get(\"error_count\", 0)}\")
"'
```

---

## Related Files

| File | Purpose |
|------|---------|
| `service/threads/position_thread.py` | Main position monitoring logic |
| `core/position_monitor/monitor.py` | PositionMonitor coordinator |
| `core/position_monitor/checkers/*.py` | Individual checker implementations |
| `services/alert_service.py` | Alert routing and persistence |
| `services/technical_data_service.py` | MA data from Polygon |
| `utils/level_calculator.py` | Stop and target calculations |
| `utils/discord_formatters.py` | Discord message formatting |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Feb 2026 | Initial documentation |
| 1.1 | Feb 2026 | Added trailing stop state guard (State 4+) |
