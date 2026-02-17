"""
CANSLIM Monitor - Repository Layer
Phase 1: Database Foundation

Provides data access abstractions for all database entities.
"""

from canslim_monitor.data.repositories.position_repo import PositionRepository
from canslim_monitor.data.repositories.alert_repo import AlertRepository
from canslim_monitor.data.repositories.snapshot_outcome_repo import SnapshotRepository, OutcomeRepository
from canslim_monitor.data.repositories.market_config_repo import (
    MarketRegimeRepository,
    ConfigRepository,
    LearnedWeightsRepository
)
from canslim_monitor.data.repositories.history_repo import HistoryRepository
from canslim_monitor.data.repositories.learning_repo import LearningRepository
from canslim_monitor.data.repositories.provider_repo import ProviderRepository

__all__ = [
    'PositionRepository',
    'AlertRepository',
    'SnapshotRepository',
    'OutcomeRepository',
    'MarketRegimeRepository',
    'ConfigRepository',
    'LearnedWeightsRepository',
    'HistoryRepository',
    'LearningRepository',
    'ProviderRepository',
]


class RepositoryManager:
    """
    Factory class for managing repository instances.
    Provides a single point of access to all repositories.
    """
    
    def __init__(self, session):
        """
        Initialize repository manager with a database session.
        
        Args:
            session: SQLAlchemy session instance
        """
        self._session = session
        self._repos = {}
    
    @property
    def positions(self) -> PositionRepository:
        """Get Position repository."""
        if 'positions' not in self._repos:
            self._repos['positions'] = PositionRepository(self._session)
        return self._repos['positions']
    
    @property
    def alerts(self) -> AlertRepository:
        """Get Alert repository."""
        if 'alerts' not in self._repos:
            self._repos['alerts'] = AlertRepository(self._session)
        return self._repos['alerts']
    
    @property
    def snapshots(self) -> SnapshotRepository:
        """Get Snapshot repository."""
        if 'snapshots' not in self._repos:
            self._repos['snapshots'] = SnapshotRepository(self._session)
        return self._repos['snapshots']
    
    @property
    def outcomes(self) -> OutcomeRepository:
        """Get Outcome repository."""
        if 'outcomes' not in self._repos:
            self._repos['outcomes'] = OutcomeRepository(self._session)
        return self._repos['outcomes']
    
    @property
    def market_regime(self) -> MarketRegimeRepository:
        """Get MarketRegime repository."""
        if 'market_regime' not in self._repos:
            self._repos['market_regime'] = MarketRegimeRepository(self._session)
        return self._repos['market_regime']
    
    @property
    def config(self) -> ConfigRepository:
        """Get Config repository."""
        if 'config' not in self._repos:
            self._repos['config'] = ConfigRepository(self._session)
        return self._repos['config']
    
    @property
    def learned_weights(self) -> LearnedWeightsRepository:
        """Get LearnedWeights repository."""
        if 'learned_weights' not in self._repos:
            self._repos['learned_weights'] = LearnedWeightsRepository(self._session)
        return self._repos['learned_weights']

    @property
    def history(self) -> HistoryRepository:
        """Get PositionHistory repository."""
        if 'history' not in self._repos:
            self._repos['history'] = HistoryRepository(self._session)
        return self._repos['history']

    @property
    def learning(self) -> LearningRepository:
        """Get Learning repository."""
        if 'learning' not in self._repos:
            self._repos['learning'] = LearningRepository(self._session)
        return self._repos['learning']

    @property
    def providers(self) -> ProviderRepository:
        """Get Provider repository."""
        if 'providers' not in self._repos:
            self._repos['providers'] = ProviderRepository(self._session)
        return self._repos['providers']
