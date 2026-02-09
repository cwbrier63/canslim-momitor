"""
Learning Service - Orchestrator

Ties together factor analysis, weight optimization, and result storage.
This is the main entry point for the learning engine used by the GUI.
"""

import json
import logging
import yaml
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from canslim_monitor.data.models import Outcome, LearnedWeights
from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.core.learning.factor_analyzer import FactorAnalyzer, FactorAnalysis
from canslim_monitor.core.learning.weight_optimizer import WeightOptimizer, OptimizationResult

logger = logging.getLogger(__name__)


def load_learning_config() -> Dict:
    """Load learning configuration from YAML file."""
    config_path = Path(__file__).parent.parent.parent / 'config' / 'learning_config.yaml'
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}


def load_scoring_weights() -> Dict[str, float]:
    """Load baseline scoring weights from scoring_config.yaml."""
    config_path = Path(__file__).parent.parent.parent / 'config' / 'scoring_config.yaml'
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
            # Extract weights from the scoring config
            weights = {}
            for factor in config.get('factors', []):
                name = factor.get('name')
                weight = factor.get('weight', 0)
                if name:
                    weights[name] = weight
            return weights
    return {
        'rs_rating': 0.15,
        'eps_rating': 0.05,
        'stage': -0.20,
        'base_depth': -0.10,
        'pattern': 0.15,
        'ad_rating': 0.10,
        'market_regime': 0.15,
    }


