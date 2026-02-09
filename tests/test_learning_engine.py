"""
CANSLIM Monitor - Unit Tests for Learning Engine
Phase 7: AI-Powered Weight Optimization

Tests for factor analysis, weight optimization, A/B testing, and orchestration.
"""

import os
import sys
import unittest
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.data.models import Position, Outcome, LearnedWeights
from canslim_monitor.data.repositories import RepositoryManager
from canslim_monitor.data.repositories.learning_repo import (
    LearningRepository, OutcomeData, ABTest, ABTestAssignment, FactorCorrelation
)
from canslim_monitor.core.learning.factor_analyzer import (
    FactorAnalyzer, FactorAnalysis, ANALYZABLE_FACTORS
)
from canslim_monitor.core.learning.weight_optimizer import (
    WeightOptimizer, OptimizationResult, DEFAULT_WEIGHTS
)
from canslim_monitor.core.learning.confidence_engine import (
    ConfidenceEngine, ConfidenceResult, ABTestSignificance
)
from canslim_monitor.core.learning.weight_manager import WeightManager, WeightSet
from canslim_monitor.core.learning.ab_test_engine import ABTestEngine, ABTestResult
from canslim_monitor.core.learning.learning_orchestrator import (
    LearningOrchestrator, LearningStatus
)


class TestConfidenceEngine(unittest.TestCase):
    """Tests for ConfidenceEngine."""

    def setUp(self):
        self.engine = ConfidenceEngine()

    def test_proportion_confidence_basic(self):
        """Test confidence interval for win rate."""
        result = self.engine.calculate_proportion_confidence(
            successes=60,
            total=100,
            confidence_level=0.95
        )

        self.assertEqual(result.sample_size, 100)
        self.assertAlmostEqual(result.value, 0.6, places=2)
        self.assertLess(result.lower_bound, result.value)
        self.assertGreater(result.upper_bound, result.value)
        self.assertTrue(result.is_reliable)

    def test_proportion_confidence_small_sample(self):
        """Test confidence interval with small sample."""
        result = self.engine.calculate_proportion_confidence(
            successes=3,
            total=5
        )

        self.assertEqual(result.confidence_rating, 'insufficient')
        self.assertFalse(result.is_reliable)

    def test_proportion_confidence_zero(self):
        """Test confidence interval with zero total."""
        result = self.engine.calculate_proportion_confidence(
            successes=0,
            total=0
        )

        self.assertEqual(result.sample_size, 0)
        self.assertFalse(result.is_reliable)

    def test_mean_confidence(self):
        """Test confidence interval for mean."""
        values = [5.0, 10.0, 15.0, 20.0, 25.0] * 10  # 50 samples

        result = self.engine.calculate_mean_confidence(
            values=values,
            confidence_level=0.95,
            metric_name="avg_return"
        )

        self.assertEqual(result.sample_size, 50)
        self.assertAlmostEqual(result.value, 15.0, places=1)
        self.assertTrue(result.is_reliable)

    def test_ab_significance_significant(self):
        """Test A/B significance with clear winner."""
        result = self.engine.test_ab_significance(
            control_successes=40,
            control_total=100,
            treatment_successes=60,
            treatment_total=100
        )

        self.assertEqual(result.control_rate, 0.4)
        self.assertEqual(result.treatment_rate, 0.6)
        self.assertAlmostEqual(result.difference, 0.2, places=2)
        self.assertTrue(result.is_significant)
        self.assertLess(result.p_value, 0.05)

    def test_ab_significance_not_significant(self):
        """Test A/B significance with small difference."""
        result = self.engine.test_ab_significance(
            control_successes=50,
            control_total=100,
            treatment_successes=52,
            treatment_total=100
        )

        self.assertFalse(result.is_significant)
        self.assertGreater(result.p_value, 0.05)

    def test_minimum_sample_size(self):
        """Test minimum sample size calculation."""
        n = self.engine.calculate_minimum_sample_size(
            baseline_rate=0.5,
            minimum_detectable_effect=0.1,
            alpha=0.05,
            power=0.80
        )

        self.assertGreater(n, 0)
        self.assertIsInstance(n, int)


