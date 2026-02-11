"""
CANSLIM Monitor - SQLAlchemy ORM Models
Database Foundation - Phase 1

All tables defined according to the Unified Monitor Implementation Plan v1.0
"""

from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Float, Text, Date, DateTime, Boolean,
    ForeignKey, Index, UniqueConstraint, create_engine, event
)
from sqlalchemy.orm import declarative_base, relationship, Session
from sqlalchemy.sql import func

Base = declarative_base()


class Position(Base):
    """
    Primary table for tracking watchlist items and active positions.
    State transitions: 0 (WATCHING) -> 1-3 (IN POSITION) -> 4-5 (TAKING PROFITS) -> -1/-2 (CLOSED/STOPPED)
    """
    __tablename__ = 'positions'
    
    # Identity
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    portfolio = Column(String(20), default='CWB')  # CWB, SKB, etc.
    
    # State Management
    state = Column(Integer, default=0, index=True)  # -2 to 6 (matches V36)
    state_updated_at = Column(DateTime)
    
    # Setup Data (from MarketSurge)
    pattern = Column(String(50))  # Cup w/Handle, Flat Base, etc.
    pivot = Column(Float)
    
    # Pivot Tracking (for stale pivot detection)
    pivot_set_date = Column(Date)  # When pivot was set/last changed
    pivot_distance_pct = Column(Float)  # Current % distance from pivot (updated each cycle)
    pivot_status = Column(String(15))  # FRESH, AGING, STALE, EXTENDED
    
    # Dates
    watch_date = Column(Date)
    entry_date = Column(Date)
    breakout_date = Column(Date)  # For 8-week rule
    
    # Multi-Tranche Entries
    e1_shares = Column(Integer, default=0)
    e1_price = Column(Float)
    e1_date = Column(Date)
    e2_shares = Column(Integer, default=0)
    e2_price = Column(Float)
    e2_date = Column(Date)
    e3_shares = Column(Integer, default=0)
    e3_price = Column(Float)
    e3_date = Column(Date)
    
    # Partial Exits
    tp1_sold = Column(Integer, default=0)
    tp1_price = Column(Float)
    tp1_date = Column(Date)
    tp2_sold = Column(Integer, default=0)
    tp2_price = Column(Float)
    tp2_date = Column(Date)

    # Full Position Close (for state -1/-2)
    close_price = Column(Float)
    close_date = Column(Date)
    close_reason = Column(String(30))  # STOP_HIT, TP_HIT, MANUAL, 50MA_BREAKDOWN, etc.
    realized_pnl = Column(Float)       # Dollar P&L
    realized_pnl_pct = Column(Float)   # Percentage P&L

    # State -1.5 (WATCHING_EXITED) - Re-entry monitoring fields
    original_pivot = Column(Float)           # Preserved pivot for retest detection
    ma_test_count = Column(Integer, default=0)  # Track # of MA bounces (max 3)
    watching_exited_since = Column(DateTime)    # When entered State -1.5

    # Pyramid Flags
    py1_done = Column(Boolean, default=False)
    py2_done = Column(Boolean, default=False)

    # 8-Week Hold Rule
    eight_week_hold_active = Column(Boolean, default=False)
    eight_week_hold_start = Column(Date)
    eight_week_hold_end = Column(Date)
    eight_week_power_move_pct = Column(Float)
    eight_week_power_move_weeks = Column(Float)
    
    # CANSLIM Factors (MarketSurge data - Left Panel)
    rs_rating = Column(Integer)
    rs_3mo = Column(Integer)                    # NEW: 3-month RS rating
    rs_6mo = Column(Integer)                    # NEW: 6-month RS rating
    eps_rating = Column(Integer)
    comp_rating = Column(Integer)
    smr_rating = Column(String(1))              # NEW: Sales/Margin/ROE: A-E
    ad_rating = Column(String(2))               # A+, A, A-, B+, etc. (expanded from 1 char)
    ud_vol_ratio = Column(Float)
    group_rank = Column(Integer)                # DEPRECATED: Use industry_rank instead
    fund_count = Column(Integer)
    prior_fund_count = Column(Integer)          # Prior quarter fund count (for calculating funds_qtr_chg)

    # Industry & Sector Data (MarketSurge - Industry Panel)
    industry_rank = Column(Integer)             # NEW: 1-197 ranking (replaces group_rank)
    industry_stock_count = Column(Integer)      # NEW: Stocks in industry group
    industry_eps_rank = Column(String(10))      # NEW: "3 of 38" format
    industry_rs_rank = Column(String(10))       # NEW: "10 of 38" format
    
    # Institutional Data (MarketSurge - Owners Panel)
    funds_qtr_chg = Column(Integer)             # NEW: Change vs prior quarter
    ibd_fund_count = Column(Integer)            # NEW: IBD Mutual Fund Index holdings
    
    # Base Characteristics (MarketSurge - Pattern Rec Panel)
    base_stage = Column(String(10))  # '2b(3)' format
    base_depth = Column(Float)
    base_length = Column(Integer)
    prior_uptrend = Column(Float)
    breakout_vol_pct = Column(Float)            # NEW: Volume % on breakout day
    breakout_price_pct = Column(Float)          # NEW: Price % on breakout day
    
    # Market Context at Entry (for ML training)
    entry_market_exposure = Column(String(15))  # NEW: IBD exposure level at entry
    entry_dist_days = Column(Integer)           # NEW: Distribution day count at entry
    
    # Risk Parameters
    hard_stop_pct = Column(Float, default=7.0)
    tp1_pct = Column(Float, default=20.0)
    tp2_pct = Column(Float, default=30.0)
    earnings_date = Column(Date)
    
    # Calculated Fields (updated by service)
    total_shares = Column(Integer)
    avg_cost = Column(Float)
    stop_price = Column(Float)
    tp1_target = Column(Float)
    tp2_target = Column(Float)
    pyramid1_price = Column(Float)
    pyramid2_price = Column(Float)
    max_extension_price = Column(Float)
    
    # Current State (updated real-time)
    last_price = Column(Float)
    last_price_time = Column(DateTime)
    current_pnl_pct = Column(Float)
    health_score = Column(Integer)
    health_rating = Column(String(10))
    
    # Volume Data (from Polygon/Massive - updated daily)
    avg_volume_50d = Column(Integer)  # 50-day average volume
    volume_updated_at = Column(DateTime)  # When volume data was last updated
    
    # Scoring (at entry)
    entry_grade = Column(String(2))
    entry_score = Column(Integer)
    entry_score_details = Column(Text)  # JSON
    
    # Sync Tracking
    sheet_row_id = Column(String(50))  # For Google Sheets sync
    last_sheet_sync = Column(DateTime)
    needs_sheet_sync = Column(Boolean, default=True)
    
    # Metadata
    notes = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    alerts = relationship("Alert", back_populates="position", cascade="all, delete-orphan")
    snapshots = relationship("DailySnapshot", back_populates="position", cascade="all, delete-orphan")
    outcome = relationship("Outcome", back_populates="position", uselist=False)
    history = relationship("PositionHistory", back_populates="position", cascade="all, delete-orphan",
                          order_by="desc(PositionHistory.changed_at)")

    __table_args__ = (
        UniqueConstraint('symbol', 'portfolio', name='uq_symbol_portfolio'),
        Index('idx_positions_portfolio', 'portfolio'),
        Index('idx_positions_needs_sync', 'needs_sheet_sync'),
    )
    
    def __repr__(self):
        return f"<Position(symbol='{self.symbol}', state={self.state}, pivot={self.pivot})>"
    
    @property
    def is_watching(self) -> bool:
        return self.state == 0
    
    @property
    def is_in_position(self) -> bool:
        return self.state >= 1
    
    @property
    def is_closed(self) -> bool:
        return self.state < 0


