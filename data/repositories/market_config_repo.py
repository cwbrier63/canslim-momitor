"""
CANSLIM Monitor - MarketRegime and Config Repositories
Phase 1: Database Foundation

Provides CRUD operations for MarketRegime and Config entities.
"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from canslim_monitor.data.models import MarketRegime, Config, LearnedWeights


class MarketRegimeRepository:
    """Repository for MarketRegime entity operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== CREATE ====================
    
    def create(self, **kwargs) -> MarketRegime:
        """Create a new market regime record."""
        regime = MarketRegime(**kwargs)
        self.session.add(regime)
        self.session.flush()
        return regime
    
    def create_daily_regime(
        self,
        regime_date: date,
        regime: str,
        regime_score: int,
        distribution_days: Dict[str, int] = None,
        ftd_data: Dict[str, Any] = None,
        index_data: Dict[str, float] = None,
        breadth_data: Dict[str, Any] = None,
        recommended_exposure: int = None,
        **kwargs
    ) -> MarketRegime:
        """
        Create a daily market regime record with structured data.
        
        Args:
            regime_date: Date of analysis
            regime: Classification (BULLISH, NEUTRAL, BEARISH)
            regime_score: Score from -100 to +100
            distribution_days: Dict with spy, qqq, total
            ftd_data: Dict with active, date, days_since
            index_data: Dict with spy_close, spy_50ma, spy_200ma, qqq_close
            breadth_data: Dict with advance_decline, new_highs, new_lows
            recommended_exposure: Exposure level 1-5
            **kwargs: Additional attributes
        
        Returns:
            Created MarketRegime instance
        """
        data = {
            'regime_date': regime_date,
            'regime': regime,
            'regime_score': regime_score,
            'recommended_exposure': recommended_exposure or 3,
        }
        
        if distribution_days:
            data.update({
                'distribution_days_spy': distribution_days.get('spy'),
                'distribution_days_qqq': distribution_days.get('qqq'),
                'distribution_days_total': distribution_days.get('total'),
            })
        
        if ftd_data:
            data.update({
                'ftd_active': ftd_data.get('active'),
                'ftd_date': ftd_data.get('date'),
                'days_since_ftd': ftd_data.get('days_since'),
            })
        
        if index_data:
            data.update({
                'spy_close': index_data.get('spy_close'),
                'spy_50ma': index_data.get('spy_50ma'),
                'spy_200ma': index_data.get('spy_200ma'),
                'qqq_close': index_data.get('qqq_close'),
            })
        
        if breadth_data:
            data.update({
                'advance_decline': breadth_data.get('advance_decline'),
                'new_highs': breadth_data.get('new_highs'),
                'new_lows': breadth_data.get('new_lows'),
            })
        
        data.update(kwargs)
        return self.create(**data)
    
    # ==================== READ ====================
    
    def get_by_date(self, regime_date: date) -> Optional[MarketRegime]:
        """Get market regime for a specific date."""
        return self.session.query(MarketRegime).filter(
            MarketRegime.regime_date == regime_date
        ).first()
    
    def get_latest(self) -> Optional[MarketRegime]:
        """Get most recent market regime."""
        return self.session.query(MarketRegime).order_by(
            desc(MarketRegime.regime_date)
        ).first()
    
    def get_current(self) -> Optional[MarketRegime]:
        """Get today's market regime (or most recent)."""
        today = date.today()
        regime = self.get_by_date(today)
        
        if not regime:
            regime = self.get_latest()
        
        return regime
    
    def get_range(
        self,
        start_date: date,
        end_date: date = None
    ) -> List[MarketRegime]:
        """Get market regimes for a date range."""
        end_date = end_date or date.today()
        
        return self.session.query(MarketRegime).filter(
            MarketRegime.regime_date >= start_date,
            MarketRegime.regime_date <= end_date
        ).order_by(MarketRegime.regime_date).all()
    
    def get_recent(self, days: int = 30) -> List[MarketRegime]:
        """Get recent market regimes."""
        start_date = date.today() - timedelta(days=days)
        return self.get_range(start_date)
    
    def get_distribution_day_count(self, as_of_date: date = None) -> Dict[str, int]:
        """
        Get current distribution day count.
        
        Args:
            as_of_date: Date to check (defaults to today)
        
        Returns:
            Dict with spy, qqq, total counts
        """
        regime = self.get_by_date(as_of_date or date.today())
        
        if not regime:
            regime = self.get_latest()
        
        if not regime:
            return {'spy': 0, 'qqq': 0, 'total': 0}
        
        return {
            'spy': regime.distribution_days_spy or 0,
            'qqq': regime.distribution_days_qqq or 0,
            'total': regime.distribution_days_total or 0,
        }
    
    def get_ftd_status(self, as_of_date: date = None) -> Dict[str, Any]:
        """
        Get follow-through day status.
        
        Returns:
            Dict with active, date, days_since
        """
        regime = self.get_by_date(as_of_date or date.today())
        
        if not regime:
            regime = self.get_latest()
        
        if not regime:
            return {'active': False, 'date': None, 'days_since': None}
        
        return {
            'active': regime.ftd_active or False,
            'date': regime.ftd_date,
            'days_since': regime.days_since_ftd,
        }
    
    # ==================== UPDATE ====================
    
    def update(self, instance: MarketRegime, **kwargs) -> MarketRegime:
        """Update market regime attributes."""
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        self.session.flush()
        return instance
    
    def upsert(self, regime_date: date, **kwargs) -> MarketRegime:
        """Update existing regime or create new one."""
        existing = self.get_by_date(regime_date)
        
        if existing:
            return self.update(existing, **kwargs)
        else:
            return self.create(regime_date=regime_date, **kwargs)
    
    # ==================== DELETE ====================
    
    def delete_old(self, days: int = 365) -> int:
        """Delete regimes older than specified days."""
        cutoff = date.today() - timedelta(days=days)
        
        deleted = self.session.query(MarketRegime).filter(
            MarketRegime.regime_date < cutoff
        ).delete(synchronize_session=False)
        
        self.session.flush()
        return deleted
    
    # ==================== ANALYTICS ====================
    
    def get_regime_distribution(
        self,
        start_date: date = None,
        end_date: date = None
    ) -> Dict[str, int]:
        """Get distribution of regime classifications."""
        query = self.session.query(
            MarketRegime.regime,
            func.count(MarketRegime.id).label('count')
        )
        
        if start_date:
            query = query.filter(MarketRegime.regime_date >= start_date)
        if end_date:
            query = query.filter(MarketRegime.regime_date <= end_date)
        
        results = query.group_by(MarketRegime.regime).all()
        
        return {row.regime: row.count for row in results if row.regime}


