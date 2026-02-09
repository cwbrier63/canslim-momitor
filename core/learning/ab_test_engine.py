"""
CANSLIM Monitor - A/B Test Engine

Manages A/B testing of different scoring weight sets.
Assigns positions to test groups and tracks outcomes.
"""

import logging
import random
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

from canslim_monitor.data.repositories.learning_repo import (
    LearningRepository, ABTest, ABTestAssignment
)
from .confidence_engine import ConfidenceEngine, ABTestSignificance
from .weight_manager import WeightManager

logger = logging.getLogger('canslim.learning.abtest')


@dataclass
class ABTestResult:
    """Complete A/B test analysis results."""
    test: ABTest
    significance: ABTestSignificance

    # Group metrics
    control_wins: int
    control_losses: int
    treatment_wins: int
    treatment_losses: int

    # Return metrics
    control_avg_return: float
    treatment_avg_return: float
    return_difference: float

    # Recommendation
    recommended_action: str  # 'promote_treatment', 'keep_control', 'continue_test'
    recommendation_reason: str

    # Power analysis
    sample_size_per_group: int
    samples_needed: int
    progress_pct: float


class ABTestEngine:
    """
    Manages A/B testing of scoring weights.

    Features:
    - Create and manage A/B tests
    - Assign positions to test groups
    - Track outcomes
    - Analyze results with statistical significance
    - Recommend actions based on results
    """

    def __init__(
        self,
        repo: LearningRepository,
        weight_manager: WeightManager,
        confidence_engine: ConfidenceEngine
    ):
        self.repo = repo
        self.weight_manager = weight_manager
        self.confidence_engine = confidence_engine
        self._current_test: Optional[ABTest] = None

    def create_test(
        self,
        name: str,
        treatment_weights_id: int,
        control_weights_id: int = 0,
        split_ratio: float = 0.5,
        min_sample_size: int = 30,
        description: str = None
    ) -> ABTest:
        """
        Create a new A/B test.

        Args:
            name: Test name
            treatment_weights_id: ID of new weights to test
            control_weights_id: ID of baseline weights (0 = current active)
            split_ratio: Fraction to treatment (0-1)
            min_sample_size: Minimum positions per group
            description: Test description

        Returns:
            Created ABTest
        """
        # If control is 0, use current active weights
        if control_weights_id == 0:
            active = self.weight_manager.get_active_weights()
            control_weights_id = active.id

        # Validate weights exist
        treatment = self.weight_manager.get_weights_by_id(treatment_weights_id)
        if not treatment:
            raise ValueError(f"Treatment weights {treatment_weights_id} not found")

        if control_weights_id > 0:
            control = self.weight_manager.get_weights_by_id(control_weights_id)
            if not control:
                raise ValueError(f"Control weights {control_weights_id} not found")

        test = self.repo.create_ab_test(
            name=name,
            control_weights_id=control_weights_id,
            treatment_weights_id=treatment_weights_id,
            split_ratio=split_ratio,
            min_sample_size=min_sample_size,
            description=description
        )

        logger.info(
            f"Created A/B test '{name}': "
            f"control={control_weights_id}, treatment={treatment_weights_id}"
        )

        return test

    def start_test(self, test_id: int) -> bool:
        """
        Start an A/B test.

        Args:
            test_id: Test ID

        Returns:
            True if started successfully
        """
        # Check for existing running test
        running = self.get_running_test()
        if running:
            raise ValueError(
                f"Test '{running.name}' is already running. "
                "Stop it before starting a new test."
            )

        success = self.repo.start_ab_test(test_id)
        if success:
            self._current_test = self.repo.get_ab_test(test_id)
            logger.info(f"Started A/B test {test_id}")

        return success

    def stop_test(self, test_id: int, winner: str = None) -> bool:
        """
        Stop an A/B test.

        Args:
            test_id: Test ID
            winner: Optional winner designation ('control' or 'treatment')

        Returns:
            True if stopped successfully
        """
        success = self.repo.end_ab_test(test_id, winner=winner)
        if success:
            self._current_test = None
            logger.info(f"Stopped A/B test {test_id}, winner={winner}")

        return success

    def get_running_test(self) -> Optional[ABTest]:
        """Get the currently running A/B test."""
        if self._current_test and self._current_test.status == 'running':
            return self._current_test

        self._current_test = self.repo.get_running_ab_test()
        return self._current_test

    def assign_position(
        self,
        position_id: int,
        score: int = None,
        grade: str = None
    ) -> Optional[ABTestAssignment]:
        """
        Assign a position to an A/B test group.

        Randomly assigns based on split ratio.

        Args:
            position_id: Position ID
            score: Score at assignment time
            grade: Grade at assignment time

        Returns:
            Assignment if a test is running, None otherwise
        """
        test = self.get_running_test()
        if not test:
            return None

        # Check if already assigned
        existing = self.repo.get_position_ab_assignment(position_id)
        if existing:
            logger.debug(f"Position {position_id} already assigned to {existing.group_name}")
            return existing

        # Random assignment based on split ratio
        if random.random() < test.split_ratio:
            group_name = 'treatment'
            weights_id = test.treatment_weights_id
        else:
            group_name = 'control'
            weights_id = test.control_weights_id

        assignment = self.repo.assign_to_ab_test(
            test_id=test.id,
            position_id=position_id,
            group_name=group_name,
            weights_id=weights_id,
            score=score,
            grade=grade
        )

        logger.info(f"Assigned position {position_id} to {group_name} group")
        return assignment

    def record_outcome(
        self,
        position_id: int,
        outcome: str,
        return_pct: float,
        holding_days: int
    ):
        """
        Record outcome for a position in an A/B test.

        Args:
            position_id: Position ID
            outcome: 'SUCCESS', 'PARTIAL', 'STOPPED', 'FAILED'
            return_pct: Percentage return
            holding_days: Days held
        """
        self.repo.record_ab_test_outcome(
            position_id=position_id,
            outcome=outcome,
            return_pct=return_pct,
            holding_days=holding_days
        )
        logger.debug(f"Recorded outcome for position {position_id}: {outcome}")

    def get_weights_for_position(self, position_id: int) -> int:
        """
        Get the weights ID to use for a position.

        If position is in a test, returns assigned weights.
        Otherwise returns active weights.

        Args:
            position_id: Position ID

        Returns:
            Weights ID to use
        """
        assignment = self.repo.get_position_ab_assignment(position_id)
        if assignment:
            return assignment.weights_id

        active = self.weight_manager.get_active_weights()
        return active.id

    def analyze_test(self, test_id: int = None) -> Optional[ABTestResult]:
        """
        Analyze current or specified A/B test results.

        Args:
            test_id: Test ID (uses running test if not specified)

        Returns:
            ABTestResult with analysis
        """
        if test_id is None:
            test = self.get_running_test()
            if not test:
                logger.warning("No running test to analyze")
                return None
            test_id = test.id
        else:
            test = self.repo.get_ab_test(test_id)
            if not test:
                logger.warning(f"Test {test_id} not found")
                return None

        # Get results by group
        results = self.repo.get_ab_test_results(test_id)
        control_results = results.get('control', [])
        treatment_results = results.get('treatment', [])

        # Calculate metrics
        control_wins = sum(1 for r in control_results if r.outcome == 'SUCCESS')
        control_losses = len(control_results) - control_wins
        treatment_wins = sum(1 for r in treatment_results if r.outcome == 'SUCCESS')
        treatment_losses = len(treatment_results) - treatment_wins

        control_returns = [r.return_pct for r in control_results if r.return_pct is not None]
        treatment_returns = [r.return_pct for r in treatment_results if r.return_pct is not None]

        control_avg = sum(control_returns) / len(control_returns) if control_returns else 0
        treatment_avg = sum(treatment_returns) / len(treatment_returns) if treatment_returns else 0

        # Statistical significance
        significance = self.confidence_engine.test_ab_significance(
            control_successes=control_wins,
            control_total=len(control_results),
            treatment_successes=treatment_wins,
            treatment_total=len(treatment_results)
        )

        # Update test stats
        self.repo.update_ab_test_stats(
            test_id=test_id,
            control_count=len(control_results),
            treatment_count=len(treatment_results),
            control_win_rate=significance.control_rate,
            treatment_win_rate=significance.treatment_rate,
            control_avg_return=control_avg,
            treatment_avg_return=treatment_avg,
            p_value=significance.p_value,
            is_significant=significance.is_significant
        )

        # Determine recommendation
        action, reason = self._get_recommendation(
            test, significance,
            len(control_results), len(treatment_results)
        )

        # Progress calculation
        min_per_group = test.min_sample_size
        current_min = min(len(control_results), len(treatment_results))
        progress = min(100, current_min / min_per_group * 100)

        return ABTestResult(
            test=test,
            significance=significance,
            control_wins=control_wins,
            control_losses=control_losses,
            treatment_wins=treatment_wins,
            treatment_losses=treatment_losses,
            control_avg_return=control_avg,
            treatment_avg_return=treatment_avg,
            return_difference=treatment_avg - control_avg,
            recommended_action=action,
            recommendation_reason=reason,
            sample_size_per_group=current_min,
            samples_needed=significance.recommended_sample,
            progress_pct=progress
        )

    def _get_recommendation(
        self,
        test: ABTest,
        significance: ABTestSignificance,
        control_n: int,
        treatment_n: int
    ) -> tuple:
        """Determine recommended action based on test results."""
        min_n = min(control_n, treatment_n)

        # Insufficient data
        if min_n < 10:
            return 'continue_test', f"Insufficient data ({min_n} per group, need 10+)"

        # Not yet at minimum sample size
        if min_n < test.min_sample_size:
            return 'continue_test', (
                f"Below minimum sample ({min_n}/{test.min_sample_size}). "
                f"Progress: {min_n/test.min_sample_size*100:.0f}%"
            )

        # Check significance
        if not significance.is_significant:
            if min_n >= test.min_sample_size * 2:
                return 'keep_control', "No significant difference after extended test"
            return 'continue_test', (
                f"Not yet significant (p={significance.p_value:.3f}). "
                f"Need more data or larger effect."
            )

        # Significant result
        if significance.treatment_rate > significance.control_rate:
            lift = significance.relative_lift
            return 'promote_treatment', (
                f"Treatment significantly better: "
                f"+{lift:.1f}% lift (p={significance.p_value:.3f})"
            )
        else:
            return 'keep_control', (
                f"Control significantly better: "
                f"Treatment {significance.difference:.1%} worse (p={significance.p_value:.3f})"
            )

    def promote_winner(self, test_id: int) -> bool:
        """
        Promote the winning weights to active.

        Args:
            test_id: Test ID

        Returns:
            True if promoted successfully
        """
        result = self.analyze_test(test_id)
        if not result:
            return False

        if result.recommended_action != 'promote_treatment':
            logger.warning(
                f"Cannot promote: recommendation is '{result.recommended_action}'"
            )
            return False

        # Activate treatment weights
        success = self.weight_manager.activate_weights(
            result.test.treatment_weights_id
        )

        if success:
            # Mark test as completed with winner
            self.stop_test(test_id, winner='treatment')
            logger.info(
                f"Promoted treatment weights {result.test.treatment_weights_id} to active"
            )

        return success

    def generate_report(self, test_id: int = None) -> str:
        """Generate A/B test report."""
        result = self.analyze_test(test_id)

        if not result:
            return "No A/B test running or specified test not found."

        lines = []
        lines.append("=" * 60)
        lines.append(f"A/B TEST REPORT: {result.test.name}")
        lines.append("=" * 60)
        lines.append(f"Status: {result.test.status.upper()}")
        lines.append(f"Started: {result.test.started_at}")
        lines.append("")

        lines.append("SAMPLE SIZES:")
        lines.append(f"  Control: {result.control_wins + result.control_losses}")
        lines.append(f"  Treatment: {result.treatment_wins + result.treatment_losses}")
        lines.append(f"  Progress: {result.progress_pct:.0f}%")
        lines.append("")

        lines.append("WIN RATES:")
        lines.append(f"  Control: {result.significance.control_rate:.1%} ({result.control_wins}W / {result.control_losses}L)")
        lines.append(f"  Treatment: {result.significance.treatment_rate:.1%} ({result.treatment_wins}W / {result.treatment_losses}L)")
        lines.append(f"  Difference: {result.significance.difference:+.1%}")
        lines.append(f"  Relative Lift: {result.significance.relative_lift:+.1f}%")
        lines.append("")

        lines.append("RETURNS:")
        lines.append(f"  Control Avg: {result.control_avg_return:+.2f}%")
        lines.append(f"  Treatment Avg: {result.treatment_avg_return:+.2f}%")
        lines.append(f"  Difference: {result.return_difference:+.2f}%")
        lines.append("")

        lines.append("STATISTICAL SIGNIFICANCE:")
        lines.append(f"  P-value: {result.significance.p_value:.4f}")
        lines.append(f"  Significant: {'YES' if result.significance.is_significant else 'NO'}")
        lines.append(f"  Power: {result.significance.achieved_power:.1%}")
        lines.append(f"  95% CI: [{result.significance.diff_lower:+.1%}, {result.significance.diff_upper:+.1%}]")
        lines.append("")

        lines.append("RECOMMENDATION:")
        lines.append(f"  Action: {result.recommended_action.replace('_', ' ').upper()}")
        lines.append(f"  Reason: {result.recommendation_reason}")

        return "\n".join(lines)
