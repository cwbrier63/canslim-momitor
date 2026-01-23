"""
CANSLIM Monitor - State Transition Dialogs
Dialogs for collecting required data when transitioning position states.
"""

from datetime import date
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTextEdit,
    QPushButton, QComboBox, QGroupBox, QMessageBox, QFrame,
    QScrollArea, QWidget
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont

from canslim_monitor.gui.state_config import (
    STATES, StateTransition, get_transition,
    VALID_PATTERNS, AD_RATINGS, BASE_STAGES, EXIT_REASONS, TRADE_OUTCOMES,
    SMR_RATINGS, MARKET_EXPOSURE_LEVELS
)


class TransitionDialog(QDialog):
    """
    Dialog for entering data required for a state transition.
    """
    
    def __init__(
        self,
        symbol: str,
        from_state: int,
        to_state: int,
        current_data: Dict[str, Any] = None,
        parent=None
    ):
        super().__init__(parent)
        
        self.symbol = symbol
        self.from_state = from_state
        self.to_state = to_state
        self.current_data = current_data or {}
        self.result_data: Dict[str, Any] = {}
        
        self.transition = get_transition(from_state, to_state)
        if not self.transition:
            raise ValueError(f"Invalid transition: {from_state} → {to_state}")
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        from_info = STATES.get(self.from_state)
        to_info = STATES.get(self.to_state)
        
        self.setWindowTitle(f"Transition: {self.symbol}")
        self.setMinimumWidth(400)
        
        # Initialize field_widgets BEFORE creating fields
        self.field_widgets = {}
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Header
        header = QLabel(f"{self.symbol}: {from_info.display_name} → {to_info.display_name}")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        # Description
        desc = QLabel(self.transition.description)
        desc.setStyleSheet("color: #666;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)
        
        # Form for required fields
        if self.transition.required_fields:
            required_group = QGroupBox("Required Information")
            required_layout = QFormLayout()
            self._create_fields(required_layout, self.transition.required_fields)
            required_group.setLayout(required_layout)
            layout.addWidget(required_group)
        
        # Form for optional fields
        if self.transition.optional_fields:
            optional_group = QGroupBox("Optional Information")
            optional_layout = QFormLayout()
            self._create_fields(optional_layout, self.transition.optional_fields)
            optional_group.setLayout(optional_layout)
            layout.addWidget(optional_group)
        
        # Current position info (read-only)
        if self.current_data:
            info_group = QGroupBox("Current Position")
            info_layout = QFormLayout()
            self._show_current_info(info_layout)
            info_group.setLayout(info_layout)
            layout.addWidget(info_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        button_layout.addStretch()
        
        confirm_btn = QPushButton("Confirm Transition")
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self._on_confirm)
        confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        button_layout.addWidget(confirm_btn)
        
        layout.addLayout(button_layout)
    
    def _create_fields(self, layout: QFormLayout, fields: list):
        """Create form fields for the given field names."""
        for field in fields:
            label, widget = self._create_field_widget(field)
            layout.addRow(label, widget)
            self.field_widgets[field] = widget
    
    def _create_field_widget(self, field: str):
        """Create appropriate widget for a field."""
        # Share fields - show total shares available
        if field in ('e1_shares', 'e2_shares', 'e3_shares', 'tp1_sold', 'tp2_sold', 'exit_shares'):
            label = self._get_field_label(field)
            
            # Create container with spinbox and suggestion label
            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)
            h_layout.setSpacing(8)
            
            widget = QSpinBox()
            widget.setRange(0, 100000)
            widget.setSingleStep(10)
            h_layout.addWidget(widget)
            
            # Show total shares available for sell fields
            total_shares = self.current_data.get('total_shares', 0)
            if field in ('tp1_sold', 'tp2_sold', 'exit_shares') and total_shares:
                shares_label = QLabel(f"of {int(total_shares)} shares")
                shares_label.setStyleSheet("color: #666; font-style: italic;")
                h_layout.addWidget(shares_label)
                
                # Default to total shares for exit
                if field == 'exit_shares':
                    widget.setValue(int(total_shares))
                # For TP sells, suggest selling portion
                elif field == 'tp1_sold':
                    widget.setValue(int(total_shares * 0.33))  # Suggest 1/3
                elif field == 'tp2_sold':
                    widget.setValue(int(total_shares * 0.5))   # Suggest half remaining
            
            # IBD Pyramiding suggestions for entry fields
            # Entry 1 = 50%, Entry 2 = 25%, Entry 3 = 25% of full position
            # So E2 shares = E1 shares / 2, E3 shares = E2 shares (or E1 / 2)
            if field == 'e2_shares':
                e1_shares = self.current_data.get('e1_shares', 0)
                if e1_shares:
                    suggested = int(e1_shares / 2)  # IBD: E2 = 25% = half of E1's 50%
                    widget.setValue(suggested)
                    # Add suggestion label
                    suggestion_label = QLabel(f"(IBD suggests {suggested} = 50% of E1)")
                    suggestion_label.setStyleSheet("color: #17A2B8; font-style: italic;")
                    h_layout.addWidget(suggestion_label)
            
            elif field == 'e3_shares':
                e2_shares = self.current_data.get('e2_shares', 0)
                e1_shares = self.current_data.get('e1_shares', 0)
                if e2_shares:
                    suggested = int(e2_shares)  # E3 should equal E2 (both 25%)
                    widget.setValue(suggested)
                    suggestion_label = QLabel(f"(IBD suggests {suggested} = same as E2)")
                    suggestion_label.setStyleSheet("color: #17A2B8; font-style: italic;")
                    h_layout.addWidget(suggestion_label)
                elif e1_shares:
                    suggested = int(e1_shares / 2)  # Fallback: E3 = half of E1
                    widget.setValue(suggested)
                    suggestion_label = QLabel(f"(IBD suggests {suggested} = 50% of E1)")
                    suggestion_label.setStyleSheet("color: #17A2B8; font-style: italic;")
                    h_layout.addWidget(suggestion_label)
            
            # Pre-fill from current data if available (overrides suggestions)
            if field in self.current_data and self.current_data[field]:
                widget.setValue(int(self.current_data[field]))
            
            h_layout.addStretch()
            
            # Store the spinbox as the actual widget for value retrieval
            container._spinbox = widget
            return label, container
        
        # Price fields
        if field in ('e1_price', 'e2_price', 'e3_price', 'tp1_price', 'tp2_price', 'stop_price', 'exit_price'):
            label = self._get_field_label(field)
            
            # Create container for price fields that need context info
            avg_cost = self.current_data.get('avg_cost', 0)
            last_price = self.current_data.get('last_price', 0)
            needs_context = (field == 'exit_price' and avg_cost) or field in ('e2_price', 'e3_price')
            
            if needs_context:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)
                h_layout.setSpacing(8)
                
                widget = QDoubleSpinBox()
                widget.setRange(0, 100000)
                widget.setDecimals(2)
                widget.setSingleStep(0.25)
                widget.setPrefix("$")
                h_layout.addWidget(widget)
                
                # Default to last price for pyramid entries and exit
                if last_price:
                    widget.setValue(float(last_price))
                
                # Show context info
                if field == 'exit_price' and avg_cost:
                    cost_label = QLabel(f"(Avg cost: ${avg_cost:.2f})")
                    cost_label.setStyleSheet("color: #666; font-style: italic;")
                    h_layout.addWidget(cost_label)
                elif field in ('e2_price', 'e3_price') and last_price:
                    # Show current price as suggestion for pyramid entries
                    context_label = QLabel(f"(Current: ${last_price:.2f})")
                    context_label.setStyleSheet("color: #17A2B8; font-style: italic;")
                    h_layout.addWidget(context_label)
                
                h_layout.addStretch()
                
                container._spinbox = widget
                return label, container
            else:
                widget = QDoubleSpinBox()
                widget.setRange(0, 100000)
                widget.setDecimals(2)
                widget.setSingleStep(0.25)
                widget.setPrefix("$")
                # Pre-fill from current data
                if field in self.current_data and self.current_data[field]:
                    widget.setValue(float(self.current_data[field]))
                elif field == 'stop_price' and 'pivot' in self.current_data:
                    # Suggest stop 7% below pivot
                    pivot = self.current_data.get('pivot', 0)
                    if pivot:
                        widget.setValue(pivot * 0.93)
                elif field == 'exit_price' and 'last_price' in self.current_data:
                    # Default exit price to last known price
                    last = self.current_data.get('last_price', 0)
                    if last:
                        widget.setValue(float(last))
                return label, widget
        
        # Date fields
        if field in ('entry_date', 'breakout_date', 'tp1_date', 'tp2_date', 'exit_date'):
            label = self._get_field_label(field)
            widget = QDateEdit()
            widget.setCalendarPopup(True)
            widget.setDate(QDate.currentDate())
            if field in self.current_data and self.current_data[field]:
                d = self.current_data[field]
                if isinstance(d, date):
                    widget.setDate(QDate(d.year, d.month, d.day))
            return label, widget
        
        # Exit reason dropdown
        if field == 'exit_reason':
            label = self._get_field_label(field)
            widget = QComboBox()
            widget.addItems([''] + EXIT_REASONS)
            # Pre-select based on transition type
            if self.to_state == -2:  # Stop out
                idx = widget.findText('STOP_HIT')
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            return label, widget
        
        # Trade outcome dropdown
        if field == 'trade_outcome':
            label = self._get_field_label(field)
            widget = QComboBox()
            widget.addItems([''] + TRADE_OUTCOMES)
            # Pre-select based on transition type
            if self.to_state == -2:  # Stop out
                idx = widget.findText('STOPPED')
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            return label, widget
        
        # Notes field
        if field == 'notes':
            label = "Notes:"
            widget = QTextEdit()
            widget.setMaximumHeight(80)
            if 'notes' in self.current_data:
                widget.setPlainText(self.current_data.get('notes', ''))
            return label, widget
        
        # Default to text input
        label = self._get_field_label(field)
        widget = QLineEdit()
        if field in self.current_data:
            widget.setText(str(self.current_data.get(field, '')))
        return label, widget
    
    def _get_field_label(self, field: str) -> str:
        """Get human-readable label for a field."""
        labels = {
            'e1_shares': 'Entry 1 Shares:',
            'e1_price': 'Entry 1 Price:',
            'e2_shares': 'Entry 2 Shares:',
            'e2_price': 'Entry 2 Price:',
            'e3_shares': 'Entry 3 Shares:',
            'e3_price': 'Entry 3 Price:',
            'tp1_sold': 'Shares to Sell:',
            'tp1_price': 'Sell Price:',
            'tp2_sold': 'Shares to Sell:',
            'tp2_price': 'Sell Price:',
            'stop_price': 'Stop Price:',
            'entry_date': 'Entry Date:',
            'breakout_date': 'Breakout Date:',
            'tp1_date': 'TP1 Date:',
            'tp2_date': 'TP2 Date:',
            'exit_date': 'Exit Date:',
            'exit_price': 'Exit Price:',
            'exit_shares': 'Shares Sold:',
            'exit_reason': 'Exit Reason:',
            'trade_outcome': 'Trade Outcome:',
            'notes': 'Notes:',
        }
        return labels.get(field, f"{field.replace('_', ' ').title()}:")
    
    def _show_current_info(self, layout: QFormLayout):
        """Show current position info - comprehensive view for all transitions."""
        from datetime import date as date_type
        
        # Calculate days held/watching
        days_text = ""
        entry_date = self.current_data.get('entry_date') or self.current_data.get('breakout_date')
        watch_date = self.current_data.get('watch_date')
        
        if entry_date and isinstance(entry_date, date_type):
            days_held = (date_type.today() - entry_date).days
            days_text = f"{days_held} days"
        elif watch_date and isinstance(watch_date, date_type):
            days_watching = (date_type.today() - watch_date).days
            days_text = f"{days_watching} days"
        
        # Calculate P&L
        pnl_text = ""
        pnl_pct = ""
        avg_cost = self.current_data.get('avg_cost', 0)
        last_price = self.current_data.get('last_price', 0)
        total_shares = self.current_data.get('total_shares', 0)
        
        if avg_cost and last_price and total_shares:
            pnl_value = (last_price - avg_cost) * total_shares
            pnl_pct_value = ((last_price / avg_cost) - 1) * 100
            pnl_text = f"${pnl_value:+,.2f}"
            pnl_pct = f"{pnl_pct_value:+.2f}%"
            if pnl_value >= 0:
                pnl_color = "#28A745"  # Green
            else:
                pnl_color = "#DC3545"  # Red
        
        # Build info display based on what data is available
        if self.from_state == 0:  # Watching
            info_fields = [
                ('pivot', 'Pivot', '${:.2f}'),
                ('last_price', 'Current Price', '${:.2f}'),
            ]
            if days_text:
                info_fields.append(('_days', 'Days Watching', days_text))
        else:  # In position
            info_fields = [
                ('total_shares', 'Shares Held', '{:,.0f}'),
                ('avg_cost', 'Avg Cost', '${:.2f}'),
                ('last_price', 'Current Price', '${:.2f}'),
                ('pivot', 'Pivot', '${:.2f}'),
                ('stop_price', 'Stop Price', '${:.2f}'),
            ]
            if days_text:
                info_fields.append(('_days', 'Days Held', days_text))
        
        for field, label, fmt in info_fields:
            if field.startswith('_'):
                # Special computed field
                value_label = QLabel(fmt)
                value_label.setStyleSheet("color: #333; font-weight: bold;")
                layout.addRow(f"{label}:", value_label)
            elif field in self.current_data and self.current_data[field]:
                value = self.current_data[field]
                try:
                    if isinstance(fmt, str) and '{' in fmt:
                        formatted = fmt.format(value)
                    else:
                        formatted = str(value)
                except:
                    formatted = str(value)
                value_label = QLabel(formatted)
                value_label.setStyleSheet("color: #333;")
                layout.addRow(f"{label}:", value_label)
        
        # Add P&L row with color if we have position data
        if pnl_text and self.from_state > 0:
            pnl_label = QLabel(f"{pnl_text}  ({pnl_pct})")
            pnl_label.setStyleSheet(f"color: {pnl_color}; font-weight: bold;")
            layout.addRow("Current P&L:", pnl_label)
    
    def _on_confirm(self):
        """Handle confirm button click."""
        # Validate required fields
        for field in self.transition.required_fields:
            widget = self.field_widgets.get(field)
            if not widget:
                continue
            
            value = self._get_widget_value(widget)
            
            if value is None or value == 0 or value == '':
                QMessageBox.warning(
                    self,
                    "Missing Required Field",
                    f"Please enter a value for: {self._get_field_label(field)}"
                )
                return
            
            self.result_data[field] = value
        
        # Collect optional fields
        for field in self.transition.optional_fields:
            widget = self.field_widgets.get(field)
            if widget:
                value = self._get_widget_value(widget)
                if value is not None and value != '' and value != 0:
                    self.result_data[field] = value
        
        self.accept()
    
    def _get_widget_value(self, widget):
        """Get value from a widget."""
        # Handle container widgets with embedded spinbox
        if hasattr(widget, '_spinbox'):
            return widget._spinbox.value()
        if isinstance(widget, QSpinBox):
            return widget.value()
        elif isinstance(widget, QDoubleSpinBox):
            return widget.value()
        elif isinstance(widget, QDateEdit):
            qdate = widget.date()
            return date(qdate.year(), qdate.month(), qdate.day())
        elif isinstance(widget, QTextEdit):
            return widget.toPlainText()
        elif isinstance(widget, QLineEdit):
            return widget.text()
        elif isinstance(widget, QComboBox):
            return widget.currentText()
        return None
    
    def get_result(self) -> Dict[str, Any]:
        """Get the collected data."""
        return self.result_data


