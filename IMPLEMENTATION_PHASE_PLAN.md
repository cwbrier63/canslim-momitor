# CANSLIM Monitor - Phased Implementation Plan
## Merging Watchlist Monitor, TrendSpider V3.6 Logic, and Alert System Design

**Version:** 1.0  
**Created:** January 15, 2026  
**Based On:** CANSLIM_Alert_System_Unified_Design v2.1

---

## 1. Executive Summary

This document outlines the phased approach to merge:
1. **CANSLIM Watch List Monitor** - Current breakout system with scoring engine and market regime
2. **TrendSpider V3.6 JavaScript** - Position management alerts, health scoring, pyramid flags
3. **canslim_monitor Framework** - Target codebase with service architecture and GUI

### Goals
- Unified codebase with all functionality in one framework
- Match TrendSpider V3.6 alert parity (95%+)
- Implement IBD methodology gaps (8-week hold, 10-week line, market blocking)
- Production-ready Windows service with Discord alerts

---

## 2. Component Mapping

### 2.1 What Exists Where

| Component | Watchlist Monitor | canslim_monitor | TrendSpider V3.6 | Status |
|-----------|-------------------|-----------------|------------------|--------|
| **Scoring Engine** | `scoring_engine.py` ✅ | `utils/scoring.py` (basic) | Pattern/Stage/RS scores | **MERGE** |
| **Market Regime** | `distribution_tracker.py`, `ftd_tracker.py`, `market_regime.py` ✅ | `models.py` (schema only) | Market exposure level | **MERGE** |
| **Breakout Detection** | `monitor_v2.py` ✅ | `threads/breakout_thread.py` (skeleton) | Breakout signals | **MERGE** |
| **Position Monitoring** | - | `threads/position_thread.py` (skeleton) | All position alerts | **CREATE** |
| **IBKR Client** | `ibkr_client.py` ✅ | `integrations/ibkr_client.py` ✅ | - | **DONE** |
| **Discord Notifier** | `discord_notifier_v2.py` | `integrations/discord_notifier.py` ✅ | - | **DONE** |
| **Position Sizing** | - | - | Share calculations | **CREATE** |
| **Health Score** | - | - | Full implementation | **CREATE** |
| **8-Week Hold** | - | - | Partial | **CREATE** |
| **GUI/Kanban** | - | `gui/` ✅ | - | **DONE** |
| **Windows Service** | - | `service/` ✅ | - | **DONE** |

### 2.2 TrendSpider V3.6 Alert Types to Implement

From the JavaScript, these signals need Python equivalents:

| Signal | Current Status | Target Thread |
|--------|----------------|---------------|
| BREAKOUT CONFIRMED | In monitor_v2.py | breakout_thread |
| BREAKOUT SUPPRESSED | In monitor_v2.py | breakout_thread |
| PYRAMID 1/2 READY | Not implemented | position_thread |
| PYRAMID 1/2 EXTENDED | Not implemented | position_thread |
| PULLBACK ADD | Not implemented | position_thread |
| 21 EMA ADD | Not implemented | position_thread |
| TP1/TP2 TRIGGERED | Not implemented | position_thread |
| HARD STOP HIT | Not implemented | hard_stop_thread |
| 50 MA WARNING/SELL | Not implemented | position_thread |
| 21 EMA WARNING | Not implemented | position_thread |
| HEALTH WARNING/CRITICAL | Not implemented | position_thread |
| EARNINGS WARNING | Not implemented | position_thread |
| LATE STAGE RISK | Not implemented | position_thread |
| MARKET WEAK | In market_regime.py | market_thread |

---

## 3. Implementation Phases

### Phase 1: Foundation (Current Sprint - 12 hours)
**Goal:** Get scoring engine and core alert infrastructure working

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 1.1 Merge scoring_engine.py into utils/ | `utils/scoring_engine.py` | 2 | - |
| 1.2 Create scoring_config.yaml | `config/scoring_config.yaml` | 1 | 1.1 |
| 1.3 Create position_sizer.py | `utils/position_sizer.py` | 2 | - |
| 1.4 Create health_calculator.py | `utils/health_calculator.py` | 2 | - |
| 1.5 Create alert_service.py | `services/alert_service.py` | 2 | 1.1 |
| 1.6 Update Discord notifier with new formats | `integrations/discord_notifier.py` | 2 | 1.5 |
| 1.7 Add missing Position model fields | `data/models.py` | 1 | - |

