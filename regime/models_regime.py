"""
Market Regime Data Models

SQLAlchemy models for tracking distribution days, overnight trends,
and market regime alerts. Add these to your existing models.py or
import alongside it.

Usage:
    from models_regime import (
        DistributionDay, DistributionDayCount, 
        OvernightTrend, MarketRegimeAlert,
        RegimeType, TrendType
    )
"""

import enum
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, 
    Boolean, Enum, Index, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class RegimeType(enum.Enum):
    """Market regime classification."""
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


class TrendType(enum.Enum):
    """Overnight futures trend classification."""
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"


class DDayTrend(enum.Enum):
    """Distribution day trend direction."""
    IMPROVING = "IMPROVING"
    WORSENING = "WORSENING"
    FLAT = "FLAT"


class IBDMarketStatus(enum.Enum):
    """
    IBD's published market status from MarketSurge.
    
    This is the STRATEGIC layer - manually entered by user based on
    what IBD/MarketSurge publishes. Changes infrequently (every few weeks).
    """
    CONFIRMED_UPTREND = "CONFIRMED_UPTREND"
    UPTREND_UNDER_PRESSURE = "UPTREND_UNDER_PRESSURE"
    RALLY_ATTEMPT = "RALLY_ATTEMPT"
    CORRECTION = "CORRECTION"


class EntryRiskLevel(enum.Enum):
    """
    Today's entry risk level for new positions.
    
    This is the TACTICAL layer - calculated daily based on overnight
    futures, D-day trends, etc. Changes daily.
    
    LOW = Favorable for entries
    MODERATE = Acceptable, be selective
    ELEVATED = Caution warranted
    HIGH = Avoid new entries today
    """
    LOW = "LOW"
    MODERATE = "MODERATE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class DistributionDay(Base):
    """
    Tracks individual distribution days for SPY and QQQ.
    
    A distribution day occurs when:
    - Index closes DOWN >= 0.2% from prior close
    - Volume is HIGHER than prior day's volume
    
    Distribution days expire when:
    - 25 trading days have passed (TIME)
    - Index rallies 5%+ from the D-day close (RALLY)
    """
    __tablename__ = 'distribution_days'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False, index=True)  # SPY or QQQ
    date = Column(Date, nullable=False, index=True)
    close_price = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    pct_change = Column(Float, nullable=False)  # Day's % change
    expired = Column(Boolean, default=False)
    expiry_reason = Column(String(20))  # 'TIME' or 'RALLY'
    expiry_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('symbol', 'date', name='uix_dday_symbol_date'),
        Index('ix_active_ddays', 'symbol', 'expired', 'date'),
    )
    
    def __repr__(self):
        status = "EXPIRED" if self.expired else "ACTIVE"
        return f"<DistributionDay {self.symbol} {self.date} {self.pct_change:+.2f}% [{status}]>"


class DistributionDayCount(Base):
    """
    Daily snapshot of distribution day counts.
    
    Used for calculating the 5-day trend (improving/worsening).
    Stored daily to enable historical trend analysis.
    """
    __tablename__ = 'distribution_day_counts'
    
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    spy_count = Column(Integer, nullable=False)
    qqq_count = Column(Integer, nullable=False)
    spy_dates = Column(String(500))  # Comma-separated D-day dates for reference
    qqq_dates = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<DDayCount {self.date} SPY:{self.spy_count} QQQ:{self.qqq_count}>"


class DistributionDayOverride(Base):
    """
    Manual adjustments when IBD count differs from calculated.
    
    Sometimes our calculation may differ from IBD's official count
    due to data discrepancies or edge cases. This allows manual correction.
    """
    __tablename__ = 'distribution_day_overrides'
    
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    symbol = Column(String(10), nullable=False)
    adjustment = Column(Integer, nullable=False)  # +1, -1, or exact count if action='SET'
    action = Column(String(10), default='ADJUST')  # 'ADJUST' (+/-) or 'SET' (absolute)
    reason = Column(String(200))
    ibd_count = Column(Integer)  # What IBD showed, for reference
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_override_date_symbol', 'date', 'symbol'),
    )