class TestWeightManager(unittest.TestCase):
    """Tests for WeightManager."""

    def setUp(self):
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = LearningRepository(self.session)
        self.manager = WeightManager(self.repo)

    def tearDown(self):
        self.session.close()
        self.db.close()

    def test_get_default_weights(self):
        """Test getting default weights."""
        weights = self.manager.get_default_weights()

        self.assertIn('rs_rating', weights)
        self.assertIn('base_stage', weights)
        self.assertGreater(weights['rs_rating'], 0)

    def test_get_active_weights_default(self):
        """Test getting active weights when none exist."""
        weight_set = self.manager.get_active_weights()

        self.assertEqual(weight_set.id, 0)
        self.assertEqual(weight_set.version, 0)
        self.assertIn('rs_rating', weight_set.weights)

    def test_get_scoring_weights(self):
        """Test getting weights for scoring."""
        weights = self.manager.get_scoring_weights()

        self.assertIsInstance(weights, dict)
        self.assertGreater(len(weights), 0)

    def test_is_using_learned_weights(self):
        """Test checking if using learned weights."""
        using_learned = self.manager.is_using_learned_weights()

        # Should be False with no learned weights
        self.assertFalse(using_learned)

    def test_compare_weights(self):
        """Test comparing two weight sets."""
        weights_a = WeightSet(
            id=1, version=1,
            weights={'rs_rating': 15, 'eps_rating': 10},
            is_active=False
        )
        weights_b = WeightSet(
            id=2, version=2,
            weights={'rs_rating': 20, 'eps_rating': 10},
            is_active=False
        )

        comparison = self.manager.compare_weights(weights_a, weights_b)

        self.assertIn('differences', comparison)
        self.assertEqual(len(comparison['differences']), 2)
        # RS rating diff should be +5
        rs_diff = next(d for d in comparison['differences'] if d['factor'] == 'rs_rating')
        self.assertEqual(rs_diff['difference'], 5)


class TestFactorAnalyzer(unittest.TestCase):
    """Tests for FactorAnalyzer."""

    def setUp(self):
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = LearningRepository(self.session)
        self.analyzer = FactorAnalyzer(self.repo)

    def tearDown(self):
        self.session.close()
        self.db.close()

    def test_pearson_correlation(self):
        """Test Pearson correlation calculation."""
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]  # Perfect positive correlation

        r = self.analyzer._pearson_correlation(x, y)
        self.assertAlmostEqual(r, 1.0, places=5)

    def test_pearson_correlation_negative(self):
        """Test negative correlation."""
        x = [1, 2, 3, 4, 5]
        y = [10, 8, 6, 4, 2]  # Perfect negative correlation

        r = self.analyzer._pearson_correlation(x, y)
        self.assertAlmostEqual(r, -1.0, places=5)

    def test_pearson_correlation_zero(self):
        """Test zero correlation."""
        x = [1, 2, 3, 4, 5]
        y = [5, 5, 5, 5, 5]  # Constant - no correlation

        r = self.analyzer._pearson_correlation(x, y)
        self.assertAlmostEqual(r, 0.0, places=5)

    def test_parse_stage(self):
        """Test stage string parsing."""
        self.assertAlmostEqual(self.analyzer._parse_stage('1'), 1.0)
        self.assertAlmostEqual(self.analyzer._parse_stage('2a'), 2.25)
        self.assertAlmostEqual(self.analyzer._parse_stage('2b'), 2.5)
        self.assertAlmostEqual(self.analyzer._parse_stage('3c(2)'), 3.75)
        self.assertIsNone(self.analyzer._parse_stage(''))

    def test_create_buckets(self):
        """Test tercile bucket creation."""
        values = list(range(30))
        returns = [i * 0.5 for i in range(30)]
        wins = [1 if i > 15 else 0 for i in range(30)]

        buckets = self.analyzer._create_buckets(values, returns, wins)

        self.assertEqual(len(buckets), 3)
        self.assertEqual(buckets[0].bucket_name, 'low')
        self.assertEqual(buckets[1].bucket_name, 'mid')
        self.assertEqual(buckets[2].bucket_name, 'high')

    def test_load_outcomes_empty(self):
        """Test loading outcomes from empty database."""
        count = self.analyzer.load_outcomes()
        self.assertEqual(count, 0)


class TestWeightOptimizer(unittest.TestCase):
    """Tests for WeightOptimizer."""

    def setUp(self):
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = LearningRepository(self.session)
        self.optimizer = WeightOptimizer(self.repo)

    def tearDown(self):
        self.session.close()
        self.db.close()

    def test_mutate_weights(self):
        """Test weight mutation."""
        original = {'rs_rating': 15, 'eps_rating': 10}

        # With high mutation rate, should change
        mutated = self.optimizer._mutate_weights(
            original,
            mutation_rate=1.0,  # Always mutate
            mutation_strength=0.5
        )

        # Should have same keys
        self.assertEqual(set(mutated.keys()), set(original.keys()))

        # Weights should be normalized
        total = sum(mutated.values())
        self.assertAlmostEqual(total, 100, places=1)

    def test_calculate_score(self):
        """Test score calculation."""
        outcome = OutcomeData(
            position_id=1,
            symbol='NVDA',
            entry_date=date.today(),
            exit_date=date.today(),
            holding_days=10,
            gross_pct=15.0,
            outcome='SUCCESS',
            rs_rating=90,
            eps_rating=85,
            comp_rating=95
        )

        score = self.optimizer._calculate_score(outcome, DEFAULT_WEIGHTS)

        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_evaluate_weights_empty(self):
        """Test weight evaluation with no data."""
        metrics = self.optimizer._evaluate_weights(DEFAULT_WEIGHTS, [])

        self.assertEqual(metrics['accuracy'], 0)
        self.assertEqual(metrics['precision'], 0)


