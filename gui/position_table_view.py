"""
CANSLIM Monitor - Position Table View
Spreadsheet-style view of all positions with Excel-like column filtering and editing.
"""

from datetime import date, datetime
from typing import Optional, Dict, Any, List, Set

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QLabel, QHeaderView, QComboBox, QWidget,
    QAbstractItemView, QMessageBox, QFrame, QGroupBox, QFormLayout,
    QScrollArea, QCheckBox, QListWidget, QListWidgetItem, QMenu,
    QWidgetAction, QSpinBox, QDoubleSpinBox
)
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    pyqtSignal, QTimer, QPoint
)
from PyQt6.QtGui import QFont, QColor, QBrush, QAction

from canslim_monitor.gui.state_config import STATES


# Define column types for filtering behavior
COLUMN_TYPES = {
    'symbol': 'text',
    'portfolio': 'text',
    'state': 'text',
    'pattern': 'text',
    'pivot': 'float',
    'last_price': 'float',
    'dist_from_pivot': 'float',  # Computed: ((last_price - pivot) / pivot) * 100
    'unrealized_pnl': 'float',   # Computed: (last_price - avg_cost) * total_shares
    'unrealized_pct': 'float',   # Computed: ((last_price - avg_cost) / avg_cost) * 100
    'realized_pnl': 'float',     # From DB: Realized P&L $
    'total_pnl': 'float',        # Computed: realized + unrealized
    'rs_rating': 'int',
    'rs_3mo': 'int',
    'rs_6mo': 'int',
    'eps_rating': 'int',
    'comp_rating': 'int',
    'smr_rating': 'text',
    'ad_rating': 'text',
    'industry_rank': 'int',
    'base_stage': 'text',
    'base_depth': 'float',
    'base_length': 'int',
    'fund_count': 'int',
    'funds_qtr_chg': 'int',
    'entry_grade': 'text',
    'entry_score': 'int',
    'watch_date': 'date',
    'breakout_date': 'date',
    'total_shares': 'int',
    'avg_cost': 'float',
}


class TextFilterPopup(QDialog):
    """Popup for filtering text columns with multi-select checkboxes."""
    
    filter_changed = pyqtSignal(set)  # Emits set of selected values
    
    def __init__(self, unique_values: List[str], selected_values: Set[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setMinimumWidth(220)
        self.setMaximumHeight(400)
        
        self.unique_values = sorted([v for v in unique_values if v], key=lambda x: str(x).lower())
        self.selected_values = selected_values or set()
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
                border: 2px solid #0078D4;
                border-radius: 6px;
            }
            QCheckBox {
                color: #333333;
                padding: 4px 8px;
                font-size: 12px;
            }
            QCheckBox:hover {
                background-color: #E8F4FD;
                border-radius: 3px;
            }
            QPushButton {
                background-color: #F0F0F0;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 5px 10px;
                color: #333333;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #E0E0E0;
                border-color: #0078D4;
            }
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px;
                color: #333333;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 2px solid #0078D4;
            }
            QScrollArea {
                border: 1px solid #E0E0E0;
                border-radius: 4px;
            }
        """)
        
        # Title
        title = QLabel("Select Values")
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #333333; padding: 2px;")
        layout.addWidget(title)
        
        # Search box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search...")
        self.search_input.textChanged.connect(self._filter_list)
        layout.addWidget(self.search_input)
        
        # Select All / Clear buttons
        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("✓ Select All")
        select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(select_all_btn)
        
        clear_btn = QPushButton("✗ Clear All")
        clear_btn.clicked.connect(self._clear_all)
        btn_layout.addWidget(clear_btn)
        layout.addLayout(btn_layout)
        
        # Scrollable checkbox list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(220)
        
        self.list_widget = QWidget()
        self.list_widget.setStyleSheet("background-color: #FFFFFF;")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(4, 4, 4, 4)
        self.list_layout.setSpacing(2)
        
        self.checkboxes: Dict[str, QCheckBox] = {}
        all_selected = len(self.selected_values) == 0
        
        for value in self.unique_values:
            cb = QCheckBox(str(value))
            cb.setChecked(all_selected or value in self.selected_values)
            self.checkboxes[value] = cb
            self.list_layout.addWidget(cb)
        
        self.list_layout.addStretch()
        scroll.setWidget(self.list_widget)
        layout.addWidget(scroll)
        
        # Apply button
        apply_btn = QPushButton("Apply Filter")
        apply_btn.clicked.connect(self._apply_filter)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #106EBE;
            }
        """)
        layout.addWidget(apply_btn)
    
    def _filter_list(self, text: str):
        """Filter the checkbox list based on search text."""
        text = text.lower()
        for value, cb in self.checkboxes.items():
            cb.setVisible(text in str(value).lower())
    
    def _select_all(self):
        """Select all visible checkboxes."""
        for cb in self.checkboxes.values():
            if cb.isVisible():
                cb.setChecked(True)
    
    def _clear_all(self):
        """Clear all visible checkboxes."""
        for cb in self.checkboxes.values():
            if cb.isVisible():
                cb.setChecked(False)
    
    def _apply_filter(self):
        """Apply the filter and close."""
        selected = {value for value, cb in self.checkboxes.items() if cb.isChecked()}
        self.filter_changed.emit(selected)
        self.close()