# Fields to track for position history (all editable fields)
TRACKED_FIELDS = {
    # Setup & Identity
    'symbol', 'portfolio', 'pattern', 'pivot', 'stop_price',
    'hard_stop_pct', 'tp1_pct', 'tp2_pct',
    # State & Lifecycle
    'state', 'watch_date', 'entry_date', 'breakout_date', 'earnings_date',
    # Position Management
    'e1_shares', 'e1_price', 'e1_date',
    'e2_shares', 'e2_price', 'e2_date',
    'e3_shares', 'e3_price', 'e3_date',
    'tp1_sold', 'tp1_price', 'tp1_date',
    'tp2_sold', 'tp2_price', 'tp2_date',
    'total_shares', 'avg_cost',
    # CANSLIM Ratings
    'rs_rating', 'rs_3mo', 'rs_6mo', 'eps_rating', 'comp_rating',
    'smr_rating', 'ad_rating', 'ud_vol_ratio',
    'industry_rank', 'fund_count', 'prior_fund_count', 'funds_qtr_chg',
    # Base Characteristics
    'base_stage', 'base_depth', 'base_length', 'prior_uptrend',
    'breakout_vol_pct', 'breakout_price_pct',
    # Exit Info
    'close_price', 'close_date', 'close_reason',
    'realized_pnl', 'realized_pnl_pct',
    # State -1.5 fields
    'original_pivot', 'ma_test_count',
    # Scoring & Notes
    'entry_grade', 'entry_score', 'notes',
    # Pyramid flags
    'py1_done', 'py2_done',
    # 8-week hold
    'eight_week_hold_active', 'eight_week_hold_start', 'eight_week_hold_end',
    # Targets (when manually set)
    'tp1_target', 'tp2_target',
}


