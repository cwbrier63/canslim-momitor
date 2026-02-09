"""
CANSLIM Monitor - Analytics Dashboard

PyQt6 GUI for viewing factor analysis, weight optimization,
and outcome statistics with matplotlib charts.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QFileDialog, QMessageBox, QProgressBar, QGroupBox,
    QSplitter, QFrame, QHeaderView, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

# Matplotlib imports for embedding in PyQt6
try:
    import matplotlib
    matplotlib.use('QtAgg')
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.core.learning import LearningService, BacktestImporter

logger = logging.getLogger(__name__)


# Color scheme
COLORS = {
    'success': '#2ECC71',
    'partial': '#F1C40F',
    'stopped': '#E74C3C',
    'failed': '#95A5A6',
    'primary': '#3498DB',
    'accent': '#9B59B6',
    'background': '#2C3E50',
    'text': '#ECF0F1',
}

GRADE_COLORS = {
    'A+': '#00FF00', 'A': '#2ECC71', 'A-': '#27AE60',
    'B+': '#F1C40F', 'B': '#F39C12', 'B-': '#E67E22',
    'C+': '#E74C3C', 'C': '#C0392B',
    'D': '#8E44AD', 'F': '#95A5A6'
}

OUTCOME_COLORS = {
    'SUCCESS': COLORS['success'],
    'PARTIAL': COLORS['partial'],
    'STOPPED': COLORS['stopped'],
    'FAILED': COLORS['failed'],
}


class MplCanvas(FigureCanvas):
    """Matplotlib canvas widget for embedding in PyQt6."""

    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)

        # Style
        self.fig.patch.set_facecolor('#f5f5f5')
        self.axes.set_facecolor('#ffffff')

    def clear(self):
        """Clear the axes."""
        self.axes.clear()


class AnalysisWorker(QThread):
    """Background thread for running analysis."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, learning_service: LearningService):
        super().__init__()
        self.learning_service = learning_service

    def run(self):
        try:
            self.progress.emit("Running factor analysis...")
            result = self.learning_service.run_full_analysis()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ImportWorker(QThread):
    """Background thread for importing backtest data."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, db: DatabaseManager, backtest_path: str, overwrite: bool = False):
        super().__init__()
        self.db = db
        self.backtest_path = backtest_path
        self.overwrite = overwrite

    def run(self):
        try:
            self.progress.emit("Importing backtest data...")
            importer = BacktestImporter(self.db, self.backtest_path)
            stats = importer.import_all(overwrite=self.overwrite)
            self.finished.emit(stats)
        except Exception as e:
            self.error.emit(str(e))


class AnalyticsDashboard(QMainWindow):
    """Main analytics dashboard window."""

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.learning_service = LearningService(db)
        self.analysis_results = None
        self.worker = None

        self.setWindowTitle("CANSLIM Analytics Dashboard")
        self.setMinimumSize(1200, 800)

        self._build_ui()
        self._load_data()

    def _build_ui(self):
        """Build the main UI."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Add tabs
        self.tabs.addTab(self._build_overview_tab(), "Overview")
        self.tabs.addTab(self._build_factor_tab(), "Factor Analysis")
        self.tabs.addTab(self._build_weights_tab(), "Weight Management")
        self.tabs.addTab(self._build_import_tab(), "Import Data")

        # Status bar
        self.statusBar().showMessage("Ready")

    def _build_overview_tab(self) -> QWidget:
        """Build the Overview tab with charts."""
        widget = QWidget()
        layout = QGridLayout(widget)

        if not MATPLOTLIB_AVAILABLE:
            layout.addWidget(QLabel("matplotlib not installed. Run: pip install matplotlib"), 0, 0)
            return widget

        # Outcome distribution pie chart
        self.outcome_pie = MplCanvas(self, width=5, height=4)
        pie_group = QGroupBox("Outcome Distribution")
        pie_layout = QVBoxLayout(pie_group)
        pie_layout.addWidget(self.outcome_pie)
        layout.addWidget(pie_group, 0, 0)

        # Grade performance bar chart
        self.grade_bar = MplCanvas(self, width=5, height=4)
        grade_group = QGroupBox("Win Rate by Grade")
        grade_layout = QVBoxLayout(grade_group)
        grade_layout.addWidget(self.grade_bar)
        layout.addWidget(grade_group, 0, 1)

        # P&L by grade
        self.pnl_bar = MplCanvas(self, width=5, height=4)
        pnl_group = QGroupBox("Avg Return by Grade")
        pnl_layout = QVBoxLayout(pnl_group)
        pnl_layout.addWidget(self.pnl_bar)
        layout.addWidget(pnl_group, 1, 0)

        # Summary stats
        stats_group = QGroupBox("Data Summary")
        stats_layout = QVBoxLayout(stats_group)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(200)
        stats_layout.addWidget(self.summary_text)
        layout.addWidget(stats_group, 1, 1)

        # Refresh button
        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.clicked.connect(self._load_data)
        layout.addWidget(refresh_btn, 2, 0, 1, 2)

        return widget

    def _build_factor_tab(self) -> QWidget:
        """Build the Factor Analysis tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        if not MATPLOTLIB_AVAILABLE:
            layout.addWidget(QLabel("matplotlib not installed. Run: pip install matplotlib"))
            return widget

        # Factor importance chart
        self.factor_chart = MplCanvas(self, width=10, height=5)
        factor_group = QGroupBox("Factor Correlations with Success")
        factor_layout = QVBoxLayout(factor_group)
        factor_layout.addWidget(self.factor_chart)
        layout.addWidget(factor_group)

        # Factor details table
        self.factor_table = QTableWidget()
        self.factor_table.setColumnCount(5)
        self.factor_table.setHorizontalHeaderLabels([
            "Factor", "Correlation", "P-Value", "Significant", "Samples"
        ])
        self.factor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.factor_table.setMaximumHeight(200)

        table_group = QGroupBox("Factor Details")
        table_layout = QVBoxLayout(table_group)
        table_layout.addWidget(self.factor_table)
        layout.addWidget(table_group)

        # Analysis button
        btn_layout = QHBoxLayout()
        self.analyze_btn = QPushButton("Run Factor Analysis")
        self.analyze_btn.clicked.connect(self._run_analysis)
        btn_layout.addWidget(self.analyze_btn)

        self.progress_label = QLabel("")
        btn_layout.addWidget(self.progress_label)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

        return widget

    def _build_weights_tab(self) -> QWidget:
        """Build the Weight Management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Weight comparison table
        self.weights_table = QTableWidget()
        self.weights_table.setColumnCount(4)
        self.weights_table.setHorizontalHeaderLabels([
            "Factor", "Current", "Suggested", "Change %"
        ])
        self.weights_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        weights_group = QGroupBox("Weight Comparison")
        weights_layout = QVBoxLayout(weights_group)
        weights_layout.addWidget(self.weights_table)
        layout.addWidget(weights_group)

        # Weight history table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels([
            "ID", "Date", "Samples", "Accuracy", "Improvement", "Status"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        history_group = QGroupBox("Weight History")
        history_layout = QVBoxLayout(history_group)
        history_layout.addWidget(self.history_table)
        layout.addWidget(history_group)

        # Action buttons
        btn_layout = QHBoxLayout()

        self.activate_btn = QPushButton("Activate Selected")
        self.activate_btn.clicked.connect(self._activate_weights)
        btn_layout.addWidget(self.activate_btn)

        self.deactivate_btn = QPushButton("Deactivate (Use Baseline)")
        self.deactivate_btn.clicked.connect(self._deactivate_weights)
        btn_layout.addWidget(self.deactivate_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return widget

    def _build_import_tab(self) -> QWidget:
        """Build the Import Data tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Import buttons
        import_group = QGroupBox("Import Data")
        import_layout = QHBoxLayout(import_group)

        import_btn = QPushButton("Import Backtest DB")
        import_btn.clicked.connect(self._import_backtest)
        import_layout.addWidget(import_btn)

        overwrite_btn = QPushButton("Import (Overwrite)")
        overwrite_btn.clicked.connect(lambda: self._import_backtest(overwrite=True))
        import_layout.addWidget(overwrite_btn)

        import_layout.addStretch()
        layout.addWidget(import_group)

        # Rescore buttons
        rescore_group = QGroupBox("Rescore Outcomes")
        rescore_layout = QHBoxLayout(rescore_group)

        preview_btn = QPushButton("Preview Rescore")
        preview_btn.clicked.connect(self._preview_rescore)
        rescore_layout.addWidget(preview_btn)

        rescore_btn = QPushButton("Rescore All Backtest")
        rescore_btn.clicked.connect(lambda: self._rescore_outcomes('swingtrader'))
        rescore_layout.addWidget(rescore_btn)

        rescore_all_btn = QPushButton("Rescore All Outcomes")
        rescore_all_btn.clicked.connect(lambda: self._rescore_outcomes(None))
        rescore_layout.addWidget(rescore_all_btn)

        rescore_layout.addStretch()
        layout.addWidget(rescore_group)

        # Import/Rescore log
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.import_log = QTextEdit()
        self.import_log.setReadOnly(True)
        log_layout.addWidget(self.import_log)
        layout.addWidget(log_group)

        # Data summary
        summary_group = QGroupBox("Data Summary by Source")
        summary_layout = QVBoxLayout(summary_group)
        self.source_table = QTableWidget()
        self.source_table.setColumnCount(3)
        self.source_table.setHorizontalHeaderLabels(["Source", "Count", "Avg Return"])
        self.source_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.source_table.setMaximumHeight(150)
        summary_layout.addWidget(self.source_table)
        layout.addWidget(summary_group)

        return widget

    def _load_data(self):
        """Load and display data."""
        try:
            # Get outcome summary
            summary = self.learning_service.get_outcome_summary()

            # Update summary text
            text = f"""Total Outcomes: {summary.get('total', 0)}

By Source:
"""
            for source, count in summary.get('by_source', {}).items():
                text += f"  {source}: {count}\n"

            text += f"""
By Outcome:
"""
            for outcome, count in summary.get('by_outcome', {}).items():
                text += f"  {outcome}: {count}\n"

            text += f"""
Average Return: {summary.get('avg_return_pct', 0):.2f}%
Date Range: {summary.get('date_range', {}).get('start', 'N/A')} to {summary.get('date_range', {}).get('end', 'N/A')}
"""
            self.summary_text.setText(text)

            # Update charts
            if MATPLOTLIB_AVAILABLE:
                self._update_outcome_pie(summary.get('by_outcome', {}))
                self._update_grade_charts()

            # Update source table
            self._update_source_table(summary.get('by_source', {}))

            # Update weight history
            self._update_weight_history()

            self.statusBar().showMessage(f"Loaded {summary.get('total', 0)} outcomes")

        except Exception as e:
            logger.error(f"Error loading data: {e}")
            self.statusBar().showMessage(f"Error: {e}")

    def _update_outcome_pie(self, by_outcome: Dict):
        """Update outcome distribution pie chart."""
        if not by_outcome:
            return

        self.outcome_pie.clear()

        labels = list(by_outcome.keys())
        sizes = list(by_outcome.values())
        colors = [OUTCOME_COLORS.get(o, COLORS['failed']) for o in labels]

        self.outcome_pie.axes.pie(
            sizes, labels=labels, colors=colors,
            autopct='%1.1f%%', startangle=90
        )
        self.outcome_pie.axes.set_title("Outcome Distribution")
        self.outcome_pie.draw()

    def _update_grade_charts(self):
        """Update grade performance charts."""
        try:
            grade_data = self.learning_service.get_grade_performance()
            if not grade_data:
                return

            # Sort by grade
            grade_order = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'D', 'F']
            grade_data.sort(key=lambda x: grade_order.index(x['grade']) if x['grade'] in grade_order else 99)

            grades = [d['grade'] for d in grade_data]
            win_rates = [d['win_rate'] * 100 for d in grade_data]
            avg_returns = [d['avg_return'] for d in grade_data]
            colors = [GRADE_COLORS.get(g, COLORS['failed']) for g in grades]

            # Win rate bar chart
            self.grade_bar.clear()
            bars = self.grade_bar.axes.bar(grades, win_rates, color=colors)
            self.grade_bar.axes.set_ylabel('Win Rate %')
            self.grade_bar.axes.set_title('Win Rate by Entry Grade')
            self.grade_bar.axes.set_ylim(0, 100)
            self.grade_bar.axes.axhline(y=50, color='gray', linestyle='--', alpha=0.5)
            self.grade_bar.draw()

            # Avg return bar chart
            self.pnl_bar.clear()
            colors_pnl = [COLORS['success'] if r > 0 else COLORS['stopped'] for r in avg_returns]
            self.pnl_bar.axes.bar(grades, avg_returns, color=colors_pnl)
            self.pnl_bar.axes.set_ylabel('Avg Return %')
            self.pnl_bar.axes.set_title('Average Return by Entry Grade')
            self.pnl_bar.axes.axhline(y=0, color='gray', linestyle='-', alpha=0.5)
            self.pnl_bar.draw()

        except Exception as e:
            logger.error(f"Error updating grade charts: {e}")

    def _update_source_table(self, by_source: Dict):
        """Update source summary table."""
        self.source_table.setRowCount(len(by_source))

        for i, (source, count) in enumerate(by_source.items()):
            self.source_table.setItem(i, 0, QTableWidgetItem(source))
            self.source_table.setItem(i, 1, QTableWidgetItem(str(count)))
            self.source_table.setItem(i, 2, QTableWidgetItem("N/A"))

    def _update_weight_history(self):
        """Update weight history table."""
        try:
            history = self.learning_service.get_weight_history()

            self.history_table.setRowCount(len(history))

            for i, record in enumerate(history):
                self.history_table.setItem(i, 0, QTableWidgetItem(str(record['id'])))
                self.history_table.setItem(i, 1, QTableWidgetItem(
                    record['created_at'][:10] if record['created_at'] else 'N/A'
                ))
                self.history_table.setItem(i, 2, QTableWidgetItem(str(record['sample_size'] or 0)))
                self.history_table.setItem(i, 3, QTableWidgetItem(
                    f"{record['accuracy']*100:.1f}%" if record['accuracy'] else 'N/A'
                ))
                self.history_table.setItem(i, 4, QTableWidgetItem(
                    f"{record['improvement_pct']:+.1f}%" if record['improvement_pct'] else 'N/A'
                ))

                status = "ACTIVE" if record['is_active'] else ""
                status_item = QTableWidgetItem(status)
                if record['is_active']:
                    status_item.setBackground(QColor(COLORS['success']))
                self.history_table.setItem(i, 5, status_item)

        except Exception as e:
            logger.error(f"Error updating weight history: {e}")

    def _run_analysis(self):
        """Run factor analysis in background thread."""
        self.analyze_btn.setEnabled(False)
        self.progress_label.setText("Running analysis...")

        self.worker = AnalysisWorker(self.learning_service)
        self.worker.finished.connect(self._on_analysis_complete)
        self.worker.error.connect(self._on_analysis_error)
        self.worker.progress.connect(lambda msg: self.progress_label.setText(msg))
        self.worker.start()

    def _on_analysis_complete(self, result: Dict):
        """Handle analysis completion."""
        self.analyze_btn.setEnabled(True)
        self.analysis_results = result

        if result.get('status') == 'insufficient_data':
            self.progress_label.setText(result.get('message', 'Insufficient data'))
            QMessageBox.warning(self, "Insufficient Data", result.get('message', 'Not enough outcomes for analysis'))
            return

        self.progress_label.setText("Analysis complete!")

        # Update factor chart
        if MATPLOTLIB_AVAILABLE and 'analysis' in result:
            self._update_factor_chart(result['analysis'])

        # Update factor table
        self._update_factor_table(result.get('analysis', {}))

        # Update weights comparison
        if 'optimization' in result:
            self._update_weights_comparison(result['optimization'])

        # Refresh weight history
        self._update_weight_history()

        self.statusBar().showMessage("Analysis complete")

    def _on_analysis_error(self, error: str):
        """Handle analysis error."""
        self.analyze_btn.setEnabled(True)
        self.progress_label.setText(f"Error: {error}")
        QMessageBox.critical(self, "Analysis Error", str(error))

    def _update_factor_chart(self, analysis: Dict):
        """Update factor correlation chart."""
        factors = analysis.get('factors', {})
        if not factors:
            return

        self.factor_chart.clear()

        # Sort by absolute correlation
        sorted_factors = sorted(
            factors.items(),
            key=lambda x: abs(x[1].get('correlation', 0)),
            reverse=True
        )

        names = [f[0] for f in sorted_factors[:10]]
        correlations = [f[1].get('correlation', 0) for f in sorted_factors[:10]]
        colors = [COLORS['success'] if c > 0 else COLORS['stopped'] for c in correlations]

        y_pos = range(len(names))
        self.factor_chart.axes.barh(y_pos, correlations, color=colors)
        self.factor_chart.axes.set_yticks(y_pos)
        self.factor_chart.axes.set_yticklabels(names)
        self.factor_chart.axes.set_xlabel('Correlation with Success')
        self.factor_chart.axes.set_title('Factor Importance')
        self.factor_chart.axes.axvline(x=0, color='gray', linestyle='-')
        self.factor_chart.fig.tight_layout()
        self.factor_chart.draw()

    def _update_factor_table(self, analysis: Dict):
        """Update factor details table."""
        factors = analysis.get('factors', {})

        self.factor_table.setRowCount(len(factors))

        for i, (name, data) in enumerate(factors.items()):
            self.factor_table.setItem(i, 0, QTableWidgetItem(name))
            self.factor_table.setItem(i, 1, QTableWidgetItem(
                f"{data.get('correlation', 0):.4f}"
            ))
            self.factor_table.setItem(i, 2, QTableWidgetItem(
                f"{data.get('p_value', 1):.4f}"
            ))

            sig_item = QTableWidgetItem("Yes" if data.get('is_significant') else "No")
            if data.get('is_significant'):
                sig_item.setBackground(QColor(COLORS['success']))
            self.factor_table.setItem(i, 3, sig_item)

            self.factor_table.setItem(i, 4, QTableWidgetItem(
                str(data.get('sample_count', 0))
            ))

    def _update_weights_comparison(self, optimization: Dict):
        """Update weights comparison table."""
        suggested = optimization.get('suggested_weights', {})
        if not suggested:
            return

        # For now, show suggested weights
        self.weights_table.setRowCount(len(suggested))

        for i, (factor, weight) in enumerate(suggested.items()):
            self.weights_table.setItem(i, 0, QTableWidgetItem(factor))
            self.weights_table.setItem(i, 1, QTableWidgetItem("baseline"))
            self.weights_table.setItem(i, 2, QTableWidgetItem(f"{weight:.1f}"))
            self.weights_table.setItem(i, 3, QTableWidgetItem("N/A"))

    def _activate_weights(self):
        """Activate selected weights."""
        selected = self.history_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a weight set to activate")
            return

        row = selected[0].row()
        weights_id = int(self.history_table.item(row, 0).text())

        reply = QMessageBox.question(
            self, "Confirm Activation",
            f"Activate weight set #{weights_id}?\n\nThis will affect future scoring.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.learning_service.activate_weights(weights_id):
                self._update_weight_history()
                self.statusBar().showMessage(f"Activated weights #{weights_id}")
            else:
                QMessageBox.warning(self, "Error", "Failed to activate weights")

    def _deactivate_weights(self):
        """Deactivate all learned weights (revert to baseline)."""
        selected = self.history_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a weight set to deactivate")
            return

        row = selected[0].row()
        weights_id = int(self.history_table.item(row, 0).text())

        if self.learning_service.deactivate_weights(weights_id):
            self._update_weight_history()
            self.statusBar().showMessage("Reverted to baseline weights")

    def _import_backtest(self, overwrite: bool = False):
        """Import backtest data."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Backtest Database",
            "C:/Trading",
            "SQLite Database (*.db)"
        )

        if not file_path:
            return

        self.import_log.append(f"Importing from: {file_path}")
        self.import_log.append(f"Overwrite mode: {overwrite}")

        self.import_worker = ImportWorker(self.db, file_path, overwrite)
        self.import_worker.finished.connect(self._on_import_complete)
        self.import_worker.error.connect(self._on_import_error)
        self.import_worker.progress.connect(lambda msg: self.import_log.append(msg))
        self.import_worker.start()

    def _on_import_complete(self, stats: Dict):
        """Handle import completion."""
        self.import_log.append("")
        self.import_log.append("=" * 40)
        self.import_log.append("IMPORT COMPLETE")
        self.import_log.append(f"Total read: {stats.get('total_read', 0)}")
        self.import_log.append(f"Imported: {stats.get('imported', 0)}")
        self.import_log.append(f"Skipped (duplicate): {stats.get('skipped_duplicate', 0)}")
        self.import_log.append(f"Skipped (missing data): {stats.get('skipped_missing_data', 0)}")
        self.import_log.append(f"Errors: {stats.get('errors', 0)}")
        self.import_log.append("=" * 40)

        # Refresh data
        self._load_data()

        QMessageBox.information(
            self, "Import Complete",
            f"Imported {stats.get('imported', 0)} outcomes"
        )

    def _on_import_error(self, error: str):
        """Handle import error."""
        self.import_log.append(f"ERROR: {error}")
        QMessageBox.critical(self, "Import Error", str(error))

    def _preview_rescore(self):
        """Preview what rescoring would produce."""
        try:
            self.import_log.append("")
            self.import_log.append("=" * 40)
            self.import_log.append("RESCORE PREVIEW (first 10 outcomes)")
            self.import_log.append("=" * 40)

            previews = self.learning_service.get_rescore_preview(source='swingtrader', limit=10)

            for p in previews:
                old = p.get('old_grade') or 'N/A'
                new = p.get('new_grade') or 'N/A'
                change = "" if old == new else f" -> {new}"
                self.import_log.append(
                    f"{p['symbol']:6} RS:{p.get('rs_rating', 'N/A'):>3} "
                    f"Depth:{p.get('depth', 0):>5.1f}% "
                    f"Grade: {old}{change} "
                    f"Score:{p.get('new_score', 0):>3} "
                    f"Return:{p.get('return_pct', 0):>6.1f}% [{p.get('outcome', '')}]"
                )

            self.import_log.append("")
            self.import_log.append("Preview complete. Use 'Rescore All' to apply changes.")

        except Exception as e:
            self.import_log.append(f"ERROR: {e}")
            logger.error(f"Rescore preview error: {e}", exc_info=True)

    def _rescore_outcomes(self, source: str = None):
        """Rescore outcomes using current scoring rules."""
        source_desc = source if source else "all"

        reply = QMessageBox.question(
            self, "Confirm Rescore",
            f"Rescore {source_desc} outcomes using current scoring rules?\n\n"
            "This will update entry_score and entry_grade for all matching outcomes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self.import_log.append("")
            self.import_log.append("=" * 40)
            self.import_log.append(f"RESCORING {source_desc.upper()} OUTCOMES")
            self.import_log.append("=" * 40)

            stats = self.learning_service.rescore_outcomes(source=source)

            self.import_log.append(f"Total outcomes: {stats.get('total', 0)}")
            self.import_log.append(f"Rescored: {stats.get('rescored', 0)}")
            self.import_log.append(f"Skipped (no data): {stats.get('skipped_no_data', 0)}")
            self.import_log.append(f"Errors: {stats.get('errors', 0)}")
            self.import_log.append("")
            self.import_log.append("Grade distribution:")

            for grade, count in sorted(stats.get('grade_distribution', {}).items()):
                self.import_log.append(f"  {grade}: {count}")

            self.import_log.append("=" * 40)

            # Refresh data
            self._load_data()

            QMessageBox.information(
                self, "Rescore Complete",
                f"Rescored {stats.get('rescored', 0)} outcomes\n\n"
                f"Grade distribution:\n" +
                "\n".join(f"  {g}: {c}" for g, c in sorted(stats.get('grade_distribution', {}).items()))
            )

        except Exception as e:
            self.import_log.append(f"ERROR: {e}")
            logger.error(f"Rescore error: {e}", exc_info=True)
            QMessageBox.critical(self, "Rescore Error", str(e))