class NumericFilterPopup(QDialog):
    """Popup for filtering numeric columns with comparison operators."""
    
    filter_changed = pyqtSignal(dict)  # Emits {'operator': str, 'value': float, 'value2': float}
    
    def __init__(self, column_type: str = 'float', current_filter: Dict = None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(280)
        
        self.column_type = column_type
        self.current_filter = current_filter or {}
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
                border: 2px solid #0078D4;
                border-radius: 6px;
            }
            QLabel {
                color: #333333;
                font-size: 12px;
            }
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px;
                color: #333333;
                font-size: 12px;
                min-height: 24px;
            }
            QComboBox:focus {
                border: 2px solid #0078D4;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                selection-background-color: #0078D4;
                selection-color: white;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px;
                color: #333333;
                font-size: 12px;
                min-height: 24px;
            }
            QSpinBox:focus, QDoubleSpinBox:focus {
                border: 2px solid #0078D4;
            }
            QPushButton {
                background-color: #F0F0F0;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px 12px;
                color: #333333;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #E0E0E0;
                border-color: #0078D4;
            }
        """)
        
        # Title
        title = QLabel("Numeric Filter")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px;")
        layout.addWidget(title)
        
        # Operator selection
        op_layout = QFormLayout()
        self.operator_combo = QComboBox()
        self.operator_combo.addItems([
            "(No Filter)",
            "=  Equals",
            "≠  Not Equals", 
            ">  Greater Than",
            "≥  Greater or Equal",
            "<  Less Than",
            "≤  Less or Equal",
            "↔  Between"
        ])
        self.operator_combo.currentIndexChanged.connect(self._on_operator_changed)
        op_layout.addRow("Condition:", self.operator_combo)
        layout.addLayout(op_layout)
        
        # Value input(s)
        value_layout = QFormLayout()
        
        if self.column_type == 'int':
            self.value_input = QSpinBox()
            self.value_input.setRange(-999999, 999999)
            self.value2_input = QSpinBox()
            self.value2_input.setRange(-999999, 999999)
        else:
            self.value_input = QDoubleSpinBox()
            self.value_input.setRange(-999999, 999999)
            self.value_input.setDecimals(2)
            self.value2_input = QDoubleSpinBox()
            self.value2_input.setRange(-999999, 999999)
            self.value2_input.setDecimals(2)
        
        value_layout.addRow("Value:", self.value_input)
        
        # Second value for "Between"
        self.value2_label = QLabel("And:")
        value_layout.addRow(self.value2_label, self.value2_input)
        self.value2_label.setVisible(False)
        self.value2_input.setVisible(False)
        
        layout.addLayout(value_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        clear_btn = QPushButton("Clear Filter")
        clear_btn.clicked.connect(self._clear_filter)
        btn_layout.addWidget(clear_btn)
        
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_filter)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106EBE;
            }
        """)
        btn_layout.addWidget(apply_btn)
        layout.addLayout(btn_layout)
        
        # Load current filter
        if self.current_filter:
            op = self.current_filter.get('operator', '')
            operators = ["", "=", "≠", ">", "≥", "<", "≤", "between"]
            if op in operators:
                self.operator_combo.setCurrentIndex(operators.index(op))
            self.value_input.setValue(self.current_filter.get('value', 0))
            self.value2_input.setValue(self.current_filter.get('value2', 0))
            self._on_operator_changed(self.operator_combo.currentIndex())
    
    def _on_operator_changed(self, index: int):
        """Show/hide second value input for 'Between' operator."""
        is_between = index == 7  # "Between" option
        is_no_filter = index == 0
        
        self.value2_label.setVisible(is_between)
        self.value2_input.setVisible(is_between)
        self.value_input.setEnabled(not is_no_filter)
    
    def _clear_filter(self):
        """Clear the filter."""
        self.filter_changed.emit({})
        self.close()
    
    def _apply_filter(self):
        """Apply the filter."""
        operators = ["", "=", "≠", ">", "≥", "<", "≤", "between"]
        op = operators[self.operator_combo.currentIndex()]
        
        if not op:
            self.filter_changed.emit({})
        else:
            result = {
                'operator': op,
                'value': self.value_input.value(),
            }
            if op == 'between':
                result['value2'] = self.value2_input.value()
            self.filter_changed.emit(result)
        
        self.close()


