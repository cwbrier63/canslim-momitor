"""
CANSLIM Monitor - Confidence Engine

Calculates statistical confidence levels for learned weights,
A/B test results, and factor analysis.
"""

import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger('canslim.learning.confidence')


@dataclass
class ConfidenceResult:
    """Statistical confidence calculation result."""
    metric_name: str
    value: float
    sample_size: int

    # Confidence interval
    confidence_level: float  # 0.90, 0.95, 0.99
    lower_bound: float
    upper_bound: float
    margin_of_error: float

    # Significance
    standard_error: float
    z_score: float
    p_value: float

    # Interpretation
    is_reliable: bool  # Meets minimum sample size
    confidence_rating: str  # 'high', 'medium', 'low', 'insufficient'


@dataclass
class ABTestSignificance:
    """A/B test statistical significance result."""
    control_rate: float
    treatment_rate: float
    difference: float
    relative_lift: float

    # Statistical significance
    z_score: float
    p_value: float
    is_significant: bool

    # Confidence interval for difference
    diff_lower: float
    diff_upper: float

    # Power analysis
    achieved_power: float
    recommended_sample: int


class ConfidenceEngine:
    """
    Calculates statistical confidence for trading analysis.

    Provides confidence intervals, significance testing, and
    power analysis for informed decision making.
    """

    # Minimum samples for various analyses
    MIN_SAMPLES_BASIC = 10
    MIN_SAMPLES_RELIABLE = 30
    MIN_SAMPLES_HIGH_CONFIDENCE = 100

    # Z-scores for confidence levels
    Z_SCORES = {
        0.80: 1.282,
        0.90: 1.645,
        0.95: 1.960,
        0.99: 2.576
    }

    def calculate_proportion_confidence(
        self,
        successes: int,
        total: int,
        confidence_level: float = 0.95,
        metric_name: str = "win_rate"
    ) -> ConfidenceResult:
        """
        Calculate confidence interval for a proportion (e.g., win rate).

        Uses Wilson score interval for better small-sample behavior.

        Args:
            successes: Number of successful outcomes
            total: Total number of outcomes
            confidence_level: Confidence level (0.90, 0.95, 0.99)
            metric_name: Name of the metric

        Returns:
            ConfidenceResult with confidence interval
        """
        if total == 0:
            return ConfidenceResult(
                metric_name=metric_name,
                value=0,
                sample_size=0,
                confidence_level=confidence_level,
                lower_bound=0,
                upper_bound=0,
                margin_of_error=0,
                standard_error=0,
                z_score=0,
                p_value=1,
                is_reliable=False,
                confidence_rating='insufficient'
            )

        p = successes / total
        n = total
        z = self.Z_SCORES.get(confidence_level, 1.96)

        # Wilson score interval
        denominator = 1 + z**2 / n
        center = (p + z**2 / (2 * n)) / denominator
        margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

        lower = max(0, center - margin)
        upper = min(1, center + margin)

        # Standard error
        se = math.sqrt(p * (1 - p) / n) if n > 0 else 0

        # Z-score for testing against 0.5 (random)
        z_score = (p - 0.5) / se if se > 0 else 0
        p_value = 2 * (1 - self._normal_cdf(abs(z_score)))

        # Determine confidence rating
        if n < self.MIN_SAMPLES_BASIC:
            rating = 'insufficient'
            is_reliable = False
        elif n < self.MIN_SAMPLES_RELIABLE:
            rating = 'low'
            is_reliable = False
        elif n < self.MIN_SAMPLES_HIGH_CONFIDENCE:
            rating = 'medium'
            is_reliable = True
        else:
            rating = 'high'
            is_reliable = True

        return ConfidenceResult(
            metric_name=metric_name,
            value=p,
            sample_size=n,
            confidence_level=confidence_level,
            lower_bound=lower,
            upper_bound=upper,
            margin_of_error=margin,
            standard_error=se,
            z_score=z_score,
            p_value=p_value,
            is_reliable=is_reliable,
            confidence_rating=rating
        )

    def calculate_mean_confidence(
        self,
        values: List[float],
        confidence_level: float = 0.95,
        metric_name: str = "avg_return"
    ) -> ConfidenceResult:
        """
        Calculate confidence interval for a mean value.

        Args:
            values: List of values
            confidence_level: Confidence level
            metric_name: Name of the metric

        Returns:
            ConfidenceResult with confidence interval
        """
        n = len(values)

        if n == 0:
            return ConfidenceResult(
                metric_name=metric_name,
                value=0,
                sample_size=0,
                confidence_level=confidence_level,
                lower_bound=0,
                upper_bound=0,
                margin_of_error=0,
                standard_error=0,
                z_score=0,
                p_value=1,
                is_reliable=False,
                confidence_rating='insufficient'
            )

        mean = sum(values) / n
        z = self.Z_SCORES.get(confidence_level, 1.96)

        # Sample standard deviation
        variance = sum((x - mean) ** 2 for x in values) / (n - 1) if n > 1 else 0
        std = math.sqrt(variance)

        # Standard error of mean
        se = std / math.sqrt(n) if n > 0 else 0

        # Confidence interval
        margin = z * se
        lower = mean - margin
        upper = mean + margin

        # Z-score for testing against 0
        z_score = mean / se if se > 0 else 0
        p_value = 2 * (1 - self._normal_cdf(abs(z_score)))

        # Determine confidence rating
        if n < self.MIN_SAMPLES_BASIC:
            rating = 'insufficient'
            is_reliable = False
        elif n < self.MIN_SAMPLES_RELIABLE:
            rating = 'low'
            is_reliable = False
        elif n < self.MIN_SAMPLES_HIGH_CONFIDENCE:
            rating = 'medium'
            is_reliable = True
        else:
            rating = 'high'
            is_reliable = True

        return ConfidenceResult(
            metric_name=metric_name,
            value=mean,
            sample_size=n,
            confidence_level=confidence_level,
            lower_bound=lower,
            upper_bound=upper,
            margin_of_error=margin,
            standard_error=se,
            z_score=z_score,
            p_value=p_value,
            is_reliable=is_reliable,
            confidence_rating=rating
        )

    def test_ab_significance(
        self,
        control_successes: int,
        control_total: int,
        treatment_successes: int,
        treatment_total: int,
        alpha: float = 0.05
    ) -> ABTestSignificance:
        """
        Test statistical significance of A/B test results.

        Uses two-proportion z-test.

        Args:
            control_successes: Wins in control group
            control_total: Total in control group
            treatment_successes: Wins in treatment group
            treatment_total: Total in treatment group
            alpha: Significance level (default 0.05)

        Returns:
            ABTestSignificance with test results
        """
        # Calculate proportions
        p1 = control_successes / control_total if control_total > 0 else 0
        p2 = treatment_successes / treatment_total if treatment_total > 0 else 0
        n1 = control_total
        n2 = treatment_total

        # Difference
        diff = p2 - p1
        relative_lift = (p2 - p1) / p1 * 100 if p1 > 0 else 0

        # Pooled proportion
        pooled_p = (control_successes + treatment_successes) / (n1 + n2) if (n1 + n2) > 0 else 0

        # Standard error of difference
        if n1 > 0 and n2 > 0:
            se = math.sqrt(pooled_p * (1 - pooled_p) * (1/n1 + 1/n2))
        else:
            se = 0

        # Z-score
        z_score = diff / se if se > 0 else 0

        # P-value (two-tailed)
        p_value = 2 * (1 - self._normal_cdf(abs(z_score)))

        # Is significant?
        is_significant = p_value < alpha

        # Confidence interval for difference
        z_crit = self.Z_SCORES.get(1 - alpha, 1.96)
        diff_margin = z_crit * se
        diff_lower = diff - diff_margin
        diff_upper = diff + diff_margin

        # Power analysis
        achieved_power = self._calculate_power(p1, p2, n1, n2, alpha)
        recommended_sample = self._calculate_required_sample(
            p1, abs(diff) if diff != 0 else 0.05, alpha, 0.80
        )

        return ABTestSignificance(
            control_rate=p1,
            treatment_rate=p2,
            difference=diff,
            relative_lift=relative_lift,
            z_score=z_score,
            p_value=p_value,
            is_significant=is_significant,
            diff_lower=diff_lower,
            diff_upper=diff_upper,
            achieved_power=achieved_power,
            recommended_sample=recommended_sample
        )

    def test_mean_difference(
        self,
        control_values: List[float],
        treatment_values: List[float],
        alpha: float = 0.05
    ) -> Dict[str, float]:
        """
        Test difference in means between two groups.

        Uses Welch's t-test (unequal variances).

        Args:
            control_values: Values in control group
            treatment_values: Values in treatment group
            alpha: Significance level

        Returns:
            Dictionary with test results
        """
        n1 = len(control_values)
        n2 = len(treatment_values)

        if n1 < 2 or n2 < 2:
            return {
                'control_mean': sum(control_values) / n1 if n1 > 0 else 0,
                'treatment_mean': sum(treatment_values) / n2 if n2 > 0 else 0,
                'difference': 0,
                't_statistic': 0,
                'p_value': 1,
                'is_significant': False
            }

        mean1 = sum(control_values) / n1
        mean2 = sum(treatment_values) / n2

        var1 = sum((x - mean1) ** 2 for x in control_values) / (n1 - 1)
        var2 = sum((x - mean2) ** 2 for x in treatment_values) / (n2 - 1)

        # Standard error
        se = math.sqrt(var1 / n1 + var2 / n2)

        # t-statistic
        t = (mean2 - mean1) / se if se > 0 else 0

        # Degrees of freedom (Welch-Satterthwaite)
        if var1 / n1 + var2 / n2 > 0:
            df = ((var1 / n1 + var2 / n2) ** 2) / (
                (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
            )
        else:
            df = n1 + n2 - 2

        # P-value (approximation using normal for large samples)
        p_value = 2 * (1 - self._normal_cdf(abs(t)))

        return {
            'control_mean': mean1,
            'treatment_mean': mean2,
            'difference': mean2 - mean1,
            't_statistic': t,
            'p_value': p_value,
            'is_significant': p_value < alpha,
            'degrees_freedom': df
        }

    def calculate_minimum_sample_size(
        self,
        baseline_rate: float,
        minimum_detectable_effect: float,
        alpha: float = 0.05,
        power: float = 0.80
    ) -> int:
        """
        Calculate minimum sample size needed per group.

        Args:
            baseline_rate: Expected rate in control group
            minimum_detectable_effect: Minimum difference to detect
            alpha: Significance level
            power: Desired statistical power

        Returns:
            Sample size per group
        """
        return self._calculate_required_sample(
            baseline_rate, minimum_detectable_effect, alpha, power
        )

    def get_confidence_recommendation(
        self,
        result: ConfidenceResult
    ) -> str:
        """Get human-readable recommendation based on confidence."""
        if result.confidence_rating == 'insufficient':
            return f"Insufficient data ({result.sample_size} samples). Need at least {self.MIN_SAMPLES_BASIC}."

        if result.confidence_rating == 'low':
            return f"Low confidence ({result.sample_size} samples). Results may not be reliable."

        if result.confidence_rating == 'medium':
            return f"Moderate confidence ({result.sample_size} samples). Results are reasonably reliable."

        return f"High confidence ({result.sample_size} samples). Results are statistically reliable."

    def _normal_cdf(self, x: float) -> float:
        """Standard normal CDF using error function approximation."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def _calculate_power(
        self,
        p1: float,
        p2: float,
        n1: int,
        n2: int,
        alpha: float
    ) -> float:
        """Calculate achieved statistical power."""
        if n1 == 0 or n2 == 0 or p1 == p2:
            return 0

        # Effect size
        diff = abs(p2 - p1)

        # Pooled standard error
        pooled_p = (p1 + p2) / 2
        se = math.sqrt(pooled_p * (1 - pooled_p) * (1/n1 + 1/n2))

        if se == 0:
            return 0

        # Critical value
        z_crit = self.Z_SCORES.get(1 - alpha, 1.96)

        # Power calculation
        z_power = (diff / se) - z_crit
        power = self._normal_cdf(z_power)

        return min(1.0, max(0.0, power))

    def _calculate_required_sample(
        self,
        p1: float,
        mde: float,
        alpha: float,
        power: float
    ) -> int:
        """Calculate required sample size per group."""
        if mde == 0:
            return 10000  # Return large number

        p2 = p1 + mde

        z_alpha = self.Z_SCORES.get(1 - alpha/2, 1.96)
        z_power = self.Z_SCORES.get(power, 0.84)

        # Sample size formula for two proportions
        pooled_p = (p1 + p2) / 2
        numerator = (z_alpha * math.sqrt(2 * pooled_p * (1 - pooled_p)) +
                     z_power * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
        denominator = mde ** 2

        n = numerator / denominator if denominator > 0 else 10000

        return max(10, int(math.ceil(n)))

    def format_confidence_interval(
        self,
        result: ConfidenceResult,
        as_percentage: bool = True
    ) -> str:
        """Format confidence interval as string."""
        if as_percentage:
            return (
                f"{result.value:.1%} "
                f"({result.confidence_level:.0%} CI: "
                f"{result.lower_bound:.1%} - {result.upper_bound:.1%})"
            )
        else:
            return (
                f"{result.value:.2f} "
                f"({result.confidence_level:.0%} CI: "
                f"{result.lower_bound:.2f} - {result.upper_bound:.2f})"
            )