class LearningService:
    """Central coordinator for the learning engine."""

    def __init__(self, db: DatabaseManager, config: Dict = None):
        self.db = db
        self.config = config or load_learning_config().get('learning', {})
        self.analyzer = FactorAnalyzer(None)  # Will set repo per-session
        self.optimizer = WeightOptimizer(None)  # Will set repo per-session

    def run_full_analysis(self, baseline_weights: Dict = None) -> Dict:
        """
        Execute the complete learning pipeline:
        1. Gather outcomes
        2. Run factor analysis
        3. Run weight optimization
        4. Store results
        5. Return summary for GUI/Discord
        """
        if baseline_weights is None:
            baseline_weights = load_scoring_weights()

        session = self.db.get_new_session()

        try:
            # 1. Gather outcomes
            outcomes = self._gather_outcomes(session)
            min_outcomes = self.config.get('min_outcomes', 50)

            if len(outcomes) < min_outcomes:
                return {
                    'status': 'insufficient_data',
                    'message': f'Need {min_outcomes}+ outcomes, have {len(outcomes)}',
                    'sample_size': len(outcomes)
                }

            # 2. Factor analysis
            from canslim_monitor.data.repositories.learning_repo import LearningRepository
            repo = LearningRepository(session)
            self.analyzer = FactorAnalyzer(repo)
            self.analyzer._outcomes = [self._dict_to_outcome_data(o) for o in outcomes]

            analysis_results = self.analyzer.analyze_all_factors()

            # 3. Weight optimization
            self.optimizer = WeightOptimizer(repo)
            self.optimizer._outcomes = [self._dict_to_outcome_data(o) for o in outcomes]

            # Split data for optimizer
            import random
            shuffled = outcomes.copy()
            random.shuffle(shuffled)
            split_idx = int(len(shuffled) * 0.8)
            self.optimizer._train_set = [self._dict_to_outcome_data(o) for o in shuffled[:split_idx]]
            self.optimizer._test_set = [self._dict_to_outcome_data(o) for o in shuffled[split_idx:]]

            optimization_results = self.optimizer.optimize(
                factor_analyses=analysis_results,
                iterations=100
            )

            # 4. Store results
            weights_id = None
            if optimization_results:
                weights_record = self._store_results(
                    session, analysis_results, optimization_results, outcomes
                )
                session.commit()
                weights_id = weights_record.id

            # Build analysis dict for return
            analysis_dict = {
                'sample_size': len(outcomes),
                'outcome_distribution': self._outcome_distribution(outcomes),
                'factors': {},
                'factor_ranking': []
            }

            for a in analysis_results:
                analysis_dict['factors'][a.factor_name] = {
                    'type': a.factor_type,
                    'correlation': a.correlation_return,
                    'p_value': a.p_value_return,
                    'is_significant': a.is_significant,
                    'sample_count': a.sample_count
                }
                if a.is_significant:
                    analysis_dict['factor_ranking'].append({
                        'factor': a.factor_name,
                        'correlation': a.correlation_return,
                        'abs_correlation': abs(a.correlation_return)
                    })

            analysis_dict['factor_ranking'].sort(key=lambda x: x['abs_correlation'], reverse=True)

            return {
                'status': 'complete',
                'weights_id': weights_id,
                'analysis': analysis_dict,
                'optimization': {
                    'accuracy': optimization_results.accuracy if optimization_results else 0,
                    'baseline_accuracy': optimization_results.baseline_accuracy if optimization_results else 0,
                    'improvement_pct': optimization_results.improvement_pct if optimization_results else 0,
                    'suggested_weights': optimization_results.weights if optimization_results else {},
                    'is_significant': optimization_results.improvement_pct >= self.config.get('optimization', {}).get('min_improvement_pct', 5.0) if optimization_results else False
                },
                'report': self._generate_report(analysis_results, optimization_results)
            }

        finally:
            session.close()

    def _gather_outcomes(self, session: Session) -> List[Dict]:
        """Fetch all outcomes and convert to dicts for analysis."""
        outcomes = session.query(Outcome).filter(
            Outcome.outcome.isnot(None)
        ).all()

        result = []
        for o in outcomes:
            result.append({
                'symbol': o.symbol,
                'entry_date': o.entry_date,
                'exit_date': o.exit_date,
                'entry_price': o.entry_price,
                'exit_price': o.exit_price,
                'rs_at_entry': o.rs_at_entry,
                'eps_at_entry': o.eps_at_entry,
                'comp_at_entry': o.comp_at_entry,
                'ad_at_entry': o.ad_at_entry,
                'stage_at_entry': o.stage_at_entry,
                'pattern': o.pattern,
                'base_depth_at_entry': o.base_depth_at_entry,
                'base_length_at_entry': o.base_length_at_entry,
                'market_regime_at_entry': o.market_regime_at_entry,
                'spy_at_entry': o.spy_at_entry,
                'gross_pct': o.gross_pct,
                'max_gain_pct': o.max_gain_pct,
                'max_drawdown_pct': o.max_drawdown_pct,
                'hit_stop': o.hit_stop,
                'holding_days': o.holding_days,
                'outcome': o.outcome,
                'outcome_score': o.outcome_score,
                'source': o.source,
                'entry_grade': o.entry_grade,
                'entry_score': o.entry_score,
            })

        logger.info(f"Gathered {len(result)} outcomes for analysis")
        return result

    def _dict_to_outcome_data(self, d: Dict):
        """Convert dict to OutcomeData for analyzer/optimizer."""
        from canslim_monitor.data.repositories.learning_repo import OutcomeData
        return OutcomeData(
            position_id=0,
            symbol=d.get('symbol', ''),
            entry_date=d.get('entry_date') or date.today(),
            exit_date=d.get('exit_date') or date.today(),
            holding_days=d.get('holding_days') or 0,
            gross_pct=d.get('gross_pct') or 0,
            outcome=d.get('outcome') or 'FAILED',
            rs_rating=d.get('rs_at_entry'),
            eps_rating=d.get('eps_at_entry'),
            comp_rating=d.get('comp_at_entry'),
            ad_rating=d.get('ad_at_entry'),
            base_stage=d.get('stage_at_entry'),
            base_depth=d.get('base_depth_at_entry'),
            base_length=d.get('base_length_at_entry'),
            pattern=d.get('pattern'),
            market_regime=d.get('market_regime_at_entry'),
            entry_grade=d.get('entry_grade'),
            entry_score=d.get('entry_score'),
            max_gain_pct=d.get('max_gain_pct'),
            max_drawdown_pct=d.get('max_drawdown_pct'),
        )

    def _outcome_distribution(self, outcomes: List[Dict]) -> Dict[str, int]:
        """Count outcomes by type."""
        dist = {}
        for o in outcomes:
            outcome = o.get('outcome', 'UNKNOWN')
            dist[outcome] = dist.get(outcome, 0) + 1
        return dist

    def _store_results(
        self, session: Session,
        analyses: List[FactorAnalysis],
        optimization: OptimizationResult,
        outcomes: List[Dict]
    ) -> LearnedWeights:
        """Store analysis and optimization results in learned_weights table."""

        # Calculate training period from outcomes
        dates = [o.get('entry_date') for o in outcomes if o.get('entry_date')]

        # Build factor analysis dict
        factor_dict = {}
        for a in analyses:
            factor_dict[a.factor_name] = {
                'correlation': a.correlation_return,
                'p_value': a.p_value_return,
                'is_significant': a.is_significant,
                'direction': a.recommended_direction
            }

        record = LearnedWeights(
            sample_size=len(outcomes),
            training_start=min(dates) if dates else None,
            training_end=max(dates) if dates else None,
            weights=json.dumps(optimization.weights),
            factor_analysis=json.dumps(factor_dict),
            accuracy=optimization.accuracy,
            precision_score=optimization.precision,
            recall_score=optimization.recall,
            f1_score=optimization.f1_score,
            baseline_accuracy=optimization.baseline_accuracy,
            improvement_pct=optimization.improvement_pct,
            confidence_level=1.0 - 0.1,  # Placeholder
            is_active=False,  # Never auto-activate
            notes=f"Auto-generated {datetime.now().isoformat()}"
        )

        session.add(record)
        session.flush()  # Get the ID

        logger.info(f"Stored learned weights id={record.id}, accuracy={record.accuracy}")
        return record

    def _generate_report(
        self,
        analyses: List[FactorAnalysis],
        optimization: OptimizationResult
    ) -> str:
        """Generate human-readable report."""
        lines = []
        lines.append("=" * 60)
        lines.append("LEARNING ENGINE ANALYSIS REPORT")
        lines.append("=" * 60)

        if optimization:
            lines.append(f"Sample size: {optimization.sample_size}")
            lines.append(f"Baseline accuracy: {optimization.baseline_accuracy:.1%}")
            lines.append(f"Optimized accuracy: {optimization.accuracy:.1%}")
            lines.append(f"Improvement: {optimization.improvement_pct:+.1f}%")
            lines.append("")

        lines.append("SIGNIFICANT FACTORS:")
        lines.append("-" * 40)
        significant = [a for a in analyses if a.is_significant]
        for a in sorted(significant, key=lambda x: abs(x.correlation_return), reverse=True):
            lines.append(f"  {a.factor_name:20} r={a.correlation_return:+.3f}")

        if optimization and optimization.weights:
            lines.append("")
            lines.append("SUGGESTED WEIGHTS:")
            lines.append("-" * 40)
            for factor, weight in sorted(optimization.weights.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {factor:20} {weight:.1f}")

        return "\n".join(lines)

    def activate_weights(self, weights_id: int) -> bool:
        """Activate a specific weight set (deactivate all others)."""
        session = self.db.get_new_session()
        try:
            # Deactivate all current
            session.query(LearnedWeights).filter(
                LearnedWeights.is_active == True
            ).update({
                'is_active': False,
                'deactivated_at': datetime.now()
            })

            # Activate requested
            weights = session.query(LearnedWeights).get(weights_id)
            if weights:
                weights.is_active = True
                weights.activated_at = datetime.now()
                session.commit()
                logger.info(f"Activated weights id={weights_id}")
                return True

            session.rollback()
            return False
        finally:
            session.close()

    def deactivate_weights(self, weights_id: int) -> bool:
        """Deactivate a weight set (revert to baseline)."""
        session = self.db.get_new_session()
        try:
            weights = session.query(LearnedWeights).get(weights_id)
            if weights:
                weights.is_active = False
                weights.deactivated_at = datetime.now()
                session.commit()
                return True
            return False
        finally:
            session.close()

    def get_active_weights(self) -> Optional[Dict]:
        """Get currently active learned weights, or None for baseline."""
        session = self.db.get_new_session()
        try:
            active = session.query(LearnedWeights).filter(
                LearnedWeights.is_active == True
            ).first()

            if active:
                return json.loads(active.weights)
            return None
        finally:
            session.close()

    def get_weight_history(self) -> List[Dict]:
        """Get all learned weight records for history display."""
        session = self.db.get_new_session()
        try:
            records = session.query(LearnedWeights).order_by(
                LearnedWeights.created_at.desc()
            ).all()

            return [{
                'id': r.id,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'sample_size': r.sample_size,
                'accuracy': r.accuracy,
                'baseline_accuracy': r.baseline_accuracy,
                'improvement_pct': r.improvement_pct,
                'is_active': r.is_active,
                'activated_at': r.activated_at.isoformat() if r.activated_at else None,
                'weights': json.loads(r.weights) if r.weights else {},
                'notes': r.notes
            } for r in records]
        finally:
            session.close()

    def get_outcome_summary(self) -> Dict:
        """Get summary of outcome data by source."""
        session = self.db.get_new_session()
        try:
            from sqlalchemy import func

            # Count by source
            source_counts = session.query(
                Outcome.source,
                func.count(Outcome.id)
            ).group_by(Outcome.source).all()

            # Count by outcome
            outcome_counts = session.query(
                Outcome.outcome,
                func.count(Outcome.id)
            ).filter(Outcome.outcome.isnot(None)).group_by(Outcome.outcome).all()

            # Average return
            avg_return = session.query(
                func.avg(Outcome.gross_pct)
            ).filter(Outcome.gross_pct.isnot(None)).scalar()

            # Date range
            date_range = session.query(
                func.min(Outcome.entry_date),
                func.max(Outcome.entry_date)
            ).first()

            return {
                'by_source': {s or 'unknown': c for s, c in source_counts},
                'by_outcome': {o or 'unknown': c for o, c in outcome_counts},
                'total': sum(c for _, c in source_counts),
                'avg_return_pct': round(avg_return, 2) if avg_return else 0,
                'date_range': {
                    'start': date_range[0].isoformat() if date_range[0] else None,
                    'end': date_range[1].isoformat() if date_range[1] else None
                }
            }
        finally:
            session.close()

    def get_grade_performance(self) -> List[Dict]:
        """Get performance breakdown by entry grade."""
        session = self.db.get_new_session()
        try:
            from sqlalchemy import func, case

            results = session.query(
                Outcome.entry_grade,
                func.count(Outcome.id).label('count'),
                func.avg(Outcome.gross_pct).label('avg_return'),
                func.sum(case(
                    (Outcome.outcome == 'SUCCESS', 1),
                    else_=0
                )).label('success_count')
            ).filter(
                Outcome.entry_grade.isnot(None),
                Outcome.outcome.isnot(None)
            ).group_by(Outcome.entry_grade).all()

            return [{
                'grade': r.entry_grade,
                'count': r.count,
                'avg_return': round(r.avg_return, 2) if r.avg_return else 0,
                'win_rate': round(r.success_count / r.count, 2) if r.count > 0 else 0
            } for r in results]
        finally:
            session.close()

    def rescore_outcomes(self, source: str = None) -> Dict:
        """
        Rescore all outcomes using current scoring rules.

        Args:
            source: Optional filter by source (e.g., 'swingtrader', 'live')

        Returns:
            Dict with stats on rescored outcomes
        """
        from canslim_monitor.utils.scoring import CANSLIMScorer

        session = self.db.get_new_session()
        scorer = CANSLIMScorer()

        stats = {
            'total': 0,
            'rescored': 0,
            'skipped_no_data': 0,
            'errors': 0,
            'grade_distribution': {}
        }

        try:
            query = session.query(Outcome).filter(Outcome.outcome.isnot(None))
            if source:
                query = query.filter(Outcome.source == source)

            outcomes = query.all()
            stats['total'] = len(outcomes)

            for outcome in outcomes:
                try:
                    # Build position_data dict for scoring
                    position_data = {
                        'rs_rating': outcome.rs_at_entry,
                        'pattern': self._guess_pattern_from_depth(outcome.base_depth_at_entry),
                        'stage': outcome.stage_at_entry or '2',  # Default to stage 2
                        'depth': outcome.base_depth_at_entry,
                        'length': outcome.base_length_at_entry,
                        'eps_rating': outcome.eps_at_entry,
                        'ad_rating': outcome.ad_at_entry,
                    }

                    # Skip if no RS rating (key scoring factor)
                    if not position_data['rs_rating']:
                        stats['skipped_no_data'] += 1
                        continue

                    # Calculate score
                    market_regime = outcome.market_regime_at_entry or 'NEUTRAL'
                    score, grade, details = scorer.calculate_score(position_data, market_regime)

                    # Update outcome
                    outcome.entry_score = score
                    outcome.entry_grade = grade

                    # Track grade distribution
                    stats['grade_distribution'][grade] = stats['grade_distribution'].get(grade, 0) + 1
                    stats['rescored'] += 1

                except Exception as e:
                    logger.error(f"Error rescoring {outcome.symbol}: {e}")
                    stats['errors'] += 1

            session.commit()
            logger.info(f"Rescored {stats['rescored']} outcomes: {stats['grade_distribution']}")

        finally:
            session.close()

        return stats

    def _guess_pattern_from_depth(self, depth: float) -> str:
        """
        Guess a pattern type based on base depth.
        Since backtest data doesn't have pattern names, we estimate.
        """
        if depth is None:
            return 'Consolidation'
        if depth <= 15:
            return 'Flat Base'
        elif depth <= 25:
            return 'Cup w/Handle'
        elif depth <= 35:
            return 'Double Bottom'
        else:
            return 'Consolidation'

    def get_rescore_preview(self, source: str = None, limit: int = 10) -> List[Dict]:
        """
        Preview what rescoring would produce without saving.

        Args:
            source: Optional filter by source
            limit: Max rows to preview

        Returns:
            List of dicts with symbol, old grade, new grade, score details
        """
        from canslim_monitor.utils.scoring import CANSLIMScorer

        session = self.db.get_new_session()
        scorer = CANSLIMScorer()

        previews = []

        try:
            query = session.query(Outcome).filter(
                Outcome.outcome.isnot(None),
                Outcome.rs_at_entry.isnot(None)
            )
            if source:
                query = query.filter(Outcome.source == source)

            outcomes = query.limit(limit).all()

            for outcome in outcomes:
                position_data = {
                    'rs_rating': outcome.rs_at_entry,
                    'pattern': self._guess_pattern_from_depth(outcome.base_depth_at_entry),
                    'stage': outcome.stage_at_entry or '2',
                    'depth': outcome.base_depth_at_entry,
                    'length': outcome.base_length_at_entry,
                    'eps_rating': outcome.eps_at_entry,
                    'ad_rating': outcome.ad_at_entry,
                }

                market_regime = outcome.market_regime_at_entry or 'NEUTRAL'
                score, grade, details = scorer.calculate_score(position_data, market_regime)

                previews.append({
                    'symbol': outcome.symbol,
                    'entry_date': outcome.entry_date.isoformat() if outcome.entry_date else None,
                    'old_grade': outcome.entry_grade,
                    'new_grade': grade,
                    'new_score': score,
                    'rs_rating': outcome.rs_at_entry,
                    'depth': outcome.base_depth_at_entry,
                    'outcome': outcome.outcome,
                    'return_pct': outcome.gross_pct,
                    'components': details.get('components', [])
                })

        finally:
            session.close()

        return previews
