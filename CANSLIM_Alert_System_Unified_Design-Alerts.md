# CANSLIM Alert System: Unified Design & Implementation Plan
## TrendSpider Migration, IBD Alignment, and Production Deployment

**Version:** 2.1  
**Created:** January 14, 2026  
**Updated:** January 15, 2026  
**Status:** Implementation Ready  
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
| Entry Signals (Breakout, Volume) | 95% | ✅ Complete |
| Pyramid Rules | 90% | ✅ Complete |
| Profit Taking (TP1/TP2) | 80% | ⚠️ TP2 needs adjustment |
| Stop Loss Rules | 95% | ✅ Complete |
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

### 2.1 Complete Alert Matrix (29 Types)

| # | Alert Type | Subtype | Thread | States | Priority | Status |
|---|------------|---------|--------|--------|----------|--------|
| **Breakout Alerts** |
| 1 | BREAKOUT | CONFIRMED | Daily | 0 | P0 | ✅ Designed |
| 2 | BREAKOUT | SUPPRESSED | Daily | 0 | P0 | ✅ Designed |
| 3 | BREAKOUT | IN_BUY_ZONE | Daily | 0 | P1 | ✅ Designed |
| 4 | BREAKOUT | APPROACHING | Daily | 0 | P1 | ✅ Designed |
| 5 | BREAKOUT | EXTENDED | Daily | 0 | P1 | ⚠️ **NEW** |
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
│  30-MINUTE THREAD (poll at :00, :30 during market hours)                    │
│  ───────────────────────────────────────────────────────                    │
│  Purpose: Capital protection - "Speed matters"                              │
│  Scope: States 1-6 (active positions)                                       │
│  Alerts: HARD_STOP                                                          │
│                                                                              │
│  2-HOUR THREAD (poll at 11:30, 1:30, 3:30)                                  │
│  ─────────────────────────────────────────────                              │
│  Purpose: Early warning                                                     │
│  Scope: States 1-6                                                          │
│  Alerts: STOP_WARNING                                                       │
│                                                                              │
│  DAILY THREAD (runs at 4:05 PM ET)                                          │
│  ─────────────────────────────────                                          │
│  Purpose: Confirmed close + volume verification                             │
│  Scope: All states                                                          │
│  Alerts: BREAKOUT, PYRAMID, PROFIT, MA_SELL, HEALTH, MARKET, ALT_ENTRY     │
│                                                                              │
│  WEEKLY THREAD (runs Friday at 4:10 PM ET)                                  │
│  ──────────────────────────────────────────                                 │
│  Purpose: IBD weekly chart signals                                          │
│  Scope: States 1+ and -1.5                                                  │
│  Alerts: 10_WEEK_SELL, THREE_WEEKS_TIGHT, NEW_BASE                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Thread Architecture

### 3.1 Alert Resolution Matrix (IBD-Aligned)

| Alert Type | IBD Guidance | TrendSpider | Python Default | Notes |
|------------|--------------|-------------|----------------|-------|
| HARD STOP | "Speed matters" | 30m-1h | **15 min** | Configurable 5m-1h |
| STOP WARNING | N/A | 2h | **2 hour** | Early warning |
| BREAKOUT | Daily close | Daily | **Daily 4:05 PM** | Confirmed close + volume |
| PYRAMID | N/A | Daily | **Daily** | Deliberate adds |
| TP1/TP2 | N/A | Daily | **Daily** | Profit confirmation |
| 50 MA SELL | Daily close + volume | Daily | **Daily** | **GAP: Add volume check** |
| 21 EMA SELL | Two daily closes | Daily | **Daily** | Count consecutive |
| **10 WEEK SELL** | **Weekly close** | ❌ Missing | **Weekly Fri 4:10** | **GAP: IBD primary guide** |
| **3 WEEKS TIGHT** | Weekly pattern | ❌ Missing | **Weekly** | **GAP: Add detection** |
| DISTRIBUTION DAY | Daily close | ❌ Missing | **Daily** | Market health |
| FTD | Daily close | ❌ Missing | **Daily** | Uptrend confirmation |

### 3.2 Scheduler Implementation

```python
# service/threads/alert_scheduler.py

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

class AlertScheduler:
    """
    Schedules alert checks at IBD-aligned resolutions.
    """
    
    def __init__(self, ibkr_client, alert_service, position_repo, market_repo):
        self.ibkr = ibkr_client
        self.alert_service = alert_service
        self.position_repo = position_repo
        self.market_repo = market_repo
        self.tz = pytz.timezone("America/New_York")
        
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._setup_schedules()
        
    def _setup_schedules(self):
        # 30-MINUTE: Hard Stop (speed matters)
        self.scheduler.add_job(
            self.run_30min_checks,
            CronTrigger(minute="0,30", hour="9-15", day_of_week="mon-fri"),
            id="30min_checks"
        )
        self.scheduler.add_job(
            self.run_30min_checks,
            CronTrigger(hour=16, minute=0, day_of_week="mon-fri"),
            id="30min_final"
        )
        
        # 2-HOUR: Stop Warning (early warning)
        self.scheduler.add_job(
            self.run_2hour_checks,
            CronTrigger(minute="30", hour="11,13,15", day_of_week="mon-fri"),
            id="2hour_checks"
        )
        
        # DAILY: Most alerts (confirmed close)
        self.scheduler.add_job(
            self.run_daily_checks,
            CronTrigger(hour=16, minute=5, day_of_week="mon-fri"),
            id="daily_checks"
        )
        
        # WEEKLY: IBD additional (10-week, 3WT)
        self.scheduler.add_job(
            self.run_weekly_checks,
            CronTrigger(hour=16, minute=10, day_of_week="fri"),
            id="weekly_checks"
        )
```

### 3.3 State-Active Alert Matrix

Alerts only fire when relevant to current position state:

| Alert | State 0 | State 1 | State 2 | State 3 | State 4 | State 5 | State 6 | State -1.5 |
|-------|---------|---------|---------|---------|---------|---------|---------|------------|
| BREAKOUT | ✓ | | | | | | | |
| EXTENDED | ✓ | | | | | | | |
| PYRAMID 1 | | ✓ | | | | | | |
| PYRAMID 2 | | | ✓ | | | | | |
| TP1 | | ✓ | ✓ | ✓ | | | | |
| TP2 | | | | | ✓ | | | |
| 8-WEEK HOLD | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| HARD STOP | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| 50 MA SELL | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| 21 EMA SELL | | | | | ✓ | ✓ | ✓ | |
| 10 WEEK SELL | | | | | ✓ | ✓ | ✓ | |
| CLIMAX TOP | | | | | ✓ | ✓ | ✓ | |
| WARNINGS | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| ALT_ENTRY | ✓ | | | | | | | ✓ |

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
    "BREAKOUT_EXTENDED": "⏸️",      # NEW
    "IN_BUY_ZONE": "✅",
    "APPROACHING_PIVOT": "👀",
    "PYRAMID_READY": "📈",
    "TP1_TRIGGERED": "💰",
    "TP2_TRIGGERED": "💎",
    "8_WEEK_HOLD": "⏳",            # NEW
    "HARD_STOP_HIT": "🛑",
    "MA_WARNING": "⚡",
    "MA_SELL": "🔻",
    "10_WEEK_SELL": "📉",          # NEW
    "CLIMAX_TOP": "🎢",            # NEW
    "HEALTH_WARNING": "⚠️",
    "HEALTH_CRITICAL": "🚨",
    "MARKET_WEAK": "📉",
    "MARKET_CORRECTION": "🛑",     # NEW
    "FTD_DETECTED": "🎯",
}
```

### 4.4 Discord Alert Formatting

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🚀 NVDA - BREAKOUT CONFIRMED                                       │
├─────────────────────────────────────────────────────────────────────┤
│ NVDA broke out above $145.50 pivot with 2.3x average volume        │
│                                                                     │
│ Price: $147.25     Grade: A     Volume: 2.3x                       │
│ Pattern: Cup w/Handle    Stage: 1    Depth: 18%                    │
│ Market: CONFIRMED UPTREND                                          │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ ⏳ AAPL - 8-WEEK HOLD TRIGGERED                                     │
├─────────────────────────────────────────────────────────────────────┤
│ AAPL gained 22% in 2 weeks. 8-week hold rule activated.            │
│ Hold until Mar 15 unless hard stop is hit.                         │
│                                                                     │
│ Price: $201.50     Entry: $165.00     Gain: +22.1%                 │
│ Hold Until: 2026-03-15     Days Left: 42                           │
│ Note: TP1 sell alert SUPPRESSED during hold period                 │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ 🛑 SPY - MARKET CORRECTION STARTED                                  │
├─────────────────────────────────────────────────────────────────────┤
│ Distribution day cluster detected. Market now in CORRECTION.        │
│ NEW BREAKOUT ALERTS BLOCKED until Follow-Through Day.              │
│                                                                     │
│ Price: $485.20     D-Days: 5     Status: CORRECTION                │
│ Last FTD: 2026-01-02     Rally Day: 0                              │
│ Action: Reduce exposure, no new entries                            │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.5 Discord Notifier Class

```python
# integrations/discord_notifier.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
import requests
from datetime import datetime

