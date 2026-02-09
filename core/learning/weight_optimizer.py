"""
CANSLIM Monitor - Weight Optimizer

Optimizes scoring weights based on factor analysis and outcome data.
Uses gradient-free optimization to find weights that maximize predictive power.
"""

import logging
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import date

from canslim_monitor.data.repositories.learning_repo import (
    LearningRepository, OutcomeData
)
from .factor_analyzer import FactorAnalysis, ANALYZABLE_FACTORS

logger = logging.getLogger('canslim.learning.optimizer')


@dataclass
class OptimizationResult:
    """Results of weight optimization."""
    weights: Dict[str, float]
    metrics: Dict[str, float]
    factor_analysis: Dict[str, Any]

    # Performance metrics
    accuracy: float  # % of correct win/loss predictions
    precision: float  # % of predicted wins that were wins
    recall: float  # % of actual wins predicted
    f1_score: float

    # Comparison to baseline
    baseline_accuracy: float
    improvement_pct: float

    # Training info
    sample_size: int
    training_start: date
    training_end: date
    iterations: int


# Default weights (from existing scoring system)
DEFAULT_WEIGHTS = {
    'rs_rating': 15,
    'eps_rating': 10,
    'comp_rating': 10,
    'industry_rank': 10,
    'fund_count': 5,
    'funds_qtr_chg': 5,
    'ad_rating': 5,
    'base_stage': 15,
    'base_depth': 10,
    'base_length': 5,
    'market_regime': 10,
}


