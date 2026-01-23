"""
CANSLIM Monitor - Utilities
Phase 1 & 2: Database Foundation & Service Architecture

Provides utility functions for logging, configuration, market calendar, and calculations.
Includes scoring engine, position sizing, and health calculation.
"""

from canslim_monitor.utils.logging import (
    setup_logging,
    get_logger,
    shutdown_logging,
    get_service_logger,
    get_breakout_logger,
    get_position_logger,
    get_market_logger,
    get_ibkr_logger,
    get_discord_logger,
    get_sheets_logger,
    get_database_logger,
    get_gui_logger,
    LoggingManager
)
from canslim_monitor.utils.market_calendar import MarketCalendar, get_market_calendar, init_market_calendar
from canslim_monitor.utils.config import (
    load_config,
    get_config,
    get_ibkr_config,
    get_ibkr_client_id,
    get_service_config,
    get_discord_config
)

# New Phase 1 modules
from canslim_monitor.utils.scoring_engine import (
    ScoringEngine,
    ScoringResult,
    ScoreComponent,
    ExecutionRiskResult
)
from canslim_monitor.utils.position_sizer import (
    PositionSizer,
    PositionSizeResult,
    ProfitExitResult,
    PositionPhase,
    ExitPhase
)
from canslim_monitor.utils.health_calculator import (
    HealthCalculator,
    HealthResult,
    HealthWarning,
    HealthRating,
    EightWeekHoldChecker
)

__all__ = [
    # Logging
    'setup_logging',
    'get_logger',
    'shutdown_logging',
    'get_service_logger',
    'get_breakout_logger',
    'get_position_logger',
    'get_market_logger',
    'get_ibkr_logger',
    'get_discord_logger',
    'get_sheets_logger',
    'get_database_logger',
    'get_gui_logger',
    'LoggingManager',
    # Market Calendar
    'MarketCalendar',
    'get_market_calendar',
    'init_market_calendar',
    # Config
    'load_config',
    'get_config',
    'get_ibkr_config',
    'get_ibkr_client_id',
    'get_service_config',
    'get_discord_config',
    # Scoring Engine (Phase 1)
    'ScoringEngine',
    'ScoringResult',
    'ScoreComponent',
    'ExecutionRiskResult',
    # Position Sizer (Phase 1)
    'PositionSizer',
    'PositionSizeResult',
    'ProfitExitResult',
    'PositionPhase',
    'ExitPhase',
    # Health Calculator (Phase 1)
    'HealthCalculator',
    'HealthResult',
    'HealthWarning',
    'HealthRating',
    'EightWeekHoldChecker',
]