class AlertChannel(Enum):
    BREAKOUT = "breakout"
    POSITION = "position"
    EXITS = "exits"
    WARNINGS = "warnings"
    MARKET = "market"
    VALIDATION = "validation"
    SYSTEM = "system"

@dataclass
class DiscordAlert:
    symbol: str
    alert_type: str
    subtype: Optional[str]
    price: float
    message: str
    grade: Optional[str] = None
    channel: AlertChannel = AlertChannel.BREAKOUT
    color: int = 0x00FF00
    fields: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.now)

class DiscordNotifier:
    """Send formatted alerts to Discord webhooks."""
    
    # Channel routing by alert type
    CHANNEL_MAP = {
        "BREAKOUT": AlertChannel.BREAKOUT,
        "PYRAMID": AlertChannel.POSITION,
        "ADD": AlertChannel.POSITION,
        "PROFIT": AlertChannel.POSITION,
        "STOP": AlertChannel.EXITS,
        "TECHNICAL": AlertChannel.EXITS,
        "HEALTH": AlertChannel.WARNINGS,
        "MARKET": AlertChannel.MARKET,
        "ALT_ENTRY": AlertChannel.BREAKOUT,
    }
    
    def __init__(self, config: dict):
        self.webhooks = config.get('webhooks', {})
        self.rate_limit = config.get('rate_limit', 30)
        self.enabled = config.get('enabled', True)
        
    def send(self, alert: DiscordAlert) -> bool:
        if not self.enabled:
            return False
            
        webhook_url = self.webhooks.get(alert.channel.value)
        if not webhook_url:
            return False
            
        embed = self._build_embed(alert)
        
        try:
            response = requests.post(
                webhook_url,
                json={"embeds": [embed]},
                timeout=10
            )
            return response.status_code == 204
        except Exception as e:
            print(f"Discord send failed: {e}")
            return False
            
    def send_to_validation(self, alert: DiscordAlert) -> bool:
        """Send copy to validation channel for comparison."""
        if not self.webhooks.get('validation'):
            return False
            
        validation_alert = DiscordAlert(
            symbol=alert.symbol,
            alert_type=alert.alert_type,
            subtype=alert.subtype,
            price=alert.price,
            message=f"[PYTHON] {alert.message}",
            grade=alert.grade,
            channel=AlertChannel.VALIDATION,
            color=0x808080,
            fields=alert.fields,
            timestamp=alert.timestamp
        )
        return self.send(validation_alert)
```

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
    subtype TEXT,
    
    -- Context
    price REAL NOT NULL,
    volume REAL,
    volume_ratio REAL,
    
    -- Scoring
    grade TEXT,
    score REAL,
    
    -- Message
    message TEXT,
    
    -- Metadata
    thread_source TEXT,
    discord_sent INTEGER DEFAULT 0,
    discord_channel TEXT,
    market_status TEXT,          -- NEW: Market regime at alert time
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE INDEX idx_alerts_symbol ON alerts(symbol);
CREATE INDEX idx_alerts_type ON alerts(alert_type, subtype);
CREATE INDEX idx_alerts_created ON alerts(created_at);
CREATE INDEX idx_alerts_position ON alerts(position_id);
```

### 5.2 Position Table Additions (For Gaps)

```sql
-- 8-Week Hold Rule tracking
ALTER TABLE positions ADD COLUMN eight_week_hold_active BOOLEAN DEFAULT 0;
ALTER TABLE positions ADD COLUMN eight_week_hold_start DATE;
ALTER TABLE positions ADD COLUMN eight_week_hold_end DATE;
ALTER TABLE positions ADD COLUMN power_move_pct FLOAT;
ALTER TABLE positions ADD COLUMN power_move_weeks INTEGER;

-- Climax Top Detection tracking
ALTER TABLE positions ADD COLUMN max_daily_gain_pct FLOAT;
ALTER TABLE positions ADD COLUMN max_daily_range FLOAT;
ALTER TABLE positions ADD COLUMN max_daily_volume INTEGER;
ALTER TABLE positions ADD COLUMN days_above_200ma_70pct INTEGER DEFAULT 0;

-- Re-entry tracking (Alternative Entries)
ALTER TABLE positions ADD COLUMN exit_date DATE;
ALTER TABLE positions ADD COLUMN exit_price REAL;
ALTER TABLE positions ADD COLUMN exit_reason TEXT;
ALTER TABLE positions ADD COLUMN ma_test_count INTEGER DEFAULT 0;
ALTER TABLE positions ADD COLUMN original_pivot REAL;
ALTER TABLE positions ADD COLUMN first_low REAL;

-- Weekly data caching
ALTER TABLE positions ADD COLUMN weekly_close REAL;
ALTER TABLE positions ADD COLUMN weekly_volume INTEGER;
ALTER TABLE positions ADD COLUMN ten_week_ma REAL;
```

### 5.3 Market Regime Table Additions

```sql
-- Distribution day expiration tracking
ALTER TABLE market_regime ADD COLUMN distribution_day_dates TEXT;  -- JSON array of dates
ALTER TABLE market_regime ADD COLUMN distribution_day_prices TEXT; -- JSON array of close prices
ALTER TABLE market_regime ADD COLUMN last_ftd_date DATE;
ALTER TABLE market_regime ADD COLUMN rally_attempt_start DATE;
ALTER TABLE market_regime ADD COLUMN rally_attempt_day INTEGER DEFAULT 0;
```

---

## 6. Position State Machine

### 6.1 State Definitions

| State | Name | Description |
|-------|------|-------------|
| 0 | WATCHING | On watchlist, monitoring for breakout |
| 1 | INITIAL | Breakout confirmed, initial position |
| 2 | PYRAMID_1 | First add completed |
| 3 | PYRAMID_2 | Second add completed (full position) |
| 4 | PROFIT_1 | TP1 hit, partial profit taken |
| 5 | PROFIT_2 | TP2 hit, trailing remaining |
| 6 | EXTENDED | 8-week hold or long-term winner |
| -1 | CLOSED | Position fully closed |
| -1.5 | WATCHING_EXITED | **NEW:** Previously owned, watching for re-entry |
| -2 | STOPPED | Stopped out, archived |

### 6.2 State Transition Diagram

```
                                    ┌──────────────────────────────────────┐
                                    │         STATE MACHINE v2.0           │
                                    └──────────────────────────────────────┘

    ┌─────────┐
    │ State 0 │──────── BREAKOUT CONFIRMED ──────────▶┌─────────┐
    │WATCHING │                                       │ State 1 │
    └─────────┘◀──────── NEW BASE (from -1.5) ───────│ INITIAL │
         │                                            └────┬────┘
         │                                                 │
         │ EXTENDED                              PYRAMID 1 │ TP1 (20%)
         │ (>5% above pivot)                               ▼
         ▼                                           ┌─────────┐
    [NO ALERT]                                       │ State 2 │
                                                     │PYRAMID_1│
                                                     └────┬────┘
                                                          │
                                               PYRAMID 2  │ TP1 (20%)
                                                          ▼
                                                     ┌─────────┐
                                                     │ State 3 │
                                                     │PYRAMID_2│
                                                     └────┬────┘
                                                          │
    ┌─────────────────────────────────────────────────────┼─────────────────┐
    │                         TP1 TRIGGERED               │                 │
    │            ┌────────────────────────────────────────┘                 │
    │            ▼                                                          │
    │      ┌─────────┐                                                      │
    │      │ State 4 │─── 8-WEEK HOLD ACTIVE? ──▶ SUPPRESS TP1 ────┐       │
    │      │PROFIT_1 │                                              │       │
    │      └────┬────┘                                              │       │
    │           │                                                   │       │
    │  TP2 (25%)│                                              ┌────▼────┐  │
    │           ▼                                              │ State 6 │  │
    │      ┌─────────┐                                         │EXTENDED │  │
    │      │ State 5 │                                         └────┬────┘  │
    │      │PROFIT_2 │                                              │       │
    │      └────┬────┘◀── 8 weeks expire ──────────────────────────┘       │
    │           │                                                          │
    └───────────┼──────────────────────────────────────────────────────────┘
                │
    ┌───────────┼───────────────────────────────────────────────────────────┐
    │           │              EXIT SIGNALS (Any State 1+)                  │
    │           ▼                                                           │
    │   HARD STOP ──▶ State -2 (STOPPED)                                   │
    │   50 MA SELL ──▶ State -1.5 (WATCHING_EXITED) ──▶ Re-entry signals  │
    │   21 EMA SELL ──▶ State -1 (CLOSED)                                  │
    │   10 WEEK SELL ──▶ State -1.5 (WATCHING_EXITED)                      │
    │   CLIMAX TOP ──▶ State -1 (CLOSED)                                   │
    │   MANUAL ──▶ State -1 (CLOSED)                                       │
    │                                                                       │
    │   State -1.5 (WATCHING_EXITED):                                      │
    │   - MA_BOUNCE ──▶ State 1 (re-entry)                                 │
    │   - PIVOT_RETEST ──▶ State 1 (re-entry)                              │
    │   - CONFLUENCE ──▶ State 1 (re-entry)                                │
    │   - NEW_BASE ──▶ State 0 (new setup)                                 │
    │   - 60 days elapsed ──▶ State -2 (archived)                          │
    └───────────────────────────────────────────────────────────────────────┘
```

