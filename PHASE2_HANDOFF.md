# CANSLIM Monitor - Phase 2 Handoff Document
## Breakout Thread Implementation

**Created:** January 15, 2026  
**Status:** Phase 1 Complete, Phase 2 Ready to Start  
**Goal:** Get breakout alerts firing to Discord

---

## 1. What Was Completed (Phase 1)

### New Files Created in `canslim_monitor/`

| File | Purpose | Status |
|------|---------|--------|
| `utils/scoring_engine.py` | Calculates setup grades (A+, B, C, etc.) with RS floor | ✅ Merged from watchlist |
| `utils/position_sizer.py` | Calculates 50/25/25 pyramid shares, TP1/TP2 exits | ✅ Created |
| `utils/health_calculator.py` | Health score (0-10) from TrendSpider V3.6 logic | ✅ Created |
| `config/scoring_config.yaml` | Scoring weights, RS tiers, grade boundaries | ✅ Copied |
| `services/alert_service.py` | Alert routing, cooldown, Discord dispatch | ✅ Created |
| `services/__init__.py` | Package exports | ✅ Created |
| `IMPLEMENTATION_PHASE_PLAN.md` | Full 72-hour roadmap | ✅ Created |

### Key Classes Available

```python
# Scoring
from canslim_monitor.utils import ScoringEngine, ScoringResult
engine = ScoringEngine("config/scoring_config.yaml")
result = engine.score(pattern="cup w/handle", stage="2", depth_pct=20, length_weeks=7, rs_rating=92)
# result.grade = "A", result.final_score = 18, result.rs_floor_applied = False

# Position Sizing
from canslim_monitor.utils import PositionSizer, PositionSizeResult
sizer = PositionSizer()
sizing = sizer.calculate_target_position(account_value=100000, entry_price=50.00, stop_price=46.50)
# sizing.initial_shares = 140 (50%), sizing.pyramid1_shares = 70 (25%), etc.

# Alert Service
from canslim_monitor.services import AlertService, AlertType, AlertSubtype, AlertContext
alert_service = AlertService(db_session_factory, discord_notifier, cooldown_minutes=60)
alert_service.create_alert(symbol="NVDA", alert_type=AlertType.BREAKOUT, subtype=AlertSubtype.CONFIRMED, ...)
```

---

## 2. What Phase 2 Must Implement

### File to Modify
`canslim_monitor/service/threads/breakout_thread.py`

### Current State (Skeleton)
```python
def _do_work(self):
    """Check all State 0 positions for breakouts."""
    positions = self._get_watchlist_positions()  # Returns empty list
    for pos in positions:
        self._check_position(pos)  # Does nothing useful

def _check_position(self, pos):
    # Just logs, doesn't create alerts
    pass
```

### Target State (Full Implementation)

The breakout thread needs to:

1. **Query State 0 positions from database**
2. **Get real-time prices from IBKR**
3. **Detect breakout conditions:**
   - Price crosses above pivot
   - Volume >= 1.0x average (configurable)
   - Close in upper half of day's range (strong close)
4. **Score the setup** using `ScoringEngine`
5. **Calculate position size** using `PositionSizer`
6. **Check market regime** for suppression
7. **Create alert** via `AlertService` → sends to Discord

### Breakout Conditions (from TrendSpider V3.6)

```javascript
// From the JavaScript indicator:
const breakoutVolume = volSMA[lastIdx] > 0 && volume[lastIdx] > volSMA[lastIdx] * 1.5;
const strongClose = close[lastIdx] > (high[lastIdx] + low[lastIdx]) / 2;
const breakoutConditionMet = positionState === 0 && pivotPrice > 0 && 
                              close[lastIdx] > pivotPrice && breakoutVolume && strongClose;

// Extended check (>5% above pivot = no entry)
const isExtended = pivotPrice > 0 && close[lastIdx] > pivotPrice * 1.05;
```

### Alert Types to Generate

| Condition | Alert Type | Subtype |
|-----------|------------|---------|
| Price > pivot, volume OK, market OK | BREAKOUT | CONFIRMED |
| Price > pivot, volume OK, market BAD | BREAKOUT | SUPPRESSED |
| Price > pivot * 1.05 (extended) | BREAKOUT | EXTENDED |
| Price within 1% of pivot | BREAKOUT | APPROACHING |

---

## 3. Implementation Checklist

### 3.1 Update `__init__` to Accept Dependencies

```python
def __init__(
    self,
    shutdown_event,
    poll_interval: int = 60,
    db_session_factory=None,
    ibkr_client=None,
    discord_notifier=None,
    config: Dict[str, Any] = None,
    logger: Optional[logging.Logger] = None,
    # NEW Phase 2:
    scoring_engine: ScoringEngine = None,
    position_sizer: PositionSizer = None,
    alert_service: AlertService = None,
):
```

### 3.2 Implement `_get_watchlist_positions()`

```python
def _get_watchlist_positions(self) -> List[Position]:
    """Get all State 0 positions from database."""
    session = self.db_session_factory()
    try:
        return session.query(Position).filter(Position.state == 0).all()
    finally:
        session.close()
```

### 3.3 Implement `_check_position()` with Full Logic