class PositionHistory(Base):
    """
    Tracks changes to position fields over time.
    Stores the old and new values with timestamp and source.
    """
    __tablename__ = 'position_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey('positions.id', ondelete='CASCADE'), nullable=False)

    # When the change happened
    changed_at = Column(DateTime, default=func.now(), nullable=False, index=True)

    # What triggered the change
    change_source = Column(String(30))  # 'manual_edit', 'state_transition', 'system_calc', 'price_update'

    # The field that changed
    field_name = Column(String(50), nullable=False, index=True)

    # Values (stored as strings for flexibility)
    old_value = Column(String(500))
    new_value = Column(String(500))

    # Relationship
    position = relationship("Position", back_populates="history")

    __table_args__ = (
        Index('idx_position_history_lookup', 'position_id', 'field_name'),
        Index('idx_position_history_recent', 'position_id', 'changed_at'),
    )

    def __repr__(self):
        return f"<PositionHistory(position_id={self.position_id}, field='{self.field_name}', changed_at='{self.changed_at}')>"


class Alert(Base):
    """
    All generated alerts (breakout, position, stop, etc.)
    Captures full context at alert time for learning and analysis.
    """
    __tablename__ = 'alerts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey('positions.id'))
    symbol = Column(String(10), nullable=False, index=True)
    
    # Alert Details
    alert_time = Column(DateTime, nullable=False, index=True)
    alert_type = Column(String(20), nullable=False, index=True)
    alert_subtype = Column(String(30))  # For categorization
    price = Column(Float)
    
    # Alert Content (for display and ML learning)
    message = Column(Text)  # Full formatted message with all context
    action = Column(String(100))  # Recommended action (SELL, HOLD, etc.)
    
    # Acknowledgment Status
    acknowledged = Column(Boolean, default=False, index=True)
    acknowledged_at = Column(DateTime)
    
    # Context at Alert Time
    state_at_alert = Column(Integer)
    pivot_at_alert = Column(Float)
    avg_cost_at_alert = Column(Float)
    pnl_pct_at_alert = Column(Float)
    
    # Technical Context
    ma50 = Column(Float)
    ma21 = Column(Float)
    ma200 = Column(Float)
    volume_ratio = Column(Float)
    
    # Health at Alert
    health_score = Column(Integer)
    health_rating = Column(String(10))
    
    # Market Context
    market_regime = Column(String(10))
    spy_price = Column(Float)
    
    # MarketSurge Context at Alert Time (NEW - for ML training)
    industry_rank_at_alert = Column(Integer)    # NEW: 1-197 ranking
    rs_3mo_at_alert = Column(Integer)           # NEW: 3-month RS
    rs_6mo_at_alert = Column(Integer)           # NEW: 6-month RS
    fund_count_at_alert = Column(Integer)       # NEW: Fund count
    funds_qtr_chg_at_alert = Column(Integer)    # NEW: Quarterly change
    breakout_vol_pct = Column(Float)            # NEW: Breakout volume %
    breakout_price_pct = Column(Float)          # NEW: Breakout price %
    market_exposure_at_alert = Column(String(15))  # NEW: IBD exposure level
    dist_days_at_alert = Column(Integer)        # NEW: Distribution day count
    
    # Scoring (for breakout alerts)
    canslim_grade = Column(String(2))
    canslim_score = Column(Integer)
    static_score = Column(Integer)
    dynamic_score = Column(Integer)
    score_details = Column(Text)  # JSON
    
    # Execution Risk (for breakout alerts)
    exec_verdict = Column(String(20))
    adv = Column(Float)  # Average Daily Volume
    spread_pct = Column(Float)
    est_slippage = Column(Float)
    
    # Delivery
    discord_channel = Column(String(50))
    discord_sent = Column(Boolean, default=False)
    discord_message_id = Column(String(30))
    discord_sent_at = Column(DateTime)
    
    # User Response (for learning)
    user_action = Column(String(10))  # TRADED, PASSED, IGNORED
    user_action_time = Column(DateTime)
    
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    position = relationship("Position", back_populates="alerts")
    
    __table_args__ = (
        Index('idx_alerts_position', 'position_id'),
        Index('idx_alerts_unacknowledged', 'acknowledged', 'position_id'),
    )
    
    def __repr__(self):
        return f"<Alert(symbol='{self.symbol}', type='{self.alert_type}', time='{self.alert_time}')>"


