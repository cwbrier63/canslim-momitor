"""
CANSLIM Monitor - Kanban Column Widget
Drop target column for the Kanban board.
"""

from typing import List, Optional, Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy, QPushButton, QLineEdit, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent

from canslim_monitor.gui.state_config import STATES, is_valid_transition, VALID_PATTERNS


class KanbanColumn(QFrame):
    """
    A column in the Kanban board representing a position state.
    
    Signals:
        position_dropped: Emitted when a position is dropped (position_id, from_state, to_state)
        card_clicked: Emitted when a card is clicked (position_id)
        card_double_clicked: Emitted when a card is double-clicked (position_id)
        card_context_menu: Emitted for right-click menu (position_id, global_pos)
        card_alert_clicked: Emitted when alert row is clicked (alert_id, position_id)
    """
    
    position_dropped = pyqtSignal(int, int, int)  # position_id, from_state, to_state
    card_clicked = pyqtSignal(int)
    card_double_clicked = pyqtSignal(int)
    card_context_menu = pyqtSignal(int, object)  # position_id, QPoint
    card_alert_clicked = pyqtSignal(int, int)  # alert_id, position_id
    add_clicked = pyqtSignal(int)  # state
    view_toggled = pyqtSignal(float)  # emits new state being shown (-1.5 or 0)
    
    def __init__(
        self,
        state: int,
        title: str,
        color: str,
        parent=None
    ):
        super().__init__(parent)
        
        self.state = state
        self.title = title
        self.color = color
        self.cards: List['PositionCard'] = []
        self._all_cards: List['PositionCard'] = []  # Keep track of all cards for filtering

        # Toggle state for Watching/Exited Watch column (state 0 can toggle to -1.5)
        self._base_state = state  # Original state (0 for watching column)
        self._showing_exited_watch = False  # True when showing State -1.5

        # Filter state
        self._symbol_filter = ""
        self._pattern_filter = ""
        self._sort_by = "symbol"
        self._has_alert_filter = False
        self._alert_type_filter = ""

        self._setup_ui()
        self.setAcceptDrops(True)
    
    def _setup_ui(self):
        """Set up the column UI."""
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        self.setStyleSheet(f"""
            KanbanColumn {{
                background-color: #F8F9FA;
                border: 1px solid #DEE2E6;
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        
        # Header
        header_layout = QHBoxLayout()

        # Color indicator
        self.color_bar = QFrame()
        self.color_bar.setFixedSize(4, 20)
        self.color_bar.setStyleSheet(f"background-color: {self.color}; border-radius: 2px;")
        header_layout.addWidget(self.color_bar)

        # Title
        self.title_label = QLabel(self.title)
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        header_layout.addWidget(self.title_label)

        # Toggle button for Watching column (state 0) to switch to Exited Watch (-1.5)
        if self.state == 0:
            self.toggle_btn = QPushButton("⇄")
            self.toggle_btn.setToolTip("Toggle: Watching ↔ Exited Watch")
            self.toggle_btn.setFixedSize(22, 22)
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: 1px solid #9C27B0;
                    color: #9C27B0;
                    border-radius: 3px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #F3E5F5;
                }
                QPushButton:pressed {
                    background-color: #E1BEE7;
                }
            """)
            self.toggle_btn.clicked.connect(self._on_toggle_view)
            header_layout.addWidget(self.toggle_btn)

        header_layout.addStretch()

        # Count badge
        self.count_label = QLabel("0")
        self.count_label.setStyleSheet(f"""
            background-color: {self.color};
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        """)
        header_layout.addWidget(self.count_label)

        layout.addLayout(header_layout)
        
        # Add button (only for watchlist column)
        if self.state == 0:
            add_btn = QPushButton("+ Add")
            add_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: 1px dashed #17A2B8;
                    color: #17A2B8;
                    padding: 4px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #E7F5F8;
                }
            """)
            add_btn.clicked.connect(lambda: self.add_clicked.emit(self.state))
            layout.addWidget(add_btn)
        
        # Filter/Sort Controls
        filter_frame = QFrame()
        filter_frame.setStyleSheet("background-color: #EAECEF; border-radius: 4px; padding: 2px;")
        filter_layout = QVBoxLayout(filter_frame)
        filter_layout.setContentsMargins(4, 4, 4, 4)
        filter_layout.setSpacing(4)
        
        # Symbol filter (text input)
        self.symbol_filter_input = QLineEdit()
        self.symbol_filter_input.setPlaceholderText("🔍 Filter by symbol...")
        self.symbol_filter_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CED4DA;
                border-radius: 3px;
                padding: 3px 6px;
                background: white;
                font-size: 11px;
            }
        """)
        self.symbol_filter_input.textChanged.connect(self._on_symbol_filter_changed)
        filter_layout.addWidget(self.symbol_filter_input)
        
        # Second row: Pattern filter + Sort
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(4)
        
        # Pattern filter dropdown
        self.pattern_filter_combo = QComboBox()
        self.pattern_filter_combo.addItem("All Patterns", "")
        for pattern in VALID_PATTERNS:
            self.pattern_filter_combo.addItem(pattern, pattern)
        self.pattern_filter_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #CED4DA;
                border-radius: 3px;
                padding: 2px 4px;
                background: white;
                font-size: 10px;
                min-width: 80px;
            }
        """)
        self.pattern_filter_combo.currentIndexChanged.connect(self._on_pattern_filter_changed)
        row2_layout.addWidget(self.pattern_filter_combo)
        
        # Sort dropdown
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Sort: Symbol", "symbol")
        self.sort_combo.addItem("Sort: RS ↓", "rs_desc")
        self.sort_combo.addItem("Sort: RS ↑", "rs_asc")
        self.sort_combo.addItem("Sort: Alert", "alert")
        self.sort_combo.addItem("Sort: Grade", "grade")
        self.sort_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #CED4DA;
                border-radius: 3px;
                padding: 2px 4px;
                background: white;
                font-size: 10px;
                min-width: 70px;
            }
        """)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        row2_layout.addWidget(self.sort_combo)
        
        filter_layout.addLayout(row2_layout)
        
        # Third row: Alert filter checkbox + Alert type
        row3_layout = QHBoxLayout()
        row3_layout.setSpacing(4)
        
        self.alert_filter_btn = QPushButton("🔔 With Alerts")
        self.alert_filter_btn.setCheckable(True)
        self.alert_filter_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #CED4DA;
                border-radius: 3px;
                padding: 2px 6px;
                background: white;
                font-size: 10px;
            }
            QPushButton:checked {
                background: #FFC107;
                border-color: #FFA000;
            }
        """)
        self.alert_filter_btn.clicked.connect(self._on_alert_filter_changed)
        row3_layout.addWidget(self.alert_filter_btn)
        
        # Alert type filter dropdown
        self.alert_type_combo = QComboBox()
        self.alert_type_combo.addItem("All Types", "")
        self.alert_type_combo.addItem("🚀 Breakout", "BREAKOUT")
        self.alert_type_combo.addItem("📈 Pyramid", "PYRAMID")
        self.alert_type_combo.addItem("💰 Profit", "PROFIT")
        self.alert_type_combo.addItem("🛑 Stop", "STOP")
        self.alert_type_combo.addItem("📊 Technical", "TECHNICAL")
        self.alert_type_combo.addItem("🌐 Market", "MARKET")
        self.alert_type_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #CED4DA;
                border-radius: 3px;
                padding: 2px 4px;
                background: white;
                font-size: 10px;
                min-width: 70px;
            }
        """)
        self.alert_type_combo.currentIndexChanged.connect(self._on_alert_type_filter_changed)
        row3_layout.addWidget(self.alert_type_combo)
        
        row3_layout.addStretch()
        filter_layout.addLayout(row3_layout)
        
        # Fourth row: Clear button
        row4_layout = QHBoxLayout()
        row4_layout.setSpacing(4)
        
        # Clear filters button
        clear_btn = QPushButton("✕ Clear")
        clear_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #CED4DA;
                border-radius: 3px;
                padding: 2px 6px;
                background: white;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #FFEBEE;
            }
        """)
        clear_btn.clicked.connect(self._clear_filters)
        row4_layout.addWidget(clear_btn)
        
        row4_layout.addStretch()
        filter_layout.addLayout(row4_layout)
        
        layout.addWidget(filter_frame)
        
        # Scroll area for cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        # Container for cards
        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(6)
        self.card_layout.addStretch()
        
        scroll.setWidget(self.card_container)
        layout.addWidget(scroll)
    
    def _on_symbol_filter_changed(self, text: str):
        """Handle symbol filter text change."""
        self._symbol_filter = text.upper().strip()
        self._apply_filters()
    
    def _on_pattern_filter_changed(self, index: int):
        """Handle pattern filter change."""
        self._pattern_filter = self.pattern_filter_combo.currentData() or ""
        self._apply_filters()
    
    def _on_sort_changed(self, index: int):
        """Handle sort change."""
        self._sort_by = self.sort_combo.currentData() or "symbol"
        self._apply_filters()
    
    def _on_alert_filter_changed(self):
        """Handle alert filter toggle."""
        self._has_alert_filter = self.alert_filter_btn.isChecked()
        self._apply_filters()
    
    def _on_alert_type_filter_changed(self, index: int):
        """Handle alert type filter change."""
        self._alert_type_filter = self.alert_type_combo.currentData() or ""
        self._apply_filters()
    
    def _clear_filters(self):
        """Clear all filters."""
        self.symbol_filter_input.clear()
        self.pattern_filter_combo.setCurrentIndex(0)
        self.sort_combo.setCurrentIndex(0)
        self.alert_filter_btn.setChecked(False)
        self.alert_type_combo.setCurrentIndex(0)

        self._symbol_filter = ""
        self._pattern_filter = ""
        self._sort_by = "symbol"
        self._has_alert_filter = False
        self._alert_type_filter = ""

        self._apply_filters()

    def _on_toggle_view(self):
        """Toggle between Watching (State 0) and Exited Watch (State -1.5)."""
        if self._base_state != 0:
            return  # Only state 0 column can toggle

        self._showing_exited_watch = not self._showing_exited_watch

        if self._showing_exited_watch:
            # Switch to Exited Watch view
            self.state = -1.5
            new_title = "Exited Watch"
            new_color = "#9C27B0"  # Purple
            self.toggle_btn.setToolTip("Toggle: Exited Watch → Watching")
        else:
            # Switch back to Watching view
            self.state = 0
            new_title = "Watching"
            new_color = "#17A2B8"  # Cyan
            self.toggle_btn.setToolTip("Toggle: Watching → Exited Watch")

        # Update appearance
        self.title = new_title
        self.color = new_color
        self.title_label.setText(new_title)
        self.color_bar.setStyleSheet(f"background-color: {new_color}; border-radius: 2px;")
        self.count_label.setStyleSheet(f"""
            background-color: {new_color};
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        """)

        # Emit signal so KanbanWindow can reload positions
        self.view_toggled.emit(self.state)

    def is_showing_exited_watch(self) -> bool:
        """Return True if this column is showing Exited Watch (State -1.5)."""
        return self._showing_exited_watch

    def get_displayed_state(self) -> float:
        """Return the state currently being displayed (0 or -1.5 for watching column)."""
        return self.state

    def _apply_filters(self):
        """Apply current filters and sorting to cards."""
        # Filter cards
        visible_cards = []
        for card in self._all_cards:
            if self._card_matches_filters(card):
                visible_cards.append(card)
        
        # Sort cards
        visible_cards = self._sort_cards(visible_cards)
        
        # Remove all cards from layout
        for card in self._all_cards:
            self.card_layout.removeWidget(card)
            card.setVisible(False)
        
        # Re-add visible cards in sorted order
        for card in visible_cards:
            self.card_layout.insertWidget(self.card_layout.count() - 1, card)
            card.setVisible(True)
        
        # Update visible cards list
        self.cards = visible_cards
        self._update_count()
    
    def _card_matches_filters(self, card: 'PositionCard') -> bool:
        """Check if a card matches current filters."""
        # Symbol filter
        if self._symbol_filter:
            if self._symbol_filter not in card.symbol.upper():
                return False
        
        # Pattern filter
        if self._pattern_filter:
            card_pattern = getattr(card, 'pattern', '') or ''
            if self._pattern_filter.lower() not in card_pattern.lower():
                return False
        
        # Alert filter (has any unacknowledged alert)
        if self._has_alert_filter:
            has_alert = getattr(card, 'has_unacknowledged_alert', False)
            if not has_alert:
                return False
        
        # Alert type filter
        if self._alert_type_filter:
            latest_alert = getattr(card, 'latest_alert', None)
            if not latest_alert:
                return False
            alert_type = latest_alert.get('alert_type', '')
            if alert_type != self._alert_type_filter:
                return False
        
        return True
    
    def _sort_cards(self, cards: List['PositionCard']) -> List['PositionCard']:
        """Sort cards based on current sort setting."""
        if self._sort_by == "symbol":
            return sorted(cards, key=lambda c: c.symbol)
        elif self._sort_by == "rs_desc":
            return sorted(cards, key=lambda c: getattr(c, 'rs_rating', 0) or 0, reverse=True)
        elif self._sort_by == "rs_asc":
            return sorted(cards, key=lambda c: getattr(c, 'rs_rating', 0) or 0)
        elif self._sort_by == "alert":
            # Cards with alerts first
            return sorted(cards, key=lambda c: (not getattr(c, 'has_unacknowledged_alert', False), c.symbol))
        elif self._sort_by == "grade":
            grade_order = {'A+': 0, 'A': 1, 'B+': 2, 'B': 3, 'C+': 4, 'C': 5, 'D': 6, 'F': 7, '': 8, None: 9}
            return sorted(cards, key=lambda c: grade_order.get(getattr(c, 'grade', ''), 8))
        return cards
    
    def add_card(self, card: 'PositionCard'):
        """Add a position card to the column."""
        # Connect card signals
        card.clicked.connect(self.card_clicked.emit)
        card.double_clicked.connect(self.card_double_clicked.emit)
        card.context_menu_requested.connect(self.card_context_menu.emit)
        card.alert_clicked.connect(self.card_alert_clicked.emit)
        
        # Add to all cards list
        self._all_cards.append(card)
        
        # Apply filters (this will add to visible cards if it matches)
        self._apply_filters()
    
    def remove_card(self, position_id: int) -> Optional['PositionCard']:
        """Remove a card by position ID."""
        for card in self._all_cards:
            if card.position_id == position_id:
                self.card_layout.removeWidget(card)
                self._all_cards.remove(card)
                if card in self.cards:
                    self.cards.remove(card)
                card.setParent(None)
                self._update_count()
                return card
        return None
    
    def clear_cards(self):
        """Remove all cards."""
        for card in self._all_cards[:]:
            self.card_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._all_cards.clear()
        self.cards.clear()
        self._update_count()
    
    def _update_count(self):
        """Update the count badge."""
        visible = len(self.cards)
        total = len(self._all_cards)
        if visible == total:
            self.count_label.setText(str(total))
        else:
            self.count_label.setText(f"{visible}/{total}")
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter - check if drop is valid."""
        mime = event.mimeData()
        if mime.hasText():
            try:
                text = mime.text()
                position_id, from_state = text.split(':')
                from_state = int(from_state)
                
                # Check if transition is valid
                if is_valid_transition(from_state, self.state):
                    event.acceptProposedAction()
                    self.setStyleSheet(f"""
                        KanbanColumn {{
                            background-color: #E8F5E9;
                            border: 2px solid {self.color};
                            border-radius: 8px;
                        }}
                    """)
                else:
                    event.ignore()
                    self.setStyleSheet(f"""
                        KanbanColumn {{
                            background-color: #FFEBEE;
                            border: 2px dashed #DC3545;
                            border-radius: 8px;
                        }}
                    """)
            except:
                event.ignore()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """Reset styling when drag leaves."""
        self.setStyleSheet(f"""
            KanbanColumn {{
                background-color: #F8F9FA;
                border: 1px solid #DEE2E6;
                border-radius: 8px;
            }}
        """)
    
    def dropEvent(self, event: QDropEvent):
        """Handle drop - emit signal for state transition."""
        mime = event.mimeData()
        if mime.hasText():
            try:
                text = mime.text()
                position_id, from_state = text.split(':')
                position_id = int(position_id)
                from_state = int(from_state)
                
                if is_valid_transition(from_state, self.state):
                    event.acceptProposedAction()
                    self.position_dropped.emit(position_id, from_state, self.state)
            except Exception as e:
                print(f"Drop error: {e}")
        
        # Reset styling
        self.setStyleSheet(f"""
            KanbanColumn {{
                background-color: #F8F9FA;
                border: 1px solid #DEE2E6;
                border-radius: 8px;
            }}
        """)


