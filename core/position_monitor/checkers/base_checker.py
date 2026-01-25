"""
Base Checker - Abstract interface for position alert checkers.

All checkers inherit from this class and implement the check() method.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import (
    AlertType, AlertSubtype, AlertContext, AlertData
)


@dataclass
class PositionContext:
    """
    Read-only snapshot of position state for alert checking.
    Built from Position model + real-time price data.
    """
    # Identity
    symbol: str
    position_id: int
    
    # Price data
    current_price: float
    entry_price: float  # avg_cost
    pivot_price: float
    
    # Position info
    shares: int
    state: int
    
    # P&L
    pnl_pct: float
    pnl_dollars: float = 0.0
    
    # Max tracking
    max_price: float = 0.0
    max_gain_pct: float = 0.0
    
    # Technical data
    ma_21: Optional[float] = None
    ma_50: Optional[float] = None
    ma_200: Optional[float] = None
    ma_10_week: Optional[float] = None
    volume_ratio: float = 1.0
    
    # MarketSurge data
    rs_rating: Optional[int] = None
    ad_rating: Optional[str] = None
    
    # Position data
    base_stage: int = 1
    days_in_position: int = 0
    days_since_breakout: int = 0
    
    # 8-week hold
    eight_week_hold_active: bool = False
    eight_week_hold_end_date: Optional[datetime] = None
    
    # Pyramid flags
    py1_done: bool = False
    py2_done: bool = False
    
    # TP flags
    tp1_sold: int = 0
    tp2_sold: int = 0
    
    # Earnings
    days_to_earnings: Optional[int] = None
    
    # Health
    health_score: int = 100
    health_rating: str = "HEALTHY"

    # CANSLIM scoring
    canslim_grade: str = ""
    canslim_score: int = 0

    # Market context
    market_regime: str = ""
    spy_price: float = 0.0

    # Stop levels
    hard_stop: float = 0.0
    trailing_stop: Optional[float] = None
    
    # Intraday data (for climax top detection)
    day_open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    prev_close: Optional[float] = None
    
    @classmethod
    def from_position(
        cls,
        position: Position,
        current_price: float,
        technical_data: Dict[str, Any] = None,
        market_regime: str = "",
        spy_price: float = 0.0,
    ) -> 'PositionContext':
        """
        Build context from Position model and real-time data.

        Args:
            position: Position ORM model
            current_price: Real-time price
            technical_data: Dict with ma_21, ma_50, ma_200, volume_ratio
            market_regime: Current market regime (BULLISH/NEUTRAL/BEARISH/CORRECTION)
            spy_price: Current SPY price
        """
        technical_data = technical_data or {}
        
        entry_price = position.avg_cost or position.pivot or current_price
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        pnl_dollars = (current_price - entry_price) * (position.total_shares or 0)
        
        # Parse base stage from string like "2b(3)"
        base_stage = 1
        if position.base_stage:
            try:
                # Extract first digit
                stage_str = str(position.base_stage)[0]
                if stage_str.isdigit():
                    base_stage = int(stage_str)
            except:
                pass
        
        # Calculate days in position
        days_in_position = 0
        if position.entry_date:
            days_in_position = (datetime.now().date() - position.entry_date).days
        
        days_since_breakout = 0
        if position.breakout_date:
            days_since_breakout = (datetime.now().date() - position.breakout_date).days
        
        # Days to earnings
        days_to_earnings = None
        if position.earnings_date:
            delta = (position.earnings_date - datetime.now().date()).days
            if delta >= 0:
                days_to_earnings = delta
        
        return cls(
            symbol=position.symbol,
            position_id=position.id,
            current_price=current_price,
            entry_price=entry_price,
            pivot_price=position.pivot or entry_price,
            shares=position.total_shares or 0,
            state=position.state or 0,
            pnl_pct=pnl_pct,
            pnl_dollars=pnl_dollars,
            max_price=technical_data.get('max_price', current_price),
            max_gain_pct=technical_data.get('max_gain_pct', max(0, pnl_pct)),
            ma_21=technical_data.get('ma_21'),
            ma_50=technical_data.get('ma_50'),
            ma_200=technical_data.get('ma_200'),
            ma_10_week=technical_data.get('ma_10_week'),
            volume_ratio=technical_data.get('volume_ratio', 1.0),
            rs_rating=position.rs_rating,
            ad_rating=position.ad_rating,
            base_stage=base_stage,
            days_in_position=days_in_position,
            days_since_breakout=days_since_breakout,
            eight_week_hold_active=False,  # TODO: Add to Position model
            py1_done=position.py1_done or False,
            py2_done=position.py2_done or False,
            tp1_sold=position.tp1_sold or 0,
            tp2_sold=position.tp2_sold or 0,
            days_to_earnings=days_to_earnings,
            health_score=position.health_score or 100,
            health_rating=position.health_rating or "HEALTHY",
            canslim_grade=position.entry_grade or "",
            canslim_score=position.entry_score or 0,
            market_regime=market_regime,
            spy_price=spy_price,
            hard_stop=position.stop_price or 0,
            trailing_stop=technical_data.get('trailing_stop'),
        )

    @classmethod
    def from_test_data(
        cls,
        symbol: str,
        current_price: float,
        entry_price: float,
        state: int = 1,
        shares: int = 100,
        base_stage: int = 1,
        days_in_position: int = 10,
        days_since_breakout: int = None,
        max_price: float = None,
        max_gain_pct: float = None,
        ma_21: float = None,
        ma_50: float = None,
        ma_200: float = None,
        ma_10_week: float = None,
        volume_ratio: float = 1.0,
        rs_rating: int = None,
        ad_rating: str = None,
        py1_done: bool = False,
        py2_done: bool = False,
        tp1_sold: int = 0,
        tp2_sold: int = 0,
        tp1_pct: float = None,
        tp2_pct: float = None,
        days_to_earnings: int = None,
        eight_week_hold_active: bool = False,
        eight_week_hold_end_date: datetime = None,
        health_score: int = 100,
        health_rating: str = "HEALTHY",
        canslim_grade: str = "",
        canslim_score: int = 0,
        pivot_price: float = None,
        hard_stop: float = None,
        trailing_stop: float = None,
        # Intraday data for climax top
        day_open: float = None,
        day_high: float = None,
        day_low: float = None,
        prev_close: float = None,
    ) -> 'PositionContext':
        """
        Create a PositionContext for testing purposes with sensible defaults.
        
        This allows tests to only specify the fields they need without
        building a full Position ORM object.
        """
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        pnl_dollars = (current_price - entry_price) * shares
        
        # Default max values to current if not specified
        if max_price is None:
            max_price = current_price
        if max_gain_pct is None:
            max_gain_pct = max(0, pnl_pct)
        if days_since_breakout is None:
            days_since_breakout = days_in_position
        if pivot_price is None:
            pivot_price = entry_price
        if hard_stop is None:
            # Default 7% stop
            hard_stop = entry_price * 0.93
        
        return cls(
            symbol=symbol,
            position_id=0,  # Test ID
            current_price=current_price,
            entry_price=entry_price,
            pivot_price=pivot_price,
            shares=shares,
            state=state,
            pnl_pct=pnl_pct,
            pnl_dollars=pnl_dollars,
            max_price=max_price,
            max_gain_pct=max_gain_pct,
            ma_21=ma_21,
            ma_50=ma_50,
            ma_200=ma_200,
            ma_10_week=ma_10_week,
            volume_ratio=volume_ratio,
            rs_rating=rs_rating,
            ad_rating=ad_rating,
            base_stage=base_stage,
            days_in_position=days_in_position,
            days_since_breakout=days_since_breakout,
            eight_week_hold_active=eight_week_hold_active,
            eight_week_hold_end_date=eight_week_hold_end_date,
            py1_done=py1_done,
            py2_done=py2_done,
            tp1_sold=tp1_sold,
            tp2_sold=tp2_sold,
            days_to_earnings=days_to_earnings,
            health_score=health_score,
            health_rating=health_rating,
            canslim_grade=canslim_grade,
            canslim_score=canslim_score,
            hard_stop=hard_stop,
            trailing_stop=trailing_stop,
            day_open=day_open,
            day_high=day_high,
            day_low=day_low,
            prev_close=prev_close,
        )


class BaseChecker(ABC):
    """
    Abstract base class for position alert checkers.
    
    Each checker is responsible for one category of alerts:
    - StopChecker: Hard stop, trailing stop, stop warnings
    - ProfitChecker: TP1, TP2, 8-week hold
    - PyramidChecker: PY1, PY2, pullback entries
    - MAChecker: 50 MA, 21 EMA, 10-week violations
    - HealthChecker: Health warnings, earnings, late stage
    """
    
    def __init__(
        self,
        config: Dict[str, Any] = None,
        logger: logging.Logger = None
    ):
        """
        Initialize checker.
        
        Args:
            config: Configuration dict (from user_config.yaml)
            logger: Logger instance
        """
        self.config = config or {}
        self.logger = logger or logging.getLogger(f'canslim.checker.{self.name}')
        
        # Cooldown tracking: {alert_key: last_alert_time}
        self._cooldowns: Dict[str, datetime] = {}
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Checker name for logging."""
        pass
    
    @abstractmethod
    def check(
        self,
        position: Position,
        context: PositionContext,
    ) -> List[AlertData]:
        """
        Check position for alerts.
        
        Args:
            position: Position ORM model
            context: PositionContext with real-time data
            
        Returns:
            List of AlertData objects (empty if no alerts)
        """
        pass
    
    def should_check(self, context: PositionContext) -> bool:
        """
        Pre-check filter. Override to skip inactive positions.
        
        Args:
            context: PositionContext
            
        Returns:
            True if this checker should run
        """
        return context.state >= 1  # Only active positions
    
    def is_on_cooldown(self, symbol: str, subtype: AlertSubtype) -> bool:
        """
        Check if alert is on cooldown.
        
        Args:
            symbol: Stock symbol
            subtype: Alert subtype
            
        Returns:
            True if on cooldown
        """
        key = f"{symbol}_{subtype.value}"
        
        if key not in self._cooldowns:
            return False
        
        last_alert = self._cooldowns[key]
        cooldown_minutes = self._get_cooldown_minutes(subtype)
        
        if cooldown_minutes == 0:
            return False
        
        cooldown_end = last_alert + timedelta(minutes=cooldown_minutes)
        return datetime.now() < cooldown_end
    
    def set_cooldown(self, symbol: str, subtype: AlertSubtype) -> None:
        """Set cooldown for an alert."""
        key = f"{symbol}_{subtype.value}"
        self._cooldowns[key] = datetime.now()
    
    def clear_cooldown(self, symbol: str, subtype: AlertSubtype = None) -> None:
        """Clear cooldown for symbol (all subtypes if subtype is None)."""
        if subtype:
            key = f"{symbol}_{subtype.value}"
            self._cooldowns.pop(key, None)
        else:
            keys_to_remove = [k for k in self._cooldowns if k.startswith(f"{symbol}_")]
            for key in keys_to_remove:
                del self._cooldowns[key]
    
    def _get_cooldown_minutes(self, subtype: AlertSubtype) -> int:
        """Get cooldown minutes for alert subtype from config."""
        cooldowns = self.config.get('cooldowns', {})
        
        # Map subtype to config key
        key_map = {
            AlertSubtype.HARD_STOP: 'hard_stop',
            AlertSubtype.WARNING: 'stop_warning',
            AlertSubtype.TRAILING_STOP: 'hard_stop',  # Same cooldown as hard stop
            AlertSubtype.TP1: 'tp1',
            AlertSubtype.TP2: 'tp2',
            AlertSubtype.EIGHT_WEEK_HOLD: 'eight_week_hold',
            AlertSubtype.P1_READY: 'pyramid',
            AlertSubtype.P1_EXTENDED: 'pyramid',
            AlertSubtype.P2_READY: 'pyramid',
            AlertSubtype.P2_EXTENDED: 'pyramid',
            AlertSubtype.PULLBACK: 'pyramid',
            AlertSubtype.MA_50_WARNING: 'ma_50_warning',
            AlertSubtype.MA_50_SELL: 'ma_50_sell',
            AlertSubtype.EMA_21_SELL: 'ema_21_sell',
            AlertSubtype.TEN_WEEK_SELL: 'ten_week_sell',
            AlertSubtype.CRITICAL: 'health_critical',
            AlertSubtype.EARNINGS: 'earnings',
            AlertSubtype.LATE_STAGE: 'late_stage',
        }
        
        config_key = key_map.get(subtype, 'default')
        return cooldowns.get(config_key, 60)  # Default 60 min
    
    def create_alert(
        self,
        context: PositionContext,
        alert_type: AlertType,
        subtype: AlertSubtype,
        message: str,
        action: str = "",
        priority: str = "P1",
    ) -> AlertData:
        """
        Create an AlertData object.
        
        Args:
            context: PositionContext
            alert_type: Alert category
            subtype: Alert subtype
            message: Alert message
            action: Recommended action
            priority: P0/P1/P2
            
        Returns:
            AlertData object
        """
        alert_context = AlertContext(
            current_price=context.current_price,
            pivot_price=context.pivot_price,
            avg_cost=context.entry_price,
            pnl_pct=context.pnl_pct,
            ma_50=context.ma_50 or 0,
            ma_21=context.ma_21 or 0,
            ma_200=context.ma_200 or 0,
            volume_ratio=context.volume_ratio,
            health_score=context.health_score,
            health_rating=context.health_rating,
            grade=context.canslim_grade,
            score=context.canslim_score,
            market_regime=context.market_regime,
            spy_price=context.spy_price,
            state_at_alert=context.state,
            days_in_position=context.days_in_position,
        )
        
        return AlertData(
            symbol=context.symbol,
            position_id=context.position_id,
            alert_type=alert_type,
            subtype=subtype,
            context=alert_context,
            title=f"{self._get_emoji(alert_type, subtype)} {context.symbol} - {subtype.value}",
            message=message,
            action=action,
            thread_source=f"{self.name}_checker",
            priority=priority,
        )
    
    def _get_emoji(self, alert_type: AlertType, subtype: AlertSubtype) -> str:
        """Get emoji for alert type."""
        emoji_map = {
            AlertType.STOP: "🛑",
            AlertType.PROFIT: "💰",
            AlertType.PYRAMID: "📈",
            AlertType.TECHNICAL: "📉",
            AlertType.HEALTH: "⚠️",
        }
        return emoji_map.get(alert_type, "📊")
    
    # Formatting helpers
    def format_price(self, price: float) -> str:
        """Format price for display."""
        return f"${price:,.2f}"
    
    def format_pct(self, pct: float) -> str:
        """Format percentage for display."""
        return f"{pct:+.1f}%"
    
    def format_dollars(self, amount: float) -> str:
        """Format dollar amount for display."""
        if amount >= 0:
            return f"+${amount:,.0f}"
        else:
            return f"-${abs(amount):,.0f}"
