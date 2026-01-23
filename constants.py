"""
CANSLIM Monitor - Shared Constants

Contains canonical pattern definitions and other shared constants
used across the GUI, scoring engine, and alert systems.

Based on IBD/MarketSurge official pattern documentation.
"""

from typing import Dict, List, Tuple

# =============================================================================
# CANONICAL PATTERN DEFINITIONS
# =============================================================================
# Official IBD/MarketSurge patterns with scoring tiers
#
# Pattern Format: (display_name, score, tier)
# - display_name: Canonical name for display in UI
# - score: Points awarded for this pattern
# - tier: Quality tier (A=best, B=good, C=acceptable)

CANONICAL_PATTERNS: List[Tuple[str, int, str]] = [
    # Primary Patterns - Tier A (highest quality)
    ("Cup w/Handle", 10, "A"),      # Most reliable pattern
    ("Double Bottom", 9, "A"),       # W-shaped pattern
    
    # Good Patterns - Tier B
    ("Flat Base", 8, "B"),           # ≤15% correction, 5+ weeks
    ("High Tight Flag", 8, "B"),     # Rarest, most powerful
    ("Cup", 7, "B"),                 # Cup without Handle
    ("Ascending Base", 7, "B"),      # 3 progressively higher lows
    ("IPO Base", 7, "B"),            # First base after IPO
    
    # Acceptable Patterns - Tier C
    ("Consolidation", 6, "C"),       # General sideways action
    ("Saucer", 6, "C"),              # Shallow cup variant
    ("Saucer w/Handle", 6, "C"),     # Saucer with handle
    
    # Alternative Entry Patterns - Tier C
    ("3 Weeks Tight", 6, "C"),       # Add-on/secondary entry
    ("Shakeout +3", 6, "C"),         # Aggressive early entry
]

# Default score for unrecognized patterns
PATTERN_DEFAULT_SCORE = 5

# =============================================================================
# PATTERN ALIASES
# =============================================================================
# Maps various input formats to canonical pattern names
# All keys should be lowercase for case-insensitive matching

PATTERN_ALIASES: Dict[str, str] = {
    # Cup with Handle variants
    "cup with handle": "Cup w/Handle",
    "cup w/ handle": "Cup w/Handle",
    "cup w/handle": "Cup w/Handle",
    "cup & handle": "Cup w/Handle",
    "cup and handle": "Cup w/Handle",
    "cupwhandle": "Cup w/Handle",
    
    # Cup without Handle variants
    "cup": "Cup",
    "cup no handle": "Cup",
    "cup without handle": "Cup",
    "cup w/o handle": "Cup",
    
    # Double Bottom variants
    "double bottom": "Double Bottom",
    "double-bottom": "Double Bottom",
    "w bottom": "Double Bottom",
    "w-bottom": "Double Bottom",
    
    # Flat Base variants
    "flat base": "Flat Base",
    "flat-base": "Flat Base",
    "flatbase": "Flat Base",
    
    # High Tight Flag variants
    "high tight flag": "High Tight Flag",
    "high-tight-flag": "High Tight Flag",
    "htf": "High Tight Flag",
    
    # Ascending Base variants
    "ascending base": "Ascending Base",
    "ascending-base": "Ascending Base",
    
    # IPO Base variants
    "ipo base": "IPO Base",
    "ipo-base": "IPO Base",
    "ipobase": "IPO Base",
    
    # Consolidation variants
    "consolidation": "Consolidation",
    "consol": "Consolidation",
    "base on base": "Consolidation",  # Use stage notation for BoB bonus
    "base-on-base": "Consolidation",
    
    # Saucer variants
    "saucer": "Saucer",
    "saucer base": "Saucer",
    "saucer-base": "Saucer",
    
    # Saucer with Handle variants
    "saucer w/handle": "Saucer w/Handle",
    "saucer with handle": "Saucer w/Handle",
    "saucer w/ handle": "Saucer w/Handle",
    
    # 3 Weeks Tight variants
    "3 weeks tight": "3 Weeks Tight",
    "three weeks tight": "3 Weeks Tight",
    "3-weeks tight": "3 Weeks Tight",
    "3-weeks-tight": "3 Weeks Tight",
    "3wt": "3 Weeks Tight",
    
    # Shakeout +3 variants
    "shakeout +3": "Shakeout +3",
    "shakeout+3": "Shakeout +3",
    "shakeout plus 3": "Shakeout +3",
    "shakeout plus three": "Shakeout +3",
    "shake out +3": "Shakeout +3",
}

