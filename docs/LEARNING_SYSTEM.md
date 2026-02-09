# Learning & Feedback System Documentation

## Overview

The **Learning System** is a machine learning-enabled feedback loop that continuously learns from trading outcomes to improve setup scoring. It analyzes historical trades, identifies which factors correlate with success, optimizes scoring weights, and validates changes through A/B testing before deployment.

**Key Characteristics:**
- **Data-Driven:** Learns from actual trade outcomes (live and backtest)
- **Statistically Rigorous:** Uses proper significance testing, not just correlations
- **Conservative:** Requires 5%+ improvement and A/B testing before deployment
- **Immutable Rules:** Core IBD rules (like RS floor) cannot be overridden by ML
- **Auditable:** All weight versions stored with metrics for review

---

## Prerequisites

Before using the learning system effectively, ensure you have:

### 1. Historical Regime Data (Required)

The learning system uses `market_regime_at_entry` to correlate outcomes with market conditions. Without historical regime data, this factor cannot be analyzed.

**Seed at least 1-2 years of regime history:**
```bash
python -m canslim_monitor.regime.historical_seeder \
    --start 2023-01-01 \
    --config user_config.yaml
```

This populates:
- Distribution days (SPY/QQQ)
- Market phase history
- Follow-through days
- Daily regime scores

