"""
Position Monitor - Main Orchestrator

Coordinates all position checkers and runs monitoring cycles.
Integrates with existing AlertService for delivery.

Version: 1.0
"""

import time
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertService, AlertData
from canslim_monitor.utils.config import get_config

from .checkers import (
    BaseChecker,
    PositionContext,
    StopChecker,
    ProfitChecker,
    PyramidChecker,
    MAChecker,
    HealthChecker,
    ReentryChecker,
)


@dataclass
class MonitorCycleResult:
    """Result of a monitoring cycle."""
    positions_checked: int = 0
    alerts_generated: int = 0
    alerts: List[AlertData] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    cycle_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'positions_checked': self.positions_checked,
            'alerts_generated': self.alerts_generated,
            'errors': self.errors,
            'cycle_time_ms': self.cycle_time_ms,
            'timestamp': self.timestamp.isoformat(),
        }


class PositionMonitor:
    """
    Main position monitoring orchestrator.
    
    Runs all checkers against active positions and coordinates
    alert generation and delivery.
    
    Usage:
        monitor = PositionMonitor(alert_service=alert_service)
        
        # Single cycle
        result = monitor.run_cycle(positions, price_data, technical_data)
        
        # Process results
        for alert in result.alerts:
            print(f"{alert.symbol}: {alert.subtype.value}")
    """
    
    def __init__(
        self,
        alert_service: AlertService = None,
        config: Dict[str, Any] = None,
        logger: logging.Logger = None,
    ):
        """
        Initialize position monitor.
        
        Args:
            alert_service: AlertService instance for delivery
            config: Configuration dict (from user_config.yaml)
            logger: Logger instance
        """
        if config is None:
            full_config = get_config()
            config = full_config.get('position_monitoring', {})
        
        self.config = config
        self.alert_service = alert_service
        self.logger = logger or logging.getLogger('canslim.position_monitor')
        
        # Initialize checkers
        self.checkers: List[BaseChecker] = [
            StopChecker(config, logging.getLogger('canslim.checker.stop')),
            ProfitChecker(config, logging.getLogger('canslim.checker.profit')),
            PyramidChecker(config, logging.getLogger('canslim.checker.pyramid')),
            MAChecker(config, logging.getLogger('canslim.checker.ma')),
            HealthChecker(config, logging.getLogger('canslim.checker.health')),
            ReentryChecker(config, logging.getLogger('canslim.checker.reentry')),
        ]
    
    def run_cycle(
        self,
        positions: List[Position],
        price_data: Dict[str, Dict[str, Any]],
        technical_data: Dict[str, Dict[str, Any]] = None,
        market_regime: str = "",
        spy_price: float = 0.0,
    ) -> MonitorCycleResult:
        """
        Run a monitoring cycle across all positions.

        Args:
            positions: List of Position ORM models (state >= 1)
            price_data: Dict of symbol -> {price, volume_ratio, ...}
            technical_data: Dict of symbol -> {ma_21, ma_50, ma_200, ...}
            market_regime: Current market regime (BULLISH/NEUTRAL/BEARISH/CORRECTION)
            spy_price: Current SPY price

        Returns:
            MonitorCycleResult with all alerts and stats
        """
        start_time = time.time()
        result = MonitorCycleResult()
        technical_data = technical_data or {}

        for position in positions:
            try:
                alerts = self._check_position(
                    position, price_data, technical_data,
                    market_regime=market_regime, spy_price=spy_price
                )
                result.alerts.extend(alerts)
                result.positions_checked += 1

            except Exception as e:
                error_msg = f"Error checking {position.symbol}: {e}"
                self.logger.error(error_msg, exc_info=True)
                result.errors.append(error_msg)

        result.alerts_generated = len(result.alerts)
        result.cycle_time_ms = (time.time() - start_time) * 1000
        
        # Route alerts through AlertService if available
        if self.alert_service and result.alerts:
            self._route_alerts(result.alerts)
        
        self.logger.debug(
            f"Cycle complete: {result.positions_checked} positions, "
            f"{result.alerts_generated} alerts, {result.cycle_time_ms:.1f}ms"
        )
        
        return result
    
    def _check_position(
        self,
        position: Position,
        price_data: Dict[str, Dict[str, Any]],
        technical_data: Dict[str, Dict[str, Any]],
        market_regime: str = "",
        spy_price: float = 0.0,
    ) -> List[AlertData]:
        """Check a single position with all checkers."""
        symbol = position.symbol

        # Get price data
        price_info = price_data.get(symbol, {})
        current_price = price_info.get('price')

        if not current_price:
            self.logger.debug(f"No price data for {symbol}, skipping")
            return []

        # Merge technical data
        tech_info = technical_data.get(symbol, {})
        tech_info['volume_ratio'] = price_info.get('volume_ratio', 1.0)
        tech_info['max_price'] = price_info.get('max_price', current_price)
        tech_info['max_gain_pct'] = price_info.get('max_gain_pct', 0)

        # Build context with market regime
        context = PositionContext.from_position(
            position, current_price, tech_info,
            market_regime=market_regime, spy_price=spy_price
        )
        
        # Run all checkers
        alerts = []
        for checker in self.checkers:
            try:
                checker_alerts = checker.check(position, context)
                alerts.extend(checker_alerts)
                
            except Exception as e:
                self.logger.warning(
                    f"Checker {checker.name} failed for {symbol}: {e}"
                )
        
        return alerts
    
    def _route_alerts(self, alerts: List[AlertData]):
        """Route alerts through AlertService."""
        for alert in alerts:
            try:
                self.alert_service.create_alert(
                    symbol=alert.symbol,
                    alert_type=alert.alert_type,
                    subtype=alert.subtype,
                    context=alert.context,
                    position_id=alert.position_id,
                    message=alert.message,
                    action=alert.action,
                    thread_source=alert.thread_source,
                )
            except Exception as e:
                self.logger.error(f"Failed to route alert: {e}")
    
    def check_single_position(
        self,
        position: Position,
        current_price: float,
        technical_data: Dict[str, Any] = None,
    ) -> List[AlertData]:
        """
        Check a single position (convenience method for testing).
        
        Args:
            position: Position ORM model
            current_price: Current price
            technical_data: Technical indicators
            
        Returns:
            List of AlertData
        """
        price_data = {
            position.symbol: {
                'price': current_price,
                'volume_ratio': (technical_data or {}).get('volume_ratio', 1.0),
            }
        }
        
        tech_data = {position.symbol: technical_data or {}}
        
        result = self.run_cycle([position], price_data, tech_data)
        return result.alerts
    
    def clear_cooldowns(self, symbol: str = None):
        """
        Clear cooldowns for all checkers.
        
        Args:
            symbol: Clear for specific symbol, or all if None
        """
        for checker in self.checkers:
            if symbol:
                checker.clear_cooldown(symbol)
            else:
                checker._cooldowns.clear()

    def check_position(self, context: PositionContext) -> List[AlertData]:
        """
        Check a position using a pre-built context (for testing).
        
        This bypasses the normal flow of Position -> Context conversion,
        allowing tests to directly inject test data.
        
        Args:
            context: Pre-built PositionContext
            
        Returns:
            List of AlertData
        """
        alerts = []
        
        for checker in self.checkers:
            try:
                # Checkers expect (position, context) but we have no Position
                # Create a minimal mock position for the checker
                checker_alerts = checker.check(None, context)
                if checker_alerts:
                    alerts.extend(checker_alerts)
            except Exception as e:
                self.logger.error(f"Checker {checker.name} error: {e}")
        
        return alerts