class ConfigRepository:
    """Repository for Config entity operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== READ ====================
    
    def get(self, key: str) -> Optional[str]:
        """Get config value by key (as string)."""
        config = self.session.query(Config).filter_by(key=key).first()
        return config.value if config else None
    
    def get_typed(self, key: str, default: Any = None) -> Any:
        """Get config value with proper type conversion."""
        config = self.session.query(Config).filter_by(key=key).first()
        
        if not config:
            return default
        
        return config.get_typed_value()
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Get config value as integer."""
        value = self.get_typed(key)
        return int(value) if value is not None else default
    
    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get config value as float."""
        value = self.get_typed(key)
        return float(value) if value is not None else default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get config value as boolean."""
        value = self.get_typed(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes')
    
    def get_by_category(self, category: str) -> Dict[str, Any]:
        """Get all config values for a category."""
        configs = self.session.query(Config).filter_by(category=category).all()
        
        return {c.key: c.get_typed_value() for c in configs}
    
    def get_all(self) -> Dict[str, Any]:
        """Get all config values."""
        configs = self.session.query(Config).all()
        return {c.key: c.get_typed_value() for c in configs}
    
    # ==================== UPDATE ====================
    
    def set(
        self,
        key: str,
        value: Any,
        value_type: str = None,
        category: str = None,
        description: str = None
    ) -> Config:
        """
        Set a config value (creates if not exists).
        
        Args:
            key: Config key
            value: Config value (will be converted to string)
            value_type: Type hint (string, integer, float, boolean, json)
            category: Config category
            description: Config description
        
        Returns:
            Config instance
        """
        config = self.session.query(Config).filter_by(key=key).first()
        
        # Convert value to string for storage
        if isinstance(value, bool):
            str_value = 'true' if value else 'false'
            value_type = value_type or 'boolean'
        elif isinstance(value, dict) or isinstance(value, list):
            import json
            str_value = json.dumps(value)
            value_type = value_type or 'json'
        else:
            str_value = str(value)
        
        if config:
            config.value = str_value
            if value_type:
                config.value_type = value_type
            if category:
                config.category = category
            if description:
                config.description = description
        else:
            config = Config(
                key=key,
                value=str_value,
                value_type=value_type or 'string',
                category=category or 'general',
                description=description
            )
            self.session.add(config)
        
        self.session.flush()
        return config
    
    def set_many(self, values: Dict[str, Any], category: str = None) -> int:
        """
        Set multiple config values.
        
        Args:
            values: Dict of key -> value
            category: Optional category for all values
        
        Returns:
            Number of values set
        """
        count = 0
        for key, value in values.items():
            self.set(key, value, category=category)
            count += 1
        return count
    
    # ==================== DELETE ====================
    
    def delete(self, key: str) -> bool:
        """Delete a config value."""
        deleted = self.session.query(Config).filter_by(key=key).delete()
        self.session.flush()
        return deleted > 0


class LearnedWeightsRepository:
    """Repository for LearnedWeights entity operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== CREATE ====================
    
    def create(self, **kwargs) -> LearnedWeights:
        """Create a new learned weights record."""
        weights = LearnedWeights(**kwargs)
        self.session.add(weights)
        self.session.flush()
        return weights
    
    # ==================== READ ====================
    
    def get_by_id(self, weights_id: int) -> Optional[LearnedWeights]:
        """Get weights by ID."""
        return self.session.query(LearnedWeights).filter_by(id=weights_id).first()
    
    def get_active(self) -> Optional[LearnedWeights]:
        """Get currently active weights."""
        return self.session.query(LearnedWeights).filter(
            LearnedWeights.is_active == True
        ).first()
    
    def get_latest(self) -> Optional[LearnedWeights]:
        """Get most recently created weights."""
        return self.session.query(LearnedWeights).order_by(
            desc(LearnedWeights.created_at)
        ).first()
    
    def get_all(self, limit: int = None) -> List[LearnedWeights]:
        """Get all weight records."""
        query = self.session.query(LearnedWeights).order_by(
            desc(LearnedWeights.created_at)
        )
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def get_weights_dict(self) -> Optional[Dict[str, float]]:
        """
        Get active weights as a dictionary.
        
        Returns:
            Dict of factor -> weight or None if no active weights
        """
        active = self.get_active()
        if not active or not active.weights:
            return None
        
        import json
        return json.loads(active.weights)
    
    # ==================== UPDATE ====================
    
    def update(self, weights: LearnedWeights, **kwargs) -> LearnedWeights:
        """Update weights attributes."""
        for key, value in kwargs.items():
            if hasattr(weights, key):
                setattr(weights, key, value)
        
        self.session.flush()
        return weights
    
    def activate(self, weights: LearnedWeights) -> LearnedWeights:
        """
        Activate a weights record (deactivates any currently active).
        """
        # Deactivate current active
        self.session.query(LearnedWeights).filter(
            LearnedWeights.is_active == True
        ).update({
            'is_active': False,
            'deactivated_at': datetime.now()
        })
        
        # Activate new weights
        weights.is_active = True
        weights.activated_at = datetime.now()
        
        self.session.flush()
        return weights
    
    def deactivate(self, weights: LearnedWeights) -> LearnedWeights:
        """Deactivate a weights record."""
        weights.is_active = False
        weights.deactivated_at = datetime.now()
        
        self.session.flush()
        return weights
    
    # ==================== DELETE ====================
    
    def delete(self, weights: LearnedWeights) -> None:
        """Delete a weights record."""
        self.session.delete(weights)
        self.session.flush()
    
    def delete_old(self, keep: int = 10) -> int:
        """
        Delete old weight records, keeping the most recent.
        
        Args:
            keep: Number of recent records to keep
        
        Returns:
            Number of records deleted
        """
        # Get IDs to keep
        keep_ids = [w.id for w in self.session.query(LearnedWeights).order_by(
            desc(LearnedWeights.created_at)
        ).limit(keep).all()]
        
        # Also keep active
        active = self.get_active()
        if active and active.id not in keep_ids:
            keep_ids.append(active.id)
        
        # Delete the rest
        deleted = self.session.query(LearnedWeights).filter(
            ~LearnedWeights.id.in_(keep_ids)
        ).delete(synchronize_session=False)
        
        self.session.flush()
        return deleted