---

## 7. Position Sizing Rules

### 7.1 IBD Position Building Strategy

IBD methodology recommends building positions incrementally to manage risk and confirm the stock's behavior before committing full capital.

#### Entry & Pyramiding

| State | Action | Position % | Cumulative | Risk Profile |
|-------|--------|------------|------------|--------------|
| 0 → 1 | Initial Entry | 50% | 50% | Test the waters |
| 1 → 2 | Pyramid 1 | +25% | 75% | Stock proving itself |
| 2 → 3 | Pyramid 2 | +25% | 100% | Full conviction |

**Key Principles:**
- **Never buy full position on breakout** - Start with 50% to limit risk if breakout fails
- **Add only when winning** - Pyramid 1 triggers at 2-2.5% gain, Pyramid 2 at 4-5% gain
- **Avoid averaging down** - Only add to winning positions, never losers

#### Profit Taking

| State | Trigger | Action | Remaining Position |
|-------|---------|--------|-------------------|
| 3 → 4 | TP1 (20% gain) | Sell 1/3 (~33%) | ~67% |
| 4 → 5 | TP2 (25% gain) | Sell 1/2 of remaining (~33%) | ~34% |
| 5 → 6 | Trailing | Hold until exit signal | Trail remainder |

**8-Week Hold Modification:**
- If 8-week hold rule triggers (20%+ gain in 1-3 weeks), **TP1 sell is suppressed**
- Position remains at 100% during hold period
- After 8 weeks expire, resume normal TP rules
- Hard stop remains active throughout (capital protection)

### 7.2 Position Sizing Calculations

```python
# service/position_sizing.py

class PositionSizer:
    """
    Calculate share quantities for entries and exits.
    IBD: "Start with 50%, add 25%, add 25% for full position."
    """
    
    def __init__(self, account_risk_pct: float = 1.0, max_position_pct: float = 10.0):
        """
        Args:
            account_risk_pct: Max % of account to risk per trade (default 1%)
            max_position_pct: Max % of account in single position (default 10%)
        """
        self.account_risk_pct = account_risk_pct
        self.max_position_pct = max_position_pct
        
    def calculate_target_position(self, account_value: float, entry_price: float, 
                                   stop_price: float) -> dict:
        """
        Calculate full position size based on risk management.
        
        Returns dict with target shares and dollar amounts for each phase.
        """
        # Risk per share
        risk_per_share = entry_price - stop_price
        risk_pct_per_share = risk_per_share / entry_price
        
        # Max position by account %
        max_position_dollars = account_value * (self.max_position_pct / 100)
        max_shares_by_account = int(max_position_dollars / entry_price)
        
        # Max position by risk
        max_risk_dollars = account_value * (self.account_risk_pct / 100)
        max_shares_by_risk = int(max_risk_dollars / risk_per_share)
        
        # Target is the smaller of the two
        target_shares = min(max_shares_by_account, max_shares_by_risk)
        
        # Round to nice number
        target_shares = self._round_to_lot(target_shares)
        
        return {
            'target_shares': target_shares,
            'target_value': target_shares * entry_price,
            'initial': {
                'shares': int(target_shares * 0.50),
                'pct': 50,
                'value': int(target_shares * 0.50) * entry_price
            },
            'pyramid1': {
                'shares': int(target_shares * 0.25),
                'pct': 25,
                'trigger_pct': 2.5,  # Add at 2-2.5% above entry
                'value': int(target_shares * 0.25) * entry_price * 1.025
            },
            'pyramid2': {
                'shares': target_shares - int(target_shares * 0.50) - int(target_shares * 0.25),
                'pct': 25,
                'trigger_pct': 5.0,  # Add at 4-5% above entry
                'value': (target_shares - int(target_shares * 0.50) - int(target_shares * 0.25)) * entry_price * 1.05
            },
            'risk_per_share': risk_per_share,
            'total_risk': target_shares * risk_per_share,
            'risk_pct_of_account': (target_shares * risk_per_share) / account_value * 100
        }
        
    def calculate_profit_exits(self, position) -> dict:
        """
        Calculate share quantities for profit taking.
        
        TP1: Sell 1/3 at 20% gain
        TP2: Sell 1/2 of remaining at 25% gain
        Trail: Hold rest until exit signal
        """
        current_shares = position.current_shares
        
        tp1_shares = int(current_shares / 3)  # Sell 1/3
        remaining_after_tp1 = current_shares - tp1_shares
        
        tp2_shares = int(remaining_after_tp1 / 2)  # Sell 1/2 of remaining
        trailing_shares = remaining_after_tp1 - tp2_shares
        
        return {
            'tp1': {
                'trigger_pct': 20,
                'shares_to_sell': tp1_shares,
                'price': position.avg_cost * 1.20,
                'remaining': remaining_after_tp1
            },
            'tp2': {
                'trigger_pct': 25,
                'shares_to_sell': tp2_shares,
                'price': position.avg_cost * 1.25,
                'remaining': trailing_shares
            },
            'trailing': {
                'shares': trailing_shares,
                'exit_method': '21 EMA or 10-week line'
            }
        }
        
    def calculate_avg_cost(self, position) -> float:
        """Calculate weighted average cost basis after pyramiding."""
        total_cost = 0
        total_shares = 0
        
        if position.initial_shares:
            total_cost += position.initial_shares * position.entry_price
            total_shares += position.initial_shares
            
        if position.pyramid1_shares and position.pyramid1_price:
            total_cost += position.pyramid1_shares * position.pyramid1_price
            total_shares += position.pyramid1_shares
            
        if position.pyramid2_shares and position.pyramid2_price:
            total_cost += position.pyramid2_shares * position.pyramid2_price
            total_shares += position.pyramid2_shares
            
        return total_cost / total_shares if total_shares > 0 else 0
        
    def _round_to_lot(self, shares: int, lot_size: int = 5) -> int:
        """Round shares to nearest lot size for cleaner orders."""
        return round(shares / lot_size) * lot_size
```

### 7.3 Position Sizing Database Schema

```sql
-- Position sizing tracking columns
ALTER TABLE positions ADD COLUMN target_shares INTEGER;       -- Full position size (100%)
ALTER TABLE positions ADD COLUMN current_shares INTEGER;      -- Currently held shares
ALTER TABLE positions ADD COLUMN position_pct REAL;           -- Current % of target (50, 75, 100)

-- Entry tracking
ALTER TABLE positions ADD COLUMN initial_shares INTEGER;      -- Entry size (50%)
ALTER TABLE positions ADD COLUMN initial_price REAL;          -- Entry price
ALTER TABLE positions ADD COLUMN pyramid1_shares INTEGER;     -- P1 add size (25%)
ALTER TABLE positions ADD COLUMN pyramid1_price REAL;         -- P1 execution price
ALTER TABLE positions ADD COLUMN pyramid2_shares INTEGER;     -- P2 add size (25%)
ALTER TABLE positions ADD COLUMN pyramid2_price REAL;         -- P2 execution price

-- Cost basis tracking
ALTER TABLE positions ADD COLUMN avg_cost REAL;               -- Weighted average cost
ALTER TABLE positions ADD COLUMN total_invested REAL;         -- Total $ invested

-- Profit taking tracking
ALTER TABLE positions ADD COLUMN tp1_shares_sold INTEGER;     -- Shares sold at TP1
ALTER TABLE positions ADD COLUMN tp1_price REAL;              -- TP1 execution price
ALTER TABLE positions ADD COLUMN tp1_date DATE;               -- TP1 date
ALTER TABLE positions ADD COLUMN tp2_shares_sold INTEGER;     -- Shares sold at TP2
ALTER TABLE positions ADD COLUMN tp2_price REAL;              -- TP2 execution price
ALTER TABLE positions ADD COLUMN tp2_date DATE;               -- TP2 date

-- Create index for position queries
CREATE INDEX idx_positions_sizing ON positions(target_shares, current_shares, position_pct);
```

### 7.4 Alert Message Formats with Position Sizing

