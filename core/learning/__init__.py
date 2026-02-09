"""
CANSLIM Monitor - Learning Engine Package

Phase 7: AI-Powered Weight Optimization

This package provides components for analyzing trading outcomes,
optimizing scoring weights, and managing A/B tests.

Components:
- FactorAnalyzer: Analyzes factor correlations with outcomes
- WeightOptimizer: Optimizes scoring weights using outcome data
- ConfidenceEngine: Calculates statistical confidence levels
- ABTestEngine: Manages A/B testing of weight sets
- WeightManager: Manages active/candidate weight sets
- LearningOrchestrator: Coordinates all learning components
- LearningService: High-level service for GUI integration
- BacktestImporter: Imports backtest data from external sources
"""

from .factor_analyzer import FactorAnalyzer, FactorAnalysis
from .weight_optimizer import WeightOptimizer, OptimizationResult
from .confidence_engine import ConfidenceEngine, ConfidenceResult
from .ab_test_engine import ABTestEngine, ABTestResult
from .weight_manager import WeightManager
from .learning_orchestrator import LearningOrchestrator
from .learning_service import LearningService
from .backtest_importer import BacktestImporter

__all__ = [
    'FactorAnalyzer',
    'FactorAnalysis',
    'WeightOptimizer',
    'OptimizationResult',
    'ConfidenceEngine',
    'ConfidenceResult',
    'ABTestEngine',
    'ABTestResult',
    'WeightManager',
    'LearningOrchestrator',
    'LearningService',
    'BacktestImporter',
]
