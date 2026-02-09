"""
CANSLIM Monitor - Weight Manager

Manages learned weight sets: storage, activation, versioning,
and integration with the scoring system.
"""

import json
import logging
from datetime import datetime, date
from typing import Dict, Optional, List, Any
from dataclasses import dataclass

from canslim_monitor.data.repositories.learning_repo import LearningRepository
from canslim_monitor.data.models import LearnedWeights

logger = logging.getLogger('canslim.learning.weights')


@dataclass
class WeightSet:
    """Represents a set of scoring weights."""
    id: int
    version: int
    weights: Dict[str, float]
    is_active: bool

    # Performance metrics
    accuracy: Optional[float] = None
    f1_score: Optional[float] = None
    improvement_pct: Optional[float] = None

    # Training info
    sample_size: int = 0
    training_start: Optional[date] = None
    training_end: Optional[date] = None

    # Metadata
    created_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    notes: Optional[str] = None


# Default weights (from existing scoring system)
DEFAULT_WEIGHTS = {
    # CANSLIM Ratings (total: 50)
    'rs_rating': 15,       # High RS = strong relative strength
    'eps_rating': 10,      # Earnings growth
    'comp_rating': 10,     # Overall composite
    'ad_rating': 5,        # Accumulation/Distribution
    'industry_rank': 5,    # Leading industry
    'fund_count': 5,       # Institutional sponsorship

    # Base Characteristics (total: 30)
    'base_stage': 15,      # Early stage preferred
    'base_depth': 10,      # Shallow base preferred
    'base_length': 5,      # Not too short, not too long

    # Market Context (total: 20)
    'market_regime': 10,   # Bullish market bonus
    'funds_qtr_chg': 5,    # Increasing sponsorship
    'breakout_volume': 5,  # Volume confirmation
}