#### Breakout Alert (Initial Entry)

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🚀 NVDA - BREAKOUT CONFIRMED                                       │
├─────────────────────────────────────────────────────────────────────┤
│ NVDA broke out above $145.50 pivot with 2.3x average volume        │
│                                                                     │
│ Price: $147.25     Grade: A     Volume: 2.3x                       │
│ Pattern: Cup w/Handle    Stage: 1    Depth: 18%                    │
│                                                                     │
│ ▶ ACTION: Buy 50 shares (50% initial position)                     │
│   Target Full Position: 100 shares                                 │
│   Estimated Cost: $7,362                                           │
│   Stop Loss: $135.50 (7.2% risk)                                   │
│                                                                     │
│ Market: CONFIRMED UPTREND                                          │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘
```

#### Pyramid 1 Alert

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📈 NVDA - PYRAMID 1 READY                                          │
├─────────────────────────────────────────────────────────────────────┤
│ NVDA in Pyramid 1 zone (2.5% above entry)                          │
│                                                                     │
│ Current Price: $149.14     Entry: $145.50     Gain: +2.5%         │
│                                                                     │
│ ▶ ACTION: Add 25 shares (brings position to 75%)                   │
│   Current Holdings: 50 shares @ $145.50                            │
│   After Add: 75 shares @ $146.71 avg                               │
│   Add Cost: $3,728                                                 │
│                                                                     │
│ Pyramid 2 Zone: $152.78 (+5.0%)                                    │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘
```

#### Pyramid 2 Alert

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📈 NVDA - PYRAMID 2 READY                                          │
├─────────────────────────────────────────────────────────────────────┤
│ NVDA in Pyramid 2 zone (5.0% above entry)                          │
│                                                                     │
│ Current Price: $152.78     Entry: $145.50     Gain: +5.0%         │
│                                                                     │
│ ▶ ACTION: Add 25 shares (completes FULL position)                  │
│   Current Holdings: 75 shares @ $146.71 avg                        │
│   After Add: 100 shares @ $148.23 avg                              │
│   Add Cost: $3,820                                                 │
│                                                                     │
│ 🎯 FULL POSITION ACHIEVED                                          │
│ Next Target: TP1 at $177.88 (+20%)                                 │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘
```

#### TP1 Alert

```
┌─────────────────────────────────────────────────────────────────────┐
│ 💰 NVDA - TP1 TRIGGERED                                            │
├─────────────────────────────────────────────────────────────────────┤
│ NVDA hit 20% profit target                                         │
│                                                                     │
│ Current Price: $177.88     Avg Cost: $148.23     Gain: +20.0%     │
│                                                                     │
│ ▶ ACTION: Sell 33 shares (1/3 of position)                         │
│   Current Holdings: 100 shares                                     │
│   After Sale: 67 shares remaining                                  │
│   Locked Profit: $979 (+20.0%)                                     │
│                                                                     │
│ Next Target: TP2 at $185.29 (+25%)                                 │
│ Trailing Stop: 21 EMA @ $168.50                                    │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘
```

#### TP1 Suppressed (8-Week Hold Active)

```
┌─────────────────────────────────────────────────────────────────────┐
│ ⏳ NVDA - TP1 SUPPRESSED (8-WEEK HOLD)                             │
├─────────────────────────────────────────────────────────────────────┤
│ NVDA hit 20% but 8-week hold rule is ACTIVE                        │
│                                                                     │
│ Current Price: $177.88     Avg Cost: $148.23     Gain: +20.0%     │
│ Power Move: +22.1% in 2 weeks (triggered 8-week hold)              │
│                                                                     │
│ ▶ ACTION: HOLD - Do not sell                                       │
│   8-Week Hold Expires: Feb 27, 2026 (42 days)                      │
│   Current Holdings: 100 shares (maintain full position)            │
│                                                                     │
│ ⚠️ Hard Stop still active at $135.50                               │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘
```

#### TP2 Alert

```
┌─────────────────────────────────────────────────────────────────────┐
│ 💎 NVDA - TP2 TRIGGERED                                            │
├─────────────────────────────────────────────────────────────────────┤
│ NVDA hit 25% profit target                                         │
│                                                                     │
│ Current Price: $185.29     Avg Cost: $148.23     Gain: +25.0%     │
│                                                                     │
│ ▶ ACTION: Sell 33 shares (1/2 of remaining)                        │
│   Current Holdings: 67 shares                                      │
│   After Sale: 34 shares remaining                                  │
│   Locked Profit: $1,223 (+25.0%)                                   │
│                                                                     │
│ Remaining Position: TRAILING                                       │
│ Exit on: 21 EMA break or 10-week line violation                    │
├─────────────────────────────────────────────────────────────────────┤
│ CANSLIM Monitor v2.0                    Today at 4:05 PM           │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.5 Position Sizing State Tracking

The position object tracks sizing through the lifecycle:

```python
# Example position lifecycle with sizing data

# State 0 → 1: Initial Entry
position.state = 1
position.target_shares = 100
position.initial_shares = 50
position.initial_price = 145.50
position.current_shares = 50
position.position_pct = 50
position.avg_cost = 145.50
position.total_invested = 7275.00

# State 1 → 2: Pyramid 1
position.state = 2
position.pyramid1_shares = 25
position.pyramid1_price = 149.14
position.current_shares = 75
position.position_pct = 75
position.avg_cost = 146.71  # Weighted average
position.total_invested = 11003.50

# State 2 → 3: Pyramid 2
position.state = 3
position.pyramid2_shares = 25
position.pyramid2_price = 152.78
position.current_shares = 100
position.position_pct = 100
position.avg_cost = 148.23
position.total_invested = 14823.00

# State 3 → 4: TP1
position.state = 4
position.tp1_shares_sold = 33
position.tp1_price = 177.88
position.tp1_date = date.today()
position.current_shares = 67
position.position_pct = 67  # 67% of original target

# State 4 → 5: TP2
position.state = 5
position.tp2_shares_sold = 33
position.tp2_price = 185.29
position.tp2_date = date.today()
position.current_shares = 34
position.position_pct = 34  # Trailing remainder
```

---

## 8. Alternative Entry System

### 7.1 State -1.5: Watching Exited

When a position exits via stop loss or MA sell (not full profit), it transitions to State -1.5 for re-entry monitoring:

```python
# Transition to State -1.5 on non-profit exits
if exit_reason in ['STOP', 'MA_SELL', '10_WEEK_SELL']:
    position.state = -1.5
    position.exit_date = datetime.now().date()
    position.exit_price = current_price
    position.exit_reason = exit_reason
    position.ma_test_count = 0
    position.original_pivot = position.pivot  # Preserve for retest detection
```

### 7.2 Alternative Entry Detection

```python
# service/threads/reentry_detector.py

class ReentryDetector:
    """Detect alternative entry opportunities."""
    
    def check_ma_bounce(self, position, price, ma_50, daily_data):
        """
        First/second test of 50-day MA with reversal.
        IBD: "The first or second test of the 10-week/50-day line 
        after a breakout often provides a buying opportunity."
        """
        if position.ma_test_count >= 3:
            return None  # 3rd+ test = lower probability
            
        distance_to_ma = abs(price - ma_50) / ma_50
        
        if distance_to_ma <= 0.01:  # Within 1%
            # Check for reversal: today's close > yesterday's close
            if daily_data[-1]['close'] > daily_data[-2]['close']:
                position.ma_test_count += 1
                return AlertContext(
                    symbol=position.symbol,
                    alert_type="ALT_ENTRY",
                    subtype="MA_BOUNCE",
                    price=price,
                    message=f"{position.symbol} bouncing off 50-day MA "
                            f"(test #{position.ma_test_count})",
                    extra_fields={
                        "MA Test": f"#{position.ma_test_count}",
                        "50-Day MA": f"${ma_50:.2f}",
                        "Prior Exit": position.exit_reason,
                        "Days Since Exit": (datetime.now().date() - position.exit_date).days
                    }
                )
        return None
        
    def check_pivot_retest(self, position, price):
        """Price returning to original pivot zone."""
        if not position.original_pivot:
            return None
            
        distance_to_pivot = abs(price - position.original_pivot) / position.original_pivot
        
        if distance_to_pivot <= 0.01:  # Within 1%
            return AlertContext(
                symbol=position.symbol,
                alert_type="ALT_ENTRY",
                subtype="PIVOT_RETEST",
                price=price,
                message=f"{position.symbol} retesting original pivot "
                        f"${position.original_pivot:.2f}",
                extra_fields={
                    "Original Pivot": f"${position.original_pivot:.2f}",
                    "Prior Entry": f"${position.entry_price:.2f}",
                    "Prior Exit": position.exit_reason,
                }
            )
        return None
        
    def check_confluence_area(self, position, price, ma_50, pivot):
        """
        Multiple support levels aligning.
        IBD: "When multiple support areas converge, it creates a 
        high-probability buying opportunity."
        """
        ma_distance = abs(price - ma_50) / ma_50
        pivot_distance = abs(price - pivot) / pivot
        ma_pivot_distance = abs(ma_50 - pivot) / pivot
        
        # MA and pivot within 2% of each other = confluence
        if ma_pivot_distance <= 0.02 and ma_distance <= 0.02:
            return AlertContext(
                symbol=position.symbol,
                alert_type="ALT_ENTRY",
                subtype="CONFLUENCE",
                price=price,
                message=f"{position.symbol} at confluence area: "
                        f"50-day (${ma_50:.2f}) + pivot (${pivot:.2f})",
                extra_fields={
                    "50-Day MA": f"${ma_50:.2f}",
                    "Pivot": f"${pivot:.2f}",
                    "Confluence Zone": f"${min(ma_50, pivot):.2f} - ${max(ma_50, pivot):.2f}",
                }
            )
        return None
        
    def check_shakeout_plus_3(self, position, price):
        """
        Shakeout +3: First low of base + 10%.
        IBD: "An aggressive entry point - use half position size."
        """
        if not position.first_low:
            return None
            
        shakeout_level = position.first_low * 1.10
        
        if price >= shakeout_level and price <= shakeout_level * 1.02:
            return AlertContext(
                symbol=position.symbol,
                alert_type="ALT_ENTRY",
                subtype="SHAKEOUT_3",
                price=price,
                message=f"{position.symbol} at Shakeout +3 level",
                extra_fields={
                    "First Low": f"${position.first_low:.2f}",
                    "Shakeout +3": f"${shakeout_level:.2f}",
                    "Note": "⚠️ Use HALF position size",
                }
            )
        return None
```