class ColumnFilterButton(QPushButton):
    """Button that shows filter status and opens filter popup."""
    
    filter_changed = pyqtSignal(int, object)  # column_index, filter_value
    
    def __init__(self, column_index: int, column_key: str, column_name: str, parent=None):
        super().__init__(parent)
        self.column_index = column_index
        self.column_key = column_key
        self.column_name = column_name
        self.column_type = COLUMN_TYPES.get(column_key, 'text')
        
        self.current_filter = None
        self.unique_values: List[str] = []
        
        self._update_appearance()
        self.clicked.connect(self._show_popup)
    
    def _update_appearance(self):
        """Update button appearance based on filter state."""
        if self.current_filter:
            self.setText("▼")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #0078D4;
                    color: white;
                    border: none;
                    border-radius: 2px;
                    font-size: 9px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #106EBE;
                }
            """)
            
            # Build tooltip showing active filter
            if isinstance(self.current_filter, set):
                count = len(self.current_filter)
                tip = f"{self.column_name}: {count} value(s) selected"
            elif isinstance(self.current_filter, dict):
                op = self.current_filter.get('operator', '')
                val = self.current_filter.get('value', 0)
                if op == 'between':
                    val2 = self.current_filter.get('value2', 0)
                    tip = f"{self.column_name}: {val} to {val2}"
                else:
                    tip = f"{self.column_name}: {op} {val}"
            else:
                tip = f"{self.column_name}: Filter active"
            self.setToolTip(tip)
        else:
            self.setText("▼")
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #888888;
                    border: none;
                    font-size: 9px;
                }
                QPushButton:hover {
                    background-color: #E0E0E0;
                    color: #333333;
                    border-radius: 2px;
                }
            """)
            self.setToolTip(f"Filter {self.column_name}")
    
    def set_unique_values(self, values: List[str]):
        """Set the unique values for text filter popup."""
        self.unique_values = values
    
    def _show_popup(self):
        """Show the appropriate filter popup."""
        if self.column_type in ('int', 'float'):
            popup = NumericFilterPopup(
                self.column_type, 
                self.current_filter if isinstance(self.current_filter, dict) else None,
                self
            )
            popup.filter_changed.connect(self._on_numeric_filter)
        else:
            # Text filter
            selected = self.current_filter if isinstance(self.current_filter, set) else set()
            popup = TextFilterPopup(
                self.unique_values,
                selected,
                self
            )
            popup.filter_changed.connect(self._on_text_filter)
        
        # Position popup below the button
        pos = self.mapToGlobal(QPoint(0, self.height()))
        popup.move(pos)
        popup.show()
    
    def _on_text_filter(self, selected_values: Set[str]):
        """Handle text filter selection."""
        if len(selected_values) == len(self.unique_values) or len(selected_values) == 0:
            self.current_filter = None
        else:
            self.current_filter = selected_values
        
        self._update_appearance()
        self.filter_changed.emit(self.column_index, self.current_filter)
    
    def _on_numeric_filter(self, filter_dict: Dict):
        """Handle numeric filter selection."""
        if not filter_dict:
            self.current_filter = None
        else:
            self.current_filter = filter_dict
        
        self._update_appearance()
        self.filter_changed.emit(self.column_index, self.current_filter)
    
    def clear_filter(self):
        """Clear the filter."""
        self.current_filter = None
        self._update_appearance()


