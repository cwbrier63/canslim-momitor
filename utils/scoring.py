"""
CANSLIM Monitor - Entry Scoring System
Loads scoring rules from scoring_config.yaml for consistency with CLI validator.
"""

import os
import json
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class ScoreComponent:
    """A single scoring component with points and reason."""
    name: str
    points: int
    max_points: int
    reason: str


# Default configuration (matches scoring_config.yaml v2.3)
DEFAULT_CONFIG = {
    'version': '2.3',
    
    'rs_rating': {
        'tiers': [
            {'name': 'Elite', 'min': 95, 'max': 100, 'score': 5},
            {'name': 'Excellent', 'min': 90, 'max': 94, 'score': 4},
            {'name': 'Good', 'min': 80, 'max': 89, 'score': 2},
            {'name': 'Acceptable', 'min': 70, 'max': 79, 'score': 0},
            {'name': 'Weak', 'min': 0, 'max': 69, 'score': -5},
        ],
        'floor': {
            'enabled': True,
            'threshold': 70,
            'max_grade': 'C'
        }
    },
    
    'patterns': [
        {'names': ['cup with handle', 'cup w/handle', 'cup w/ handle'], 'score': 10, 'tier': 'A'},
        {'names': ['double bottom'], 'score': 9, 'tier': 'A'},
        {'names': ['flat base', 'high tight flag'], 'score': 8, 'tier': 'B'},
        {'names': ['cup', 'cup no handle', 'ascending base', 'ipo base'], 'score': 7, 'tier': 'B'},
        {'names': ['consolidation', 'base on base', 'saucer', 'saucer with handle', 'saucer w/handle'], 'score': 6, 'tier': 'C'},
        {'names': ['3 weeks tight', 'three weeks tight', 'shakeout +3', 'shakeout plus 3'], 'score': 6, 'tier': 'C'},
    ],
    'pattern_default_score': 5,
    
    'stages': {
        'scores': {
            '1': 0, '1(1)': 0,
            '2': -1, '2(2)': -1, '2(3)': -2, '2b': -1,
            '3': -4, '3(3)': -4, '3(4)': -5, '3b': -4,
            '4': -8, '4+': -10,
            'Late': -10
        },
        'base_on_base_bonus': 2
    },
    
    'depth': {
        'tiers': [
            {'name': 'Shallow', 'max': 15, 'score': 1},
            {'name': 'Normal', 'max': 25, 'score': 0},
            {'name': 'Deep', 'max': 35, 'score': -2},
            {'name': 'Very Deep', 'max': 100, 'score': -5},
        ]
    },
    
    'length': {
        'tiers': [
            {'name': 'Ideal', 'min': 7, 'score': 1},
            {'name': 'Acceptable', 'min': 5, 'score': 0},
            {'name': 'Short', 'min': 0, 'score': -1},
        ]
    },
    
    'eps_rating': {
        'tiers': [
            {'name': 'Elite', 'min': 90, 'score': 3},
            {'name': 'Good', 'min': 80, 'score': 2},
            {'name': 'Acceptable', 'min': 70, 'score': 1},
            {'name': 'Weak', 'min': 0, 'score': 0},
        ]
    },
    
    'ad_rating': {
        'scores': {
            'A+': 3, 'A': 2, 'A-': 2,
            'B+': 1, 'B': 1, 'B-': 0,
            'C+': 0, 'C': 0, 'C-': -1,
            'D+': -1, 'D': -2, 'D-': -2,
            'E': -3
        }
    },
    
    'grades': {
        'boundaries': {
            'A+': 20,
            'A': 15,
            'B+': 12,
            'B': 9,
            'C+': 7,
            'C': 5,
            'D': 3,
            'F': 0
        }
    }
}