```python
def _check_position(self, pos: Position):
    """Check single position for breakout."""
    symbol = pos.symbol
    pivot = pos.pivot
    
    if not pivot or pivot <= 0:
        return
    
    # 1. Get current price from IBKR
    price_data = self.ibkr_client.get_price(symbol)
    if not price_data:
        return
    
    current_price = price_data.last
    volume = price_data.volume
    avg_volume = price_data.avg_volume or 500000
    
    # 2. Calculate distance from pivot
    distance_pct = ((current_price - pivot) / pivot) * 100
    
    # 3. Check breakout conditions
    above_pivot = current_price > pivot
    in_buy_zone = 0 <= distance_pct <= 5.0
    is_extended = distance_pct > 5.0
    volume_ratio = volume / avg_volume if avg_volume > 0 else 0
    has_volume = volume_ratio >= 1.0
    
    # 4. Determine alert type
    if above_pivot and in_buy_zone and has_volume:
        # Score the setup
        result = self.scoring_engine.score(
            pattern=pos.pattern or "Unknown",
            stage=pos.base_stage or "1",
            depth_pct=pos.base_depth or 20,
            length_weeks=pos.base_length or 7,
            rs_rating=pos.rs_rating
        )
        
        # Calculate sizing
        # ... (get account value from config)
        
        # Build context
        context = AlertContext(
            current_price=current_price,
            pivot_price=pivot,
            grade=result.grade,
            score=result.final_score,
            volume_ratio=volume_ratio,
            market_regime=self._get_market_regime()
        )
        
        # Determine subtype based on market
        if self._is_market_in_correction():
            subtype = AlertSubtype.SUPPRESSED
        else:
            subtype = AlertSubtype.CONFIRMED
        
        # Create alert
        self.alert_service.create_alert(
            symbol=symbol,
            alert_type=AlertType.BREAKOUT,
            subtype=subtype,
            context=context,
            position_id=pos.id,
            message=self._build_breakout_message(pos, result, current_price, volume_ratio),
            action=self._build_action_message(result, sizing),
            thread_source="breakout"
        )
    
    elif is_extended:
        # Alert but don't recommend entry
        self.alert_service.create_alert(
            symbol=symbol,
            alert_type=AlertType.BREAKOUT,
            subtype=AlertSubtype.EXTENDED,
            ...
        )
```

### 3.4 Wire Up in `service_main.py`

```python
# In service initialization:
from canslim_monitor.utils import ScoringEngine, PositionSizer
from canslim_monitor.services import AlertService

scoring_engine = ScoringEngine(config_path)
position_sizer = PositionSizer()
alert_service = AlertService(db_session_factory, discord_notifier)

breakout_thread = BreakoutThread(
    shutdown_event=shutdown_event,
    db_session_factory=db_session_factory,
    ibkr_client=ibkr_client,
    discord_notifier=discord_notifier,
    scoring_engine=scoring_engine,
    position_sizer=position_sizer,
    alert_service=alert_service,
)
```

---

## 4. Key Files Reference

### Source Files (CANSLIM Watch List Monitor)
- `/CANSLIM Watch List Monitor/monitor_v2.py` - Working breakout logic to port
- `/CANSLIM Watch List Monitor/scoring_engine.py` - Already copied
- `/CANSLIM Watch List Monitor/discord_notifier_v2.py` - Alert formatting reference

### Target Files (canslim_monitor)
- `/canslim_monitor/service/threads/breakout_thread.py` - **MODIFY THIS**
- `/canslim_monitor/service/service_main.py` - Wire up dependencies
- `/canslim_monitor/utils/scoring_engine.py` - Ready to use
- `/canslim_monitor/utils/position_sizer.py` - Ready to use
- `/canslim_monitor/services/alert_service.py` - Ready to use

### Database Models
- `Position` model in `/canslim_monitor/data/models.py` has all needed fields:
  - `state`, `symbol`, `pivot`, `pattern`, `base_stage`, `base_depth`, `base_length`
  - `rs_rating`, `eps_rating`, `ad_rating`, `ud_vol_ratio`

---

## 5. Discord Alert Format Target

```
🚀 NVDA - BREAKOUT CONFIRMED

NVDA broke out above $145.50 pivot with 2.3x average volume

Price: $147.25 (+1.2% from pivot)
Pivot: $145.50 | Buy Zone: $145.50 - $152.78

📊 SETUP QUALITY: A (Score: 18)
   Pattern: Cup w/Handle | Stage 2 | RS: 94

▶ ACTION: Buy 70 shares (50% initial position)
   Target Full Position: 140 shares
   Stop Loss: $135.52 (8% risk)

Market: CONFIRMED UPTREND
Time: 10:45:23 ET
```

---

## 6. Testing Plan

1. **Unit test** scoring engine with known setups
2. **Mock IBKR** to simulate price data
3. **Test alert service** sends to Discord (dry-run first)
4. **Run parallel** with existing TrendSpider for 2 weeks
5. **Measure parity** - target 95%+ match rate

---

## 7. Estimated Effort

| Task | Hours |
|------|-------|
| Update breakout_thread.py with full logic | 3 |
| Wire up dependencies in service_main.py | 1 |
| Add Discord message formatting | 1 |
| Testing with mock data | 2 |
| Integration testing with real IBKR | 1 |
| **Total** | **8** |

---

## 8. Quick Start for Next Session

```bash
# Extract the Phase 1 zip
unzip canslim_monitor_phase1.zip

# Files to work on:
# 1. canslim_monitor/service/threads/breakout_thread.py  <- Main implementation
# 2. canslim_monitor/service/service_main.py            <- Wire dependencies

# Reference files:
# - CANSLIM Watch List Monitor/monitor_v2.py (lines 469-700) <- Breakout logic
# - canslim_monitor/services/alert_service.py           <- How to create alerts
# - canslim_monitor/utils/scoring_engine.py             <- How to score setups
```

---

*End of Handoff Document*
