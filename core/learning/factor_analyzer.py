"""
CANSLIM Monitor - Factor Analyzer

Analyzes which factors correlate with successful trading outcomes.
Uses statistical methods to determine factor importance.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import date
import statistics

from canslim_monitor.data.repositories.learning_repo import (
    LearningRepository, OutcomeData, FactorCorrelation
)

logger = logging.getLogger('canslim.learning.analyzer')


@dataclass
class FactorBucket:
    """Statistics for a bucket of factor values."""
    bucket_name: str  # 'low', 'mid', 'high'
    min_value: float
    max_value: float
    count: int
    win_count: int
    avg_return: float
    win_rate: float


@dataclass
class FactorAnalysis:
    """Complete analysis results for a single factor."""
    factor_name: str
    factor_type: str  # 'numeric', 'categorical', 'stage'
    sample_count: int

    # Correlation metrics
    correlation_return: float  # Pearson correlation with return %
    correlation_win_rate: float  # Point-biserial correlation with win/loss

    # Statistical significance
    p_value_return: float
    p_value_win_rate: float
    is_significant: bool

    # Bucket analysis (for numeric factors)
    buckets: List[FactorBucket] = field(default_factory=list)

    # Recommendation
    recommended_direction: str = 'none'  # 'higher', 'lower', 'none'
    recommended_weight: float = 0.0

    # Additional metrics
    missing_count: int = 0
    variance_explained: float = 0.0


# Factors to analyze
ANALYZABLE_FACTORS = {
    # Numeric CANSLIM factors
    'rs_rating': {'type': 'numeric', 'direction': 'higher', 'min': 0, 'max': 99},
    'eps_rating': {'type': 'numeric', 'direction': 'higher', 'min': 0, 'max': 99},
    'comp_rating': {'type': 'numeric', 'direction': 'higher', 'min': 0, 'max': 99},
    'industry_rank': {'type': 'numeric', 'direction': 'lower', 'min': 1, 'max': 197},
    'fund_count': {'type': 'numeric', 'direction': 'higher', 'min': 0, 'max': 5000},
    'funds_qtr_chg': {'type': 'numeric', 'direction': 'higher', 'min': -500, 'max': 500},

    # Base characteristics
    'base_depth': {'type': 'numeric', 'direction': 'lower', 'min': 0, 'max': 50},
    'base_length': {'type': 'numeric', 'direction': 'none', 'min': 1, 'max': 100},

    # Categorical factors
    'ad_rating': {'type': 'categorical', 'order': ['E', 'D-', 'D', 'D+', 'C-', 'C', 'C+', 'B-', 'B', 'B+', 'A-', 'A', 'A+']},
    'market_regime': {'type': 'categorical', 'order': ['BEARISH', 'NEUTRAL', 'BULLISH']},

    # Stage (special handling)
    'base_stage': {'type': 'stage', 'direction': 'lower'},

    # Entry score (for validation)
    'entry_score': {'type': 'numeric', 'direction': 'higher', 'min': 0, 'max': 100},
}


class FactorAnalyzer:
    """
    Analyzes factor correlations with trading outcomes.

    Uses statistical methods to determine which factors
    are predictive of success.
    """

    SIGNIFICANCE_THRESHOLD = 0.05
    MIN_BUCKET_SIZE = 5

    def __init__(self, repo: LearningRepository):
        self.repo = repo
        self._outcomes: List[OutcomeData] = []

    def load_outcomes(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        min_holding_days: int = 1
    ) -> int:
        """
        Load outcome data for analysis.

        Args:
            min_date: Minimum entry date
            max_date: Maximum entry date
            min_holding_days: Minimum holding period

        Returns:
            Number of outcomes loaded
        """
        self._outcomes = self.repo.get_outcomes_for_training(
            min_date=min_date,
            max_date=max_date,
            min_holding_days=min_holding_days
        )

        logger.info(f"Loaded {len(self._outcomes)} outcomes for analysis")
        return len(self._outcomes)

    def analyze_all_factors(self) -> List[FactorAnalysis]:
        """
        Analyze all configured factors.

        Returns:
            List of FactorAnalysis objects
        """
        if not self._outcomes:
            logger.warning("No outcomes loaded - call load_outcomes() first")
            return []

        results = []

        for factor_name, config in ANALYZABLE_FACTORS.items():
            try:
                analysis = self._analyze_factor(factor_name, config)
                if analysis:
                    results.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing factor {factor_name}: {e}")

        # Sort by absolute correlation
        results.sort(key=lambda x: abs(x.correlation_return), reverse=True)

        logger.info(f"Completed analysis of {len(results)} factors")
        return results

    def analyze_factor(self, factor_name: str) -> Optional[FactorAnalysis]:
        """Analyze a single factor."""
        if factor_name not in ANALYZABLE_FACTORS:
            logger.warning(f"Factor {factor_name} not in analyzable factors")
            return None

        return self._analyze_factor(factor_name, ANALYZABLE_FACTORS[factor_name])

    def _analyze_factor(
        self,
        factor_name: str,
        config: Dict[str, Any]
    ) -> Optional[FactorAnalysis]:
        """
        Analyze a single factor.

        Args:
            factor_name: Name of the factor
            config: Factor configuration

        Returns:
            FactorAnalysis or None if insufficient data
        """
        factor_type = config.get('type', 'numeric')

        # Extract values and returns
        values = []
        returns = []
        wins = []

        for outcome in self._outcomes:
            value = getattr(outcome, factor_name, None)

            # Handle stage parsing
            if factor_type == 'stage' and value:
                value = self._parse_stage(value)
            # Handle categorical ordering
            elif factor_type == 'categorical' and value:
                order = config.get('order', [])
                if value in order:
                    value = order.index(value)
                else:
                    value = None

            if value is not None:
                values.append(value)
                returns.append(outcome.gross_pct)
                wins.append(1 if outcome.outcome == 'SUCCESS' else 0)

        if len(values) < 10:
            logger.debug(f"Insufficient data for factor {factor_name}: {len(values)} samples")
            return None

        # Calculate correlations
        corr_return = self._pearson_correlation(values, returns)
        corr_win = self._point_biserial_correlation(values, wins)

        # Calculate p-values (using t-test approximation)
        n = len(values)
        p_return = self._correlation_p_value(corr_return, n)
        p_win = self._correlation_p_value(corr_win, n)

        is_significant = p_return < self.SIGNIFICANCE_THRESHOLD or p_win < self.SIGNIFICANCE_THRESHOLD

        # Bucket analysis for numeric factors
        buckets = []
        if factor_type in ('numeric', 'stage'):
            buckets = self._create_buckets(values, returns, wins)

        # Determine recommended direction
        expected_dir = config.get('direction', 'none')
        if is_significant:
            if corr_return > 0.05:
                recommended_dir = 'higher'
            elif corr_return < -0.05:
                recommended_dir = 'lower'
            else:
                recommended_dir = 'none'
        else:
            recommended_dir = 'none'

        # Calculate recommended weight based on correlation strength
        recommended_weight = abs(corr_return) * (1 if is_significant else 0.5)

        # Adjust for expected direction mismatch
        if expected_dir != 'none' and recommended_dir != 'none' and expected_dir != recommended_dir:
            logger.warning(
                f"Factor {factor_name}: expected direction {expected_dir} "
                f"but data suggests {recommended_dir}"
            )

        return FactorAnalysis(
            factor_name=factor_name,
            factor_type=factor_type,
            sample_count=len(values),
            correlation_return=corr_return,
            correlation_win_rate=corr_win,
            p_value_return=p_return,
            p_value_win_rate=p_win,
            is_significant=is_significant,
            buckets=buckets,
            recommended_direction=recommended_dir,
            recommended_weight=recommended_weight,
            missing_count=len(self._outcomes) - len(values)
        )

    def _create_buckets(
        self,
        values: List[float],
        returns: List[float],
        wins: List[int]
    ) -> List[FactorBucket]:
        """Create tercile buckets for analysis."""
        if len(values) < self.MIN_BUCKET_SIZE * 3:
            return []

        # Sort by value
        sorted_data = sorted(zip(values, returns, wins), key=lambda x: x[0])

        # Split into terciles
        n = len(sorted_data)
        tercile_size = n // 3

        buckets = []
        bucket_names = ['low', 'mid', 'high']

        for i, name in enumerate(bucket_names):
            if i == 2:
                # High bucket gets remainder
                bucket_data = sorted_data[i * tercile_size:]
            else:
                bucket_data = sorted_data[i * tercile_size:(i + 1) * tercile_size]

            if not bucket_data:
                continue

            bucket_values = [d[0] for d in bucket_data]
            bucket_returns = [d[1] for d in bucket_data]
            bucket_wins = [d[2] for d in bucket_data]

            win_count = sum(bucket_wins)
            count = len(bucket_data)

            buckets.append(FactorBucket(
                bucket_name=name,
                min_value=min(bucket_values),
                max_value=max(bucket_values),
                count=count,
                win_count=win_count,
                avg_return=statistics.mean(bucket_returns) if bucket_returns else 0,
                win_rate=win_count / count if count > 0 else 0
            ))

        return buckets

    def _parse_stage(self, stage_str: str) -> Optional[float]:
        """Parse stage string to numeric value (e.g., '2b(3)' -> 2.5)."""
        if not stage_str:
            return None

        try:
            # Remove parenthetical count
            stage = stage_str.split('(')[0].strip()

            # Extract number and modifier
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

    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        n = len(x)
        if n < 3:
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        # Calculate covariance and standard deviations
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
        std_x = (sum((xi - mean_x) ** 2 for xi in x) / n) ** 0.5
        std_y = (sum((yi - mean_y) ** 2 for yi in y) / n) ** 0.5

        if std_x == 0 or std_y == 0:
            return 0.0

        return cov / (std_x * std_y)

    def _point_biserial_correlation(self, x: List[float], y: List[int]) -> float:
        """Calculate point-biserial correlation (continuous vs binary)."""
        # This is equivalent to Pearson for binary y
        return self._pearson_correlation(x, [float(yi) for yi in y])

    def _correlation_p_value(self, r: float, n: int) -> float:
        """
        Approximate p-value for correlation using t-distribution.

        This is a simplified approximation - for production use,
        consider scipy.stats.pearsonr.
        """
        if n < 3 or abs(r) >= 1:
            return 1.0

        # t-statistic
        t = r * ((n - 2) ** 0.5) / ((1 - r ** 2) ** 0.5)

        # Simple approximation of two-tailed p-value
        # Using normal approximation for large n
        if n > 30:
            import math
            p = 2 * (1 - self._normal_cdf(abs(t)))
        else:
            # Very rough approximation for small n
            p = 2 * (1 - self._t_cdf(abs(t), n - 2))

        return min(1.0, max(0.0, p))

    def _normal_cdf(self, x: float) -> float:
        """Standard normal CDF approximation."""
        import math
        return 0.5 * (1 + math.erf(x / (2 ** 0.5)))

    def _t_cdf(self, t: float, df: int) -> float:
        """
        Approximation of Student's t CDF.
        Uses normal approximation for simplicity.
        """
        if df > 30:
            return self._normal_cdf(t)

        # Rough approximation
        x = t / ((df / (df - 2)) ** 0.5) if df > 2 else t
        return self._normal_cdf(x)

    def get_significant_factors(
        self,
        analyses: List[FactorAnalysis]
    ) -> List[FactorAnalysis]:
        """Get only statistically significant factors."""
        return [a for a in analyses if a.is_significant]

    def save_correlations(self, analyses: List[FactorAnalysis]):
        """Save correlation results to database."""
        if not analyses or not self._outcomes:
            return

        correlations = []
        for a in analyses:
            corr = FactorCorrelation(
                factor_name=a.factor_name,
                correlation_return=a.correlation_return,
                correlation_win_rate=a.correlation_win_rate,
                p_value_return=a.p_value_return,
                p_value_win_rate=a.p_value_win_rate,
                is_significant=a.is_significant,
                recommended_direction=a.recommended_direction,
                low_bucket_win_rate=a.buckets[0].win_rate if len(a.buckets) > 0 else None,
                mid_bucket_win_rate=a.buckets[1].win_rate if len(a.buckets) > 1 else None,
                high_bucket_win_rate=a.buckets[2].win_rate if len(a.buckets) > 2 else None,
            )
            correlations.append(corr)

        # Get date range from outcomes
        dates = [o.entry_date for o in self._outcomes if o.entry_date]
        sample_start = min(dates) if dates else date.today()
        sample_end = max(dates) if dates else date.today()

        self.repo.save_factor_correlations(
            correlations=correlations,
            sample_size=len(self._outcomes),
            sample_start=sample_start,
            sample_end=sample_end
        )

    def generate_report(self, analyses: List[FactorAnalysis]) -> str:
        """Generate a human-readable analysis report."""
        lines = []
        lines.append("=" * 60)
        lines.append("FACTOR CORRELATION ANALYSIS REPORT")
        lines.append("=" * 60)
        lines.append(f"Sample size: {len(self._outcomes)} outcomes")
        lines.append("")

        # Significant factors
        significant = self.get_significant_factors(analyses)
        lines.append(f"Significant factors: {len(significant)} / {len(analyses)}")
        lines.append("")

        lines.append("TOP FACTORS BY CORRELATION:")
        lines.append("-" * 60)

        for a in analyses[:10]:
            sig_marker = "*" if a.is_significant else " "
            lines.append(
                f"{sig_marker} {a.factor_name:20} "
                f"r={a.correlation_return:+.3f}  "
                f"p={a.p_value_return:.3f}  "
                f"dir={a.recommended_direction}"
            )

            # Show buckets if available
            if a.buckets:
                bucket_str = "  Buckets: " + " | ".join(
                    f"{b.bucket_name}:{b.win_rate:.1%}"
                    for b in a.buckets
                )
                lines.append(bucket_str)

        lines.append("")
        lines.append("* = statistically significant (p < 0.05)")

        return "\n".join(lines)