class TestLearningRepository(unittest.TestCase):
    """Tests for LearningRepository."""

    def setUp(self):
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = LearningRepository(self.session)

    def tearDown(self):
        self.session.close()
        self.db.close()

    def test_get_outcome_count_empty(self):
        """Test outcome count with empty database."""
        count = self.repo.get_outcome_count()
        self.assertEqual(count, 0)

    def test_get_outcome_stats_empty(self):
        """Test outcome stats with empty database."""
        stats = self.repo.get_outcome_stats()

        self.assertEqual(stats['total_outcomes'], 0)
        self.assertEqual(stats['win_rate'], 0)

    def test_get_active_weights_none(self):
        """Test getting active weights when none exist."""
        active = self.repo.get_active_weights()
        self.assertIsNone(active)

    def test_create_and_activate_weights(self):
        """Test creating and activating weights."""
        learned = self.repo.create_weights(
            weights={'rs_rating': 20, 'eps_rating': 15},
            factor_analysis={},
            metrics={'accuracy': 0.65},
            sample_size=100,
            training_start=date.today() - timedelta(days=30),
            training_end=date.today(),
            notes="Test weights"
        )

        self.assertIsNotNone(learned.id)
        self.assertFalse(learned.is_active)

        # Activate
        success = self.repo.activate_weights(learned.id)
        self.assertTrue(success)

        # Check active
        active = self.repo.get_active_weights()
        self.assertIsNotNone(active)
        self.assertEqual(active.id, learned.id)
        self.assertTrue(active.is_active)


class TestABTestEngine(unittest.TestCase):
    """Tests for ABTestEngine."""

    def setUp(self):
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.repo = LearningRepository(self.session)
        self.confidence = ConfidenceEngine()
        self.weight_manager = WeightManager(self.repo)
        self.engine = ABTestEngine(self.repo, self.weight_manager, self.confidence)

    def tearDown(self):
        self.session.close()
        self.db.close()

    def test_no_running_test(self):
        """Test getting running test when none exists."""
        running = self.engine.get_running_test()
        self.assertIsNone(running)

    def test_get_weights_for_position_no_test(self):
        """Test getting weights when no test running."""
        weights_id = self.engine.get_weights_for_position(position_id=1)
        self.assertEqual(weights_id, 0)  # Default weights


class TestLearningOrchestrator(unittest.TestCase):
    """Tests for LearningOrchestrator."""

    def setUp(self):
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()
        self.orchestrator = LearningOrchestrator(self.session)

    def tearDown(self):
        self.session.close()
        self.db.close()

    def test_get_status_empty(self):
        """Test getting status with empty database."""
        status = self.orchestrator.get_status()

        self.assertEqual(status.total_outcomes, 0)
        self.assertFalse(status.using_learned_weights)
        self.assertFalse(status.ab_test_running)
        self.assertFalse(status.can_run_analysis)
        self.assertFalse(status.can_optimize)

    def test_get_weights_for_scoring(self):
        """Test getting weights for scoring."""
        weights = self.orchestrator.get_weights_for_scoring()

        self.assertIsInstance(weights, dict)
        self.assertIn('rs_rating', weights)

    def test_generate_full_report(self):
        """Test generating full report."""
        report = self.orchestrator.generate_full_report()

        self.assertIn('LEARNING ENGINE', report)
        self.assertIn('STATUS', report)


class TestIntegration(unittest.TestCase):
    """Integration tests for learning engine."""

    def setUp(self):
        self.db = DatabaseManager(in_memory=True)
        self.db.initialize(seed_config=True)
        self.session = self.db.get_new_session()

    def tearDown(self):
        self.session.close()
        self.db.close()

    def test_full_workflow_insufficient_data(self):
        """Test full workflow with insufficient data."""
        orchestrator = LearningOrchestrator(self.session)

        # Check status
        status = orchestrator.get_status()
        self.assertFalse(status.can_run_analysis)

        # Try to run analysis - should return empty
        analyses = orchestrator.run_analysis(save_results=False)
        self.assertEqual(len(analyses), 0)

    def test_weights_creation_and_retrieval(self):
        """Test creating and retrieving weights."""
        repo = LearningRepository(self.session)
        manager = WeightManager(repo)

        # Create weights
        learned = repo.create_weights(
            weights={'rs_rating': 25, 'eps_rating': 20, 'base_stage': 15},
            factor_analysis={'rs_rating': {'correlation': 0.3}},
            metrics={'accuracy': 0.68, 'f1': 0.65},
            sample_size=150,
            training_start=date.today() - timedelta(days=60),
            training_end=date.today()
        )

        # Retrieve
        all_weights = manager.get_all_weights()
        self.assertGreater(len(all_weights), 0)

        # Activate
        repo.activate_weights(learned.id)

        # Check active
        active = manager.get_active_weights(force_refresh=True)
        self.assertEqual(active.id, learned.id)
        self.assertTrue(manager.is_using_learned_weights())


if __name__ == '__main__':
    unittest.main()