class PositionTableModel(QAbstractTableModel):
    """Table model for displaying positions in a spreadsheet view."""
    
    COLUMNS = [
        ('symbol', 'Symbol'),
        ('portfolio', 'Portfolio'),
        ('state', 'State'),
        ('pattern', 'Pattern'),
        ('pivot', 'Pivot'),
        ('last_price', 'Last Price'),
        ('dist_from_pivot', 'Dist %'),      # Computed: distance from pivot
        ('unrealized_pct', 'Unreal %'),     # Computed: unrealized P&L %
        ('unrealized_pnl', 'Unreal $'),     # Computed: unrealized P&L $
        ('realized_pnl', 'Real $'),         # From DB: realized P&L $
        ('total_pnl', 'Total $'),           # Computed: realized + unrealized
        ('rs_rating', 'RS'),
        ('rs_3mo', 'RS 3M'),
        ('rs_6mo', 'RS 6M'),
        ('eps_rating', 'EPS'),
        ('comp_rating', 'Comp'),
        ('smr_rating', 'SMR'),
        ('ad_rating', 'A/D'),
        ('industry_rank', 'Ind Rank'),
        ('base_stage', 'Stage'),
        ('base_depth', 'Depth %'),
        ('base_length', 'Length'),
        ('fund_count', 'Funds'),
        ('funds_qtr_chg', 'Funds Chg'),
        ('entry_grade', 'Grade'),
        ('entry_score', 'Score'),
        ('watch_date', 'Watch Date'),
        ('breakout_date', 'Breakout'),
        ('total_shares', 'Shares'),
        ('avg_cost', 'Avg Cost'),
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []
        self._column_keys = [col[0] for col in self.COLUMNS]
        self._column_names = [col[1] for col in self.COLUMNS]
    
    def load_positions(self, positions: List[Dict[str, Any]]):
        """Load position data into the model."""
        self.beginResetModel()
        self._data = positions
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)
    
    def get_unique_values(self, column: int) -> List[str]:
        """Get unique values for a column (for text filter popup)."""
        col_key = self._column_keys[column]
        values = set()
        for row_data in self._data:
            value = row_data.get(col_key)
            if col_key == 'state':
                state_info = STATES.get(value)
                display = state_info.display_name if state_info else str(value)
                values.add(display)
            elif value is not None:
                values.add(str(value))
        return list(values)
    
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        
        row_data = self._data[index.row()]
        col_key = self._column_keys[index.column()]
        value = row_data.get(col_key)
        
        if role == Qt.ItemDataRole.DisplayRole:
            if col_key == 'state':
                state_info = STATES.get(value)
                return state_info.display_name if state_info else str(value)
            elif col_key in ('pivot', 'last_price', 'avg_cost'):
                return f"${value:.2f}" if value else ""
            elif col_key in ('dist_from_pivot', 'unrealized_pct', 'base_depth'):
                return f"{value:+.1f}%" if value is not None else ""
            elif col_key in ('unrealized_pnl', 'realized_pnl', 'total_pnl'):
                return f"${value:+,.2f}" if value is not None else ""
            elif col_key in ('watch_date', 'breakout_date'):
                if isinstance(value, (date, datetime)):
                    return value.strftime('%Y-%m-%d')
                return str(value) if value else ""
            elif value is None:
                return ""
            return str(value)
        
        elif role == Qt.ItemDataRole.BackgroundRole:
            state = row_data.get('state', 0)
            if state == -2:
                return QBrush(QColor(80, 45, 45))
            elif state == -1:
                return QBrush(QColor(85, 65, 40))
            elif state == 0:
                return QBrush(QColor(45, 55, 75))
            elif state >= 1:
                return QBrush(QColor(45, 75, 55))
        
        elif role == Qt.ItemDataRole.ForegroundRole:
            # Color all P&L and distance columns
            if col_key in ('dist_from_pivot', 'unrealized_pct', 'unrealized_pnl', 
                          'realized_pnl', 'total_pnl') and value is not None:
                if value > 0:
                    return QBrush(QColor(80, 220, 100))  # Green
                elif value < 0:
                    return QBrush(QColor(255, 100, 100))  # Red
        
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col_key in ('pivot', 'last_price', 'avg_cost', 
                          'dist_from_pivot', 'unrealized_pct', 'unrealized_pnl',
                          'realized_pnl', 'total_pnl',
                          'rs_rating', 'rs_3mo', 'rs_6mo', 'eps_rating', 'comp_rating',
                          'industry_rank', 'base_depth', 'base_length', 'fund_count',
                          'funds_qtr_chg', 'entry_score', 'total_shares'):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        
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
    
    def get_position_data(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None
    
    def get_column_key(self, column: int) -> str:
        return self._column_keys[column]


class AdvancedFilterProxyModel(QSortFilterProxyModel):
    """Proxy model supporting text multi-select and numeric comparison filters."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filters: Dict[int, Any] = {}
        self._state_filter: Optional[int] = None
    
    def set_column_filter(self, column: int, filter_value):
        """Set filter for a column. None to clear."""
        if filter_value is None:
            if column in self._filters:
                del self._filters[column]
        else:
            self._filters[column] = filter_value
        self.invalidateFilter()
    
    def set_state_filter(self, state: Optional[int]):
        self._state_filter = state
        self.invalidateFilter()
    
    def clear_filters(self):
        self._filters.clear()
        self._state_filter = None
        self.invalidateFilter()
    
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        
        # Check state filter
        if self._state_filter is not None:
            state_col = model._column_keys.index('state')
            state_index = model.index(source_row, state_col, source_parent)
            state_value = model.data(state_index, Qt.ItemDataRole.UserRole)
            if state_value != self._state_filter:
                return False
        
        # Check column filters
        for column, filter_value in self._filters.items():
            index = model.index(source_row, column, source_parent)
            raw_value = model.data(index, Qt.ItemDataRole.UserRole)
            display_value = model.data(index, Qt.ItemDataRole.DisplayRole)
            
            if isinstance(filter_value, set):
                # Text multi-select filter
                if display_value not in filter_value and str(raw_value) not in filter_value:
                    return False
            
            elif isinstance(filter_value, dict):
                # Numeric comparison filter
                if raw_value is None:
                    return False
                
                try:
                    num_value = float(raw_value)
                except (ValueError, TypeError):
                    return False
                
                op = filter_value.get('operator')
                target = filter_value.get('value', 0)
                target2 = filter_value.get('value2', 0)
                
                if op == '=' and num_value != target:
                    return False
                elif op == '≠' and num_value == target:
                    return False
                elif op == '>' and num_value <= target:
                    return False
                elif op == '≥' and num_value < target:
                    return False
                elif op == '<' and num_value >= target:
                    return False
                elif op == '≤' and num_value > target:
                    return False
                elif op == 'between':
                    min_val, max_val = min(target, target2), max(target, target2)
                    if num_value < min_val or num_value > max_val:
                        return False
        
        return True


class PositionTableView(QDialog):
    """Spreadsheet-style view with Excel-like filtering."""
    
    position_edited = pyqtSignal(int, dict)
    
    def __init__(self, db_session, parent=None):
        super().__init__(parent)
        self.db_session = db_session
        self._position_id_map: Dict[int, int] = {}
        self._filter_buttons: Dict[int, ColumnFilterButton] = {}
        
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        
        self._setup_ui()
        self._load_data()
    
    def _setup_ui(self):
        self.setWindowTitle("Position Database View")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)
        
        # Overall window style
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D30;
            }
            QLabel {
                color: #E0E0E0;
            }
            QComboBox {
                background-color: #3C3C3F;
                border: 1px solid #4A4A4D;
                border-radius: 3px;
                padding: 4px;
                color: #E0E0E0;
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
        
        layout = QVBoxLayout(self)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("All Positions")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(14)
        title.setFont(title_font)
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        self.count_label = QLabel("0 positions")
        self.count_label.setStyleSheet("color: #AAAAAA; font-style: italic;")
        header_layout.addWidget(self.count_label)
        
        layout.addLayout(header_layout)
        
        # Quick filters row
        quick_filter_layout = QHBoxLayout()
        
        # State filter dropdown
        state_layout = QFormLayout()
        self.state_filter_combo = QComboBox()
        self.state_filter_combo.addItem("All States", None)
        self.state_filter_combo.addItem("📋 Watching (0)", 0)
        self.state_filter_combo.addItem("🎯 Entry Ready (1)", 1)
        self.state_filter_combo.addItem("💰 In Position (2)", 2)
        self.state_filter_combo.addItem("📈 Pyramiding (3)", 3)
        self.state_filter_combo.addItem("⚠️ Failed Setup (-1)", -1)
        self.state_filter_combo.addItem("🛑 Stopped Out (-2)", -2)
        self.state_filter_combo.currentIndexChanged.connect(self._on_state_filter_changed)
        state_layout.addRow("State:", self.state_filter_combo)
        quick_filter_layout.addLayout(state_layout)
        
        quick_filter_layout.addStretch()
        
        # Info label
        info_label = QLabel("💡 Click ▼ below column headers to filter")
        info_label.setStyleSheet("color: #888888; font-style: italic;")
        quick_filter_layout.addWidget(info_label)
        
        clear_btn = QPushButton("Clear All Filters")
        clear_btn.clicked.connect(self._clear_filters)
        quick_filter_layout.addWidget(clear_btn)
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._load_data)
        quick_filter_layout.addWidget(refresh_btn)
        
        layout.addLayout(quick_filter_layout)
        
        # Table model and proxy
        self.table_model = PositionTableModel()
        self.proxy_model = AdvancedFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        self.proxy_model.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        
        # Filter buttons row
        self.filter_row = QWidget()
        self.filter_row.setFixedHeight(24)
        self.filter_row.setStyleSheet("background-color: #3C3C3F;")
        filter_row_layout = QHBoxLayout(self.filter_row)
        filter_row_layout.setContentsMargins(0, 0, 0, 0)
        filter_row_layout.setSpacing(0)
        
        for i, (key, name) in enumerate(PositionTableModel.COLUMNS):
            btn = ColumnFilterButton(i, key, name)
            btn.setFixedHeight(22)
            btn.filter_changed.connect(self._on_column_filter_changed)
            self._filter_buttons[i] = btn
            filter_row_layout.addWidget(btn)
        
        filter_row_layout.addStretch()
        layout.addWidget(self.filter_row)
        
        # Table view
        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        
        # Double-click to edit
        self.table_view.doubleClicked.connect(self._on_double_click)

        # Right-click context menu
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._on_table_context_menu)

        # Set column widths
        header = self.table_view.horizontalHeader()
        column_widths = [
            70,   # Symbol
            60,   # Portfolio
            85,   # State
            100,  # Pattern
            70,   # Pivot
            75,   # Last Price
            55,   # Dist %
            60,   # Unreal %
            75,   # Unreal $
            70,   # Real $
            75,   # Total $
            40,   # RS
            50,   # RS 3M
            50,   # RS 6M
            40,   # EPS
            50,   # Comp
            45,   # SMR
            45,   # A/D
            60,   # Ind Rank
            50,   # Stage
            60,   # Depth %
            50,   # Length
            55,   # Funds
            65,   # Funds Chg
            50,   # Grade
            50,   # Score
            85,   # Watch Date
            85,   # Breakout
            55,   # Shares
            75,   # Avg Cost
        ]
        for i, width in enumerate(column_widths):
            if i < len(PositionTableModel.COLUMNS):
                header.resizeSection(i, width)
        
        # Sync filter button widths with columns
        self.table_view.horizontalHeader().sectionResized.connect(self._sync_filter_widths)
        QTimer.singleShot(100, self._sync_filter_widths)
        
        # Style
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
                border-bottom: 1px solid #4A4A4D;
            }
            QTableView::item:selected {
                background-color: #0078D4;
                color: white;
            }
            QHeaderView::section {
                background-color: #3C3C3F;
                color: #FFFFFF;
                padding: 6px 4px;
                border: none;
                border-right: 1px solid #4A4A4D;
                border-bottom: 1px solid #4A4A4D;
                font-weight: bold;
                font-size: 11px;
            }
            QHeaderView::section:hover {
                background-color: #4A4A4D;
            }
        """)
        
        layout.addWidget(self.table_view)
        
        # Bottom buttons
        button_layout = QHBoxLayout()
        
        export_btn = QPushButton("📊 Export CSV")
        export_btn.clicked.connect(self._export_csv)
        button_layout.addWidget(export_btn)
        
        button_layout.addStretch()
        
        edit_btn = QPushButton("✏️ Edit Selected")
        edit_btn.clicked.connect(self._edit_selected)
        button_layout.addWidget(edit_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _sync_filter_widths(self):
        """Sync filter button widths with table column widths."""
        header = self.table_view.horizontalHeader()
        for i, btn in self._filter_buttons.items():
            if i < header.count():
                btn.setFixedWidth(header.sectionSize(i))
    
    def _load_data(self):
        """Load all positions from database."""
        try:
            from canslim_monitor.data.models import Position
            
            positions = self.db_session.query(Position).all()
            
            position_data = []
            self._position_id_map.clear()
            
            for i, pos in enumerate(positions):
                # Compute distance from pivot: ((last_price - pivot) / pivot) * 100
                dist_from_pivot = None
                if pos.last_price and pos.pivot and pos.pivot > 0:
                    dist_from_pivot = ((pos.last_price - pos.pivot) / pos.pivot) * 100
                
                # Compute unrealized P&L % : ((last_price - avg_cost) / avg_cost) * 100
                unrealized_pct = None
                if pos.last_price and pos.avg_cost and pos.avg_cost > 0:
                    unrealized_pct = ((pos.last_price - pos.avg_cost) / pos.avg_cost) * 100
                
                # Compute unrealized P&L $: (last_price - avg_cost) * total_shares
                unrealized_pnl = None
                if pos.last_price and pos.avg_cost and pos.total_shares:
                    unrealized_pnl = (pos.last_price - pos.avg_cost) * pos.total_shares
                
                # Get realized P&L if it exists in the model
                realized_pnl = getattr(pos, 'realized_pnl', None)
                
                # Compute total P&L: realized + unrealized
                total_pnl = None
                if realized_pnl is not None or unrealized_pnl is not None:
                    total_pnl = (realized_pnl or 0) + (unrealized_pnl or 0)
                
                data = {
                    'id': pos.id,
                    'symbol': pos.symbol,
                    'portfolio': pos.portfolio,
                    'state': pos.state,
                    'pattern': pos.pattern,
                    'pivot': pos.pivot,
                    'last_price': pos.last_price,
                    'dist_from_pivot': dist_from_pivot,    # Computed
                    'unrealized_pct': unrealized_pct,      # Computed
                    'unrealized_pnl': unrealized_pnl,      # Computed
                    'realized_pnl': realized_pnl,          # From DB
                    'total_pnl': total_pnl,                # Computed
                    'rs_rating': pos.rs_rating,
                    'rs_3mo': pos.rs_3mo,
                    'rs_6mo': pos.rs_6mo,
                    'eps_rating': pos.eps_rating,
                    'comp_rating': pos.comp_rating,
                    'smr_rating': pos.smr_rating,
                    'ad_rating': pos.ad_rating,
                    'industry_rank': pos.industry_rank,
                    'base_stage': pos.base_stage,
                    'base_depth': pos.base_depth,
                    'base_length': pos.base_length,
                    'fund_count': pos.fund_count,
                    'funds_qtr_chg': pos.funds_qtr_chg,
                    'entry_grade': pos.entry_grade,
                    'entry_score': pos.entry_score,
                    'watch_date': pos.watch_date,
                    'breakout_date': pos.breakout_date,
                    'total_shares': pos.total_shares,
                    'avg_cost': pos.avg_cost,
                }
                position_data.append(data)
                self._position_id_map[i] = pos.id
            
            self.table_model.load_positions(position_data)
            
            # Update filter buttons with unique values
            for i, btn in self._filter_buttons.items():
                if COLUMN_TYPES.get(btn.column_key) not in ('int', 'float'):
                    btn.set_unique_values(self.table_model.get_unique_values(i))
            
            self._update_count()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load positions: {e}")
    
    def _update_count(self):
        visible = self.proxy_model.rowCount()
        total = self.table_model.rowCount()
        if visible == total:
            self.count_label.setText(f"{total} positions")
        else:
            self.count_label.setText(f"{visible} of {total} positions")
    
    def _on_state_filter_changed(self, index: int):
        state = self.state_filter_combo.currentData()
        self.proxy_model.set_state_filter(state)
        self._update_count()
    
    def _on_column_filter_changed(self, column: int, filter_value):
        self.proxy_model.set_column_filter(column, filter_value)
        self._update_count()
    
    def _clear_filters(self):
        self.state_filter_combo.setCurrentIndex(0)
        for btn in self._filter_buttons.values():
            btn.clear_filter()
        self.proxy_model.clear_filters()
        self._update_count()
    
    def _on_double_click(self, index: QModelIndex):
        source_index = self.proxy_model.mapToSource(index)
        row = source_index.row()
        position_data = self.table_model.get_position_data(row)
        if position_data:
            self._open_edit_dialog(position_data)
    
    def _edit_selected(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "No Selection", "Please select a position to edit.")
            return
        
        source_index = self.proxy_model.mapToSource(indexes[0])
        row = source_index.row()
        position_data = self.table_model.get_position_data(row)
        if position_data:
            self._open_edit_dialog(position_data)
    
    def _open_edit_dialog(self, position_data: Dict[str, Any]):
        from canslim_monitor.gui.transition_dialogs import EditPositionDialog
        
        dialog = EditPositionDialog(position_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = dialog.get_result()
            position_id = position_data.get('id')
            
            if position_id:
                self.position_edited.emit(position_id, updated_data)
                self._load_data()
    
    def _export_csv(self):
        from PyQt6.QtWidgets import QFileDialog
        import csv
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Positions", "positions.csv", "CSV Files (*.csv)"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                headers = [col[1] for col in PositionTableModel.COLUMNS]
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
                f"Exported {self.proxy_model.rowCount()} positions to:\n{filename}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")

    def _on_table_context_menu(self, pos: QPoint):
        """Handle right-click context menu on table rows."""
        # Get the index at the click position
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return

        # Get the source row and position data
        source_index = self.proxy_model.mapToSource(index)
        row = source_index.row()
        position_data = self.table_model.get_position_data(row)

        if not position_data:
            return

        position_id = position_data.get('id')
        state = position_data.get('state', 0)
        symbol = position_data.get('symbol', 'Unknown')

        menu = QMenu(self)

        # Edit action
        edit_action = menu.addAction("✏️ Edit Position")
        edit_action.triggered.connect(lambda: self._open_edit_dialog(position_data))

        # Score details action
        score_action = menu.addAction("📊 View Score Details")
        score_action.triggered.connect(lambda: self._show_score_details(position_id))

        # View alerts action
        alerts_action = menu.addAction("🔔 View Alerts")
        alerts_action.triggered.connect(lambda: self._show_position_alerts(symbol, position_id))

        menu.addSeparator()

        # State transition actions
        from canslim_monitor.gui.state_config import get_valid_transitions
        valid_transitions = get_valid_transitions(state)

        if valid_transitions:
            move_menu = menu.addMenu("📦 Move to...")
            for transition in valid_transitions:
                to_state = transition.to_state
                to_name = STATES[to_state].display_name
                action = move_menu.addAction(f"{to_name}")
                action.triggered.connect(
                    lambda checked, ts=to_state, pid=position_id, cs=state: self._trigger_transition(pid, cs, ts)
                )

        menu.addSeparator()

        # Quick actions based on state
        if state >= 1:  # In position
            stop_action = menu.addAction("🛑 Stop Out")
            stop_action.triggered.connect(
                lambda: self._trigger_transition(position_id, state, -2)
            )

            close_action = menu.addAction("✅ Close Position")
            close_action.triggered.connect(
                lambda: self._trigger_transition(position_id, state, -1)
            )

        menu.addSeparator()

        # Delete action
        delete_action = menu.addAction("🗑️ Delete")
        delete_action.triggered.connect(lambda: self._delete_position(position_id, symbol))

        # Show menu at cursor position
        menu.exec(self.table_view.viewport().mapToGlobal(pos))

    def _show_score_details(self, position_id: int):
        """Show detailed score breakdown for a position."""
        import json
        from canslim_monitor.utils.scoring import CANSLIMScorer
        from canslim_monitor.data.models import Position
        from PyQt6.QtWidgets import QTextEdit

        try:
            position = self.db_session.query(Position).filter_by(id=position_id).first()

            if not position:
                QMessageBox.warning(self, "Error", "Position not found")
                return

            # Get current market regime (default to BULLISH)
            market_regime = 'BULLISH'
            try:
                from canslim_monitor.data.models import MarketRegime
                market_config = self.db_session.query(MarketRegime).order_by(MarketRegime.id.desc()).first()
                if market_config:
                    market_regime = market_config.regime
            except:
                pass

            scorer = CANSLIMScorer()

            # Try to load stored details first
            details = None
            if position.entry_score_details:
                try:
                    details = json.loads(position.entry_score_details)
                    if 'total_score' not in details or 'grade' not in details:
                        details = None
                except (json.JSONDecodeError, TypeError):
                    details = None

            # If no stored details, calculate static score
            if details is None:
                position_data = {
                    'pattern': position.pattern,
                    'rs_rating': position.rs_rating,
                    'eps_rating': position.eps_rating,
                    'ad_rating': position.ad_rating,
                    'base_stage': position.base_stage,
                    'base_depth': position.base_depth,
                    'base_length': position.base_length,
                    'ud_vol_ratio': position.ud_vol_ratio,
                    'fund_count': position.fund_count,
                    'group_rank': position.group_rank,
                    'comp_rating': position.comp_rating,
                    'prior_uptrend': position.prior_uptrend,
                }
                score, grade, details = scorer.calculate_score(position_data, market_regime)
            else:
                score = details.get('total_score', position.entry_score or 0)
                grade = details.get('grade', position.entry_grade or 'F')

            # Format details text
            details_text = scorer.format_details_text(details, symbol=position.symbol, pivot=position.pivot)

            # Show in a dialog
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Score Details: {position.symbol}")
            dialog.setMinimumSize(720, 750)

            layout = QVBoxLayout(dialog)

            # Header with symbol and grade
            header = QLabel(f"<h2>{position.symbol} - Grade: {grade} (Score: {score})</h2>")
            header.setStyleSheet("color: #E0E0E0;")
            layout.addWidget(header)

            # Score details in monospace text
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setFontFamily("Consolas, Monaco, monospace")
            text_edit.setPlainText(details_text)
            text_edit.setStyleSheet("""
                QTextEdit {
                    background-color: #1E1E1E;
                    color: #D4D4D4;
                    font-size: 13px;
                    padding: 10px;
                    line-height: 1.4;
                }
            """)
            layout.addWidget(text_edit)

            # Buttons
            btn_layout = QHBoxLayout()

            # Recalculate button - call parent's recalculate method if available
            recalc_btn = QPushButton("🔄 Recalculate")
            recalc_btn.setToolTip("Fetch latest data and recalculate score with execution feasibility")

            def do_recalculate():
                # Call parent's recalculate method if available (kanban_window)
                if self.parent() and hasattr(self.parent(), '_recalculate_score'):
                    dialog.accept()  # Close this dialog
                    self.parent()._recalculate_score(position_id)
                else:
                    QMessageBox.information(
                        dialog, "Info",
                        "Recalculate is only available from the main window.\n"
                        "Please use the kanban view for full recalculation."
                    )

            recalc_btn.clicked.connect(do_recalculate)
            btn_layout.addWidget(recalc_btn)

            btn_layout.addStretch()

            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(close_btn)

            layout.addLayout(btn_layout)

            dialog.exec()

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to show score details: {e}")

    def _show_position_alerts(self, symbol: str, position_id: int):
        """Show alerts dialog for position using the AlertService."""
        try:
            from canslim_monitor.gui.alerts import PositionAlertDialog
            from canslim_monitor.services.alert_service import AlertService
            import logging

            # Get db_session_factory from parent (kanban_window)
            db_session_factory = None
            if self.parent() and hasattr(self.parent(), 'db'):
                db_session_factory = self.parent().db.get_new_session

            # Create alert service
            alert_service = AlertService(
                db_session_factory=db_session_factory,
                logger=logging.getLogger('canslim.alerts')
            )

            # Fetch alerts for this symbol using the proper service
            alerts = alert_service.get_recent_alerts(
                symbol=symbol,
                hours=24 * 90,  # 90 days
                limit=500
            )

            if not alerts:
                QMessageBox.information(self, "No Alerts", f"No alerts found for {symbol}")
                return

            # Show dialog with alert service for acknowledgment support
            dialog = PositionAlertDialog(
                symbol=symbol,
                alerts=alerts,
                parent=self,
                alert_service=alert_service,
                db_session_factory=db_session_factory
            )
            dialog.alert_acknowledged.connect(lambda _: self._load_data())
            dialog.show()  # Modeless like kanban_window

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to show alerts: {e}")

    def _trigger_transition(self, position_id: int, from_state: int, to_state: int):
        """Trigger a state transition for the position."""
        try:
            from canslim_monitor.data.models import Position

            position = self.db_session.query(Position).filter_by(id=position_id).first()
            if not position:
                QMessageBox.warning(self, "Error", "Position not found")
                return

            # Check if transition requires a dialog
            from canslim_monitor.gui.state_config import get_transition
            transition = get_transition(from_state, to_state)

            if transition and transition.requires_dialog:
                # Import appropriate dialog
                if to_state == 1:  # Entry
                    from canslim_monitor.gui.transition_dialogs import EntryDialog
                    dialog = EntryDialog(position, self)
                elif to_state == -1:  # Closed
                    from canslim_monitor.gui.transition_dialogs import ClosePositionDialog
                    dialog = ClosePositionDialog(position, self)
                elif to_state == -2:  # Stopped Out
                    from canslim_monitor.gui.transition_dialogs import StopOutDialog
                    dialog = StopOutDialog(position, self)
                else:
                    dialog = None

                if dialog:
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        result = dialog.get_result()
                        # Apply the transition result
                        for key, value in result.items():
                            if hasattr(position, key):
                                setattr(position, key, value)
                        position.state = to_state
                        self.db_session.commit()
                        self._load_data()
                    return

            # Simple state change (no dialog required)
            position.state = to_state
            self.db_session.commit()
            self._load_data()

            # Emit signal so parent window updates
            self.position_edited.emit(position_id, {'state': to_state})

        except Exception as e:
            self.db_session.rollback()
            QMessageBox.warning(self, "Error", f"Failed to change state: {e}")

    def _delete_position(self, position_id: int, symbol: str):
        """Delete a position after confirmation."""
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete position '{symbol}'?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                from canslim_monitor.data.models import Position

                position = self.db_session.query(Position).filter_by(id=position_id).first()
                if position:
                    self.db_session.delete(position)
                    self.db_session.commit()
                    self._load_data()
                    QMessageBox.information(self, "Deleted", f"Position '{symbol}' has been deleted.")

                    # Emit signal so parent window updates
                    self.position_edited.emit(position_id, {'deleted': True})
                else:
                    QMessageBox.warning(self, "Error", "Position not found")
            except Exception as e:
                self.db_session.rollback()
                QMessageBox.warning(self, "Error", f"Failed to delete position: {e}")
