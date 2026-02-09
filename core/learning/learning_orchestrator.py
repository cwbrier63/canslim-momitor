"""
CANSLIM Monitor - Learning Orchestrator

Coordinates all learning engine components:
- Factor analysis
- Weight optimization
- A/B testing
- Weight management
"""

import logging
from datetime import date, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from sqlalchemy.orm import Session

from canslim_monitor.data.repositories.learning_repo import LearningRepository
from .factor_analyzer import FactorAnalyzer, FactorAnalysis
from .weight_optimizer import WeightOptimizer, OptimizationResult
from .confidence_engine import ConfidenceEngine, ConfidenceResult
from .ab_test_engine import ABTestEngine, ABTestResult
from .weight_manager import WeightManager, WeightSet

logger = logging.getLogger('canslim.learning')


@dataclass
class LearningStatus:
    """Current status of the learning engine."""
    # Data availability
    total_outcomes: int
    outcomes_last_30d: int
    oldest_outcome_date: Optional[date]
    newest_outcome_date: Optional[date]

    # Current weights
    using_learned_weights: bool
    active_weights_version: int
    active_weights_accuracy: Optional[float]

    # A/B testing
    ab_test_running: bool
    ab_test_name: Optional[str]
    ab_test_progress: float

    # Recommendations
    can_run_analysis: bool
    can_optimize: bool
    recommended_action: str


