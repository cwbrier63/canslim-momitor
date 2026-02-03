"""
CANSLIM Monitor - Change Indicator Widget

Shows a small △ indicator next to fields that have changed.
Clicking the indicator shows a popup with the field's change history.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QPushButton, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QFont, QCursor


class ChangeIndicator(QLabel):
    """
    Small clickable △ indicator that shows when a field has changed.

    Signals:
        clicked: Emitted when the indicator is clicked
    """

    clicked = pyqtSignal()

    def __init__(
        self,
        field_name: str,
        position_id: int,
        has_history: bool = False,
        parent=None
    ):
        super().__init__(parent)
        self.field_name = field_name
        self.position_id = position_id
        self._has_history = has_history

        self._setup_ui()

    def _setup_ui(self):
        """Set up the indicator UI."""
        self.setText("△")
        self.setFixedSize(14, 14)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self._has_history:
            self.setStyleSheet("""
                QLabel {
                    color: #FF9800;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 0px;
                }
                QLabel:hover {
                    color: #FFC107;
                }
            """)
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.setToolTip(f"Click to see {self.field_name} history")
        else:
            # Hidden state - no history
            self.setStyleSheet("""
                QLabel {
                    color: transparent;
                    font-size: 10px;
                }
            """)
            self.setToolTip("")

    def set_has_history(self, has_history: bool):
        """Update the indicator visibility based on whether there's history."""
        self._has_history = has_history
        self._setup_ui()

    def mousePressEvent(self, event):
        """Handle mouse press to emit clicked signal."""
        if self._has_history and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class FieldHistoryPopup(QFrame):
    """
    Popup window showing the history of changes for a specific field.

    Displays a list of changes with timestamps and values.
    """

    def __init__(
        self,
        field_name: str,
        current_value: Any,
        history: List[Dict[str, Any]],
        parent=None
    ):
        super().__init__(parent)
        self.field_name = field_name
        self.current_value = current_value
        self.history = history

        self._setup_ui()

    def _setup_ui(self):
        """Set up the popup UI."""
        self.setWindowFlags(
            Qt.WindowType.Popup |
            Qt.WindowType.FramelessWindowHint
        )
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setLineWidth(1)

        self.setStyleSheet("""
            QFrame {
                background-color: #2D2D30;
                border: 1px solid #3F3F46;
                border-radius: 6px;
            }
            QLabel {
                color: #CCCCCC;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header with field name
        header = QLabel(f"{self._format_field_name(self.field_name)} History")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(10)
        header.setFont(header_font)
        header.setStyleSheet("color: #FFFFFF; padding-bottom: 4px;")
        layout.addWidget(header)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #3F3F46;")
        line.setFixedHeight(1)
        layout.addWidget(line)

        # Current value
        current_row = QHBoxLayout()
        current_label = QLabel(self._format_value(self.current_value))
        current_label.setStyleSheet("color: #4FC3F7; font-weight: bold;")
        current_row.addWidget(current_label)
        current_row.addStretch()
        current_indicator = QLabel("← Current")
        current_indicator.setStyleSheet("color: #81C784; font-size: 9px;")
        current_row.addWidget(current_indicator)
        layout.addLayout(current_row)

        # History entries
        if self.history:
            for entry in self.history[:10]:  # Limit to 10 entries
                entry_row = QHBoxLayout()

                # Old value
                old_value = entry.get('old_value', '?')
                value_label = QLabel(self._format_value(old_value))
                value_label.setStyleSheet("color: #AAAAAA;")
                entry_row.addWidget(value_label)

                entry_row.addStretch()

                # Timestamp and source
                changed_at = entry.get('changed_at')
                source = entry.get('change_source', '')

                time_text = self._format_time_ago(changed_at) if changed_at else '?'
                source_text = f" ({source})" if source else ""

                meta_label = QLabel(f"{time_text}{source_text}")
                meta_label.setStyleSheet("color: #888888; font-size: 9px;")
                entry_row.addWidget(meta_label)

                layout.addLayout(entry_row)
        else:
            no_history = QLabel("No prior changes recorded")
            no_history.setStyleSheet("color: #888888; font-style: italic;")
            layout.addWidget(no_history)

        # Close hint
        hint = QLabel("Click anywhere to close")
        hint.setStyleSheet("color: #666666; font-size: 8px; padding-top: 4px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self.adjustSize()
        self.setMinimumWidth(200)

    def _format_field_name(self, field_name: str) -> str:
        """Format field name for display."""
        # Convert snake_case to Title Case
        return field_name.replace('_', ' ').title()

    def _format_value(self, value: Any) -> str:
        """Format a value for display."""
        if value is None:
            return "—"
        if isinstance(value, str):
            # Check if it's a price (looks like a number)
            try:
                num = float(value)
                if '.' in value and num > 1:
                    return f"${num:.2f}"
                return value
            except ValueError:
                return value
        if isinstance(value, float):
            if value > 1:
                return f"${value:.2f}"
            return f"{value:.2f}"
        return str(value)

    def _format_time_ago(self, dt: datetime) -> str:
        """Format a datetime as relative time (e.g., '2d ago')."""
        if not dt:
            return "?"

        # Handle string datetime
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                return dt

        now = datetime.now()
        delta = now - dt

        if delta < timedelta(minutes=1):
            return "just now"
        elif delta < timedelta(hours=1):
            mins = int(delta.total_seconds() / 60)
            return f"{mins}m ago"
        elif delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h ago"
        elif delta < timedelta(days=30):
            days = delta.days
            return f"{days}d ago"
        else:
            return dt.strftime("%b %d")

    def mousePressEvent(self, event):
        """Close popup on any click."""
        self.close()


class FieldWithHistory(QWidget):
    """
    A composite widget that combines a value label with a change indicator.

    Use this to display a field value with its change history indicator.
    """

    indicator_clicked = pyqtSignal(str, int)  # field_name, position_id

    def __init__(
        self,
        field_name: str,
        position_id: int,
        value: Any,
        format_func=None,
        has_history: bool = False,
        parent=None
    ):
        super().__init__(parent)
        self.field_name = field_name
        self.position_id = position_id
        self._value = value
        self._format_func = format_func or str
        self._has_history = has_history

        self._setup_ui()

    def _setup_ui(self):
        """Set up the composite widget."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Value label
        self._value_label = QLabel(self._format_func(self._value))
        layout.addWidget(self._value_label)

        # Change indicator
        self._indicator = ChangeIndicator(
            self.field_name,
            self.position_id,
            self._has_history
        )
        self._indicator.clicked.connect(self._on_indicator_clicked)
        layout.addWidget(self._indicator)

        layout.addStretch()

    def _on_indicator_clicked(self):
        """Handle indicator click - emit signal for parent to show popup."""
        self.indicator_clicked.emit(self.field_name, self.position_id)

    def set_value(self, value: Any):
        """Update the displayed value."""
        self._value = value
        self._value_label.setText(self._format_func(value))

    def set_has_history(self, has_history: bool):
        """Update the indicator based on history availability."""
        self._has_history = has_history
        self._indicator.set_has_history(has_history)

    def show_history_popup(self, current_value: Any, history: List[Dict[str, Any]]):
        """Show the history popup at the indicator position."""
        popup = FieldHistoryPopup(
            self.field_name,
            current_value,
            history,
            self
        )

        # Position popup near the indicator
        indicator_pos = self._indicator.mapToGlobal(QPoint(0, 0))
        popup.move(indicator_pos.x() + 20, indicator_pos.y() - 10)
        popup.show()