class OvernightTrend(Base):
    """
    Daily overnight futures trend data.
    
    Captures futures movement from Globex session open (6 PM ET)
    to the alert capture time (default 8 AM ET).
    """
    __tablename__ = 'overnight_trends'
    
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    
    # E-mini S&P 500
    es_open = Column(Float)
    es_current = Column(Float)
    es_change_pct = Column(Float)
    es_regime = Column(Enum(TrendType))
    
    # E-mini Nasdaq 100
    nq_open = Column(Float)
    nq_current = Column(Float)
    nq_change_pct = Column(Float)
    nq_regime = Column(Enum(TrendType))
    
    # E-mini Dow
    ym_open = Column(Float)
    ym_current = Column(Float)
    ym_change_pct = Column(Float)
    ym_regime = Column(Enum(TrendType))
    
    captured_at = Column(DateTime, nullable=False)  # When data was captured
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<OvernightTrend {self.date} ES:{self.es_change_pct:+.2f}%>"


class MarketRegimeAlert(Base):
    """
    Historical log of morning regime alerts.
    
    Stores the complete regime calculation for each trading day,
    enabling historical analysis, backtesting, and trending reports.
    
    ALL DATA is logged here for future analysis:
    - Distribution day counts and individual dates
    - Overnight futures data
    - FTD/market phase status
    - Component scores for debugging
    - Regime trend vs prior day
    """
    __tablename__ = 'market_regime_alerts'
    
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    
    # Distribution day data
    spy_d_count = Column(Integer, nullable=False)
    qqq_d_count = Column(Integer, nullable=False)
    spy_5day_delta = Column(Integer)  # Change vs 5 days ago
    qqq_5day_delta = Column(Integer)
    d_day_trend = Column(Enum(DDayTrend))
    
    # D-day dates for histogram reconstruction (comma-separated ISO dates)
    spy_d_dates = Column(String(500))  # e.g., "2025-01-02,2025-01-05,2025-01-10"
    qqq_d_dates = Column(String(500))
    
    # Overnight futures data
    es_change_pct = Column(Float)
    nq_change_pct = Column(Float)
    ym_change_pct = Column(Float)
    es_open = Column(Float)  # Session open price
    es_close = Column(Float)  # Price at alert time
    nq_open = Column(Float)
    nq_close = Column(Float)
    ym_open = Column(Float)
    ym_close = Column(Float)
    
    # Scoring breakdown (for analysis/debugging)
    spy_d_score = Column(Float)
    qqq_d_score = Column(Float)
    trend_score = Column(Float)
    es_score = Column(Float)
    nq_score = Column(Float)
    ym_score = Column(Float)
    ftd_adjustment = Column(Float)  # FTD score contribution
    
    # FTD / Market Phase data
    market_phase = Column(String(30))  # CONFIRMED_UPTREND, RALLY_ATTEMPT, CORRECTION
    in_rally_attempt = Column(Boolean)
    rally_day = Column(Integer)  # Day of rally attempt (1, 2, 3, 4+)
    has_confirmed_ftd = Column(Boolean)
    ftd_date = Column(Date)  # Most recent FTD date
    days_since_ftd = Column(Integer)
    
    # Final regime
    composite_score = Column(Float, nullable=False)
    regime = Column(Enum(RegimeType), nullable=False)
    
    # Trend vs prior day
    prior_regime = Column(Enum(RegimeType))
    prior_score = Column(Float)
    regime_changed = Column(Boolean, default=False)
    
    # NEW: IBD Published Exposure (manual input from MarketSurge)
    # This is the STRATEGIC layer - what IBD says the overall market posture should be
    ibd_market_status = Column(Enum(IBDMarketStatus))  # CONFIRMED_UPTREND, etc.
    ibd_exposure_min = Column(Integer)  # e.g., 80
    ibd_exposure_max = Column(Integer)  # e.g., 100
    ibd_exposure_updated_at = Column(DateTime)  # When user last updated IBD exposure
    
    # NEW: Today's Entry Risk (calculated daily)
    # This is the TACTICAL layer - whether today is good for new entries
    entry_risk_level = Column(Enum(EntryRiskLevel))  # LOW, MODERATE, ELEVATED, HIGH
    entry_risk_score = Column(Float)  # Raw score (-1.5 to +1.5, positive = favorable)
    
    # Alert status
    alert_sent = Column(Boolean, default=False)
    alert_sent_at = Column(DateTime)
    alert_channel = Column(String(50))  # 'discord', 'email', etc.
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<RegimeAlert {self.date} {self.regime.value} ({self.composite_score:+.2f})>"
    
    def get_spy_dates(self) -> list:
        """Parse SPY D-day dates from stored string."""
        if not self.spy_d_dates:
            return []
        return [date.fromisoformat(d) for d in self.spy_d_dates.split(',') if d]
    
    def get_qqq_dates(self) -> list:
        """Parse QQQ D-day dates from stored string."""
        if not self.qqq_d_dates:
            return []
        return [date.fromisoformat(d) for d in self.qqq_d_dates.split(',') if d]