---

## 9. IBD Methodology Gaps

### 8.1 Gap Summary Table

| Priority | Gap | Description | Est. Effort | Status |
|----------|-----|-------------|-------------|--------|
| **P0** | 8-Week Hold Rule | Suppress TP1 when stock gains 20%+ in 1-3 weeks | 8h | ❌ Not Started |
| **P0** | 10-Week Line Sell | Weekly close below 10-week MA on volume | 4h | ❌ Not Started |
| **P0** | Market Regime Integration | Block entries during CORRECTION | 8h | ❌ Not Started |
| **P0** | 50 MA Volume Confirmation | Require volume on 50 MA sell | 2h | ❌ Not Started |
| **P1** | Extended From Pivot | Alert when stock >5% above pivot | 2h | ❌ Not Started |
| **P1** | Climax Top Detection | Detect exhaustion signals | 4h | ❌ Not Started |
| **P1** | TP2 Percentage Adjust | Change from 40% to 25-30% | 1h | ❌ Not Started |
| **P2** | Distribution Day Expiration | Expire D-days after 25 days or 5% rally | 4h | ❌ Not Started |

### 8.2 P0 Gap: 8-Week Hold Rule

**IBD Guidance:**
> "If a stock gains 20% or more in the first 1-3 weeks after a breakout, hold it for at least 8 weeks. This rule keeps you in potential big winners."

**Implementation:**

```python
# service/rules/eight_week_hold.py

class EightWeekHoldRule:
    """
    Implements IBD's 8-Week Hold Rule for power moves.
    """
    
    def check_power_move(self, position, current_price):
        """
        Check if position qualifies for 8-week hold.
        
        Conditions:
        - Gain of 20%+ from entry price
        - Achieved within 3 weeks (15 trading days) of entry
        """
        if position.eight_week_hold_active:
            return None  # Already active
            
        days_since_entry = (datetime.now().date() - position.entry_date).days
        trading_days = self._count_trading_days(position.entry_date)
        
        if trading_days > 15:  # Beyond 3-week window
            return None
            
        gain_pct = (current_price - position.entry_price) / position.entry_price * 100
        
        if gain_pct >= 20:
            # Activate 8-week hold
            position.eight_week_hold_active = True
            position.eight_week_hold_start = datetime.now().date()
            position.eight_week_hold_end = position.eight_week_hold_start + timedelta(weeks=8)
            position.power_move_pct = gain_pct
            position.power_move_weeks = max(1, trading_days // 5)
            
            return AlertContext(
                symbol=position.symbol,
                alert_type="PROFIT",
                subtype="8_WEEK_HOLD",
                price=current_price,
                message=f"⏳ {position.symbol} 8-WEEK HOLD ACTIVATED\n"
                        f"Gained {gain_pct:.1f}% in {position.power_move_weeks} week(s).\n"
                        f"Hold until {position.eight_week_hold_end.strftime('%b %d')}",
                extra_fields={
                    "Entry": f"${position.entry_price:.2f}",
                    "Current": f"${current_price:.2f}",
                    "Gain": f"+{gain_pct:.1f}%",
                    "Hold Until": position.eight_week_hold_end.strftime("%Y-%m-%d"),
                    "Note": "TP1 alerts SUPPRESSED during hold"
                }
            )
        return None
        
    def is_hold_active(self, position):
        """Check if 8-week hold is currently active."""
        if not position.eight_week_hold_active:
            return False
        if datetime.now().date() > position.eight_week_hold_end:
            # Hold expired
            position.eight_week_hold_active = False
            return False
        return True
        
    def should_suppress_tp1(self, position):
        """TP1 should be suppressed during active 8-week hold."""
        return self.is_hold_active(position)
```

**Alert Modification:**

```python
# In TP1 check logic
def check_tp1(self, position, price):
    if self.eight_week_rule.should_suppress_tp1(position):
        # Don't fire TP1 - 8-week hold active
        return None
    
    # Normal TP1 logic
    if price >= position.entry_price * 1.20:
        return self._create_tp1_alert(position, price)
```

### 8.3 P0 Gap: 10-Week Line Sell

**IBD Guidance:**
> "The 10-week moving average is your primary trend guide. A decisive close below it on volume is a sell signal."

**Implementation:**

```python
# service/rules/ten_week_sell.py

class TenWeekSellRule:
    """
    Weekly chart sell signal based on 10-week MA violation.
    Runs in Weekly thread (Friday 4:10 PM).
    """
    
    def check_weekly_violation(self, position, weekly_data):
        """
        Check for 10-week line violation.
        
        Conditions:
        - Weekly close below 10-week MA
        - Volume on down week > average weekly volume
        - Position held 8+ weeks (extended run)
        """
        weeks_held = (datetime.now().date() - position.entry_date).days // 7
        
        if weeks_held < 8:
            return None  # Not an extended run yet
            
        weekly_close = weekly_data[-1]['close']
        weekly_volume = weekly_data[-1]['volume']
        ten_week_ma = self._calc_10_week_ma(weekly_data)
        avg_weekly_volume = self._calc_avg_weekly_volume(weekly_data)
        
        if weekly_close < ten_week_ma:
            # Below 10-week line
            if weekly_volume > avg_weekly_volume:
                # Volume confirms - definitive sell
                return AlertContext(
                    symbol=position.symbol,
                    alert_type="TECHNICAL",
                    subtype="10_WEEK_SELL",
                    price=weekly_close,
                    message=f"📉 {position.symbol} 10-WEEK LINE VIOLATED\n"
                            f"Weekly close ${weekly_close:.2f} below 10-week MA "
                            f"${ten_week_ma:.2f} on {weekly_volume/avg_weekly_volume:.1f}x volume",
                    extra_fields={
                        "Weekly Close": f"${weekly_close:.2f}",
                        "10-Week MA": f"${ten_week_ma:.2f}",
                        "Volume": f"{weekly_volume/avg_weekly_volume:.1f}x avg",
                        "Weeks Held": weeks_held,
                        "Action": "SELL - Primary trend broken"
                    }
                )
            else:
                # No volume - warning only
                return AlertContext(
                    symbol=position.symbol,
                    alert_type="TECHNICAL",
                    subtype="10_WEEK_WARNING",
                    price=weekly_close,
                    message=f"⚠️ {position.symbol} below 10-week line (no volume confirm)",
                    extra_fields={
                        "Weekly Close": f"${weekly_close:.2f}",
                        "10-Week MA": f"${ten_week_ma:.2f}",
                        "Action": "WATCH - Need volume to confirm"
                    }
                )
        return None
```

### 8.4 P0 Gap: Market Regime Integration

**IBD Guidance:**
> "Don't fight the market. When the market status changes to 'Uptrend Under Pressure' or 'Correction', reduce exposure and stop taking new entries."

**Implementation:**

```python
# service/rules/market_regime_filter.py

class MarketRegimeFilter:
    """
    Filter breakout alerts based on market regime.
    IBD: "The M in CANSLIM is the most important letter."
    """
    
    def should_send_breakout_alert(self, position, market_regime):
        """
        Determine if breakout alert should be sent based on market status.
        
        Returns: (should_send: bool, prefix: Optional[str], reason: str)
        """
        status = market_regime.status
        d_day_count = market_regime.distribution_day_count
        
        if status == "CORRECTION":
            return False, None, "MARKET_BLOCKED"
            
        if status == "UPTREND_UNDER_PRESSURE":
            return True, "[⚠️ CAUTION]", "UPTREND_PRESSURE"
            
        if d_day_count >= 5:
            return True, "[⚡ ELEVATED RISK]", "DISTRIBUTION_CLUSTER"
            
        return True, None, "MARKET_OK"
        
    def modify_breakout_alert(self, alert, market_regime):
        """Add market context to breakout alerts."""
        should_send, prefix, reason = self.should_send_breakout_alert(
            alert.position, market_regime
        )
        
        if not should_send:
            # Log suppressed alert
            self._log_suppressed(alert, reason)
            return None
            
        if prefix:
            alert.message = f"{prefix} {alert.message}"
            alert.fields["Market Status"] = market_regime.status
            alert.fields["D-Days"] = f"{market_regime.distribution_day_count}/5"
            
        return alert
```

