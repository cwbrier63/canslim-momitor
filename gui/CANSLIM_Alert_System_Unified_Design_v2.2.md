# CANSLIM Alert System: Unified Design & Implementation Plan
## TrendSpider Migration, IBD Alignment, and Production Deployment

**Version:** 2.2  
**Created:** January 14, 2026  
**Updated:** January 16, 2026  
**Status:** Phase 2 In Progress - Breakout Alerts Operational  
**IBD Methodology Coverage:** ~90% (with gaps identified)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Alert Type Catalog](#2-alert-type-catalog)
3. [Thread Architecture](#3-thread-architecture)
4. [Discord Integration](#4-discord-integration)
5. [Database Schema](#5-database-schema)
6. [Position State Machine](#6-position-state-machine)
7. [Position Sizing Rules](#7-position-sizing-rules)
8. [Alternative Entry System](#8-alternative-entry-system)
9. [IBD Methodology Gaps](#9-ibd-methodology-gaps)
10. [GUI Components](#10-gui-components)
11. [Implementation Sequence](#11-implementation-sequence)
12. [Validation Plan](#12-validation-plan)
13. [Configuration Reference](#13-configuration-reference)

---

## 1. Executive Summary

### 1.1 Goal

Build a comprehensive Python alert system that:
- Runs **in parallel** with existing TrendSpider alerts for validation
- Achieves **95%+ parity** with TrendSpider V3.6 signals
- Fills **IBD methodology gaps** identified in webinar analysis
- Provides **production-ready** position management and market regime integration

### 1.2 Success Criteria

| Metric | Target |
|--------|--------|
| TrendSpider Parity | 95%+ match rate over 2-week validation |
| Alert Latency | Python fires within 5 seconds of TrendSpider |
| IBD Alignment | Address all P0 gaps before production |
| False Positive Rate | < 2% |
| False Negative Rate | < 3% |

### 1.3 IBD Methodology Coverage

| Category | Coverage | Status |
|----------|----------|--------|
| Entry Signals (Breakout, Volume) | 95% | ✅ **IMPLEMENTED** |
| Pyramid Rules | 90% | ✅ Designed |
| Profit Taking (TP1/TP2) | 80% | ⚠️ TP2 needs adjustment |
| Stop Loss Rules | 95% | ✅ Designed |
| Moving Average Sells | 70% | ⚠️ Missing 10-week, volume confirmation |
| 8-Week Hold Rule | 0% | ❌ Not implemented |
| Market Regime Integration | 60% | ⚠️ Alerts exist, entries not blocked |
| Alternative Entries | 85% | ✅ Designed |

### 1.4 Document Consolidation Note

This document merges:
- `Alert_System_Integration_Design.md` - Core system design
- `IBD_Gap_Analysis_Working_Document.md` - Methodology gaps

All gaps are now integrated into relevant sections with implementation details.

---

## 2. Alert Type Catalog

### 2.1 Complete Alert Matrix (35 Types)

| # | Alert Type | Subtype | Thread | States | Priority | Status |
|---|------------|---------|--------|--------|----------|--------|
| **Breakout Alerts** |
| 1 | BREAKOUT | CONFIRMED | Realtime | 0 | P0 | ✅ **IMPLEMENTED** |
| 2 | BREAKOUT | SUPPRESSED | Realtime | 0 | P0 | ✅ **IMPLEMENTED** |
| 3 | BREAKOUT | IN_BUY_ZONE | Realtime | 0 | P1 | ✅ **IMPLEMENTED** |
| 4 | BREAKOUT | APPROACHING | Realtime | 0 | P1 | ✅ **IMPLEMENTED** |
| 5 | BREAKOUT | EXTENDED | Realtime | 0 | P1 | ✅ **IMPLEMENTED** |
| **Pyramid Alerts** |
| 6 | PYRAMID | P1_READY | Daily | 1 | P0 | ✅ Designed |
| 7 | PYRAMID | P1_EXTENDED | Daily | 1 | P1 | ✅ Designed |
| 8 | PYRAMID | P2_READY | Daily | 2 | P0 | ✅ Designed |
| 9 | PYRAMID | P2_EXTENDED | Daily | 2 | P1 | ✅ Designed |
| **Add Signals** |
| 10 | ADD | PULLBACK | Daily | 1+ | P1 | ✅ Designed |
| 11 | ADD | 21_EMA | Daily | 1+ | P1 | ✅ Designed |
| **Profit Alerts** |
| 12 | PROFIT | TP1 | Daily | 1-3 | P0 | ✅ Designed |
| 13 | PROFIT | TP2 | Daily | 4 | P0 | ⚠️ Needs % adjustment |
| 14 | PROFIT | 8_WEEK_HOLD | Daily | 1+ | P0 | ❌ **NEW - GAP** |
| **Stop Alerts** |
| 15 | STOP | HARD_STOP | 30-min | 1-6 | P0 | ✅ Designed |
| 16 | STOP | WARNING | 2-hour | 1-6 | P1 | ✅ Designed |
| **Technical Sells** |
| 17 | TECHNICAL | 50_MA_WARNING | Daily | 1-6 | P1 | ✅ Designed |
| 18 | TECHNICAL | 50_MA_SELL | Daily | 1-6 | P0 | ⚠️ Missing volume confirm |
| 19 | TECHNICAL | 21_EMA_SELL | Daily | 4-6 | P0 | ✅ Designed |
| 20 | TECHNICAL | 10_WEEK_SELL | Weekly | 4-6 | P0 | ❌ **NEW - GAP** |
| 21 | TECHNICAL | CLIMAX_TOP | Daily | 4-6 | P1 | ❌ **NEW - GAP** |
| **Health/Risk Alerts** |
| 22 | HEALTH | WARNING | Daily | 1+ | P1 | ✅ Designed |
| 23 | HEALTH | CRITICAL | Daily | 1+ | P0 | ✅ Designed |
| 24 | HEALTH | EARNINGS | Daily | 1+ | P1 | ✅ Designed |
| 25 | HEALTH | LATE_STAGE | Daily | 1+ | P2 | ✅ Designed |
| **Market Alerts** |
| 26 | MARKET | WEAK | Daily | All | P0 | ⚠️ Needs entry blocking |
| 27 | MARKET | FTD | Daily | All | P0 | ✅ Designed |
| 28 | MARKET | RALLY_ATTEMPT | Daily | All | P1 | ✅ Designed |
| 29 | MARKET | CORRECTION | Daily | All | P0 | ⚠️ **NEW - GAP** |
| **Alternative Entry Alerts** |
| 30 | ALT_ENTRY | MA_BOUNCE | Daily | -1.5, 0 | P1 | ✅ Designed |
| 31 | ALT_ENTRY | PIVOT_RETEST | Daily | -1.5 | P1 | ✅ Designed |
| 32 | ALT_ENTRY | CONFLUENCE | Daily | -1.5, 0 | P1 | ✅ Designed |
| 33 | ALT_ENTRY | SHAKEOUT_3 | Daily | 0 | P1 | ✅ Designed |
| 34 | ALT_ENTRY | THREE_WEEKS_TIGHT | Weekly | 1+ | P2 | ✅ Designed |
| 35 | ALT_ENTRY | NEW_BASE | Weekly | -1.5 | P1 | ✅ Designed |

### 2.2 Thread Responsibility Matrix

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ALERT THREAD OWNERSHIP                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  BREAKOUT THREAD (60 second poll during market hours) **IMPLEMENTED**       │
│  ────────────────────────────────────────────────────                       │
│  Purpose: Real-time pivot detection for watchlist                           │
│  Scope: State 0 (watchlist) positions with valid pivots                     │
│  Alerts: BREAKOUT (all subtypes)                                            │
│  Features:                                                                   │
│    - RVOL (time-adjusted volume ratio) **ADD: Not in original design**     │
│    - Pivot status tracking (BELOW/APPROACHING/IN_BUY_ZONE/EXTENDED)        │
│    - Market regime suppression                                              │
│    - Scoring engine integration                                             │
│    - Position sizing integration                                            │
│                                                                              │
│  POSITION THREAD (30 second poll during market hours) **RUNNING**           │
│  ─────────────────────────────────────────────────────                      │
│  Purpose: Monitor active positions for pyramids, profits, exits             │
│  Scope: States 1-6 (active positions)                                       │
│  Alerts: PYRAMID, ADD, PROFIT, STOP_WARNING, TECHNICAL, HEALTH             │
│  Status: Thread running, alert logic pending                                │
│                                                                              │
│  MARKET THREAD (300 second poll) **RUNNING**                                │
│  ────────────────────────────────                                           │
│  Purpose: Market regime analysis and distribution day tracking              │
│  Scope: Market indices (SPY, QQQ, DIA)                                      │
│  Alerts: MARKET (all subtypes)                                              │
│  Status: Thread running, morning regime alerts working                      │
│                                                                              │
│  30-MINUTE THREAD (poll at :00, :30 during market hours) **PLANNED**       │
│  ───────────────────────────────────────────────────────                    │
│  Purpose: Capital protection - "Speed matters"                              │
│  Scope: States 1-6 (active positions)                                       │
│  Alerts: HARD_STOP                                                          │
│                                                                              │
│  2-HOUR THREAD (poll at 11:30, 1:30, 3:30) **PLANNED**                     │
│  ─────────────────────────────────────────────                              │
│  Purpose: Early warning                                                     │
│  Scope: States 1-6                                                          │
│  Alerts: STOP_WARNING                                                       │
│                                                                              │
│  DAILY THREAD (runs at 4:05 PM ET) **PLANNED**                             │
│  ─────────────────────────────────                                          │
│  Purpose: Confirmed close + volume verification                             │
│  Scope: All states                                                          │
│  Alerts: End-of-day confirmations                                           │
│                                                                              │
│  WEEKLY THREAD (runs Friday at 4:10 PM ET) **PLANNED**                     │
│  ──────────────────────────────────────────                                 │
│  Purpose: IBD weekly chart signals                                          │
│  Scope: States 1+ and -1.5                                                  │
│  Alerts: 10_WEEK_SELL, THREE_WEEKS_TIGHT, NEW_BASE                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Thread Architecture

### 3.1 Current Implementation Status **ADD: Implementation Details**

| Thread | File | Status | Poll Interval | Notes |
|--------|------|--------|---------------|-------|
| Breakout | `breakout_thread.py` (734 lines) | ✅ **OPERATIONAL** | 60s | Full alert generation |
| Position | `position_thread.py` | ✅ Running | 30s | Alert logic pending |
| Market | `market_thread.py` | ✅ Running | 300s | Morning alerts working |
| Hard Stop | N/A | ❌ Planned | 15-30m | Separate thread needed |
| Stop Warning | N/A | ❌ Planned | 2h | Separate thread needed |
| Daily | N/A | ❌ Planned | 4:05 PM | APScheduler |
| Weekly | N/A | ❌ Planned | Fri 4:10 PM | APScheduler |

### 3.2 Windows Service Architecture **ADD: Production Implementation**

The alert system runs as a Windows Service with the following architecture:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      WINDOWS SERVICE ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  service_main.py                                                            │
│  ├── CANSLIMMonitorService (Windows Service wrapper)                        │
│  │   ├── SvcDoRun() - Service entry point                                  │
│  │   └── SvcStop() - Graceful shutdown                                     │
│  │                                                                          │
│  └── service_controller.py                                                  │
│      ├── _ensure_event_loop() **ADD: Critical for ib_insync**              │
│      ├── _init_database() - SQLite connection                              │
│      ├── _init_ibkr() - IBKR TWS/Gateway connection                        │
│      ├── _init_discord() - Webhook initialization                          │
│      ├── _init_scoring_engine() - Setup grading                            │
│      ├── _init_position_sizer() - Share calculations                       │
│      ├── _init_alert_service() - Routing & persistence                     │
│      └── _create_threads()                                                  │
│          ├── BreakoutThread (poll: 60s, client_id: base+0)                 │
│          ├── PositionThread (poll: 30s, client_id: base+1)                 │
│          └── MarketThread (poll: 300s, client_id: base+2)                  │
│                                                                              │
│  IPC Server (Named Pipes)                                                   │
│  ├── Pipe: \\.\pipe\CANSLIMMonitor                                         │
│  └── Commands: GET_STATUS, RELOAD_CONFIG, FORCE_CHECK, SHUTDOWN            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Client ID Allocation **ADD: IBKR Connection Management**

| Component | Client ID | Notes |
|-----------|-----------|-------|
| GUI | base + 5 (25) | Interactive price display |
| Service - Breakout | base + 0 (20) | Primary monitoring |
| Service - Position | base + 1 (21) | Position monitoring |
| Service - Market | base + 2 (22) | Market regime |
| Service - Reserved | base + 3,4 (23,24) | Future threads |

### 3.4 Event Loop Handling **ADD: Critical Implementation Detail**

```python
# CRITICAL: Windows Services run without event loops
# ib_insync requires an event loop before import

def _ensure_event_loop():
    """Ensure asyncio event loop exists for current thread."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop
```

### 3.5 Alert Resolution Matrix (IBD-Aligned)

| Alert Type | IBD Guidance | TrendSpider | Python Implementation | Notes |
|------------|--------------|-------------|----------------------|-------|
| BREAKOUT | Intraday + Close | Daily | **Realtime 60s poll** | Catches intraday breakouts |
| HARD STOP | "Speed matters" | 30m-1h | **15 min** (planned) | Configurable 5m-1h |
| STOP WARNING | N/A | 2h | **2 hour** (planned) | Early warning |
| PYRAMID | N/A | Daily | **Daily** | Deliberate adds |
| TP1/TP2 | N/A | Daily | **Daily** | Profit confirmation |
| 50 MA SELL | Daily close + volume | Daily | **Daily** | **GAP: Add volume check** |
| 21 EMA SELL | Two daily closes | Daily | **Daily** | Count consecutive |
| **10 WEEK SELL** | **Weekly close** | ❌ Missing | **Weekly Fri 4:10** | **GAP: IBD primary guide** |
| **3 WEEKS TIGHT** | Weekly pattern | ❌ Missing | **Weekly** | **GAP: Add detection** |
| DISTRIBUTION DAY | Daily close | ❌ Missing | **Daily** | Market health |
| FTD | Daily close | ❌ Missing | **Daily** | Uptrend confirmation |

---

## 4. Discord Integration

### 4.1 Channel Structure

| Channel | Webhook Config Key | Alert Types | Color |
|---------|-------------------|-------------|-------|
| #canslim-breakouts | `discord.webhooks.breakout` | Breakout, Extended | 🟢 Green |
| #canslim-positions | `discord.webhooks.position` | Pyramid, Add, Profit | 🟡 Gold |
| #canslim-exits | `discord.webhooks.exits` | Stop, MA Sell, EMA Sell | 🔴 Red |
| #canslim-warnings | `discord.webhooks.warnings` | Health, Earnings, Stage | 🟠 Orange |
| #canslim-market | `discord.webhooks.market` | Market regime alerts | 🔵 Blue |
| #canslim-validation | `discord.webhooks.validation` | ALL (for Python vs TS) | ⚪ Gray |
| #canslim-system | `discord.webhooks.system` | Service status, errors | ⚪ Gray |

### 4.2 Color Scheme (Matching TrendSpider)

| Alert Category | Color Name | Hex | Decimal |
|----------------|------------|-----|---------|
| BREAKOUT | Green | #2ECC71 | 3066993 |
| PYRAMID | Blue | #3498DB | 3447003 |
| TAKE PROFIT | Gold | #F1C40F | 15844367 |
| WARNING | Orange | #E67E22 | 15105570 |
| STOP/MA EXIT | Red | #E74C3C | 15158332 |
| 21 EMA SELL | Purple | #9B59B6 | 10181046 |
| MARKET | Royal Blue | #4169E1 | 4286945 |

### 4.3 Emoji Mapping

```python
EMOJIS = {
    "BREAKOUT_CONFIRMED": "🚀",
    "BREAKOUT_SUPPRESSED": "⚠️",
    "BREAKOUT_EXTENDED": "⏸️",
    "BREAKOUT_IN_BUY_ZONE": "✅",      # ADD: Implementation detail
    "BREAKOUT_APPROACHING": "👀",
    "PYRAMID_READY": "📈",
    "TP1_TRIGGERED": "💰",
    "TP2_TRIGGERED": "💎",
    "8_WEEK_HOLD": "⏳",
    "HARD_STOP_HIT": "🛑",
    "MA_WARNING": "⚡",
    "MA_SELL": "🔻",
    "10_WEEK_SELL": "📉",
    "CLIMAX_TOP": "🎢",
    "HEALTH_WARNING": "⚠️",
    "HEALTH_CRITICAL": "🚨",
    "MARKET_WEAK": "📉",
    "MARKET_CORRECTION": "🛑",
    "FTD_DETECTED": "🎯",
}
```

### 4.4 Breakout Alert Format **ADD: Actual Implementation**

The implemented breakout alert includes:

```
🚀 **NVDA - BREAKOUT CONFIRMED**

NVDA broke out above $145.50 pivot with 2.3x average volume

Price: $147.25 (+1.2% from pivot)
Pivot: $145.50 | Buy Zone: $145.50 - $152.78

**Setup Analysis**
Pattern: Cup w/Handle | Stage: 1 | Depth: 18%
RS Rating: 94 | Grade: A (Score: 18/24)

**Position Sizing**
▶ ACTION: Buy 50 shares (50% initial position)
Target Full Position: 100 shares
Stop Loss: $135.50 (-7.2%)

**Pivot Status**
Days at pivot: 3 | Status: FRESH    **ADD: Pivot staleness tracking**

Market: CONFIRMED UPTREND
Time: 10:32:15 ET
```

### 4.5 RVOL Calculation **ADD: Time-Adjusted Volume Ratio**

The breakout thread implements time-adjusted volume ratio (RVOL) instead of simple volume comparison:

```python
def _calculate_rvol(self, current_volume: int, avg_daily_volume: int) -> float:
    """
    Calculate Relative Volume (RVOL) - time-adjusted volume ratio.
    
    Compares current intraday volume to expected volume at this time of day,
    based on the assumption that volume accumulates proportionally throughout
    the trading session.
    
    Returns:
        RVOL ratio (1.0 = normal, >1.0 = above average, <1.0 = below average)
    """
    # Get elapsed minutes since market open
    elapsed_minutes = (now_et - market_open).total_seconds() / 60
    day_fraction = min(elapsed_minutes / 390, 1.0)  # 390 min trading day
    
    # Expected volume at this time
    expected_volume = avg_daily_volume * day_fraction
    
    return current_volume / expected_volume if expected_volume > 0 else 0
```

This allows accurate volume assessment throughout the trading day, not just at close.

---

## 5. Database Schema

### 5.1 Alerts Table

```sql
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Identity
    symbol TEXT NOT NULL,
    position_id INTEGER,
    
    -- Classification
    alert_type TEXT NOT NULL,
    alert_subtype TEXT,              -- ADD: Renamed from 'subtype'
    
    -- Context at alert time
    price REAL NOT NULL,
    volume REAL,
    volume_ratio REAL,
    
    -- Scoring (breakout alerts)
    canslim_grade TEXT,              -- ADD: Grade (A, B, C, D)
    canslim_score INTEGER,           -- ADD: Numeric score
    static_score INTEGER,            -- ADD: Pattern/stage/depth score
    dynamic_score INTEGER,           -- ADD: Volume/technical score
    
    -- Technical context
    ma50 REAL,                       -- ADD: 50-day MA at alert
    ma21 REAL,                       -- ADD: 21-day EMA at alert
    pivot_at_alert REAL,             -- ADD: Pivot price
    avg_cost_at_alert REAL,          -- ADD: Position avg cost
    pnl_pct_at_alert REAL,           -- ADD: P/L % at alert
    
    -- Health context
    health_score INTEGER,            -- ADD: Position health
    health_rating TEXT,              -- ADD: HEALTHY/WARNING/CRITICAL
    
    -- Market context
    market_regime TEXT,
    spy_price REAL,                  -- ADD: SPY price at alert
    state_at_alert INTEGER,          -- ADD: Position state
    
    -- Message
    message TEXT,
    
    -- Metadata
    thread_source TEXT,
    discord_sent INTEGER DEFAULT 0,
    discord_channel TEXT,
    
    -- Timestamps
    alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- ADD: Renamed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE INDEX idx_alerts_symbol ON alerts(symbol);
CREATE INDEX idx_alerts_type ON alerts(alert_type, alert_subtype);
CREATE INDEX idx_alerts_created ON alerts(alert_time);
CREATE INDEX idx_alerts_position ON alerts(position_id);
```

### 5.2 Position Table - Pivot Status Additions **ADD: New Fields**

```sql
-- Pivot status tracking for breakout thread
ALTER TABLE positions ADD COLUMN pivot_distance_pct REAL;     -- Distance from pivot (%)
ALTER TABLE positions ADD COLUMN pivot_status TEXT;           -- BELOW/APPROACHING/IN_BUY_ZONE/EXTENDED
ALTER TABLE positions ADD COLUMN pivot_set_date DATE;         -- When pivot was set
ALTER TABLE positions ADD COLUMN avg_volume_50d INTEGER;      -- 50-day avg volume (from Polygon)
```

---

## 6. Position State Machine

(No changes from v2.1 - see original document)

---

## 7. Position Sizing Rules

### 7.1 Implementation Status **ADD: Current State**

| Component | File | Status |
|-----------|------|--------|
| PositionSizer class | `utils/position_sizer.py` | ✅ **IMPLEMENTED** |
| Sizing in breakout alerts | `breakout_thread.py` | ✅ **IMPLEMENTED** |
| Database columns | `data/models.py` | ⚠️ Partial |
| GUI display | `gui/kanban_window.py` | ❌ Pending |

### 7.2 IBD Position Building Strategy

(No changes from v2.1 - see original document)

---

## 8. Alternative Entry System

(No changes from v2.1 - see original document)

---

## 9. IBD Methodology Gaps

(No changes from v2.1 - see original document)

---

## 10. GUI Components

(No changes from v2.1 - see original document)

---

## 11. Implementation Sequence

### Phase 1: Foundation ✅ **COMPLETE**

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 1.1 | Discord Notifier class | 4h | ✅ **COMPLETE** (907 lines) |
| 1.2 | Alert Repository + schema | 4h | ✅ **COMPLETE** |
| 1.3 | Alert Service layer | 4h | ✅ **COMPLETE** (669 lines) |
| 1.4 | GUI Alert Panel | 6h | ⚠️ Partial (logs panel exists) |
| 1.5 | Position sizing DB schema | 2h | ⚠️ Partial |
| 1.6 | PositionSizer class | 4h | ✅ **COMPLETE** |

### Phase 2: Core Alerts **IN PROGRESS**

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 2.1 | Breakout Thread integration | 4h | ✅ **COMPLETE** (734 lines) |
| 2.2 | Position Thread integration | 6h | ⚠️ Thread running, alerts pending |
| 2.3 | Market Thread integration | 4h | ⚠️ Thread running, partial alerts |
| 2.4 | Hard Stop (30-min) thread | 2h | ❌ Not Started |
| 2.5 | Stop Warning (2-hour) thread | 2h | ❌ Not Started |
| 2.6 | Position sizing in alert messages | 4h | ✅ **COMPLETE** |

### Phase 3: IBD Gap Fixes (P0 Priority)

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 3.1 | 50 MA Volume Confirmation | 2h | ❌ Not Started |
| 3.2 | Market Regime Entry Blocking | 8h | ⚠️ Suppression works, blocking pending |
| 3.3 | 10-Week Line Sell (Weekly thread) | 4h | ❌ Not Started |
| 3.4 | 8-Week Hold Rule | 8h | ❌ Not Started |

### Phase 4: P1 Gaps + Alternative Entries

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 4.1 | Extended From Pivot alert | 2h | ✅ **COMPLETE** |
| 4.2 | Climax Top Detection | 4h | ❌ Not Started |
| 4.3 | TP2 Percentage Adjustment (40%→25%) | 1h | ❌ Not Started |
| 4.4 | State -1.5 implementation | 4h | ❌ Not Started |
| 4.5 | Re-entry detection (MA bounce, pivot retest) | 6h | ❌ Not Started |
| 4.6 | Exited Watch List GUI | 4h | ❌ Not Started |

### Phase 5: GUI Enhancements

(No changes from v2.1)

### Phase 6: Validation & Polish

(No changes from v2.1)

---

## 12. Validation Plan

### 12.1 Breakout Alert Validation Checklist **ADD: Specific Tests**

```markdown
## Pre-Market (Before 9:30 AM ET)
- [ ] Service running (check Windows Services)
- [ ] IBKR connected (check log: "IBKR client connected")
- [ ] Discord webhooks configured
- [ ] State 0 positions have valid pivots

## Market Hours Testing
- [ ] Thread only runs during market hours (9:30 AM - 4:00 PM ET)
- [ ] RVOL calculation accurate (compare to MarketSurge)
- [ ] Strong close detection working (upper half of range)
- [ ] Pivot distance calculation correct

## Alert Generation
- [ ] APPROACHING fires at -1% to 0% from pivot
- [ ] IN_BUY_ZONE fires at 0% to +5% with volume
- [ ] CONFIRMED fires with volume + strong close
- [ ] EXTENDED fires at >5% above pivot
- [ ] SUPPRESSED fires during market correction

## Cooldown & Suppression
- [ ] Same alert doesn't repeat within cooldown period (60 min)
- [ ] Market correction suppresses CONFIRMED → SUPPRESSED
- [ ] Different subtypes can fire independently

## Discord Delivery
- [ ] Alerts appear in correct channel (#breakout-alerts)
- [ ] Format matches design specification
- [ ] Grade and score displayed correctly
- [ ] Position sizing recommendation included
```

---

## 13. Configuration Reference

### 13.1 user_config.yaml **ADD: Actual Configuration**

```yaml
# CANSLIM Monitor Configuration
# Working configuration as of January 16, 2026

# Database
database:
  path: canslim_positions.db  # Relative to canslim_monitor folder

# IBKR Connection
ibkr:
  host: 127.0.0.1
  port: 4001                  # IB Gateway (4001=live, 4002=paper)
  client_id_base: 20          # Service uses 20-24, GUI uses 25
  timeout: 30
  max_client_id_retries: 5

# Discord Webhooks
discord:
  enabled: true
  webhooks:
    breakout: "https://discord.com/api/webhooks/..."
    position: "https://discord.com/api/webhooks/..."
    market: "https://discord.com/api/webhooks/..."
    system: "https://discord.com/api/webhooks/..."

# Thread Configuration
threads:
  breakout_interval: 60       # Seconds between checks
  position_interval: 30
  market_interval: 300

# Breakout Configuration
breakout:
  volume_threshold: 1.0       # RVOL threshold (1.0 = average)
  buy_zone_max_pct: 5.0       # Max % above pivot for buy zone
  approaching_pct: 1.0        # Within 1% = approaching
  account_value: 100000       # For position sizing
  stop_loss_pct: 7.0          # Default stop loss %

# Alert Configuration
alerts:
  cooldown_minutes: 60
  enable_suppression: true    # Suppress during market correction

# Position Sizing
position_sizing:
  account_risk_pct: 1.0       # Max 1% account risk per trade
  max_position_pct: 10.0      # Max 10% in single position
  initial_pct: 50.0           # 50% initial entry
  pyramid1_pct: 25.0          # 25% first add
  pyramid2_pct: 25.0          # 25% second add

# Logging
logging:
  level: DEBUG
  log_dir: logs               # Relative to canslim_monitor folder
```

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-14 | Initial Alert System Design |
| 1.1 | 2026-01-14 | Gap Analysis document created |
| 2.0 | 2026-01-14 | Merged design + gaps into unified plan |
| 2.1 | 2026-01-15 | Added Position Sizing Rules (Section 7), enhanced GUI specs |
| **2.2** | **2026-01-16** | **Implementation status updates: Breakout thread operational, RVOL calculation added, Windows Service architecture documented, event loop handling added, pivot status tracking added, actual config documented** |

---

## References

### Implementation Files

| File | Lines | Purpose |
|------|-------|---------|
| `service/threads/breakout_thread.py` | 734 | Breakout detection & alerts |
| `services/alert_service.py` | 669 | Alert routing & persistence |
| `integrations/discord_notifier.py` | 907 | Discord webhook integration |
| `utils/scoring_engine.py` | ~300 | Setup grading |
| `utils/position_sizer.py` | ~200 | Share calculations |
| `service/service_controller.py` | 536 | Service orchestration |
| `service/service_main.py` | 294 | Windows Service wrapper |

### Project Knowledge Files
(No changes from v2.1)

---

*This unified document supersedes Alert_System_Integration_Design.md and IBD_Gap_Analysis_Working_Document.md*
