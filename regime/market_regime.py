"""
Market Regime Calculator

Calculates daily market regime based on:
1. Distribution day counts (SPY, QQQ)
2. Distribution day trend (improving/worsening)
3. Overnight futures trends (ES, NQ, YM)
4. Follow-Through Day status (confirms uptrend after correction)
5. Market phase (Confirmed Uptrend, Rally Attempt, Correction)

Produces a weighted composite score and regime classification:
- BULLISH: Favorable conditions for new positions
- NEUTRAL: Proceed with caution, selective entries
- BEARISH: Defensive posture, avoid new longs

Usage:
    from market_regime import MarketRegimeCalculator, RegimeScore
    
    calculator = MarketRegimeCalculator(config)
    score = calculator.calculate_regime(distribution_data, overnight_data, ftd_status)
    print(f"Regime: {score.regime.value} ({score.composite_score:+.2f})")
"""

import logging
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional

try:
    import pytz
    ET_TIMEZONE = pytz.timezone('America/New_York')
except ImportError:
    ET_TIMEZONE = None

from .models_regime import RegimeType, TrendType, DDayTrend, EntryRiskLevel


def get_eastern_time() -> datetime:
    """Get current time in Eastern Time zone."""
    if ET_TIMEZONE:
        return datetime.now(ET_TIMEZONE)
    # Fallback to local time if pytz not available
    return datetime.now()

logger = logging.getLogger(__name__)


@dataclass
class DistributionData:
    """Distribution day data for regime calculation."""
    spy_count: int
    qqq_count: int
    spy_5day_delta: int
    qqq_5day_delta: int
    trend: DDayTrend
    spy_dates: list = None  # List of date objects for D-days
    qqq_dates: list = None  # List of date objects for D-days
    
    def __post_init__(self):
        if self.spy_dates is None:
            self.spy_dates = []
        if self.qqq_dates is None:
            self.qqq_dates = []
    
    @property
    def total_count(self) -> int:
        return self.spy_count + self.qqq_count


@dataclass
class OvernightData:
    """Overnight futures data for regime calculation."""
    es_change_pct: float
    es_trend: TrendType
    nq_change_pct: float
    nq_trend: TrendType
    ym_change_pct: float
    ym_trend: TrendType
    captured_at: datetime = None
    
    @property
    def average_change(self) -> float:
        """Average change across all three futures."""
        return (self.es_change_pct + self.nq_change_pct + self.ym_change_pct) / 3


@dataclass
class FTDData:
    """Follow-Through Day data for regime calculation."""
    market_phase: str  # 'CONFIRMED_UPTREND', 'RALLY_ATTEMPT', 'CORRECTION', etc.
    in_rally_attempt: bool
    rally_day: int  # 0 if not in rally
    has_confirmed_ftd: bool
    ftd_still_valid: bool
    days_since_ftd: Optional[int]
    ftd_today: bool  # FTD occurred today
    rally_failed_today: bool
    ftd_score_adjustment: float  # Pre-calculated score adjustment
    
    # Details for display
    spy_ftd_date: Optional[date] = None
    qqq_ftd_date: Optional[date] = None
    
    # Rally histogram (for displaying attempt history)
    rally_histogram: any = None  # RallyHistogram object
    failed_rally_count: int = 0
    successful_ftd_count: int = 0


