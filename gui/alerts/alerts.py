"""
CANSLIM Monitor - Alert Monitor Windows
Global and position-specific alert viewing with advanced date filtering.
"""

from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List, Callable

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QLabel, QHeaderView, QComboBox, QWidget,
    QAbstractItemView, QMessageBox, QFrame, QGroupBox, QFormLayout,
    QDateTimeEdit, QSpinBox, QRadioButton, QButtonGroup, QCheckBox,
    QSplitter, QTextEdit
)
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    pyqtSignal, QTimer, QDateTime, QDate, QTime
)
from PyQt6.QtGui import QFont, QColor, QBrush


# Alert severity colors
SEVERITY_COLORS = {
    'critical': QColor(220, 53, 69),    # Red
    'high': QColor(255, 140, 0),        # Orange
    'medium': QColor(255, 193, 7),      # Yellow
    'low': QColor(40, 167, 69),         # Green
    'info': QColor(23, 162, 184),       # Cyan
}

SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}


class AlertTableModel(QAbstractTableModel):
    """Table model for displaying alerts."""
    
    COLUMNS = [
        ('alert_time', 'Time'),
        ('symbol', 'Symbol'),
        ('alert_type', 'Type'),
        ('alert_subtype', 'Subtype'),
        ('price', 'Price'),
        ('pnl_pct', 'P&L %'),
        ('severity', 'Severity'),
        ('acknowledged', 'Ack'),
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []
        self._column_keys = [col[0] for col in self.COLUMNS]
        self._column_names = [col[1] for col in self.COLUMNS]
    
    def load_alerts(self, alerts: List[Dict[str, Any]]):
        """Load alert data into the model."""
        self.beginResetModel()
        self._data = alerts
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)
    
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        
        row_data = self._data[index.row()]
        col_key = self._column_keys[index.column()]
        value = row_data.get(col_key)
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col_key == 'alert_time':
                if isinstance(value, datetime):
                    return value.strftime('%m/%d %H:%M')
                elif isinstance(value, str):
                    try:
                        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        return dt.strftime('%m/%d %H:%M')
                    except:
                        return value[:16] if len(value) > 16 else value
                return str(value) if value else ""
            elif col_key == 'price':
                return f"${value:.2f}" if value else ""
            elif col_key == 'pnl_pct':
                return f"{value:+.1f}%" if value is not None else ""
            elif col_key == 'acknowledged':
                return "✓" if value else ""
            elif value is None:
                return ""
            return str(value)
        
        elif role == Qt.ItemDataRole.BackgroundRole:
            severity = row_data.get('severity', 'info')
            color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS['info'])
            # Make it lighter for background
            return QBrush(QColor(color.red(), color.green(), color.blue(), 40))
        
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col_key == 'severity':
                severity = row_data.get('severity', 'info')
                return QBrush(SEVERITY_COLORS.get(severity, SEVERITY_COLORS['info']))
            elif col_key == 'pnl_pct' and value is not None:
                if value > 0:
                    return QBrush(QColor(80, 220, 100))  # Green
                elif value < 0:
                    return QBrush(QColor(255, 100, 100))  # Red
        
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col_key in ('alert_time', 'severity', 'acknowledged', 'price', 'pnl_pct'):
                return Qt.AlignmentFlag.AlignCenter
        
        elif role == Qt.ItemDataRole.UserRole:
            return value
        
        return None
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self._column_names[section]
            else:
                return section + 1
        return None
    
    def get_alert_data(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None


class DateRangeFilterWidget(QGroupBox):
    """Widget for selecting date/time range with presets."""
    
    filter_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("Date/Time Filter", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        
        # Preset buttons row
        preset_layout = QHBoxLayout()
        
        self.preset_group = QButtonGroup(self)
        
        presets = [
            ("Last 15 min", 15),
            ("Last Hour", 60),
            ("Last 4 Hours", 240),
            ("Today", "today"),
            ("Last 7 Days", 7 * 24 * 60),
            ("Last 30 Days", 30 * 24 * 60),
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
        
        # Custom date range section
        self.custom_frame = QFrame()
        custom_layout = QHBoxLayout(self.custom_frame)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        
        custom_layout.addWidget(QLabel("From:"))
        self.from_datetime = QDateTimeEdit()
        self.from_datetime.setCalendarPopup(True)
        self.from_datetime.setDateTime(QDateTime.currentDateTime().addDays(-1))
        self.from_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.from_datetime.dateTimeChanged.connect(self._on_custom_changed)
        custom_layout.addWidget(self.from_datetime)
        
        custom_layout.addWidget(QLabel("To:"))
        self.to_datetime = QDateTimeEdit()
        self.to_datetime.setCalendarPopup(True)
        self.to_datetime.setDateTime(QDateTime.currentDateTime())
        self.to_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.to_datetime.dateTimeChanged.connect(self._on_custom_changed)
        custom_layout.addWidget(self.to_datetime)
        
        custom_layout.addStretch()
        
        self.custom_frame.setVisible(False)
        layout.addWidget(self.custom_frame)
        
        # Quick minute/hour selector
        self.quick_frame = QFrame()
        quick_layout = QHBoxLayout(self.quick_frame)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        
        quick_layout.addWidget(QLabel("Or last"))
        self.quick_value = QSpinBox()
        self.quick_value.setRange(1, 999)
        self.quick_value.setValue(30)
        self.quick_value.valueChanged.connect(self._on_quick_changed)
        quick_layout.addWidget(self.quick_value)
        
        self.quick_unit = QComboBox()
        self.quick_unit.addItems(["minutes", "hours", "days"])
        self.quick_unit.currentIndexChanged.connect(self._on_quick_changed)
        quick_layout.addWidget(self.quick_unit)
        
        apply_quick_btn = QPushButton("Apply")
        apply_quick_btn.clicked.connect(self._apply_quick_filter)
        quick_layout.addWidget(apply_quick_btn)
        
        quick_layout.addStretch()
        layout.addWidget(self.quick_frame)
    
    def _on_preset_changed(self, button):
        """Handle preset button selection."""
        value = button.property("preset_value")
        self.custom_frame.setVisible(value == "custom")
        
        if value != "custom":
            self.filter_changed.emit()
    
    def _on_custom_changed(self):
        """Handle custom date range change."""
        # Only emit if custom is selected
        checked = self.preset_group.checkedButton()
        if checked and checked.property("preset_value") == "custom":
            self.filter_changed.emit()
    
    def _on_quick_changed(self):
        """Handle quick filter value change."""
        pass  # Don't auto-apply, wait for button click
    
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
    
    def get_description(self) -> str:
        """Get human-readable description of current filter."""
        checked = self.preset_group.checkedButton()
        
        if checked is None:
            value = self.quick_value.value()
            unit = self.quick_unit.currentText()
            return f"Last {value} {unit}"
        
        preset_value = checked.property("preset_value")
        
        if preset_value == "custom":
            from_dt = self.from_datetime.dateTime().toString("yyyy-MM-dd HH:mm")
            to_dt = self.to_datetime.dateTime().toString("yyyy-MM-dd HH:mm")
            return f"{from_dt} to {to_dt}"
        
        return checked.text()


class AlertFilterProxyModel(QSortFilterProxyModel):
    """Proxy model for filtering alerts by date, type, symbol, severity."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._from_datetime: Optional[datetime] = None
        self._to_datetime: Optional[datetime] = None
        self._symbol_filter: str = ""
        self._type_filter: str = ""
        self._severity_filter: set = set()
        self._hide_acknowledged: bool = False
    
    def set_date_range(self, from_dt: datetime, to_dt: datetime):
        """Set the date range filter."""
        self._from_datetime = from_dt
        self._to_datetime = to_dt
        self.invalidateFilter()
    
    def set_symbol_filter(self, text: str):
        """Set symbol filter (partial match)."""
        self._symbol_filter = text.upper()
        self.invalidateFilter()
    
    def set_type_filter(self, text: str):
        """Set alert type filter (partial match)."""
        self._type_filter = text.lower()
        self.invalidateFilter()
    
    def set_severity_filter(self, severities: set):
        """Set severity filter (set of allowed severities)."""
        self._severity_filter = severities
        self.invalidateFilter()
    
    def set_hide_acknowledged(self, hide: bool):
        """Set whether to hide acknowledged alerts."""
        self._hide_acknowledged = hide
        self.invalidateFilter()
    
    def clear_filters(self):
        """Clear all filters except date range."""
        self._symbol_filter = ""
        self._type_filter = ""
        self._severity_filter = set()
        self._hide_acknowledged = False
        self.invalidateFilter()
    
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        
        # Get alert data
        alert = model.get_alert_data(source_row)
        if not alert:
            return False
        
        # Date filter
        alert_time = alert.get('alert_time')
        if alert_time and self._from_datetime and self._to_datetime:
            if isinstance(alert_time, str):
                try:
                    alert_time = datetime.fromisoformat(alert_time.replace('Z', '+00:00'))
                except ValueError:
                    pass
            
            if isinstance(alert_time, datetime):
                if alert_time < self._from_datetime or alert_time > self._to_datetime:
                    return False
        
        # Symbol filter
        if self._symbol_filter:
            symbol = alert.get('symbol', '')
            if self._symbol_filter not in symbol.upper():
                return False
        
        # Type filter
        if self._type_filter:
            alert_type = alert.get('alert_type', '')
            alert_subtype = alert.get('alert_subtype', '')
            combined = f"{alert_type} {alert_subtype}".lower()
            if self._type_filter not in combined:
                return False
        
        # Severity filter
        if self._severity_filter:
            severity = alert.get('severity', 'info')
            if severity not in self._severity_filter:
                return False
        
        # Hide acknowledged
        if self._hide_acknowledged and alert.get('acknowledged'):
            return False
        
        return True


class GlobalAlertWindow(QDialog):
    """
    Global alert monitor window showing all alerts with advanced filtering.
    Singleton pattern - only one instance at a time.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls, parent=None, db_session_factory=None, alert_service=None, config=None):
        """Get or create the singleton instance."""
        if cls._instance is None or not cls._instance.isVisible():
            cls._instance = cls(parent, db_session_factory, alert_service, config)
        return cls._instance
    
    def __init__(self, parent=None, db_session_factory=None, alert_service=None, config=None):
        super().__init__(parent)
        self.db_session_factory = db_session_factory
        self.alert_service = alert_service
        self.config = config or {}
        
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        
        self._setup_ui()
        self._load_alerts()
        
        # Auto-refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._load_alerts)
        self.refresh_timer.start(30000)  # 30 seconds
    
    def _setup_ui(self):
        self.setWindowTitle("Alert Monitor")
        self.setMinimumSize(1000, 600)
        self.resize(1200, 700)
        
        # Styling
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D30;
            }
            QLabel {
                color: #E0E0E0;
            }
            QGroupBox {
                background-color: #383838;
                border: 1px solid #4A4A4D;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                color: #E0E0E0;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit, QComboBox, QSpinBox, QDateTimeEdit {
                background-color: #3C3C3F;
                border: 1px solid #4A4A4D;
                border-radius: 3px;
                padding: 4px;
                color: #E0E0E0;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus {
                border: 1px solid #0078D4;
            }
            QPushButton {
                background-color: #3C3C3F;
                border: 1px solid #4A4A4D;
                border-radius: 3px;
                padding: 6px 12px;
                color: #E0E0E0;
            }
            QPushButton:hover {
                background-color: #4A4A4D;
                border: 1px solid #0078D4;
            }
            QRadioButton, QCheckBox {
                color: #E0E0E0;
            }
            QRadioButton::indicator, QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("🔔 Alert Monitor")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(14)
        title.setFont(title_font)
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        self.count_label = QLabel("0 alerts")
        self.count_label.setStyleSheet("color: #AAAAAA; font-style: italic;")
        header_layout.addWidget(self.count_label)
        
        layout.addLayout(header_layout)
        
        # Date/Time Filter
        self.date_filter = DateRangeFilterWidget()
        self.date_filter.filter_changed.connect(self._on_filter_changed)
        layout.addWidget(self.date_filter)
        
        # Additional Filters
        filter_group = QGroupBox("Additional Filters")
        filter_layout = QHBoxLayout()
        
        # Symbol filter
        filter_layout.addWidget(QLabel("Symbol:"))
        self.symbol_filter = QLineEdit()
        self.symbol_filter.setPlaceholderText("e.g., AAPL")
        self.symbol_filter.setMaximumWidth(100)
        self.symbol_filter.textChanged.connect(self._on_symbol_filter_changed)
        filter_layout.addWidget(self.symbol_filter)
        
        # Type filter
        filter_layout.addWidget(QLabel("Type:"))
        self.type_filter = QLineEdit()
        self.type_filter.setPlaceholderText("e.g., breakout")
        self.type_filter.setMaximumWidth(120)
        self.type_filter.textChanged.connect(self._on_type_filter_changed)
        filter_layout.addWidget(self.type_filter)
        
        # Severity checkboxes
        filter_layout.addWidget(QLabel("Severity:"))
        self.severity_checks = {}
        for severity in ['critical', 'high', 'medium', 'low', 'info']:
            cb = QCheckBox(severity.capitalize())
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_severity_filter_changed)
            self.severity_checks[severity] = cb
            filter_layout.addWidget(cb)
        
        filter_layout.addStretch()
        
        # Hide acknowledged
        self.hide_ack_check = QCheckBox("Hide Acknowledged")
        self.hide_ack_check.stateChanged.connect(self._on_hide_ack_changed)
        filter_layout.addWidget(self.hide_ack_check)
        
        # Clear filters button
        clear_btn = QPushButton("Clear Filters")
        clear_btn.clicked.connect(self._clear_filters)
        filter_layout.addWidget(clear_btn)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        # Table model and proxy
        self.table_model = AlertTableModel()
        self.proxy_model = AlertFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        
        # Table view
        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        
        # Column widths
        header = self.table_view.horizontalHeader()
        header.resizeSection(0, 100)  # Time
        header.resizeSection(1, 70)   # Symbol
        header.resizeSection(2, 100)  # Type
        header.resizeSection(3, 90)   # Subtype
        header.resizeSection(4, 80)   # Price
        header.resizeSection(5, 70)   # P&L %
        header.resizeSection(6, 70)   # Severity
        header.resizeSection(7, 40)   # Ack
        
        # Table styling
        self.table_view.setStyleSheet("""
            QTableView {
                background-color: #2D2D30;
                alternate-background-color: #363638;
                gridline-color: #4A4A4D;
                selection-background-color: #0078D4;
                color: #E0E0E0;
            }
            QTableView::item {
                padding: 4px;
            }
            QTableView::item:selected {
                background-color: #0078D4;
                color: white;
            }
            QHeaderView::section {
                background-color: #3C3C3F;
                color: #FFFFFF;
                padding: 6px;
                border: none;
                border-right: 1px solid #4A4A4D;
                border-bottom: 1px solid #4A4A4D;
                font-weight: bold;
            }
        """)
        
        # Double-click to show details
        self.table_view.doubleClicked.connect(self._on_alert_double_clicked)
        
        layout.addWidget(self.table_view)
        
        # Bottom buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._load_alerts)
        button_layout.addWidget(refresh_btn)
        
        ack_btn = QPushButton("✓ Acknowledge Selected")
        ack_btn.clicked.connect(self._acknowledge_selected)
        button_layout.addWidget(ack_btn)
        
        ack_all_btn = QPushButton("✓ Acknowledge All Visible")
        ack_all_btn.clicked.connect(self._acknowledge_all_visible)
        button_layout.addWidget(ack_all_btn)
        
        button_layout.addStretch()
        
        export_btn = QPushButton("📊 Export CSV")
        export_btn.clicked.connect(self._export_csv)
        button_layout.addWidget(export_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Status bar
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888888; font-style: italic;")
        layout.addWidget(self.status_label)
    
    def _load_alerts(self):
        """Load alerts from database with current date filter."""
        try:
            if not self.alert_service:
                return
            
            from_dt, to_dt = self.date_filter.get_date_range()
            
            # Calculate hours for the query
            delta = to_dt - from_dt
            hours = max(1, int(delta.total_seconds() / 3600) + 1)
            
            # Fetch alerts
            alerts = self.alert_service.get_recent_alerts(
                hours=hours,
                limit=5000
            )
            
            # Convert to list of dicts matching Alert model schema
            alert_data = []
            for alert in alerts:
                # Compute severity from alert_type and subtype
                severity = 'info'
                if hasattr(self.alert_service, 'get_alert_severity'):
                    severity = self.alert_service.get_alert_severity(
                        getattr(alert, 'alert_type', '') or '',
                        getattr(alert, 'alert_subtype', '') or ''
                    )
                
                data = {
                    'id': getattr(alert, 'id', None),
                    'alert_time': getattr(alert, 'alert_time', None),
                    'symbol': getattr(alert, 'symbol', ''),
                    'alert_type': getattr(alert, 'alert_type', ''),
                    'alert_subtype': getattr(alert, 'alert_subtype', ''),
                    'price': getattr(alert, 'price', None),
                    'pnl_pct': getattr(alert, 'pnl_pct', None),
                    'severity': severity,
                    'acknowledged': getattr(alert, 'acknowledged', False),
                }
                alert_data.append(data)
            
            self.table_model.load_alerts(alert_data)
            
            # Apply date filter to proxy
            self.proxy_model.set_date_range(from_dt, to_dt)
            
            self._update_count()
            self.status_label.setText(f"Showing: {self.date_filter.get_description()} | Last updated: {datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            self.status_label.setText(f"Error loading alerts: {e}")
    
    def _update_count(self):
        """Update the alert count label."""
        visible = self.proxy_model.rowCount()
        total = self.table_model.rowCount()
        if visible == total:
            self.count_label.setText(f"{total} alerts")
        else:
            self.count_label.setText(f"{visible} of {total} alerts")
    
    def _on_filter_changed(self):
        """Handle date filter change."""
        self._load_alerts()
    
    def _on_symbol_filter_changed(self, text: str):
        """Handle symbol filter change."""
        self.proxy_model.set_symbol_filter(text)
        self._update_count()
    
    def _on_type_filter_changed(self, text: str):
        """Handle type filter change."""
        self.proxy_model.set_type_filter(text)
        self._update_count()
    
    def _on_severity_filter_changed(self):
        """Handle severity filter change."""
        selected = {sev for sev, cb in self.severity_checks.items() if cb.isChecked()}
        self.proxy_model.set_severity_filter(selected)
        self._update_count()
    
    def _on_hide_ack_changed(self, state):
        """Handle hide acknowledged checkbox change."""
        self.proxy_model.set_hide_acknowledged(state == Qt.CheckState.Checked.value)
        self._update_count()
    
    def _clear_filters(self):
        """Clear all additional filters (not date)."""
        self.symbol_filter.clear()
        self.type_filter.clear()
        for cb in self.severity_checks.values():
            cb.setChecked(True)
        self.hide_ack_check.setChecked(False)
        self.proxy_model.clear_filters()
        self._update_count()
    
    def _on_alert_double_clicked(self, index: QModelIndex):
        """Show alert details on double-click."""
        source_index = self.proxy_model.mapToSource(index)
        alert = self.table_model.get_alert_data(source_index.row())
        if alert:
            price_str = f"${alert.get('price', 0):.2f}" if alert.get('price') else "N/A"
            pnl_str = f"{alert.get('pnl_pct', 0):+.1f}%" if alert.get('pnl_pct') is not None else "N/A"
            
            msg = f"""
Symbol: {alert.get('symbol', 'N/A')}
Type: {alert.get('alert_type', 'N/A')}
Subtype: {alert.get('alert_subtype', 'N/A')}
Time: {alert.get('alert_time', 'N/A')}
Price: {price_str}
P&L: {pnl_str}
Severity: {alert.get('severity', 'N/A')}
Acknowledged: {'Yes' if alert.get('acknowledged') else 'No'}
            """
            QMessageBox.information(self, "Alert Details", msg.strip())
    
    def _acknowledge_selected(self):
        """Acknowledge the selected alert."""
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return
        
        source_index = self.proxy_model.mapToSource(indexes[0])
        alert = self.table_model.get_alert_data(source_index.row())
        
        if alert and self.alert_service:
            alert_id = alert.get('id')
            if alert_id:
                try:
                    self.alert_service.acknowledge_alert(alert_id)
                    self._load_alerts()
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to acknowledge: {e}")
    
    def _acknowledge_all_visible(self):
        """Acknowledge all visible alerts."""
        if not self.alert_service:
            return
        
        count = self.proxy_model.rowCount()
        if count == 0:
            return
        
        reply = QMessageBox.question(
            self, "Confirm",
            f"Acknowledge all {count} visible alerts?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for row in range(count):
                source_index = self.proxy_model.mapToSource(self.proxy_model.index(row, 0))
                alert = self.table_model.get_alert_data(source_index.row())
                if alert:
                    alert_id = alert.get('id')
                    if alert_id and not alert.get('acknowledged'):
                        try:
                            self.alert_service.acknowledge_alert(alert_id)
                        except:
                            pass
            
            self._load_alerts()
    
    def _export_csv(self):
        """Export visible alerts to CSV."""
        from PyQt6.QtWidgets import QFileDialog
        import csv
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Alerts", "alerts.csv", "CSV Files (*.csv)"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                headers = [col[1] for col in AlertTableModel.COLUMNS]
                writer.writerow(headers)
                
                for row in range(self.proxy_model.rowCount()):
                    row_data = []
                    for col in range(self.proxy_model.columnCount()):
                        index = self.proxy_model.index(row, col)
                        value = self.proxy_model.data(index, Qt.ItemDataRole.DisplayRole)
                        row_data.append(value if value else "")
                    writer.writerow(row_data)
            
            QMessageBox.information(
                self, "Export Complete",
                f"Exported {self.proxy_model.rowCount()} alerts to:\n{filename}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")
    
    def closeEvent(self, event):
        """Stop timer on close."""
        self.refresh_timer.stop()
        event.accept()


class PositionAlertDialog(QDialog):
    """Dialog showing alerts for a specific position/symbol."""
    
    alert_acknowledged = pyqtSignal(int)  # Emits alert_id when acknowledged
    
    def __init__(self, symbol: str, alerts: List[Any], parent=None, 
                 alert_service=None, db_session_factory=None):
        super().__init__(parent)
        self.symbol = symbol
        self.alerts = alerts
        self.alert_service = alert_service
        self.db_session_factory = db_session_factory
        
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        
        self.setWindowTitle(f"Alerts for {symbol}")
        self.setMinimumSize(900, 550)
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Styling
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D30;
            }
            QLabel {
                color: #E0E0E0;
            }
            QTableView {
                background-color: #2D2D30;
                alternate-background-color: #363638;
                gridline-color: #4A4A4D;
                selection-background-color: #0078D4;
                color: #E0E0E0;
            }
            QTableView::item {
                padding: 4px;
            }
            QHeaderView::section {
                background-color: #3C3C3F;
                color: #FFFFFF;
                padding: 6px;
                border: none;
                border-right: 1px solid #4A4A4D;
                font-weight: bold;
            }
            QPushButton {
                background-color: #3C3C3F;
                border: 1px solid #4A4A4D;
                border-radius: 3px;
                padding: 6px 12px;
                color: #E0E0E0;
            }
            QPushButton:hover {
                background-color: #4A4A4D;
                border: 1px solid #0078D4;
            }
        """)
        
        # Header
        header_layout = QHBoxLayout()
        header = QLabel(f"📊 Alert History: {self.symbol}")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        header.setFont(header_font)
        header_layout.addWidget(header)
        
        header_layout.addStretch()
        
        self.count_label = QLabel(f"{len(self.alerts)} alerts")
        self.count_label.setStyleSheet("color: #AAAAAA;")
        header_layout.addWidget(self.count_label)
        
        layout.addLayout(header_layout)
        
        # Convert alerts to dicts matching Alert model schema
        alert_data = []
        for alert in self.alerts:
            # Compute severity from alert_type and subtype if alert_service available
            severity = 'info'
            if self.alert_service and hasattr(self.alert_service, 'get_alert_severity'):
                severity = self.alert_service.get_alert_severity(
                    getattr(alert, 'alert_type', '') or '',
                    getattr(alert, 'alert_subtype', '') or ''
                )
            
            data = {
                'id': getattr(alert, 'id', None),
                'alert_time': getattr(alert, 'alert_time', None),
                'symbol': getattr(alert, 'symbol', ''),
                'alert_type': getattr(alert, 'alert_type', ''),
                'alert_subtype': getattr(alert, 'alert_subtype', ''),
                'price': getattr(alert, 'price', None),
                'pnl_pct': getattr(alert, 'pnl_pct', None),
                'severity': severity,
                'acknowledged': getattr(alert, 'acknowledged', False),
            }
            alert_data.append(data)
        
        # Table
        self.table_model = AlertTableModel()
        self.table_model.load_alerts(alert_data)
        
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setVisible(False)
        
        # Column widths
        header = self.table_view.horizontalHeader()
        header.resizeSection(0, 100)  # Time
        header.resizeSection(1, 60)   # Symbol
        header.resizeSection(2, 100)  # Type
        header.resizeSection(3, 90)   # Subtype
        header.resizeSection(4, 80)   # Price
        header.resizeSection(5, 70)   # P&L %
        header.resizeSection(6, 70)   # Severity
        header.resizeSection(7, 40)   # Ack
        
        # Double-click for details
        self.table_view.doubleClicked.connect(self._on_alert_double_clicked)
        
        layout.addWidget(self.table_view)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        if self.alert_service:
            ack_btn = QPushButton("✓ Acknowledge Selected")
            ack_btn.clicked.connect(self._acknowledge_selected)
            button_layout.addWidget(ack_btn)
            
            ack_all_btn = QPushButton("✓ Acknowledge All")
            ack_all_btn.clicked.connect(self._acknowledge_all)
            button_layout.addWidget(ack_all_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _on_alert_double_clicked(self, index: QModelIndex):
        """Show alert details on double-click."""
        alert = self.table_model.get_alert_data(index.row())
        if alert:
            price_str = f"${alert.get('price', 0):.2f}" if alert.get('price') else "N/A"
            pnl_str = f"{alert.get('pnl_pct', 0):+.1f}%" if alert.get('pnl_pct') is not None else "N/A"
            
            msg = f"""
Symbol: {alert.get('symbol', 'N/A')}
Type: {alert.get('alert_type', 'N/A')}
Subtype: {alert.get('alert_subtype', 'N/A')}
Time: {alert.get('alert_time', 'N/A')}
Price: {price_str}
P&L: {pnl_str}
Severity: {alert.get('severity', 'N/A')}
Acknowledged: {'Yes' if alert.get('acknowledged') else 'No'}
            """
            QMessageBox.information(self, "Alert Details", msg.strip())
    
    def _acknowledge_selected(self):
        """Acknowledge the selected alert."""
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            return
        
        alert = self.table_model.get_alert_data(indexes[0].row())
        if alert and self.alert_service:
            alert_id = alert.get('id')
            if alert_id:
                try:
                    self.alert_service.acknowledge_alert(alert_id)
                    self.alert_acknowledged.emit(alert_id)
                    # Reload to show updated status
                    self._reload_alerts()
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to acknowledge: {e}")
    
    def _acknowledge_all(self):
        """Acknowledge all alerts for this symbol."""
        if not self.alert_service:
            return
        
        reply = QMessageBox.question(
            self, "Confirm",
            f"Acknowledge all {len(self.alerts)} alerts for {self.symbol}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for alert in self.alerts:
                alert_id = getattr(alert, 'id', None)
                if alert_id and not getattr(alert, 'acknowledged', False):
                    try:
                        self.alert_service.acknowledge_alert(alert_id)
                        self.alert_acknowledged.emit(alert_id)
                    except:
                        pass
            
            self._reload_alerts()
    
    def _reload_alerts(self):
        """Reload alerts from database."""
        if self.alert_service:
            try:
                self.alerts = self.alert_service.get_recent_alerts(
                    symbol=self.symbol,
                    hours=24 * 90,
                    limit=500
                )
                
                alert_data = []
                for alert in self.alerts:
                    # Compute severity
                    severity = 'info'
                    if hasattr(self.alert_service, 'get_alert_severity'):
                        severity = self.alert_service.get_alert_severity(
                            getattr(alert, 'alert_type', '') or '',
                            getattr(alert, 'alert_subtype', '') or ''
                        )
                    
                    data = {
                        'id': getattr(alert, 'id', None),
                        'alert_time': getattr(alert, 'alert_time', None),
                        'symbol': getattr(alert, 'symbol', ''),
                        'alert_type': getattr(alert, 'alert_type', ''),
                        'alert_subtype': getattr(alert, 'alert_subtype', ''),
                        'price': getattr(alert, 'price', None),
                        'pnl_pct': getattr(alert, 'pnl_pct', None),
                        'severity': severity,
                        'acknowledged': getattr(alert, 'acknowledged', False),
                    }
                    alert_data.append(data)
                
                self.table_model.load_alerts(alert_data)
                self.count_label.setText(f"{len(self.alerts)} alerts")
            except Exception as e:
                pass  # Silent fail on reload
