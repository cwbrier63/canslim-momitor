"""
CANSLIM Monitor - Position State Definitions
Configuration for position state management and transitions.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from enum import IntEnum


class PositionState(IntEnum):
    """Position state values matching spreadsheet."""
    STOPPED_OUT = -2
    CLOSED = -1
    WATCHING = 0
    ENTRY_1 = 1
    ENTRY_2 = 2
    FULL_POSITION = 3
    TP1_HIT = 4
    TP2_HIT = 5
    TRAILING = 6


@dataclass
class StateInfo:
    """Information about a position state."""
    value: int
    name: str
    display_name: str
    description: str
    color: str  # Hex color for UI
    next_action: str
    column_order: int  # Order in Kanban board


# State definitions
STATES: Dict[int, StateInfo] = {
    PositionState.STOPPED_OUT: StateInfo(
        value=-2,
        name='STOPPED_OUT',
        display_name='Stopped Out',
        description='Position closed at stop loss',
        color='#DC3545',  # Red
        next_action='Review and learn',
        column_order=8
    ),
    PositionState.CLOSED: StateInfo(
        value=-1,
        name='CLOSED',
        display_name='Closed',
        description='Position manually closed',
        color='#6C757D',  # Gray
        next_action='Archive',
        column_order=7
    ),
    PositionState.WATCHING: StateInfo(
        value=0,
        name='WATCHING',
        display_name='Watching',
        description='On watchlist, awaiting breakout',
        color='#17A2B8',  # Cyan/Info
        next_action='Wait for breakout signal',
        column_order=0
    ),
    PositionState.ENTRY_1: StateInfo(
        value=1,
        name='ENTRY_1',
        display_name='Entry 1',
        description='Initial position taken',
        color='#28A745',  # Green
        next_action='Watch for pyramid opportunity',
        column_order=1
    ),
    PositionState.ENTRY_2: StateInfo(
        value=2,
        name='ENTRY_2',
        display_name='Entry 2',
        description='First pyramid added',
        color='#20C997',  # Teal
        next_action='Watch for second pyramid',
        column_order=2
    ),
    PositionState.FULL_POSITION: StateInfo(
        value=3,
        name='FULL_POSITION',
        display_name='Full Position',
        description='Full position established (3 entries)',
        color='#198754',  # Dark green
        next_action='Hold and manage',
        column_order=3
    ),
    PositionState.TP1_HIT: StateInfo(
        value=4,
        name='TP1_HIT',
        display_name='TP1 Hit',
        description='First profit target reached',
        color='#FFC107',  # Yellow
        next_action='Trail stop on remainder',
        column_order=4
    ),
    PositionState.TP2_HIT: StateInfo(
        value=5,
        name='TP2_HIT',
        display_name='TP2 Hit',
        description='Second profit target reached',
        color='#FD7E14',  # Orange
        next_action='Consider closing',
        column_order=5
    ),
    PositionState.TRAILING: StateInfo(
        value=6,
        name='TRAILING',
        display_name='Trailing',
        description='Trailing stop active',
        color='#6F42C1',  # Purple
        next_action='Let winners run',
        column_order=6
    ),
}


# Valid state transitions and required fields
@dataclass
class StateTransition:
    """Defines a valid state transition."""
    from_state: int
    to_state: int
    required_fields: List[str]
    optional_fields: List[str]
    description: str


# All valid transitions
VALID_TRANSITIONS: List[StateTransition] = [
    # Forward progression
    StateTransition(
        from_state=0, to_state=1,
        required_fields=['e1_shares', 'e1_price', 'stop_price'],
        optional_fields=['entry_date', 'breakout_date'],
        description='Initial buy'
    ),
    StateTransition(
        from_state=1, to_state=2,
        required_fields=['e2_shares', 'e2_price'],
        optional_fields=[],
        description='First pyramid'
    ),
    StateTransition(
        from_state=2, to_state=3,
        required_fields=['e3_shares', 'e3_price'],
        optional_fields=[],
        description='Second pyramid (full position)'
    ),
    StateTransition(
        from_state=3, to_state=4,
        required_fields=['tp1_sold', 'tp1_price'],
        optional_fields=['tp1_date'],
        description='First profit take'
    ),
    StateTransition(
        from_state=4, to_state=5,
        required_fields=['tp2_sold', 'tp2_price'],
        optional_fields=['tp2_date'],
        description='Second profit take'
    ),
    StateTransition(
        from_state=5, to_state=6,
        required_fields=[],
        optional_fields=[],
        description='Move to trailing stop'
    ),
    
    # Skip transitions (jump states)
    StateTransition(
        from_state=1, to_state=3,
        required_fields=['e2_shares', 'e2_price', 'e3_shares', 'e3_price'],
        optional_fields=[],
        description='Quick fill to full position'
    ),
    StateTransition(
        from_state=1, to_state=4,
        required_fields=['tp1_sold', 'tp1_price'],
        optional_fields=[],
        description='Skip pyramids, take first profit'
    ),
    StateTransition(
        from_state=2, to_state=4,
        required_fields=['tp1_sold', 'tp1_price'],
        optional_fields=['tp1_date'],
        description='Take first profit from Entry 2'
    ),
    StateTransition(
        from_state=2, to_state=5,
        required_fields=['tp1_sold', 'tp1_price', 'tp2_sold', 'tp2_price'],
        optional_fields=['tp1_date', 'tp2_date'],
        description='Take both profits from Entry 2'
    ),
    StateTransition(
        from_state=3, to_state=5,
        required_fields=['tp1_sold', 'tp1_price', 'tp2_sold', 'tp2_price'],
        optional_fields=['tp1_date', 'tp2_date'],
        description='Take both profits from Full Position'
    ),
    StateTransition(
        from_state=2, to_state=6,
        required_fields=[],
        optional_fields=[],
        description='Move to trailing from Entry 2'
    ),
    StateTransition(
        from_state=3, to_state=6,
        required_fields=[],
        optional_fields=[],
        description='Move to trailing from Full Position'
    ),
    StateTransition(
        from_state=4, to_state=6,
        required_fields=[],
        optional_fields=[],
        description='Move to trailing from TP1'
    ),
    
    # Close/Stop from any active state
    StateTransition(
        from_state=1, to_state=-1,
        required_fields=['exit_date', 'exit_price', 'exit_reason'],
        optional_fields=['trade_outcome', 'notes'],
        description='Manual close from Entry 1'
    ),
    StateTransition(
        from_state=2, to_state=-1,
        required_fields=['exit_date', 'exit_price', 'exit_reason'],
        optional_fields=['trade_outcome', 'notes'],
        description='Manual close from Entry 2'
    ),
    StateTransition(
        from_state=3, to_state=-1,
        required_fields=['exit_date', 'exit_price', 'exit_reason'],
        optional_fields=['trade_outcome', 'notes'],
        description='Manual close from Full Position'
    ),
    StateTransition(
        from_state=4, to_state=-1,
        required_fields=['exit_date', 'exit_price', 'exit_reason'],
        optional_fields=['trade_outcome', 'notes'],
        description='Manual close from TP1'
    ),
    StateTransition(
        from_state=5, to_state=-1,
        required_fields=['exit_date', 'exit_price', 'exit_reason'],
        optional_fields=['trade_outcome', 'notes'],
        description='Close from TP2'
    ),
    StateTransition(
        from_state=6, to_state=-1,
        required_fields=['exit_date', 'exit_price', 'exit_reason'],
        optional_fields=['trade_outcome', 'notes'],
        description='Close from trailing'
    ),
    
    # Stop out from any active state
    StateTransition(
        from_state=1, to_state=-2,
        required_fields=['exit_date', 'exit_price'],
        optional_fields=['notes'],
        description='Stopped out from Entry 1'
    ),
    StateTransition(
        from_state=2, to_state=-2,
        required_fields=['exit_date', 'exit_price'],
        optional_fields=['notes'],
        description='Stopped out from Entry 2'
    ),
    StateTransition(
        from_state=3, to_state=-2,
        required_fields=['exit_date', 'exit_price'],
        optional_fields=['notes'],
        description='Stopped out from Full Position'
    ),
    StateTransition(
        from_state=4, to_state=-2,
        required_fields=['exit_date', 'exit_price'],
        optional_fields=['notes'],
        description='Stopped out from TP1'
    ),
    StateTransition(
        from_state=5, to_state=-2,
        required_fields=[],
        optional_fields=['notes'],
        description='Stopped out from TP2'
    ),
    StateTransition(
        from_state=6, to_state=-2,
        required_fields=[],
        optional_fields=['notes'],
        description='Stopped out from trailing'
    ),
    
    # Remove from watchlist
    StateTransition(
        from_state=0, to_state=-1,
        required_fields=[],
        optional_fields=['notes'],
        description='Remove from watchlist'
    ),
]


def get_valid_transitions(from_state: int) -> List[StateTransition]:
    """Get all valid transitions from a given state."""
    return [t for t in VALID_TRANSITIONS if t.from_state == from_state]


def get_transition(from_state: int, to_state: int) -> Optional[StateTransition]:
    """Get transition definition for a state change."""
    for t in VALID_TRANSITIONS:
        if t.from_state == from_state and t.to_state == to_state:
            return t
    return None


def is_valid_transition(from_state: int, to_state: int) -> bool:
    """Check if a state transition is allowed."""
    return get_transition(from_state, to_state) is not None


def get_kanban_columns() -> List[Tuple[int, str, str]]:
    """Get Kanban columns in display order: (state, name, color)."""
    columns = []
    for state_info in sorted(STATES.values(), key=lambda s: s.column_order):
        # Skip closed states from main Kanban (show in separate area)
        if state_info.value < 0:
            continue
        columns.append((state_info.value, state_info.display_name, state_info.color))
    return columns

# =============================================================================
# Import shared constants for patterns, stages, ratings
# =============================================================================
try:
    from ..constants import (
        VALID_PATTERNS,
        AD_RATINGS,
        BASE_STAGES,
        SMR_RATINGS,
        MARKET_EXPOSURE_LEVELS,
    )
except ImportError:
    # Fallback if constants module not available
    VALID_PATTERNS = [
        'Cup w/Handle',
        'Cup',
        'Flat Base',
        'Double Bottom',
        'High Tight Flag',
        'Ascending Base',
        'IPO Base',
        'Consolidation',
        'Saucer',
        'Saucer w/Handle',
        '3 Weeks Tight',
        'Shakeout +3',
    ]
    
    AD_RATINGS = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'E']
    
    SMR_RATINGS = ['A', 'B', 'C', 'D', 'E']
    
    MARKET_EXPOSURE_LEVELS = ['0%-20%', '20%-40%', '40%-60%', '60%-80%', '80%-100%']
    
    BASE_STAGES = [
        '1', '1(1)', 
        '2', '2(2)', '2(3)', '2b', 
        '3', '3(3)', '3(4)', '3b', 
        '4', '4+', 'Late'
    ]

# Exit reasons for closing positions
EXIT_REASONS = [
    'TP1_HIT',           # First profit target hit
    'TP2_HIT',           # Second profit target hit
    'TRAILING_STOP',     # Trailing stop triggered
    'MANUAL_CLOSE',      # Closed manually
    'STOP_HIT',          # Hard stop hit
    '50MA_BREAKDOWN',    # Closed below 50-day MA
    '10WMA_BREAKDOWN',   # Closed below 10-week MA
    'EARNINGS_EXIT',     # Exited before/after earnings
    'MARKET_CORRECTION', # Closed due to market correction
    'SECTOR_ROTATION',   # Sector falling out of favor
    'RS_DETERIORATION',  # Relative strength declining
    'VOLUME_DRY_UP',     # Volume declining significantly
    'OTHER'              # Other reason (see notes)
]

# Trade outcome classifications for learning
TRADE_OUTCOMES = [
    'SUCCESS',   # Met profit target (20%+ gain)
    'PARTIAL',   # Partial success (5-20% gain)
    'BREAKEVEN', # Near breakeven (-2% to +5%)
    'FAILED',    # Loss but not stopped (-2% to -7%)
    'STOPPED'    # Hit stop loss (-7% or worse)
]