class DailySnapshot(Base):
    """
    Daily snapshots of position performance.
    Used for tracking running statistics and learning.
    """
    __tablename__ = 'daily_snapshots'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey('positions.id'), nullable=False)
    symbol = Column(String(10), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    
    # OHLCV
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(Integer)
    
    # Position Metrics
    avg_cost = Column(Float)
    total_shares = Column(Integer)
    pnl_pct = Column(Float)
    gain_from_pivot = Column(Float)
    
    # Running Statistics (for learning)
    max_gain_to_date = Column(Float)
    max_drawdown_to_date = Column(Float)
    days_in_position = Column(Integer)
    
    # Technical Indicators
    ma50 = Column(Float)
    ma21 = Column(Float)
    ma200 = Column(Float)
    above_50ma = Column(Boolean)
    above_21ema = Column(Boolean)
    above_200ma = Column(Boolean)
    
    # Volume Analysis
    volume_sma50 = Column(Float)
    volume_ratio = Column(Float)
    
    # Health
    health_score = Column(Integer)
    
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    position = relationship("Position", back_populates="snapshots")
    
    __table_args__ = (
        UniqueConstraint('position_id', 'snapshot_date', name='uq_position_snapshot_date'),
        Index('idx_snapshots_position_date', 'position_id', 'snapshot_date'),
        Index('idx_snapshots_symbol_date', 'symbol', 'snapshot_date'),
    )
    
    def __repr__(self):
        return f"<DailySnapshot(symbol='{self.symbol}', date='{self.snapshot_date}', close={self.close_price})>"


class Outcome(Base):
    """
    Closed positions with complete entry/exit data.
    Primary source for learning engine analysis.
    """
    __tablename__ = 'outcomes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey('positions.id'), unique=True)
    symbol = Column(String(10), nullable=False, index=True)
    portfolio = Column(String(20))
    
    # Entry Context (snapshot at entry for learning)
    entry_date = Column(Date, index=True)
    entry_price = Column(Float)
    entry_shares = Column(Integer)
    entry_grade = Column(String(2), index=True)
    entry_score = Column(Integer)
    
    # CANSLIM Factors at Entry
    rs_at_entry = Column(Integer)
    eps_at_entry = Column(Integer)
    comp_at_entry = Column(Integer)
    ad_at_entry = Column(String(1))
    stage_at_entry = Column(String(10))
    pattern = Column(String(50))
    base_depth_at_entry = Column(Float)
    base_length_at_entry = Column(Integer)
    
    # MarketSurge v2 Factors at Entry (NEW - for ML training)
    industry_rank_at_entry = Column(Integer)    # NEW: 1-197 ranking
    rs_3mo_at_entry = Column(Integer)           # NEW: 3-month RS
    rs_6mo_at_entry = Column(Integer)           # NEW: 6-month RS
    fund_count_at_entry = Column(Integer)       # NEW: Fund count
    funds_qtr_chg_at_entry = Column(Integer)    # NEW: Quarterly change
    ibd_fund_count_at_entry = Column(Integer)   # NEW: IBD elite fund count
    breakout_vol_pct = Column(Float)            # NEW: Breakout volume %
    breakout_price_pct = Column(Float)          # NEW: Breakout price %
    
    # Market Context at Entry
    market_regime_at_entry = Column(String(10))
    spy_at_entry = Column(Float)
    market_exposure_at_entry = Column(String(15))  # NEW: IBD exposure level
    dist_days_at_entry = Column(Integer)           # NEW: Distribution day count
    
    # Exit Data
    exit_date = Column(Date)
    exit_price = Column(Float)
    exit_shares = Column(Integer)
    exit_reason = Column(String(30))  # STOP_HIT, TP1, TP2, MANUAL, 50MA_BREAKDOWN, etc.
    
    # Results
    holding_days = Column(Integer)
    gross_pnl = Column(Float)
    gross_pct = Column(Float)
    
    # Risk Metrics (from snapshots)
    max_gain_pct = Column(Float)
    max_drawdown_pct = Column(Float)
    days_to_max_gain = Column(Integer)
    hit_stop = Column(Boolean)
    
    # Relative Performance
    spy_entry_price = Column(Float)
    spy_exit_price = Column(Float)
    spy_return = Column(Float)
    relative_return = Column(Float)
    
    # Classification (for learning)
    outcome = Column(String(10), index=True)  # SUCCESS, PARTIAL, STOPPED, FAILED
    outcome_score = Column(Integer)  # Numeric for regression
    
    # Validation
    validated = Column(Boolean, default=False)
    tradesviz_matched = Column(Boolean, default=False)
    tradesviz_trade_id = Column(String(50))
    validation_notes = Column(Text)

    # Source tracking
    source = Column(String(20), default='live')  # 'live', 'swingtrader', 'manual', 'backtest'

    created_at = Column(DateTime, default=func.now())

    # Relationships
    position = relationship("Position", back_populates="outcome")

    def __repr__(self):
        return f"<Outcome(symbol='{self.symbol}', outcome='{self.outcome}', gross_pct={self.gross_pct})>"


class LearnedWeights(Base):
    """
    Stores learned scoring weights from outcome analysis.
    Supports A/B testing with is_active flag.
    """
    __tablename__ = 'learned_weights'

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now(), index=True)

    # Versioning (for tracking weight evolution)
    version = Column(Integer, default=1)
    parent_weights_id = Column(Integer, ForeignKey('learned_weights.id'))

    # Training Period
    sample_size = Column(Integer)
    training_start = Column(Date)
    training_end = Column(Date)

    # Factor Weights (JSON)
    weights = Column(Text)  # {"rs_rating": 0.25, "stage": -0.20, ...}

    # Individual Factor Analysis (JSON)
    factor_analysis = Column(Text)  # Per-factor correlation and success rates

    # Performance Metrics
    accuracy = Column(Float)
    precision_score = Column(Float)
    recall_score = Column(Float)
    f1_score = Column(Float)

    # Comparison to Baseline
    baseline_accuracy = Column(Float)
    improvement_pct = Column(Float)

    # Confidence
    confidence_level = Column(Float)  # Based on sample size

    # Status
    is_active = Column(Boolean, default=False, index=True)
    activated_at = Column(DateTime)
    deactivated_at = Column(DateTime)

    # A/B Test Association
    ab_test_id = Column(Integer)

    # Notes
    notes = Column(Text)

    def __repr__(self):
        return f"<LearnedWeights(id={self.id}, accuracy={self.accuracy}, active={self.is_active})>"


