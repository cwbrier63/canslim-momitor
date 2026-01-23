"""
CANSLIM Monitor - Level Calculator
===================================
Calculates price levels for position management:
- Stop loss levels (hard stop, warning stop, trailing stop)
- Profit targets (TP1, TP2)
- Pyramid zones (PY1, PY2)

Matches TrendSpider V3.6 logic with stage-adjusted stops.

Version: 1.0
Created: January 17, 2026
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger('canslim.levels')


@dataclass
class PositionLevels:
    """Calculated price levels for a position."""
    # Stop levels
    hard_stop: float
    warning_stop: float
    
    # Profit targets
    tp1: float
    tp2: float
    
    # Pyramid zones
    py1_min: float
    py1_max: float
    py2_min: float
    py2_max: float
    
    # Trailing stop (None if not activated)
    trailing_stop: Optional[float] = None
    
    def is_in_py1_zone(self, price: float) -> bool:
        """Check if price is in pyramid 1 zone."""
        return self.py1_min <= price <= self.py1_max
    
    def is_in_py2_zone(self, price: float) -> bool:
        """Check if price is in pyramid 2 zone."""
        return self.py2_min <= price <= self.py2_max
    
    def is_extended(self, price: float) -> bool:
        """Check if price is extended beyond PY2."""
        return price > self.py2_max
    
    def get_distance_to_stop(self, current_price: float) -> float:
        """Get percentage distance to hard stop."""
        if current_price <= 0:
            return 0.0
        return ((current_price - self.hard_stop) / current_price) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'hard_stop': self.hard_stop,
            'warning_stop': self.warning_stop,
            'trailing_stop': self.trailing_stop,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'py1_min': self.py1_min,
            'py1_max': self.py1_max,
            'py2_min': self.py2_min,
            'py2_max': self.py2_max,
        }


class LevelCalculator:
    """
    Calculate price levels for position management.
    
    Follows IBD methodology with stage-adjusted stops:
    - Stage 1: Full 7% stop
    - Stage 2: ~6% stop (0.85x)
    - Stage 3: ~5% stop (0.70x)
    - Stage 4: ~4.2% stop (0.60x)
    - Stage 5: ~3.5% stop (0.50x)
    
    Usage:
        calc = LevelCalculator()
        levels = calc.calculate_levels(position)
        
        if current_price <= levels.hard_stop:
            # Trigger stop alert
    """
    
    # Default stage multipliers
    DEFAULT_STAGE_MULTIPLIERS = {
        1: 1.00,
        2: 0.85,
        3: 0.70,
        4: 0.60,
        5: 0.50,
    }
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize level calculator.
        
        Args:
            config: Configuration dict (position_monitoring section)
                    If None, uses defaults
        """
        config = config or {}
        
        # Stop loss settings
        stop_config = config.get('stop_loss', {})
        self.base_stop_pct = stop_config.get('base_pct', 7.0)
        self.warning_buffer_pct = stop_config.get('warning_buffer_pct', 2.0)
        self.stage_multipliers = stop_config.get(
            'stage_multipliers', 
            self.DEFAULT_STAGE_MULTIPLIERS
        )
        
        # Trailing stop settings
        trailing_config = config.get('trailing_stop', {})
        self.trailing_activation_pct = trailing_config.get('activation_pct', 15.0)
        self.trailing_trail_pct = trailing_config.get('trail_pct', 8.0)
        
        # Profit target settings (defaults)
        self.default_tp1_pct = 20.0
        self.default_tp2_pct = 25.0
        
        # Pyramid zone settings
        pyramid_config = config.get('pyramid', {})
        self.py1_min_pct = pyramid_config.get('py1_min_pct', 0.0)
        self.py1_max_pct = pyramid_config.get('py1_max_pct', 5.0)
        self.py2_min_pct = pyramid_config.get('py2_min_pct', 5.0)
        self.py2_max_pct = pyramid_config.get('py2_max_pct', 10.0)
    
    def calculate_levels(
        self,
        entry_price: float,
        base_stage: int = 1,
        tp1_pct: float = None,
        tp2_pct: float = None,
        hard_stop_pct: float = None,
    ) -> PositionLevels:
        """
        Calculate all price levels for a position.
        
        Args:
            entry_price: Average entry price
            base_stage: Base stage (1-5, higher = tighter stop)
            tp1_pct: Override TP1 percentage
            tp2_pct: Override TP2 percentage
            hard_stop_pct: Override hard stop percentage
            
        Returns:
            PositionLevels with all calculated levels
        """
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")
        
        # Get stage multiplier (default to 1.0 for unknown stages)
        stage_mult = self.stage_multipliers.get(base_stage, 1.0)
        
        # Calculate adjusted stop percentage
        stop_pct = (hard_stop_pct or self.base_stop_pct) * stage_mult
        
        # Calculate stops
        hard_stop = entry_price * (1 - stop_pct / 100)
        warning_stop = entry_price * (1 - (stop_pct - self.warning_buffer_pct) / 100)
        
        # Calculate profit targets
        tp1 = entry_price * (1 + (tp1_pct or self.default_tp1_pct) / 100)
        tp2 = entry_price * (1 + (tp2_pct or self.default_tp2_pct) / 100)
        
        # Calculate pyramid zones
        py1_min = entry_price * (1 + self.py1_min_pct / 100)
        py1_max = entry_price * (1 + self.py1_max_pct / 100)
        py2_min = entry_price * (1 + self.py2_min_pct / 100)
        py2_max = entry_price * (1 + self.py2_max_pct / 100)
        
        return PositionLevels(
            hard_stop=round(hard_stop, 2),
            warning_stop=round(warning_stop, 2),
            tp1=round(tp1, 2),
            tp2=round(tp2, 2),
            py1_min=round(py1_min, 2),
            py1_max=round(py1_max, 2),
            py2_min=round(py2_min, 2),
            py2_max=round(py2_max, 2),
        )
    
    def calculate_trailing_stop(
        self,
        entry_price: float,
        max_price: float,
        current_gain_pct: float,
    ) -> Optional[float]:
        """
        Calculate trailing stop if activated.
        
        Trailing stop activates at trailing_activation_pct (default 15%)
        and trails by trailing_trail_pct (default 8%) from high.
        
        Args:
            entry_price: Average entry price
            max_price: Maximum price reached since entry
            current_gain_pct: Current gain percentage
            
        Returns:
            Trailing stop price if activated, None otherwise
        """
        # Check if trailing stop should be activated
        if current_gain_pct < self.trailing_activation_pct:
            return None
        
        # Calculate trailing stop from max price
        trailing_stop = max_price * (1 - self.trailing_trail_pct / 100)
        
        # Ensure trailing stop is above entry (never lock in a loss)
        if trailing_stop < entry_price:
            return entry_price
        
        return round(trailing_stop, 2)
    
    def get_dynamic_stop(
        self,
        entry_price: float,
        base_stage: int,
        max_price: float,
        current_gain_pct: float,
        hard_stop_pct: float = None,
    ) -> float:
        """
        Get the active stop price (higher of hard stop or trailing stop).
        
        Args:
            entry_price: Average entry price
            base_stage: Base stage for stop calculation
            max_price: Maximum price reached
            current_gain_pct: Current gain percentage
            hard_stop_pct: Override hard stop percentage
            
        Returns:
            Active stop price
        """
        levels = self.calculate_levels(entry_price, base_stage, hard_stop_pct=hard_stop_pct)
        trailing = self.calculate_trailing_stop(entry_price, max_price, current_gain_pct)
        
        if trailing is not None:
            return max(levels.hard_stop, trailing)
        
        return levels.hard_stop
    
    def get_pyramid_status(
        self,
        entry_price: float,
        current_price: float,
        state: int,
        py1_done: bool = False,
        py2_done: bool = False,
    ) -> Dict[str, Any]:
        """
        Get pyramid status for a position.
        
        Args:
            entry_price: Average entry price
            current_price: Current price
            state: Position state (1-3)
            py1_done: Whether PY1 has been executed
            py2_done: Whether PY2 has been executed
            
        Returns:
            Dict with pyramid status info
        """
        if entry_price <= 0:
            return {'py1_ready': False, 'py2_ready': False, 'extended': False}
        
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Check PY1 zone (state 1, 0-5%)
        py1_ready = (
            state == 1 and
            not py1_done and
            self.py1_min_pct <= pnl_pct <= self.py1_max_pct
        )
        
        # Check PY1 extended
        py1_extended = (
            state == 1 and
            not py1_done and
            pnl_pct > self.py1_max_pct
        )
        
        # Check PY2 zone (state 2, 5-10%)
        py2_ready = (
            state == 2 and
            not py2_done and
            self.py2_min_pct <= pnl_pct <= self.py2_max_pct
        )
        
        # Check PY2 extended
        py2_extended = (
            state == 2 and
            not py2_done and
            pnl_pct > self.py2_max_pct
        )
        
        return {
            'pnl_pct': pnl_pct,
            'py1_ready': py1_ready,
            'py1_extended': py1_extended,
            'py2_ready': py2_ready,
            'py2_extended': py2_extended,
            'extended': pnl_pct > self.py2_max_pct,
        }
    
    def get_profit_status(
        self,
        entry_price: float,
        current_price: float,
        tp1_pct: float = None,
        tp2_pct: float = None,
    ) -> Dict[str, Any]:
        """
        Get profit target status for a position.
        
        Args:
            entry_price: Average entry price
            current_price: Current price
            tp1_pct: Override TP1 percentage
            tp2_pct: Override TP2 percentage
            
        Returns:
            Dict with profit status info
        """
        if entry_price <= 0:
            return {'tp1_hit': False, 'tp2_hit': False}
        
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        tp1_target = tp1_pct or self.default_tp1_pct
        tp2_target = tp2_pct or self.default_tp2_pct
        
        return {
            'pnl_pct': pnl_pct,
            'tp1_hit': pnl_pct >= tp1_target,
            'tp2_hit': pnl_pct >= tp2_target,
            'tp1_distance': tp1_target - pnl_pct,
            'tp2_distance': tp2_target - pnl_pct,
        }


def calculate_position_levels(
    entry_price: float,
    base_stage: int = 1,
    **kwargs
) -> PositionLevels:
    """
    Convenience function to calculate levels.
    
    Args:
        entry_price: Average entry price
        base_stage: Base stage (1-5)
        **kwargs: Additional args passed to LevelCalculator.calculate_levels
        
    Returns:
        PositionLevels
    """
    calc = LevelCalculator()
    return calc.calculate_levels(entry_price, base_stage, **kwargs)
