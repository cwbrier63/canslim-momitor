"""
CANSLIM Monitor - Alert Table Widget
=====================================
Reusable sortable, filterable table for displaying alerts.

Features:
- Sortable columns (click header to toggle asc/desc)
- Filterable by alert type (multi-select dropdown)
- Color-coded rows by severity
- Double-click row emits signal for detail view
- New alert highlight effect
- Right-click header to show/hide columns
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set
from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMenu, QWidgetAction, QCheckBox, QVBoxLayout, QWidget, QPushButton,
    QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSettings
from PyQt6.QtGui import QColor, QBrush, QFont, QAction

from canslim_monitor.services.alert_service import AlertService


class AlertTableWidget(QTableWidget):
    """
    Reusable alert table with sorting, filtering, and severity coloring.
    
    Signals:
        alert_double_clicked(dict): Emitted when a row is double-clicked, passes alert data
        alert_selected(dict): Emitted when a row is single-clicked
    """
    
    alert_double_clicked = pyqtSignal(dict)
    alert_selected = pyqtSignal(dict)
    
    # Column definitions: (key, header, width, default_visible)
    ALL_COLUMNS = [
        ('time', 'Time', 100, True),
        ('symbol', 'Symbol', 70, True),
        ('type', 'Type', 90, True),
        ('subtype', 'Subtype', 100, True),
        ('price', 'Price', 75, True),
        ('pnl_pct', 'P&L%', 65, True),
        ('severity', 'Severity', 70, False),
        ('acknowledged', 'Ack', 40, True),
        ('health_rating', 'Health', 55, False),
        ('grade', 'Grade', 50, False),
        ('score', 'Score', 50, False),
        ('market_regime', 'Market', 90, False),
        ('volume_ratio', 'Vol Ratio', 70, False),
        ('pivot', 'Pivot', 75, False),
        ('avg_cost', 'Avg Cost', 75, False),
        ('ma21', 'MA21', 70, False),
        ('ma50', 'MA50', 70, False),
    ]
    
    # Severity colors
    SEVERITY_COLORS = {
        'critical': {'bg': '#FFEBEE', 'fg': '#C62828'},  # Light red
        'warning': {'bg': '#FFF8E1', 'fg': '#F57F17'},   # Light amber
        'profit': {'bg': '#E8F5E9', 'fg': '#2E7D32'},    # Light green
        'info': {'bg': '#E3F2FD', 'fg': '#1565C0'},      # Light blue
        'neutral': {'bg': '#FFFFFF', 'fg': '#000000'},   # White
    }
    
    # Highlight color for new alerts
    HIGHLIGHT_COLOR = '#FFFDE7'  # Light yellow
    
    def __init__(self, parent=None, show_symbol_column: bool = True):
        """
        Initialize the alert table.
        
        Args:
            parent: Parent widget
            show_symbol_column: Whether to show symbol column (False for single-symbol view)
        """
        super().__init__(parent)
        
        self.show_symbol_column = show_symbol_column
        self._all_alerts: List[Dict[str, Any]] = []
        self._filtered_alerts: List[Dict[str, Any]] = []
        self._active_type_filters: Set[str] = set()  # Empty = show all
        self._highlighted_rows: Dict[int, QTimer] = {}  # alert_id -> timer
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.DescendingOrder
        
        # Column visibility - load from settings or use defaults
        self._visible_columns: Set[str] = self._load_column_visibility()
        
        self._setup_table()
        self._setup_signals()
    
    def _load_column_visibility(self) -> Set[str]:
        """Load column visibility from settings or use defaults."""
        settings = QSettings('CANSLIM', 'AlertTable')
        saved = settings.value('visible_columns', None)
        
        if saved:
            return set(saved)
        
        # Default visibility
        visible = set()
        for key, _, _, default_visible in self.ALL_COLUMNS:
            if default_visible:
                visible.add(key)
        return visible
    
    def _save_column_visibility(self):
        """Save column visibility to settings."""
        settings = QSettings('CANSLIM', 'AlertTable')
        settings.setValue('visible_columns', list(self._visible_columns))
    
    def _get_visible_columns(self) -> List[tuple]:
        """Get list of currently visible columns."""
        columns = []
        for col_def in self.ALL_COLUMNS:
            key = col_def[0]
            # Skip symbol column if not showing
            if key == 'symbol' and not self.show_symbol_column:
                continue
            if key in self._visible_columns:
                columns.append(col_def)
        return columns
    
    def _setup_table(self):
        """Configure table appearance and behavior."""
        columns = self._get_visible_columns()
        
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels([c[1] for c in columns])
        
        # Set column widths
        for i, (_, _, width, _) in enumerate(columns):
            self.setColumnWidth(i, width)
        
        # Table settings
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(False)  # We use severity colors instead
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)
        
        # Header settings
        header = self.horizontalHeader()
        header.setSectionsClickable(True)
        header.setStretchLastSection(True)
        header.setSortIndicatorShown(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)
        
        # Style
        self.setStyleSheet("""
            QTableWidget {
                border: 1px solid #ddd;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #1976D2;
                color: white;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #ddd;
                border-right: 1px solid #ddd;
                font-weight: bold;
            }
        """)
    
    def _setup_signals(self):
        """Connect internal signals."""
        self.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.cellDoubleClicked.connect(self._on_double_click)
        self.cellClicked.connect(self._on_single_click)
    
    def _show_column_menu(self, pos):
        """Show context menu for column visibility."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #ccc;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #e0e0e0;
            }
        """)
        
        # Add checkbox for each column
        for key, header, _, _ in self.ALL_COLUMNS:
            # Skip symbol if not showing
            if key == 'symbol' and not self.show_symbol_column:
                continue
            
            action = QAction(header, menu)
            action.setCheckable(True)
            action.setChecked(key in self._visible_columns)
            action.triggered.connect(lambda checked, k=key: self._toggle_column(k, checked))
            menu.addAction(action)
        
        menu.addSeparator()
        
        # Show all / Hide optional
        show_all_action = menu.addAction("Show All Columns")
        show_all_action.triggered.connect(self._show_all_columns)
        
        reset_action = menu.addAction("Reset to Defaults")
        reset_action.triggered.connect(self._reset_columns)
        
        menu.exec(self.horizontalHeader().mapToGlobal(pos))
    
    def _toggle_column(self, key: str, visible: bool):
        """Toggle column visibility."""
        if visible:
            self._visible_columns.add(key)
        else:
            # Don't allow hiding all columns
            if len(self._visible_columns) > 1:
                self._visible_columns.discard(key)
        
        self._save_column_visibility()
        self._rebuild_table()
    
    def _show_all_columns(self):
        """Show all available columns."""
        for key, _, _, _ in self.ALL_COLUMNS:
            if key == 'symbol' and not self.show_symbol_column:
                continue
            self._visible_columns.add(key)
        
        self._save_column_visibility()
        self._rebuild_table()
    
    def _reset_columns(self):
        """Reset to default column visibility."""
        self._visible_columns.clear()
        for key, _, _, default_visible in self.ALL_COLUMNS:
            if default_visible:
                self._visible_columns.add(key)
        
        self._save_column_visibility()
        self._rebuild_table()
    
    def _rebuild_table(self):
        """Rebuild table with current column visibility."""
        columns = self._get_visible_columns()
        
        self.clear()
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels([c[1] for c in columns])
        
        for i, (_, _, width, _) in enumerate(columns):
            self.setColumnWidth(i, width)
        
        # Re-populate with current data
        self._populate_table()
    
    def _on_header_clicked(self, column: int):
        """Handle column header click for sorting."""
        if column == self._sort_column:
            # Toggle sort order
            if self._sort_order == Qt.SortOrder.AscendingOrder:
                self._sort_order = Qt.SortOrder.DescendingOrder
            else:
                self._sort_order = Qt.SortOrder.AscendingOrder
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.DescendingOrder  # Default desc for new column
        
        self._apply_sort()
        self.horizontalHeader().setSortIndicator(column, self._sort_order)
    
    def _apply_sort(self):
        """Sort the filtered alerts and refresh display."""
        if not self._filtered_alerts:
            return
        
        # Map column index to data key
        columns = self._get_visible_columns()
        if self._sort_column >= len(columns):
            self._sort_column = 0
        sort_key = columns[self._sort_column][0]
        
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        
        # Sort with appropriate key function
        def get_sort_value(alert):
            val = self._get_raw_value(sort_key, alert)
            if sort_key == 'time':
                if isinstance(val, str):
                    try:
                        return datetime.fromisoformat(val.replace('Z', '+00:00'))
                    except:
                        return datetime.min
                elif isinstance(val, datetime):
                    return val
                return datetime.min
            elif sort_key in ('price', 'pnl_pct', 'volume_ratio', 'pivot', 'avg_cost', 'ma21', 'ma50', 'score'):
                return val if val is not None else 0.0
            elif sort_key == 'acknowledged':
                return 1 if val else 0
            else:
                return str(val) if val else ''
        
        self._filtered_alerts.sort(key=get_sort_value, reverse=reverse)
        self._populate_table()
    
    def _on_double_click(self, row: int, column: int):
        """Handle double-click on a row."""
        if 0 <= row < len(self._filtered_alerts):
            alert = self._filtered_alerts[row]
            self.alert_double_clicked.emit(alert)
    
    def _on_single_click(self, row: int, column: int):
        """Handle single-click on a row."""
        if 0 <= row < len(self._filtered_alerts):
            alert = self._filtered_alerts[row]
            self.alert_selected.emit(alert)
    
    def set_alerts(self, alerts: List[Dict[str, Any]], highlight_new: bool = False):
        """
        Set the alerts to display.
        
        Args:
            alerts: List of alert dictionaries
            highlight_new: If True, highlight alerts not previously shown
        """
        old_ids = {a.get('id') for a in self._all_alerts}
        new_ids = {a.get('id') for a in alerts if a.get('id') not in old_ids}
        
        self._all_alerts = alerts
        self._apply_filter()
        
        if highlight_new and new_ids:
            self._highlight_new_alerts(new_ids)
    
    def _apply_filter(self):
        """Apply current type filter to alerts."""
        if not self._active_type_filters:
            # No filter = show all
            self._filtered_alerts = list(self._all_alerts)
        else:
            self._filtered_alerts = [
                a for a in self._all_alerts 
                if a.get('alert_type') in self._active_type_filters
            ]
        
        self._apply_sort()
    
    def _populate_table(self):
        """Populate table with filtered/sorted alerts."""
        self.setRowCount(len(self._filtered_alerts))
        
        columns = self._get_visible_columns()
        
        for row, alert in enumerate(self._filtered_alerts):
            severity = alert.get('severity', 'neutral')
            colors = self.SEVERITY_COLORS.get(severity, self.SEVERITY_COLORS['neutral'])
            bg_color = QColor(colors['bg'])
            fg_color = QColor(colors['fg'])
            
            for col, (key, _, _, _) in enumerate(columns):
                value = self._format_value(key, alert)
                item = QTableWidgetItem(value)
                item.setBackground(QBrush(bg_color))
                item.setForeground(QBrush(fg_color))
                
                # Right-align numeric columns
                if key in ('price', 'pnl_pct', 'volume_ratio', 'pivot', 'avg_cost', 'ma21', 'ma50', 'score'):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif key in ('acknowledged', 'severity', 'health_rating', 'grade'):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                
                # Bold for critical/profit
                if severity in ('critical', 'profit'):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                
                self.setItem(row, col, item)
    
    def _get_raw_value(self, key: str, alert: Dict[str, Any]) -> Any:
        """Get raw value for a column key."""
        if key == 'time':
            return alert.get('alert_time')
        elif key == 'symbol':
            return alert.get('symbol')
        elif key == 'type':
            return alert.get('alert_type')
        elif key == 'subtype':
            return alert.get('subtype')
        elif key == 'price':
            return alert.get('price')
        elif key == 'pnl_pct':
            return alert.get('pnl_pct_at_alert')
        elif key == 'severity':
            return alert.get('severity')
        elif key == 'acknowledged':
            return alert.get('acknowledged')
        elif key == 'health_rating':
            return alert.get('health_rating')
        elif key == 'grade':
            return alert.get('grade')
        elif key == 'score':
            return alert.get('score')
        elif key == 'market_regime':
            return alert.get('market_regime')
        elif key == 'volume_ratio':
            return alert.get('volume_ratio')
        elif key == 'pivot':
            return alert.get('pivot_at_alert')
        elif key == 'avg_cost':
            return alert.get('avg_cost_at_alert')
        elif key == 'ma21':
            return alert.get('ma21')
        elif key == 'ma50':
            return alert.get('ma50')
        return alert.get(key)
    
    def _format_value(self, key: str, alert: Dict[str, Any]) -> str:
        """Format a value for display."""
        val = self._get_raw_value(key, alert)
        
        if key == 'time':
            if isinstance(val, str):
                try:
                    dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
                    return dt.strftime('%m/%d %H:%M')
                except:
                    return val[:16] if val else ''
            elif isinstance(val, datetime):
                return val.strftime('%m/%d %H:%M')
            return ''
        
        elif key == 'symbol':
            return val or ''
        
        elif key == 'type':
            return val or ''
        
        elif key == 'subtype':
            return val or ''
        
        elif key == 'price':
            return f"${val:.2f}" if val else ''
        
        elif key == 'pnl_pct':
            if val is not None:
                return f"{val:+.1f}%"
            return ''
        
        elif key == 'severity':
            return (val or '').capitalize()
        
        elif key == 'acknowledged':
            return '✓' if val else ''
        
        elif key == 'health_rating':
            return val or ''
        
        elif key == 'grade':
            return val or ''
        
        elif key == 'score':
            return f"{val:.0f}" if val is not None else ''
        
        elif key == 'market_regime':
            # Shorten long regime names
            regime = val or ''
            if regime == 'CONFIRMED_UPTREND':
                return 'CONF UP'
            elif regime == 'UPTREND_UNDER_PRESSURE':
                return 'PRESSURE'
            elif regime == 'MARKET_IN_CORRECTION':
                return 'CORRECT'
            elif regime == 'DOWNTREND':
                return 'DOWN'
            elif regime == 'RALLY_ATTEMPT':
                return 'RALLY'
            return regime[:10] if len(regime) > 10 else regime
        
        elif key == 'volume_ratio':
            return f"{val:.1f}x" if val is not None else ''
        
        elif key in ('pivot', 'avg_cost', 'ma21', 'ma50'):
            return f"${val:.2f}" if val else ''
        
        return str(val) if val else ''
    
    def _highlight_new_alerts(self, alert_ids: Set[int]):
        """Highlight newly arrived alerts for a few seconds."""
        highlight_color = QColor(self.HIGHLIGHT_COLOR)
        
        for row, alert in enumerate(self._filtered_alerts):
            if alert.get('id') in alert_ids:
                # Set highlight
                for col in range(self.columnCount()):
                    item = self.item(row, col)
                    if item:
                        item.setBackground(QBrush(highlight_color))
                
                # Set timer to remove highlight
                alert_id = alert.get('id')
                if alert_id in self._highlighted_rows:
                    self._highlighted_rows[alert_id].stop()
                
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(lambda r=row, a=alert: self._remove_highlight(r, a))
                timer.start(5000)  # 5 seconds
                self._highlighted_rows[alert_id] = timer
    
    def _remove_highlight(self, row: int, alert: Dict[str, Any]):
        """Remove highlight from a row, restore severity color."""
        if row >= self.rowCount():
            return
        
        severity = alert.get('severity', 'neutral')
        colors = self.SEVERITY_COLORS.get(severity, self.SEVERITY_COLORS['neutral'])
        bg_color = QColor(colors['bg'])
        
        for col in range(self.columnCount()):
            item = self.item(row, col)
            if item:
                item.setBackground(QBrush(bg_color))
    
    def set_type_filter(self, types: Set[str]):
        """
        Set active type filters.
        
        Args:
            types: Set of alert types to show. Empty set = show all.
        """
        self._active_type_filters = types
        self._apply_filter()
    
    def get_available_types(self) -> Set[str]:
        """Get all unique alert types in current data."""
        return {a.get('alert_type') for a in self._all_alerts if a.get('alert_type')}
    
    def get_selected_alert(self) -> Optional[Dict[str, Any]]:
        """Get the currently selected alert, if any."""
        row = self.currentRow()
        if 0 <= row < len(self._filtered_alerts):
            return self._filtered_alerts[row]
        return None
    
    def get_alert_count(self) -> int:
        """Get total number of alerts (before filtering)."""
        return len(self._all_alerts)
    
    def get_filtered_count(self) -> int:
        """Get number of alerts after filtering."""
        return len(self._filtered_alerts)


class TypeFilterButton(QPushButton):
    """
    Button with dropdown for multi-select type filtering.
    """
    
    filter_changed = pyqtSignal(set)  # Emits set of selected types
    
    def __init__(self, parent=None):
        super().__init__("Type: All ▼", parent)
        self._all_types: Set[str] = set()
        self._selected_types: Set[str] = set()
        self.setMinimumWidth(120)
        self.clicked.connect(self._show_menu)
    
    def set_available_types(self, types: Set[str]):
        """Set the available types for filtering."""
        self._all_types = types
    
    def _show_menu(self):
        """Show the filter dropdown menu."""
        menu = QMenu(self)
        
        # "All" option
        all_action = menu.addAction("✓ All" if not self._selected_types else "  All")
        all_action.triggered.connect(self._select_all)
        
        menu.addSeparator()
        
        # Individual type options
        for type_name in sorted(self._all_types):
            is_selected = type_name in self._selected_types or not self._selected_types
            prefix = "✓ " if is_selected else "  "
            action = menu.addAction(f"{prefix}{type_name}")
            action.triggered.connect(lambda checked, t=type_name: self._toggle_type(t))
        
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
    
    def _select_all(self):
        """Clear filters (show all)."""
        self._selected_types.clear()
        self._update_text()
        self.filter_changed.emit(self._selected_types)
    
    def _toggle_type(self, type_name: str):
        """Toggle a type filter."""
        if not self._selected_types:
            # Currently showing all, switch to showing only this type
            self._selected_types = {type_name}
        elif type_name in self._selected_types:
            self._selected_types.discard(type_name)
            if not self._selected_types:
                # Removed last filter, back to all
                pass
        else:
            self._selected_types.add(type_name)
        
        self._update_text()
        self.filter_changed.emit(self._selected_types)
    
    def _update_text(self):
        """Update button text based on selection."""
        if not self._selected_types:
            self.setText("Type: All ▼")
        elif len(self._selected_types) == 1:
            self.setText(f"Type: {list(self._selected_types)[0]} ▼")
        else:
            self.setText(f"Type: {len(self._selected_types)} selected ▼")


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
    
    app = QApplication(sys.argv)
    
    window = QMainWindow()
    window.setWindowTitle("Alert Table Test")
    window.setGeometry(100, 100, 1000, 400)
    
    central = QWidget()
    layout = QVBoxLayout(central)
    
    # Create table
    table = AlertTableWidget(show_symbol_column=True)
    layout.addWidget(table)
    
    # Add test data
    test_alerts = [
        {'id': 1, 'symbol': 'NVDA', 'alert_type': 'BREAKOUT', 'subtype': 'CONFIRMED',
         'alert_time': '2026-01-18T09:32:00', 'price': 142.50, 'pnl_pct_at_alert': 2.3, 
         'severity': 'info', 'acknowledged': False, 'health_rating': 'A', 'grade': 'A+',
         'score': 85, 'market_regime': 'CONFIRMED_UPTREND', 'volume_ratio': 1.5,
         'pivot_at_alert': 140.00, 'avg_cost_at_alert': 138.50, 'ma21': 139.00, 'ma50': 135.00},
        {'id': 2, 'symbol': 'AMD', 'alert_type': 'STOP', 'subtype': 'WARNING',
         'alert_time': '2026-01-18T09:15:00', 'price': 178.30, 'pnl_pct_at_alert': -5.2, 
         'severity': 'warning', 'acknowledged': True, 'health_rating': 'B', 'grade': 'B',
         'score': 65, 'market_regime': 'UPTREND_UNDER_PRESSURE', 'volume_ratio': 0.8},
        {'id': 3, 'symbol': 'NVDA', 'alert_type': 'PROFIT', 'subtype': 'TP1',
         'alert_time': '2026-01-17T15:58:00', 'price': 152.80, 'pnl_pct_at_alert': 20.1, 
         'severity': 'profit', 'acknowledged': True},
        {'id': 4, 'symbol': 'MSFT', 'alert_type': 'STOP', 'subtype': 'HARD_STOP',
         'alert_time': '2026-01-17T14:30:00', 'price': 410.00, 'pnl_pct_at_alert': -7.5, 
         'severity': 'critical', 'acknowledged': False},
    ]
    
    table.set_alerts(test_alerts)
    
    # Connect signals
    table.alert_double_clicked.connect(lambda a: print(f"Double-clicked: {a['symbol']} - {a['subtype']}"))
    
    window.setCentralWidget(central)
    window.show()
    
    sys.exit(app.exec())