class MarketRegime(Base):
    """
    Daily market analysis including distribution days,
    follow-through days, and regime classification.
    """
    __tablename__ = 'market_regime'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    regime_date = Column(Date, nullable=False, unique=True, index=True)
    
    # Classification
    regime = Column(String(10))  # BULLISH, NEUTRAL, BEARISH
    regime_score = Column(Integer)  # -100 to +100
    
    # Distribution Day Tracking
    distribution_days_spy = Column(Integer)
    distribution_days_qqq = Column(Integer)
    distribution_days_total = Column(Integer)
    
    # Follow-Through Day
    ftd_active = Column(Boolean)
    ftd_date = Column(Date)
    days_since_ftd = Column(Integer)
    
    # Index Levels
    spy_close = Column(Float)
    spy_50ma = Column(Float)
    spy_200ma = Column(Float)
    qqq_close = Column(Float)
    
    # Breadth Indicators
    advance_decline = Column(Float)
    new_highs = Column(Integer)
    new_lows = Column(Integer)
    
    # Overnight/Pre-market
    futures_change_pct = Column(Float)
    
    # Exposure Recommendation
    recommended_exposure = Column(Integer)  # 1-5
    
    created_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f"<MarketRegime(date='{self.regime_date}', regime='{self.regime}', score={self.regime_score})>"