**Entry Blocking in Breakout Thread:**

```python
# In breakout_thread.py
def check_breakout(self, position, price, volume):
    # Get current market regime
    market_regime = self.market_repo.get_current_regime()
    
    # Check if market allows new entries
    if market_regime.status == "CORRECTION":
        # Log but don't alert
        self.logger.info(
            f"BREAKOUT SUPPRESSED (market correction): {position.symbol}"
        )
        return None
        
    # Normal breakout logic...
```

### 8.5 P0 Gap: 50 MA Volume Confirmation

**IBD Guidance:**
> "A close below the 50-day moving average on above-average volume is a clear sell signal. Without volume, it may just be a pullback."

**Enhanced Implementation:**

```python
def check_50ma_sell(self, position, daily_data):
    """
    Check for 50-day MA violation with volume confirmation.
    
    IBD: "Close below 50 MA on above-average volume is a sell.
    Without volume, it may just be a pullback."
    """
    close = daily_data[-1]['close']
    volume = daily_data[-1]['volume']
    ma_50 = self._calc_50_day_ma(daily_data)
    avg_volume = self._calc_50_day_avg_volume(daily_data)
    
    if close < ma_50:
        volume_ratio = volume / avg_volume
        
        if volume_ratio >= 1.0:
            # Volume confirms - immediate sell signal
            return AlertContext(
                symbol=position.symbol,
                alert_type="TECHNICAL",
                subtype="50_MA_SELL",
                price=close,
                message=f"🔻 {position.symbol} CLOSED BELOW 50-DAY MA on volume",
                extra_fields={
                    "Close": f"${close:.2f}",
                    "50-Day MA": f"${ma_50:.2f}",
                    "Volume": f"{volume_ratio:.1f}x avg",
                    "Action": "SELL - Confirmed break"
                }
            )
        else:
            # No volume - warning, track consecutive days
            days_below = self._count_consecutive_days_below_ma(position, daily_data, ma_50)
            
            if days_below >= 2:
                # 2+ days below without volume = delayed confirmation
                return AlertContext(
                    symbol=position.symbol,
                    alert_type="TECHNICAL",
                    subtype="50_MA_SELL",
                    price=close,
                    message=f"🔻 {position.symbol} 2+ DAYS BELOW 50-DAY MA",
                    extra_fields={
                        "Days Below": days_below,
                        "Action": "SELL - Delayed confirmation"
                    }
                )
            else:
                # First day below, low volume - warning only
                return AlertContext(
                    symbol=position.symbol,
                    alert_type="TECHNICAL",
                    subtype="50_MA_WARNING",
                    price=close,
                    message=f"⚠️ {position.symbol} closed below 50-day MA (low volume)",
                    extra_fields={
                        "Close": f"${close:.2f}",
                        "50-Day MA": f"${ma_50:.2f}",
                        "Volume": f"{volume_ratio:.1f}x avg",
                        "Action": "WATCH - Need volume or 2nd day to confirm"
                    }
                )
    return None
```

### 8.6 P1 Gap: Extended From Pivot Alert

**Implementation:**

```python
def check_extended_from_pivot(self, position, price):
    """
    Alert when stock moves too far above pivot for safe entry.
    IBD: "Don't chase. If >5% above pivot, wait for pullback."
    """
    if position.state != 0:  # Only for watching positions
        return None
        
    extension_pct = (price - position.pivot) / position.pivot * 100
    
    if extension_pct > 5:
        return AlertContext(
            symbol=position.symbol,
            alert_type="BREAKOUT",
            subtype="EXTENDED",
            price=price,
            message=f"⏸️ {position.symbol} EXTENDED from pivot - don't chase",
            extra_fields={
                "Price": f"${price:.2f}",
                "Pivot": f"${position.pivot:.2f}",
                "Extension": f"+{extension_pct:.1f}%",
                "Action": "Wait for pullback to MA or new base"
            }
        )
    return None
```

### 8.7 P1 Gap: Climax Top Detection

**IBD Guidance:**
> "After an extended run, watch for exhaustion signals: largest daily point gain, widest spread, highest volume of the entire run."

**Implementation:**

```python
def check_climax_top(self, position, daily_data):
    """
    Detect potential climax top signals.
    IBD: "These exhaustion signals often mark the top."
    """
    if position.state < 4:  # Only for runners
        return None
        
    today = daily_data[-1]
    
    # Calculate today's metrics
    daily_gain_pct = (today['close'] - today['open']) / today['open'] * 100
    daily_range = today['high'] - today['low']
    daily_volume = today['volume']
    
    # Check if price is extended above 200 MA
    ma_200 = self._calc_200_day_ma(daily_data)
    extension_above_200 = (today['close'] - ma_200) / ma_200 * 100
    
    if extension_above_200 < 70:
        return None  # Not extended enough for climax concern
        
    # Count exhaustion signals (need 2 of 3)
    signals = 0
    reasons = []
    
    if daily_gain_pct > position.max_daily_gain_pct:
        signals += 1
        reasons.append(f"Largest daily gain: +{daily_gain_pct:.1f}%")
        position.max_daily_gain_pct = daily_gain_pct
        
    if daily_range > position.max_daily_range:
        signals += 1
        reasons.append(f"Widest daily range: ${daily_range:.2f}")
        position.max_daily_range = daily_range
        
    if daily_volume > position.max_daily_volume:
        signals += 1
        reasons.append(f"Highest volume: {daily_volume:,}")
        position.max_daily_volume = daily_volume
        
    if signals >= 2:
        return AlertContext(
            symbol=position.symbol,
            alert_type="TECHNICAL",
            subtype="CLIMAX_TOP",
            price=today['close'],
            message=f"🎢 {position.symbol} CLIMAX TOP WARNING\n"
                    f"Exhaustion signals detected after extended run",
            extra_fields={
                "Signals": f"{signals}/3 exhaustion signals",
                "Extension": f"+{extension_above_200:.0f}% above 200-MA",
                "Details": "\n".join(reasons),
                "Action": "Consider taking profits"
            }
        )
    return None
```

---

## 10. GUI Components

### 10.1 Position Cards - Enhanced Layout

Position cards need to display sizing information clearly:

```
┌─────────────────────────────────────────────────────────────────────┐
│ NVDA                                           State: 3 (FULL POS) │
├─────────────────────────────────────────────────────────────────────┤
│ Entry: $145.50    Current: $168.20    Gain: +15.6%                 │
│                                                                     │
│ POSITION SIZING                                                     │
│ ├── Target: 100 shares                                             │
│ ├── Current: 100 shares (100%)                                     │
│ ├── Avg Cost: $148.25                                              │
│ └── Invested: $14,825                                              │
│                                                                     │
│ BUILD HISTORY                                                       │
│ ├── Initial (50%): 50 sh @ $145.50  ✓                             │
│ ├── Pyramid 1 (25%): 25 sh @ $149.00  ✓                           │
│ └── Pyramid 2 (25%): 25 sh @ $152.00  ✓                           │
│                                                                     │
│ NEXT ACTION                                                         │
│ └── TP1 at $177.90: Sell 33 shares (1/3)                          │
│                                                                     │
│ Stop Loss: $135.50 (8.6% below avg cost)                           │
└─────────────────────────────────────────────────────────────────────┘
```

**Card States by Position Phase:**