class AddPositionDialog(QDialog):
    """
    Dialog for adding a new position to the watchlist.
    Modeless dialog - can be used independently of main window.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_data: Dict[str, Any] = {}
        
        # Make dialog independent (modeless) - can minimize main window while this stays open
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Add to Watchlist")
        self.setMinimumWidth(550)
        self.setMinimumHeight(500)
        
        # Apply light theme styling for better readability
        self.setStyleSheet("""
            QDialog {
                background-color: #F5F5F5;
            }
            QGroupBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
                color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #333333;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QLineEdit:focus {
                border: 1px solid #0078D4;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #0078D4;
            }
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QComboBox:focus {
                border: 1px solid #0078D4;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                color: #333333;
                selection-background-color: #0078D4;
                selection-color: #FFFFFF;
            }
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                color: #333333;
            }
            QTextEdit:focus {
                border: 1px solid #0078D4;
            }
            QDateEdit {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QDateEdit:focus {
                border: 1px solid #0078D4;
            }
            QPushButton {
                background-color: #E0E0E0;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px 16px;
                color: #333333;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D0D0D0;
                border: 1px solid #0078D4;
            }
            QPushButton:pressed {
                background-color: #C0C0C0;
            }
            QScrollArea {
                border: none;
                background-color: #F5F5F5;
            }
        """)
        
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        
        # Header (outside scroll area)
        header = QLabel("Add New Position")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header)
        
        # Scroll area for form content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        
        # Required fields
        required_group = QGroupBox("Setup Information (Required)")
        required_layout = QFormLayout()
        
        # Symbol (with lookup button)
        symbol_row = QHBoxLayout()
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("AAPL, NVDA, etc.")
        self.symbol_input.setMaxLength(10)
        self.symbol_input.textChanged.connect(self._on_symbol_changed)
        symbol_row.addWidget(self.symbol_input)
        
        # Lookup button (for future IBKR/Massive integration)
        self.lookup_btn = QPushButton("🔍 Lookup")
        self.lookup_btn.setFixedWidth(80)
        self.lookup_btn.clicked.connect(self._on_lookup)
        self.lookup_btn.setToolTip("Lookup stock data from IBKR/Massive")
        symbol_row.addWidget(self.lookup_btn)
        required_layout.addRow("Symbol:", symbol_row)
        
        # Pattern
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems([''] + VALID_PATTERNS)
        self.pattern_combo.setEditable(True)
        required_layout.addRow("Pattern:", self.pattern_combo)
        
        # Pivot
        self.pivot_input = QDoubleSpinBox()
        self.pivot_input.setRange(0, 100000)
        self.pivot_input.setDecimals(2)
        self.pivot_input.setPrefix("$")
        required_layout.addRow("Pivot Price:", self.pivot_input)
        
        # Stop %
        self.stop_pct_input = QDoubleSpinBox()
        self.stop_pct_input.setRange(1, 20)
        self.stop_pct_input.setValue(7.0)
        self.stop_pct_input.setSuffix("%")
        required_layout.addRow("Stop Loss %:", self.stop_pct_input)
        
        # Portfolio
        self.portfolio_combo = QComboBox()
        self.portfolio_combo.addItems(['', 'Swing', 'Position', 'Paper', 'Other'])
        self.portfolio_combo.setEditable(True)
        self.portfolio_combo.setToolTip("Portfolio/account for this position")
        required_layout.addRow("Portfolio:", self.portfolio_combo)
        
        required_group.setLayout(required_layout)
        layout.addWidget(required_group)
        
        # Base Characteristics
        base_group = QGroupBox("Base Characteristics")
        base_layout = QFormLayout()
        
        # Base Stage
        self.stage_combo = QComboBox()
        self.stage_combo.addItems([''] + BASE_STAGES)
        self.stage_combo.setEditable(True)
        base_layout.addRow("Base Stage:", self.stage_combo)
        
        # Base Depth %
        self.depth_input = QDoubleSpinBox()
        self.depth_input.setRange(0, 100)
        self.depth_input.setDecimals(1)
        self.depth_input.setSuffix("%")
        base_layout.addRow("Base Depth:", self.depth_input)
        
        # Base Length (weeks)
        self.length_input = QSpinBox()
        self.length_input.setRange(0, 100)
        self.length_input.setSuffix(" weeks")
        base_layout.addRow("Base Length:", self.length_input)
        
        base_group.setLayout(base_layout)
        layout.addWidget(base_group)
        
        # CANSLIM Ratings (two columns)
        ratings_group = QGroupBox("CANSLIM Ratings")
        ratings_layout = QHBoxLayout()
        
        # Left column - Core Ratings
        left_layout = QFormLayout()
        
        self.rs_input = QSpinBox()
        self.rs_input.setRange(0, 99)
        left_layout.addRow("RS Rating:", self.rs_input)
        
        self.rs_3mo_input = QSpinBox()
        self.rs_3mo_input.setRange(0, 99)
        self.rs_3mo_input.setToolTip("3-Month RS Rating (from Technical panel)")
        left_layout.addRow("RS 3-Month:", self.rs_3mo_input)
        
        self.rs_6mo_input = QSpinBox()
        self.rs_6mo_input.setRange(0, 99)
        self.rs_6mo_input.setToolTip("6-Month RS Rating (from Technical panel)")
        left_layout.addRow("RS 6-Month:", self.rs_6mo_input)
        
        self.eps_input = QSpinBox()
        self.eps_input.setRange(0, 99)
        left_layout.addRow("EPS Rating:", self.eps_input)
        
        self.comp_input = QSpinBox()
        self.comp_input.setRange(0, 99)
        left_layout.addRow("Composite:", self.comp_input)
        
        self.smr_combo = QComboBox()
        self.smr_combo.addItems([''] + SMR_RATINGS)
        self.smr_combo.setToolTip("Sales/Margin/ROE Rating")
        left_layout.addRow("SMR Rating:", self.smr_combo)
        
        self.ad_combo = QComboBox()
        self.ad_combo.addItems([''] + AD_RATINGS)
        left_layout.addRow("A/D Rating:", self.ad_combo)
        
        self.ud_ratio_input = QDoubleSpinBox()
        self.ud_ratio_input.setRange(0, 10)
        self.ud_ratio_input.setDecimals(2)
        left_layout.addRow("U/D Vol Ratio:", self.ud_ratio_input)
        
        ratings_layout.addLayout(left_layout)
        
        # Right column - Industry & Institutional
        right_layout = QFormLayout()
        
        self.industry_rank_input = QSpinBox()
        self.industry_rank_input.setRange(0, 197)
        self.industry_rank_input.setToolTip("Industry 197 Rank (1=best)")
        right_layout.addRow("Industry Rank:", self.industry_rank_input)
        
        self.industry_eps_rank_input = QLineEdit()
        self.industry_eps_rank_input.setPlaceholderText("e.g., 3 of 38")
        self.industry_eps_rank_input.setToolTip("EPS Rank within Industry Group")
        right_layout.addRow("EPS in Industry:", self.industry_eps_rank_input)
        
        self.industry_rs_rank_input = QLineEdit()
        self.industry_rs_rank_input.setPlaceholderText("e.g., 10 of 38")
        self.industry_rs_rank_input.setToolTip("RS Rank within Industry Group")
        right_layout.addRow("RS in Industry:", self.industry_rs_rank_input)
        
        self.fund_count_input = QSpinBox()
        self.fund_count_input.setRange(0, 10000)
        self.fund_count_input.setToolTip("Number of Funds (from Owners panel)")
        right_layout.addRow("Fund Count:", self.fund_count_input)
        
        self.funds_qtr_chg_input = QSpinBox()
        self.funds_qtr_chg_input.setRange(-9999, 9999)
        self.funds_qtr_chg_input.setToolTip("Change in fund count vs prior quarter")
        right_layout.addRow("Funds Qtr Chg:", self.funds_qtr_chg_input)
        
        self.prior_uptrend_input = QSpinBox()
        self.prior_uptrend_input.setRange(-100, 500)
        self.prior_uptrend_input.setSuffix("%")
        right_layout.addRow("Prior Uptrend:", self.prior_uptrend_input)
        
        ratings_layout.addLayout(right_layout)
        ratings_group.setLayout(ratings_layout)
        layout.addWidget(ratings_group)
        
        # Breakout Quality
        breakout_group = QGroupBox("Breakout Quality")
        breakout_layout = QFormLayout()
        
        self.breakout_vol_pct_input = QSpinBox()
        self.breakout_vol_pct_input.setRange(-100, 9999)
        self.breakout_vol_pct_input.setSuffix("%")
        self.breakout_vol_pct_input.setToolTip("Volume % on breakout day vs 50-day avg")
        breakout_layout.addRow("Breakout Vol %:", self.breakout_vol_pct_input)
        
        self.breakout_price_pct_input = QDoubleSpinBox()
        self.breakout_price_pct_input.setRange(-50, 100)
        self.breakout_price_pct_input.setDecimals(1)
        self.breakout_price_pct_input.setSuffix("%")
        self.breakout_price_pct_input.setToolTip("Price % change on breakout day")
        breakout_layout.addRow("Breakout Price %:", self.breakout_price_pct_input)
        
        breakout_group.setLayout(breakout_layout)
        layout.addWidget(breakout_group)
        
        # Dates
        dates_group = QGroupBox("Key Dates")
        dates_layout = QFormLayout()
        
        self.watch_date_input = QDateEdit()
        self.watch_date_input.setCalendarPopup(True)
        self.watch_date_input.setDate(QDate.currentDate())
        dates_layout.addRow("Watch Date:", self.watch_date_input)
        
        self.breakout_date_input = QDateEdit()
        self.breakout_date_input.setCalendarPopup(True)
        self.breakout_date_input.setSpecialValueText("Not Set")
        self.breakout_date_input.setToolTip("Date stock broke out of the base (if already occurred)")
        dates_layout.addRow("Breakout Date:", self.breakout_date_input)
        
        self.earnings_date_input = QDateEdit()
        self.earnings_date_input.setCalendarPopup(True)
        self.earnings_date_input.setSpecialValueText("Not Set")
        dates_layout.addRow("Earnings Date:", self.earnings_date_input)
        
        dates_group.setLayout(dates_layout)
        layout.addWidget(dates_group)
        
        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(60)
        notes_layout.addWidget(self.notes_input)
        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)
        
        # Finalize scroll area
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        
        # Buttons (outside scroll area)
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        button_layout.addStretch()
        
        add_btn = QPushButton("Add to Watchlist")
        add_btn.setDefault(True)
        add_btn.clicked.connect(self._on_add)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #17A2B8;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        button_layout.addWidget(add_btn)
        
        main_layout.addLayout(button_layout)
    
    def _on_symbol_changed(self, text: str):
        """Convert symbol to uppercase."""
        cursor_pos = self.symbol_input.cursorPosition()
        self.symbol_input.blockSignals(True)
        self.symbol_input.setText(text.upper())
        self.symbol_input.setCursorPosition(cursor_pos)
        self.symbol_input.blockSignals(False)
    
    def _on_lookup(self):
        """Lookup stock data from IBKR/Massive."""
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "No Symbol", "Please enter a symbol first.")
            return
        
        # TODO: Integrate with IBKR/Massive API
        QMessageBox.information(
            self, 
            "Lookup", 
            f"Lookup for {symbol} will fetch data from IBKR/Massive.\n\n"
            "(This feature is coming soon - for now enter data manually)"
        )
    
    def _on_add(self):
        """Handle add button click."""
        # Validate required fields
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "Missing Symbol", "Please enter a stock symbol.")
            return
        
        pattern = self.pattern_combo.currentText()
        if not pattern:
            QMessageBox.warning(self, "Missing Pattern", "Please select or enter a pattern.")
            return
        
        pivot = self.pivot_input.value()
        if pivot <= 0:
            QMessageBox.warning(self, "Invalid Pivot", "Please enter a valid pivot price.")
            return
        
        # Build result with all fields
        watch_date = self.watch_date_input.date()
        
        self.result_data = {
            'symbol': symbol,
            'pattern': pattern,
            'pivot': pivot,
            'hard_stop_pct': self.stop_pct_input.value(),
            'stop_price': pivot * (1 - self.stop_pct_input.value() / 100),
            'state': 0,  # Watching
            'watch_date': date(watch_date.year(), watch_date.month(), watch_date.day()),
        }
        
        # Portfolio
        if self.portfolio_combo.currentText():
            self.result_data['portfolio'] = self.portfolio_combo.currentText()
        
        # Base characteristics
        if self.stage_combo.currentText():
            self.result_data['base_stage'] = self.stage_combo.currentText()
        if self.depth_input.value() > 0:
            self.result_data['base_depth'] = self.depth_input.value()
        if self.length_input.value() > 0:
            self.result_data['base_length'] = self.length_input.value()
        
        # CANSLIM ratings
        if self.rs_input.value() > 0:
            self.result_data['rs_rating'] = self.rs_input.value()
        if self.rs_3mo_input.value() > 0:
            self.result_data['rs_3mo'] = self.rs_3mo_input.value()
        if self.rs_6mo_input.value() > 0:
            self.result_data['rs_6mo'] = self.rs_6mo_input.value()
        if self.eps_input.value() > 0:
            self.result_data['eps_rating'] = self.eps_input.value()
        if self.comp_input.value() > 0:
            self.result_data['comp_rating'] = self.comp_input.value()
        if self.smr_combo.currentText():
            self.result_data['smr_rating'] = self.smr_combo.currentText()
        if self.ad_combo.currentText():
            self.result_data['ad_rating'] = self.ad_combo.currentText()
        if self.ud_ratio_input.value() > 0:
            self.result_data['ud_vol_ratio'] = self.ud_ratio_input.value()
        
        # Industry data
        if self.industry_rank_input.value() > 0:
            self.result_data['industry_rank'] = self.industry_rank_input.value()
        if self.industry_eps_rank_input.text().strip():
            self.result_data['industry_eps_rank'] = self.industry_eps_rank_input.text().strip()
        if self.industry_rs_rank_input.text().strip():
            self.result_data['industry_rs_rank'] = self.industry_rs_rank_input.text().strip()
        
        # Institutional
        if self.fund_count_input.value() > 0:
            self.result_data['fund_count'] = self.fund_count_input.value()
        if self.funds_qtr_chg_input.value() != 0:
            self.result_data['funds_qtr_chg'] = self.funds_qtr_chg_input.value()
        if self.prior_uptrend_input.value() > 0:
            self.result_data['prior_uptrend'] = self.prior_uptrend_input.value()
        
        # Breakout quality
        if self.breakout_vol_pct_input.value() > 0:
            self.result_data['breakout_vol_pct'] = self.breakout_vol_pct_input.value()
        if self.breakout_price_pct_input.value() != 0:
            self.result_data['breakout_price_pct'] = self.breakout_price_pct_input.value()
        
        # Earnings date
        # Breakout date
        breakout_date = self.breakout_date_input.date()
        if breakout_date != self.breakout_date_input.minimumDate():
            self.result_data['breakout_date'] = date(
                breakout_date.year(), breakout_date.month(), breakout_date.day()
            )
        
        # Earnings date
        earnings_date = self.earnings_date_input.date()
        if earnings_date != self.earnings_date_input.minimumDate():
            self.result_data['earnings_date'] = date(
                earnings_date.year(), earnings_date.month(), earnings_date.day()
            )
        
        # Notes
        if self.notes_input.toPlainText():
            self.result_data['notes'] = self.notes_input.toPlainText()
        
        self.accept()
    
    def get_result(self) -> Dict[str, Any]:
        """Get the collected data."""
        return self.result_data


class EditPositionDialog(QDialog):
    """
    Dialog for editing all fields of an existing position.
    Modeless dialog - can be used independently of main window.
    """
    
    def __init__(self, position_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.position_data = position_data.copy()
        self.result_data: Dict[str, Any] = {}
        
        # Make dialog independent (modeless)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        
        self._setup_ui()
        self._populate_fields()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        symbol = self.position_data.get('symbol', 'Unknown')
        self.setWindowTitle(f"Edit Position: {symbol}")
        self.setMinimumWidth(550)
        self.setMinimumHeight(600)
        
        # Apply light theme styling for better readability
        self.setStyleSheet("""
            QDialog {
                background-color: #F5F5F5;
            }
            QGroupBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
                color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #333333;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QLineEdit:focus {
                border: 1px solid #0078D4;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #0078D4;
            }
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QComboBox:focus {
                border: 1px solid #0078D4;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                color: #333333;
                selection-background-color: #0078D4;
                selection-color: #FFFFFF;
            }
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                color: #333333;
            }
            QTextEdit:focus {
                border: 1px solid #0078D4;
            }
            QDateEdit {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QDateEdit:focus {
                border: 1px solid #0078D4;
            }
            QPushButton {
                background-color: #E0E0E0;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px 16px;
                color: #333333;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D0D0D0;
                border: 1px solid #0078D4;
            }
            QPushButton:pressed {
                background-color: #C0C0C0;
            }
            QScrollArea {
                border: none;
                background-color: #F5F5F5;
            }
        """)
        
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        
        # Header
        header = QLabel(f"Edit: {symbol}")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(14)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        # Setup Information
        setup_group = QGroupBox("Setup Information")
        setup_layout = QFormLayout()
        
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems([''] + VALID_PATTERNS)
        self.pattern_combo.setEditable(True)
        setup_layout.addRow("Pattern:", self.pattern_combo)
        
        self.pivot_input = QDoubleSpinBox()
        self.pivot_input.setRange(0, 100000)
        self.pivot_input.setDecimals(2)
        self.pivot_input.setPrefix("$")
        setup_layout.addRow("Pivot Price:", self.pivot_input)
        
        self.stop_price_input = QDoubleSpinBox()
        self.stop_price_input.setRange(0, 100000)
        self.stop_price_input.setDecimals(2)
        self.stop_price_input.setPrefix("$")
        setup_layout.addRow("Stop Price:", self.stop_price_input)
        
        self.stop_pct_input = QDoubleSpinBox()
        self.stop_pct_input.setRange(1, 50)
        self.stop_pct_input.setDecimals(1)
        self.stop_pct_input.setSuffix("%")
        setup_layout.addRow("Stop %:", self.stop_pct_input)
        
        # Portfolio
        self.portfolio_combo = QComboBox()
        self.portfolio_combo.addItems(['', 'Swing', 'Position', 'Paper', 'Other'])
        self.portfolio_combo.setEditable(True)
        self.portfolio_combo.setToolTip("Portfolio/account for this position")
        setup_layout.addRow("Portfolio:", self.portfolio_combo)
        
        setup_group.setLayout(setup_layout)
        layout.addWidget(setup_group)
        
        # Base Characteristics
        base_group = QGroupBox("Base Characteristics")
        base_layout = QFormLayout()
        
        self.stage_combo = QComboBox()
        self.stage_combo.addItems([''] + BASE_STAGES)
        self.stage_combo.setEditable(True)
        base_layout.addRow("Base Stage:", self.stage_combo)
        
        self.depth_input = QDoubleSpinBox()
        self.depth_input.setRange(0, 100)
        self.depth_input.setDecimals(1)
        self.depth_input.setSuffix("%")
        base_layout.addRow("Base Depth:", self.depth_input)
        
        self.length_input = QSpinBox()
        self.length_input.setRange(0, 100)
        self.length_input.setSuffix(" weeks")
        base_layout.addRow("Base Length:", self.length_input)
        
        base_group.setLayout(base_layout)
        layout.addWidget(base_group)
        
        # CANSLIM Ratings
        ratings_group = QGroupBox("CANSLIM Ratings (Left Panel)")
        ratings_layout = QHBoxLayout()
        
        # Left column - Strength Ratings
        left_layout = QFormLayout()
        
        self.rs_input = QSpinBox()
        self.rs_input.setRange(0, 99)
        left_layout.addRow("RS Rating:", self.rs_input)
        
        self.rs_3mo_input = QSpinBox()
        self.rs_3mo_input.setRange(0, 99)
        self.rs_3mo_input.setToolTip("3-Month RS Rating (from Technical panel)")
        left_layout.addRow("RS 3-Month:", self.rs_3mo_input)
        
        self.rs_6mo_input = QSpinBox()
        self.rs_6mo_input.setRange(0, 99)
        self.rs_6mo_input.setToolTip("6-Month RS Rating (from Technical panel)")
        left_layout.addRow("RS 6-Month:", self.rs_6mo_input)
        
        self.eps_input = QSpinBox()
        self.eps_input.setRange(0, 99)
        left_layout.addRow("EPS Rating:", self.eps_input)
        
        self.comp_input = QSpinBox()
        self.comp_input.setRange(0, 99)
        left_layout.addRow("Composite:", self.comp_input)
        
        self.smr_combo = QComboBox()
        self.smr_combo.addItems([''] + SMR_RATINGS)
        self.smr_combo.setToolTip("Sales/Margin/ROE Rating")
        left_layout.addRow("SMR Rating:", self.smr_combo)
        
        self.ad_combo = QComboBox()
        self.ad_combo.addItems([''] + AD_RATINGS)
        left_layout.addRow("A/D Rating:", self.ad_combo)
        
        self.ud_ratio_input = QDoubleSpinBox()
        self.ud_ratio_input.setRange(0, 10)
        self.ud_ratio_input.setDecimals(2)
        left_layout.addRow("U/D Vol Ratio:", self.ud_ratio_input)
        
        ratings_layout.addLayout(left_layout)
        
        # Right column - Industry & Institutional
        right_layout = QFormLayout()
        
        self.industry_rank_input = QSpinBox()
        self.industry_rank_input.setRange(0, 197)
        self.industry_rank_input.setToolTip("Industry 197 Rank (1=best, from Industry panel)")
        right_layout.addRow("Industry Rank:", self.industry_rank_input)
        
        self.industry_eps_rank_input = QLineEdit()
        self.industry_eps_rank_input.setPlaceholderText("e.g., 3 of 38")
        self.industry_eps_rank_input.setToolTip("EPS Rank within Industry Group")
        right_layout.addRow("EPS in Industry:", self.industry_eps_rank_input)
        
        self.industry_rs_rank_input = QLineEdit()
        self.industry_rs_rank_input.setPlaceholderText("e.g., 10 of 38")
        self.industry_rs_rank_input.setToolTip("RS Rank within Industry Group")
        right_layout.addRow("RS in Industry:", self.industry_rs_rank_input)
        
        self.fund_count_input = QSpinBox()
        self.fund_count_input.setRange(0, 10000)
        self.fund_count_input.setToolTip("Number of Funds (from Owners panel)")
        right_layout.addRow("Fund Count:", self.fund_count_input)
        
        self.funds_qtr_chg_input = QSpinBox()
        self.funds_qtr_chg_input.setRange(-9999, 9999)
        self.funds_qtr_chg_input.setToolTip("Change in fund count vs prior quarter")
        right_layout.addRow("Funds Qtr Chg:", self.funds_qtr_chg_input)
        
        self.prior_uptrend_input = QSpinBox()
        self.prior_uptrend_input.setRange(-100, 500)
        self.prior_uptrend_input.setSuffix("%")
        right_layout.addRow("Prior Uptrend:", self.prior_uptrend_input)
        
        ratings_layout.addLayout(right_layout)
        ratings_group.setLayout(ratings_layout)
        layout.addWidget(ratings_group)
        
        # Breakout Quality (NEW)
        breakout_group = QGroupBox("Breakout Quality (Pattern Rec Panel)")
        breakout_layout = QFormLayout()
        
        self.breakout_vol_pct_input = QSpinBox()
        self.breakout_vol_pct_input.setRange(-100, 9999)
        self.breakout_vol_pct_input.setSuffix("%")
        self.breakout_vol_pct_input.setToolTip("Volume % on breakout day vs 50-day avg")
        breakout_layout.addRow("Breakout Vol %:", self.breakout_vol_pct_input)
        
        self.breakout_price_pct_input = QDoubleSpinBox()
        self.breakout_price_pct_input.setRange(-50, 100)
        self.breakout_price_pct_input.setDecimals(1)
        self.breakout_price_pct_input.setSuffix("%")
        self.breakout_price_pct_input.setToolTip("Price % change on breakout day")
        breakout_layout.addRow("Breakout Price %:", self.breakout_price_pct_input)
        
        breakout_group.setLayout(breakout_layout)
        layout.addWidget(breakout_group)
        
        # Position Info (if in position)
        position_group = QGroupBox("Position Details")
        position_layout = QFormLayout()
        
        # Entry 1
        e1_row = QHBoxLayout()
        self.e1_shares_input = QSpinBox()
        self.e1_shares_input.setRange(0, 100000)
        e1_row.addWidget(QLabel("Shares:"))
        e1_row.addWidget(self.e1_shares_input)
        self.e1_price_input = QDoubleSpinBox()
        self.e1_price_input.setRange(0, 100000)
        self.e1_price_input.setDecimals(2)
        self.e1_price_input.setPrefix("$")
        e1_row.addWidget(QLabel("Price:"))
        e1_row.addWidget(self.e1_price_input)
        position_layout.addRow("Entry 1:", e1_row)
        
        # Entry 2
        e2_row = QHBoxLayout()
        self.e2_shares_input = QSpinBox()
        self.e2_shares_input.setRange(0, 100000)
        e2_row.addWidget(QLabel("Shares:"))
        e2_row.addWidget(self.e2_shares_input)
        self.e2_price_input = QDoubleSpinBox()
        self.e2_price_input.setRange(0, 100000)
        self.e2_price_input.setDecimals(2)
        self.e2_price_input.setPrefix("$")
        e2_row.addWidget(QLabel("Price:"))
        e2_row.addWidget(self.e2_price_input)
        position_layout.addRow("Entry 2:", e2_row)
        
        # Entry 3
        e3_row = QHBoxLayout()
        self.e3_shares_input = QSpinBox()
        self.e3_shares_input.setRange(0, 100000)
        e3_row.addWidget(QLabel("Shares:"))
        e3_row.addWidget(self.e3_shares_input)
        self.e3_price_input = QDoubleSpinBox()
        self.e3_price_input.setRange(0, 100000)
        self.e3_price_input.setDecimals(2)
        self.e3_price_input.setPrefix("$")
        e3_row.addWidget(QLabel("Price:"))
        e3_row.addWidget(self.e3_price_input)
        position_layout.addRow("Entry 3:", e3_row)
        
        position_group.setLayout(position_layout)
        layout.addWidget(position_group)
        
        # Dates
        dates_group = QGroupBox("Key Dates")
        dates_layout = QFormLayout()
        
        self.watch_date_input = QDateEdit()
        self.watch_date_input.setCalendarPopup(True)
        self.watch_date_input.setSpecialValueText("Not Set")
        dates_layout.addRow("Watch Date:", self.watch_date_input)
        
        self.breakout_date_input = QDateEdit()
        self.breakout_date_input.setCalendarPopup(True)
        self.breakout_date_input.setSpecialValueText("Not Set")
        dates_layout.addRow("Breakout Date:", self.breakout_date_input)
        
        self.earnings_date_input = QDateEdit()
        self.earnings_date_input.setCalendarPopup(True)
        self.earnings_date_input.setSpecialValueText("Not Set")
        dates_layout.addRow("Earnings Date:", self.earnings_date_input)
        
        dates_group.setLayout(dates_layout)
        layout.addWidget(dates_group)
        
        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(80)
        notes_layout.addWidget(self.notes_input)
        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)
        
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        button_layout.addStretch()
        
        save_btn = QPushButton("Save Changes")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        button_layout.addWidget(save_btn)
        
        main_layout.addLayout(button_layout)
    
    def _populate_fields(self):
        """Populate fields with current position data."""
        data = self.position_data
        
        # Setup
        if data.get('pattern'):
            idx = self.pattern_combo.findText(data['pattern'])
            if idx >= 0:
                self.pattern_combo.setCurrentIndex(idx)
            else:
                self.pattern_combo.setCurrentText(data['pattern'])
        
        self.pivot_input.setValue(float(data.get('pivot') or 0))
        self.stop_price_input.setValue(float(data.get('stop_price') or 0))
        self.stop_pct_input.setValue(float(data.get('hard_stop_pct') or 7.0))
        
        # Portfolio
        if data.get('portfolio'):
            idx = self.portfolio_combo.findText(data['portfolio'])
            if idx >= 0:
                self.portfolio_combo.setCurrentIndex(idx)
            else:
                self.portfolio_combo.setCurrentText(data['portfolio'])
        
        # Base
        if data.get('base_stage'):
            idx = self.stage_combo.findText(str(data['base_stage']))
            if idx >= 0:
                self.stage_combo.setCurrentIndex(idx)
            else:
                self.stage_combo.setCurrentText(str(data['base_stage']))
        
        self.depth_input.setValue(float(data.get('base_depth') or 0))
        self.length_input.setValue(int(data.get('base_length') or 0))
        
        # Ratings
        self.rs_input.setValue(int(data.get('rs_rating') or 0))
        self.rs_3mo_input.setValue(int(data.get('rs_3mo') or 0))
        self.rs_6mo_input.setValue(int(data.get('rs_6mo') or 0))
        self.eps_input.setValue(int(data.get('eps_rating') or 0))
        self.comp_input.setValue(int(data.get('comp_rating') or 0))
        
        if data.get('smr_rating'):
            idx = self.smr_combo.findText(data['smr_rating'])
            if idx >= 0:
                self.smr_combo.setCurrentIndex(idx)
        
        if data.get('ad_rating'):
            idx = self.ad_combo.findText(data['ad_rating'])
            if idx >= 0:
                self.ad_combo.setCurrentIndex(idx)
        
        self.ud_ratio_input.setValue(float(data.get('ud_vol_ratio') or 0))
        
        # Industry data (use industry_rank, fall back to group_rank for legacy data)
        industry_rank = data.get('industry_rank') or data.get('group_rank') or 0
        self.industry_rank_input.setValue(int(industry_rank))
        
        if data.get('industry_eps_rank'):
            self.industry_eps_rank_input.setText(str(data['industry_eps_rank']))
        if data.get('industry_rs_rank'):
            self.industry_rs_rank_input.setText(str(data['industry_rs_rank']))
        
        self.fund_count_input.setValue(int(data.get('fund_count') or 0))
        self.funds_qtr_chg_input.setValue(int(data.get('funds_qtr_chg') or 0))
        self.prior_uptrend_input.setValue(int(data.get('prior_uptrend') or 0))
        
        # Breakout quality
        self.breakout_vol_pct_input.setValue(int(data.get('breakout_vol_pct') or 0))
        self.breakout_price_pct_input.setValue(float(data.get('breakout_price_pct') or 0))
        
        # Position details
        self.e1_shares_input.setValue(int(data.get('e1_shares') or 0))
        self.e1_price_input.setValue(float(data.get('e1_price') or 0))
        self.e2_shares_input.setValue(int(data.get('e2_shares') or 0))
        self.e2_price_input.setValue(float(data.get('e2_price') or 0))
        self.e3_shares_input.setValue(int(data.get('e3_shares') or 0))
        self.e3_price_input.setValue(float(data.get('e3_price') or 0))
        
        # Dates
        for field, widget in [
            ('watch_date', self.watch_date_input),
            ('breakout_date', self.breakout_date_input),
            ('earnings_date', self.earnings_date_input),
        ]:
            if data.get(field):
                d = data[field]
                if isinstance(d, date):
                    widget.setDate(QDate(d.year, d.month, d.day))
        
        # Notes
        if data.get('notes'):
            self.notes_input.setPlainText(data['notes'])
    
    def _on_save(self):
        """Handle save button click."""
        # Collect all fields
        self.result_data = {
            'pattern': self.pattern_combo.currentText() or None,
            'pivot': self.pivot_input.value() or None,
            'stop_price': self.stop_price_input.value() or None,
            'hard_stop_pct': self.stop_pct_input.value() or None,
            'portfolio': self.portfolio_combo.currentText() or None,
            'base_stage': self.stage_combo.currentText() or None,
            'base_depth': self.depth_input.value() or None,
            'base_length': self.length_input.value() or None,
            # Ratings
            'rs_rating': self.rs_input.value() or None,
            'rs_3mo': self.rs_3mo_input.value() or None,
            'rs_6mo': self.rs_6mo_input.value() or None,
            'eps_rating': self.eps_input.value() or None,
            'comp_rating': self.comp_input.value() or None,
            'smr_rating': self.smr_combo.currentText() or None,
            'ad_rating': self.ad_combo.currentText() or None,
            'ud_vol_ratio': self.ud_ratio_input.value() or None,
            # Industry
            'industry_rank': self.industry_rank_input.value() or None,
            'industry_eps_rank': self.industry_eps_rank_input.text().strip() or None,
            'industry_rs_rank': self.industry_rs_rank_input.text().strip() or None,
            # Institutional
            'fund_count': self.fund_count_input.value() or None,
            'funds_qtr_chg': self.funds_qtr_chg_input.value() or None,
            'prior_uptrend': self.prior_uptrend_input.value() or None,
            # Breakout quality
            'breakout_vol_pct': self.breakout_vol_pct_input.value() or None,
            'breakout_price_pct': self.breakout_price_pct_input.value() or None,
            # Position
            'e1_shares': self.e1_shares_input.value() or None,
            'e1_price': self.e1_price_input.value() or None,
            'e2_shares': self.e2_shares_input.value() or None,
            'e2_price': self.e2_price_input.value() or None,
            'e3_shares': self.e3_shares_input.value() or None,
            'e3_price': self.e3_price_input.value() or None,
            'notes': self.notes_input.toPlainText() or None,
        }
        
        # Dates
        for field, widget in [
            ('watch_date', self.watch_date_input),
            ('breakout_date', self.breakout_date_input),
            ('earnings_date', self.earnings_date_input),
        ]:
            qdate = widget.date()
            if qdate != widget.minimumDate():
                self.result_data[field] = date(qdate.year(), qdate.month(), qdate.day())
        
        self.accept()
    
    def get_result(self) -> Dict[str, Any]:
        """Get the updated data."""
        return self.result_data