class CANSLIMScorer:
    """
    Calculates CANSLIM entry scores for positions.
    
    Loads configuration from scoring_config.yaml if available,
    otherwise uses built-in defaults matching CLI validator v2.3.
    
    Score Range: Approximately -15 to +25 points
    
    Grades:
    - A+: ≥20 pts
    - A: ≥15 pts
    - B+: ≥12 pts
    - B: ≥9 pts
    - C+: ≥7 pts
    - C: ≥5 pts
    - D: ≥3 pts
    - F: <3 pts
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize scorer with optional config file path.
        
        Args:
            config_path: Path to scoring_config.yaml. If None, searches
                        common locations, then falls back to defaults.
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.version = self.config.get('version', 'unknown')
        
        # Build lookup tables
        self._build_pattern_lookup()
        self._build_grade_thresholds()
    
    def _find_config(self) -> Optional[str]:
        """Find config file in common locations."""
        search_paths = [
            "scoring_config.yaml",
            "config/scoring_config.yaml",
            "../scoring_config.yaml",
            "canslim_monitor/config/scoring_config.yaml",
            os.path.join(os.path.dirname(__file__), "..", "config", "scoring_config.yaml"),
            os.path.expanduser("~/.canslim/scoring_config.yaml"),
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def _load_config(self) -> Dict:
        """Load config from file or use defaults."""
        # Try explicit path first
        if self.config_path and os.path.exists(self.config_path):
            return self._load_yaml(self.config_path)
        
        # Search common locations
        found_path = self._find_config()
        if found_path:
            self.config_path = found_path
            return self._load_yaml(found_path)
        
        # Use defaults
        self.config_path = None
        return DEFAULT_CONFIG.copy()
    
    def _load_yaml(self, path: str) -> Dict:
        """Load YAML config file."""
        if not HAS_YAML:
            print(f"Warning: PyYAML not installed, using default config")
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Merge with defaults for any missing keys
            merged = DEFAULT_CONFIG.copy()
            self._deep_merge(merged, config)
            return merged
            
        except Exception as e:
            print(f"Warning: Error loading {path}: {e}, using defaults")
            return DEFAULT_CONFIG.copy()
    
    def _deep_merge(self, base: Dict, override: Dict):
        """Deep merge override into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def _build_pattern_lookup(self):
        """Build fast pattern name to score lookup."""
        self._pattern_scores = {}
        self._pattern_default = self.config.get('pattern_default_score', 5)
        
        patterns_config = self.config.get('patterns', [])
        
        # Handle YAML structure: patterns.groups (dict with 'groups' key)
        # or DEFAULT_CONFIG structure: patterns (list directly)
        if isinstance(patterns_config, dict):
            # YAML format: {'groups': [...], 'default_score': 5}
            pattern_groups = patterns_config.get('groups', [])
            self._pattern_default = patterns_config.get('default_score', self._pattern_default)
        elif isinstance(patterns_config, list):
            # DEFAULT_CONFIG format: direct list
            pattern_groups = patterns_config
        else:
            pattern_groups = []
        
        # Build lookup from pattern groups
        for pattern_group in pattern_groups:
            if isinstance(pattern_group, dict) and 'names' in pattern_group:
                score = pattern_group['score']
                tier = pattern_group.get('tier', '')
                for name in pattern_group['names']:
                    self._pattern_scores[name.lower()] = (score, tier)
        
        # Also add aliases from constants module if available
        try:
            from ..constants import PATTERN_ALIASES, PATTERN_SCORES
            for alias, canonical in PATTERN_ALIASES.items():
                if alias not in self._pattern_scores and canonical in PATTERN_SCORES:
                    score, tier = PATTERN_SCORES[canonical]
                    self._pattern_scores[alias] = (score, tier)
        except ImportError:
            pass  # Constants module not available, skip aliases
    
    def _build_grade_thresholds(self):
        """Build sorted grade thresholds for fast lookup."""
        boundaries = self.config.get('grades', {}).get('boundaries', DEFAULT_CONFIG['grades']['boundaries'])
        # Sort by score descending
        self._grade_thresholds = sorted(
            boundaries.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
    
    def calculate_score(self, position_data: Dict[str, Any], market_regime: str = 'BULLISH') -> Tuple[int, str, Dict]:
        """
        Calculate entry score for a position.
        
        Args:
            position_data: Dict with position attributes
            market_regime: Current market regime (BULLISH, CAUTIOUS, BEARISH)
            
        Returns:
            Tuple of (total_score, grade, details_dict)
            
        Note: 
            - Base score = Static factors only (Pattern, Stage, Depth, Length, RS)
            - Dynamic factors will be added in Phase 2
            - EPS/A/D ratings are tracked as supplemental data for ML training
              but NOT included in the base score to match CLI validator
        """
        static_components = []
        supplemental_components = []
        static_total = 0
        
        # =====================================================
        # STATIC FACTORS (included in score - matches CLI)
        # =====================================================
        
        # 1. RS Rating
        rs_score, rs_reason = self._score_rs_rating(position_data)
        static_total += rs_score
        static_components.append(ScoreComponent("RS Rating", rs_score, 5, rs_reason))
        
        # 2. Pattern
        pattern_score, pattern_reason = self._score_pattern(position_data)
        static_total += pattern_score
        static_components.append(ScoreComponent("Pattern", pattern_score, 10, pattern_reason))
        
        # 3. Stage
        stage_score, stage_reason = self._score_stage(position_data)
        static_total += stage_score
        static_components.append(ScoreComponent("Stage", stage_score, 0, stage_reason))
        
        # 4. Depth
        depth_score, depth_reason = self._score_depth(position_data)
        static_total += depth_score
        static_components.append(ScoreComponent("Depth", depth_score, 1, depth_reason))
        
        # 5. Length
        length_score, length_reason = self._score_length(position_data)
        static_total += length_score
        static_components.append(ScoreComponent("Length", length_score, 1, length_reason))
        
        # =====================================================
        # SUPPLEMENTAL DATA (NOT included in score - for ML)
        # =====================================================
        
        # EPS Rating (tracked for ML training, not scored)
        eps_score, eps_reason = self._score_eps_rating(position_data)
        supplemental_components.append(ScoreComponent("EPS Rating", eps_score, 3, eps_reason))
        
        # A/D Rating (tracked for ML training, not scored)
        ad_score, ad_reason = self._score_ad_rating(position_data)
        supplemental_components.append(ScoreComponent("A/D Rating", ad_score, 3, ad_reason))
        
        # =====================================================
        # CALCULATE FINAL SCORE
        # =====================================================
        
        # Base score = Static only (Dynamic will be added in Phase 2)
        total_score = static_total
        
        # Determine grade
        grade = self._score_to_grade(total_score)
        
        # Apply RS floor rule
        rs_rating = position_data.get('rs_rating') or 0
        rs_floor = self.config.get('rs_rating', {}).get('floor', {})
        if rs_floor.get('enabled', True):
            threshold = rs_floor.get('threshold', 70)
            max_grade = rs_floor.get('max_grade', 'C')
            if rs_rating < threshold and rs_rating > 0:
                grade = self._cap_grade(grade, max_grade)
        
        # Build details dict
        all_components = static_components + supplemental_components
        details = {
            'total_score': total_score,
            'static_score': static_total,
            'dynamic_score': 0,  # Will be populated in Phase 2
            'grade': grade,
            'config_version': self.version,
            'config_path': self.config_path,
            'market_regime': market_regime,
            'components': [
                {
                    'name': c.name,
                    'points': c.points,
                    'max_points': c.max_points,
                    'reason': c.reason
                }
                for c in all_components
            ],
            'dynamic_components': [],  # Will be populated in Phase 2
        }
        
        return total_score, grade, details
    
    def calculate_score_with_dynamic(
        self, 
        position_data: Dict[str, Any], 
        daily_df: 'pd.DataFrame',
        index_df: 'pd.DataFrame' = None,
        market_regime: str = 'BULLISH'
    ) -> Tuple[int, str, Dict]:
        """
        Calculate entry score including dynamic factors from technical analysis.
        
        Args:
            position_data: Dict with position attributes
            daily_df: DataFrame with columns: date, open, high, low, close, volume
            index_df: Optional SPY data for RS calculations
            market_regime: Current market regime
            
        Returns:
            Tuple of (total_score, grade, details_dict)
        """
        # First calculate static score
        static_score, static_grade, details = self.calculate_score(position_data, market_regime)
        
        if daily_df is None or len(daily_df) < 50:
            # Not enough data for dynamic analysis
            return static_score, static_grade, details
        
        try:
            from .indicators import build_technical_profile
            
            # Get base length from position data (default 12 weeks)
            base_length = position_data.get('base_length', 12)
            if isinstance(base_length, str):
                base_length = int(''.join(filter(str.isdigit, base_length)) or 12)
            
            # Build technical profile
            profile = build_technical_profile(
                symbol=position_data.get('symbol', 'UNKNOWN'),
                daily_df=daily_df,
                index_df=index_df,
                base_length_weeks=base_length
            )
            
            # Extract dynamic scores
            dynamic_components = []
            dynamic_total = 0
            
            # Up/Down Volume Ratio
            if profile.indicator_details.get('up_down_ratio'):
                ind = profile.indicator_details['up_down_ratio']
                dynamic_components.append({
                    'name': 'Up/Down Ratio',
                    'points': ind.score,
                    'max_points': 3,
                    'reason': f"{ind.value:.2f} - {ind.description}"
                })
                dynamic_total += ind.score
            
            # MA Position
            if profile.indicator_details.get('ma_position'):
                ind = profile.indicator_details['ma_position']
                dynamic_components.append({
                    'name': '50-MA Position',
                    'points': ind.score,
                    'max_points': 2,
                    'reason': ind.description
                })
                dynamic_total += ind.score
            
            # Support Bounces
            if profile.indicator_details.get('support_bounces'):
                ind = profile.indicator_details['support_bounces']
                dynamic_components.append({
                    'name': '10W Support',
                    'points': ind.score,
                    'max_points': 2,
                    'reason': f"{int(ind.value)} bounces"
                })
                dynamic_total += ind.score
            
            # RS Trend
            if profile.indicator_details.get('rs_trend'):
                ind = profile.indicator_details['rs_trend']
                dynamic_components.append({
                    'name': 'RS Trend',
                    'points': ind.score,
                    'max_points': 2,
                    'reason': ind.description
                })
                dynamic_total += ind.score
            
            # Volume Dry-Up
            if profile.indicator_details.get('volume_dryup'):
                ind = profile.indicator_details['volume_dryup']
                dynamic_components.append({
                    'name': 'Volume Dry-Up',
                    'points': ind.score,
                    'max_points': 2,
                    'reason': ind.description
                })
                dynamic_total += ind.score
            
            # Update details with dynamic components
            details['dynamic_components'] = dynamic_components
            details['dynamic_score'] = dynamic_total
            
            # Recalculate total score with dynamic factors
            total_score = details['static_score'] + dynamic_total
            details['total_score'] = total_score
            
            # Recalculate grade
            grade = self._score_to_grade(total_score)
            
            # Re-apply RS floor
            rs_rating = position_data.get('rs_rating') or 0
            rs_floor = self.config.get('rs_rating', {}).get('floor', {})
            if rs_floor.get('enabled', True):
                threshold = rs_floor.get('threshold', 70)
                max_grade = rs_floor.get('max_grade', 'C')
                if rs_rating < threshold and rs_rating > 0:
                    grade = self._cap_grade(grade, max_grade)
            
            details['grade'] = grade
            
            return total_score, grade, details
            
        except ImportError as e:
            # Indicators module not available
            return static_score, static_grade, details
        except Exception as e:
            # Log error but return static score
            import logging
            logging.getLogger('canslim.scoring').warning(
                f"Dynamic scoring failed: {e}, using static score only"
            )
            return static_score, static_grade, details
    
    def score(self, position, price_data: Dict = None, market_regime: str = 'BULLISH') -> Dict:
        """
        Convenience wrapper for calculate_score that accepts a Position object.
        
        Args:
            position: Position object or dict with position attributes
            price_data: Optional price data (not currently used but kept for API compatibility)
            market_regime: Current market regime
            
        Returns:
            Dict with 'grade', 'score', and 'details' keys
        """
        # Convert Position object to dict if needed
        if hasattr(position, '__dict__'):
            # It's a Position object, extract relevant fields
            position_data = {
                'symbol': getattr(position, 'symbol', None),
                'rs_rating': getattr(position, 'rs_rating', None),
                'eps_rating': getattr(position, 'eps_rating', None),
                'comp_rating': getattr(position, 'comp_rating', None),
                'ad_rating': getattr(position, 'ad_rating', None),
                'pattern': getattr(position, 'pattern', None),
                'stage': getattr(position, 'stage', None),
                'base_depth': getattr(position, 'base_depth', None),
                'base_length': getattr(position, 'base_length', None),
                'ud_volume_ratio': getattr(position, 'ud_volume_ratio', None),
                'avg_volume': getattr(position, 'avg_volume', None),
            }
        else:
            position_data = position
        
        # Call the main scoring method
        total_score, grade, details = self.calculate_score(position_data, market_regime)
        
        # Return in the format expected by breakout_thread
        return {
            'grade': grade,
            'score': total_score,
            'details': details
        }
    
    def _score_rs_rating(self, data: Dict) -> Tuple[int, str]:
        """Score RS Rating."""
        rs = data.get('rs_rating') or 0
        
        if not rs:
            return 0, "No RS rating"
        
        tiers = self.config.get('rs_rating', {}).get('tiers', [])
        for tier in tiers:
            if tier['min'] <= rs <= tier['max']:
                return tier['score'], f"RS {rs} ({tier['name']})"
        
        return 0, f"RS {rs}"
    
    def _score_pattern(self, data: Dict) -> Tuple[int, str]:
        """Score pattern quality."""
        pattern = data.get('pattern') or ''
        
        if not pattern:
            return self._pattern_default, "No pattern specified"
        
        pattern_lower = pattern.lower().strip()
        
        # Direct lookup in built patterns
        if pattern_lower in self._pattern_scores:
            score, tier = self._pattern_scores[pattern_lower]
            return score, f"{pattern} (Tier {tier})" if tier else f"{pattern} (+{score})"
        
        # Try constants module for better alias support
        try:
            from ..constants import get_pattern_score
            score, tier, canonical = get_pattern_score(pattern)
            if tier:  # Recognized pattern
                return score, f"{canonical} (Tier {tier})"
        except ImportError:
            pass  # Constants module not available
        
        # Fallback: Partial match in local lookup
        for name, (score, tier) in self._pattern_scores.items():
            if name in pattern_lower or pattern_lower in name:
                return score, f"{pattern} (Tier {tier})" if tier else f"{pattern} (+{score})"
        
        return self._pattern_default, f"{pattern} (Unrecognized)"
    
    def _score_stage(self, data: Dict) -> Tuple[int, str]:
        """
        Score base stage.
        
        Matches CLI validation tool behavior:
        - Stage 1: 0 pts (best odds)
        - Stage 2: -1 pts (still good)
        - Stage 3: -4 pts (elevated risk)
        - Stage 4+: -8 pts (high risk)
        - Base-on-base (notation with parentheses): +2 bonus
        
        Examples:
        - "1" -> 0
        - "2" -> -1
        - "2(2)" -> -1 + 2 = 1 (base-on-base bonus)
        - "3" -> -4
        - "3(3)" -> -4 + 2 = -2
        """
        stage = data.get('base_stage') or ''
        stage = str(stage) if stage else ''
        
        if not stage:
            return 0, "No stage specified"
        
        stage_str = stage.lower().strip()
        
        # Check for base-on-base indicator (parentheses notation)
        base_on_base = False
        if "(" in stage_str:
            base_on_base = True
            stage_str = stage_str.split("(")[0].strip()
        
        # Remove letters (like 'b' in '2b')
        stage_clean = ''.join(c for c in stage_str if c.isdigit())
        
        try:
            stage_num = int(stage_clean) if stage_clean else 1
        except ValueError:
            stage_num = 2
        
        # Base stage scores (before base-on-base bonus)
        if stage_num == 1:
            score, desc = 0, f"Stage {stage} (0)"
        elif stage_num == 2:
            score, desc = -1, f"Stage {stage} (-1)"
        elif stage_num == 3:
            score, desc = -4, f"Stage {stage} (-4)"
        else:
            score, desc = -8, f"Stage {stage} (-8)"
        
        # Handle special "Late" designation
        if 'late' in stage.lower():
            score, desc = -10, f"Stage {stage} (-10)"
        
        # Apply base-on-base bonus
        bob_bonus = self.config.get('stages', {}).get('base_on_base_bonus', 2)
        if base_on_base:
            score += bob_bonus
            desc += f" [+{bob_bonus} base-on-base]"
        
        return score, desc
    
    def _score_depth(self, data: Dict) -> Tuple[int, str]:
        """Score base depth."""
        depth = data.get('base_depth') or 0
        
        if not depth:
            return 0, "No depth specified"
        
        # Handle string depth like "15%" or "15"
        if isinstance(depth, str):
            depth = float(depth.replace('%', ''))
        
        tiers = self.config.get('depth', {}).get('tiers', [])
        for tier in tiers:
            if depth <= tier['max']:
                return tier['score'], f"{depth}% ({tier['name']})"
        
        return -5, f"{depth}% (Very Deep)"
    
    def _score_length(self, data: Dict) -> Tuple[int, str]:
        """Score base length in weeks."""
        length = data.get('base_length') or 0
        
        if not length:
            return 0, "No length specified"
        
        # Handle string like "7 weeks" or "7"
        if isinstance(length, str):
            length = int(''.join(filter(str.isdigit, length)) or 0)
        
        tiers = self.config.get('length', {}).get('tiers', [])
        # Sort by min descending to find highest qualifying tier
        sorted_tiers = sorted(tiers, key=lambda x: x.get('min', 0), reverse=True)
        
        for tier in sorted_tiers:
            if length >= tier.get('min', 0):
                return tier['score'], f"{length} weeks ({tier['name']})"
        
        return -1, f"{length} weeks (Short)"
    
    def _score_eps_rating(self, data: Dict) -> Tuple[int, str]:
        """Score EPS Rating."""
        eps = data.get('eps_rating') or 0
        
        if not eps:
            return 0, "No EPS rating"
        
        tiers = self.config.get('eps_rating', {}).get('tiers', [])
        sorted_tiers = sorted(tiers, key=lambda x: x.get('min', 0), reverse=True)
        
        for tier in sorted_tiers:
            if eps >= tier.get('min', 0):
                return tier['score'], f"EPS {eps} ({tier['name']})"
        
        return 0, f"EPS {eps}"
    
    def _score_ad_rating(self, data: Dict) -> Tuple[int, str]:
        """Score A/D Rating."""
        ad = data.get('ad_rating') or ''
        
        if not ad:
            return 0, "No A/D rating"
        
        ad_scores = self.config.get('ad_rating', {}).get('scores', {})
        score = ad_scores.get(ad, 0)
        
        return score, f"A/D {ad}"
    
    def _score_to_grade(self, score: int) -> str:
        """Convert numeric score to letter grade."""
        for grade, threshold in self._grade_thresholds:
            if score >= threshold:
                return grade
        return 'F'
    
    def _cap_grade(self, grade: str, max_grade: str) -> str:
        """Cap a grade at a maximum level."""
        grade_order = ['A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'F']
        
        try:
            grade_idx = grade_order.index(grade)
            max_idx = grade_order.index(max_grade)
            
            if grade_idx < max_idx:
                return max_grade
            return grade
        except ValueError:
            return grade
    
    def format_details_text(self, details: Dict, symbol: str = None, pivot: float = None) -> str:
        """
        Format score details as human-readable text matching CLI validator output.
        
        Args:
            details: Score details dict from calculate_score()
            symbol: Optional symbol for header
            pivot: Optional pivot price for header
        """
        lines = []
        
        # Header
        header_symbol = symbol or "POSITION"
        lines.append("════════════════════════════════════════════════════════════")
        lines.append(f"CANSLIM SCORE REPORT: {header_symbol}")
        lines.append("════════════════════════════════════════════════════════════")
        
        # Analysis info
        from datetime import date
        lines.append(f"Analysis Date: {date.today().isoformat()}")
        if pivot:
            lines.append(f"Pivot: ${pivot:.2f}")
        lines.append(f"Config: v{details.get('config_version', '?')}")
        lines.append(f"Market: {details.get('market_regime', 'Unknown')}")
        lines.append("")
        lines.append(f"GRADE: {details['grade']} (Score: {details['total_score']})")
        lines.append("")
        
        # Categorize components
        static_components = []
        supplemental_components = []
        
        static_names = {'RS Rating', 'Pattern', 'Stage', 'Depth', 'Length'}
        supplemental_names = {'EPS Rating', 'A/D Rating'}
        
        for comp in details.get('components', []):
            if comp['name'] in static_names:
                static_components.append(comp)
            elif comp['name'] in supplemental_names:
                supplemental_components.append(comp)
        
        # STATIC FACTORS
        lines.append("--- STATIC FACTORS (Sheet Data) ---")
        static_total = 0
        for comp in static_components:
            sign = '+' if comp['points'] >= 0 else ''
            static_total += comp['points']
            lines.append(f"  {comp['name']:<12} {comp['reason']} ({sign}{comp['points']})")
        lines.append(f"  Subtotal: {static_total}")
        lines.append("")
        
        # DYNAMIC FACTORS (placeholder for now - will be populated in Phase 2)
        lines.append("--- DYNAMIC FACTORS (Technical Analysis) ---")
        dynamic_components = details.get('dynamic_components', [])
        dynamic_total = 0
        
        if dynamic_components:
            for comp in dynamic_components:
                sign = '+' if comp['points'] >= 0 else ''
                dynamic_total += comp['points']
                lines.append(f"  {comp['name']:<15} {comp['reason']} ({sign}{comp['points']})")
            lines.append(f"  Subtotal: {dynamic_total}")
        else:
            lines.append("  Up/Down Ratio:    N/A (requires market data)")
            lines.append("  50-MA Position:   N/A")
            lines.append("  10W Support:      N/A")
            lines.append("  RS Trend:         N/A")
            lines.append("  Volume Dry-Up:    N/A")
            lines.append("  Subtotal: 0")
        lines.append("")
        
        # TOTALS
        base_score = static_total + dynamic_total
        lines.append("════════════════════════════════════════════════════════════")
        lines.append(f"BASE SCORE:   {base_score} (Static {static_total} + Dynamic {dynamic_total})")
        lines.append(f"FINAL SCORE:  {details['total_score']}")
        lines.append(f"GRADE:        {details['grade']}")
        
        # Grade interpretation
        grade = details['grade']
        if grade in ('A+', 'A'):
            interp = "Excellent setup - high probability"
        elif grade in ('B+', 'B'):
            interp = "Good setup - above average odds"
        elif grade in ('C+', 'C'):
            interp = "Average setup - proceed with caution"
        else:
            interp = "Weak setup - consider passing"
        lines.append(interp)
        lines.append("════════════════════════════════════════════════════════════")
        
        # EXECUTION FEASIBILITY (if data available)
        exec_data = details.get('execution', {})
        if exec_data:
            lines.append("")
            lines.append("--- EXECUTION FEASIBILITY ---")
            
            # ADV
            adv = exec_data.get('adv_50day', 0)
            adv_status = exec_data.get('adv_status', 'N/A')
            adv_pct = exec_data.get('adv_pct_of_min', 0)
            adv_emoji = "✅" if adv_status == 'PASS' else "⚠️" if adv_status == 'CAUTION' else "❌"
            lines.append(f"  ADV (50-day):    {adv:,} shares")
            lines.append(f"  ADV Status:      {adv_emoji} {adv_status} ({adv_pct:.0f}% of 500K minimum)")
            
            # Spread
            spread_available = exec_data.get('spread_available', False)
            if spread_available:
                bid = exec_data.get('bid', 0)
                ask = exec_data.get('ask', 0)
                spread_pct = exec_data.get('spread_pct', 0)
                spread_status = exec_data.get('spread_status', 'N/A')
                spread_emoji = "✅" if spread_status == 'TIGHT' else "⚠️" if spread_status == 'NORMAL' else "❌"
                lines.append(f"")
                lines.append(f"  Spread:          ${ask - bid:.2f} (${bid:.2f} / ${ask:.2f})")
                lines.append(f"  Spread %:        {spread_pct:.2f}%")
                lines.append(f"  Spread Rating:   {spread_emoji} {spread_status}")
            else:
                lines.append(f"")
                lines.append(f"  Spread:          N/A (no real-time data)")
            
            # Position sizing
            pos_size = exec_data.get('position_dollars', 0)
            allocation_pct = exec_data.get('allocation_pct', 0)
            shares_needed = exec_data.get('shares_needed', 0)
            pct_of_adv = exec_data.get('pct_of_adv', 0)
            lines.append(f"")
            lines.append(f"  Position Size:   ${pos_size:,.0f} ({allocation_pct*100:.0f}% allocation @ {grade} grade)")
            lines.append(f"  Shares Needed:   {shares_needed:,} shares")
            
            # % of ADV
            impact_emoji = "✅" if pct_of_adv <= 1.0 else "⚠️" if pct_of_adv <= 2.0 else "❌"
            impact_desc = "OK" if pct_of_adv <= 1.0 else "elevated" if pct_of_adv <= 2.0 else "EXCESSIVE"
            lines.append(f"  % of ADV:        {impact_emoji} {pct_of_adv:.1f}% ({impact_desc}, want <2%)")
            
            # Overall risk
            exec_risk = exec_data.get('overall_risk', 'N/A')
            risk_emoji = {"LOW": "✅", "MODERATE": "⚠️", "HIGH": "🔶", "DO_NOT_TRADE": "⛔"}.get(exec_risk, "")
            recommendation = exec_data.get('recommendation', '')
            lines.append(f"")
            lines.append(f"{risk_emoji} EXECUTION RISK: {exec_risk}")
            if recommendation:
                lines.append(f"   Recommendation: {recommendation}")
            
            lines.append("════════════════════════════════════════════════════════════")
        
        # SUPPLEMENTAL DATA (EPS/A/D for ML training)
        if supplemental_components:
            lines.append("")
            lines.append("--- SUPPLEMENTAL DATA (for ML training) ---")
            for comp in supplemental_components:
                lines.append(f"  {comp['name']:<12} {comp['reason']}")
            lines.append("  (Not included in base score - used for future ML analysis)")
            lines.append("════════════════════════════════════════════════════════════")
        
        return '\n'.join(lines)
    
    def reload_config(self):
        """Reload configuration from file (for hot-reloading in GUI)."""
        self.config = self._load_config()
        self._build_pattern_lookup()
        self._build_grade_thresholds()


def calculate_entry_score(position_data: Dict[str, Any], market_regime: str = 'BULLISH') -> Tuple[int, str, str]:
    """
    Convenience function to calculate entry score.
    
    Returns:
        Tuple of (score, grade, details_json)
    """
    scorer = CANSLIMScorer()
    score, grade, details = scorer.calculate_score(position_data, market_regime)
    return score, grade, json.dumps(details)