class LearningOrchestrator:
    """
    Coordinates the learning engine components.

    Provides a high-level interface for:
    - Running factor analysis
    - Optimizing weights
    - Managing A/B tests
    - Generating reports
    """

    MIN_OUTCOMES_FOR_ANALYSIS = 20
    MIN_OUTCOMES_FOR_OPTIMIZATION = 50

    def __init__(self, session: Session):
        """
        Initialize the learning orchestrator.

        Args:
            session: SQLAlchemy session
        """
        self.session = session
        self.repo = LearningRepository(session)
        self.confidence = ConfidenceEngine()
        self.weight_manager = WeightManager(self.repo)
        self.factor_analyzer = FactorAnalyzer(self.repo)
        self.optimizer = WeightOptimizer(self.repo)
        self.ab_engine = ABTestEngine(self.repo, self.weight_manager, self.confidence)

    def get_status(self) -> LearningStatus:
        """
        Get current status of the learning engine.

        Returns:
            LearningStatus with current state
        """
        # Outcome stats
        stats = self.repo.get_outcome_stats()
        total = stats.get('total_outcomes', 0)

        # Count recent outcomes
        recent_date = date.today() - timedelta(days=30)
        recent_outcomes = self.repo.get_outcomes_for_training(min_date=recent_date)
        recent_count = len(recent_outcomes)

        # Current weights
        active = self.weight_manager.get_active_weights()

        # A/B test status
        running_test = self.ab_engine.get_running_test()
        ab_test_progress = 0.0
        if running_test:
            result = self.ab_engine.analyze_test(running_test.id)
            if result:
                ab_test_progress = result.progress_pct

        # Determine recommendations
        can_analyze = total >= self.MIN_OUTCOMES_FOR_ANALYSIS
        can_optimize = total >= self.MIN_OUTCOMES_FOR_OPTIMIZATION

        if not can_analyze:
            recommendation = f"Need {self.MIN_OUTCOMES_FOR_ANALYSIS - total} more outcomes for analysis"
        elif not can_optimize:
            recommendation = f"Need {self.MIN_OUTCOMES_FOR_OPTIMIZATION - total} more outcomes for optimization"
        elif running_test:
            recommendation = f"A/B test in progress: {running_test.name}"
        elif not self.weight_manager.is_using_learned_weights():
            recommendation = "Run optimization to create learned weights"
        else:
            recommendation = "System is optimized. Monitor A/B tests."

        return LearningStatus(
            total_outcomes=total,
            outcomes_last_30d=recent_count,
            oldest_outcome_date=stats.get('earliest_entry'),
            newest_outcome_date=stats.get('latest_entry'),
            using_learned_weights=active.id > 0,
            active_weights_version=active.version,
            active_weights_accuracy=active.accuracy,
            ab_test_running=running_test is not None,
            ab_test_name=running_test.name if running_test else None,
            ab_test_progress=ab_test_progress,
            can_run_analysis=can_analyze,
            can_optimize=can_optimize,
            recommended_action=recommendation
        )

    def run_analysis(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        save_results: bool = True
    ) -> List[FactorAnalysis]:
        """
        Run factor correlation analysis.

        Args:
            min_date: Minimum entry date
            max_date: Maximum entry date
            save_results: Whether to save to database

        Returns:
            List of FactorAnalysis results
        """
        logger.info("Starting factor analysis...")

        # Load outcomes
        count = self.factor_analyzer.load_outcomes(
            min_date=min_date,
            max_date=max_date
        )

        if count < self.MIN_OUTCOMES_FOR_ANALYSIS:
            logger.warning(
                f"Insufficient outcomes ({count}) for analysis. "
                f"Need at least {self.MIN_OUTCOMES_FOR_ANALYSIS}."
            )
            return []

        # Run analysis
        analyses = self.factor_analyzer.analyze_all_factors()

        if save_results:
            self.factor_analyzer.save_correlations(analyses)

        # Log summary
        significant = [a for a in analyses if a.is_significant]
        logger.info(
            f"Analysis complete: {len(significant)}/{len(analyses)} "
            f"factors significant"
        )

        return analyses

    def run_optimization(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        iterations: int = 100,
        save_result: bool = True
    ) -> Optional[OptimizationResult]:
        """
        Run weight optimization.

        Args:
            min_date: Minimum entry date
            max_date: Maximum entry date
            iterations: Optimization iterations
            save_result: Whether to save optimized weights

        Returns:
            OptimizationResult or None if insufficient data
        """
        logger.info("Starting weight optimization...")

        # Load data
        count = self.optimizer.load_data(
            min_date=min_date,
            max_date=max_date
        )

        if count < self.MIN_OUTCOMES_FOR_OPTIMIZATION:
            logger.warning(
                f"Insufficient outcomes ({count}) for optimization. "
                f"Need at least {self.MIN_OUTCOMES_FOR_OPTIMIZATION}."
            )
            return None

        # Run factor analysis first
        analyses = self.run_analysis(
            min_date=min_date,
            max_date=max_date,
            save_results=True
        )

        # Optimize
        result = self.optimizer.optimize(
            factor_analyses=analyses,
            iterations=iterations
        )

        if save_result:
            weights_id = self.optimizer.save_result(result)
            logger.info(f"Saved optimized weights with id={weights_id}")

        return result

    def start_ab_test(
        self,
        name: str,
        treatment_weights_id: int,
        control_weights_id: int = 0,
        min_sample_size: int = 30
    ) -> ABTestResult:
        """
        Start a new A/B test.

        Args:
            name: Test name
            treatment_weights_id: ID of weights to test
            control_weights_id: ID of baseline weights (0 = current)
            min_sample_size: Minimum positions per group

        Returns:
            Initial ABTestResult
        """
        # Check for existing test
        running = self.ab_engine.get_running_test()
        if running:
            raise ValueError(
                f"Cannot start new test: '{running.name}' is already running"
            )

        # Create test
        test = self.ab_engine.create_test(
            name=name,
            treatment_weights_id=treatment_weights_id,
            control_weights_id=control_weights_id,
            min_sample_size=min_sample_size
        )

        # Start test
        self.ab_engine.start_test(test.id)

        # Return initial analysis
        return self.ab_engine.analyze_test(test.id)

    def analyze_ab_test(self) -> Optional[ABTestResult]:
        """
        Analyze the currently running A/B test.

        Returns:
            ABTestResult or None if no test running
        """
        return self.ab_engine.analyze_test()

    def stop_ab_test(self, promote_winner: bool = False) -> bool:
        """
        Stop the currently running A/B test.

        Args:
            promote_winner: If True, promote winning weights to active

        Returns:
            True if stopped successfully
        """
        running = self.ab_engine.get_running_test()
        if not running:
            logger.warning("No A/B test running")
            return False

        if promote_winner:
            result = self.ab_engine.analyze_test(running.id)
            if result and result.recommended_action == 'promote_treatment':
                return self.ab_engine.promote_winner(running.id)
            else:
                logger.warning(
                    f"Cannot promote: recommendation is "
                    f"'{result.recommended_action if result else 'unknown'}'"
                )
                return self.ab_engine.stop_test(running.id)
        else:
            return self.ab_engine.stop_test(running.id)

    def on_position_entry(
        self,
        position_id: int,
        score: int = None,
        grade: str = None
    ) -> int:
        """
        Handle position entry - assign to A/B test if running.

        Args:
            position_id: Position ID
            score: Entry score
            grade: Entry grade

        Returns:
            Weights ID to use for this position
        """
        # Try to assign to A/B test
        assignment = self.ab_engine.assign_position(
            position_id=position_id,
            score=score,
            grade=grade
        )

        if assignment:
            return assignment.weights_id

        # No test running, use active weights
        active = self.weight_manager.get_active_weights()
        return active.id

    def on_position_close(
        self,
        position_id: int,
        outcome: str,
        return_pct: float,
        holding_days: int
    ):
        """
        Handle position close - record outcome for A/B test.

        Args:
            position_id: Position ID
            outcome: 'SUCCESS', 'PARTIAL', 'STOPPED', 'FAILED'
            return_pct: Percentage return
            holding_days: Days held
        """
        self.ab_engine.record_outcome(
            position_id=position_id,
            outcome=outcome,
            return_pct=return_pct,
            holding_days=holding_days
        )

    def get_weights_for_scoring(self, position_id: int = None) -> Dict[str, float]:
        """
        Get weights to use for scoring.

        If position is in an A/B test, returns test-assigned weights.
        Otherwise returns active weights.

        Args:
            position_id: Optional position ID for A/B test lookup

        Returns:
            Dictionary of factor weights
        """
        if position_id:
            weights_id = self.ab_engine.get_weights_for_position(position_id)
            weights_set = self.weight_manager.get_weights_by_id(weights_id)
            if weights_set:
                return weights_set.weights

        return self.weight_manager.get_scoring_weights()

    def generate_full_report(self) -> str:
        """Generate comprehensive learning engine report."""
        lines = []
        lines.append("=" * 70)
        lines.append("CANSLIM LEARNING ENGINE - COMPREHENSIVE REPORT")
        lines.append("=" * 70)
        lines.append("")

        # Status
        status = self.get_status()
        lines.append("STATUS OVERVIEW")
        lines.append("-" * 40)
        lines.append(f"Total Outcomes: {status.total_outcomes}")
        lines.append(f"Last 30 Days: {status.outcomes_last_30d}")
        lines.append(f"Date Range: {status.oldest_outcome_date} to {status.newest_outcome_date}")
        lines.append(f"Using Learned Weights: {'Yes' if status.using_learned_weights else 'No'}")
        if status.using_learned_weights:
            lines.append(f"  Version: {status.active_weights_version}")
            if status.active_weights_accuracy:
                lines.append(f"  Accuracy: {status.active_weights_accuracy:.1%}")
        lines.append(f"A/B Test Running: {'Yes' if status.ab_test_running else 'No'}")
        if status.ab_test_running:
            lines.append(f"  Test: {status.ab_test_name}")
            lines.append(f"  Progress: {status.ab_test_progress:.0f}%")
        lines.append(f"Recommendation: {status.recommended_action}")
        lines.append("")

        # Current weights
        lines.append(self.weight_manager.generate_report())
        lines.append("")

        # A/B test report if running
        if status.ab_test_running:
            lines.append(self.ab_engine.generate_report())
            lines.append("")

        # Factor correlations
        correlations = self.repo.get_latest_factor_correlations()
        if correlations:
            lines.append("LATEST FACTOR CORRELATIONS")
            lines.append("-" * 40)
            for corr in correlations[:10]:
                sig = "*" if corr.is_significant else " "
                lines.append(
                    f"{sig} {corr.factor_name:20} "
                    f"r={corr.correlation_return:+.3f}  "
                    f"dir={corr.recommended_direction}"
                )
            lines.append("* = statistically significant")
            lines.append("")

        return "\n".join(lines)

    def run_full_cycle(
        self,
        min_sample_size: int = 30,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Run a complete learning cycle:
        1. Analyze factors
        2. Optimize weights
        3. Start A/B test if appropriate

        Args:
            min_sample_size: Minimum A/B test sample size
            force: Run even if conditions not ideal

        Returns:
            Dictionary with cycle results
        """
        results = {
            'analysis': None,
            'optimization': None,
            'ab_test': None,
            'status': None,
            'errors': []
        }

        status = self.get_status()

        # Check if we can run
        if not status.can_run_analysis and not force:
            results['errors'].append("Insufficient outcomes for analysis")
            results['status'] = 'insufficient_data'
            return results

        if status.ab_test_running:
            results['errors'].append("A/B test already running")
            results['status'] = 'ab_test_running'
            return results

        try:
            # Step 1: Factor analysis
            logger.info("Step 1: Running factor analysis...")
            analyses = self.run_analysis(save_results=True)
            results['analysis'] = {
                'total_factors': len(analyses),
                'significant_factors': len([a for a in analyses if a.is_significant])
            }

            # Step 2: Optimization
            if status.can_optimize or force:
                logger.info("Step 2: Running optimization...")
                opt_result = self.run_optimization(save_result=True)
                if opt_result:
                    results['optimization'] = {
                        'accuracy': opt_result.accuracy,
                        'improvement': opt_result.improvement_pct,
                        'weights_id': self.repo.get_all_weights(limit=1)[0].id
                    }

                    # Step 3: Start A/B test
                    if opt_result.improvement_pct > 0:
                        logger.info("Step 3: Starting A/B test...")
                        ab_result = self.start_ab_test(
                            name=f"Optimization {date.today().isoformat()}",
                            treatment_weights_id=results['optimization']['weights_id'],
                            min_sample_size=min_sample_size
                        )
                        results['ab_test'] = {
                            'name': ab_result.test.name,
                            'treatment_weights': ab_result.test.treatment_weights_id,
                            'control_weights': ab_result.test.control_weights_id
                        }
                    else:
                        results['errors'].append(
                            "No improvement from optimization - skipping A/B test"
                        )

            results['status'] = 'completed'

        except Exception as e:
            logger.error(f"Error in learning cycle: {e}")
            results['errors'].append(str(e))
            results['status'] = 'error'

        return results