class HistoricalBar(Base):
    """
    Daily OHLCV bars for volume analysis.
    Used to calculate 50-day average volume for breakout confirmation.
    Data sourced from Polygon.io / Massive API (1-day delayed).
    """
    __tablename__ = 'historical_bars'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    bar_date = Column(Date, nullable=False, index=True)
    
    # OHLCV data
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    
    # Additional metrics (optional)
    vwap = Column(Float)  # Volume-weighted average price
    transactions = Column(Integer)  # Number of transactions
    
    created_at = Column(DateTime, default=func.now())
    
    __table_args__ = (
        UniqueConstraint('symbol', 'bar_date', name='uq_symbol_bar_date'),
        Index('idx_historical_bars_symbol_date', 'symbol', 'bar_date'),
    )
    
    def __repr__(self):
        return f"<HistoricalBar(symbol='{self.symbol}', date='{self.bar_date}', volume={self.volume})>"


class Config(Base):
    """
    System configuration stored in database.
    Supports different value types and categories.
    """
    __tablename__ = 'config'
    
    key = Column(String(100), primary_key=True)
    value = Column(Text)
    value_type = Column(String(20))  # string, integer, float, boolean, json
    category = Column(String(20), index=True)  # service, alerts, scoring, gui
    description = Column(Text)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Config(key='{self.key}', value='{self.value}')>"
    
    def get_typed_value(self):
        """Return the value converted to its proper type."""
        if self.value is None:
            return None
        
        if self.value_type == 'integer':
            return int(self.value)
        elif self.value_type == 'float':
            return float(self.value)
        elif self.value_type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes')
        elif self.value_type == 'json':
            import json
            return json.loads(self.value)
        else:
            return self.value


class ABTest(Base):
    """
    A/B test configuration for comparing weight sets.
    """
    __tablename__ = 'ab_tests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # Test configuration
    control_weights_id = Column(Integer, ForeignKey('learned_weights.id'))
    treatment_weights_id = Column(Integer, ForeignKey('learned_weights.id'))
    split_ratio = Column(Float, default=0.5)

    # Status
    status = Column(String(20), default='draft', index=True)  # draft, running, completed, cancelled
    started_at = Column(DateTime)
    ended_at = Column(DateTime)

    # Sample tracking
    min_sample_size = Column(Integer, default=30)
    control_count = Column(Integer, default=0)
    treatment_count = Column(Integer, default=0)

    # Results
    control_win_rate = Column(Float)
    treatment_win_rate = Column(Float)
    control_avg_return = Column(Float)
    treatment_avg_return = Column(Float)
    p_value = Column(Float)
    is_significant = Column(Boolean, default=False)

    # Winner selection
    winner = Column(String(20))
    winner_selected_at = Column(DateTime)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ABTest(id={self.id}, name='{self.name}', status='{self.status}')>"


class ABTestAssignment(Base):
    """
    Position assignment to A/B test group.
    """
    __tablename__ = 'ab_test_assignments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ab_test_id = Column(Integer, ForeignKey('ab_tests.id', ondelete='CASCADE'), nullable=False)
    position_id = Column(Integer, ForeignKey('positions.id', ondelete='CASCADE'), nullable=False)

    # Assignment
    group_name = Column(String(20), nullable=False)  # 'control' or 'treatment'
    weights_id = Column(Integer, ForeignKey('learned_weights.id'), nullable=False)
    assigned_at = Column(DateTime, default=func.now())

    # Score at assignment
    score_at_assignment = Column(Integer)
    grade_at_assignment = Column(String(2))

    # Outcome (updated when position closes)
    outcome = Column(String(20))
    return_pct = Column(Float)
    holding_days = Column(Integer)
    outcome_recorded_at = Column(DateTime)

    __table_args__ = (
        Index('idx_ab_assignments_test', 'ab_test_id', 'group_name'),
        Index('idx_ab_assignments_position', 'position_id'),
    )

    def __repr__(self):
        return f"<ABTestAssignment(id={self.id}, test={self.ab_test_id}, group='{self.group_name}')>"


