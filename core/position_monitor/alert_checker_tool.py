"""
Alert Checker Tool - Run alert checkers without side effects.

This tool allows running all position alert checkers against a position
for status checking purposes. It does NOT store alerts in the database
or send Discord notifications - purely for display in the GUI.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
import logging

from canslim_monitor.data.models import Position
from canslim_monitor.services.alert_service import AlertType, AlertSubtype, AlertData
from canslim_monitor.core.position_monitor.checkers.base_checker import PositionContext
from canslim_monitor.core.position_monitor.checkers.stop_checker import StopChecker
from canslim_monitor.core.position_monitor.checkers.profit_checker import ProfitChecker
from canslim_monitor.core.position_monitor.checkers.pyramid_checker import PyramidChecker
from canslim_monitor.core.position_monitor.checkers.ma_checker import MAChecker
from canslim_monitor.core.position_monitor.checkers.health_checker import HealthChecker


class AlertCheckerTool:
    """
    Run all alert checkers against a position without side effects.

    Used by the GUI to show current alert status without storing alerts
    in the database or sending Discord notifications.
    """

    # Severity mapping for display colors
    SEVERITY_MAP = {
        # STOP alerts
        (AlertType.STOP, AlertSubtype.HARD_STOP): 'critical',
        (AlertType.STOP, AlertSubtype.TRAILING_STOP): 'critical',
        (AlertType.STOP, AlertSubtype.WARNING): 'warning',

        # PROFIT alerts
        (AlertType.PROFIT, AlertSubtype.TP1): 'profit',
        (AlertType.PROFIT, AlertSubtype.TP2): 'profit',
        (AlertType.PROFIT, AlertSubtype.EIGHT_WEEK_HOLD): 'info',

        # PYRAMID alerts
        (AlertType.PYRAMID, AlertSubtype.P1_READY): 'info',
        (AlertType.PYRAMID, AlertSubtype.P1_EXTENDED): 'info',
        (AlertType.PYRAMID, AlertSubtype.P2_READY): 'info',
        (AlertType.PYRAMID, AlertSubtype.P2_EXTENDED): 'info',

        # ADD alerts
        (AlertType.ADD, AlertSubtype.PULLBACK): 'info',

        # TECHNICAL alerts
        (AlertType.TECHNICAL, AlertSubtype.MA_50_WARNING): 'warning',
        (AlertType.TECHNICAL, AlertSubtype.MA_50_SELL): 'critical',
        (AlertType.TECHNICAL, AlertSubtype.EMA_21_SELL): 'warning',
        (AlertType.TECHNICAL, AlertSubtype.TEN_WEEK_SELL): 'critical',
        (AlertType.TECHNICAL, AlertSubtype.CLIMAX_TOP): 'warning',

        # HEALTH alerts
        (AlertType.HEALTH, AlertSubtype.CRITICAL): 'critical',
        (AlertType.HEALTH, AlertSubtype.EARNINGS): 'warning',
        (AlertType.HEALTH, AlertSubtype.LATE_STAGE): 'warning',
    }

    def __init__(self, config: Dict[str, Any] = None, logger: logging.Logger = None):
        """
        Initialize the alert checker tool.

        Args:
            config: Configuration dict (from user_config.yaml)
            logger: Logger instance
        """
        self.config = config or {}
        self.logger = logger or logging.getLogger('canslim.alert_checker_tool')

        # Initialize all checkers
        self.checkers = [
            StopChecker(config, logger),
            ProfitChecker(config, logger),
            PyramidChecker(config, logger),
            MAChecker(config, logger),
            HealthChecker(config, logger),
        ]

    def check_position(
        self,
        position: Position,
        current_price: float,
        technical_data: Dict[str, Any] = None,
        market_regime: str = "",
        spy_price: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Run all checkers against a position and return alert data.

        This method runs all checkers WITHOUT cooldowns and returns
        alert data in the format expected by AlertTableWidget.

        Args:
            position: Position ORM model
            current_price: Real-time price
            technical_data: Dict with ma_21, ma_50, ma_200, volume_ratio, etc.
            market_regime: Current market regime
            spy_price: Current SPY price

        Returns:
            List of alert dicts ready for display
        """
        if current_price <= 0:
            self.logger.warning(f"Invalid price for {position.symbol}: {current_price}")
            return []

        # Build position context
        context = PositionContext.from_position(
            position=position,
            current_price=current_price,
            technical_data=technical_data or {},
            market_regime=market_regime,
            spy_price=spy_price,
        )

        # Run all checkers with cooldowns disabled
        alerts: List[AlertData] = []
        for checker in self.checkers:
            # Clear cooldowns so all alerts fire for status check
            checker._cooldowns.clear()

            try:
                checker_alerts = checker.check(position, context)
                if checker_alerts:
                    alerts.extend(checker_alerts)
            except Exception as e:
                self.logger.error(f"Error in {checker.name} checker: {e}")

        # Convert to display format
        return [self._alert_to_dict(alert, position) for alert in alerts]

    def _alert_to_dict(self, alert: AlertData, position: Position = None) -> Dict[str, Any]:
        """
        Convert AlertData to dict format for AlertTableWidget.

        Args:
            alert: AlertData object from checker

        Returns:
            Dict with all fields needed for display
        """
        severity = self._get_severity(alert.alert_type, alert.subtype)

        return {
            # No database ID - these are real-time generated
            'id': None,

            # Identity
            'symbol': alert.symbol,
            'position_id': alert.position_id,

            # Classification
            'alert_type': alert.alert_type.value,
            'subtype': alert.subtype.value,

            # Timing
            'alert_time': datetime.now().isoformat(),

            # Price context
            'price': alert.context.current_price,
            'pnl_pct_at_alert': alert.context.pnl_pct,
            'pivot_at_alert': alert.context.pivot_price,
            'avg_cost_at_alert': alert.context.avg_cost,

            # Technical context
            'ma21': alert.context.ma_21,
            'ma50': alert.context.ma_50,
            'volume_ratio': alert.context.volume_ratio,

            # Scoring context
            'grade': alert.context.grade,
            'score': alert.context.score,
            'health_rating': alert.context.health_rating,

            # Market context
            'market_regime': alert.context.market_regime,

            # Display metadata
            'severity': severity,
            'acknowledged': False,  # Not applicable for real-time checks

            # Full message for detail view
            'message': alert.message,
            'action': alert.action,
            'priority': alert.priority,

            # Volume context
            'avg_volume': getattr(position, 'avg_volume_50d', None) if position else None,
        }

    def _get_severity(self, alert_type: AlertType, subtype: AlertSubtype) -> str:
        """
        Get severity level for color coding.

        Args:
            alert_type: Alert type enum
            subtype: Alert subtype enum

        Returns:
            Severity string: 'critical', 'warning', 'profit', 'info', 'neutral'
        """
        return self.SEVERITY_MAP.get((alert_type, subtype), 'neutral')

    def get_status_summary(
        self,
        position: Position,
        current_price: float,
        technical_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Get a quick summary of position alert status.

        Args:
            position: Position ORM model
            current_price: Real-time price
            technical_data: Technical indicators

        Returns:
            Dict with summary info
        """
        alerts = self.check_position(position, current_price, technical_data)

        # Count by severity
        severity_counts = {'critical': 0, 'warning': 0, 'profit': 0, 'info': 0}
        for alert in alerts:
            sev = alert.get('severity', 'neutral')
            if sev in severity_counts:
                severity_counts[sev] += 1

        # Determine overall status
        if severity_counts['critical'] > 0:
            status = 'critical'
        elif severity_counts['warning'] > 0:
            status = 'warning'
        elif severity_counts['profit'] > 0:
            status = 'profit'
        elif severity_counts['info'] > 0:
            status = 'info'
        else:
            status = 'ok'

        return {
            'status': status,
            'total_alerts': len(alerts),
            'critical': severity_counts['critical'],
            'warning': severity_counts['warning'],
            'profit': severity_counts['profit'],
            'info': severity_counts['info'],
            'alerts': alerts,
        }