class WeightManager:
    """
    Manages scoring weight sets.

    Handles:
    - Loading active/candidate weights
    - Weight versioning
    - Activation/deactivation
    - Weight comparison
    - Default weight fallback
    """

    def __init__(self, repo: LearningRepository):
        self.repo = repo
        self._cached_weights: Optional[WeightSet] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minute cache

    def get_active_weights(self, force_refresh: bool = False) -> WeightSet:
        """
        Get the currently active weights.

        Falls back to default weights if none are active.

        Args:
            force_refresh: Bypass cache

        Returns:
            Active WeightSet
        """
        # Check cache
        if not force_refresh and self._cached_weights and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds()
            if elapsed < self._cache_ttl_seconds:
                return self._cached_weights

        # Load from database
        active = self.repo.get_active_weights()

        if active:
            weight_set = self._model_to_weightset(active)
            logger.debug(f"Loaded active weights v{weight_set.version}")
        else:
            # Use defaults
            weight_set = WeightSet(
                id=0,
                version=0,
                weights=DEFAULT_WEIGHTS.copy(),
                is_active=True,
                notes="Default weights"
            )
            logger.debug("Using default weights (no active learned weights)")

        # Update cache
        self._cached_weights = weight_set
        self._cache_time = datetime.now()

        return weight_set

    def get_weights_by_id(self, weights_id: int) -> Optional[WeightSet]:
        """Get a specific weight set by ID."""
        if weights_id == 0:
            return WeightSet(
                id=0,
                version=0,
                weights=DEFAULT_WEIGHTS.copy(),
                is_active=False,
                notes="Default weights"
            )

        learned = self.repo.get_weights_by_id(weights_id)
        if learned:
            return self._model_to_weightset(learned)
        return None

    def get_all_weights(self, limit: int = 20) -> List[WeightSet]:
        """Get all weight sets, most recent first."""
        all_weights = self.repo.get_all_weights(limit=limit)

        weight_sets = [self._model_to_weightset(w) for w in all_weights]

        # Add default as option
        default = WeightSet(
            id=0,
            version=0,
            weights=DEFAULT_WEIGHTS.copy(),
            is_active=not any(w.is_active for w in weight_sets),
            notes="Default baseline weights"
        )
        weight_sets.append(default)

        return weight_sets

    def activate_weights(self, weights_id: int) -> bool:
        """
        Activate a specific weight set.

        Args:
            weights_id: ID of weights to activate (0 for default)

        Returns:
            True if successful
        """
        if weights_id == 0:
            # Deactivate all learned weights to use defaults
            active = self.repo.get_active_weights()
            if active:
                active.is_active = False
                active.deactivated_at = datetime.now()
            logger.info("Activated default weights")
            self._invalidate_cache()
            return True

        success = self.repo.activate_weights(weights_id)
        if success:
            self._invalidate_cache()
            logger.info(f"Activated weights id={weights_id}")

        return success

    def compare_weights(
        self,
        weights_a: WeightSet,
        weights_b: WeightSet
    ) -> Dict[str, Any]:
        """
        Compare two weight sets.

        Returns:
            Dictionary with comparison results
        """
        comparison = {
            'a': {'id': weights_a.id, 'version': weights_a.version},
            'b': {'id': weights_b.id, 'version': weights_b.version},
            'differences': [],
            'summary': {}
        }

        all_factors = set(weights_a.weights.keys()) | set(weights_b.weights.keys())

        total_diff = 0
        for factor in sorted(all_factors):
            val_a = weights_a.weights.get(factor, 0)
            val_b = weights_b.weights.get(factor, 0)

            diff = val_b - val_a
            pct_change = (diff / val_a * 100) if val_a > 0 else 0

            comparison['differences'].append({
                'factor': factor,
                'weight_a': val_a,
                'weight_b': val_b,
                'difference': diff,
                'pct_change': pct_change
            })

            total_diff += abs(diff)

        # Calculate similarity
        comparison['summary'] = {
            'total_absolute_difference': total_diff,
            'similarity_pct': max(0, 100 - total_diff),
            'factors_changed': len([d for d in comparison['differences'] if d['difference'] != 0]),
            'performance_improvement': None
        }

        # Add performance comparison if available
        if weights_a.accuracy and weights_b.accuracy:
            comparison['summary']['performance_improvement'] = (
                (weights_b.accuracy - weights_a.accuracy) / weights_a.accuracy * 100
            )

        return comparison

    def create_variant(
        self,
        base_weights_id: int,
        modifications: Dict[str, float],
        notes: str = None
    ) -> int:
        """
        Create a new weight set as a variant of existing weights.

        Args:
            base_weights_id: ID of weights to base on
            modifications: Factor weights to change
            notes: Optional notes

        Returns:
            ID of created weights
        """
        base = self.get_weights_by_id(base_weights_id)
        if not base:
            raise ValueError(f"Base weights {base_weights_id} not found")

        # Apply modifications
        new_weights = base.weights.copy()
        new_weights.update(modifications)

        # Normalize to sum to 100
        total = sum(new_weights.values())
        if total > 0:
            for key in new_weights:
                new_weights[key] = new_weights[key] / total * 100

        # Create via repo
        learned = self.repo.create_weights(
            weights=new_weights,
            factor_analysis={},
            metrics={},
            sample_size=0,
            training_start=date.today(),
            training_end=date.today(),
            parent_weights_id=base_weights_id if base_weights_id > 0 else None,
            notes=notes or f"Variant of weights v{base.version}"
        )

        logger.info(f"Created weight variant id={learned.id} from base={base_weights_id}")
        return learned.id

    def get_scoring_weights(self) -> Dict[str, float]:
        """
        Get weights formatted for the scoring system.

        This is the main interface for the scoring module.

        Returns:
            Dictionary of factor weights
        """
        active = self.get_active_weights()
        return active.weights.copy()

    def is_using_learned_weights(self) -> bool:
        """Check if currently using learned (vs default) weights."""
        active = self.get_active_weights()
        return active.id > 0

    def get_weight_for_factor(self, factor_name: str) -> float:
        """Get the weight for a specific factor."""
        weights = self.get_scoring_weights()
        return weights.get(factor_name, 0)

    def get_default_weights(self) -> Dict[str, float]:
        """Get the default baseline weights."""
        return DEFAULT_WEIGHTS.copy()

    def _model_to_weightset(self, model: LearnedWeights) -> WeightSet:
        """Convert LearnedWeights model to WeightSet dataclass."""
        weights = json.loads(model.weights) if model.weights else {}

        return WeightSet(
            id=model.id,
            version=model.version or 1,
            weights=weights,
            is_active=model.is_active,
            accuracy=model.accuracy,
            f1_score=model.f1_score,
            improvement_pct=model.improvement_pct,
            sample_size=model.sample_size or 0,
            training_start=model.training_start,
            training_end=model.training_end,
            created_at=model.created_at,
            activated_at=model.activated_at,
            notes=model.notes
        )

    def _invalidate_cache(self):
        """Invalidate the weights cache."""
        self._cached_weights = None
        self._cache_time = None

    def generate_report(self) -> str:
        """Generate a report on current weights status."""
        lines = []
        lines.append("=" * 60)
        lines.append("WEIGHT MANAGER STATUS")
        lines.append("=" * 60)

        active = self.get_active_weights()
        lines.append(f"Active Weights: v{active.version} (id={active.id})")

        if active.id > 0:
            lines.append(f"  Accuracy: {active.accuracy:.1%}" if active.accuracy else "  Accuracy: N/A")
            lines.append(f"  F1 Score: {active.f1_score:.3f}" if active.f1_score else "  F1 Score: N/A")
            lines.append(f"  Sample Size: {active.sample_size}")
            if active.activated_at:
                lines.append(f"  Activated: {active.activated_at.strftime('%Y-%m-%d %H:%M')}")
        else:
            lines.append("  Using default baseline weights")

        lines.append("")
        lines.append("CURRENT WEIGHTS:")
        lines.append("-" * 40)

        sorted_weights = sorted(active.weights.items(), key=lambda x: x[1], reverse=True)
        for factor, weight in sorted_weights:
            bar = "#" * int(weight / 2)
            lines.append(f"  {factor:20} {weight:5.1f}  {bar}")

        # Show all versions
        all_weights = self.get_all_weights(limit=5)
        lines.append("")
        lines.append("RECENT VERSIONS:")
        lines.append("-" * 40)
        for ws in all_weights[:5]:
            status = "ACTIVE" if ws.is_active else "      "
            acc = f"{ws.accuracy:.1%}" if ws.accuracy else "N/A"
            lines.append(f"  v{ws.version:3d} (id={ws.id:3d}) {status}  acc={acc}")

        return "\n".join(lines)