```
State 1 (Initial):
┌─────────────────────────────────────────────────────────────────────┐
│ AAPL                                         State: 1 (INITIAL)    │
├─────────────────────────────────────────────────────────────────────┤
│ Entry: $185.00    Current: $186.50    Gain: +0.8%                  │
│                                                                     │
│ POSITION: 50 of 100 shares (50%)                                   │
│ Invested: $9,250    Avg Cost: $185.00                              │
│                                                                     │
│ BUILD HISTORY                                                       │
│ ├── Initial (50%): 50 sh @ $185.00  ✓                             │
│ ├── Pyramid 1 (25%): waiting @ $189.63 (+2.5%)                    │
│ └── Pyramid 2 (25%): waiting @ $194.25 (+5.0%)                    │
│                                                                     │
│ NEXT ACTION: Pyramid 1 at $189.63                                  │
└─────────────────────────────────────────────────────────────────────┘

State 4 (After TP1):
┌─────────────────────────────────────────────────────────────────────┐
│ MSFT                                         State: 4 (PROFIT_1)   │
├─────────────────────────────────────────────────────────────────────┤
│ Entry: $410.00    Current: $498.00    Gain: +21.5%                 │
│                                                                     │
│ POSITION: 67 of 100 shares (67%)                                   │
│ Invested: $27,462    Avg Cost: $409.88                              │
│                                                                     │
│ PROFIT TAKEN                                                        │
│ └── TP1: Sold 33 sh @ $492.00 (+20%)  💰 $2,710 profit            │
│                                                                     │
│ NEXT ACTION: TP2 at $512.35 (+25%) - Sell 33 shares               │
│ Trailing Stop: 21 EMA @ $475.00                                    │
└─────────────────────────────────────────────────────────────────────┘

State 6 (8-Week Hold):
┌─────────────────────────────────────────────────────────────────────┐
│ GOOGL                                        State: 6 (8WK HOLD)   │
├─────────────────────────────────────────────────────────────────────┤
│ Entry: $165.00    Current: $205.00    Gain: +24.2%                 │
│                                                                     │
│ ⏳ 8-WEEK HOLD ACTIVE                                               │
│ ├── Power Move: +21.5% in 2 weeks                                  │
│ ├── Hold Until: Feb 27, 2026                                       │
│ ├── Days Remaining: 38                                             │
│ └── TP1 Status: SUPPRESSED                                         │
│                                                                     │
│ POSITION: 100 shares (100%) - HOLDING                              │
│ Invested: $16,725    Avg Cost: $167.25                              │
│                                                                     │
│ Hard Stop: $155.00 (still active)                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.2 Position Table Columns

**Existing columns to keep:**
- Symbol
- State
- Entry Price
- Current Price
- Gain %
- Days Held
- Grade

**New columns to add:**

| Column | Width | Description | Format |
|--------|-------|-------------|--------|
| Shares | 80px | Current shares held | "67/100" |
| Pos % | 60px | % of target position | "67%" with color |
| Avg Cost | 90px | Weighted average cost | "$148.25" |
| Invested | 100px | Total $ in position | "$14,825" |
| Next Action | 150px | What we're waiting for | "TP1 @ $177.90" |
| 8WK Hold | 80px | Hold status | "38 days" or "—" |

**Color coding for Pos % column:**
- 50% = Yellow (initial only)
- 75% = Light Blue (building)
- 100% = Green (full position)
- 67% = Gold (after TP1)
- 34% = Orange (after TP2, trailing)

### 10.3 Watchlist Table Updates

For State 0 positions, show projected sizing:

| Symbol | Grade | Pivot | Current | Distance | Target Shares | Initial Buy | Est. Cost |
|--------|-------|-------|---------|----------|---------------|-------------|-----------|
| NVDA | A | $145.50 | $143.20 | -1.6% | 100 | 50 | $7,275 |
| AAPL | B+ | $185.00 | $182.50 | -1.4% | 80 | 40 | $7,400 |
| TSLA | B | $275.00 | $268.00 | -2.5% | 60 | 30 | $8,250 |

### 10.4 Alert History Widget

```python
# gui/widgets/alert_history.py

class AlertHistoryWidget(QWidget):
    """Widget for viewing and filtering historical alerts."""
    
    TYPE_COLORS = {
        "BREAKOUT": QColor(46, 204, 113),   # Green
        "PYRAMID": QColor(52, 152, 219),    # Blue
        "PROFIT": QColor(241, 196, 15),     # Gold
        "STOP": QColor(231, 76, 60),        # Red
        "TECHNICAL": QColor(230, 126, 34),  # Orange
        "HEALTH": QColor(255, 99, 71),      # Tomato
        "MARKET": QColor(65, 105, 225),     # Royal blue
        "ALT_ENTRY": QColor(155, 89, 182),  # Purple
    }
    
    def __init__(self, alert_repo, parent=None):
        super().__init__(parent)
        self.alert_repo = alert_repo
        self.setup_ui()
        self.load_alerts()
        
        # Auto-refresh every 30 seconds
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.load_alerts)
        self.refresh_timer.start(30000)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Filter bar
        filter_layout = QHBoxLayout()
        
        # Symbol filter
        filter_layout.addWidget(QLabel("Symbol:"))
        self.symbol_filter = QLineEdit()
        self.symbol_filter.setPlaceholderText("e.g., NVDA")
        self.symbol_filter.setMaximumWidth(100)
        self.symbol_filter.textChanged.connect(self.load_alerts)
        filter_layout.addWidget(self.symbol_filter)
        
        # Type filter
        filter_layout.addWidget(QLabel("Type:"))
        self.type_filter = QComboBox()
        self.type_filter.addItems([
            "All Types", "BREAKOUT", "PYRAMID", "PROFIT", 
            "STOP", "TECHNICAL", "HEALTH", "MARKET", "ALT_ENTRY"
        ])
        self.type_filter.currentTextChanged.connect(self.load_alerts)
        filter_layout.addWidget(self.type_filter)
        
        # Date range
        filter_layout.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_from.dateChanged.connect(self.load_alerts)
        filter_layout.addWidget(self.date_from)
        
        filter_layout.addStretch()
        
        # Alert count + gap indicator
        self.count_label = QLabel("0 alerts")
        filter_layout.addWidget(self.count_label)
        
        layout.addLayout(filter_layout)
        
        # Alert table
        self.table = QTableWidget()
        self.table.setColumnCount(10)  # Added Action and Shares columns
        self.table.setHorizontalHeaderLabels([
            "Time", "Symbol", "Type", "Subtype", "Price", 
            "Grade", "Action", "Shares", "Market", "Message"
        ])
        layout.addWidget(self.table)
```

### 10.5 Exited Watch List Tab

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📋 Exited - Watching for Re-Entry                                  │
├─────────────────────────────────────────────────────────────────────┤
│ Symbol │ Exit Date │ Exit Reason │ Exit Price │ Current │ MA Tests │
├────────┼───────────┼─────────────┼────────────┼─────────┼──────────┤
│ NVDA   │ Jan 10    │ STOP        │ $138.50    │ $142.30 │ 1        │
│ AAPL   │ Jan 08    │ MA_SELL     │ $182.00    │ $179.50 │ 0        │
│ MSFT   │ Jan 05    │ MANUAL      │ $410.00    │ $398.00 │ 2        │
└─────────────────────────────────────────────────────────────────────┘
│ [🔍 Check Now] [📊 View Chart] [❌ Remove] [📁 Archive]           │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.6 8-Week Hold Indicator

Add to position detail view:

```
┌─────────────────────────────────────────────────────────────────────┐
│ NVDA - Position Detail                                              │
├─────────────────────────────────────────────────────────────────────┤
│ State: 4 (PROFIT_1)     Entry: $145.50     Current: $178.20        │
│ Gain: +22.5%            Days Held: 18                              │
│                                                                     │
│ ⏳ 8-WEEK HOLD ACTIVE                                               │
│ ├── Triggered: Jan 2, 2026 (+20.1% in 2 weeks)                     │
│ ├── Hold Until: Feb 27, 2026                                       │
│ ├── Days Remaining: 44                                             │
│ └── TP1 Sell: SUPPRESSED                                           │
│                                                                     │
│ Hard Stop: $135.00 (still active during hold)                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 10.7 Position Sizing Summary Panel

Add a summary panel to the main dashboard:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 📊 POSITION SIZING SUMMARY                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ Active Positions: 5                                                 │
│ Total Invested: $52,340                                            │
│ Current Value: $58,920                                             │
│ Unrealized P/L: +$6,580 (+12.6%)                                   │
│                                                                     │
│ BY POSITION PHASE:                                                  │
│ ├── Initial (50%): 1 position ($9,250)                            │
│ ├── Building (75%): 1 position ($14,200)                          │
│ ├── Full (100%): 2 positions ($22,500)                            │
│ └── Trailing: 1 position ($6,390)                                 │
│                                                                     │
│ 8-Week Holds Active: 1 (GOOGL - 38 days remaining)                 │
│                                                                     │
│ PROFIT TAKEN THIS MONTH:                                           │
│ ├── TP1 Sales: $8,540                                             │
│ ├── TP2 Sales: $3,220                                             │
│ └── Total Locked: $11,760                                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 11. Implementation Sequence

### Phase 1: Foundation (Current Sprint)

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 1.1 | Discord Notifier class | 4h | ⬜ Not Started |
| 1.2 | Alert Repository + schema | 4h | ⬜ Not Started |
| 1.3 | Alert Service layer | 4h | ⬜ Not Started |
| 1.4 | GUI Alert Panel | 6h | ⬜ Not Started |
| 1.5 | Position sizing DB schema | 2h | ⬜ Not Started |
| 1.6 | PositionSizer class | 4h | ⬜ Not Started |

### Phase 2: Core Alerts (Next Sprint)

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 2.1 | Breakout Thread integration | 4h | ⬜ Not Started |
| 2.2 | Position Thread integration | 6h | ⬜ Not Started |
| 2.3 | Market Thread integration | 4h | ⬜ Not Started |
| 2.4 | Hard Stop (30-min) thread | 2h | ⬜ Not Started |
| 2.5 | Stop Warning (2-hour) thread | 2h | ⬜ Not Started |
| 2.6 | Position sizing in alert messages | 4h | ⬜ Not Started |

