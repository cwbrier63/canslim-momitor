"""
CANSLIM Monitor - Position Alert Dialog
========================================
Dialog showing all alerts for a specific symbol.
Accessed via right-click on position card -> "View Alerts"
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from .alert_table_widget import AlertTableWidget, TypeFilterButton
from .alert_detail_dialog import AlertDetailDialog


class PositionAlertDialog(QDialog):
    """
    Dialog showing all alerts for a specific symbol.
    
    Features:
    - Filterable by alert type
    - Sortable columns
    - Double-click for detail view
    - Export option
    """
    
    alert_acknowledged = pyqtSignal(int)  # Emitted when alert is acknowledged
    
    def __init__(
        self,
        symbol: str,
        alerts: List[Dict[str, Any]],
        parent=None,
        alert_service=None,
        db_session_factory=None
    ):
        """
        Initialize the position alert dialog.
        
        Args:
            symbol: Stock symbol
            alerts: List of alert dictionaries for this symbol
            parent: Parent widget
            alert_service: AlertService for acknowledge functionality
            db_session_factory: Database session factory for enriching alert data
        """
        super().__init__(parent)
        
        self.symbol = symbol
        self.alerts = alerts
        self.alert_service = alert_service
        self.db_session_factory = db_session_factory
        
        self._setup_ui()
        self._populate_data()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle(f"📊 Alerts for {self.symbol}")
        self.setMinimumSize(700, 450)
        self.setModal(False)  # Modeless - don't block main window
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Header
        header = self._create_header()
        layout.addLayout(header)
        
        # Filter row
        filter_row = self._create_filter_row()
        layout.addLayout(filter_row)
        
        # Alert table (no symbol column since all same symbol)
        self.table = AlertTableWidget(show_symbol_column=False)
        self.table.alert_double_clicked.connect(self._on_alert_double_click)
        layout.addWidget(self.table, stretch=1)
        
        # Footer
        footer = self._create_footer()
        layout.addLayout(footer)
    
    def _create_header(self) -> QHBoxLayout:
        """Create the header row."""
        layout = QHBoxLayout()
        
        # Symbol label
        title = QLabel(f"📊 Alerts for {self.symbol}")
        title.setFont(QFont('Arial', 14, QFont.Weight.Bold))
        layout.addWidget(title)
        
        layout.addStretch()
        
        return layout
    
    def _create_filter_row(self) -> QHBoxLayout:
        """Create the filter row."""
        layout = QHBoxLayout()
        
        # Type filter
        filter_label = QLabel("Filter:")
        layout.addWidget(filter_label)
        
        self.type_filter = TypeFilterButton()
        self.type_filter.filter_changed.connect(self._on_type_filter_changed)
        layout.addWidget(self.type_filter)
        
        layout.addStretch()
        
        # Alert count
        self.count_label = QLabel()
        layout.addWidget(self.count_label)
        
        return layout
    
    def _create_footer(self) -> QHBoxLayout:
        """Create the footer row."""
        layout = QHBoxLayout()
        
        # Info label
        self.info_label = QLabel("Double-click row for details")
        self.info_label.setStyleSheet("color: #888;")
        layout.addWidget(self.info_label)
        
        layout.addStretch()
        
        # Export button
        export_btn = QPushButton("Export CSV")
        export_btn.setMinimumWidth(90)
        export_btn.clicked.connect(self._on_export)
        layout.addWidget(export_btn)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setMinimumWidth(70)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        return layout
    
    def _populate_data(self):
        """Populate the table with alerts."""
        self.table.set_alerts(self.alerts)
        
        # Update type filter options
        available_types = self.table.get_available_types()
        self.type_filter.set_available_types(available_types)
        
        # Update count
        self._update_count()
    
    def _update_count(self):
        """Update the alert count label."""
        total = self.table.get_alert_count()
        filtered = self.table.get_filtered_count()
        
        if total == filtered:
            self.count_label.setText(f"Total: {total} alerts")
        else:
            self.count_label.setText(f"Showing: {filtered} of {total} alerts")
    
    def _on_type_filter_changed(self, types: set):
        """Handle type filter change."""
        self.table.set_type_filter(types)
        self._update_count()
    
    def _on_alert_double_click(self, alert: Dict[str, Any]):
        """Handle double-click on alert row."""
        dialog = AlertDetailDialog(
            alert=alert,
            parent=self,
            alert_service=self.alert_service,
            db_session_factory=self.db_session_factory
        )
        dialog.alert_acknowledged.connect(self._on_alert_acknowledged)
        dialog.exec()
    
    def _on_alert_acknowledged(self, alert_id: int):
        """Handle alert acknowledgment."""
        # Update local data
        for alert in self.alerts:
            if alert.get('id') == alert_id:
                alert['acknowledged'] = True
                break
        
        # Refresh table
        self.table.set_alerts(self.alerts)
        
        # Emit signal
        self.alert_acknowledged.emit(alert_id)
    
    def _on_export(self):
        """Export alerts to CSV."""
        from PyQt6.QtWidgets import QFileDialog
        import csv
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Alerts",
            f"{self.symbol}_alerts.csv",
            "CSV Files (*.csv)"
        )
        
        if filename:
            try:
                with open(filename, 'w', newline='') as f:
                    writer = csv.writer(f)
                    
                    # Header
                    writer.writerow(['Time', 'Type', 'Subtype', 'Price', 'P&L%', 'Acknowledged'])
                    
                    # Data
                    for alert in self.alerts:
                        writer.writerow([
                            alert.get('alert_time', ''),
                            alert.get('alert_type', ''),
                            alert.get('subtype', ''),
                            alert.get('price', ''),
                            alert.get('pnl_pct_at_alert', ''),
                            'Yes' if alert.get('acknowledged') else 'No'
                        ])
                
                self.info_label.setText(f"Exported to {filename}")
            except Exception as e:
                self.info_label.setText(f"Export failed: {e}")


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Test data
    test_alerts = [
        {'id': 1, 'symbol': 'NVDA', 'alert_type': 'BREAKOUT', 'subtype': 'CONFIRMED',
         'alert_time': '2026-01-18T09:32:00', 'price': 142.50, 'pnl_pct_at_alert': 2.3, 
         'severity': 'info', 'acknowledged': False},
        {'id': 2, 'symbol': 'NVDA', 'alert_type': 'PYRAMID', 'subtype': 'P1_READY',
         'alert_time': '2026-01-17T14:15:00', 'price': 145.20, 'pnl_pct_at_alert': 4.2, 
         'severity': 'info', 'acknowledged': False},
        {'id': 3, 'symbol': 'NVDA', 'alert_type': 'PROFIT', 'subtype': 'TP1',
         'alert_time': '2026-01-17T11:03:00', 'price': 152.80, 'pnl_pct_at_alert': 9.7, 
         'severity': 'profit', 'acknowledged': True},
        {'id': 4, 'symbol': 'NVDA', 'alert_type': 'TECHNICAL', 'subtype': '50_MA_WARNING',
         'alert_time': '2026-01-16T10:45:00', 'price': 138.90, 'pnl_pct_at_alert': -0.4, 
         'severity': 'warning', 'acknowledged': True},
    ]
    
    dialog = PositionAlertDialog("NVDA", test_alerts)
    dialog.exec()