# =============================================================================
# GUI DROPDOWN LIST
# =============================================================================
# Ordered list of canonical pattern names for dropdown menus
# This is what users will see in the UI

VALID_PATTERNS: List[str] = [pattern[0] for pattern in CANONICAL_PATTERNS]

# =============================================================================
# PATTERN SCORING LOOKUP
# =============================================================================
# Quick lookup from canonical name to (score, tier)

PATTERN_SCORES: Dict[str, Tuple[int, str]] = {
    pattern[0]: (pattern[1], pattern[2]) for pattern in CANONICAL_PATTERNS
}


def get_pattern_score(pattern_name: str) -> Tuple[int, str, str]:
    """
    Get the score for a pattern name.
    
    Args:
        pattern_name: The pattern name (can be any variant/alias)
        
    Returns:
        Tuple of (score, tier, canonical_name)
        Returns (PATTERN_DEFAULT_SCORE, "", pattern_name) if unrecognized
    """
    if not pattern_name:
        return PATTERN_DEFAULT_SCORE, "", "Unknown"
    
    # Normalize input
    pattern_lower = pattern_name.lower().strip()
    
    # Try direct alias lookup
    if pattern_lower in PATTERN_ALIASES:
        canonical = PATTERN_ALIASES[pattern_lower]
        score, tier = PATTERN_SCORES[canonical]
        return score, tier, canonical
    
    # Try matching against canonical names (case-insensitive)
    for canonical, (score, tier) in PATTERN_SCORES.items():
        if canonical.lower() == pattern_lower:
            return score, tier, canonical
    
    # Try partial matching
    for alias, canonical in PATTERN_ALIASES.items():
        if alias in pattern_lower or pattern_lower in alias:
            score, tier = PATTERN_SCORES[canonical]
            return score, tier, canonical
    
    # Unrecognized pattern
    return PATTERN_DEFAULT_SCORE, "", pattern_name


# =============================================================================
# BASE STAGE DEFINITIONS
# =============================================================================
# Valid base stage formats for dropdown menus

BASE_STAGES: List[str] = [
    '1', '1(1)', 
    '2', '2(2)', '2(3)', '2b', 
    '3', '3(3)', '3(4)', '3b', 
    '4', '4+', 'Late'
]

# =============================================================================
# A/D RATING GRADES
# =============================================================================
# School-style grades for Accumulation/Distribution rating

AD_RATINGS: List[str] = [
    'A+', 'A', 'A-', 
    'B+', 'B', 'B-', 
    'C+', 'C', 'C-', 
    'D+', 'D', 'D-', 
    'E'
]

# =============================================================================
# SMR RATING GRADES (NEW - MarketSurge v2)
# =============================================================================
# Sales/Margin/ROE composite rating

SMR_RATINGS: List[str] = ['A', 'B', 'C', 'D', 'E']

# =============================================================================
# MARKET EXPOSURE LEVELS (NEW - MarketSurge v2)
# =============================================================================
# IBD recommended market exposure levels

MARKET_EXPOSURE_LEVELS: List[str] = [
    '0%-20%',
    '20%-40%', 
    '40%-60%',
    '60%-80%',
    '80%-100%'
]

# =============================================================================
# GRADE BOUNDARIES
# =============================================================================
# Score thresholds for final grades (score >= threshold)

GRADE_BOUNDARIES: Dict[str, int] = {
    "A+": 20,
    "A": 15,
    "B+": 12,
    "B": 9,
    "C+": 7,
    "C": 5,
    "D": 3,
    "F": -999,  # Catch-all
}


def score_to_grade(score: int) -> str:
    """Convert numeric score to letter grade."""
    for grade, threshold in sorted(GRADE_BOUNDARIES.items(), 
                                   key=lambda x: x[1], reverse=True):
        if score >= threshold:
            return grade
    return "F"