class WeightOptimizer:
    """
    Optimizes scoring weights using outcome data.

    Uses a simple evolutionary strategy:
    1. Start with baseline weights
    2. Mutate weights randomly
    3. Evaluate fitness (accuracy/F1)
    4. Keep best performing weights
    5. Repeat
    """

    def __init__(self, repo: LearningRepository):
        self.repo = repo
        self._outcomes: List[OutcomeData] = []
        self._train_set: List[OutcomeData] = []
        self._test_set: List[OutcomeData] = []

    def load_data(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        test_split: float = 0.2
    ) -> int:
        """
        Load and split outcome data for training.

        Args:
            min_date: Minimum entry date
            max_date: Maximum entry date
            test_split: Fraction of data for testing

        Returns:
            Total number of outcomes loaded
        """
        self._outcomes = self.repo.get_outcomes_for_training(
            min_date=min_date,
            max_date=max_date,
            min_holding_days=1
        )

        if not self._outcomes:
            logger.warning("No outcomes loaded")
            return 0

        # Shuffle for random split
        shuffled = self._outcomes.copy()
        random.shuffle(shuffled)

        # Split into train/test
        split_idx = int(len(shuffled) * (1 - test_split))
        self._train_set = shuffled[:split_idx]
        self._test_set = shuffled[split_idx:]

        logger.info(
            f"Loaded {len(self._outcomes)} outcomes: "
            f"{len(self._train_set)} train, {len(self._test_set)} test"
        )

        return len(self._outcomes)

    def optimize(
        self,
        initial_weights: Dict[str, float] = None,
        factor_analyses: List[FactorAnalysis] = None,
        iterations: int = 100,
        population_size: int = 20,
        mutation_rate: float = 0.3,
        mutation_strength: float = 0.2
    ) -> OptimizationResult:
        """
        Optimize weights using evolutionary strategy.

        Args:
            initial_weights: Starting weights (defaults to DEFAULT_WEIGHTS)
            factor_analyses: Factor analysis results to guide optimization
            iterations: Number of optimization iterations
            population_size: Size of weight population
            mutation_rate: Probability of mutating each weight
            mutation_strength: Magnitude of mutations

        Returns:
            OptimizationResult with optimized weights
        """
        if not self._train_set:
            raise ValueError("No training data loaded - call load_data() first")

        if initial_weights is None:
            initial_weights = DEFAULT_WEIGHTS.copy()

        # Calculate baseline accuracy
        baseline_accuracy = self._evaluate_weights(initial_weights, self._train_set)['accuracy']
        logger.info(f"Baseline accuracy: {baseline_accuracy:.1%}")

        # Initialize population
        population = [initial_weights.copy()]

        # Add variations based on factor analysis
        if factor_analyses:
            for analysis in factor_analyses[:5]:  # Top 5 significant factors
                if analysis.is_significant:
                    variation = initial_weights.copy()
                    factor = analysis.factor_name
                    if factor in variation:
                        # Boost weight based on correlation strength
                        boost = 1 + abs(analysis.correlation_return)
                        variation[factor] *= boost
                        population.append(variation)

        # Fill population with random mutations
        while len(population) < population_size:
            mutated = self._mutate_weights(
                initial_weights,
                mutation_rate=0.5,
                mutation_strength=0.3
            )
            population.append(mutated)

        # Evolution loop
        best_weights = initial_weights.copy()
        best_fitness = baseline_accuracy

        for iteration in range(iterations):
            # Evaluate fitness
            fitness_scores = []
            for weights in population:
                metrics = self._evaluate_weights(weights, self._train_set)
                # Use F1 score as fitness (balances precision and recall)
                fitness = metrics['f1_score']
                fitness_scores.append((fitness, weights))

            # Sort by fitness
            fitness_scores.sort(key=lambda x: x[0], reverse=True)

            # Update best
            if fitness_scores[0][0] > best_fitness:
                best_fitness = fitness_scores[0][0]
                best_weights = fitness_scores[0][1].copy()

            # Select top performers
            survivors = [w for f, w in fitness_scores[:population_size // 2]]

            # Create new population
            new_population = survivors.copy()

            # Add mutations of survivors
            while len(new_population) < population_size:
                parent = random.choice(survivors)
                child = self._mutate_weights(parent, mutation_rate, mutation_strength)
                new_population.append(child)

            population = new_population

            # Log progress
            if (iteration + 1) % 20 == 0:
                logger.info(f"Iteration {iteration + 1}: best fitness = {best_fitness:.3f}")

        # Final evaluation on test set
        test_metrics = self._evaluate_weights(best_weights, self._test_set)

        # Get date range
        dates = [o.entry_date for o in self._outcomes if o.entry_date]
        training_start = min(dates) if dates else date.today()
        training_end = max(dates) if dates else date.today()

        # Build factor analysis dict
        factor_dict = {}
        if factor_analyses:
            for a in factor_analyses:
                factor_dict[a.factor_name] = {
                    'correlation': a.correlation_return,
                    'p_value': a.p_value_return,
                    'is_significant': a.is_significant,
                    'direction': a.recommended_direction
                }

        improvement = (test_metrics['accuracy'] - baseline_accuracy) / baseline_accuracy * 100

        result = OptimizationResult(
            weights=best_weights,
            metrics=test_metrics,
            factor_analysis=factor_dict,
            accuracy=test_metrics['accuracy'],
            precision=test_metrics['precision'],
            recall=test_metrics['recall'],
            f1_score=test_metrics['f1_score'],
            baseline_accuracy=baseline_accuracy,
            improvement_pct=improvement,
            sample_size=len(self._outcomes),
            training_start=training_start,
            training_end=training_end,
            iterations=iterations
        )

        logger.info(
            f"Optimization complete: accuracy={result.accuracy:.1%}, "
            f"improvement={result.improvement_pct:+.1f}%"
        )

        return result

    def _mutate_weights(
        self,
        weights: Dict[str, float],
        mutation_rate: float,
        mutation_strength: float
    ) -> Dict[str, float]:
        """Create a mutated copy of weights."""
        mutated = weights.copy()

        for key in mutated:
            if random.random() < mutation_rate:
                # Multiply by random factor
                factor = 1 + random.uniform(-mutation_strength, mutation_strength)
                mutated[key] *= factor

                # Keep weights positive
                mutated[key] = max(0.1, mutated[key])

        # Normalize to sum to 100
        total = sum(mutated.values())
        if total > 0:
            for key in mutated:
                mutated[key] = mutated[key] / total * 100

        return mutated

    def _evaluate_weights(
        self,
        weights: Dict[str, float],
        outcomes: List[OutcomeData]
    ) -> Dict[str, float]:
        """
        Evaluate weights on outcome data.

        Returns accuracy, precision, recall, F1 score.
        """
        if not outcomes:
            return {
                'accuracy': 0,
                'precision': 0,
                'recall': 0,
                'f1_score': 0
            }

        # Score each outcome and predict win/loss
        true_positives = 0
        false_positives = 0
        true_negatives = 0
        false_negatives = 0

        for outcome in outcomes:
            score = self._calculate_score(outcome, weights)
            predicted_win = score >= 70  # Threshold for "good" score

            actual_win = outcome.outcome == 'SUCCESS'

            if predicted_win and actual_win:
                true_positives += 1
            elif predicted_win and not actual_win:
                false_positives += 1
            elif not predicted_win and not actual_win:
                true_negatives += 1
            else:
                false_negatives += 1

        total = len(outcomes)
        accuracy = (true_positives + true_negatives) / total if total > 0 else 0

        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives) > 0 else 0
        )

        recall = (
            true_positives / (true_positives + false_negatives)
            if (true_positives + false_negatives) > 0 else 0
        )

        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0 else 0
        )

        return {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1_score': f1
        }

    def _calculate_score(
        self,
        outcome: OutcomeData,
        weights: Dict[str, float]
    ) -> float:
        """
        Calculate a score for an outcome using weights.

        Simplified scoring for optimization - uses normalized factor values.
        """
        score = 50  # Start at midpoint

        # RS Rating (0-99 -> 0-1)
        if outcome.rs_rating and weights.get('rs_rating', 0) > 0:
            normalized = outcome.rs_rating / 99
            score += (normalized - 0.5) * weights['rs_rating']

        # EPS Rating (0-99 -> 0-1)
        if outcome.eps_rating and weights.get('eps_rating', 0) > 0:
            normalized = outcome.eps_rating / 99
            score += (normalized - 0.5) * weights['eps_rating']

        # Composite Rating (0-99 -> 0-1)
        if outcome.comp_rating and weights.get('comp_rating', 0) > 0:
            normalized = outcome.comp_rating / 99
            score += (normalized - 0.5) * weights['comp_rating']

        # Industry Rank (1-197 -> 0-1, inverted - lower is better)
        if outcome.industry_rank and weights.get('industry_rank', 0) > 0:
            normalized = 1 - (outcome.industry_rank / 197)
            score += (normalized - 0.5) * weights['industry_rank']

        # Fund Count (0-5000 -> 0-1, log scale)
        if outcome.fund_count and weights.get('fund_count', 0) > 0:
            import math
            normalized = min(1, math.log10(max(1, outcome.fund_count)) / 3.7)
            score += (normalized - 0.5) * weights['fund_count']

        # Funds Qtr Change (-500 to +500 -> 0-1)
        if outcome.funds_qtr_chg and weights.get('funds_qtr_chg', 0) > 0:
            normalized = (outcome.funds_qtr_chg + 500) / 1000
            normalized = max(0, min(1, normalized))
            score += (normalized - 0.5) * weights['funds_qtr_chg']

        # Base Stage (1-5 -> 0-1, inverted - lower is better)
        if outcome.base_stage and weights.get('base_stage', 0) > 0:
            stage_num = self._parse_stage(outcome.base_stage)
            if stage_num:
                normalized = 1 - (stage_num / 5)
                score += (normalized - 0.5) * weights['base_stage']

        # Base Depth (0-50% -> 0-1, inverted - lower is better)
        if outcome.base_depth and weights.get('base_depth', 0) > 0:
            normalized = 1 - min(1, outcome.base_depth / 50)
            score += (normalized - 0.5) * weights['base_depth']

        # A/D Rating (E to A+ -> 0-1)
        if outcome.ad_rating and weights.get('ad_rating', 0) > 0:
            ad_order = ['E', 'D-', 'D', 'D+', 'C-', 'C', 'C+', 'B-', 'B', 'B+', 'A-', 'A', 'A+']
            if outcome.ad_rating in ad_order:
                normalized = ad_order.index(outcome.ad_rating) / (len(ad_order) - 1)
                score += (normalized - 0.5) * weights['ad_rating']

        # Market Regime
        if outcome.market_regime and weights.get('market_regime', 0) > 0:
            regime_map = {'BEARISH': 0, 'NEUTRAL': 0.5, 'BULLISH': 1}
            normalized = regime_map.get(outcome.market_regime, 0.5)
            score += (normalized - 0.5) * weights['market_regime']

        return max(0, min(100, score))

    def _parse_stage(self, stage_str: str) -> Optional[float]:
        """Parse stage string to numeric value."""
        if not stage_str:
            return None

        try:
            stage = stage_str.split('(')[0].strip()
            base = 0
            modifier = 0

            for char in stage:
                if char.isdigit():
                    base = int(char)
                elif char.lower() == 'a':
                    modifier = 0.25
                elif char.lower() == 'b':
                    modifier = 0.5
                elif char.lower() == 'c':
                    modifier = 0.75

            return base + modifier

        except Exception:
            return None

    def save_result(self, result: OptimizationResult) -> int:
        """
        Save optimization result as new learned weights.

        Returns:
            ID of created LearnedWeights record
        """
        learned = self.repo.create_weights(
            weights=result.weights,
            factor_analysis=result.factor_analysis,
            metrics={
                'accuracy': result.accuracy,
                'precision': result.precision,
                'recall': result.recall,
                'f1': result.f1_score,
                'baseline_accuracy': result.baseline_accuracy,
                'improvement_pct': result.improvement_pct
            },
            sample_size=result.sample_size,
            training_start=result.training_start,
            training_end=result.training_end,
            notes=f"Optimized over {result.iterations} iterations"
        )

        return learned.id

    def generate_report(self, result: OptimizationResult) -> str:
        """Generate optimization report."""
        lines = []
        lines.append("=" * 60)
        lines.append("WEIGHT OPTIMIZATION REPORT")
        lines.append("=" * 60)
        lines.append(f"Sample size: {result.sample_size} outcomes")
        lines.append(f"Training period: {result.training_start} to {result.training_end}")
        lines.append(f"Iterations: {result.iterations}")
        lines.append("")

        lines.append("PERFORMANCE METRICS:")
        lines.append("-" * 40)
        lines.append(f"  Baseline accuracy: {result.baseline_accuracy:.1%}")
        lines.append(f"  Optimized accuracy: {result.accuracy:.1%}")
        lines.append(f"  Improvement: {result.improvement_pct:+.1f}%")
        lines.append(f"  Precision: {result.precision:.1%}")
        lines.append(f"  Recall: {result.recall:.1%}")
        lines.append(f"  F1 Score: {result.f1_score:.3f}")
        lines.append("")

        lines.append("OPTIMIZED WEIGHTS:")
        lines.append("-" * 40)
        sorted_weights = sorted(result.weights.items(), key=lambda x: x[1], reverse=True)
        for factor, weight in sorted_weights:
            bar = "#" * int(weight / 2)
            lines.append(f"  {factor:20} {weight:5.1f}  {bar}")

        return "\n".join(lines)