See [MARKET_REGIME_THREAD.md](MARKET_REGIME_THREAD.md#seed-historical-regime-data) for details.

### 2. Backtest Data (Recommended)

Import historical trading outcomes for training data:

```bash
python -m canslim_monitor.cli.import_backtest \
    --backtest-db C:/Trading/backtest_training.db
```

### 3. Minimum Data Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Total outcomes | 50 | 200+ |
| SUCCESS outcomes | 20 | 50+ |
| FAILED outcomes | 20 | 50+ |
| Time span | 3 months | 12+ months |
| Regime data coverage | Matches outcomes | 2+ years |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LEARNING SYSTEM ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  DATA SOURCES                         ANALYSIS                               │
│  ────────────                         ────────                               │
│  ┌──────────────┐                    ┌──────────────┐                       │
│  │ Live Trades  │─────┐              │   Factor     │                       │
│  │ (Positions)  │     │              │  Analyzer    │                       │
│  └──────────────┘     │              │  ──────────  │                       │
│                       ▼              │ • Correlations│                       │
│  ┌──────────────┐  ┌──────────────┐  │ • P-values   │                       │
│  │  Backtest    │─▶│   Outcome    │─▶│ • Terciles   │                       │
│  │  Imports     │  │   Database   │  │ • Directions │                       │
│  └──────────────┘  └──────────────┘  └──────┬───────┘                       │
│                       │                      │                               │
│  ┌──────────────┐     │                      ▼                               │
│  │   Manual     │─────┘              ┌──────────────┐                       │
│  │   Entries    │                    │    Weight    │                       │
│  └──────────────┘                    │  Optimizer   │                       │
│                                      │  ──────────  │                       │
│                                      │ • Population │                       │
│                                      │ • Mutations  │                       │
│                                      │ • F1 Scoring │                       │
│                                      └──────┬───────┘                       │
│                                             │                                │
│                                             ▼                                │
│  VALIDATION                          ┌──────────────┐                       │
│  ──────────                          │   A/B Test   │                       │
│  ┌──────────────┐                    │   Manager    │                       │
│  │  Confidence  │◄───────────────────│  ──────────  │                       │
│  │   Engine     │                    │ • Control    │                       │
│  │  ──────────  │                    │ • Treatment  │                       │
│  │ • Z-tests    │                    │ • Assignment │                       │
│  │ • T-tests    │                    └──────────────┘                       │
│  │ • Power      │                           │                                │
│  └──────────────┘                           ▼                                │
│                                      ┌──────────────┐                       │
│                                      │   Weight     │                       │
│                                      │   Manager    │                       │
│  OUTPUT                              │  ──────────  │                       │
│  ──────                              │ • Activate   │                       │
│  ┌──────────────┐                    │ • Compare    │                       │
│  │   Scoring    │◄───────────────────│ • History    │                       │
│  │   System     │                    └──────────────┘                       │
│  └──────────────┘                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Complete Learning Cycle

```
1. COLLECT OUTCOMES
   ─────────────────
   Live Positions → On close → Record outcome with factors at entry
   Backtest DB    → Import   → Map to Outcome model
   Manual Entry   → GUI form → Add historical trades

2. ANALYZE FACTORS
   ─────────────────
   For each factor (RS, EPS, Stage, Depth, etc.):
   • Calculate Pearson correlation with returns
   • Calculate point-biserial correlation with win/loss
   • Determine statistical significance (p < 0.05)
   • Bucket into terciles (low/mid/high)
   • Recommend direction (higher/lower better)

3. OPTIMIZE WEIGHTS
   ─────────────────
   Evolutionary algorithm:
   • Initialize population from baseline + factor-guided variants
   • Evaluate fitness using F1 score
   • Select top 50%, breed mutations
   • Repeat 100 iterations
   • Output: optimized weight set

4. VALIDATE VIA A/B TEST
   ─────────────────
   • Split new entries 50/50
   • Control: current weights
   • Treatment: optimized weights
   • Accumulate 30+ outcomes per group
   • Run significance tests

5. PROMOTE OR REJECT
   ─────────────────
   If treatment wins (p < 0.05):
   • Activate new weights
   • Archive old weights
   If no difference:
   • Keep current weights
   • Log results for analysis
```

---

## Outcome Model

The `Outcome` table stores all trade outcomes for analysis:

### Core Fields

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | String | Stock ticker |
| `entry_date` | Date | When position opened |
| `exit_date` | Date | When position closed |
| `holding_days` | Integer | Days held |
| `entry_price` | Float | Entry price |
| `exit_price` | Float | Exit price |
| `gross_pct` | Float | Return percentage |

### Classification

| Field | Type | Description |
|-------|------|-------------|
| `outcome` | Enum | SUCCESS, PARTIAL, STOPPED, FAILED |
| `outcome_score` | Integer | Numeric version (0-100) |
| `hit_stop` | Boolean | Did position hit stop loss? |

### Risk Metrics

| Field | Type | Description |
|-------|------|-------------|
| `max_gain_pct` | Float | Maximum gain during hold |
| `max_drawdown_pct` | Float | Maximum drawdown during hold |
| `days_to_max_gain` | Integer | Days to reach peak |

### CANSLIM Factors at Entry

| Field | Type | Description |
|-------|------|-------------|
| `rs_at_entry` | Integer | Relative Strength (0-99) |
| `eps_at_entry` | Integer | EPS Rating (0-99) |
| `comp_at_entry` | Integer | Composite Rating (0-99) |
| `ad_at_entry` | String | A/D Rating (A+ to E) |
| `smr_at_entry` | String | SMR Rating |
| `stage_at_entry` | Integer | Base stage (1-4+) |
| `base_depth_at_entry` | Float | Base depth % |
| `base_length_at_entry` | Integer | Base length weeks |
| `pattern` | String | Pattern type |

### Market Context at Entry

| Field | Type | Description |
|-------|------|-------------|
| `market_regime_at_entry` | String | BULLISH/NEUTRAL/BEARISH |
| `market_exposure_at_entry` | Float | IBD exposure % |
| `dist_days_at_entry` | Integer | Distribution days |

### Institutional Data

| Field | Type | Description |
|-------|------|-------------|
| `industry_rank_at_entry` | Integer | Industry rank (1-197) |
| `fund_count_at_entry` | Integer | Number of funds |
| `funds_qtr_chg_at_entry` | Integer | Quarterly fund change |
| `rs_3mo_at_entry` | Integer | 3-month RS |
| `rs_6mo_at_entry` | Integer | 6-month RS |

### Metadata

| Field | Type | Description |
|-------|------|-------------|
| `source` | String | 'live', 'swingtrader', 'manual', 'backtest' |
| `validated` | Boolean | Has outcome been verified? |
| `validation_notes` | Text | Notes on data quality |
| `entry_grade` | String | Grade at entry (A+ to F) |
| `entry_score` | Integer | Score at entry |

---

## Outcome Classification

### Thresholds

```yaml
# From learning_config.yaml
outcome_thresholds:
  success_pct: 20.0      # >= 20% gain = SUCCESS
  partial_min_pct: 5.0   # 5-20% gain = PARTIAL
  stop_loss_pct: -7.0    # Hit stop = STOPPED
  # < 5% gain = FAILED
```

### Classification Logic

```python
def classify_outcome(gross_pct: float, hit_stop: bool) -> str:
    if hit_stop:
        return "STOPPED"
    elif gross_pct >= 20.0:
        return "SUCCESS"
    elif gross_pct >= 5.0:
        return "PARTIAL"
    else:
        return "FAILED"
```

### Interpretation

| Outcome | Meaning | Learning Impact |
|---------|---------|-----------------|
| **SUCCESS** | Full winner - hit 20%+ target | Strong positive signal for factors |
| **PARTIAL** | Modest gain - 5-20% | Weak positive signal |
| **STOPPED** | Hit stop loss | Strong negative signal for factors |
| **FAILED** | Small gain/loss, no clear outcome | Weak negative signal |

---

## Factor Analysis

### Analyzable Factors

**Numeric Factors** (correlation-based):

| Factor | Range | Preferred Direction | IBD Meaning |
|--------|-------|---------------------|-------------|
| `rs_rating` | 0-99 | Higher | Relative price strength |
| `eps_rating` | 0-99 | Higher | Earnings growth |
| `comp_rating` | 0-99 | Higher | Combined quality |
| `industry_rank` | 1-197 | Lower | Leading industry |
| `fund_count` | 0-5000 | Higher | Institutional support |
| `funds_qtr_chg` | -500 to +500 | Higher | Increasing sponsorship |
| `base_depth` | 0-50% | Lower | Shallow bases better |
| `base_length` | 1-100 wks | Moderate | Time to consolidate |

**Categorical Factors** (ordered scales):

| Factor | Values | Preferred |
|--------|--------|-----------|
| `ad_rating` | A+, A, B, C, D, E | A+ |
| `market_regime` | BULLISH, NEUTRAL, BEARISH | BULLISH |
| `base_stage` | 1, 2, 3, 4+ | 1-2 |
| `pattern` | Cup/Handle, Flat, etc. | Cup w/Handle |

### Statistical Methods

**1. Pearson Correlation (numeric factors)**
```
r = Σ[(xi - x̄)(yi - ȳ)] / √[Σ(xi - x̄)² × Σ(yi - ȳ)²]

Where:
  xi = factor value for trade i
  yi = return % for trade i
```

**2. Point-Biserial Correlation (binary outcome)**
```
rpb = (M₁ - M₀) / s × √[n₁n₀ / n²]

Where:
  M₁ = mean factor for winners
  M₀ = mean factor for losers
  s = pooled standard deviation
```

**3. P-Value Calculation**
```
t = r × √[(n-2) / (1-r²)]
p = 2 × (1 - CDF(|t|, df=n-2))

Significant if p < 0.05
```

**4. Tercile Analysis**

For each numeric factor:
- Split outcomes into Low / Medium / High terciles
- Calculate win rate and average return per tercile
- Identify if linear relationship exists

### Factor Analysis Output

```python
@dataclass
class FactorAnalysis:
    factor_name: str
    sample_size: int
    correlation_return: float        # r with returns (%)
    correlation_win_rate: float      # r with win/loss
    p_value_return: float
    p_value_win_rate: float
    is_significant: bool             # p < 0.05
    tercile_stats: List[TercileBucket]
    recommended_direction: str       # 'higher' | 'lower' | 'none'
    recommended_weight: float        # Based on |r|
    variance_explained: float        # r²
```

### Example Output

```
FACTOR ANALYSIS RESULTS
═══════════════════════════════════════════════════════════

Factor          r(return)  p-value   Sig?   Direction
────────────────────────────────────────────────────────
rs_rating         +0.32    0.001     ✓      higher
eps_rating        +0.18    0.042     ✓      higher
base_stage        -0.25    0.008     ✓      lower
base_depth        -0.15    0.089     -      lower
industry_rank     -0.12    0.124     -      lower
ad_rating         +0.21    0.019     ✓      higher
market_regime     +0.28    0.003     ✓      bullish

Tercile Analysis - RS Rating:
  Low (0-79):   Win Rate 38%, Avg Return +4.2%
  Mid (80-89):  Win Rate 52%, Avg Return +12.5%
  High (90-99): Win Rate 68%, Avg Return +22.1%
  → Strong positive relationship confirmed
```

---

## Weight Optimization

### Baseline Weights

```python
DEFAULT_WEIGHTS = {
    # CANSLIM Ratings (50 points total)
    'rs_rating': 15,
    'eps_rating': 10,
    'comp_rating': 10,
    'ad_rating': 5,
    'industry_rank': 5,
    'fund_count': 5,

    # Base Characteristics (30 points total)
    'base_stage': 15,
    'base_depth': 10,
    'base_length': 5,

    # Market Context (20 points total)
    'market_regime': 10,
    'funds_qtr_chg': 5,
    'breakout_volume': 5,
}
# Total: 100 points
```

### Evolutionary Optimization Algorithm

**1. Initialization**

```python
population = []

# Start with baseline
population.append(DEFAULT_WEIGHTS)

# Add factor-analysis-guided variants
for factor, analysis in factor_analyses.items():
    variant = DEFAULT_WEIGHTS.copy()
    if analysis.is_significant:
        # Boost weight proportional to correlation
        boost = 1 + (abs(analysis.correlation_return) * 2)
        variant[factor] = DEFAULT_WEIGHTS[factor] * boost
    population.append(normalize(variant))

# Add random mutations
while len(population) < 20:
    variant = mutate(random.choice(population))
    population.append(normalize(variant))
```

**2. Fitness Evaluation**

```python
def evaluate_fitness(weights, outcomes):
    predictions = []
    actuals = []

    for outcome in outcomes:
        # Calculate score with these weights
        score = calculate_score(outcome, weights)

        # Predict: score > 50 = win, else loss
        predicted_win = score > 50
        actual_win = outcome.outcome in ['SUCCESS', 'PARTIAL']

        predictions.append(predicted_win)
        actuals.append(actual_win)

    # F1 score balances precision and recall
    return f1_score(actuals, predictions)
```

**3. Selection & Breeding**

```python
for iteration in range(100):
    # Evaluate all
    scores = [(w, evaluate_fitness(w, outcomes)) for w in population]

    # Sort by fitness (F1 score)
    scores.sort(key=lambda x: x[1], reverse=True)

    # Keep top 50%
    survivors = [w for w, s in scores[:len(scores)//2]]

    # Breed new population
    population = survivors.copy()
    while len(population) < 20:
        parent = random.choice(survivors)
        child = mutate(parent)
        population.append(normalize(child))
```

**4. Mutation**

```python
def mutate(weights):
    mutated = weights.copy()
    for factor in mutated:
        if random.random() < 0.3:  # 30% chance per factor
            # Random adjustment ±20%
            multiplier = random.uniform(0.8, 1.2)
            mutated[factor] *= multiplier
    return normalize(mutated)

def normalize(weights):
    """Ensure weights sum to 100."""
    total = sum(weights.values())
    return {k: v * 100 / total for k, v in weights.items()}
```

### Optimization Output

```python
@dataclass
class OptimizationResult:
    optimized_weights: Dict[str, float]
    baseline_accuracy: float           # Before optimization
    optimized_accuracy: float          # After optimization
    improvement_pct: float             # (opt - baseline) / baseline
    precision_score: float
    recall_score: float
    f1_score: float
    training_samples: int
    test_samples: int
    iterations: int
    convergence_history: List[float]   # F1 per iteration
```

### Example Output

```
WEIGHT OPTIMIZATION RESULTS
═══════════════════════════════════════════════════════════

Training Set: 180 outcomes (80%)
Test Set: 45 outcomes (20%)
Iterations: 100

Performance:
  Baseline Accuracy: 58.2%
  Optimized Accuracy: 65.3%
  Improvement: +12.2%

  Precision: 0.68 (68% of predicted wins were wins)
  Recall: 0.72 (72% of actual wins were predicted)
  F1 Score: 0.70

Weight Changes:
  Factor          Baseline  Optimized  Change
  ─────────────────────────────────────────────
  rs_rating         15.0      18.2     +21.3%  ⬆️
  base_stage        15.0      17.5     +16.7%  ⬆️
  eps_rating        10.0       8.1     -19.0%  ⬇️
  market_regime     10.0      12.3     +23.0%  ⬆️
  base_depth        10.0      11.8     +18.0%  ⬆️
  ...
```

---

## A/B Testing Framework

### Purpose

Before deploying optimized weights to production, they must prove superiority through A/B testing with real positions.

### Test Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                        A/B TEST SETUP                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│     CONTROL GROUP (50%)              TREATMENT GROUP (50%)       │
│     ─────────────────                ──────────────────          │
│     Current/Baseline Weights         Optimized Weights           │
│                                                                  │
│     Position assigned on entry       Position assigned on entry  │
│     Score calculated with            Score calculated with       │
│     control weights                  treatment weights           │
│                                                                  │
│     Outcome recorded on close        Outcome recorded on close   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     STATISTICAL COMPARISON                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│     Win Rate Comparison:                                         │
│       Control: 52% (26/50)                                       │
│       Treatment: 62% (31/50)                                     │
│       Two-Proportion Z-Test: p = 0.032 ✓                         │
│                                                                  │
│     Mean Return Comparison:                                      │
│       Control: +8.5%                                             │
│       Treatment: +12.3%                                          │
│       Welch's T-Test: p = 0.048 ✓                                │
│                                                                  │
│     Decision: PROMOTE TREATMENT                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Assignment Logic

```python
def assign_to_test(position_id: int, test: ABTest) -> str:
    """Assign position to control or treatment group."""
    # Deterministic hash for reproducibility
    hash_value = hash(f"{test.id}_{position_id}")
    assignment = "control" if hash_value % 2 == 0 else "treatment"

    # Record assignment
    ABTestAssignment.create(
        test_id=test.id,
        position_id=position_id,
        group=assignment,
        assigned_at=datetime.now()
    )

    return assignment
```

### Statistical Tests

**1. Two-Proportion Z-Test (Win Rates)**

```python
def compare_proportions(control_wins, control_n, treat_wins, treat_n):
    """Test if treatment win rate > control."""
    p1 = control_wins / control_n
    p2 = treat_wins / treat_n

    # Pooled proportion
    p_pooled = (control_wins + treat_wins) / (control_n + treat_n)

    # Standard error
    se = sqrt(p_pooled * (1 - p_pooled) * (1/control_n + 1/treat_n))

    # Z-statistic
    z = (p2 - p1) / se

    # P-value (one-tailed)
    p_value = 1 - norm_cdf(z)

    return z, p_value
```

**2. Welch's T-Test (Mean Returns)**

```python
def compare_means(control_returns, treat_returns):
    """Test if treatment mean return > control."""
    m1, m2 = mean(control_returns), mean(treat_returns)
    v1, v2 = var(control_returns), var(treat_returns)
    n1, n2 = len(control_returns), len(treat_returns)

    # Welch's t-statistic (unequal variances)
    t = (m2 - m1) / sqrt(v1/n1 + v2/n2)

    # Degrees of freedom (Welch-Satterthwaite)
    df = (v1/n1 + v2/n2)² / ((v1/n1)²/(n1-1) + (v2/n2)²/(n2-1))

    p_value = 1 - t_cdf(t, df)

    return t, p_value
```

**3. Power Analysis**

```python
def required_sample_size(effect_size, alpha=0.05, power=0.80):
    """Minimum samples to detect effect with given power."""
    # For two proportions
    z_alpha = 1.96  # Two-tailed, α=0.05
    z_beta = 0.84   # Power=0.80

    n = 2 * ((z_alpha + z_beta) / effect_size) ** 2
    return ceil(n)

# Example: To detect 10% difference in win rates
# required_sample_size(0.10) → ~393 per group
```

### Confidence Levels

| Samples Per Group | Confidence | Action |
|-------------------|------------|--------|
| < 10 | Insufficient | Keep collecting |
| 10-30 | Low | Preliminary signals only |
| 30-100 | Medium | Can make tentative decisions |
| ≥ 100 | High | Statistical power sufficient |

### Test Completion Criteria

```python
def should_complete_test(test: ABTest) -> Tuple[bool, str]:
    """Check if test has enough data to conclude."""

    # Minimum samples
    if min(test.control_count, test.treatment_count) < 30:
        return False, "Need 30+ outcomes per group"

    # Run significance tests
    win_rate_p = compare_proportions(...)
    mean_return_p = compare_means(...)

    # Clear winner?
    if win_rate_p < 0.05 and mean_return_p < 0.05:
        return True, "Treatment wins both metrics"

    if win_rate_p > 0.95 and mean_return_p > 0.95:
        return True, "Control wins both metrics"

    # Need more data if inconclusive
    if max(test.control_count, test.treatment_count) > 200:
        return True, "Max samples reached, no clear winner"

    return False, "Continue collecting data"
```

---

## Learned Weights Storage

### LearnedWeights Model

```python
class LearnedWeights:
    id: Integer (primary key)
    version: Integer                 # Sequential version number
    weights: JSON                    # {"rs_rating": 15.2, ...}
    factor_analysis: JSON            # Per-factor correlations

    # Performance Metrics
    accuracy: Float
    precision_score: Float
    recall_score: Float
    f1_score: Float
    baseline_accuracy: Float         # For comparison
    improvement_pct: Float           # vs baseline

    # Confidence
    confidence_level: String         # 'low', 'medium', 'high'
    sample_size: Integer             # Training outcomes

    # Status
    is_active: Boolean               # Currently in use?
    created_at: DateTime
    activated_at: DateTime

    # Training Details
    training_start: Date
    training_end: Date
    notes: Text
```

### Weight Manager Operations

```python
class WeightManager:

    def get_active_weights(self) -> Dict[str, float]:
        """Get currently active weights, or defaults."""
        active = session.query(LearnedWeights)\
            .filter(LearnedWeights.is_active == True)\
            .first()

        if active:
            return active.weights
        return DEFAULT_WEIGHTS

    def activate_weights(self, weights_id: int) -> bool:
        """Activate a weight set, deactivate current."""
        # Deactivate current
        session.query(LearnedWeights)\
            .filter(LearnedWeights.is_active == True)\
            .update({'is_active': False})

        # Activate new
        weights = session.query(LearnedWeights).get(weights_id)
        weights.is_active = True
        weights.activated_at = datetime.now()
        session.commit()
        return True

    def compare_weights(self, id1: int, id2: int) -> Dict:
        """Compare two weight sets."""
        w1 = session.query(LearnedWeights).get(id1)
        w2 = session.query(LearnedWeights).get(id2)

        comparison = {}
        for factor in w1.weights:
            v1, v2 = w1.weights[factor], w2.weights[factor]
            comparison[factor] = {
                'set1': v1,
                'set2': v2,
                'difference': v2 - v1,
                'pct_change': ((v2 - v1) / v1) * 100 if v1 > 0 else 0
            }
        return comparison
```

---

## Analytics Dashboard

### Overview Tab

**Outcome Distribution Chart**

```
                 OUTCOME DISTRIBUTION
    ┌─────────────────────────────────────────────┐
    │                                             │
    │      ██████████████████████  SUCCESS 42%    │
    │      ████████████  PARTIAL 25%              │
    │      ████████  STOPPED 18%                  │
    │      ██████  FAILED 15%                     │
    │                                             │
    └─────────────────────────────────────────────┘

    Total Outcomes: 225
    Win Rate: 67% (SUCCESS + PARTIAL)
    Average Return: +8.5%
```

**Win Rate by Grade**

```
    WIN RATE BY ENTRY GRADE
    ┌─────────────────────────────────────────────┐
    │ A+  ████████████████████████████████  85%   │
    │ A   ██████████████████████████████  78%     │
    │ B   ██████████████████████████  68%         │
    │ C   ████████████████████  52%               │
    │ D   ████████████  38%                       │
    │ F   ██████  22%                             │
    └─────────────────────────────────────────────┘

    Observation: Strong grade→outcome correlation
    A/B grades: 73% win rate
    C/D/F grades: 42% win rate
```

### Factor Analysis Tab

**Correlation Chart**

```
    FACTOR CORRELATIONS WITH SUCCESS
    ─────────────────────────────────────────────────

    rs_rating       █████████████████████  +0.32 ***
    market_regime   █████████████████  +0.28 ***
    ad_rating       ██████████████  +0.21 **
    eps_rating      ███████████  +0.18 *
    base_depth      ▓▓▓▓▓▓▓▓▓  -0.15
    industry_rank   ▓▓▓▓▓▓  -0.12
    base_stage      ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  -0.25 **

    Legend: *** p<0.001, ** p<0.01, * p<0.05
            █ Positive  ▓ Negative
```

**Factor Details Table**

| Factor | Correlation | P-Value | Significant | N | Direction |
|--------|-------------|---------|-------------|---|-----------|
| rs_rating | +0.32 | 0.001 | ✓ | 225 | higher |
| market_regime | +0.28 | 0.003 | ✓ | 225 | bullish |
| base_stage | -0.25 | 0.008 | ✓ | 225 | lower |
| ad_rating | +0.21 | 0.019 | ✓ | 225 | higher |
| eps_rating | +0.18 | 0.042 | ✓ | 225 | higher |
| base_depth | -0.15 | 0.089 | - | 225 | lower |
| industry_rank | -0.12 | 0.124 | - | 225 | lower |

### Weight Management Tab

**Current vs Suggested Weights**

| Factor | Current | Suggested | Change | Rationale |
|--------|---------|-----------|--------|-----------|
| rs_rating | 15.0 | 18.2 | +21% ⬆️ | Strong correlation |
| base_stage | 15.0 | 17.5 | +17% ⬆️ | Significant negative |
| market_regime | 10.0 | 12.3 | +23% ⬆️ | Important context |
| eps_rating | 10.0 | 8.1 | -19% ⬇️ | Weaker correlation |
| base_depth | 10.0 | 11.8 | +18% ⬆️ | Matters for success |

**Weight History**

| Version | Created | Accuracy | F1 | Improvement | Status |
|---------|---------|----------|-----|-------------|--------|
| v3 | Feb 1 | 65.3% | 0.70 | +12.2% | ✓ Active |
| v2 | Jan 15 | 61.8% | 0.65 | +6.2% | Inactive |
| v1 | Jan 1 | 58.2% | 0.58 | baseline | Inactive |

### Import Data Tab

**Actions:**
- **Import Backtest DB**: Load historical trades from backtest database
- **Import (Overwrite)**: Replace existing backtest outcomes
- **Preview Rescore**: Show grade changes before applying
- **Rescore All**: Apply current scoring rules to all outcomes

**Log Output Example:**

```
════════════════════════════════════════
BACKTEST IMPORT SUMMARY
════════════════════════════════════════
Source: C:\Trading\backtest_training.db
Total records read: 450
Successfully imported: 423
Duplicates skipped: 18
Errors: 9

Grade distribution:
  A: 45 (10.6%)
  B: 112 (26.5%)
  C: 156 (36.9%)
  D: 78 (18.4%)
  F: 32 (7.6%)
════════════════════════════════════════
```

---

## Immutable Rules

The learning system respects core IBD rules that should never be overridden:

### RS Floor Rule

```yaml
# From learning_config.yaml
immutable_rules:
  rs_floor:
    enabled: true
    threshold: 70
    max_grade: "C"
```

**Behavior:**
- If RS Rating < 70, maximum grade is capped at C
- Cannot be overridden by learned weights
- Based on IBD's proven research

### Minimum Thresholds

```yaml
minimum_requirements:
  min_outcomes: 50           # Don't optimize with fewer
  min_successes: 20          # Need enough winners
  min_failures: 20           # Need enough losers
  min_months: 3              # Time diversity
```

### Weight Constraints

```yaml
weight_constraints:
  multiplier_clamp_min: 0.3    # Weight can't go below 30% of baseline
  multiplier_clamp_max: 3.0    # Weight can't exceed 300% of baseline
  min_improvement_pct: 5.0     # Require 5%+ improvement to adopt
```

---

## Configuration Reference

### Complete Learning Config

```yaml
# config/learning_config.yaml

# Outcome Classification
outcome_thresholds:
  success_pct: 20.0
  partial_min_pct: 5.0
  stop_loss_pct: -7.0

# Data Requirements
data_requirements:
  min_outcomes: 50
  min_successes: 20
  min_failures: 20
  min_months: 3

# Optimization Settings
optimization:
  population_size: 20
  iterations: 100
  mutation_rate: 0.3
  mutation_range: 0.2
  train_split: 0.8

# Weight Constraints
weight_constraints:
  multiplier_clamp_min: 0.3
  multiplier_clamp_max: 3.0
  min_improvement_pct: 5.0

# A/B Testing
ab_testing:
  split_ratio: 0.5
  min_samples_per_group: 30
  significance_level: 0.05
  max_samples: 200

# Immutable Rules
immutable_rules:
  rs_floor:
    enabled: true
    threshold: 70
    max_grade: "C"

# Auto-Trigger
auto_trigger:
  trigger_after_n_outcomes: 10
  min_days_between: 7

# Performance Monitoring
monitoring:
  degradation_threshold: 0.55
  rolling_window_days: 90

# Factor Analysis
factor_analysis:
  significance_level: 0.05
  min_samples_per_tercile: 10
  correlation_threshold: 0.10
```

---

## Interpreting Results

### Factor Analysis Interpretation

**Strong Positive Correlation (r > 0.20, p < 0.05)**
```
rs_rating: r = +0.32, p = 0.001
→ Higher RS strongly associated with better outcomes
→ Recommendation: Increase RS weight
```

**Strong Negative Correlation (r < -0.20, p < 0.05)**
```
base_stage: r = -0.25, p = 0.008
→ Higher stage (3, 4) associated with worse outcomes
→ Recommendation: Penalize late-stage bases more
```

**Weak/Insignificant Correlation (|r| < 0.10 or p > 0.05)**
```
base_length: r = +0.08, p = 0.234
→ No clear relationship with outcomes
→ Recommendation: Keep moderate weight or reduce
```

### Tercile Analysis Interpretation

```
RS Rating Terciles:
  Low (0-79):    Win Rate 38%, Avg Return +4.2%
  Mid (80-89):   Win Rate 52%, Avg Return +12.5%
  High (90-99):  Win Rate 68%, Avg Return +22.1%
```

**Interpretation:**
- Clear linear relationship: higher RS = better outcomes
- Delta from low to high tercile: +30% win rate
- Action: RS should have high weight, favor 90+ stocks

### A/B Test Interpretation

```
Test Results (n=60 per group):
  Control Win Rate: 52%
  Treatment Win Rate: 62%
  Difference: +10%
  p-value: 0.032
```

**Interpretation:**
- Treatment (optimized weights) outperformed control
- 10% improvement in win rate is meaningful
- p < 0.05 means statistically significant
- Action: Promote treatment weights to active

### Weight Change Interpretation

```
Weight Changes:
  rs_rating:    15 → 18.2  (+21%)
  base_stage:   15 → 17.5  (+17%)
  eps_rating:   10 → 8.1   (-19%)
```

**Interpretation:**
- RS and stage are more predictive than originally weighted
- EPS rating is less predictive than expected
- Changes align with factor analysis findings
- Total still sums to 100 (normalized)

---

## Workflow Examples

### Example 1: Running Full Analysis

```python
from canslim_monitor.core.learning import LearningService

# Initialize
service = LearningService(db_connection)

# Run complete pipeline
result = service.run_full_analysis()

print(f"Outcomes analyzed: {result.sample_size}")
print(f"Significant factors: {result.significant_factors}")
print(f"Improvement: {result.improvement_pct:.1f}%")

if result.improvement_pct >= 5.0:
    print("Recommendation: Start A/B test with optimized weights")
```

### Example 2: Importing Backtest Data

```python
from canslim_monitor.core.learning import BacktestImporter

# Initialize
importer = BacktestImporter(
    backtest_db_path="C:/Trading/backtest_training.db",
    target_db=db_connection
)

# Run import
stats = importer.import_all(overwrite=False)

print(f"Imported: {stats['imported']}")
print(f"Skipped (duplicates): {stats['skipped']}")

# Print summary
print(importer.get_summary_report())
```

### Example 3: Rescoring Outcomes

```python
from canslim_monitor.core.learning import LearningService

service = LearningService(db_connection)

# Preview changes first
preview = service.get_rescore_preview(source='swingtrader', limit=10)
for p in preview:
    print(f"{p['symbol']}: {p['old_grade']} → {p['new_grade']}")

# Apply rescoring
stats = service.rescore_outcomes(source='swingtrader')
print(f"Rescored: {stats['rescored']}")
```

### Example 4: Activating New Weights

```python
from canslim_monitor.core.learning import WeightManager

manager = WeightManager(db_connection)

# View current weights
current = manager.get_active_weights()
print(f"Current: {current}")

# Compare with candidate
comparison = manager.compare_weights(
    current_id=manager.get_active_id(),
    candidate_id=5
)
for factor, diff in comparison.items():
    print(f"{factor}: {diff['set1']} → {diff['set2']} ({diff['pct_change']:+.1f}%)")

# Activate if satisfied
manager.activate_weights(weights_id=5)
```

---

## Best Practices

### Data Quality

1. **Validate imports:** Check for missing data before analysis
2. **Exclude outliers:** Very high/low returns may skew results
3. **Require minimum samples:** Don't optimize with < 50 outcomes
4. **Diversify sources:** Mix live, backtest, and manual data

### Analysis Frequency

1. **Run factor analysis:** After every 10-20 new outcomes
2. **Run optimization:** Monthly or after significant new data
3. **A/B test duration:** Minimum 4-6 weeks
4. **Don't over-fit:** Watch for suspiciously high improvements

### Weight Changes

1. **Incremental changes:** Prefer 10-20% adjustments over radical changes
2. **Validate with A/B:** Always test before production
3. **Monitor degradation:** Track rolling accuracy after deployment
4. **Keep history:** Never delete old weight sets

### Statistical Rigor

1. **Require significance:** p < 0.05 for weight changes
2. **Use multiple tests:** Both win rate and mean return
3. **Watch for false positives:** Multiple testing correction
4. **Power analysis:** Ensure adequate sample size

---

## Troubleshooting

### "Not Enough Data"

```
Error: Minimum 50 outcomes required for optimization
```

**Solution:** Import more backtest data or wait for more live outcomes

### "No Significant Factors"

```
Warning: No factors reached p < 0.05 significance
```

**Solutions:**
- Need more data (current sample may be too small)
- Factors may genuinely have equal predictive power
- Check data quality (missing values?)

### "Improvement Below Threshold"

```
Info: Optimized weights only 3.2% better (need 5%)
```

**Solutions:**
- Current weights may already be well-tuned
- Try different factor combinations
- Collect more diverse outcome data

### "A/B Test Inconclusive"

```
Status: 80 samples per group, p = 0.12 (not significant)
```

**Solutions:**
- Continue collecting data (target 200+ per group)
- Effect size may be small but real
- May need to accept no improvement

---

## CLI Commands

### Import Backtest Data

**Primary command for importing historical trade outcomes:**

```bash
# Standard import (skip duplicates)
python -m canslim_monitor.cli.import_backtest

# Preview what would be imported (no changes)
python -m canslim_monitor.cli.import_backtest --dry-run

# Clear existing and reimport
python -m canslim_monitor.cli.import_backtest --overwrite

# Custom database paths
python -m canslim_monitor.cli.import_backtest \
    --main-db C:/Trading/canslim_monitor/canslim_positions.db \
    --backtest-db C:/Trading/backtest_training.db
```

**Output Example:**
```
════════════════════════════════════════════════════════════
BACKTEST IMPORT SUMMARY
════════════════════════════════════════════════════════════
Source: C:/Trading/backtest_training.db
Total records read: 450
Successfully imported: 423
Duplicates skipped: 18
Errors: 9

Grade distribution:
  A: 45 (10.6%)
  B: 112 (26.5%)
  C: 156 (36.9%)
  D: 78 (18.4%)
  F: 32 (7.6%)
════════════════════════════════════════════════════════════
```

### Launch Analytics Dashboard

**Open the GUI analytics dashboard:**

```bash
# Launch main GUI (includes Analytics tab)
python -m canslim_monitor gui
```

Navigate to **Analytics** tab for:
- Outcome distribution charts
- Factor correlation analysis
- Weight management
- Import/rescore tools

### Run Factor Analysis (Programmatic)

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.core.learning import LearningService

db = Database('canslim_positions.db')
service = LearningService(db)

# Run factor analysis only
result = service.run_factor_analysis()

print('Factor Analysis Results:')
print('=' * 50)
for factor, analysis in result.items():
    sig = '***' if analysis.p_value < 0.001 else '**' if analysis.p_value < 0.01 else '*' if analysis.p_value < 0.05 else ''
    print(f'{factor:20} r={analysis.correlation:+.3f} p={analysis.p_value:.3f} {sig}')
"
```

### Run Weight Optimization (Programmatic)

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.core.learning import LearningService

db = Database('canslim_positions.db')
service = LearningService(db)

# Run full optimization
result = service.run_full_analysis()

print(f'Baseline Accuracy: {result.baseline_accuracy:.1%}')
print(f'Optimized Accuracy: {result.optimized_accuracy:.1%}')
print(f'Improvement: {result.improvement_pct:+.1f}%')
print(f'F1 Score: {result.f1_score:.3f}')
print('')
print('Optimized Weights:')
for factor, weight in result.optimized_weights.items():
    print(f'  {factor}: {weight:.1f}')
"
```

### Preview Rescoring

See what grade changes would occur before applying:

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.core.learning import LearningService

db = Database('canslim_positions.db')
service = LearningService(db)

# Preview first 20 changes
preview = service.get_rescore_preview(source='swingtrader', limit=20)

print('Rescore Preview:')
print('=' * 60)
for p in preview:
    old = p['old_grade'] or 'N/A'
    new = p['new_grade'] or 'N/A'
    change = ' → ' + new if old != new else ''
    print(f\"{p['symbol']:6} RS:{p.get('rs_rating', 'N/A'):>3} Grade: {old}{change} Return:{p.get('return_pct', 0):>6.1f}%\")
"
```

### Apply Rescoring

Rescore all outcomes using current scoring rules:

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.core.learning import LearningService

db = Database('canslim_positions.db')
service = LearningService(db)

# Rescore backtest outcomes only
stats = service.rescore_outcomes(source='swingtrader')

print(f'Total outcomes: {stats[\"total\"]}')
print(f'Rescored: {stats[\"rescored\"]}')
print(f'Skipped (no data): {stats[\"skipped_no_data\"]}')
print(f'Errors: {stats[\"errors\"]}')
print('')
print('Grade Distribution:')
for grade, count in sorted(stats['grade_distribution'].items()):
    print(f'  {grade}: {count}')
"
```

### View Current Active Weights

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.core.learning import WeightManager

db = Database('canslim_positions.db')
manager = WeightManager(db)

weights = manager.get_active_weights()
version = manager.get_active_version()

print(f'Active Weights (v{version}):')
print('=' * 40)
for factor, weight in sorted(weights.items(), key=lambda x: -x[1]):
    print(f'  {factor:20} {weight:6.2f}')
print(f'                     ──────')
print(f'  Total:             {sum(weights.values()):6.2f}')
"
```

### Compare Weight Sets

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.core.learning import WeightManager

db = Database('canslim_positions.db')
manager = WeightManager(db)

# Compare active vs baseline (v1)
comparison = manager.compare_weights(
    current_id=manager.get_active_id(),
    candidate_id=1  # Baseline
)

print('Weight Comparison (Active vs Baseline):')
print('=' * 55)
print(f'{\"Factor\":20} {\"Active\":>10} {\"Baseline\":>10} {\"Change\":>10}')
print('-' * 55)
for factor, diff in sorted(comparison.items(), key=lambda x: -abs(x[1]['difference'])):
    print(f\"{factor:20} {diff['set1']:>10.2f} {diff['set2']:>10.2f} {diff['pct_change']:>+9.1f}%\")
"
```

### Activate New Weights

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.core.learning import WeightManager

db = Database('canslim_positions.db')
manager = WeightManager(db)

# List available weight sets
print('Available Weight Sets:')
for w in manager.list_all():
    active = ' (ACTIVE)' if w.is_active else ''
    print(f'  v{w.version}: Accuracy {w.accuracy:.1%}, F1 {w.f1_score:.3f}{active}')

# Activate a specific version
# manager.activate_weights(weights_id=3)
# print('Activated v3')
"
```

### View Outcome Statistics

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.data.models import Outcome
from sqlalchemy import func

db = Database('canslim_positions.db')
session = db.get_new_session()

# Count by outcome type
stats = session.query(
    Outcome.outcome,
    func.count(Outcome.id),
    func.avg(Outcome.gross_pct)
).group_by(Outcome.outcome).all()

print('Outcome Statistics:')
print('=' * 50)
print(f'{\"Outcome\":12} {\"Count\":>8} {\"Avg Return\":>12}')
print('-' * 50)
total = 0
for outcome, count, avg_return in stats:
    total += count
    print(f'{outcome or \"Unknown\":12} {count:>8} {avg_return or 0:>+11.1f}%')
print('-' * 50)
print(f'{\"TOTAL\":12} {total:>8}')

session.close()
"
```

### View Outcomes by Grade

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.data.models import Outcome
from sqlalchemy import func

db = Database('canslim_positions.db')
session = db.get_new_session()

# Win rate by entry grade
stats = session.query(
    Outcome.entry_grade,
    func.count(Outcome.id),
    func.sum(func.case((Outcome.outcome.in_(['SUCCESS', 'PARTIAL']), 1), else_=0)),
    func.avg(Outcome.gross_pct)
).filter(
    Outcome.entry_grade.isnot(None)
).group_by(Outcome.entry_grade).all()

print('Win Rate by Entry Grade:')
print('=' * 55)
print(f'{\"Grade\":8} {\"Count\":>8} {\"Wins\":>8} {\"Win Rate\":>10} {\"Avg Ret\":>10}')
print('-' * 55)
for grade, count, wins, avg_ret in sorted(stats, key=lambda x: x[0] or 'ZZZ'):
    win_rate = (wins or 0) / count * 100 if count > 0 else 0
    print(f'{grade or \"N/A\":8} {count:>8} {wins or 0:>8} {win_rate:>9.1f}% {avg_ret or 0:>+9.1f}%')

session.close()
"
```

### CLI Commands Summary

| Command | Purpose |
|---------|---------|
| `import_backtest` | Import historical trades from backtest DB |
| `import_backtest --dry-run` | Preview import without changes |
| `import_backtest --overwrite` | Clear and reimport all |
| `gui` → Analytics | Launch GUI with analytics dashboard |

### Programmatic Commands Summary

| Action | Method |
|--------|--------|
| Run factor analysis | `LearningService.run_factor_analysis()` |
| Run full optimization | `LearningService.run_full_analysis()` |
| Preview rescore | `LearningService.get_rescore_preview()` |
| Apply rescore | `LearningService.rescore_outcomes()` |
| Get active weights | `WeightManager.get_active_weights()` |
| Activate weights | `WeightManager.activate_weights(id)` |
| Compare weights | `WeightManager.compare_weights(id1, id2)` |

---

## Related Files

| File | Purpose |
|------|---------|
| `core/learning/learning_service.py` | Main orchestration |
| `core/learning/factor_analyzer.py` | Statistical analysis |
| `core/learning/weight_optimizer.py` | Evolutionary optimization |
| `core/learning/weight_manager.py` | Weight storage/activation |
| `core/learning/confidence_engine.py` | Statistical tests |
| `core/learning/backtest_importer.py` | Import historical data |
| `data/models.py` | Outcome, LearnedWeights models |
| `data/repositories/learning_repo.py` | Data access layer |
| `gui/analytics/analytics_dashboard.py` | PyQt6 dashboard |
| `config/learning_config.yaml` | Configuration |
| `utils/scoring.py` | Scoring calculations |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Feb 2026 | Initial documentation |