**Deliverable:** Scoring engine integrated, alert service created, position sizing ready

---

### Phase 2: Breakout Thread Enhancement (8 hours)
**Goal:** Full breakout detection matching TrendSpider

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 2.1 Merge monitor_v2.py logic into breakout_thread | `service/threads/breakout_thread.py` | 3 | Phase 1 |
| 2.2 Add BREAKOUT_CONFIRMED alert generation | breakout_thread.py | 1 | 2.1 |
| 2.3 Add BREAKOUT_SUPPRESSED alert generation | breakout_thread.py | 1 | 2.1 |
| 2.4 Add BREAKOUT_EXTENDED check | breakout_thread.py | 1 | 2.1 |
| 2.5 Integrate scoring engine into alerts | breakout_thread.py | 1 | 2.1, 1.1 |
| 2.6 Add execution risk assessment | breakout_thread.py | 1 | 2.5 |

**Deliverable:** Breakout thread fires all entry-related alerts

---

### Phase 3: Position Thread Implementation (16 hours)
**Goal:** Full position monitoring matching TrendSpider

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 3.1 Implement pyramid level detection | `service/threads/position_thread.py` | 2 | Phase 2 |
| 3.2 Add PYRAMID 1/2 READY alerts | position_thread.py | 2 | 3.1 |
| 3.3 Add PYRAMID EXTENDED alerts | position_thread.py | 1 | 3.2 |
| 3.4 Add PULLBACK ADD (50 MA bounce) | position_thread.py | 2 | 3.1 |
| 3.5 Add 21 EMA ADD signal | position_thread.py | 1 | 3.4 |
| 3.6 Implement TP1/TP2 trigger alerts | position_thread.py | 2 | Phase 1.3 |
| 3.7 Implement health score calculation | position_thread.py | 2 | Phase 1.4 |
| 3.8 Add HEALTH WARNING/CRITICAL alerts | position_thread.py | 1 | 3.7 |
| 3.9 Add EARNINGS WARNING alert | position_thread.py | 1 | - |
| 3.10 Add 50 MA WARNING/SELL signals | position_thread.py | 2 | - |

**Deliverable:** Position thread monitors all in-position alerts

---

### Phase 4: Market Regime Integration (8 hours)
**Goal:** Merge market regime system and implement entry blocking

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 4.1 Merge distribution_tracker.py | `utils/distribution_tracker.py` | 2 | - |
| 4.2 Merge ftd_tracker.py | `utils/ftd_tracker.py` | 1 | 4.1 |
| 4.3 Merge market_regime.py into market_thread | `service/threads/market_thread.py` | 2 | 4.1, 4.2 |
| 4.4 Add MARKET_CORRECTION entry blocking | breakout_thread.py | 1 | 4.3 |
| 4.5 Add regime-aware Discord alerts | alert_service.py | 1 | 4.3 |
| 4.6 Create morning regime alert (8 AM ET) | market_thread.py | 1 | 4.3 |

**Deliverable:** Market regime fully integrated with entry blocking

---

### Phase 5: IBD Gap Fixes (10 hours)
**Goal:** Implement missing IBD methodology

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 5.1 Implement 8-week hold rule | `utils/eight_week_hold.py` | 3 | Phase 3 |
| 5.2 Add 8-week hold to position_thread | position_thread.py | 1 | 5.1 |
| 5.3 Implement 10-week line monitoring | position_thread.py | 2 | - |
| 5.4 Add volume confirmation to 50 MA sell | position_thread.py | 1 | Phase 3.10 |
| 5.5 Implement climax top detection | `utils/climax_detector.py` | 2 | - |
| 5.6 Add climax alert to position_thread | position_thread.py | 1 | 5.5 |

**Deliverable:** 95%+ IBD methodology coverage

---

### Phase 6: Hard Stop Thread (4 hours)
**Goal:** Implement 30-minute capital protection thread

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 6.1 Create hard_stop_thread.py | `service/threads/hard_stop_thread.py` | 2 | Phase 3 |
| 6.2 Implement HARD_STOP_HIT alert | hard_stop_thread.py | 1 | 6.1 |
| 6.3 Add 30-minute polling during market hours | hard_stop_thread.py | 1 | 6.2 |

**Deliverable:** Capital protection with 30-minute checks

