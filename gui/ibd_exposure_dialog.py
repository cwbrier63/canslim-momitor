"""
IBD Exposure Dialog

Dialog for viewing and editing IBD market exposure settings.
These settings are the STRATEGIC layer - manually input from MarketSurge.
"""

import logging
from datetime import datetime, date
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QSpinBox, QTextEdit,
    QPushButton, QGroupBox, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

logger = logging.getLogger(__name__)


class IBDExposureDialog(QDialog):
    """
    Dialog for editing IBD Market Exposure settings.
    
    Shows:
    - Current IBD market status (dropdown)
    - Exposure range (auto-populated based on status)
    - Notes field
    - History of recent changes
    
    Emits:
        exposure_updated: Signal with (status, min, max, notes) when saved
    """
    
    exposure_updated = pyqtSignal(str, int, int, str)  # status, min, max, notes
    
    # Default exposure ranges for each status
    DEFAULT_EXPOSURES = {
        'CONFIRMED_UPTREND': (80, 100),
        'UPTREND_UNDER_PRESSURE': (40, 80),
        'RALLY_ATTEMPT': (20, 40),
        'CORRECTION': (0, 20),
    }
    
    STATUS_DISPLAY_NAMES = {
        'CONFIRMED_UPTREND': 'Confirmed Uptrend',
        'UPTREND_UNDER_PRESSURE': 'Uptrend Under Pressure',
        'RALLY_ATTEMPT': 'Rally Attempt',
        'CORRECTION': 'Market in Correction',
    }
    
    def __init__(
        self, 
        parent=None,
        current_status: str = 'CONFIRMED_UPTREND',
        current_min: int = 80,
        current_max: int = 100,
        current_notes: str = '',
        last_updated: datetime = None,
        db_session_factory=None
    ):
        super().__init__(parent)
        self.db_session_factory = db_session_factory
        self._current_status = current_status
        self._current_min = current_min
        self._current_max = current_max
        self._current_notes = current_notes or ''
        self._last_updated = last_updated
        
        self.setWindowTitle("IBD Market Exposure Settings")
        self.setMinimumWidth(450)
        self.setModal(True)
        
        self._setup_ui()
        self._load_values()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Header
        header = QLabel(
            "Set the IBD Market Exposure based on MarketSurge's published guidance.\n"
            "This is the STRATEGIC layer - update when IBD changes their outlook."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(header)
        
        # Current Status Group
        status_group = QGroupBox("IBD Market Status")
        status_layout = QFormLayout(status_group)
        
        # Status dropdown
        self.status_combo = QComboBox()
        for key, display in self.STATUS_DISPLAY_NAMES.items():
            self.status_combo.addItem(display, key)
        self.status_combo.currentIndexChanged.connect(self._on_status_changed)
        status_layout.addRow("Market Status:", self.status_combo)
        
        # Exposure range
        exposure_layout = QHBoxLayout()
        
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 100)
        self.min_spin.setSuffix("%")
        self.min_spin.setMinimumWidth(70)
        exposure_layout.addWidget(self.min_spin)
        
        exposure_layout.addWidget(QLabel(" to "))
        
        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 100)
        self.max_spin.setSuffix("%")
        self.max_spin.setMinimumWidth(70)
        exposure_layout.addWidget(self.max_spin)
        
        exposure_layout.addStretch()
        status_layout.addRow("Exposure Range:", exposure_layout)
        
        # Last updated
        self.updated_label = QLabel("Not set")
        self.updated_label.setStyleSheet("color: #888;")
        status_layout.addRow("Last Updated:", self.updated_label)
        
        layout.addWidget(status_group)
        
        # Notes Group
        notes_group = QGroupBox("Notes (optional)")
        notes_layout = QVBoxLayout(notes_group)
        
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(60)
        self.notes_edit.setPlaceholderText(
            "e.g., 'IBD raised exposure after strong FTD on Jan 15'"
        )
        notes_layout.addWidget(self.notes_edit)
        
        layout.addWidget(notes_group)
        
        # Guidance based on selection
        self.guidance_label = QLabel()
        self.guidance_label.setWordWrap(True)
        self.guidance_label.setStyleSheet("""
            QLabel {
                background-color: #2A4A6F;
                padding: 8px;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.guidance_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                padding: 6px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
    
    def _load_values(self):
        """Load current values into the form."""
        # Set status combo
        index = self.status_combo.findData(self._current_status)
        if index >= 0:
            self.status_combo.setCurrentIndex(index)
        
        # Set exposure range
        self.min_spin.setValue(self._current_min)
        self.max_spin.setValue(self._current_max)
        
        # Set notes
        self.notes_edit.setPlainText(self._current_notes)
        
        # Set last updated
        if self._last_updated:
            # Handle case where updated_at is a string from SQLite
            last_updated = self._last_updated
            if isinstance(last_updated, str):
                try:
                    # Try common datetime formats from SQLite
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S']:
                        try:
                            last_updated = datetime.strptime(last_updated, fmt)
                            break
                        except ValueError:
                            continue
                except Exception:
                    last_updated = None
            
            if last_updated and isinstance(last_updated, datetime):
                days_ago = (datetime.now() - last_updated).days
                if days_ago <= 0:  # Today or future (timezone edge case)
                    updated_str = f"Today at {last_updated.strftime('%I:%M %p')}"
                elif days_ago == 1:
                    updated_str = "Yesterday"
                else:
                    updated_str = f"{last_updated.strftime('%b %d, %Y')} ({days_ago} days ago)"
                self.updated_label.setText(updated_str)
            else:
                self.updated_label.setText("Unknown date format")
        else:
            self.updated_label.setText("Not set - using default")
        
        # Update guidance
        self._update_guidance()
    
    def _on_status_changed(self, index: int):
        """Handle status selection change."""
        status = self.status_combo.currentData()
        
        # Auto-fill exposure range based on status
        if status in self.DEFAULT_EXPOSURES:
            min_exp, max_exp = self.DEFAULT_EXPOSURES[status]
            self.min_spin.setValue(min_exp)
            self.max_spin.setValue(max_exp)
        
        self._update_guidance()
    
    def _update_guidance(self):
        """Update guidance text based on current selection."""
        status = self.status_combo.currentData()
        
        guidance = {
            'CONFIRMED_UPTREND': (
                "🟢 <b>Confirmed Uptrend</b><br>"
                "• Full position sizes permitted<br>"
                "• Act on quality breakouts<br>"
                "• Market environment supports growth stocks"
            ),
            'UPTREND_UNDER_PRESSURE': (
                "🟠 <b>Uptrend Under Pressure</b><br>"
                "• Reduce position sizes (40-80%)<br>"
                "• Be selective - A-grade setups only<br>"
                "• Tighten stops on existing positions"
            ),
            'RALLY_ATTEMPT': (
                "🟡 <b>Rally Attempt</b><br>"
                "• Small test positions only after FTD<br>"
                "• Wait for follow-through confirmation<br>"
                "• Most cash should remain on sidelines"
            ),
            'CORRECTION': (
                "🔴 <b>Market in Correction</b><br>"
                "• Defensive posture - preserve capital<br>"
                "• No new long positions<br>"
                "• Build watchlist for next uptrend"
            ),
        }
        
        self.guidance_label.setText(guidance.get(status, ""))
    
    def _on_save(self):
        """Handle save button click."""
        status = self.status_combo.currentData()
        min_exp = self.min_spin.value()
        max_exp = self.max_spin.value()
        notes = self.notes_edit.toPlainText().strip()
        
        # Validate
        if min_exp > max_exp:
            QMessageBox.warning(
                self, "Invalid Range",
                "Minimum exposure cannot be greater than maximum."
            )
            return
        
        # Save to database
        if self.db_session_factory:
            try:
                self._save_to_database(status, min_exp, max_exp, notes)
            except Exception as e:
                logger.error(f"Error saving IBD exposure: {e}")
                QMessageBox.critical(
                    self, "Save Error",
                    f"Could not save to database: {e}"
                )
                return
        
        # Emit signal
        self.exposure_updated.emit(status, min_exp, max_exp, notes)
        
        self.accept()
    
    def _save_to_database(self, status: str, min_exp: int, max_exp: int, notes: str):
        """Save IBD exposure to database."""
        from canslim_monitor.regime.models_regime import (
            IBDExposureCurrent, IBDExposureHistory, IBDMarketStatus
        )
        
        session = self.db_session_factory()
        try:
            # Convert status string to enum
            status_enum = IBDMarketStatus[status]
            
            # Update current exposure (singleton row)
            current = session.query(IBDExposureCurrent).filter(
                IBDExposureCurrent.id == 1
            ).first()
            
            if current:
                current.market_status = status_enum
                current.exposure_min = min_exp
                current.exposure_max = max_exp
                current.updated_at = datetime.now()
                current.notes = notes
            else:
                current = IBDExposureCurrent(
                    id=1,
                    market_status=status_enum,
                    exposure_min=min_exp,
                    exposure_max=max_exp,
                    notes=notes
                )
                session.add(current)
            
            # Add to history
            history = IBDExposureHistory(
                effective_date=date.today(),
                market_status=status_enum,
                exposure_min=min_exp,
                exposure_max=max_exp,
                notes=notes,
                source='GUI'
            )
            session.add(history)
            
            session.commit()
            logger.info(f"Saved IBD exposure: {status} {min_exp}-{max_exp}%")
            
        finally:
            session.close()


class IBDExposureWidget(QFrame):
    """
    Clickable widget showing IBD exposure status.
    Used in the MarketRegimeBanner.
    
    Emits:
        clicked: Signal when widget is clicked
    """
    
    clicked = pyqtSignal()
    
    STATUS_COLORS = {
        'CONFIRMED_UPTREND': '#28A745',
        'UPTREND_UNDER_PRESSURE': '#FFA500',
        'RALLY_ATTEMPT': '#FFC107',
        'CORRECTION': '#DC3545',
    }
    
    STATUS_DISPLAY = {
        'CONFIRMED_UPTREND': 'Confirmed Uptrend',
        'UPTREND_UNDER_PRESSURE': 'Under Pressure',
        'RALLY_ATTEMPT': 'Rally Attempt',
        'CORRECTION': 'Correction',
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()
        
        # Default values
        self.update_display('CONFIRMED_UPTREND', 80, 100)
    
    def _setup_ui(self):
        """Set up widget UI."""
        self.setStyleSheet("""
            IBDExposureWidget {
                background-color: #2A4A6F;
                border-radius: 4px;
                border: 1px solid #3A5A7F;
            }
            IBDExposureWidget:hover {
                background-color: #3A5A8F;
                border: 1px solid #4A6A9F;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)
        
        # Title with edit hint
        title_layout = QHBoxLayout()
        title = QLabel("IBD EXPOSURE")
        title.setStyleSheet("font-size: 10px; color: #AAA;")
        title_layout.addWidget(title)
        
        edit_hint = QLabel("✏️")
        edit_hint.setStyleSheet("font-size: 10px;")
        edit_hint.setToolTip("Click to edit")
        title_layout.addWidget(edit_hint)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # Status line
        self.status_label = QLabel("Confirmed Uptrend")
        status_font = QFont()
        status_font.setBold(True)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: #28A745;")
        layout.addWidget(self.status_label)
        
        # Exposure line
        self.exposure_label = QLabel("80-100%")
        self.exposure_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.exposure_label)
    
    def update_display(self, status: str, min_exp: int, max_exp: int):
        """Update the display with current values."""
        display_name = self.STATUS_DISPLAY.get(status, status)
        color = self.STATUS_COLORS.get(status, 'white')
        
        self.status_label.setText(display_name)
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.exposure_label.setText(f"{min_exp}-{max_exp}%")
    
    def mousePressEvent(self, event):
        """Handle mouse press."""
        self.clicked.emit()
        super().mousePressEvent(event)


class EntryRiskWidget(QFrame):
    """
    Widget showing today's entry risk level.
    Used in the MarketRegimeBanner.
    """
    
    RISK_COLORS = {
        'LOW': '#28A745',
        'MODERATE': '#FFC107',
        'ELEVATED': '#FFA500',
        'HIGH': '#DC3545',
    }
    
    RISK_EMOJI = {
        'LOW': '🟢',
        'MODERATE': '🟡',
        'ELEVATED': '🟠',
        'HIGH': '🔴',
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        
        # Default values
        self.update_display('MODERATE', 0.0)
    
    def _setup_ui(self):
        """Set up widget UI."""
        self.setStyleSheet("""
            EntryRiskWidget {
                background-color: #2A4A6F;
                border-radius: 4px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)
        
        # Title
        title = QLabel("TODAY'S RISK")
        title.setStyleSheet("font-size: 10px; color: #AAA;")
        layout.addWidget(title)
        
        # Risk level
        self.risk_label = QLabel("🟡 MODERATE")
        risk_font = QFont()
        risk_font.setBold(True)
        self.risk_label.setFont(risk_font)
        layout.addWidget(self.risk_label)
        
        # Score
        self.score_label = QLabel("Score: +0.25")
        self.score_label.setStyleSheet("font-size: 11px; color: #AAA;")
        layout.addWidget(self.score_label)
    
    def update_display(self, risk_level: str, score: float):
        """Update the display with current values."""
        emoji = self.RISK_EMOJI.get(risk_level, '⚪')
        color = self.RISK_COLORS.get(risk_level, 'white')
        
        self.risk_label.setText(f"{emoji} {risk_level}")
        self.risk_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.score_label.setText(f"Score: {score:+.2f}")
