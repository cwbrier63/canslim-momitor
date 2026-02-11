"""
CANSLIM Monitor - Alert Detail Dialog
======================================
Detailed view of a single alert with IBD methodology education.

Shows:
- Alert info (type, time, price, technicals)
- IBD education panel explaining the alert
- Acknowledge button
"""

from datetime import datetime
from typing import Dict, Any, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QGridLayout, QGroupBox, QTextEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from .alert_descriptions import get_description_text


class AlertDetailDialog(QDialog):
    """
    Dialog showing detailed information about a single alert.
    
    Signals:
        alert_acknowledged(int): Emitted when alert is acknowledged, passes alert_id
    """
    
    alert_acknowledged = pyqtSignal(int)
    
    def __init__(
        self,
        alert: Dict[str, Any],
        parent=None,
        alert_service=None,
        db_session_factory=None
    ):
        """
        Initialize the detail dialog.
        
        Args:
            alert: Alert dictionary with all fields
            parent: Parent widget
            alert_service: AlertService instance for acknowledge functionality
            db_session_factory: Database session factory for fetching position data
        """
        super().__init__(parent)
        
        self.alert = alert
        self.alert_service = alert_service
        self.db_session_factory = db_session_factory
        
        # Enrich alert with position data if missing
        self._enrich_alert_data()
        
        self._setup_ui()
        self._populate_data()
    
    def _enrich_alert_data(self):
        """Fetch missing data from position if available.

        avg_volume is never stored in the Alert table, so it always
        needs to be fetched from the position. Other fields are only
        fetched when the alert record itself is missing them.
        """
        position_id = self.alert.get('position_id')
        if not position_id:
            return

        # Determine what needs enrichment
        needs_avg_volume = self.alert.get('avg_volume') is None
        needs_other = (
            self.alert.get('grade') is None or
            self.alert.get('pivot_at_alert') is None or
            self.alert.get('pnl_pct_at_alert') is None
        )

        if not needs_avg_volume and not needs_other:
            return

        # Try to get db_session_factory from alert_service if not provided
        session_factory = self.db_session_factory
        if not session_factory and self.alert_service:
            session_factory = getattr(self.alert_service, 'db_session_factory', None)

        if not session_factory:
            return

        try:
            from canslim_monitor.data.repository import RepositoryManager

            session = session_factory()
            try:
                repos = RepositoryManager(session)
                position = repos.positions.get_by_id(position_id)

                if position:
                    # avg_volume is never on Alert — always fetch from position
                    if needs_avg_volume:
                        self.alert['avg_volume'] = position.avg_volume_50d

                    # Fill in other missing fields from position
                    if self.alert.get('grade') is None:
                        self.alert['grade'] = position.entry_grade
                    if self.alert.get('score') is None:
                        self.alert['score'] = position.entry_score
                    if self.alert.get('pivot_at_alert') is None:
                        self.alert['pivot_at_alert'] = position.pivot

                    # Calculate P&L if we have entry price (use e1_price or avg_cost)
                    entry_price = position.e1_price or position.avg_cost
                    if self.alert.get('pnl_pct_at_alert') is None and entry_price:
                        alert_price = self.alert.get('price')
                        if alert_price:
                            pnl = ((alert_price - entry_price) / entry_price) * 100
                            self.alert['pnl_pct_at_alert'] = pnl

            finally:
                session.close()

        except Exception as e:
            print(f"Error enriching alert data: {e}")
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("🔔 Alert Details")
        self.setMinimumSize(850, 600)
        self.setModal(True)
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # Top section: header + action
        header_layout = self._create_header()
        main_layout.addLayout(header_layout)
        
        # Middle section: three columns
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(10)
        
        # Left panel - Alert context data
        left_panel = self._create_info_panel()
        middle_layout.addWidget(left_panel, stretch=1)
        
        # Center panel - Full message
        center_panel = self._create_message_panel()
        middle_layout.addWidget(center_panel, stretch=2)
        
        # Right panel - IBD education
        right_panel = self._create_education_panel()
        middle_layout.addWidget(right_panel, stretch=1)
        
        main_layout.addLayout(middle_layout, stretch=1)
        
        # Bottom buttons
        button_layout = self._create_button_layout()
        main_layout.addLayout(button_layout)
    
    def _create_header(self) -> QHBoxLayout:
        """Create the header row with symbol, type, and action."""
        layout = QHBoxLayout()
        
        # Symbol and type
        self.header_label = QLabel()
        self.header_label.setFont(QFont('Arial', 16, QFont.Weight.Bold))
        layout.addWidget(self.header_label)
        
        self.subtype_label = QLabel()
        self.subtype_label.setFont(QFont('Arial', 14))
        self.subtype_label.setStyleSheet("color: #666;")
        layout.addWidget(self.subtype_label)
        
        layout.addStretch()
        
        # Action badge
        self.action_label = QLabel()
        self.action_label.setFont(QFont('Arial', 12, QFont.Weight.Bold))
        self.action_label.setStyleSheet("""
            QLabel {
                background-color: #1976D2;
                color: white;
                padding: 5px 15px;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.action_label)
        
        return layout
    
    def _create_message_panel(self) -> QGroupBox:
        """Create the center panel with full alert message."""
        group = QGroupBox("📋 ALERT MESSAGE")
        group.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        layout = QVBoxLayout(group)
        
        self.message_text = QTextEdit()
        self.message_text.setReadOnly(True)
        self.message_text.setFont(QFont('Consolas', 10))
        self.message_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #ddd;
                padding: 10px;
            }
        """)
        layout.addWidget(self.message_text)
        
        return group
    
    def _create_info_panel(self) -> QGroupBox:
        """Create the left panel with alert context data."""
        group = QGroupBox("📊 CONTEXT")
        group.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        layout = QVBoxLayout(group)
        
        # Info grid
        grid = QGridLayout()
        grid.setSpacing(6)
        
        self.info_labels = {}
        info_fields = [
            ('time', 'Time'),
            ('price', 'Price'),
            ('entry', 'Entry'),
            ('pnl', 'P&L'),
            ('pivot', 'Pivot'),
            ('volume_ratio', 'Vol Ratio'),
            ('avg_vol', 'Avg Vol'),
            ('ma_50', '50 MA'),
            ('ma_21', '21 EMA'),
            ('grade', 'Grade'),
            ('score', 'Score'),
            ('market', 'Market'),
        ]
        
        for row, (key, label) in enumerate(info_fields):
            label_widget = QLabel(f"{label}:")
            label_widget.setFont(QFont('Arial', 9, QFont.Weight.Bold))
            label_widget.setAlignment(Qt.AlignmentFlag.AlignRight)
            
            value_widget = QLabel()
            value_widget.setFont(QFont('Arial', 9))
            
            grid.addWidget(label_widget, row, 0)
            grid.addWidget(value_widget, row, 1)
            
            self.info_labels[key] = value_widget
        
        layout.addLayout(grid)
        layout.addStretch()
        
        return group
    
    def _create_education_panel(self) -> QGroupBox:
        """Create the right panel with IBD education content."""
        group = QGroupBox("📚 IBD METHODOLOGY")
        group.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        layout = QVBoxLayout(group)
        
        # Meaning section
        meaning_header = QLabel("WHAT THIS MEANS:")
        meaning_header.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        meaning_header.setStyleSheet("color: #1565C0;")
        layout.addWidget(meaning_header)
        
        self.meaning_text = QLabel()
        self.meaning_text.setWordWrap(True)
        self.meaning_text.setFont(QFont('Arial', 10))
        layout.addWidget(self.meaning_text)
        
        layout.addSpacing(10)
        
        # IBD context section
        context_header = QLabel("IBD CONTEXT:")
        context_header.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        context_header.setStyleSheet("color: #1565C0;")
        layout.addWidget(context_header)
        
        self.context_text = QLabel()
        self.context_text.setWordWrap(True)
        self.context_text.setFont(QFont('Arial', 10))
        self.context_text.setStyleSheet("color: #555;")
        layout.addWidget(self.context_text)
        
        layout.addSpacing(10)
        
        # Recommended action section
        action_header = QLabel("RECOMMENDED ACTION:")
        action_header.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        action_header.setStyleSheet("color: #2E7D32;")
        layout.addWidget(action_header)
        
        self.action_rec_text = QLabel()
        self.action_rec_text.setWordWrap(True)
        self.action_rec_text.setFont(QFont('Arial', 10, QFont.Weight.Bold))
        layout.addWidget(self.action_rec_text)
        
        layout.addSpacing(10)
        
        # Source reference
        self.source_label = QLabel()
        self.source_label.setFont(QFont('Arial', 9))
        self.source_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self.source_label)
        
        layout.addStretch()
        
        return group
    
    def _create_button_layout(self) -> QHBoxLayout:
        """Create the bottom button row."""
        layout = QHBoxLayout()
        
        # Status indicator
        self.status_label = QLabel()
        self.status_label.setFont(QFont('Arial', 10))
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # Acknowledge button
        self.ack_button = QPushButton("Acknowledge")
        self.ack_button.setMinimumWidth(100)
        self.ack_button.clicked.connect(self._on_acknowledge)
        layout.addWidget(self.ack_button)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.setMinimumWidth(80)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        return layout
    
    def _format_embed_message(self, message: str) -> str:
        """
        Format an EMBED message for display.
        
        If message starts with 'EMBED:', parse the JSON and format nicely.
        Otherwise return the raw message.
        """
        if not message:
            return "(No message recorded)"
        
        if not message.strip().startswith("EMBED:"):
            return message
        
        try:
            import json
            embed_json = message.strip()[6:]  # Remove "EMBED:" prefix
            embed = json.loads(embed_json)
            
            # Build formatted message
            lines = []
            
            # Title
            title = embed.get('title', '')
            if title:
                lines.append(f"📌 {title}")
                lines.append("")
            
            # Description (already formatted with newlines)
            description = embed.get('description', '')
            if description:
                lines.append(description)
                lines.append("")
            
            # Footer
            footer = embed.get('footer', {})
            footer_text = footer.get('text', '') if isinstance(footer, dict) else str(footer)
            if footer_text:
                lines.append(f"──────────────────────")
                lines.append(footer_text)
            
            # Timestamp
            timestamp = embed.get('timestamp', '')
            if timestamp:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    lines.append(f"🕐 {dt.strftime('%m/%d/%Y %H:%M:%S')}")
                except:
                    pass
            
            return "\n".join(lines)
            
        except Exception as e:
            # If parsing fails, return original message
            return f"(Parse error: {e})\n\n{message}"
    
    def _populate_data(self):
        """Populate the dialog with alert data."""
        alert = self.alert
        
        # Header
        symbol = alert.get('symbol', 'N/A')
        alert_type = alert.get('alert_type', 'N/A')
        subtype = alert.get('subtype', 'N/A')
        
        self.header_label.setText(f"{symbol} - {alert_type}")
        self.subtype_label.setText(f" / {subtype}")
        
        # Action badge
        action = alert.get('action', '')
        if action:
            self.action_label.setText(action)
            self.action_label.setVisible(True)
        else:
            self.action_label.setVisible(False)
        
        # Full message - format EMBED messages nicely
        message = alert.get('message', '')
        formatted_message = self._format_embed_message(message)
        self.message_text.setText(formatted_message)
        
        # Info fields
        self._set_info('time', self._format_time(alert.get('alert_time')))
        self._set_info('price', self._format_price(alert.get('price')))
        self._set_info('entry', self._format_price(alert.get('avg_cost_at_alert')))
        self._set_info('pnl', self._format_pnl(alert.get('pnl_pct_at_alert')))
        self._set_info('pivot', self._format_price(alert.get('pivot_at_alert')))
        self._set_info('volume_ratio', self._format_volume(alert.get('volume_ratio')))
        self._set_info('avg_vol', self._format_avg_volume(alert.get('avg_volume')))
        self._set_info('ma_50', self._format_price(alert.get('ma50')))
        self._set_info('ma_21', self._format_price(alert.get('ma21')))
        self._set_info('grade', alert.get('grade') or '-')
        self._set_info('score', str(alert.get('score')) if alert.get('score') is not None else '-')
        self._set_info('market', alert.get('market_regime') or '-')
        
        # Education content
        desc = get_description_text(alert_type, subtype)
        self.meaning_text.setText(desc['meaning'])
        self.context_text.setText(desc['ibd_context'])
        self.action_rec_text.setText(desc['recommended_action'])
        
        if desc['source_reference']:
            self.source_label.setText(f"Source: {desc['source_reference']}")
        else:
            self.source_label.setText("")
        
        # Status
        is_acknowledged = alert.get('acknowledged', False)
        if is_acknowledged:
            self.status_label.setText("○ Acknowledged")
            self.status_label.setStyleSheet("color: #888;")
            self.ack_button.setEnabled(False)
            self.ack_button.setText("Acknowledged")
        else:
            self.status_label.setText("● Unacknowledged")
            self.status_label.setStyleSheet("color: #C62828; font-weight: bold;")
            self.ack_button.setEnabled(True)
    
    def _set_info(self, key: str, value: str):
        """Set an info label value."""
        if key in self.info_labels:
            self.info_labels[key].setText(value)
    
    def _format_time(self, time_val) -> str:
        """Format time for display."""
        if isinstance(time_val, str):
            try:
                dt = datetime.fromisoformat(time_val.replace('Z', '+00:00'))
                return dt.strftime('%m/%d/%Y %H:%M')
            except:
                return time_val[:16] if time_val else '-'
        elif isinstance(time_val, datetime):
            return time_val.strftime('%m/%d/%Y %H:%M')
        return '-'
    
    def _format_price(self, price) -> str:
        """Format price for display."""
        if price:
            return f"${price:.2f}"
        return '-'
    
    def _format_pct_from_pivot(self, price, pivot) -> str:
        """Calculate and format % from pivot."""
        if price and pivot and pivot > 0:
            pct = ((price - pivot) / pivot) * 100
            return f"{pct:+.2f}%"
        return '-'
    
    def _format_volume(self, ratio) -> str:
        """Format volume ratio (RVOL)."""
        if ratio is not None and ratio > 0:
            return f"{ratio:.2f}x"
        return '-'

    def _format_avg_volume(self, volume) -> str:
        """Format average daily volume with K/M suffixes."""
        if not volume or volume <= 0:
            return '-'
        if volume >= 1_000_000:
            return f"{volume / 1_000_000:.1f}M"
        elif volume >= 1_000:
            return f"{volume / 1_000:.0f}K"
        return str(int(volume))
    
    def _format_pnl(self, pnl) -> str:
        """Format P&L percentage."""
        if pnl is not None:
            color = '#2E7D32' if pnl >= 0 else '#C62828'
            self.info_labels['pnl'].setStyleSheet(f"color: {color}; font-weight: bold;")
            return f"{pnl:+.1f}%"
        return '-'
    
    def _on_acknowledge(self):
        """Handle acknowledge button click."""
        alert_id = self.alert.get('id')
        if not alert_id:
            return
        
        if self.alert_service:
            success = self.alert_service.acknowledge_alert(alert_id)
            if success:
                self.alert['acknowledged'] = True
                self.status_label.setText("○ Acknowledged")
                self.status_label.setStyleSheet("color: #888;")
                self.ack_button.setEnabled(False)
                self.ack_button.setText("Acknowledged")
                self.alert_acknowledged.emit(alert_id)
        else:
            # No service, just update UI
            self.alert['acknowledged'] = True
            self.status_label.setText("○ Acknowledged")
            self.status_label.setStyleSheet("color: #888;")
            self.ack_button.setEnabled(False)
            self.ack_button.setText("Acknowledged")
            self.alert_acknowledged.emit(alert_id)


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Test alert data
    test_alert = {
        'id': 1,
        'symbol': 'NVDA',
        'alert_type': 'BREAKOUT',
        'subtype': 'CONFIRMED',
        'alert_time': '2026-01-18T09:32:00',
        'price': 142.50,
        'pivot_at_alert': 139.50,
        'volume_ratio': 1.85,
        'ma50': 135.20,
        'ma21': 138.40,
        'grade': 'A',
        'score': 18,
        'market_regime': 'CONFIRMED_UPTREND',
        'pnl_pct_at_alert': 2.3,
        'acknowledged': False,
    }
    
    dialog = AlertDetailDialog(test_alert)
    dialog.alert_acknowledged.connect(lambda id: print(f"Alert {id} acknowledged"))
    dialog.exec()
