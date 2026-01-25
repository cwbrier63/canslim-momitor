#!/usr/bin/env python3
"""
CANSLIM Scoring Engine
======================

Configurable scoring engine that loads rules from YAML config file.
Allows adjusting scoring weights without code changes.

Usage:
    from scoring_engine import ScoringEngine
    
    scorer = ScoringEngine("scoring_config.yaml")
    result = scorer.score(
        pattern="cup w/handle",
        stage="2(2)",
        depth_pct=23,
        length_weeks=7,
        rs_rating=96
    )
    
    print(result.grade)        # "A+"
    print(result.final_score)  # 22
    print(result.details)      # Full breakdown

Author: CANSLIM Monitor Project
Version: 2.3
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ScoreComponent:
    """Individual score component with details."""
    name: str
    value: Any           # The raw input value
    score: int           # Points assigned
    description: str     # Human-readable description
    tier: str = ""       # Optional tier name (e.g., "Elite", "Deep")


@dataclass
class ScoringResult:
    """Complete scoring result."""
    # Final outputs
    grade: str
    final_score: int
    
    # Score breakdown
    static_score: int
    dynamic_score: int
    
    # Individual components
    pattern: ScoreComponent
    stage: ScoreComponent
    depth: ScoreComponent
    length: ScoreComponent
    rs_rating: ScoreComponent
    
    # Dynamic components (may be empty if not calculated)
    dynamic_components: Dict[str, ScoreComponent] = field(default_factory=dict)
    
    # Flags
    rs_floor_applied: bool = False
    original_grade: str = ""
    
    # Config version used
    config_version: str = ""
    
    @property
    def details(self) -> Dict[str, Any]:
        """Return full details as dictionary."""
        return {
            'grade': self.grade,
            'final_score': self.final_score,
            'static_score': self.static_score,
            'dynamic_score': self.dynamic_score,
            'rs_floor_applied': self.rs_floor_applied,
            'original_grade': self.original_grade if self.rs_floor_applied else None,
            'components': {
                'pattern': {'score': self.pattern.score, 'desc': self.pattern.description},
                'stage': {'score': self.stage.score, 'desc': self.stage.description},
                'depth': {'score': self.depth.score, 'desc': self.depth.description},
                'length': {'score': self.length.score, 'desc': self.length.description},
                'rs_rating': {'score': self.rs_rating.score, 'desc': self.rs_rating.description},
            },
            'dynamic': {k: {'score': v.score, 'desc': v.description} 
                       for k, v in self.dynamic_components.items()},
            'config_version': self.config_version
        }


@dataclass 
class ExecutionRiskResult:
    """Execution risk assessment result."""
    risk_level: str      # LOW, MODERATE, HIGH, DO_NOT_TRADE
    adv_50day: int
    volume_status: str   # PASS, CAUTION, FAIL
    volume_pct_of_min: float
    shares_needed: int
    pct_of_adv: float
    spread_pct: Optional[float] = None
    spread_status: Optional[str] = None
    recommendation: str = ""


# =============================================================================
# SCORING ENGINE
# =============================================================================

class ScoringEngine:
    """
    Configurable CANSLIM scoring engine.
    
    Loads scoring rules from YAML config file and provides
    consistent scoring across monitor, validation, and GUI tools.
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize scoring engine with config file.
        
        Args:
            config_path: Path to scoring_config.yaml
                        If None, looks in current directory
        """
        self.config_path = config_path or self._find_config()
        self.config = self._load_config()
        self.version = self.config.get('version', 'unknown')
        
        # Pre-process config for faster lookups
        self._build_pattern_lookup()
        self._build_grade_thresholds()
    
    def _find_config(self) -> str:
        """Find config file in common locations."""
        search_paths = [
            "scoring_config.yaml",
            "config/scoring_config.yaml",
            "../scoring_config.yaml",
            os.path.join(os.path.dirname(__file__), "scoring_config.yaml"),
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                return path
        
        raise FileNotFoundError(
            "scoring_config.yaml not found. Searched: " + ", ".join(search_paths)
        )
    
    def _load_config(self) -> Dict:
        """Load and validate config file."""
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Validate required sections
        required = ['rs_rating', 'patterns', 'stages', 'depth', 'length', 'grades']
        missing = [s for s in required if s not in config]
        if missing:
            raise ValueError(f"Config missing required sections: {missing}")
        
        return config
    
    def _build_pattern_lookup(self):
        """Build fast pattern name to score lookup."""
        self._pattern_scores = {}
        patterns_config = self.config['patterns']
        self._pattern_default = patterns_config.get('default_score', 5)
        
        for pattern_group in patterns_config.get('groups', []):
            if isinstance(pattern_group, dict) and 'names' in pattern_group:
                score = pattern_group['score']
                tier = pattern_group.get('tier', '')
                for name in pattern_group['names']:
                    self._pattern_scores[name.lower()] = (score, tier)
    
    def _build_grade_thresholds(self):
        """Build sorted grade thresholds for fast lookup."""
        boundaries = self.config['grades']['boundaries']
        # Sort by score descending
        self._grade_thresholds = sorted(
            boundaries.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
    
    def reload_config(self):
        """Reload config file (useful for hot-reloading in GUI)."""
        self.config = self._load_config()
        self.version = self.config.get('version', 'unknown')
        self._build_pattern_lookup()
        self._build_grade_thresholds()
    
    # =========================================================================
    # SCORING METHODS
    # =========================================================================
    
    def score(
        self,
        pattern: str,
        stage: str,
        depth_pct: float,
        length_weeks: int,
        rs_rating: int = None,
        dynamic_scores: Dict[str, int] = None
    ) -> ScoringResult:
        """
        Calculate complete score for a setup.
        
        Args:
            pattern: Base pattern type (e.g., "cup w/handle", "flat base")
            stage: Stage string (e.g., "1", "2(2)", "3(4)")
            depth_pct: Base depth as percentage (e.g., 25 for 25%)
            length_weeks: Base length in weeks
            rs_rating: IBD Relative Strength Rating (1-99)
            dynamic_scores: Optional dict of pre-calculated dynamic scores
        
        Returns:
            ScoringResult with grade, scores, and full breakdown
        """
        # Calculate individual components
        pattern_comp = self._score_pattern(pattern)
        stage_comp = self._score_stage(stage)
        depth_comp = self._score_depth(depth_pct)
        length_comp = self._score_length(length_weeks)
        rs_comp = self._score_rs_rating(rs_rating)
        
        # Static score
        static_score = (
            pattern_comp.score +
            stage_comp.score +
            depth_comp.score +
            length_comp.score +
            rs_comp.score
        )
        
        # Dynamic score
        dynamic_components = {}
        dynamic_score = 0
        if dynamic_scores:
            for key, value in dynamic_scores.items():
                dynamic_components[key] = ScoreComponent(
                    name=key,
                    value=value,
                    score=value,
                    description=f"{key}: {value:+d}"
                )
                dynamic_score += value
        
        # Final score and grade
        final_score = static_score + dynamic_score
        grade = self._score_to_grade(final_score)
        
        # Apply RS floor if enabled
        rs_floor_applied = False
        original_grade = grade
        
        floor_config = self.config['rs_rating'].get('floor', {})
        if floor_config.get('enabled', False) and rs_rating is not None:
            threshold = floor_config.get('threshold', 70)
            max_grade = floor_config.get('max_grade', 'C')
            
            if rs_rating < threshold:
                if self._grade_rank(grade) > self._grade_rank(max_grade):
                    rs_floor_applied = True
                    grade = max_grade
        
        return ScoringResult(
            grade=grade,
            final_score=final_score,
            static_score=static_score,
            dynamic_score=dynamic_score,
            pattern=pattern_comp,
            stage=stage_comp,
            depth=depth_comp,
            length=length_comp,
            rs_rating=rs_comp,
            dynamic_components=dynamic_components,
            rs_floor_applied=rs_floor_applied,
            original_grade=original_grade,
            config_version=self.version
        )
    
    def _score_pattern(self, pattern: str) -> ScoreComponent:
        """Score the base pattern type."""
        if not pattern:
            return ScoreComponent(
                name="pattern",
                value=pattern,
                score=self._pattern_default,
                description=f"Unknown pattern (+{self._pattern_default})"
            )
        
        pattern_lower = pattern.lower().strip()
        
        # Check for exact match first
        if pattern_lower in self._pattern_scores:
            score, tier = self._pattern_scores[pattern_lower]
            return ScoreComponent(
                name="pattern",
                value=pattern,
                score=score,
                description=f"{pattern} (+{score})",
                tier=tier
            )
        
        # Check for partial match
        for name, (score, tier) in self._pattern_scores.items():
            if name in pattern_lower or pattern_lower in name:
                return ScoreComponent(
                    name="pattern",
                    value=pattern,
                    score=score,
                    description=f"{pattern} (+{score})",
                    tier=tier
                )
        
        # Default
        return ScoreComponent(
            name="pattern",
            value=pattern,
            score=self._pattern_default,
            description=f"{pattern} (+{self._pattern_default})"
        )
    
    def _score_stage(self, stage: str) -> ScoreComponent:
        """Score the base stage count."""
        stage_config = self.config['stages']
        scores = stage_config['scores']
        bob_bonus = stage_config.get('base_on_base_bonus', 2)
        max_stage = stage_config.get('max_tracked_stage', 4)
        
        stage_str = str(stage).lower().strip()
        
        # Check for base-on-base indicator
        has_bob = '(' in stage_str or 'b' in stage_str
        
        # Extract numeric stage (keep decimal point to handle "1.0", "2.0", etc.)
        stage_clean = ''.join(c for c in stage_str.split('(')[0] if c.isdigit() or c == '.')

        try:
            # Parse as float first to handle decimals, then get integer part
            stage_num = int(float(stage_clean)) if stage_clean else 1
        except ValueError:
            stage_num = 2
        
        # Cap at max tracked stage
        stage_num = min(stage_num, max_stage)
        
        # Get base score
        base_score = scores.get(stage_num, scores.get(max_stage, -8))
        
        # Apply base-on-base bonus
        final_score = base_score
        desc_parts = [f"Stage {stage_num} ({base_score:+d})"]
        
        if has_bob:
            final_score += bob_bonus
            desc_parts.append(f"[base-on-base +{bob_bonus}]")
        
        return ScoreComponent(
            name="stage",
            value=stage,
            score=final_score,
            description=" ".join(desc_parts)
        )
    
    def _score_depth(self, depth_pct: float) -> ScoreComponent:
        """Score the base depth percentage."""
        depth_config = self.config['depth']['tiers']
        
        for tier in depth_config:
            if depth_pct <= tier['max']:
                return ScoreComponent(
                    name="depth",
                    value=depth_pct,
                    score=tier['score'],
                    description=f"{tier['name']} {depth_pct:.0f}% ({tier['score']:+d})",
                    tier=tier['name']
                )
        
        # Should not reach here, but default to last tier
        last_tier = depth_config[-1]
        return ScoreComponent(
            name="depth",
            value=depth_pct,
            score=last_tier['score'],
            description=f"Very Deep {depth_pct:.0f}% ({last_tier['score']:+d})",
            tier="Very Deep"
        )
    
    def _score_length(self, length_weeks: int) -> ScoreComponent:
        """Score the base length in weeks."""
        length_config = self.config['length']['tiers']
        
        # Tiers are sorted by min descending, so first match wins
        for tier in length_config:
            if length_weeks >= tier['min']:
                return ScoreComponent(
                    name="length",
                    value=length_weeks,
                    score=tier['score'],
                    description=f"{tier['name']} {length_weeks}w ({tier['score']:+d})",
                    tier=tier['name']
                )
        
        # Default to last tier
        last_tier = length_config[-1]
        return ScoreComponent(
            name="length",
            value=length_weeks,
            score=last_tier['score'],
            description=f"Short {length_weeks}w ({last_tier['score']:+d})",
            tier="Short"
        )
    
    def _score_rs_rating(self, rs_rating: int) -> ScoreComponent:
        """Score the RS Rating."""
        if rs_rating is None:
            return ScoreComponent(
                name="rs_rating",
                value=None,
                score=0,
                description="RS Rating: N/A (0)"
            )
        
        rs_config = self.config['rs_rating']['tiers']
        
        for tier in rs_config:
            if tier['min'] <= rs_rating <= tier['max']:
                return ScoreComponent(
                    name="rs_rating",
                    value=rs_rating,
                    score=tier['score'],
                    description=f"RS {rs_rating} - {tier['name']} ({tier['score']:+d})",
                    tier=tier['name']
                )
        
        # Default to weak
        return ScoreComponent(
            name="rs_rating",
            value=rs_rating,
            score=-5,
            description=f"RS {rs_rating} - Unknown (-5)"
        )
    
    def _score_to_grade(self, score: int) -> str:
        """Convert numeric score to letter grade."""
        for grade, threshold in self._grade_thresholds:
            if score >= threshold:
                return grade
        return "F"
    
    def _grade_rank(self, grade: str) -> int:
        """Get numeric rank for grade comparison (higher = better)."""
        ranks = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
        return ranks.get(grade, 0)
    
    # =========================================================================
    # EXECUTION RISK
    # =========================================================================
    
    def assess_execution_risk(
        self,
        grade: str,
        current_price: float,
        adv_50day: int,
        portfolio_value: float = None,
        bid: float = None,
        ask: float = None
    ) -> ExecutionRiskResult:
        """
        Assess execution risk for a trade.
        
        Args:
            grade: Setup grade (determines position size)
            current_price: Current stock price
            adv_50day: 50-day average daily volume
            portfolio_value: Total portfolio value (uses config default if None)
            bid: Current bid price (optional)
            ask: Current ask price (optional)
        
        Returns:
            ExecutionRiskResult with risk assessment
        """
        exec_config = self.config.get('execution', {})
        sizing_config = self.config.get('position_sizing', {})
        
        # Get portfolio value
        if portfolio_value is None:
            portfolio_value = sizing_config.get('default_portfolio_value', 100000)
        
        # Calculate position size based on grade
        allocations = sizing_config.get('allocations', {})
        allocation_pct = allocations.get(grade, 0)
        position_value = portfolio_value * allocation_pct
        
        # Calculate shares needed
        shares_needed = int(position_value / current_price) if current_price > 0 else 0
        
        # Volume assessment
        vol_config = exec_config.get('volume', {})
        vol_pass = vol_config.get('pass', 500000)
        vol_caution = vol_config.get('caution', 400000)
        
        if adv_50day >= vol_pass:
            volume_status = "PASS"
        elif adv_50day >= vol_caution:
            volume_status = "CAUTION"
        else:
            volume_status = "FAIL"
        
        volume_pct = (adv_50day / vol_pass * 100) if vol_pass > 0 else 0
        
        # Position impact
        pct_of_adv = (shares_needed / adv_50day * 100) if adv_50day > 0 else 999
        
        impact_config = exec_config.get('position_impact', {})
        low_thresh = impact_config.get('low', 1.0)
        mod_thresh = impact_config.get('moderate', 2.0)
        high_thresh = impact_config.get('high', 5.0)
        
        # Spread assessment
        spread_pct = None
        spread_status = None
        if bid and ask and bid > 0:
            spread_pct = (ask - bid) / ((bid + ask) / 2) * 100
            spread_config = exec_config.get('spread', {})
            if spread_pct <= spread_config.get('tight', 0.10):
                spread_status = "TIGHT"
            elif spread_pct <= spread_config.get('normal', 0.30):
                spread_status = "NORMAL"
            else:
                spread_status = "WIDE"
        
        # Overall risk level
        if volume_status == "FAIL":
            risk_level = "DO_NOT_TRADE"
            recommendation = "Skip trade - fails IBD volume requirements"
        elif pct_of_adv > high_thresh:
            risk_level = "DO_NOT_TRADE"
            recommendation = "Skip trade - position too large relative to volume"
        elif volume_status == "CAUTION" or pct_of_adv > mod_thresh:
            risk_level = "HIGH"
            recommendation = "Size down significantly; use limit orders; consider splitting"
        elif pct_of_adv > low_thresh or spread_status == "WIDE":
            risk_level = "MODERATE"
            recommendation = "Use limit orders; be patient on entry"
        else:
            risk_level = "LOW"
            recommendation = "Normal execution - standard limit order"
        
        return ExecutionRiskResult(
            risk_level=risk_level,
            adv_50day=adv_50day,
            volume_status=volume_status,
            volume_pct_of_min=round(volume_pct, 1),
            shares_needed=shares_needed,
            pct_of_adv=round(pct_of_adv, 2),
            spread_pct=round(spread_pct, 3) if spread_pct else None,
            spread_status=spread_status,
            recommendation=recommendation
        )
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_config_summary(self) -> str:
        """Return human-readable config summary."""
        lines = [
            f"CANSLIM Scoring Engine v{self.version}",
            f"Config: {self.config_path}",
            "",
            "RS Rating Scores:",
        ]
        
        for tier in self.config['rs_rating']['tiers']:
            lines.append(f"  {tier['name']}: {tier['min']}-{tier['max']} = {tier['score']:+d}")
        
        floor = self.config['rs_rating'].get('floor', {})
        if floor.get('enabled'):
            lines.append(f"  Floor: RS < {floor['threshold']} capped at {floor['max_grade']}")
        
        lines.extend(["", "Grade Boundaries:"])
        for grade, threshold in self._grade_thresholds:
            lines.append(f"  {grade}: >= {threshold}")
        
        return "\n".join(lines)
    
    def format_discord_alert(
        self,
        symbol: str,
        current_price: float,
        pivot: float,
        result: ScoringResult,
        exec_risk: ExecutionRiskResult = None
    ) -> str:
        """
        Format a Discord alert message.
        
        Args:
            symbol: Stock symbol
            current_price: Current price
            pivot: Pivot/buy point
            result: ScoringResult from score()
            exec_risk: Optional ExecutionRiskResult
        
        Returns:
            Formatted Discord message string
        """
        pct_above = ((current_price - pivot) / pivot * 100) if pivot > 0 else 0
        buy_zone_top = pivot * 1.05
        
        lines = [
            f"🚀 BREAKOUT: {symbol}",
            "",
            f"Price: ${current_price:.2f} ({pct_above:+.1f}% above pivot)",
            f"Pivot: ${pivot:.2f} | Buy Zone: ${pivot:.2f} - ${buy_zone_top:.2f}",
            "",
            f"📊 SETUP QUALITY: {result.grade} (Score: {result.final_score})",
            f"   Pattern: {result.pattern.value} | Stage {result.stage.value} | RS: {result.rs_rating.value or 'N/A'}",
        ]
        
        if result.rs_floor_applied:
            lines.append(f"   ⚠️ RS Floor applied (RS < 70)")
        
        if exec_risk:
            risk_emoji = {
                "LOW": "✅",
                "MODERATE": "⚠️",
                "HIGH": "⚠️",
                "DO_NOT_TRADE": "⛔"
            }.get(exec_risk.risk_level, "❓")
            
            lines.extend([
                "",
                f"⚡ EXECUTION: {exec_risk.risk_level} {risk_emoji}",
                f"   ADV: {exec_risk.adv_50day:,.0f} | Position: {exec_risk.pct_of_adv:.2f}% of ADV",
                "",
                f"{risk_emoji} {exec_risk.recommendation}"
            ])
        
        return "\n".join(lines)


# =============================================================================
# STANDALONE USAGE
# =============================================================================

def main():
    """Test the scoring engine."""
    import sys
    
    # Find config file
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    
    try:
        engine = ScoringEngine(config_path)
        print(engine.get_config_summary())
        print("\n" + "="*60 + "\n")
        
        # Test case: TTMI from validation
        result = engine.score(
            pattern="cup w/handle",
            stage="2(2)",
            depth_pct=23,
            length_weeks=7,
            rs_rating=96,
            dynamic_scores={'up_down_ratio': 3, 'ma_position': 2, 'support': 2, 'rs_trend': 2, 'volume_dryup': 1}
        )
        
        print("Test Case: TTMI")
        print(f"Grade: {result.grade}")
        print(f"Final Score: {result.final_score}")
        print(f"Static: {result.static_score}, Dynamic: {result.dynamic_score}")
        print(f"\nBreakdown:")
        print(f"  {result.pattern.description}")
        print(f"  {result.stage.description}")
        print(f"  {result.depth.description}")
        print(f"  {result.length.description}")
        print(f"  {result.rs_rating.description}")
        
        if result.rs_floor_applied:
            print(f"\n⚠️ RS Floor: {result.original_grade} -> {result.grade}")
        
        # Test execution risk
        exec_risk = engine.assess_execution_risk(
            grade=result.grade,
            current_price=51.85,
            adv_50day=2445289
        )
        
        print(f"\nExecution Risk: {exec_risk.risk_level}")
        print(f"  {exec_risk.recommendation}")
        
        # Test Discord format
        print("\n" + "="*60)
        print("Discord Alert Preview:")
        print("="*60)
        print(engine.format_discord_alert(
            symbol="TTMI",
            current_price=51.85,
            pivot=50.78,
            result=result,
            exec_risk=exec_risk
        ))
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