@dataclass
class RegimeScore:
    """Complete regime calculation result."""
    composite_score: float
    regime: RegimeType
    distribution_data: DistributionData
    overnight_data: OvernightData
    component_scores: Dict[str, float]
    timestamp: datetime
    
    # FTD/Market Phase data
    ftd_data: Optional[FTDData] = None
    market_phase: str = "UNKNOWN"
    
    # Trend context for morning message
    regime_trend: str = ""  # "improving", "worsening", "stable"
    prior_regime: Optional[RegimeType] = None
    prior_score: Optional[float] = None
    
    # NEW: Entry Risk (tactical layer - calculated daily)
    entry_risk_score: float = 0.0  # -1.5 to +1.5, positive = favorable
    entry_risk_level: EntryRiskLevel = EntryRiskLevel.MODERATE

    # CNN Fear & Greed Index (display only - not in composite score)
    fear_greed_data: Optional['FearGreedData'] = None

    # VIX data (display only - not in composite score)
    vix_close: Optional[float] = None
    vix_previous_close: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization."""
        result = {
            'date': self.timestamp.date().isoformat(),
            'composite_score': self.composite_score,
            'regime': self.regime.value,
            'market_phase': self.market_phase,
            'spy_d_count': self.distribution_data.spy_count,
            'qqq_d_count': self.distribution_data.qqq_count,
            'spy_5day_delta': self.distribution_data.spy_5day_delta,
            'qqq_5day_delta': self.distribution_data.qqq_5day_delta,
            'd_day_trend': self.distribution_data.trend.value,
            'es_change_pct': self.overnight_data.es_change_pct,
            'nq_change_pct': self.overnight_data.nq_change_pct,
            'ym_change_pct': self.overnight_data.ym_change_pct,
            'component_scores': self.component_scores,
            'regime_trend': self.regime_trend,
            'prior_regime': self.prior_regime.value if self.prior_regime else None,
            'prior_score': self.prior_score
        }
        
        if self.ftd_data:
            result.update({
                'in_rally_attempt': self.ftd_data.in_rally_attempt,
                'rally_day': self.ftd_data.rally_day,
                'has_confirmed_ftd': self.ftd_data.has_confirmed_ftd,
                'ftd_still_valid': self.ftd_data.ftd_still_valid,
                'ftd_today': self.ftd_data.ftd_today,
                'days_since_ftd': self.ftd_data.days_since_ftd
            })
        
        return result


class MarketRegimeCalculator:
    """
    Calculates weighted market regime score aligned with IBD methodology.

    Score Components (default weights):
    - SPY Distribution Count: 25%
    - QQQ Distribution Count: 25%
    - D-Day Trend (5-day change): 20%
    - Overnight ES Futures: 10%
    - Overnight NQ Futures: 10%
    - Overnight YM Futures: 10%

    Regime Classification (aligned with IBD exposure levels):
    - BULLISH: Score >= 0.5 (0-3 D-days, 80-100% exposure)
    - NEUTRAL: Score between -0.65 and 0.5 (4-10 D-days, 40-80% exposure)
    - BEARISH: Score <= -0.65 (11+ D-days, 0-40% exposure)
    """
    
    # Default configuration
    DEFAULT_WEIGHTS = {
        'spy_distribution': 0.25,
        'qqq_distribution': 0.25,
        'distribution_trend': 0.20,
        'overnight_es': 0.10,
        'overnight_nq': 0.10,
        'overnight_ym': 0.10
    }
    
    # Updated D-day scoring to align with IBD exposure guidance
    # IBD: 4-7 distribution days = 60-80% exposure (NEUTRAL, not BEARISH)
    # IBD: 8-10 distribution days = 40-60% exposure (CAUTION, still not BEARISH)
    DEFAULT_D_DAY_SCORES = {
        # Granular scoring aligned with IBD exposure levels
        # 0-3 D-days = "Confirmed uptrend" = 80-100% exposure → score +2
        # 4-7 D-days = "Uptrend under pressure" = 60-80% exposure → score 0
        # 8-10 D-days = "Pressure increasing" = 40-60% exposure → score -1
        # 11+ D-days = "Correction" = 0-40% exposure → score -2
        'thresholds': [3, 7, 10],       # Breakpoints (more lenient)
        'scores': [2, 0, -1, -2],       # Scores for each range
        # Legacy fields for backward compatibility
        'low': 2,
        'medium': 0,
        'high': -2,
        'low_max': 3,
        'medium_max': 7
    }
    
    # Updated regime thresholds - align with IBD methodology
    DEFAULT_THRESHOLDS = {
        'bullish_min': 0.50,    # Strong positive signal for BULLISH (0-3 D-days)
        'bearish_max': -0.65    # Significant weakness for BEARISH (11+ D-days only)
        # NEUTRAL: Between -0.65 and 0.50 (wide band for 4-10 D-days)
    }
    
    DEFAULT_OVERNIGHT = {
        'bull_threshold': 0.25,
        'bear_threshold': -0.25
    }
    
    def __init__(self, config: dict = None):
        """
        Initialize calculator.
        
        Args:
            config: Configuration dict with 'scoring' and 'overnight' sections.
                   Uses defaults if not provided.
        """
        config = config or {}
        scoring = config.get('scoring', {})
        
        self.weights = scoring.get('weights', self.DEFAULT_WEIGHTS)
        self.d_day_scores = scoring.get('d_day_scores', self.DEFAULT_D_DAY_SCORES)
        self.thresholds = scoring.get('regime_thresholds', self.DEFAULT_THRESHOLDS)
        self.overnight_thresholds = config.get('overnight', self.DEFAULT_OVERNIGHT)
        
        # Validate weights sum to 1.0
        total_weight = sum(self.weights.values())
        if not (0.99 <= total_weight <= 1.01):
            logger.warning(f"Weights sum to {total_weight}, not 1.0. Normalizing.")
            for key in self.weights:
                self.weights[key] /= total_weight
        
        # Calculate actual score range for documentation
        self._calculate_score_range()
    
    def _calculate_score_range(self):
        """Calculate and log the actual score range based on weights."""
        # D-day scores: low_max to high
        d_range = (self.d_day_scores['high'], self.d_day_scores['low'])
        
        # Min/max possible scores
        min_score = (
            d_range[0] * self.weights['spy_distribution'] +
            d_range[0] * self.weights['qqq_distribution'] +
            -1.0 * self.weights['distribution_trend'] +
            -1.0 * self.weights['overnight_es'] +
            -1.0 * self.weights['overnight_nq'] +
            -1.0 * self.weights['overnight_ym']
        )
        max_score = (
            d_range[1] * self.weights['spy_distribution'] +
            d_range[1] * self.weights['qqq_distribution'] +
            1.0 * self.weights['distribution_trend'] +
            1.0 * self.weights['overnight_es'] +
            1.0 * self.weights['overnight_nq'] +
            1.0 * self.weights['overnight_ym']
        )
        
        self.score_range = (min_score, max_score)
        logger.debug(f"Score range: {min_score:.2f} to {max_score:.2f}")
    
    def calculate_d_day_score(self, count: int) -> float:
        """
        Score distribution day count using IBD-aligned thresholds.

        IBD Exposure Alignment (updated to match MarketSurge guidance):
        0-3 D-days:  +2 (80-100% exposure - "Confirmed uptrend")
        4-7 D-days:   0 (60-80% exposure - "Uptrend under pressure")
        8-10 D-days: -1 (40-60% exposure - "Pressure increasing")
        11+ D-days:  -2 (0-40% exposure - "Correction")

        Returns:
            Score from -2 to +2
        """
        # Check if using new granular thresholds
        if 'thresholds' in self.d_day_scores and 'scores' in self.d_day_scores:
            thresholds = self.d_day_scores['thresholds']  # [2, 4, 6, 8]
            scores = self.d_day_scores['scores']          # [2, 1, 0, -1, -2]
            
            for i, threshold in enumerate(thresholds):
                if count <= threshold:
                    return float(scores[i])
            
            # Above all thresholds
            return float(scores[-1])
        
        # Fallback to legacy scoring
        if count <= self.d_day_scores.get('low_max', 2):
            return float(self.d_day_scores.get('low', 2))
        elif count <= self.d_day_scores.get('medium_max', 4):
            return float(self.d_day_scores.get('medium', 0))
        else:
            return float(self.d_day_scores.get('high', -2))
    
    def calculate_trend_score(self, trend: DDayTrend) -> float:
        """
        Score distribution day trend.

        IMPROVING (D-days decreasing): +1.0
        HEALTHY (low count 0-3, stable): +0.5
        STABLE (moderate count 4-5, stable): 0.0
        ELEVATED_STABLE (high count 6+, stable): -0.5
        WORSENING (D-days increasing): -1.0
        """
        if trend == DDayTrend.IMPROVING:
            return 1.0
        elif trend == DDayTrend.HEALTHY:
            return 0.5
        elif trend == DDayTrend.STABLE:
            return 0.0
        elif trend == DDayTrend.ELEVATED_STABLE:
            return -0.5
        elif trend == DDayTrend.WORSENING:
            return -1.0
        else:
            return 0.0
    
    def calculate_overnight_score(self, change_pct: float) -> Tuple[float, TrendType]:
        """
        Score overnight futures change.
        
        >= +0.25%: +1, BULL
        <= -0.25%: -1, BEAR
        Otherwise:  0, NEUTRAL
        """
        bull_thresh = self.overnight_thresholds['bull_threshold']
        bear_thresh = self.overnight_thresholds['bear_threshold']
        
        if change_pct >= bull_thresh:
            return 1.0, TrendType.BULL
        elif change_pct <= bear_thresh:
            return -1.0, TrendType.BEAR
        else:
            return 0.0, TrendType.NEUTRAL
    
    def determine_regime(self, score: float) -> RegimeType:
        """Classify regime based on composite score."""
        if score >= self.thresholds['bullish_min']:
            return RegimeType.BULLISH
        elif score <= self.thresholds['bearish_max']:
            return RegimeType.BEARISH
        else:
            return RegimeType.NEUTRAL
    
    def calculate_regime(
        self,
        distribution: DistributionData,
        overnight: OvernightData,
        prior_score: RegimeScore = None,
        ftd_data: FTDData = None
    ) -> RegimeScore:
        """
        Calculate composite regime score.
        
        Args:
            distribution: Distribution day data
            overnight: Overnight futures data
            prior_score: Previous day's score (for trend calculation)
            ftd_data: Follow-Through Day status (optional but recommended)
        
        Returns:
            RegimeScore with all components
        """
        # Calculate individual component scores
        spy_d_score = self.calculate_d_day_score(distribution.spy_count)
        qqq_d_score = self.calculate_d_day_score(distribution.qqq_count)
        trend_score = self.calculate_trend_score(distribution.trend)
        es_score, _ = self.calculate_overnight_score(overnight.es_change_pct)
        nq_score, _ = self.calculate_overnight_score(overnight.nq_change_pct)
        ym_score, _ = self.calculate_overnight_score(overnight.ym_change_pct)
        
        # Calculate weighted composite
        composite = (
            spy_d_score * self.weights['spy_distribution'] +
            qqq_d_score * self.weights['qqq_distribution'] +
            trend_score * self.weights['distribution_trend'] +
            es_score * self.weights['overnight_es'] +
            nq_score * self.weights['overnight_nq'] +
            ym_score * self.weights['overnight_ym']
        )
        
        # Apply FTD adjustment if available
        ftd_adjustment = 0.0
        market_phase = "UNKNOWN"
        
        if ftd_data:
            ftd_adjustment = ftd_data.ftd_score_adjustment
            market_phase = ftd_data.market_phase
            composite += ftd_adjustment
        
        # Determine regime
        regime = self.determine_regime(composite)
        
        # Override regime based on market phase in certain conditions
        if ftd_data:
            # Fresh FTD today = at least NEUTRAL, likely BULLISH
            if ftd_data.ftd_today:
                if regime == RegimeType.BEARISH:
                    regime = RegimeType.NEUTRAL
            
            # Rally failed today = at least NEUTRAL, likely BEARISH
            if ftd_data.rally_failed_today:
                if regime == RegimeType.BULLISH:
                    regime = RegimeType.NEUTRAL
            
            # In correction with no rally attempt and high D-days = BEARISH
            if (market_phase == "CORRECTION" and 
                distribution.total_count >= 6 and
                regime == RegimeType.NEUTRAL):
                regime = RegimeType.BEARISH
        
        # Calculate regime trend vs prior day
        regime_trend = "stable"
        prior_regime = None
        prior_score_val = None
        
        if prior_score:
            prior_regime = prior_score.regime
            prior_score_val = prior_score.composite_score
            
            score_diff = composite - prior_score.composite_score
            if score_diff > 0.15:
                regime_trend = "improving"
            elif score_diff < -0.15:
                regime_trend = "worsening"
        
        component_scores = {
            'spy_distribution': round(spy_d_score * self.weights['spy_distribution'], 3),
            'qqq_distribution': round(qqq_d_score * self.weights['qqq_distribution'], 3),
            'distribution_trend': round(trend_score * self.weights['distribution_trend'], 3),
            'overnight_es': round(es_score * self.weights['overnight_es'], 3),
            'overnight_nq': round(nq_score * self.weights['overnight_nq'], 3),
            'overnight_ym': round(ym_score * self.weights['overnight_ym'], 3)
        }
        
        if ftd_data:
            component_scores['ftd_adjustment'] = round(ftd_adjustment, 3)
        
        return RegimeScore(
            composite_score=round(composite, 2),
            regime=regime,
            distribution_data=distribution,
            overnight_data=overnight,
            component_scores=component_scores,
            timestamp=get_eastern_time(),  # Use ET for consistent display
            ftd_data=ftd_data,
            market_phase=market_phase,
            regime_trend=regime_trend,
            prior_regime=prior_regime,
            prior_score=prior_score_val
        )
    
    def get_regime_guidance(self, regime: RegimeType) -> str:
        """Get trading guidance for a regime."""
        guidance = {
            RegimeType.BULLISH: (
                "→ Full position sizes permitted (80-100%)\n"
                "→ Favor long setups on breakouts\n"
                "→ Market environment supports growth stocks"
            ),
            RegimeType.NEUTRAL: (
                "→ Moderate position sizes (40-80%)\n"
                "→ Selective entries only - A+/A setups\n"
                "→ Tighten stops on existing positions\n"
                "→ Monitor distribution day trends closely"
            ),
            RegimeType.BEARISH: (
                "→ Defensive posture - raise cash (0-40%)\n"
                "→ Avoid new long positions entirely\n"
                "→ Take profits on remaining positions\n"
                "→ Wait for follow-through day signal"
            )
        }
        return guidance.get(regime, "")
    
    def get_exposure_percentage(
        self, 
        regime: RegimeType, 
        d_day_total: int = None,
        market_phase: str = None
    ) -> Tuple[int, int]:
        """
        Get suggested exposure range based on regime, D-day count, and market phase.
        
        Aligned with IBD exposure guidance.
        
        Args:
            regime: Current regime classification
            d_day_total: Total D-days (SPY + QQQ). If None, uses regime only.
            market_phase: Market phase string (CONFIRMED_UPTREND, RALLY_ATTEMPT, CORRECTION)
            
        Returns:
            Tuple of (min_exposure, max_exposure) as percentages
        """
        # Market phase takes priority - IBD methodology
        if market_phase:
            phase_upper = market_phase.upper()
            
            if 'CORRECTION' in phase_upper:
                # During correction, very low exposure regardless of D-day count
                return (0, 20)
            
            if 'RALLY_ATTEMPT' in phase_upper:
                # During rally attempt, cautious exposure
                return (20, 40)
            
            if 'PRESSURE' in phase_upper or 'UNDER_PRESSURE' in phase_upper:
                # Uptrend under pressure
                if d_day_total and d_day_total >= 6:
                    return (20, 40)
                return (40, 60)
        
        # For CONFIRMED_UPTREND or unknown phase, use D-day count
        if d_day_total is not None:
            if d_day_total <= 2:
                return (80, 100)
            elif d_day_total <= 4:
                return (70, 90)
            elif d_day_total <= 6:
                return (60, 80)
            elif d_day_total <= 8:
                return (40, 60)
            elif d_day_total <= 10:
                return (20, 40)
            else:
                return (0, 20)
        
        # Fallback to regime-based exposure
        base_exposure = {
            RegimeType.BULLISH: (80, 100),
            RegimeType.NEUTRAL: (40, 80),
            RegimeType.BEARISH: (0, 40)
        }
        
        return base_exposure.get(regime, (40, 60))
    
    def format_score_bar(self, score: float, width: int = 20) -> str:
        """Create a visual progress bar for the score."""
        min_score, max_score = self.score_range
        
        # Normalize to 0-1
        normalized = (score - min_score) / (max_score - min_score)
        normalized = max(0, min(1, normalized))  # Clamp
        
        filled = int(normalized * width)
        return '█' * filled + '░' * (width - filled)


def create_overnight_data(
    es_change: float,
    nq_change: float,
    ym_change: float,
    bull_threshold: float = 0.25,
    bear_threshold: float = -0.25
) -> OvernightData:
    """
    Helper to create OvernightData with automatic trend classification.
    
    Args:
        es_change: ES futures % change
        nq_change: NQ futures % change
        ym_change: YM futures % change
        bull_threshold: % change for bullish classification
        bear_threshold: % change for bearish classification
    
    Returns:
        OvernightData instance
    """
    def classify(pct: float) -> TrendType:
        if pct >= bull_threshold:
            return TrendType.BULL
        elif pct <= bear_threshold:
            return TrendType.BEAR
        return TrendType.NEUTRAL
    
    return OvernightData(
        es_change_pct=es_change,
        es_trend=classify(es_change),
        nq_change_pct=nq_change,
        nq_trend=classify(nq_change),
        ym_change_pct=ym_change,
        ym_trend=classify(ym_change),
        captured_at=datetime.now()
    )


if __name__ == '__main__':
    # Test the calculator
    logging.basicConfig(level=logging.DEBUG)
    
    calc = MarketRegimeCalculator()
    
    print(f"Score range: {calc.score_range[0]:.2f} to {calc.score_range[1]:.2f}")
    print(f"Bullish threshold: >= {calc.thresholds['bullish_min']}")
    print(f"Bearish threshold: <= {calc.thresholds['bearish_max']}")
    
    # Test various scenarios
    scenarios = [
        ("Best case (bullish)", 1, 1, DDayTrend.IMPROVING, 0.5, 0.7, 0.3),
        ("Worst case (bearish)", 6, 7, DDayTrend.WORSENING, -0.8, -1.2, -0.6),
        ("Low count, stable", 2, 3, DDayTrend.HEALTHY, 0.1, -0.1, 0.05),
        ("Moderate count, stable", 4, 5, DDayTrend.STABLE, 0.0, 0.0, 0.0),
        ("High D-days but stable", 6, 6, DDayTrend.ELEVATED_STABLE, 0.3, 0.4, 0.2),
        ("High D-days, strong futures", 5, 6, DDayTrend.WORSENING, 0.8, 1.0, 0.5),
    ]
    
    print("\n=== Scenario Testing ===")
    for name, spy, qqq, trend, es, nq, ym in scenarios:
        dist = DistributionData(
            spy_count=spy,
            qqq_count=qqq,
            spy_5day_delta=0,
            qqq_5day_delta=0,
            trend=trend
        )
        overnight = create_overnight_data(es, nq, ym)
        
        score = calc.calculate_regime(dist, overnight)
        
        print(f"\n{name}:")
        print(f"  SPY D-days: {spy}, QQQ D-days: {qqq}, Trend: {trend.value}")
        print(f"  Futures: ES {es:+.2f}%, NQ {nq:+.2f}%, YM {ym:+.2f}%")
        print(f"  Score: {score.composite_score:+.2f}")
        print(f"  {calc.format_score_bar(score.composite_score)} {score.regime.value}")


def calculate_entry_risk_score(
    overnight_data: OvernightData,
    distribution_data: DistributionData,
    ftd_data: Optional[FTDData] = None
) -> Tuple[float, EntryRiskLevel]:
    """
    Calculate today's entry risk score for new positions.
    
    This is the TACTICAL layer - assesses whether TODAY is favorable for
    entering new breakout positions, regardless of the overall IBD exposure.
    
    Score Range: -1.50 (highest risk) to +1.50 (lowest risk)
    - Positive = favorable for entries (low risk)
    - Negative = unfavorable for entries (high risk)
    
    Components:
    - Overnight Futures (40%): Positive futures = lower entry risk
    - D-Day Trend (35%): Improving trend = lower entry risk
    - D-Day Count (25%): Fewer D-days = lower entry risk
    - FTD Bonus: Fresh FTD is very favorable
    
    Args:
        overnight_data: Current overnight futures data
        distribution_data: Current distribution day data
        ftd_data: Optional FTD/rally attempt data
        
    Returns:
        Tuple of (score, risk_level)
    """
    score = 0.0
    
    # 1. Overnight Futures (weight: 0.40)
    # Positive futures = lower risk for entries
    avg_futures = overnight_data.average_change
    if avg_futures > 0.5:
        score += 0.40  # Strong bullish overnight
    elif avg_futures > 0.25:
        score += 0.25  # Moderate bullish
    elif avg_futures > -0.25:
        score += 0.0   # Neutral
    elif avg_futures > -0.5:
        score -= 0.25  # Moderate bearish
    else:
        score -= 0.40  # Strong bearish overnight
    
    # 2. Distribution Day Trend (weight: 0.35)
    # Improving trend = lower risk
    if distribution_data.trend == DDayTrend.IMPROVING:
        score += 0.35
    elif distribution_data.trend == DDayTrend.HEALTHY:
        score += 0.20  # Low count, stable = good
    elif distribution_data.trend == DDayTrend.STABLE:
        score += 0.10  # Moderate count, stable = ok
    elif distribution_data.trend == DDayTrend.ELEVATED_STABLE:
        score -= 0.10  # High count but stable = caution
    elif distribution_data.trend == DDayTrend.WORSENING:
        score -= 0.35
    
    # 3. D-Day Count (weight: 0.25)
    # Lower count = lower risk
    max_d = max(distribution_data.spy_count, distribution_data.qqq_count)
    if max_d <= 2:
        score += 0.25
    elif max_d <= 4:
        score += 0.10
    elif max_d <= 6:
        score -= 0.10
    else:
        score -= 0.25
    
    # 4. FTD Context Bonus (can add up to +0.50)
    if ftd_data:
        if ftd_data.ftd_today:
            score += 0.50  # Follow-through day is very favorable for entries
        elif ftd_data.has_confirmed_ftd and ftd_data.ftd_still_valid:
            if ftd_data.days_since_ftd and ftd_data.days_since_ftd <= 5:
                score += 0.15  # Recent valid FTD is favorable
            elif ftd_data.days_since_ftd and ftd_data.days_since_ftd <= 15:
                score += 0.05  # FTD still fresh enough to add confidence
        
        # Rally failed today is very negative
        if ftd_data.rally_failed_today:
            score -= 0.40
    
    # Clamp to range
    score = max(-1.50, min(1.50, score))
    
    # Convert to risk level
    risk_level = score_to_entry_risk_level(score)
    
    return round(score, 2), risk_level


def score_to_entry_risk_level(score: float) -> EntryRiskLevel:
    """
    Convert numeric entry risk score to categorical risk level.
    
    Score thresholds:
    - >= +0.75: LOW risk (favorable for entries)
    - >= +0.25: MODERATE risk (acceptable, be selective)
    - >= -0.24: ELEVATED risk (caution warranted)
    - < -0.24: HIGH risk (avoid new entries today)
    
    Note: Score is INVERTED from risk - higher score = lower risk.
    """
    if score >= 0.75:
        return EntryRiskLevel.LOW
    elif score >= 0.25:
        return EntryRiskLevel.MODERATE
    elif score >= -0.24:
        return EntryRiskLevel.ELEVATED
    else:
        return EntryRiskLevel.HIGH


def get_entry_risk_emoji(risk_level: EntryRiskLevel) -> str:
    """Get emoji for entry risk level."""
    emojis = {
        EntryRiskLevel.LOW: '🟢',
        EntryRiskLevel.MODERATE: '🟡',
        EntryRiskLevel.ELEVATED: '🟠',
        EntryRiskLevel.HIGH: '🔴'
    }
    return emojis.get(risk_level, '⚪')


def get_entry_risk_description(risk_level: EntryRiskLevel) -> str:
    """Get short description for entry risk level."""
    descriptions = {
        EntryRiskLevel.LOW: "Favorable for new entries",
        EntryRiskLevel.MODERATE: "Acceptable, be selective",
        EntryRiskLevel.ELEVATED: "Caution for new entries",
        EntryRiskLevel.HIGH: "Avoid new entries today"
    }
    return descriptions.get(risk_level, "Unknown")
