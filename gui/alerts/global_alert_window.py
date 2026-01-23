"""
CANSLIM Monitor - Global Alert Window
======================================
Singleton free-floating window showing all alerts with advanced filtering.
Accessible from main menu: View -> Alert Monitor

Features:
- Singleton pattern (only one instance)
- Date/time preset filters (15 min, 1 hour, 4 hours, today, 7 days, 30 days)
- Custom date range picker
- Quick time filter (last X minutes/hours/days)
- Filter by symbol, type
- Auto-refresh with configurable interval
- Real-time new alert highlighting
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QComboBox, QCheckBox, QFrame, QStatusBar,
    QGroupBox, QRadioButton, QButtonGroup, QSpinBox, QDateTimeEdit
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QDateTime
from PyQt6.QtGui import QFont, QAction

from .alert_table_widget import AlertTableWidget, TypeFilterButton
from .alert_detail_dialog import AlertDetailDialog


class DateRangeFilterWidget(QGroupBox):
    """Widget for selecting date/time range with presets."""
    
    filter_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("Date/Time Filter", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 12, 8, 8)
        
        # Preset buttons row
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(4)
        
        self.preset_group = QButtonGroup(self)
        
        presets = [
            ("15 min", 15),
            ("1 Hour", 60),
            ("4 Hours", 240),
            ("Today", "today"),
            ("7 Days", 7 * 24 * 60),
            ("30 Days", 30 * 24 * 60),
            ("Custom", "custom"),
        ]
        
        for i, (label, value) in enumerate(presets):
            btn = QRadioButton(label)
            btn.setProperty("preset_value", value)
            self.preset_group.addButton(btn, i)
            preset_layout.addWidget(btn)
            
            if label == "Today":
                btn.setChecked(True)
        
        self.preset_group.buttonClicked.connect(self._on_preset_changed)
        layout.addLayout(preset_layout)
        
        # Second row: Custom range and quick filter
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)
        
        # Custom date range section
        self.custom_frame = QFrame()
        custom_layout = QHBoxLayout(self.custom_frame)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(4)
        
        custom_layout.addWidget(QLabel("From:"))
        self.from_datetime = QDateTimeEdit()
        self.from_datetime.setCalendarPopup(True)
        self.from_datetime.setDateTime(QDateTime.currentDateTime().addDays(-1))
        self.from_datetime.setDisplayFormat("MM/dd HH:mm")
        self.from_datetime.setMaximumWidth(120)
        self.from_datetime.dateTimeChanged.connect(self._on_custom_changed)
        custom_layout.addWidget(self.from_datetime)
        
        custom_layout.addWidget(QLabel("To:"))
        self.to_datetime = QDateTimeEdit()
        self.to_datetime.setCalendarPopup(True)
        self.to_datetime.setDateTime(QDateTime.currentDateTime())
        self.to_datetime.setDisplayFormat("MM/dd HH:mm")
        self.to_datetime.setMaximumWidth(120)
        self.to_datetime.dateTimeChanged.connect(self._on_custom_changed)
        custom_layout.addWidget(self.to_datetime)
        
        self.custom_frame.setVisible(False)
        row2_layout.addWidget(self.custom_frame)
        
        # Quick minute/hour/day selector
        row2_layout.addWidget(QLabel("Or last"))
        self.quick_value = QSpinBox()
        self.quick_value.setRange(1, 999)
        self.quick_value.setValue(30)
        self.quick_value.setMaximumWidth(60)
        row2_layout.addWidget(self.quick_value)
        
        self.quick_unit = QComboBox()
        self.quick_unit.addItems(["minutes", "hours", "days"])
        self.quick_unit.setMaximumWidth(80)
        row2_layout.addWidget(self.quick_unit)
        
        apply_quick_btn = QPushButton("Apply")
        apply_quick_btn.setMaximumWidth(60)
        apply_quick_btn.clicked.connect(self._apply_quick_filter)
        row2_layout.addWidget(apply_quick_btn)
        
        row2_layout.addStretch()
        layout.addLayout(row2_layout)
    
    def _on_preset_changed(self, button):
        """Handle preset button selection."""
        value = button.property("preset_value")
        self.custom_frame.setVisible(value == "custom")
        
        if value != "custom":
            self.filter_changed.emit()
    
    def _on_custom_changed(self):
        """Handle custom date range change."""
        checked = self.preset_group.checkedButton()
        if checked and checked.property("preset_value") == "custom":
            self.filter_changed.emit()
    
    def _apply_quick_filter(self):
        """Apply quick time filter."""
        # Uncheck all presets
        checked = self.preset_group.checkedButton()
        if checked:
            self.preset_group.setExclusive(False)
            checked.setChecked(False)
            self.preset_group.setExclusive(True)
        
        self.filter_changed.emit()
    
    def get_date_range(self) -> tuple:
        """
        Get the selected date range as (from_datetime, to_datetime).
        Returns Python datetime objects.
        """
        now = datetime.now()
        
        # Check if quick filter was used (no preset selected)
        checked = self.preset_group.checkedButton()
        
        if checked is None:
            # Quick filter
            value = self.quick_value.value()
            unit = self.quick_unit.currentText()
            
            if unit == "minutes":
                delta = timedelta(minutes=value)
            elif unit == "hours":
                delta = timedelta(hours=value)
            else:  # days
                delta = timedelta(days=value)
            
            return (now - delta, now)
        
        preset_value = checked.property("preset_value")
        
        if preset_value == "custom":
            from_dt = self.from_datetime.dateTime().toPyDateTime()
            to_dt = self.to_datetime.dateTime().toPyDateTime()
            return (from_dt, to_dt)
        
        elif preset_value == "today":
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return (start_of_day, now)
        
        else:
            # Preset is in minutes
            delta = timedelta(minutes=preset_value)
            return (now - delta, now)
    
    def get_hours(self) -> int:
        """Get the selected range as hours (for backward compatibility)."""
        from_dt, to_dt = self.get_date_range()
        delta = to_dt - from_dt
        return max(1, int(delta.total_seconds() / 3600) + 1)
    
    def get_description(self) -> str:
        """Get human-readable description of current filter."""
        checked = self.preset_group.checkedButton()
        
        if checked is None:
            value = self.quick_value.value()
            unit = self.quick_unit.currentText()
            return f"Last {value} {unit}"
        
        preset_value = checked.property("preset_value")
        
        if preset_value == "custom":
            from_dt = self.from_datetime.dateTime().toString("MM/dd HH:mm")
            to_dt = self.to_datetime.dateTime().toString("MM/dd HH:mm")
            return f"{from_dt} to {to_dt}"
        
        return checked.text()


class GlobalAlertWindow(QMainWindow):
    """
    Singleton window for monitoring all alerts.
    
    Usage:
        window = GlobalAlertWindow.get_instance(parent, db_session_factory, config)
    """
    
    _instance: Optional['GlobalAlertWindow'] = None
    
    alert_acknowledged = pyqtSignal(int)  # Emitted when alert is acknowledged
    
    @classmethod
    def get_instance(
        cls,
        parent=None,
        db_session_factory=None,
        alert_service=None,
        config: Optional[Dict] = None
    ) -> 'GlobalAlertWindow':
        """
        Get or create the singleton instance.
        """
        if cls._instance is None or not cls._instance.isVisible():
            cls._instance = cls(parent, db_session_factory, alert_service, config)
        
        cls._instance.raise_()
        cls._instance.activateWindow()
        return cls._instance
    
    def __init__(
        self,
        parent=None,
        db_session_factory=None,
        alert_service=None,
        config: Optional[Dict] = None
    ):
        super().__init__(parent)
        
        self.db_session_factory = db_session_factory
        self.alert_service = alert_service
        self.config = config or {}
        
        # Get display settings from config
        display_config = self.config.get('alerts', {}).get('display', {})
        self.auto_refresh_default = display_config.get('auto_refresh', True)
        self.refresh_interval = display_config.get('refresh_interval', 30) * 1000  # ms
        self.highlight_duration = display_config.get('highlight_duration', 5) * 1000
        
        # State
        self._all_symbols: Set[str] = set()
        self._current_alerts: List[Dict[str, Any]] = []
        
        self._setup_ui()
        self._setup_refresh_timer()
        
        # Initial load
        self._refresh_data()
    
    def _setup_ui(self):
        """Set up the window UI."""
        self.setWindowTitle("🔔 Alert Monitor")
        self.setMinimumSize(950, 550)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Date/Time Filter Widget
        self.date_filter = DateRangeFilterWidget()
        self.date_filter.filter_changed.connect(self._refresh_data)
        layout.addWidget(self.date_filter)
        
        # Additional filters row
        filter_row = self._create_filter_row()
        layout.addLayout(filter_row)
        
        # Refresh row
        refresh_row = self._create_refresh_row()
        layout.addLayout(refresh_row)
        
        # Alert table
        self.table = AlertTableWidget(show_symbol_column=True)
        self.table.alert_double_clicked.connect(self._on_alert_double_click)
        layout.addWidget(self.table, stretch=1)
        
        # Footer
        footer = self._create_footer()
        layout.addLayout(footer)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
    
    def _create_filter_row(self) -> QHBoxLayout:
        """Create the filter controls row."""
        layout = QHBoxLayout()
        
        # Symbol filter
        symbol_label = QLabel("Symbol:")
        layout.addWidget(symbol_label)
        
        self.symbol_combo = QComboBox()
        self.symbol_combo.setMinimumWidth(100)
        self.symbol_combo.addItem("All")
        self.symbol_combo.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self.symbol_combo)
        
        layout.addSpacing(15)
        
        # Type filter
        type_label = QLabel("Type:")
        layout.addWidget(type_label)
        
        self.type_filter = TypeFilterButton()
        self.type_filter.filter_changed.connect(self._on_type_filter_changed)
        layout.addWidget(self.type_filter)
        
        layout.addStretch()
        
        return layout
    
    def _create_refresh_row(self) -> QHBoxLayout:
        """Create the refresh controls row."""
        layout = QHBoxLayout()
        
        # Auto-refresh checkbox
        self.auto_refresh_check = QCheckBox("🔄 Auto-refresh")
        self.auto_refresh_check.setChecked(self.auto_refresh_default)
        self.auto_refresh_check.stateChanged.connect(self._on_auto_refresh_changed)
        layout.addWidget(self.auto_refresh_check)
        
        # Interval combo
        interval_label = QLabel("Interval:")
        layout.addWidget(interval_label)
        
        self.interval_combo = QComboBox()
        self.interval_combo.setMinimumWidth(70)
        self.interval_combo.addItems(['10s', '30s', '60s', '5m'])
        self.interval_combo.setCurrentIndex(1)  # 30s default
        self.interval_combo.currentTextChanged.connect(self._on_interval_changed)
        layout.addWidget(self.interval_combo)
        
        layout.addStretch()
        
        # Refresh now button
        self.refresh_btn = QPushButton("Refresh Now")
        self.refresh_btn.setMinimumWidth(100)
        self.refresh_btn.clicked.connect(self._refresh_data)
        layout.addWidget(self.refresh_btn)
        
        return layout
    
    def _create_footer(self) -> QHBoxLayout:
        """Create the footer row."""
        layout = QHBoxLayout()
        
        # Count label
        self.count_label = QLabel("Showing 0 alerts")
        layout.addWidget(self.count_label)
        
        layout.addStretch()
        
        # Export button
        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._on_export)
        layout.addWidget(export_btn)
        
        # Clear filters button
        clear_btn = QPushButton("Clear Filters")
        clear_btn.clicked.connect(self._clear_filters)
        layout.addWidget(clear_btn)
        
        return layout
    
    def _setup_refresh_timer(self):
        """Set up the auto-refresh timer."""
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_data)
        
        if self.auto_refresh_check.isChecked():
            self.refresh_timer.start(self.refresh_interval)
    
    def _on_auto_refresh_changed(self, state):
        """Handle auto-refresh checkbox change."""
        if state == Qt.CheckState.Checked.value:
            self.refresh_timer.start(self.refresh_interval)
            self.status_bar.showMessage("Auto-refresh enabled", 2000)
        else:
            self.refresh_timer.stop()
            self.status_bar.showMessage("Auto-refresh disabled", 2000)
    
    def _on_interval_changed(self, text: str):
        """Handle refresh interval change."""
        intervals = {
            '10s': 10000,
            '30s': 30000,
            '60s': 60000,
            '5m': 300000
        }
        
        self.refresh_interval = intervals.get(text, 30000)
        
        if self.auto_refresh_check.isChecked():
            self.refresh_timer.stop()
            self.refresh_timer.start(self.refresh_interval)
    
    def _on_filter_changed(self):
        """Handle symbol filter change."""
        self._apply_filters()
    
    def _on_type_filter_changed(self, selected_types: set):
        """Handle type filter change."""
        self.table.set_type_filter(selected_types)
        self._update_count()
    
    def _apply_filters(self):
        """Apply current filters to the table."""
        symbol = self.symbol_combo.currentText()
        if symbol == "All":
            symbol = None
        
        # Filter alerts by symbol
        if symbol:
            filtered = [a for a in self._current_alerts if a.get('symbol') == symbol]
        else:
            filtered = self._current_alerts
        
        self.table.set_alerts(filtered)
        self._update_count()
    
    def _refresh_data(self):
        """Refresh alert data from database."""
        try:
            # Get date range from filter widget
            hours = self.date_filter.get_hours()
            
            symbol = self.symbol_combo.currentText()
            if symbol == "All":
                symbol = None
            
            # Fetch alerts
            alerts = self._fetch_alerts_direct(symbol, hours)
            
            if alerts:
                # Update symbol filter options
                symbols = {a.get('symbol') for a in alerts if a.get('symbol')}
                self._all_symbols.update(symbols)
                self._update_symbol_filter(self._all_symbols)
                
                # Store and display
                self._current_alerts = alerts
                self.table.set_alerts(alerts)
                self._update_count()
            
            # Update status
            desc = self.date_filter.get_description()
            self.status_bar.showMessage(
                f"Showing: {desc} | Last updated: {datetime.now().strftime('%H:%M:%S')}", 
                10000
            )
            
        except Exception as e:
            self.status_bar.showMessage(f"Refresh failed: {e}", 5000)
    
    def _fetch_alerts_direct(self, symbol: Optional[str], hours: int) -> List[Dict]:
        """Fetch alerts directly from database."""
        if not self.db_session_factory:
            return []
        
        try:
            from canslim_monitor.data.models import Alert
            from canslim_monitor.services.alert_service import AlertService
            
            session = self.db_session_factory()
            try:
                query = session.query(Alert)
                
                cutoff = datetime.now() - timedelta(hours=hours)
                query = query.filter(Alert.alert_time >= cutoff)
                
                if symbol:
                    query = query.filter(Alert.symbol == symbol)
                
                query = query.order_by(Alert.alert_time.desc()).limit(2000)
                
                alerts = []
                for a in query.all():
                    alerts.append({
                        'id': a.id,
                        'symbol': a.symbol,
                        'position_id': a.position_id,
                        'alert_type': a.alert_type,
                        'subtype': a.alert_subtype,
                        'alert_time': a.alert_time.isoformat() if a.alert_time else None,
                        'price': a.price,
                        'message': a.message,
                        'action': a.action,
                        'pivot_at_alert': a.pivot_at_alert,
                        'avg_cost_at_alert': a.avg_cost_at_alert,
                        'pnl_pct_at_alert': a.pnl_pct_at_alert,
                        'state_at_alert': a.state_at_alert,
                        'ma50': a.ma50,
                        'ma21': a.ma21,
                        'volume_ratio': a.volume_ratio,
                        'health_score': a.health_score,
                        'health_rating': a.health_rating,
                        'grade': a.canslim_grade,
                        'score': a.canslim_score,
                        'market_regime': a.market_regime,
                        'severity': AlertService.get_alert_severity(a.alert_type, a.alert_subtype),
                        'acknowledged': a.acknowledged or False,
                    })
                
                return alerts
                
            finally:
                session.close()
                
        except Exception as e:
            print(f"Error fetching alerts: {e}")
            return []
    
    def _update_symbol_filter(self, symbols: Set[str]):
        """Update symbol filter combo box."""
        current = self.symbol_combo.currentText()
        
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        self.symbol_combo.addItem("All")
        
        for symbol in sorted(symbols):
            self.symbol_combo.addItem(symbol)
        
        idx = self.symbol_combo.findText(current)
        if idx >= 0:
            self.symbol_combo.setCurrentIndex(idx)
        
        self.symbol_combo.blockSignals(False)
    
    def _update_count(self):
        """Update the alert count label."""
        total = self.table.get_alert_count()
        filtered = self.table.get_filtered_count()
        
        if total == filtered:
            self.count_label.setText(f"Showing {total} alerts")
        else:
            self.count_label.setText(f"Showing {filtered} of {total} alerts")
    
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
        for alert in self._current_alerts:
            if alert.get('id') == alert_id:
                alert['acknowledged'] = True
                break
        
        self.table.set_alerts(self._current_alerts)
        self.alert_acknowledged.emit(alert_id)
    
    def _clear_filters(self):
        """Clear all filters."""
        self.symbol_combo.setCurrentIndex(0)
        self.type_filter._selected_types.clear()
        self.type_filter._update_text()
        self.table.set_type_filter(set())
        
        # Reset date filter to "Today"
        for btn in self.date_filter.preset_group.buttons():
            if btn.property("preset_value") == "today":
                btn.setChecked(True)
                break
        self.date_filter.custom_frame.setVisible(False)
        
        self._refresh_data()
        self.status_bar.showMessage("Filters cleared", 2000)
    
    def _on_export(self):
        """Export all alerts to CSV."""
        from PyQt6.QtWidgets import QFileDialog
        import csv
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Alerts",
            f"alerts_{datetime.now().strftime('%Y%m%d')}.csv",
            "CSV Files (*.csv)"
        )
        
        if filename:
            try:
                with open(filename, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Time', 'Symbol', 'Type', 'Subtype', 'Price', 'P&L%', 'Acknowledged'])
                    
                    for alert in self._current_alerts:
                        writer.writerow([
                            alert.get('alert_time', ''),
                            alert.get('symbol', ''),
                            alert.get('alert_type', ''),
                            alert.get('subtype', ''),
                            alert.get('price', ''),
                            alert.get('pnl_pct_at_alert', ''),
                            'Yes' if alert.get('acknowledged') else 'No'
                        ])
                
                self.status_bar.showMessage(f"Exported {len(self._current_alerts)} alerts to {filename}", 3000)
            except Exception as e:
                self.status_bar.showMessage(f"Export failed: {e}", 5000)
    
    def closeEvent(self, event):
        """Handle window close."""
        self.refresh_timer.stop()
        GlobalAlertWindow._instance = None
        super().closeEvent(event)


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    window = GlobalAlertWindow.get_instance()
    
    test_alerts = [
        {'id': 1, 'symbol': 'NVDA', 'alert_type': 'BREAKOUT', 'subtype': 'CONFIRMED',
         'alert_time': datetime.now().isoformat(), 'price': 142.50, 
         'pnl_pct_at_alert': 2.3, 'severity': 'info', 'acknowledged': False},
        {'id': 2, 'symbol': 'AMD', 'alert_type': 'STOP', 'subtype': 'WARNING',
         'alert_time': datetime.now().isoformat(), 'price': 178.30, 
         'pnl_pct_at_alert': -5.2, 'severity': 'warning', 'acknowledged': False},
    ]
    
    window._current_alerts = test_alerts
    window.table.set_alerts(test_alerts)
    window._update_symbol_filter({'NVDA', 'AMD'})
    window._update_count()
    window.show()
    
    sys.exit(app.exec())