class IBDExposureHistory(Base):
    """
    Tracks changes to IBD published exposure for post-mortem analysis.
    
    New record created each time user updates the IBD exposure setting.
    This enables historical analysis of:
    - How IBD exposure changes correlated with market tops/bottoms
    - Whether being more/less aggressive than IBD helped or hurt
    - Timing of market status changes vs actual price action
    """
    __tablename__ = 'ibd_exposure_history'
    
    id = Column(Integer, primary_key=True)
    effective_date = Column(Date, nullable=False, index=True)  # Date this exposure became active
    market_status = Column(Enum(IBDMarketStatus), nullable=False)  # CONFIRMED_UPTREND, etc.
    exposure_min = Column(Integer, nullable=False)  # 0, 20, 40, 80
    exposure_max = Column(Integer, nullable=False)  # 20, 40, 80, 100
    distribution_days_spy = Column(Integer)  # D-days at time of change
    distribution_days_qqq = Column(Integer)
    notes = Column(String(500))  # Optional user notes explaining the change
    source = Column(String(50), default='MarketSurge')  # Where the user saw this
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_ibd_exposure_effective', 'effective_date'),
    )
    
    def __repr__(self):
        return f"<IBDExposure {self.effective_date} {self.market_status.value} {self.exposure_min}-{self.exposure_max}%>"
    
    @property
    def exposure_range(self) -> str:
        """Return exposure as string like '80-100%'."""
        return f"{self.exposure_min}-{self.exposure_max}%"


class IBDExposureCurrent(Base):
    """
    Singleton table to store the current IBD exposure setting.
    
    Only one row should exist (id=1). Updated when user changes
    the IBD exposure in the GUI. History is tracked in IBDExposureHistory.
    """
    __tablename__ = 'ibd_exposure_current'
    
    id = Column(Integer, primary_key=True)  # Always 1
    market_status = Column(Enum(IBDMarketStatus), nullable=False, 
                          default=IBDMarketStatus.CONFIRMED_UPTREND)
    exposure_min = Column(Integer, nullable=False, default=80)
    exposure_max = Column(Integer, nullable=False, default=100)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(50), default='user')  # 'user' or 'system'
    notes = Column(String(500))
    
    def __repr__(self):
        return f"<IBDExposureCurrent {self.market_status.value} {self.exposure_min}-{self.exposure_max}%>"
    
    @property
    def exposure_range(self) -> str:
        """Return exposure as string like '80-100%'."""
        return f"{self.exposure_min}-{self.exposure_max}%"
    
    @classmethod
    def get_default_exposure(cls, status: IBDMarketStatus) -> tuple:
        """Get default exposure range for a market status."""
        defaults = {
            IBDMarketStatus.CONFIRMED_UPTREND: (80, 100),
            IBDMarketStatus.UPTREND_UNDER_PRESSURE: (40, 80),
            IBDMarketStatus.RALLY_ATTEMPT: (20, 40),
            IBDMarketStatus.CORRECTION: (0, 20),
        }
        return defaults.get(status, (40, 60))


# Migration helper - run this to create tables
def create_regime_tables(engine):
    """
    Create all regime-related tables.
    
    Usage:
        from sqlalchemy import create_engine
        from models_regime import create_regime_tables
        
        engine = create_engine('sqlite:///canslim_monitor.db')
        create_regime_tables(engine)
    """
    Base.metadata.create_all(engine)
    print("Created regime tables:")
    for table in Base.metadata.tables:
        print(f"  - {table}")