class FactorCorrelation(Base):
    """
    Stores factor correlation analysis results.
    """
    __tablename__ = 'factor_correlations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_date = Column(Date, nullable=False, index=True)

    # Analysis period
    sample_start_date = Column(Date)
    sample_end_date = Column(Date)
    sample_size = Column(Integer)

    # Factor being analyzed
    factor_name = Column(String(50), nullable=False, index=True)
    factor_type = Column(String(20))

    # Correlation metrics
    correlation_return = Column(Float)
    correlation_win_rate = Column(Float)
    p_value_return = Column(Float)
    p_value_win_rate = Column(Float)

    # Success rate by bucket
    low_bucket_win_rate = Column(Float)
    mid_bucket_win_rate = Column(Float)
    high_bucket_win_rate = Column(Float)

    # Averages
    low_bucket_avg_return = Column(Float)
    mid_bucket_avg_return = Column(Float)
    high_bucket_avg_return = Column(Float)

    # Statistical significance
    is_significant = Column(Boolean, default=False)
    recommended_direction = Column(String(10))  # 'higher', 'lower', 'none'

    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index('idx_factor_correlations_date', 'analysis_date', 'factor_name'),
    )

    def __repr__(self):
        return f"<FactorCorrelation(factor='{self.factor_name}', r={self.correlation_return})>"


# Default configuration entries
DEFAULT_CONFIG = [
    ('service.poll_interval_breakout', '60', 'integer', 'service', 'Breakout thread poll interval (seconds)'),
    ('service.poll_interval_position', '30', 'integer', 'service', 'Position thread poll interval (seconds)'),
    ('service.poll_interval_market', '300', 'integer', 'service', 'Market thread poll interval (seconds)'),
    ('service.market_hours_only', 'true', 'boolean', 'service', 'Only run during market hours'),
    ('service.market_open', '09:30', 'string', 'service', 'Market open time (ET)'),
    ('service.market_close', '16:00', 'string', 'service', 'Market close time (ET)'),
    ('service.timezone', 'America/New_York', 'string', 'service', 'Timezone for market hours'),
    ('alerts.discord_webhook_breakout', '', 'string', 'alerts', 'Discord webhook for breakout alerts'),
    ('alerts.discord_webhook_position', '', 'string', 'alerts', 'Discord webhook for position alerts'),
    ('alerts.discord_webhook_market', '', 'string', 'alerts', 'Discord webhook for market alerts'),
    ('alerts.discord_webhook_system', '', 'string', 'alerts', 'Discord webhook for system alerts'),
    ('alerts.cooldown_minutes', '60', 'integer', 'alerts', 'Alert cooldown period'),
    ('scoring.rs_floor', '70', 'integer', 'scoring', 'RS Rating floor for grade cap'),
    ('scoring.use_learned_weights', 'false', 'boolean', 'scoring', 'Use ML-derived weights'),
    ('ibkr.host', '127.0.0.1', 'string', 'ibkr', 'IBKR TWS host'),
    ('ibkr.port', '7497', 'integer', 'ibkr', 'IBKR TWS port'),
    ('ibkr.client_id', '10', 'integer', 'ibkr', 'IBKR client ID'),
    ('sheets.enabled', 'true', 'boolean', 'sheets', 'Enable Google Sheets sync'),
    ('sheets.sync_interval', '300', 'integer', 'sheets', 'Sheets sync interval (seconds)'),
    ('sheets.spreadsheet_id', '', 'string', 'sheets', 'Google Sheets spreadsheet ID'),
    ('database.backup_interval', '86400', 'integer', 'database', 'Backup interval (seconds)'),
    ('database.backup_retain', '7', 'integer', 'database', 'Number of backups to retain'),
]


def seed_default_config(session: Session):
    """Seed the database with default configuration values."""
    for key, value, value_type, category, description in DEFAULT_CONFIG:
        existing = session.query(Config).filter_by(key=key).first()
        if not existing:
            session.add(Config(
                key=key,
                value=value,
                value_type=value_type,
                category=category,
                description=description
            ))
    session.commit()