---

### Phase 7: GUI Integration (8 hours)
**Goal:** Connect alert system to GUI

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 7.1 Add Alert Panel to kanban_window | `gui/alert_panel.py` | 3 | Phase 3 |
| 7.2 Add position sizing display to cards | `gui/position_card.py` | 2 | Phase 1.3 |
| 7.3 Add health score display to cards | `gui/position_card.py` | 1 | Phase 3.7 |
| 7.4 Add market regime indicator | `gui/market_indicator.py` | 2 | Phase 4 |

**Deliverable:** GUI shows all alerts and position data

---

### Phase 8: Validation & Polish (6 hours)
**Goal:** Verify parity with TrendSpider

| Task | File(s) | Hours | Dependencies |
|------|---------|-------|--------------|
| 8.1 Create validation test suite | `tests/test_alerts_parity.py` | 2 | All phases |
| 8.2 Run parallel with TrendSpider for 2 weeks | - | 2 | 8.1 |
| 8.3 Tune thresholds based on results | config files | 2 | 8.2 |

**Deliverable:** 95%+ TrendSpider parity confirmed

---

## 4. Total Effort Estimate

| Phase | Hours | Status |
|-------|-------|--------|
| Phase 1: Foundation | 12 | 🟡 Starting |
| Phase 2: Breakout Thread | 8 | ⬜ Not Started |
| Phase 3: Position Thread | 16 | ⬜ Not Started |
| Phase 4: Market Regime | 8 | ⬜ Not Started |
| Phase 5: IBD Gap Fixes | 10 | ⬜ Not Started |
| Phase 6: Hard Stop Thread | 4 | ⬜ Not Started |
| Phase 7: GUI Integration | 8 | ⬜ Not Started |
| Phase 8: Validation | 6 | ⬜ Not Started |
| **TOTAL** | **72** | |

---

## 5. File Structure After Implementation

```
canslim_monitor/
├── config/
│   ├── config.yaml              # Main config
│   ├── scoring_config.yaml      # Scoring rules (NEW)
│   └── service_config.yaml      # Service settings
├── data/
│   ├── models.py                # Updated with sizing fields
│   ├── database.py
│   └── repositories/
├── gui/
│   ├── alert_panel.py           # (NEW) Alert display
│   ├── market_indicator.py      # (NEW) Regime display
│   ├── kanban_window.py
│   └── position_card.py         # Updated with sizing/health
├── integrations/
│   ├── discord_notifier.py      # Enhanced alert formats
│   └── ibkr_client.py
├── service/
│   ├── threads/
│   │   ├── breakout_thread.py   # Enhanced with scoring
│   │   ├── position_thread.py   # Full implementation
│   │   ├── market_thread.py     # Regime integration
│   │   └── hard_stop_thread.py  # (NEW) 30-min checks
│   ├── service_controller.py
│   └── service_main.py
├── services/                     # (NEW)
│   └── alert_service.py         # Alert generation/routing
└── utils/
    ├── scoring_engine.py        # (NEW) Merged from watchlist
    ├── position_sizer.py        # (NEW) Share calculations
    ├── health_calculator.py     # (NEW) Health score logic
    ├── distribution_tracker.py  # (NEW) Merged from watchlist
    ├── ftd_tracker.py           # (NEW) Merged from watchlist
    ├── eight_week_hold.py       # (NEW) IBD gap fix
    └── climax_detector.py       # (NEW) IBD gap fix
```

---

## 6. Next Steps

**Immediate (Today):**
1. ✅ Create this implementation plan
2. 🟡 Start Phase 1.1: Merge scoring_engine.py
3. 🟡 Start Phase 1.3: Create position_sizer.py

**This Week:**
- Complete Phase 1 (Foundation)
- Begin Phase 2 (Breakout Thread Enhancement)

**Validation Criteria:**
- Unit tests pass for scoring engine
- Breakout thread generates alerts matching TrendSpider
- Position sizing calculations match design doc

---

## 7. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Scoring config breaks existing behavior | Keep old `utils/scoring.py` as fallback |
| IBKR connection issues | Use mock client for testing |
| TrendSpider parity not achievable | Accept 90%+ and document differences |
| Performance issues with multiple threads | Profile and optimize, consider async |

---

*Document History:*
- v1.0 (2026-01-15): Initial phased implementation plan
