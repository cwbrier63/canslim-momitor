"""
CANSLIM Monitor - Position Card Widget
Draggable card representing a position in the Kanban board.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QMenu, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QPoint
from PyQt6.QtGui import QDrag, QFont, QColor, QPalette, QCursor

from canslim_monitor.gui.state_config import STATES, PositionState


class PositionCard(QFrame):
    """
    Draggable card widget representing a position.
    
    Signals:
        clicked: Emitted when card is clicked (for editing)
        double_clicked: Emitted when card is double-clicked
        context_menu_requested: Emitted for right-click menu
        alert_clicked: Emitted when alert row is clicked (for acknowledgment)
    """
    
    clicked = pyqtSignal(int)  # position_id
    double_clicked = pyqtSignal(int)  # position_id
    context_menu_requested = pyqtSignal(int, QPoint)  # position_id, global_pos
    alert_clicked = pyqtSignal(int, int)  # alert_id, position_id
    
    def __init__(
        self,
        position_id: int,
        symbol: str,
        state: int,
        pattern: str = None,
        pivot: float = None,
        last_price: float = None,
        pnl_pct: float = None,
        rs_rating: int = None,
        total_shares: int = None,
        avg_cost: float = None,
        watch_date=None,
        entry_date=None,
        portfolio: str = None,
        entry_grade: str = None,
        entry_score: int = None,
        latest_alert: dict = None,  # NEW: Latest alert from database
        parent=None
    ):
        super().__init__(parent)
        
        self.position_id = position_id
        self.symbol = symbol
        self.state = state
        self.pattern = pattern
        self.pivot = pivot
        self.last_price = last_price
        self.pnl_pct = pnl_pct
        self.rs_rating = rs_rating
        self.total_shares = total_shares
        self.avg_cost = avg_cost
        self.watch_date = watch_date
        self.entry_date = entry_date
        self.portfolio = portfolio
        self.entry_grade = entry_grade
        self.entry_score = entry_score
        self.latest_alert = latest_alert  # NEW

        # Labels that need incremental updates (stored for performance)
        self._price_label = None
        self._pnl_label = None
        self._current_label = None  # For watching state

        self._setup_ui()
        self._apply_style()
        
        # Enable drag
        self.setAcceptDrops(False)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
    
    @property
    def grade(self) -> str:
        """Alias for entry_grade for filtering compatibility."""
        return self.entry_grade or ''
    
    @property
    def has_unacknowledged_alert(self) -> bool:
        """Check if this card has an unacknowledged alert."""
        if not self.latest_alert:
            return False
        return not self.latest_alert.get('acknowledged', True)
    
    @property
    def alert_type(self) -> str:
        """Get the alert type of the latest alert."""
        if not self.latest_alert:
            return ''
        return self.latest_alert.get('alert_type', '')
    
    def _setup_ui(self):
        """Set up the card UI."""
        from datetime import date
        
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setMinimumHeight(100)  # Increased for alert row
        self.setMaximumHeight(160)  # Increased for alert row
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        
        # Top row: Symbol, Grade, and RS rating
        top_row = QHBoxLayout()
        
        self.symbol_label = QLabel(self.symbol)
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        self.symbol_label.setFont(font)
        top_row.addWidget(self.symbol_label)
        
        # Entry grade badge
        if self.entry_grade:
            grade_label = QLabel(self.entry_grade)
            grade_label.setStyleSheet(self._get_grade_style())
            grade_label.setToolTip(f"Entry Score: {self.entry_score or '?'}/100")
            top_row.addWidget(grade_label)
        
        top_row.addStretch()
        
        if self.rs_rating:
            rs_label = QLabel(f"RS: {self.rs_rating}")
            rs_label.setStyleSheet(self._get_rs_style())
            top_row.addWidget(rs_label)
        
        layout.addLayout(top_row)
        
        # Pattern and Portfolio row
        if self.pattern or self.portfolio:
            info_row = QHBoxLayout()
            info_row.setSpacing(8)
            
            if self.pattern:
                pattern_label = QLabel(self.pattern)
                pattern_label.setStyleSheet("color: #666; font-size: 10px;")
                info_row.addWidget(pattern_label)
            
            info_row.addStretch()
            
            if self.portfolio:
                portfolio_label = QLabel(self.portfolio)
                portfolio_label.setStyleSheet(self._get_portfolio_style())
                info_row.addWidget(portfolio_label)
            
            layout.addLayout(info_row)
        
        # Different display for Watching vs In Position
        if self.state == 0:  # Watching
            # Price row: Pivot and Current Price
            price_row = QHBoxLayout()
            if self.pivot:
                pivot_label = QLabel(f"Pivot: ${self.pivot:.2f}")
                pivot_label.setStyleSheet("color: #333; font-size: 10px;")
                price_row.addWidget(pivot_label)

            # Current price label (stored for incremental updates)
            self._current_label = QLabel(f"Now: ${self.last_price:.2f}" if self.last_price else "Now: --")
            self._current_label.setStyleSheet("color: #17A2B8; font-size: 10px;")
            price_row.addWidget(self._current_label)

            price_row.addStretch()
            layout.addLayout(price_row)
            
            # Days watching
            if self.watch_date:
                try:
                    if isinstance(self.watch_date, date):
                        days = (date.today() - self.watch_date).days
                        days_label = QLabel(f"{days}d watching")
                        days_label.setStyleSheet("color: #888; font-size: 9px;")
                        layout.addWidget(days_label)
                except:
                    pass
        
        else:  # In position (state > 0)
            # Price row: Current price and P&L
            price_row = QHBoxLayout()

            # Price label (stored for incremental updates)
            self._price_label = QLabel(f"${self.last_price:.2f}" if self.last_price else "--")
            self._price_label.setStyleSheet("font-weight: bold;")
            price_row.addWidget(self._price_label)

            # P&L label (stored for incremental updates)
            self._pnl_label = QLabel(f"{self.pnl_pct:+.1f}%" if self.pnl_pct is not None else "--")
            self._pnl_label.setStyleSheet(self._get_pnl_style())
            price_row.addWidget(self._pnl_label)

            price_row.addStretch()

            if self.total_shares and self.total_shares > 0:
                shares_label = QLabel(f"{int(self.total_shares)} sh")
                shares_label.setStyleSheet("color: #888; font-size: 9px;")
                price_row.addWidget(shares_label)

            layout.addLayout(price_row)
            
            # Cost basis row
            if self.avg_cost:
                cost_row = QHBoxLayout()
                cost_label = QLabel(f"Avg: ${self.avg_cost:.2f}")
                cost_label.setStyleSheet("color: #666; font-size: 9px;")
                cost_row.addWidget(cost_label)
                
                # Days held
                hold_date = self.entry_date or self.watch_date
                if hold_date:
                    try:
                        if isinstance(hold_date, date):
                            days = (date.today() - hold_date).days
                            days_label = QLabel(f"{days}d held")
                            days_label.setStyleSheet("color: #888; font-size: 9px;")
                            cost_row.addWidget(days_label)
                    except:
                        pass
                
                cost_row.addStretch()
                layout.addLayout(cost_row)
        
        # Alert status row (NEW)
        if self.latest_alert:
            self._add_alert_status_row(layout)
    
    def _apply_style(self):
        """Apply visual styling based on state."""
        state_info = STATES.get(self.state)
        if state_info:
            border_color = state_info.color
        else:
            border_color = '#CCC'
        
        self.setStyleSheet(f"""
            PositionCard {{
                background-color: white;
                border: 2px solid {border_color};
                border-radius: 6px;
            }}
            PositionCard:hover {{
                background-color: #F8F9FA;
                border-color: {border_color};
            }}
        """)

    def update_price(self, new_price: float, new_pnl_pct: float = None):
        """
        Update price display without rebuilding the entire card.
        This is much more efficient than recreating the card.
        """
        self.last_price = new_price
        if new_pnl_pct is not None:
            self.pnl_pct = new_pnl_pct

        if self.state == 0:  # Watching
            if self._current_label and new_price:
                self._current_label.setText(f"Now: ${new_price:.2f}")
        else:  # In position
            if self._price_label and new_price:
                self._price_label.setText(f"${new_price:.2f}")
            if self._pnl_label and new_pnl_pct is not None:
                self._pnl_label.setText(f"{new_pnl_pct:+.1f}%")
                self._pnl_label.setStyleSheet(self._get_pnl_style())

    def _get_rs_style(self) -> str:
        """Get RS rating badge style."""
        if self.rs_rating >= 90:
            return "background-color: #28A745; color: white; padding: 2px 6px; border-radius: 3px; font-size: 9px;"
        elif self.rs_rating >= 80:
            return "background-color: #17A2B8; color: white; padding: 2px 6px; border-radius: 3px; font-size: 9px;"
        elif self.rs_rating >= 70:
            return "background-color: #FFC107; color: black; padding: 2px 6px; border-radius: 3px; font-size: 9px;"
        else:
            return "background-color: #DC3545; color: white; padding: 2px 6px; border-radius: 3px; font-size: 9px;"
    
    def _get_grade_style(self) -> str:
        """Get entry grade badge style."""
        grade = self.entry_grade or ''
        if grade.startswith('A'):
            return "background-color: #28A745; color: white; padding: 2px 6px; border-radius: 3px; font-size: 9px; font-weight: bold;"
        elif grade.startswith('B'):
            return "background-color: #17A2B8; color: white; padding: 2px 6px; border-radius: 3px; font-size: 9px; font-weight: bold;"
        elif grade.startswith('C'):
            return "background-color: #FFC107; color: black; padding: 2px 6px; border-radius: 3px; font-size: 9px; font-weight: bold;"
        elif grade.startswith('D'):
            return "background-color: #FD7E14; color: white; padding: 2px 6px; border-radius: 3px; font-size: 9px; font-weight: bold;"
        else:
            return "background-color: #DC3545; color: white; padding: 2px 6px; border-radius: 3px; font-size: 9px; font-weight: bold;"
    
    def _get_pnl_style(self) -> str:
        """Get P&L label style."""
        if self.pnl_pct is None:
            return ""
        elif self.pnl_pct >= 20:
            return "color: #28A745; font-weight: bold;"
        elif self.pnl_pct >= 0:
            return "color: #28A745;"
        elif self.pnl_pct >= -7:
            return "color: #FFC107;"
        else:
            return "color: #DC3545; font-weight: bold;"
    
    def _get_portfolio_style(self) -> str:
        """Get portfolio badge style."""
        portfolio_lower = (self.portfolio or '').lower()
        if 'swing' in portfolio_lower:
            return "background-color: #6F42C1; color: white; padding: 1px 4px; border-radius: 2px; font-size: 8px;"
        elif 'position' in portfolio_lower:
            return "background-color: #0D6EFD; color: white; padding: 1px 4px; border-radius: 2px; font-size: 8px;"
        elif 'paper' in portfolio_lower:
            return "background-color: #6C757D; color: white; padding: 1px 4px; border-radius: 2px; font-size: 8px;"
        else:
            return "background-color: #17A2B8; color: white; padding: 1px 4px; border-radius: 2px; font-size: 8px;"
    
    def _add_alert_status_row(self, layout: QVBoxLayout):
        """Add the alert status row to the card layout."""
        from datetime import datetime
        
        alert = self.latest_alert
        if not alert:
            return
        
        # Get severity and acknowledgment status
        severity = alert.get('severity', 'neutral')
        alert_type = alert.get('alert_type', '')
        subtype = alert.get('subtype', '')
        acknowledged = alert.get('acknowledged', False)
        alert_id = alert.get('id')
        
        # Format the alert text
        alert_text = self._format_alert_text(alert_type, subtype)
        
        # Get time since alert
        alert_time = alert.get('alert_time')
        time_text = self._format_alert_time(alert_time)
        
        # Create the alert row as a clickable frame
        from PyQt6.QtWidgets import QFrame as AlertFrame
        alert_container = AlertFrame()
        alert_container.setObjectName("alertContainer")
        
        # Store alert_id for click handling
        alert_container.alert_id = alert_id
        alert_container.position_id = self.position_id
        
        alert_row = QHBoxLayout(alert_container)
        alert_row.setContentsMargins(2, 2, 2, 2)
        alert_row.setSpacing(4)
        
        # Different styling based on acknowledgment
        if acknowledged:
            # Acknowledged: muted/faded styling
            indicator_text = "○"  # Hollow circle
            indicator_style = "font-size: 10px; color: #999;"
            text_style = self._get_alert_style_acknowledged(severity)
            container_style = ""
            tooltip_extra = "\n✓ Acknowledged"
        else:
            # Unacknowledged: bright/bold styling
            indicator_text = self._get_severity_emoji(severity)
            indicator_style = "font-size: 10px;"
            text_style = self._get_alert_style_unacknowledged(severity)
            container_style = self._get_alert_container_style(severity)
            tooltip_extra = "\n⚡ Click to acknowledge"
        
        alert_container.setStyleSheet(container_style)
        
        # Severity indicator
        indicator = QLabel(indicator_text)
        indicator.setStyleSheet(indicator_style)
        alert_row.addWidget(indicator)
        
        # Alert text
        text_label = QLabel(alert_text)
        text_label.setStyleSheet(text_style)
        text_label.setToolTip(f"{alert_type}.{subtype}\n{time_text}{tooltip_extra}")
        alert_row.addWidget(text_label)
        
        alert_row.addStretch()
        
        # Time indicator
        time_label = QLabel(time_text)
        time_style = "color: #666; font-size: 8px;" if acknowledged else "color: #888; font-size: 8px; font-weight: bold;"
        time_label.setStyleSheet(time_style)
        alert_row.addWidget(time_label)
        
        # Make the alert container clickable (for acknowledgment)
        alert_container.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        alert_container.mousePressEvent = lambda e: self._on_alert_clicked(alert_id)
        
        layout.addWidget(alert_container)
    
    def _format_alert_text(self, alert_type: str, subtype: str) -> str:
        """Format alert type/subtype for display."""
        # Friendly names for alert subtypes
        friendly_names = {
            # Stop alerts
            ("STOP", "HARD_STOP"): "⛔ Stop Hit",
            ("STOP", "WARNING"): "⚠️ Near Stop",
            ("STOP", "TRAILING_STOP"): "⛔ Trail Stop",
            
            # Profit alerts
            ("PROFIT", "TP1"): "💰 TP1 Hit",
            ("PROFIT", "TP2"): "💰 TP2 Hit",
            ("PROFIT", "8_WEEK_HOLD"): "📅 8-Week Hold",
            
            # Pyramid alerts
            ("PYRAMID", "P1_READY"): "🔺 P1 Ready",
            ("PYRAMID", "P1_EXTENDED"): "↗️ P1 Extended",
            ("PYRAMID", "P2_READY"): "🔺 P2 Ready",
            ("PYRAMID", "P2_EXTENDED"): "↗️ P2 Extended",
            
            # Add alerts
            ("ADD", "PULLBACK"): "🔄 Pullback",
            ("ADD", "21_EMA"): "🔄 21 EMA",
            
            # Technical alerts
            ("TECHNICAL", "50_MA_WARNING"): "⚠️ 50 MA Test",
            ("TECHNICAL", "50_MA_SELL"): "📉 50 MA Sell",
            ("TECHNICAL", "21_EMA_SELL"): "📉 21 EMA Sell",
            ("TECHNICAL", "10_WEEK_SELL"): "📉 10W Sell",
            ("TECHNICAL", "CLIMAX_TOP"): "🔥 Climax Top",
            
            # Health alerts
            ("HEALTH", "CRITICAL"): "🚨 Critical",
            ("HEALTH", "EXTENDED"): "↗️ Extended",
            ("HEALTH", "EARNINGS"): "📅 Earnings",
            ("HEALTH", "LATE_STAGE"): "⚠️ Late Stage",
            
            # Breakout alerts
            ("BREAKOUT", "CONFIRMED"): "✅ Breakout",
            ("BREAKOUT", "IN_BUY_ZONE"): "🎯 Buy Zone",
            ("BREAKOUT", "APPROACHING"): "👀 Approaching",
            ("BREAKOUT", "EXTENDED"): "↗️ Extended",
            ("BREAKOUT", "SUPPRESSED"): "⏸️ Suppressed",
        }
        
        return friendly_names.get((alert_type, subtype), f"{alert_type}.{subtype}")
    
    def _format_alert_time(self, alert_time_str: str) -> str:
        """Format alert time as relative time."""
        if not alert_time_str:
            return ""
        
        try:
            from datetime import datetime
            
            # Parse ISO format
            if 'T' in alert_time_str:
                alert_time = datetime.fromisoformat(alert_time_str.replace('Z', '+00:00'))
            else:
                alert_time = datetime.fromisoformat(alert_time_str)
            
            # Calculate time difference
            now = datetime.now()
            if alert_time.tzinfo:
                now = datetime.now(alert_time.tzinfo)
            
            diff = now - alert_time
            minutes = int(diff.total_seconds() / 60)
            hours = int(minutes / 60)
            days = int(hours / 24)
            
            if days > 0:
                return f"{days}d ago"
            elif hours > 0:
                return f"{hours}h ago"
            elif minutes > 0:
                return f"{minutes}m ago"
            else:
                return "just now"
                
        except Exception:
            return ""
    
    def _get_severity_emoji(self, severity: str) -> str:
        """Get emoji for severity level."""
        emojis = {
            "critical": "🔴",
            "warning": "🟡",
            "profit": "🟢",
            "info": "🔵",
            "neutral": "⚪",
        }
        return emojis.get(severity, "⚪")
    
    def _get_alert_style(self, severity: str) -> str:
        """Get CSS style for alert text based on severity (deprecated, use specific methods)."""
        return self._get_alert_style_unacknowledged(severity)
    
    def _get_alert_style_unacknowledged(self, severity: str) -> str:
        """Get CSS style for UNACKNOWLEDGED alert text - bright and bold."""
        colors = {
            "critical": "#DC3545",  # Red
            "warning": "#B8860B",   # Dark goldenrod
            "profit": "#28A745",    # Green
            "info": "#17A2B8",      # Blue
            "neutral": "#6C757D",   # Gray
        }
        color = colors.get(severity, "#6C757D")
        return f"color: {color}; font-size: 9px; font-weight: bold;"
    
    def _get_alert_style_acknowledged(self, severity: str) -> str:
        """Get CSS style for ACKNOWLEDGED alert text - muted and normal weight."""
        # All acknowledged alerts use muted gray
        return "color: #999; font-size: 9px; font-weight: normal;"
    
    def _get_alert_container_style(self, severity: str) -> str:
        """Get container style for unacknowledged alerts - subtle highlight."""
        bg_colors = {
            "critical": "rgba(220, 53, 69, 0.1)",   # Light red tint
            "warning": "rgba(255, 193, 7, 0.1)",   # Light yellow tint
            "profit": "rgba(40, 167, 69, 0.1)",    # Light green tint
            "info": "rgba(23, 162, 184, 0.08)",    # Light blue tint
            "neutral": "transparent",
        }
        bg = bg_colors.get(severity, "transparent")
        border_colors = {
            "critical": "#DC3545",
            "warning": "#FFC107",
            "profit": "#28A745",
            "info": "#17A2B8",
            "neutral": "transparent",
        }
        border = border_colors.get(severity, "transparent")
        return f"""
            QFrame#alertContainer {{
                background-color: {bg};
                border-left: 2px solid {border};
                border-radius: 2px;
            }}
        """
    
    def _on_alert_clicked(self, alert_id: int):
        """Handle click on alert row to acknowledge."""
        if alert_id:
            self.alert_clicked.emit(alert_id, self.position_id)
    
    def update_price(self, last_price: float, pnl_pct: float = None):
        """Update the displayed price and P&L."""
        self.last_price = last_price
        self.pnl_pct = pnl_pct
        # Would need to rebuild layout to update - simplified for now
    
    def mousePressEvent(self, event):
        """Handle mouse press for drag start."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_pos = event.pos()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for drag operation."""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        
        if not hasattr(self, 'drag_start_pos'):
            return
        
        # Check if moved enough to start drag
        distance = (event.pos() - self.drag_start_pos).manhattanLength()
        if distance < 10:
            return
        
        # Start drag
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"{self.position_id}:{self.state}")
        drag.setMimeData(mime_data)
        
        # Change cursor during drag
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        
        # Execute drag
        result = drag.exec(Qt.DropAction.MoveAction)
        
        # Reset cursor - but card may have been deleted during drag
        # (e.g., if drop triggered a state change and GUI refresh)
        try:
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        except RuntimeError:
            # Card was deleted, ignore
            pass
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release (click)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.position_id)
        # Don't call super() - we handle the event ourselves
        event.accept()
    
    def mouseDoubleClickEvent(self, event):
        """Handle double-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.position_id)
        # Don't call super() - the widget may be deleted during signal handling
        event.accept()
    
    def contextMenuEvent(self, event):
        """Handle right-click context menu."""
        self.context_menu_requested.emit(self.position_id, event.globalPos())
        event.accept()
