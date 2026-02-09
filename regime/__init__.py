"""
CANSLIM Monitor - Market Regime Subsystem

Ported from standalone MarketRegime-MonitorSystem.
Provides comprehensive market regime analysis based on IBD methodology.

Components:
- distribution_tracker: Distribution day detection and tracking
- ftd_tracker: Follow-Through Day detection and rally attempt tracking
- market_regime: Regime calculation with weighted scoring
- models_regime: Database models for regime data
- historical_data: Data fetching from Polygon/Massive API
- discord_regime: Discord alert formatting

Usage:
    from canslim_monitor.regime import (
        DistributionDayTracker,
        FollowThroughDayTracker,
        MarketRegimeCalculator,
        RegimeType
    )
"""

from .models_regime import (
    RegimeType,
    TrendType,
    DDayTrend,
    IBDMarketStatus,
    EntryRiskLevel,
    DistributionDay,
    DistributionDayCount,
    DistributionDayOverride,
    OvernightTrend,
    MarketRegimeAlert,
    IBDExposureHistory,
    IBDExposureCurrent,
    create_regime_tables
)

from .distribution_tracker import (
    DistributionDayTracker,
    DistributionType,
    DistributionDayResult,
    CombinedDistributionData
)

from .market_regime import (
    MarketRegimeCalculator,
    DistributionData,
    OvernightData,
    FTDData,
    RegimeScore,
    create_overnight_data,
    calculate_entry_risk_score,
    score_to_entry_risk_level,
    get_entry_risk_emoji,
    get_entry_risk_description
)

from .ftd_tracker import (
    FollowThroughDayTracker,
    MarketPhase,
    RallyAttempt,
    FollowThroughDay,
    RallyStatus,
    MarketPhaseStatus,
    RallyHistogram
)

from .historical_data import (
    DailyBar,
    MassiveHistoricalClient,
    TradingCalendar,
    fetch_spy_qqq_daily,
    fetch_index_daily
)

from .fear_greed_client import (
    FearGreedClient,
    FearGreedData,
    FearGreedHistoryPoint,
    classify_score
)

__all__ = [
    # Enums
    'RegimeType',
    'TrendType',
    'DDayTrend',
    'IBDMarketStatus',
    'EntryRiskLevel',
    'MarketPhase',
    'DistributionType',
    
    # Models
    'DistributionDay',
    'DistributionDayCount',
    'DistributionDayOverride',
    'OvernightTrend',
    'MarketRegimeAlert',
    'IBDExposureHistory',
    'IBDExposureCurrent',
    'RallyAttempt',
    'FollowThroughDay',
    
    # Data classes
    'DailyBar',
    'DistributionData',
    'OvernightData',
    'FTDData',
    'RegimeScore',
    'DistributionDayResult',
    'CombinedDistributionData',
    'RallyStatus',
    'MarketPhaseStatus',
    'RallyHistogram',
    
    # Trackers/Calculators
    'DistributionDayTracker',
    'FollowThroughDayTracker',
    'MarketRegimeCalculator',
    'MassiveHistoricalClient',
    'TradingCalendar',
    
    # Fear & Greed
    'FearGreedClient',
    'FearGreedData',
    'FearGreedHistoryPoint',
    'classify_score',

    # Functions
    'create_regime_tables',
    'create_overnight_data',
    'fetch_spy_qqq_daily',
    'fetch_index_daily',
]
