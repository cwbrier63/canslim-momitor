"""
CANSLIM Monitor - Learning Repository

Provides data access for the learning engine components:
- Outcome data for training
- Factor correlation storage
- A/B test management
- Learned weights storage
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from sqlalchemy import and_, desc, func, text
from sqlalchemy.orm import Session

from canslim_monitor.data.models import (
    Outcome, LearnedWeights, Position, Alert, DailySnapshot
)

logger = logging.getLogger('canslim.learning')


@dataclass
class OutcomeData:
    """Structured outcome data for factor analysis."""
    position_id: int
    symbol: str
    entry_date: date
    exit_date: date
    holding_days: int
    gross_pct: float
    outcome: str  # SUCCESS, PARTIAL, STOPPED, FAILED

    # CANSLIM factors at entry
    rs_rating: Optional[int] = None
    eps_rating: Optional[int] = None
    comp_rating: Optional[int] = None
    ad_rating: Optional[str] = None
    industry_rank: Optional[int] = None
    fund_count: Optional[int] = None
    funds_qtr_chg: Optional[int] = None

    # Base characteristics
    base_stage: Optional[str] = None
    base_depth: Optional[float] = None
    base_length: Optional[int] = None
    pattern: Optional[str] = None

    # Market context
    market_regime: Optional[str] = None

    # Scoring
    entry_grade: Optional[str] = None
    entry_score: Optional[int] = None

    # Risk metrics
    max_gain_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None


@dataclass
class ABTest:
    """A/B test configuration and status."""
    id: int
    name: str
    status: str  # draft, running, completed, cancelled
    control_weights_id: int
    treatment_weights_id: int
    split_ratio: float
    min_sample_size: int
    control_count: int
    treatment_count: int
    control_win_rate: Optional[float] = None
    treatment_win_rate: Optional[float] = None
    control_avg_return: Optional[float] = None
    treatment_avg_return: Optional[float] = None
    p_value: Optional[float] = None
    is_significant: bool = False
    winner: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


@dataclass
class ABTestAssignment:
    """Position assignment to A/B test group."""
    id: int
    ab_test_id: int
    position_id: int
    group_name: str  # 'control' or 'treatment'
    weights_id: int
    score_at_assignment: Optional[int] = None
    grade_at_assignment: Optional[str] = None
    outcome: Optional[str] = None
    return_pct: Optional[float] = None


@dataclass
class FactorCorrelation:
    """Factor correlation analysis result."""
    factor_name: str
    correlation_return: float
    correlation_win_rate: float
    p_value_return: float
    p_value_win_rate: float
    is_significant: bool
    recommended_direction: str  # 'higher', 'lower', 'none'
    low_bucket_win_rate: Optional[float] = None
    mid_bucket_win_rate: Optional[float] = None
    high_bucket_win_rate: Optional[float] = None


class LearningRepository:
    """Repository for learning engine data access."""

    def __init__(self, session: Session):
        self.session = session

    # =========================================
    # Outcome Data Access
    # =========================================

    def get_outcomes_for_training(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        min_holding_days: int = 1,
        exclude_positions: Optional[List[int]] = None
    ) -> List[OutcomeData]:
        """
        Get outcome data suitable for factor analysis and training.

        Args:
            min_date: Minimum entry date
            max_date: Maximum entry date
            min_holding_days: Minimum holding period
            exclude_positions: Position IDs to exclude (e.g., test set)

        Returns:
            List of OutcomeData objects
        """
        query = self.session.query(Outcome).filter(
            Outcome.holding_days >= min_holding_days,
            Outcome.gross_pct.isnot(None),
            Outcome.outcome.isnot(None)
        )

        if min_date:
            query = query.filter(Outcome.entry_date >= min_date)
        if max_date:
            query = query.filter(Outcome.entry_date <= max_date)
        if exclude_positions:
            query = query.filter(~Outcome.position_id.in_(exclude_positions))

        outcomes = query.all()

        return [
            OutcomeData(
                position_id=o.position_id,
                symbol=o.symbol,
                entry_date=o.entry_date,
                exit_date=o.exit_date,
                holding_days=o.holding_days,
                gross_pct=o.gross_pct,
                outcome=o.outcome,
                rs_rating=o.rs_at_entry,
                eps_rating=o.eps_at_entry,
                comp_rating=o.comp_at_entry,
                ad_rating=o.ad_at_entry,
                industry_rank=o.industry_rank_at_entry,
                fund_count=o.fund_count_at_entry,
                funds_qtr_chg=o.funds_qtr_chg_at_entry,
                base_stage=o.stage_at_entry,
                base_depth=o.base_depth_at_entry,
                base_length=o.base_length_at_entry,
                pattern=o.pattern,
                market_regime=o.market_regime_at_entry,
                entry_grade=o.entry_grade,
                entry_score=o.entry_score,
                max_gain_pct=o.max_gain_pct,
                max_drawdown_pct=o.max_drawdown_pct,
            )
            for o in outcomes
        ]

    def get_outcome_count(self) -> int:
        """Get total number of outcomes."""
        return self.session.query(func.count(Outcome.id)).scalar() or 0

    def get_outcome_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics on outcomes."""
        from sqlalchemy import case

        results = self.session.query(
            func.count(Outcome.id).label('total'),
            func.avg(Outcome.gross_pct).label('avg_return'),
            func.sum(case(
                (Outcome.outcome == 'SUCCESS', 1),
                else_=0
            )).label('success_count'),
            func.sum(case(
                (Outcome.outcome == 'STOPPED', 1),
                else_=0
            )).label('stopped_count'),
            func.min(Outcome.entry_date).label('earliest_entry'),
            func.max(Outcome.entry_date).label('latest_entry'),
        ).first()

        total = results.total or 0
        success_count = results.success_count or 0

        return {
            'total_outcomes': total,
            'avg_return': results.avg_return,
            'win_rate': success_count / total if total > 0 else 0,
            'success_count': success_count,
            'stopped_count': results.stopped_count or 0,
            'earliest_entry': results.earliest_entry,
            'latest_entry': results.latest_entry,
        }

    # =========================================
    # Learned Weights Management
    # =========================================

    def get_active_weights(self) -> Optional[LearnedWeights]:
        """Get the currently active learned weights."""
        return self.session.query(LearnedWeights).filter(
            LearnedWeights.is_active == True
        ).first()

    def get_all_weights(self, limit: int = 50) -> List[LearnedWeights]:
        """Get all learned weights, most recent first."""
        return self.session.query(LearnedWeights).order_by(
            desc(LearnedWeights.created_at)
        ).limit(limit).all()

    def create_weights(
        self,
        weights: Dict[str, float],
        factor_analysis: Dict[str, Any],
        metrics: Dict[str, float],
        sample_size: int,
        training_start: date,
        training_end: date,
        parent_weights_id: Optional[int] = None,
        notes: str = None
    ) -> LearnedWeights:
        """
        Create a new learned weights record.

        Args:
            weights: Factor weights dictionary
            factor_analysis: Per-factor analysis results
            metrics: Performance metrics (accuracy, precision, etc.)
            sample_size: Number of outcomes used in training
            training_start: Start of training period
            training_end: End of training period
            parent_weights_id: ID of weights this was derived from
            notes: Optional notes

        Returns:
            Created LearnedWeights record
        """
        # Get next version number
        max_version = self.session.query(
            func.max(LearnedWeights.version)
        ).scalar() or 0

        learned = LearnedWeights(
            weights=json.dumps(weights),
            factor_analysis=json.dumps(factor_analysis),
            sample_size=sample_size,
            training_start=training_start,
            training_end=training_end,
            accuracy=metrics.get('accuracy'),
            precision_score=metrics.get('precision'),
            recall_score=metrics.get('recall'),
            f1_score=metrics.get('f1'),
            baseline_accuracy=metrics.get('baseline_accuracy'),
            improvement_pct=metrics.get('improvement_pct'),
            confidence_level=metrics.get('confidence_level'),
            version=max_version + 1,
            parent_weights_id=parent_weights_id,
            notes=notes,
            is_active=False
        )

        self.session.add(learned)
        self.session.flush()

        logger.info(f"Created learned weights v{learned.version} with {sample_size} samples")
        return learned

    def activate_weights(self, weights_id: int) -> bool:
        """
        Activate a specific weights record, deactivating others.

        Args:
            weights_id: ID of weights to activate

        Returns:
            True if successful
        """
        # Deactivate all weights
        self.session.query(LearnedWeights).filter(
            LearnedWeights.is_active == True
        ).update({
            'is_active': False,
            'deactivated_at': datetime.now()
        })

        # Activate the specified weights
        weights = self.session.query(LearnedWeights).get(weights_id)
        if weights:
            weights.is_active = True
            weights.activated_at = datetime.now()
            self.session.flush()
            logger.info(f"Activated weights v{weights.version} (id={weights_id})")
            return True

        return False

    def get_weights_by_id(self, weights_id: int) -> Optional[LearnedWeights]:
        """Get a specific weights record by ID."""
        return self.session.query(LearnedWeights).get(weights_id)

    # =========================================
    # A/B Test Management
    # =========================================

    def create_ab_test(
        self,
        name: str,
        control_weights_id: int,
        treatment_weights_id: int,
        split_ratio: float = 0.5,
        min_sample_size: int = 30,
        description: str = None
    ) -> ABTest:
        """
        Create a new A/B test.

        Args:
            name: Test name
            control_weights_id: ID of control (baseline) weights
            treatment_weights_id: ID of treatment (new) weights
            split_ratio: Fraction assigned to treatment (0-1)
            min_sample_size: Minimum positions per group before analysis
            description: Optional description

        Returns:
            Created ABTest object
        """
        self.session.execute(text("""
            INSERT INTO ab_tests (
                name, description, control_weights_id, treatment_weights_id,
                split_ratio, min_sample_size, status
            ) VALUES (
                :name, :description, :control_id, :treatment_id,
                :split_ratio, :min_sample, 'draft'
            )
        """), {
            'name': name,
            'description': description,
            'control_id': control_weights_id,
            'treatment_id': treatment_weights_id,
            'split_ratio': split_ratio,
            'min_sample': min_sample_size
        })
        self.session.flush()

        # Get the created test
        result = self.session.execute(text(
            "SELECT id FROM ab_tests ORDER BY id DESC LIMIT 1"
        )).fetchone()

        test_id = result[0]
        logger.info(f"Created A/B test '{name}' (id={test_id})")

        return self.get_ab_test(test_id)

    def get_ab_test(self, test_id: int) -> Optional[ABTest]:
        """Get an A/B test by ID."""
        result = self.session.execute(text("""
            SELECT id, name, status, control_weights_id, treatment_weights_id,
                   split_ratio, min_sample_size, control_count, treatment_count,
                   control_win_rate, treatment_win_rate, control_avg_return,
                   treatment_avg_return, p_value, is_significant, winner,
                   started_at, ended_at
            FROM ab_tests WHERE id = :id
        """), {'id': test_id}).fetchone()

        if not result:
            return None

        return ABTest(
            id=result[0],
            name=result[1],
            status=result[2],
            control_weights_id=result[3],
            treatment_weights_id=result[4],
            split_ratio=result[5],
            min_sample_size=result[6],
            control_count=result[7],
            treatment_count=result[8],
            control_win_rate=result[9],
            treatment_win_rate=result[10],
            control_avg_return=result[11],
            treatment_avg_return=result[12],
            p_value=result[13],
            is_significant=bool(result[14]),
            winner=result[15],
            started_at=result[16],
            ended_at=result[17],
        )

    def get_running_ab_test(self) -> Optional[ABTest]:
        """Get the currently running A/B test, if any."""
        result = self.session.execute(text("""
            SELECT id FROM ab_tests WHERE status = 'running' LIMIT 1
        """)).fetchone()

        if result:
            return self.get_ab_test(result[0])
        return None

    def start_ab_test(self, test_id: int) -> bool:
        """Start an A/B test."""
        self.session.execute(text("""
            UPDATE ab_tests
            SET status = 'running', started_at = :now
            WHERE id = :id AND status = 'draft'
        """), {'id': test_id, 'now': datetime.now()})
        self.session.flush()

        logger.info(f"Started A/B test {test_id}")
        return True

    def end_ab_test(self, test_id: int, winner: str = None) -> bool:
        """End an A/B test."""
        self.session.execute(text("""
            UPDATE ab_tests
            SET status = 'completed', ended_at = :now, winner = :winner,
                winner_selected_at = :now
            WHERE id = :id AND status = 'running'
        """), {'id': test_id, 'now': datetime.now(), 'winner': winner})
        self.session.flush()

        logger.info(f"Ended A/B test {test_id}, winner={winner}")
        return True

    def update_ab_test_stats(
        self,
        test_id: int,
        control_count: int,
        treatment_count: int,
        control_win_rate: float,
        treatment_win_rate: float,
        control_avg_return: float,
        treatment_avg_return: float,
        p_value: float,
        is_significant: bool
    ):
        """Update A/B test statistics."""
        self.session.execute(text("""
            UPDATE ab_tests
            SET control_count = :control_count,
                treatment_count = :treatment_count,
                control_win_rate = :control_wr,
                treatment_win_rate = :treatment_wr,
                control_avg_return = :control_ret,
                treatment_avg_return = :treatment_ret,
                p_value = :p_value,
                is_significant = :is_sig,
                updated_at = :now
            WHERE id = :id
        """), {
            'id': test_id,
            'control_count': control_count,
            'treatment_count': treatment_count,
            'control_wr': control_win_rate,
            'treatment_wr': treatment_win_rate,
            'control_ret': control_avg_return,
            'treatment_ret': treatment_avg_return,
            'p_value': p_value,
            'is_sig': 1 if is_significant else 0,
            'now': datetime.now()
        })
        self.session.flush()

    # =========================================
    # A/B Test Assignments
    # =========================================

    def assign_to_ab_test(
        self,
        test_id: int,
        position_id: int,
        group_name: str,
        weights_id: int,
        score: int = None,
        grade: str = None
    ) -> ABTestAssignment:
        """
        Assign a position to an A/B test group.

        Args:
            test_id: A/B test ID
            position_id: Position ID
            group_name: 'control' or 'treatment'
            weights_id: Weights used for scoring
            score: Score at assignment
            grade: Grade at assignment

        Returns:
            Created assignment
        """
        self.session.execute(text("""
            INSERT INTO ab_test_assignments (
                ab_test_id, position_id, group_name, weights_id,
                score_at_assignment, grade_at_assignment
            ) VALUES (
                :test_id, :position_id, :group_name, :weights_id,
                :score, :grade
            )
        """), {
            'test_id': test_id,
            'position_id': position_id,
            'group_name': group_name,
            'weights_id': weights_id,
            'score': score,
            'grade': grade
        })
        self.session.flush()

        logger.debug(f"Assigned position {position_id} to {group_name} group in test {test_id}")

        return ABTestAssignment(
            id=0,  # Not fetched
            ab_test_id=test_id,
            position_id=position_id,
            group_name=group_name,
            weights_id=weights_id,
            score_at_assignment=score,
            grade_at_assignment=grade
        )

    def get_position_ab_assignment(self, position_id: int) -> Optional[ABTestAssignment]:
        """Get A/B test assignment for a position."""
        result = self.session.execute(text("""
            SELECT a.id, a.ab_test_id, a.position_id, a.group_name, a.weights_id,
                   a.score_at_assignment, a.grade_at_assignment, a.outcome, a.return_pct
            FROM ab_test_assignments a
            JOIN ab_tests t ON a.ab_test_id = t.id
            WHERE a.position_id = :position_id AND t.status = 'running'
            LIMIT 1
        """), {'position_id': position_id}).fetchone()

        if not result:
            return None

        return ABTestAssignment(
            id=result[0],
            ab_test_id=result[1],
            position_id=result[2],
            group_name=result[3],
            weights_id=result[4],
            score_at_assignment=result[5],
            grade_at_assignment=result[6],
            outcome=result[7],
            return_pct=result[8]
        )

    def record_ab_test_outcome(
        self,
        position_id: int,
        outcome: str,
        return_pct: float,
        holding_days: int
    ):
        """Record the outcome for a position in an A/B test."""
        self.session.execute(text("""
            UPDATE ab_test_assignments
            SET outcome = :outcome, return_pct = :return_pct,
                holding_days = :holding_days, outcome_recorded_at = :now
            WHERE position_id = :position_id AND outcome IS NULL
        """), {
            'position_id': position_id,
            'outcome': outcome,
            'return_pct': return_pct,
            'holding_days': holding_days,
            'now': datetime.now()
        })
        self.session.flush()

    def get_ab_test_results(self, test_id: int) -> Dict[str, List[ABTestAssignment]]:
        """Get all completed assignments for an A/B test, grouped by group."""
        results = self.session.execute(text("""
            SELECT id, ab_test_id, position_id, group_name, weights_id,
                   score_at_assignment, grade_at_assignment, outcome, return_pct
            FROM ab_test_assignments
            WHERE ab_test_id = :test_id AND outcome IS NOT NULL
            ORDER BY group_name
        """), {'test_id': test_id}).fetchall()

        grouped = {'control': [], 'treatment': []}

        for r in results:
            assignment = ABTestAssignment(
                id=r[0],
                ab_test_id=r[1],
                position_id=r[2],
                group_name=r[3],
                weights_id=r[4],
                score_at_assignment=r[5],
                grade_at_assignment=r[6],
                outcome=r[7],
                return_pct=r[8]
            )
            grouped[assignment.group_name].append(assignment)

        return grouped

    # =========================================
    # Factor Correlation Storage
    # =========================================

    def save_factor_correlations(
        self,
        correlations: List[FactorCorrelation],
        sample_size: int,
        sample_start: date,
        sample_end: date
    ):
        """
        Save factor correlation analysis results.

        Args:
            correlations: List of correlation results
            sample_size: Number of outcomes analyzed
            sample_start: Start of analysis period
            sample_end: End of analysis period
        """
        analysis_date = date.today()

        for corr in correlations:
            self.session.execute(text("""
                INSERT INTO factor_correlations (
                    analysis_date, sample_start_date, sample_end_date, sample_size,
                    factor_name, correlation_return, correlation_win_rate,
                    p_value_return, p_value_win_rate, is_significant,
                    recommended_direction, low_bucket_win_rate, mid_bucket_win_rate,
                    high_bucket_win_rate
                ) VALUES (
                    :analysis_date, :sample_start, :sample_end, :sample_size,
                    :factor_name, :corr_return, :corr_wr, :p_return, :p_wr,
                    :is_sig, :direction, :low_wr, :mid_wr, :high_wr
                )
            """), {
                'analysis_date': analysis_date,
                'sample_start': sample_start,
                'sample_end': sample_end,
                'sample_size': sample_size,
                'factor_name': corr.factor_name,
                'corr_return': corr.correlation_return,
                'corr_wr': corr.correlation_win_rate,
                'p_return': corr.p_value_return,
                'p_wr': corr.p_value_win_rate,
                'is_sig': 1 if corr.is_significant else 0,
                'direction': corr.recommended_direction,
                'low_wr': corr.low_bucket_win_rate,
                'mid_wr': corr.mid_bucket_win_rate,
                'high_wr': corr.high_bucket_win_rate
            })

        self.session.flush()
        logger.info(f"Saved {len(correlations)} factor correlations")

    def get_latest_factor_correlations(self) -> List[FactorCorrelation]:
        """Get the most recent factor correlation analysis."""
        # Get the latest analysis date
        result = self.session.execute(text("""
            SELECT MAX(analysis_date) FROM factor_correlations
        """)).fetchone()

        if not result or not result[0]:
            return []

        latest_date = result[0]

        results = self.session.execute(text("""
            SELECT factor_name, correlation_return, correlation_win_rate,
                   p_value_return, p_value_win_rate, is_significant,
                   recommended_direction, low_bucket_win_rate, mid_bucket_win_rate,
                   high_bucket_win_rate
            FROM factor_correlations
            WHERE analysis_date = :date
            ORDER BY ABS(correlation_return) DESC
        """), {'date': latest_date}).fetchall()

        return [
            FactorCorrelation(
                factor_name=r[0],
                correlation_return=r[1],
                correlation_win_rate=r[2],
                p_value_return=r[3],
                p_value_win_rate=r[4],
                is_significant=bool(r[5]),
                recommended_direction=r[6],
                low_bucket_win_rate=r[7],
                mid_bucket_win_rate=r[8],
                high_bucket_win_rate=r[9]
            )
            for r in results
        ]