# =============================================================================
# STANDALONE TESTING
# =============================================================================

def main():
    """Test the position monitor."""
    from canslim_monitor.data.models import Position
    
    print("=" * 60)
    print("POSITION MONITOR TEST")
    print("=" * 60)
    
    # Create test position
    position = Position(
        id=1,
        symbol="NVDA",
        portfolio="CWB",
        state=1,
        pivot=100.0,
        avg_cost=100.0,
        total_shares=100,
        hard_stop_pct=7.0,
        tp1_pct=20.0,
        tp2_pct=25.0,
        rs_rating=92,
        ad_rating="A",
        base_stage="1b(2)",
    )
    
    # Create monitor
    monitor = PositionMonitor()
    
    # Test 1: Price at entry (no alerts)
    print("\n--- Test 1: Price at Entry ---")
    alerts = monitor.check_single_position(position, 100.0)
    print(f"Alerts: {len(alerts)}")
    
    # Test 2: Price at stop
    print("\n--- Test 2: Price at Stop ($92) ---")
    alerts = monitor.check_single_position(position, 92.0)
    print(f"Alerts: {len(alerts)}")
    for alert in alerts:
        print(f"  {alert.subtype.value}: {alert.title}")
    
    # Test 3: Price at TP1
    print("\n--- Test 3: Price at TP1 ($121) ---")
    monitor.clear_cooldowns()
    alerts = monitor.check_single_position(position, 121.0)
    print(f"Alerts: {len(alerts)}")
    for alert in alerts:
        print(f"  {alert.subtype.value}: {alert.title}")
    
    # Test 4: Price in PY1 zone
    print("\n--- Test 4: Price in PY1 Zone ($103) ---")
    monitor.clear_cooldowns()
    alerts = monitor.check_single_position(position, 103.0)
    print(f"Alerts: {len(alerts)}")
    for alert in alerts:
        print(f"  {alert.subtype.value}: {alert.title}")


if __name__ == "__main__":
    main()