class ClosedPositionsPanel(QFrame):
    """
    Panel for displaying closed/stopped positions (collapsed by default).
    Cards have fixed width and scroll horizontally. Includes a symbol filter.
    """

    card_clicked = pyqtSignal(int)
    card_double_clicked = pyqtSignal(int)
    card_context_menu = pyqtSignal(int, object)  # position_id, QPoint
    card_alert_clicked = pyqtSignal(int, int)  # alert_id, position_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards: List[PositionCard] = []       # visible (filtered) cards
        self._all_cards: List[PositionCard] = []   # all cards before filtering
        self._expanded = False
        self._symbol_filter = ""
        self._setup_ui()

    def _setup_ui(self):
        """Set up the panel UI."""
        self.setStyleSheet("""
            ClosedPositionsPanel {
                background-color: #F8F9FA;
                border: 1px solid #DEE2E6;
                border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header (clickable to expand/collapse)
        header = QHBoxLayout()

        self.expand_btn = QPushButton("▶")
        self.expand_btn.setFixedSize(20, 20)
        self.expand_btn.setStyleSheet("border: none;")
        self.expand_btn.clicked.connect(self._toggle_expand)
        header.addWidget(self.expand_btn)

        title = QLabel("Closed Positions")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)

        header.addStretch()

        self.count_label = QLabel("0")
        self.count_label.setStyleSheet("""
            background-color: #6C757D;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        """)
        header.addWidget(self.count_label)

        layout.addLayout(header)

        # Expandable content container (filter + scroll area)
        self._content_widget = QWidget()
        self._content_widget.setVisible(False)
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 4, 0, 0)
        content_layout.setSpacing(4)

        # Symbol filter input
        self.symbol_filter_input = QLineEdit()
        self.symbol_filter_input.setPlaceholderText("Filter by symbol...")
        self.symbol_filter_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CED4DA;
                border-radius: 3px;
                padding: 3px 6px;
                background: white;
                font-size: 11px;
            }
        """)
        self.symbol_filter_input.textChanged.connect(self._on_symbol_filter_changed)
        content_layout.addWidget(self.symbol_filter_input)

        # Scroll area for cards (horizontal scrolling)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(170)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)

        # Card container inside scroll area
        self.card_container = QWidget()
        self.card_layout = QHBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(8)
        self.card_layout.addStretch()

        scroll.setWidget(self.card_container)
        content_layout.addWidget(scroll)

        layout.addWidget(self._content_widget)

    def _toggle_expand(self):
        """Toggle expanded/collapsed state."""
        self._expanded = not self._expanded
        self._content_widget.setVisible(self._expanded)
        self.expand_btn.setText("▼" if self._expanded else "▶")

    def _on_symbol_filter_changed(self, text: str):
        """Handle symbol filter text change."""
        self._symbol_filter = text.upper().strip()
        self._apply_filter()

    def _apply_filter(self):
        """Apply symbol filter to cards."""
        visible_cards = []
        for card in self._all_cards:
            matches = not self._symbol_filter or self._symbol_filter in card.symbol.upper()
            card.setVisible(matches)
            if matches:
                visible_cards.append(card)
        self.cards = visible_cards
        self._update_count()

    def add_card(self, card: PositionCard):
        """Add a position card."""
        card.clicked.connect(self.card_clicked.emit)
        card.double_clicked.connect(self.card_double_clicked.emit)
        card.context_menu_requested.connect(self.card_context_menu.emit)
        card.alert_clicked.connect(self.card_alert_clicked.emit)
        card.setFixedWidth(200)
        card.setMinimumWidth(200)

        # Insert before the stretch at the end
        self.card_layout.insertWidget(self.card_layout.count() - 1, card)
        self._all_cards.append(card)
        self._apply_filter()

    def clear_cards(self):
        """Remove all cards."""
        for card in self._all_cards[:]:
            self.card_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._all_cards.clear()
        self.cards.clear()
        self._update_count()

    def _update_count(self):
        """Update the count badge."""
        visible = len(self.cards)
        total = len(self._all_cards)
        if visible == total:
            self.count_label.setText(str(total))
        else:
            self.count_label.setText(f"{visible}/{total}")
