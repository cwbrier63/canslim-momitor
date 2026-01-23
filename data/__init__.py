"""
CANSLIM Monitor - Data Access Layer
Phase 1: Database Foundation

Provides database connection management, ORM models, and repositories.
"""

from canslim_monitor.data.database import (
    DatabaseManager,
    get_database,
    init_database
)
from canslim_monitor.data.models import (
    Base,
    Position,
    Alert,
    DailySnapshot,
    Outcome,
    LearnedWeights,
    MarketRegime,
    Config
)
from canslim_monitor.data.repositories import (
    RepositoryManager,
    PositionRepository,
    AlertRepository,
    SnapshotRepository,
    OutcomeRepository,
    MarketRegimeRepository,
    ConfigRepository,
    LearnedWeightsRepository
)

__all__ = [
    # Database
    'DatabaseManager',
    'get_database',
    'init_database',
    
    # Models
    'Base',
    'Position',
    'Alert',
    'DailySnapshot',
    'Outcome',
    'LearnedWeights',
    'MarketRegime',
    'Config',
    
    # Repositories
    'RepositoryManager',
    'PositionRepository',
    'AlertRepository',
    'SnapshotRepository',
    'OutcomeRepository',
    'MarketRegimeRepository',
    'ConfigRepository',
    'LearnedWeightsRepository',
]
