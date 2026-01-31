"""
CANSLIM Monitor - GUI Alert Components
=======================================
Alert visualization components for the GUI.

Components:
- AlertTableWidget: Reusable sortable/filterable alert table
- AlertDetailDialog: Single alert detail view with IBD education
- PositionAlertDialog: Alerts for a specific symbol
- AlertCheckDialog: Real-time alert status check dialog
- GlobalAlertWindow: Singleton window for all alerts
- AlertDescription: IBD education content
"""

from .alert_descriptions import (
    AlertDescription,
    get_alert_description,
    get_description_text,
    ALERT_DESCRIPTIONS,
)

from .alert_table_widget import (
    AlertTableWidget,
    TypeFilterButton,
)

from .alert_detail_dialog import AlertDetailDialog

from .position_alert_dialog import PositionAlertDialog

from .alert_check_dialog import AlertCheckDialog

from .global_alert_window import GlobalAlertWindow


__all__ = [
    'AlertDescription',
    'get_alert_description',
    'get_description_text',
    'ALERT_DESCRIPTIONS',
    'AlertTableWidget',
    'TypeFilterButton',
    'AlertDetailDialog',
    'PositionAlertDialog',
    'AlertCheckDialog',
    'GlobalAlertWindow',
]