### Phase 3: IBD Gap Fixes (P0 Priority)

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 3.1 | 50 MA Volume Confirmation | 2h | ⬜ Not Started |
| 3.2 | Market Regime Entry Blocking | 8h | ⬜ Not Started |
| 3.3 | 10-Week Line Sell (Weekly thread) | 4h | ⬜ Not Started |
| 3.4 | 8-Week Hold Rule | 8h | ⬜ Not Started |

### Phase 4: P1 Gaps + Alternative Entries

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 4.1 | Extended From Pivot alert | 2h | ⬜ Not Started |
| 4.2 | Climax Top Detection | 4h | ⬜ Not Started |
| 4.3 | TP2 Percentage Adjustment (40%→25%) | 1h | ⬜ Not Started |
| 4.4 | State -1.5 implementation | 4h | ⬜ Not Started |
| 4.5 | Re-entry detection (MA bounce, pivot retest) | 6h | ⬜ Not Started |
| 4.6 | Exited Watch List GUI | 4h | ⬜ Not Started |

### Phase 5: GUI Enhancements

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 5.1 | Enhanced Position Cards (sizing display) | 6h | ⬜ Not Started |
| 5.2 | Position Table new columns | 4h | ⬜ Not Started |
| 5.3 | Watchlist projected sizing | 3h | ⬜ Not Started |
| 5.4 | Position Sizing Summary Panel | 4h | ⬜ Not Started |
| 5.5 | 8-Week Hold indicator in cards | 2h | ⬜ Not Started |

### Phase 6: Validation & Polish

| Step | Task | Est. Hours | Status |
|------|------|------------|--------|
| 6.1 | TrendSpider parallel validation | 8h | ⬜ Not Started |
| 6.2 | Distribution day expiration (P2) | 4h | ⬜ Not Started |
| 6.3 | Three Weeks Tight detection | 4h | ⬜ Not Started |
| 6.4 | Final GUI polish | 4h | ⬜ Not Started |

**Total Estimated Effort: ~128 hours**

### Implementation Priority Order

1. **Position Sizing Foundation** (Phase 1.5-1.6) - Critical for all subsequent work
2. **Core Alert Threads** (Phase 2) - Get basic alerts working
3. **IBD P0 Gaps** (Phase 3) - Must fix before production
4. **GUI Position Cards** (Phase 5.1-5.2) - User-facing sizing display
5. **Alternative Entries** (Phase 4) - Secondary entry signals
6. **Validation** (Phase 6) - Final production readiness

---

## 12. Validation Plan

### 12.1 TrendSpider Parity Testing

Run Python alerts in parallel with TrendSpider for 2 weeks:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    VALIDATION ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│    TrendSpider V3.6                     Python Monitor              │
│    ─────────────────                    ──────────────              │
│    [JavaScript Indicators]              [Service Threads]           │
│           │                                    │                    │
│           ▼                                    ▼                    │
│    #trendspider-alerts              #canslim-validation             │
│    (existing channel)                (new channel)                  │
│           │                                    │                    │
│           └────────────┬───────────────────────┘                    │
│                        ▼                                            │
│               Manual Comparison Log                                 │
│               (SQLite + Google Sheet)                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 12.2 Validation Metrics

| Metric | Target | Calculation |
|--------|--------|-------------|
| Match Rate | 95% | (Matched alerts / Total alerts) × 100 |
| Latency | < 5s | Python alert time - TrendSpider alert time |
| False Positives | < 2% | Python fired but TS didn't |
| False Negatives | < 3% | TS fired but Python didn't |

### 12.3 Daily Validation Checklist

```markdown
## Breakout Alerts
- [ ] BREAKOUT CONFIRMED - timestamps match within 60s
- [ ] BREAKOUT SUPPRESSED - volume threshold correct
- [ ] IN BUY ZONE - price range matches
- [ ] APPROACHING PIVOT - proximity % matches

## Position Alerts
- [ ] PYRAMID signals - level calculations match
- [ ] TP1/TP2 triggers - percentage thresholds match
- [ ] HARD STOP - stop level correct
- [ ] MA warnings - technical calculations match

## Market Alerts
- [ ] Distribution day detection - dates match
- [ ] FTD detection - criteria aligned
- [ ] Regime classification - BULLISH/NEUTRAL/BEARISH matches

## IBD Gap Validation
- [ ] 8-Week Hold - suppresses TP1 correctly
- [ ] 10-Week Sell - fires on Friday after weekly close
- [ ] Market blocking - no breakouts during CORRECTION
- [ ] 50 MA volume - distinguishes warning vs sell
```

---

## 13. Configuration Reference

### 13.1 config.yaml

```yaml
# Alert Resolution Configuration
alert_resolution:
  threads:
    hard_stop:
      enabled: true
      interval_minutes: 15
      market_hours_only: true
      
    stop_warning:
      enabled: true
      interval_minutes: 120
      market_hours_only: true
      
    daily:
      enabled: true
      run_time: "16:05"
      timezone: "America/New_York"
      
    weekly:
      enabled: true
      run_time: "16:10"
      day: "friday"
      timezone: "America/New_York"

# Discord Configuration
discord:
  enabled: true
  webhooks:
    breakout: "https://discord.com/api/webhooks/..."
    position: "https://discord.com/api/webhooks/..."
    exits: "https://discord.com/api/webhooks/..."
    warnings: "https://discord.com/api/webhooks/..."
    market: "https://discord.com/api/webhooks/..."
    validation: "https://discord.com/api/webhooks/..."
    system: "https://discord.com/api/webhooks/..."
  rate_limit: 30
  
  colors:
    breakout: 3066993      # Green
    pyramid: 3447003       # Blue
    take_profit: 15844367  # Gold
    warning: 15105570      # Orange
    stop_exit: 15158332    # Red
    trailing_exit: 10181046  # Purple

# Alert Cooldowns
alerts:
  cooldown_minutes: 60
  validation_mode: true
  
  cooldowns:
    BREAKOUT: 60
    PYRAMID: 30
    PROFIT: 0
    STOP: 0
    TECHNICAL: 60
    HEALTH: 120
    MARKET: 300
    ALT_ENTRY: 60

# IBD Rule Parameters
ibd_rules:
  eight_week_hold:
    enabled: true
    trigger_gain_pct: 20
    trigger_weeks_max: 3
    hold_weeks: 8
    
  profit_targets:
    tp1_pct: 20
    tp2_pct: 25  # Changed from 40%
    
  market_regime:
    block_entries_on_correction: true
    caution_prefix_on_pressure: true
    elevated_risk_ddays: 5
    
  ma_sells:
    require_volume_confirmation: true
    volume_threshold: 1.0
    consecutive_days_fallback: 2

# Alternative Entry Parameters
alternative_entries:
  enabled: true
  ma_bounce:
    proximity_pct: 1.0
    max_tests: 2
  pivot_retest:
    proximity_pct: 1.0
  confluence:
    max_spread_pct: 2.0
  shakeout_3:
    first_low_pct: 10.0
  aging:
    archive_after_days: 60
```

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-14 | Initial Alert System Design |
| 1.1 | 2026-01-14 | Gap Analysis document created |
| 2.0 | 2026-01-14 | Merged design + gaps into unified plan |
| **2.1** | **2026-01-15** | **Added Position Sizing Rules (Section 7), enhanced GUI specs with position cards and table columns, updated alert messages with share counts** |

---

## References

### Project Knowledge Files
- `MarketSurge_Using_the_8-week_Hold_Rule_to_Achieve_Massive_Gains_otter_ai.txt`
- `MarketSurge__How_to_Enhance_Your_Trading_with_Moving_Averages_otter_ai.txt`
- `MarketSurge_-_Essential_Selling_Strategies_to_Lock_In_Gains_and_Minimize_Losses_otter_ai.txt`
- `MarketSurge_How_to_Identify_Market_Tops_otter_ai.txt`
- `MarketSurge_Understanding_the_Importance_of_Follow-Through_Days_otter_ai.txt`

### Key IBD Quotes

**On 8-Week Hold:**
> "If a stock gains 20% or more in the first 1-3 weeks after a breakout, hold it for at least 8 weeks. This rule keeps you in potential big winners."

**On 10-Week Line:**
> "The 10-week moving average on the weekly chart serves as the primary trend guide for existing positions. A decisive close below it on volume is a sell signal."

**On Market Regime:**
> "Don't fight the market. When distribution days cluster and the market status changes to 'Correction', reduce exposure and stop taking new entries."

**On Volume Confirmation:**
> "A close below the 50-day moving average on above-average volume is a clear sell signal. Without volume, it may just be a pullback."

---

*This unified document supersedes Alert_System_Integration_Design.md and IBD_Gap_Analysis_Working_Document.md*
