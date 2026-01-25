"""
Report Generator Dialog

Dialog for configuring and generating weekly watchlist reports.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QSpinBox, QCheckBox, QFileDialog, QMessageBox,
    QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.reports.weekly_report import WeeklyWatchlistReport

logger = logging.getLogger(__name__)


class ReportGeneratorThread(QThread):
    """Background thread for report generation."""

    finished = pyqtSignal(str)  # Emits path to generated file
    error = pyqtSignal(str)     # Emits error message

    def __init__(self, config: Dict[str, Any], db: DatabaseManager):
        super().__init__()
        self.config = config
        self.db = db

    def run(self):
        """Generate the report in background thread."""
        try:
            report = WeeklyWatchlistReport(self.config, self.db)
            output_path = report.generate()
            self.finished.emit(output_path)
        except Exception as e:
            logger.error(f"Report generation error: {e}", exc_info=True)
            self.error.emit(str(e))


class ReportGeneratorDialog(QDialog):
    """
    Dialog for configuring and generating weekly watchlist reports.

    Features:
    - Output directory selection
    - Report configuration options
    - Generate button with progress indication
    - Open generated file button
    """

    def __init__(self, config: Dict[str, Any], db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.generated_file_path = None
        self.generator_thread = None

        self.setWindowTitle("Weekly Watchlist Report Generator")
        self.setMinimumWidth(600)
        self.setModal(True)

        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Header
        header = QLabel(
            "Generate a comprehensive weekly watchlist report in Word format (.docx).\n"
            "Report includes executive summary, active positions, trend analysis, and recommendations."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #888; font-style: italic; padding: 8px;")
        layout.addWidget(header)

        # Output Settings Group
        output_group = QGroupBox("Output Settings")
        output_layout = QFormLayout(output_group)
        output_layout.setSpacing(10)

        # Output directory
        dir_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setReadOnly(True)
        self.output_dir_edit.setPlaceholderText("Select output directory...")
        dir_layout.addWidget(self.output_dir_edit, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output_dir)
        dir_layout.addWidget(browse_btn)

        output_layout.addRow("Output Directory:", dir_layout)

        layout.addWidget(output_group)

        # Report Options Group
        options_group = QGroupBox("Report Options")
        options_layout = QFormLayout(options_group)
        options_layout.setSpacing(10)

        # Include closed positions
        self.include_closed_check = QCheckBox()
        self.include_closed_check.setToolTip("Include recently closed positions in the report")
        options_layout.addRow("Include Closed Positions:", self.include_closed_check)

        # Minimum RS Rating
        self.min_rs_spin = QSpinBox()
        self.min_rs_spin.setRange(0, 99)
        self.min_rs_spin.setValue(0)
        self.min_rs_spin.setSuffix(" (0 = all)")
        self.min_rs_spin.setToolTip("Filter positions with RS rating below this value")
        options_layout.addRow("Minimum RS Rating:", self.min_rs_spin)

        # Top picks count
        self.top_picks_spin = QSpinBox()
        self.top_picks_spin.setRange(1, 20)
        self.top_picks_spin.setValue(5)
        self.top_picks_spin.setToolTip("Number of top picks to highlight in the report")
        options_layout.addRow("Top Picks Count:", self.top_picks_spin)

        layout.addWidget(options_group)

        # Progress bar (initially hidden)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-style: italic;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.generate_btn = QPushButton("📝 Generate Report")
        self.generate_btn.setMinimumWidth(140)
        self.generate_btn.setDefault(True)
        self.generate_btn.clicked.connect(self._generate_report)
        button_layout.addWidget(self.generate_btn)

        self.open_btn = QPushButton("📂 Open Report")
        self.open_btn.setMinimumWidth(120)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_report)
        button_layout.addWidget(self.open_btn)

        close_btn = QPushButton("Close")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _load_config(self):
        """Load values from configuration."""
        report_config = self.config.get('reports', {}).get('weekly_watchlist', {})

        # Output directory
        default_dir = report_config.get('output_dir', 'C:/Trading/canslim_monitor/reports/output')
        self.output_dir_edit.setText(default_dir)

        # Options
        self.include_closed_check.setChecked(report_config.get('include_closed', False))
        self.min_rs_spin.setValue(report_config.get('min_rs_rating', 0))
        self.top_picks_spin.setValue(report_config.get('top_picks_count', 5))

    def _browse_output_dir(self):
        """Browse for output directory."""
        current_dir = self.output_dir_edit.text() or os.path.expanduser("~")

        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            current_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if dir_path:
            self.output_dir_edit.setText(dir_path)

    def _generate_report(self):
        """Generate the weekly watchlist report."""
        # Validate output directory
        output_dir = self.output_dir_edit.text()
        if not output_dir:
            QMessageBox.warning(
                self,
                "No Output Directory",
                "Please select an output directory for the report."
            )
            return

        # Update config with current UI values
        if 'reports' not in self.config:
            self.config['reports'] = {}
        if 'weekly_watchlist' not in self.config['reports']:
            self.config['reports']['weekly_watchlist'] = {}

        report_config = self.config['reports']['weekly_watchlist']
        report_config['output_dir'] = output_dir
        report_config['include_closed'] = self.include_closed_check.isChecked()
        report_config['min_rs_rating'] = self.min_rs_spin.value()
        report_config['top_picks_count'] = self.top_picks_spin.value()

        # Disable UI during generation
        self.generate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Generating report...")

        # Create and start background thread
        self.generator_thread = ReportGeneratorThread(self.config, self.db)
        self.generator_thread.finished.connect(self._on_generation_complete)
        self.generator_thread.error.connect(self._on_generation_error)
        self.generator_thread.start()

    def _on_generation_complete(self, output_path: str):
        """Handle successful report generation."""
        self.generated_file_path = output_path

        # Re-enable UI
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.open_btn.setEnabled(True)

        # Show success message
        self.status_label.setText(f"✓ Report generated successfully!")
        self.status_label.setStyleSheet("color: #00AA00; font-weight: bold;")

        # Show file location
        file_name = Path(output_path).name
        QMessageBox.information(
            self,
            "Report Generated",
            f"Weekly watchlist report has been generated:\n\n{file_name}\n\n"
            f"Location: {output_path}\n\n"
            f"Click 'Open Report' to view the file."
        )

    def _on_generation_error(self, error_msg: str):
        """Handle report generation error."""
        # Re-enable UI
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        # Show error
        self.status_label.setText("✗ Report generation failed")
        self.status_label.setStyleSheet("color: #AA0000; font-weight: bold;")

        QMessageBox.critical(
            self,
            "Report Generation Error",
            f"Failed to generate report:\n\n{error_msg}"
        )

    def _open_report(self):
        """Open the generated report file."""
        if not self.generated_file_path or not os.path.exists(self.generated_file_path):
            QMessageBox.warning(
                self,
                "File Not Found",
                "Report file not found. Please generate a new report."
            )
            return

        try:
            # Open file with default application
            os.startfile(self.generated_file_path)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Cannot Open File",
                f"Unable to open report file:\n\n{str(e)}"
            )

    def closeEvent(self, event):
        """Handle dialog close - clean up thread."""
        if self.generator_thread and self.generator_thread.isRunning():
            self.generator_thread.quit()
            self.generator_thread.wait()

        event.accept()
