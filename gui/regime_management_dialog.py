"""
Regime Management Dialog - Enhanced Version

Dialog for managing market regime data including:
- Viewing current status
- Seeding FULL historical regime data (like CLI seed command)
- Trend analysis with charts and statistics
- Data reset capabilities
- CSV export
"""

import logging
import time
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QGroupBox, QTextEdit,
    QSpinBox, QProgressBar, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QMessageBox,
    QCheckBox, QFrame, QFileDialog, QDateEdit,
    QComboBox, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtGui import QFont, QColor

logger = logging.getLogger(__name__)


class FullRegimeSeedWorker(QThread):
    """
    Worker thread for seeding FULL historical regime data.
    
    This replicates the CLI 'seed' command - runs complete regime calculation
    for each historical day including:
    - Distribution day analysis
    - FTD tracking
    - Composite score calculation
    - Full MarketRegimeAlert storage
    """
    
    progress = pyqtSignal(int, int, str)  # current, total, message
    day_complete = pyqtSignal(str, str, bool)  # date, result, success
    finished = pyqtSignal(dict)  # Summary stats
    error = pyqtSignal(str)
    
    def __init__(
        self, 
        config: dict, 
        db_session_factory,
        days: int = 60,
        delay_seconds: int = 25,
        skip_existing: bool = True
    ):
        super().__init__()
        self.config = config
        self.db_session_factory = db_session_factory
        self.days = days
        self.delay_seconds = delay_seconds
        self.skip_existing = skip_existing
        self._stop_requested = False
    
    def stop(self):
        """Request the worker to stop."""
        self._stop_requested = True
    
    def run(self):
        """Run the full historical seeding process."""
        try:
            from canslim_monitor.regime.historical_data import MassiveHistoricalClient
            from canslim_monitor.regime.distribution_tracker import DistributionDayTracker
            from canslim_monitor.regime.market_regime import (
                MarketRegimeCalculator, DistributionData, create_overnight_data, FTDData
            )
            from canslim_monitor.regime.ftd_tracker import FollowThroughDayTracker
            from canslim_monitor.regime.models_regime import (
                MarketRegimeAlert, RegimeType, DDayTrend
            )
            
            # Calculate date range
            end_date = date.today()
            # Rough estimate: 252 trading days/year, multiply by 1.4 for calendar days
            calendar_days = int(self.days * 1.4)
            start_date = end_date - timedelta(days=calendar_days)
            
            self.progress.emit(0, self.days, f"Starting seed from {start_date} to {end_date}...")
            
            # Create client
            client = MassiveHistoricalClient.from_config(self.config)
            
            current = start_date
            processed = 0
            skipped = 0
            errors = 0
            day_index = 0
            
            while current <= end_date and not self._stop_requested:
                # Skip weekends
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    continue
                
                day_index += 1
                
                # Check if already exists
                session = self.db_session_factory()
                try:
                    if self.skip_existing:
                        existing = session.query(MarketRegimeAlert).filter(
                            MarketRegimeAlert.date == current
                        ).first()
                        
                        if existing:
                            skipped += 1
                            self.day_complete.emit(
                                current.isoformat(), 
                                "Skipped (exists)", 
                                True
                            )
                            current += timedelta(days=1)
                            continue
                    
                    self.progress.emit(
                        day_index, 
                        self.days, 
                        f"Processing {current.isoformat()}..."
                    )
                    
                    # Fetch historical data for this date
                    spy_bars = client.get_daily_bars('SPY', lookback_days=40, end_date=current)
                    qqq_bars = client.get_daily_bars('QQQ', lookback_days=40, end_date=current)
                    
                    if not spy_bars or not qqq_bars:
                        errors += 1
                        self.day_complete.emit(
                            current.isoformat(),
                            "No data available",
                            False
                        )
                        current += timedelta(days=1)
                        time.sleep(self.delay_seconds)
                        continue
                    
                    # Calculate distribution days
                    tracker = DistributionDayTracker.from_config(self.config, session)
                    combined = tracker.get_combined_data(spy_bars, qqq_bars)
                    
                    # Calculate FTD status
                    ftd_tracker = FollowThroughDayTracker(session)
                    ftd_status = ftd_tracker.get_market_phase_status(
                        spy_bars, qqq_bars,
                        spy_d_count=combined.spy_count,
                        qqq_d_count=combined.qqq_count
                    )
                    
                    # Build rally histogram
                    trading_days = [bar.date for bar in spy_bars]
                    rally_histogram = ftd_tracker.build_rally_histogram(trading_days)
                    
                    # Create FTD data
                    ftd_data = FTDData(
                        market_phase=ftd_status.phase.value,
                        in_rally_attempt=(ftd_status.spy_status.in_rally_attempt or 
                                          ftd_status.qqq_status.in_rally_attempt),
                        rally_day=max(ftd_status.spy_status.rally_day, 
                                     ftd_status.qqq_status.rally_day),
                        has_confirmed_ftd=(ftd_status.spy_status.has_confirmed_ftd or 
                                           ftd_status.qqq_status.has_confirmed_ftd),
                        ftd_still_valid=(ftd_status.spy_status.ftd_still_valid or 
                                         ftd_status.qqq_status.ftd_still_valid),
                        days_since_ftd=ftd_status.days_since_last_ftd,
                        ftd_today=ftd_status.any_ftd_today,
                        rally_failed_today=ftd_status.any_rally_failed,
                        ftd_score_adjustment=ftd_status.ftd_score_adjustment,
                        spy_ftd_date=ftd_status.spy_status.last_ftd_date,
                        qqq_ftd_date=ftd_status.qqq_status.last_ftd_date,
                        rally_histogram=rally_histogram,
                        failed_rally_count=rally_histogram.failed_count,
                        successful_ftd_count=rally_histogram.success_count
                    )
                    
                    # Create distribution data
                    dist_data = DistributionData(
                        spy_count=combined.spy_count,
                        qqq_count=combined.qqq_count,
                        spy_5day_delta=combined.spy_5day_delta,
                        qqq_5day_delta=combined.qqq_5day_delta,
                        trend=combined.trend,
                        spy_dates=combined.spy_dates,
                        qqq_dates=combined.qqq_dates
                    )
                    
                    # Mock overnight data for historical dates
                    overnight = create_overnight_data(0.0, 0.0, 0.0)
                    
                    # Calculate regime
                    calc = MarketRegimeCalculator(self.config.get('market_regime', {}))
                    score = calc.calculate_regime(dist_data, overnight, None, ftd_data=ftd_data)
                    
                    # Save to database
                    self._save_regime_alert(session, score, current, combined, ftd_data)
                    
                    processed += 1
                    self.day_complete.emit(
                        current.isoformat(),
                        f"{score.regime.value} (score: {score.composite_score:+.2f})",
                        True
                    )
                    
                except Exception as e:
                    errors += 1
                    self.day_complete.emit(
                        current.isoformat(),
                        f"Error: {str(e)[:40]}",
                        False
                    )
                    logger.exception(f"Error processing {current}")
                    
                finally:
                    session.close()
                
                current += timedelta(days=1)
                
                # Rate limit delay (skip on last day)
                if current <= end_date and not self._stop_requested:
                    time.sleep(self.delay_seconds)
            
            # Final summary
            self.finished.emit({
                'processed': processed,
                'skipped': skipped,
                'errors': errors,
                'stopped': self._stop_requested
            })
            
        except Exception as e:
            logger.exception("Error in FullRegimeSeedWorker")
            self.error.emit(str(e))
    
    def _save_regime_alert(self, session, score, target_date, combined, ftd_data):
        """Save regime alert to database."""
        from canslim_monitor.regime.models_regime import MarketRegimeAlert
        
        # Check for existing
        existing = session.query(MarketRegimeAlert).filter(
            MarketRegimeAlert.date == target_date
        ).first()
        
        if existing:
            # Update existing
            existing.spy_d_count = combined.spy_count
            existing.qqq_d_count = combined.qqq_count
            existing.spy_5day_delta = combined.spy_5day_delta
            existing.qqq_5day_delta = combined.qqq_5day_delta
            existing.d_day_trend = combined.trend
            existing.composite_score = score.composite_score
            existing.regime = score.regime
            existing.market_phase = ftd_data.market_phase
            existing.in_rally_attempt = ftd_data.in_rally_attempt
            existing.rally_day = ftd_data.rally_day
            existing.has_confirmed_ftd = ftd_data.has_confirmed_ftd
        else:
            # Create new
            alert = MarketRegimeAlert(
                date=target_date,
                spy_d_count=combined.spy_count,
                qqq_d_count=combined.qqq_count,
                spy_5day_delta=combined.spy_5day_delta,
                qqq_5day_delta=combined.qqq_5day_delta,
                d_day_trend=combined.trend,
                composite_score=score.composite_score,
                regime=score.regime,
                market_phase=ftd_data.market_phase,
                in_rally_attempt=ftd_data.in_rally_attempt,
                rally_day=ftd_data.rally_day,
                has_confirmed_ftd=ftd_data.has_confirmed_ftd,
                es_change_pct=0.0,
                nq_change_pct=0.0,
                ym_change_pct=0.0
            )
            session.add(alert)
        
        session.commit()


class RegimeManagementDialog(QDialog):
    """
    Dialog for managing market regime data.
    
    Features:
    - Current status view
    - Full historical regime seeding
    - Trend analysis with statistics
    - Data reset
    - CSV export
    """
    
    data_updated = pyqtSignal()
    
    def __init__(
        self,
        parent=None,
        config: dict = None,
        db_session_factory=None,
        ibkr_client=None
    ):
        super().__init__(parent)
        self.config = config or {}
        self.db_session_factory = db_session_factory
        self.ibkr_client = ibkr_client
        self.seed_worker = None
        
        self.setWindowTitle("Market Regime Management")
        self.setMinimumWidth(750)
        self.setMinimumHeight(600)
        self.setModal(True)
        
        self._setup_ui()
        self._load_current_status()
        self._load_trend_analysis()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Tab widget
        tabs = QTabWidget()
        
        # Tab 1: Status
        status_tab = QWidget()
        self._setup_status_tab(status_tab)
        tabs.addTab(status_tab, "📊 Current Status")
        
        # Tab 2: Seed Data (FULL)
        seed_tab = QWidget()
        self._setup_seed_tab(seed_tab)
        tabs.addTab(seed_tab, "🌱 Seed History")
        
        # Tab 3: Trend Analysis
        trend_tab = QWidget()
        self._setup_trend_tab(trend_tab)
        tabs.addTab(trend_tab, "📈 Trend Analysis")
        
        # Tab 4: Reset
        reset_tab = QWidget()
        self._setup_reset_tab(reset_tab)
        tabs.addTab(reset_tab, "🔄 Reset")
        
        layout.addWidget(tabs)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    
    def _setup_status_tab(self, tab: QWidget):
        """Set up the status tab."""
        layout = QVBoxLayout(tab)
        
        # Distribution Days Group
        dd_group = QGroupBox("Distribution Days (Rolling 25-Day)")
        dd_layout = QVBoxLayout(dd_group)
        
        # SPY/QQQ counts
        counts_layout = QHBoxLayout()
        
        self.spy_count_label = QLabel("SPY: --")
        self.spy_count_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        counts_layout.addWidget(self.spy_count_label)
        
        self.qqq_count_label = QLabel("QQQ: --")
        self.qqq_count_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        counts_layout.addWidget(self.qqq_count_label)
        
        counts_layout.addStretch()
        dd_layout.addLayout(counts_layout)
        
        # Distribution day dates table
        self.dd_table = QTableWidget()
        self.dd_table.setColumnCount(4)
        self.dd_table.setHorizontalHeaderLabels(["Symbol", "Date", "% Change", "Status"])
        self.dd_table.setMaximumHeight(180)
        dd_layout.addWidget(self.dd_table)
        
        layout.addWidget(dd_group)
        
        # Current Regime Group
        regime_group = QGroupBox("Current Regime")
        regime_layout = QHBoxLayout(regime_group)
        
        self.regime_label = QLabel("--")
        self.regime_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        regime_layout.addWidget(self.regime_label)
        
        self.score_label = QLabel("Score: --")
        self.score_label.setStyleSheet("font-size: 14px;")
        regime_layout.addWidget(self.score_label)
        
        self.phase_label = QLabel("Phase: --")
        self.phase_label.setStyleSheet("font-size: 14px;")
        regime_layout.addWidget(self.phase_label)
        
        regime_layout.addStretch()
        layout.addWidget(regime_group)
        
        # Futures Group
        futures_group = QGroupBox("Overnight Futures (from last alert)")
        futures_layout = QHBoxLayout(futures_group)
        
        self.es_label = QLabel("ES: --")
        futures_layout.addWidget(self.es_label)
        
        self.nq_label = QLabel("NQ: --")
        futures_layout.addWidget(self.nq_label)
        
        self.ym_label = QLabel("YM: --")
        futures_layout.addWidget(self.ym_label)
        
        futures_layout.addStretch()
        layout.addWidget(futures_group)
        
        # Last Updated
        self.last_updated_label = QLabel("Last regime alert: --")
        self.last_updated_label.setStyleSheet("color: #888;")
        layout.addWidget(self.last_updated_label)
        
        # Database stats
        self.db_stats_label = QLabel("Database: -- regime alerts")
        self.db_stats_label.setStyleSheet("color: #888;")
        layout.addWidget(self.db_stats_label)
        
        layout.addStretch()
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Status")
        refresh_btn.clicked.connect(self._load_current_status)
        layout.addWidget(refresh_btn)
    
    def _setup_seed_tab(self, tab: QWidget):
        """Set up the full seed data tab."""
        layout = QVBoxLayout(tab)
        
        # Description
        desc = QLabel(
            "<b>Seed Full Historical Regime Data</b><br><br>"
            "This runs the complete morning regime calculation for each historical day:<br>"
            "• Fetches SPY/QQQ historical data from Polygon<br>"
            "• Calculates distribution days<br>"
            "• Analyzes Follow-Through Day status<br>"
            "• Computes composite regime score<br>"
            "• Saves full MarketRegimeAlert to database<br><br>"
            "<i>Note: Polygon free tier allows 5 API calls/minute. "
            "Each day needs 2 calls, so seeding is rate-limited.</i>"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # Options Group
        options_group = QGroupBox("Seeding Options")
        options_layout = QFormLayout(options_group)
        
        self.seed_days_spin = QSpinBox()
        self.seed_days_spin.setRange(10, 252)
        self.seed_days_spin.setValue(60)
        self.seed_days_spin.setSuffix(" trading days")
        self.seed_days_spin.valueChanged.connect(self._update_time_estimate)
        options_layout.addRow("Days to Seed:", self.seed_days_spin)
        
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(5, 60)
        self.delay_spin.setValue(25)
        self.delay_spin.setSuffix(" seconds")
        self.delay_spin.setToolTip("Delay between API calls (Polygon rate limit)")
        self.delay_spin.valueChanged.connect(self._update_time_estimate)
        options_layout.addRow("Rate Limit Delay:", self.delay_spin)
        
        self.skip_existing_check = QCheckBox("Skip existing dates")
        self.skip_existing_check.setChecked(True)
        self.skip_existing_check.setToolTip("Don't overwrite days already in database")
        options_layout.addRow("", self.skip_existing_check)
        
        self.time_estimate_label = QLabel("Estimated time: ~25 minutes")
        self.time_estimate_label.setStyleSheet("color: #888;")
        options_layout.addRow("", self.time_estimate_label)
        
        layout.addWidget(options_group)
        
        # Progress Group
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        self.seed_progress = QProgressBar()
        self.seed_progress.setRange(0, 100)
        self.seed_progress.setValue(0)
        progress_layout.addWidget(self.seed_progress)
        
        self.seed_status_label = QLabel("Ready to seed")
        progress_layout.addWidget(self.seed_status_label)
        
        # Log area
        self.seed_log = QTextEdit()
        self.seed_log.setReadOnly(True)
        self.seed_log.setMaximumHeight(150)
        self.seed_log.setStyleSheet("font-family: monospace; font-size: 11px;")
        progress_layout.addWidget(self.seed_log)
        
        layout.addWidget(progress_group)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.seed_btn = QPushButton("🌱 Start Seeding")
        self.seed_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.seed_btn.clicked.connect(self._start_full_seed)
        btn_layout.addWidget(self.seed_btn)
        
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.stop_btn.clicked.connect(self._stop_seed)
        btn_layout.addWidget(self.stop_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self._update_time_estimate()
    
    def _setup_trend_tab(self, tab: QWidget):
        """Set up the trend analysis tab."""
        layout = QVBoxLayout(tab)
        
        # Period selection
        period_layout = QHBoxLayout()
        period_layout.addWidget(QLabel("Analysis Period:"))
        
        self.trend_days_combo = QComboBox()
        self.trend_days_combo.addItems(["30 days", "60 days", "90 days", "120 days", "All"])
        self.trend_days_combo.setCurrentIndex(1)  # Default 60 days
        self.trend_days_combo.currentIndexChanged.connect(self._load_trend_analysis)
        period_layout.addWidget(self.trend_days_combo)
        
        period_layout.addStretch()
        
        refresh_trend_btn = QPushButton("🔄 Refresh")
        refresh_trend_btn.clicked.connect(self._load_trend_analysis)
        period_layout.addWidget(refresh_trend_btn)
        
        export_btn = QPushButton("📥 Export CSV")
        export_btn.clicked.connect(self._export_trend_csv)
        period_layout.addWidget(export_btn)
        
        layout.addLayout(period_layout)
        
        # Scroll area for analysis content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        # Regime Distribution
        dist_group = QGroupBox("📊 Regime Distribution")
        dist_layout = QVBoxLayout(dist_group)
        self.regime_dist_label = QLabel("Loading...")
        self.regime_dist_label.setStyleSheet("font-family: monospace;")
        dist_layout.addWidget(self.regime_dist_label)
        scroll_layout.addWidget(dist_group)
        
        # Score Statistics
        stats_group = QGroupBox("📈 Score Statistics")
        stats_layout = QVBoxLayout(stats_group)
        self.score_stats_label = QLabel("Loading...")
        self.score_stats_label.setStyleSheet("font-family: monospace;")
        stats_layout.addWidget(self.score_stats_label)
        scroll_layout.addWidget(stats_group)
        
        # D-Day Averages
        dday_group = QGroupBox("📉 Distribution Day Averages")
        dday_layout = QVBoxLayout(dday_group)
        self.dday_stats_label = QLabel("Loading...")
        self.dday_stats_label.setStyleSheet("font-family: monospace;")
        dday_layout.addWidget(self.dday_stats_label)
        scroll_layout.addWidget(dday_group)
        
        # Regime Changes
        changes_group = QGroupBox("🔄 Recent Regime Changes")
        changes_layout = QVBoxLayout(changes_group)
        self.regime_changes_label = QLabel("Loading...")
        self.regime_changes_label.setStyleSheet("font-family: monospace;")
        changes_layout.addWidget(self.regime_changes_label)
        scroll_layout.addWidget(changes_group)
        
        # Score Chart (ASCII)
        chart_group = QGroupBox("📈 Score Trend (Last 20 Days)")
        chart_layout = QVBoxLayout(chart_group)
        self.score_chart_label = QLabel("Loading...")
        self.score_chart_label.setStyleSheet("font-family: monospace; font-size: 12px;")
        chart_layout.addWidget(self.score_chart_label)
        scroll_layout.addWidget(chart_group)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
    
    def _setup_reset_tab(self, tab: QWidget):
        """Set up the reset tab."""
        layout = QVBoxLayout(tab)
        
        # Warning
        warning = QLabel(
            "⚠️ <b>WARNING: These operations cannot be undone!</b><br><br>"
            "Reset options will permanently delete data from the database."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #DC3545;")
        layout.addWidget(warning)
        
        # Reset options
        options_group = QGroupBox("Select Data to Reset")
        options_layout = QVBoxLayout(options_group)
        
        self.reset_alerts_check = QCheckBox("Regime Alerts (MarketRegimeAlert)")
        self.reset_alerts_check.setToolTip("Delete all market regime alert records")
        options_layout.addWidget(self.reset_alerts_check)
        
        self.reset_dd_check = QCheckBox("Distribution Days")
        self.reset_dd_check.setToolTip("Delete all distribution day records")
        options_layout.addWidget(self.reset_dd_check)
        
        self.reset_counts_check = QCheckBox("Daily Counts History")
        self.reset_counts_check.setToolTip("Delete distribution day count history")
        options_layout.addWidget(self.reset_counts_check)
        
        self.reset_futures_check = QCheckBox("Overnight Trends")
        self.reset_futures_check.setToolTip("Delete overnight futures trend records")
        options_layout.addWidget(self.reset_futures_check)
        
        self.reset_ftd_check = QCheckBox("FTD Tracking Data")
        self.reset_ftd_check.setToolTip("Delete follow-through day and rally attempt records")
        options_layout.addWidget(self.reset_ftd_check)
        
        self.reset_ibd_check = QCheckBox("IBD Exposure History")
        self.reset_ibd_check.setToolTip("Delete IBD exposure history (keeps current setting)")
        options_layout.addWidget(self.reset_ibd_check)
        
        layout.addWidget(options_group)
        
        # Select all / none
        select_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all_reset)
        select_layout.addWidget(select_all_btn)
        
        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(self._select_none_reset)
        select_layout.addWidget(select_none_btn)
        
        select_layout.addStretch()
        layout.addLayout(select_layout)
        
        layout.addStretch()
        
        # Reset button
        reset_btn = QPushButton("🗑️ Reset Selected Data")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
        """)
        reset_btn.clicked.connect(self._do_reset)
        layout.addWidget(reset_btn)
    
    # =========================================================================
    # Status Tab Methods
    # =========================================================================
    
    def _load_current_status(self):
        """Load current status from database."""
        if not self.db_session_factory:
            return
            
        try:
            session = self.db_session_factory()
            try:
                from canslim_monitor.regime.models_regime import (
                    MarketRegimeAlert, DistributionDay
                )
                
                # Get latest regime alert
                latest = session.query(MarketRegimeAlert).order_by(
                    MarketRegimeAlert.date.desc()
                ).first()
                
                # Count total alerts
                total_alerts = session.query(MarketRegimeAlert).count()
                self.db_stats_label.setText(f"Database: {total_alerts} regime alerts")
                
                if latest:
                    # D-day counts
                    self.spy_count_label.setText(f"SPY: {latest.spy_d_count}")
                    self.qqq_count_label.setText(f"QQQ: {latest.qqq_d_count}")
                    
                    spy_color = self._get_count_color(latest.spy_d_count)
                    qqq_color = self._get_count_color(latest.qqq_d_count)
                    self.spy_count_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {spy_color};")
                    self.qqq_count_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {qqq_color};")
                    
                    # Regime
                    regime_colors = {
                        'BULLISH': '#28A745',
                        'NEUTRAL': '#FFC107',
                        'BEARISH': '#DC3545'
                    }
                    regime_val = latest.regime.value if hasattr(latest.regime, 'value') else str(latest.regime)
                    self.regime_label.setText(regime_val)
                    self.regime_label.setStyleSheet(
                        f"font-size: 20px; font-weight: bold; color: {regime_colors.get(regime_val, 'white')};"
                    )
                    self.score_label.setText(f"Score: {latest.composite_score:+.2f}")
                    self.phase_label.setText(f"Phase: {latest.market_phase or 'N/A'}")
                    
                    # Futures
                    if latest.es_change_pct is not None:
                        self.es_label.setText(f"ES: {latest.es_change_pct:+.2f}%")
                        self._color_label(self.es_label, latest.es_change_pct)
                    if latest.nq_change_pct is not None:
                        self.nq_label.setText(f"NQ: {latest.nq_change_pct:+.2f}%")
                        self._color_label(self.nq_label, latest.nq_change_pct)
                    if latest.ym_change_pct is not None:
                        self.ym_label.setText(f"YM: {latest.ym_change_pct:+.2f}%")
                        self._color_label(self.ym_label, latest.ym_change_pct)
                    
                    self.last_updated_label.setText(
                        f"Last regime alert: {latest.date.strftime('%Y-%m-%d %H:%M') if hasattr(latest.date, 'strftime') else latest.date}"
                    )
                
                # Get active distribution days
                cutoff = date.today() - timedelta(days=25)
                active_ddays = session.query(DistributionDay).filter(
                    DistributionDay.date >= cutoff,
                    DistributionDay.expired == False
                ).order_by(DistributionDay.date.desc()).all()
                
                # Populate table
                self.dd_table.setRowCount(len(active_ddays))
                for i, dd in enumerate(active_ddays):
                    self.dd_table.setItem(i, 0, QTableWidgetItem(dd.symbol))
                    self.dd_table.setItem(i, 1, QTableWidgetItem(str(dd.date)))
                    self.dd_table.setItem(i, 2, QTableWidgetItem(f"{dd.pct_change:+.2f}%"))
                    self.dd_table.setItem(i, 3, QTableWidgetItem("Active"))
                
                self.dd_table.resizeColumnsToContents()
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error loading status: {e}")
    
    def _get_count_color(self, count: int) -> str:
        """Get color for distribution day count."""
        if count <= 2:
            return "#28A745"
        elif count <= 4:
            return "#FFC107"
        elif count <= 5:
            return "#FFA500"
        else:
            return "#DC3545"
    
    def _color_label(self, label: QLabel, pct: float):
        """Color a label based on value."""
        color = "#28A745" if pct >= 0 else "#DC3545"
        label.setStyleSheet(f"color: {color};")
    
    # =========================================================================
    # Seed Tab Methods
    # =========================================================================
    
    def _update_time_estimate(self):
        """Update estimated seed time."""
        days = self.seed_days_spin.value()
        delay = self.delay_spin.value()
        minutes = (days * delay) / 60
        self.time_estimate_label.setText(f"Estimated time: ~{minutes:.0f} minutes")
    
    def _start_full_seed(self):
        """Start the full historical seeding process."""
        if not self.db_session_factory:
            QMessageBox.warning(self, "Error", "Database not available")
            return
        
        # Confirm
        days = self.seed_days_spin.value()
        reply = QMessageBox.question(
            self, "Confirm Seed",
            f"This will seed {days} trading days of regime history.\n\n"
            f"Estimated time: ~{(days * self.delay_spin.value()) / 60:.0f} minutes\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Disable controls
        self.seed_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.seed_days_spin.setEnabled(False)
        self.delay_spin.setEnabled(False)
        self.skip_existing_check.setEnabled(False)
        
        self.seed_log.clear()
        self.seed_progress.setValue(0)
        self.seed_status_label.setText("Starting...")
        
        # Create and start worker
        self.seed_worker = FullRegimeSeedWorker(
            config=self.config,
            db_session_factory=self.db_session_factory,
            days=self.seed_days_spin.value(),
            delay_seconds=self.delay_spin.value(),
            skip_existing=self.skip_existing_check.isChecked()
        )
        
        self.seed_worker.progress.connect(self._on_seed_progress)
        self.seed_worker.day_complete.connect(self._on_day_complete)
        self.seed_worker.finished.connect(self._on_seed_finished)
        self.seed_worker.error.connect(self._on_seed_error)
        
        self.seed_worker.start()
    
    def _stop_seed(self):
        """Stop the seeding process."""
        if self.seed_worker:
            self.seed_worker.stop()
            self.seed_status_label.setText("Stopping...")
    
    def _on_seed_progress(self, current: int, total: int, message: str):
        """Handle progress update."""
        pct = int((current / total) * 100) if total > 0 else 0
        self.seed_progress.setValue(pct)
        self.seed_status_label.setText(message)
    
    def _on_day_complete(self, date_str: str, result: str, success: bool):
        """Handle day completion."""
        color = "green" if success else "red"
        symbol = "✓" if success else "✗"
        self.seed_log.append(f'<span style="color:{color}">{symbol} {date_str}: {result}</span>')
        
        # Auto-scroll to bottom
        scrollbar = self.seed_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_seed_finished(self, stats: dict):
        """Handle seed completion."""
        self.seed_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.seed_days_spin.setEnabled(True)
        self.delay_spin.setEnabled(True)
        self.skip_existing_check.setEnabled(True)
        
        self.seed_progress.setValue(100)
        
        status = "stopped" if stats.get('stopped') else "complete"
        self.seed_status_label.setText(
            f"Seeding {status}: {stats['processed']} processed, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )
        
        self.seed_log.append("")
        self.seed_log.append(f"<b>===== Seeding {status.upper()} =====</b>")
        self.seed_log.append(f"Processed: {stats['processed']}")
        self.seed_log.append(f"Skipped: {stats['skipped']}")
        self.seed_log.append(f"Errors: {stats['errors']}")
        
        # Refresh other tabs
        self._load_current_status()
        self._load_trend_analysis()
        self.data_updated.emit()
        
        self.seed_worker = None
    
    def _on_seed_error(self, error: str):
        """Handle seed error."""
        self.seed_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.seed_days_spin.setEnabled(True)
        self.delay_spin.setEnabled(True)
        self.skip_existing_check.setEnabled(True)
        
        self.seed_status_label.setText(f"Error: {error}")
        self.seed_log.append(f'<span style="color:red">ERROR: {error}</span>')
        
        QMessageBox.critical(self, "Seed Error", f"Seeding failed:\n{error}")
        
        self.seed_worker = None
    
    # =========================================================================
    # Trend Tab Methods
    # =========================================================================
    
    def _load_trend_analysis(self):
        """Load trend analysis data."""
        if not self.db_session_factory:
            return
        
        try:
            # Get days from combo
            days_text = self.trend_days_combo.currentText()
            if days_text == "All":
                days = 9999
            else:
                days = int(days_text.split()[0])
            
            session = self.db_session_factory()
            try:
                from canslim_monitor.regime.models_regime import MarketRegimeAlert, RegimeType
                
                alerts = session.query(MarketRegimeAlert).order_by(
                    MarketRegimeAlert.date.desc()
                ).limit(days).all()
                
                if not alerts:
                    self.regime_dist_label.setText("No regime history found.\nRun seeding first.")
                    self.score_stats_label.setText("N/A")
                    self.dday_stats_label.setText("N/A")
                    self.regime_changes_label.setText("N/A")
                    self.score_chart_label.setText("N/A")
                    return
                
                alerts = list(reversed(alerts))  # Oldest first
                total_days = len(alerts)
                
                # Regime distribution
                bullish = sum(1 for a in alerts if a.regime == RegimeType.BULLISH)
                neutral = sum(1 for a in alerts if a.regime == RegimeType.NEUTRAL)
                bearish = sum(1 for a in alerts if a.regime == RegimeType.BEARISH)
                
                dist_text = f"""Period: {alerts[0].date} to {alerts[-1].date} ({total_days} days)

🟢 BULLISH:  {bullish:3d} days ({100*bullish/total_days:.1f}%)  {'█' * int(20*bullish/total_days)}
🟡 NEUTRAL:  {neutral:3d} days ({100*neutral/total_days:.1f}%)  {'█' * int(20*neutral/total_days)}
🔴 BEARISH:  {bearish:3d} days ({100*bearish/total_days:.1f}%)  {'█' * int(20*bearish/total_days)}"""
                self.regime_dist_label.setText(dist_text)
                
                # Score statistics
                avg_score = sum(a.composite_score for a in alerts) / total_days
                current_score = alerts[-1].composite_score
                
                # Score trend
                if len(alerts) >= 5:
                    recent_avg = sum(a.composite_score for a in alerts[-5:]) / 5
                    older_avg = sum(a.composite_score for a in alerts[:5]) / 5
                    score_trend = recent_avg - older_avg
                    trend_arrow = '↑' if score_trend > 0.1 else '↓' if score_trend < -0.1 else '→'
                else:
                    score_trend = 0
                    trend_arrow = '→'
                
                stats_text = f"""Average Score:  {avg_score:+.2f}
Current Score:  {current_score:+.2f}
Score Trend:    {score_trend:+.2f} {trend_arrow}"""
                self.score_stats_label.setText(stats_text)
                
                # D-day averages
                avg_spy = sum(a.spy_d_count for a in alerts) / total_days
                avg_qqq = sum(a.qqq_d_count for a in alerts) / total_days
                current_spy = alerts[-1].spy_d_count
                current_qqq = alerts[-1].qqq_d_count
                
                dday_text = f"""SPY Average: {avg_spy:.1f} D-days (current: {current_spy})
QQQ Average: {avg_qqq:.1f} D-days (current: {current_qqq})"""
                self.dday_stats_label.setText(dday_text)
                
                # Regime changes
                changes = []
                for i in range(1, len(alerts)):
                    if alerts[i].regime != alerts[i-1].regime:
                        changes.append({
                            'date': alerts[i].date,
                            'from': alerts[i-1].regime,
                            'to': alerts[i].regime
                        })
                
                if changes:
                    emoji = {'BULLISH': '🟢', 'NEUTRAL': '🟡', 'BEARISH': '🔴'}
                    changes_lines = [f"Total regime changes: {len(changes)}", ""]
                    for c in changes[-7:]:  # Last 7 changes
                        from_val = c['from'].value if hasattr(c['from'], 'value') else str(c['from'])
                        to_val = c['to'].value if hasattr(c['to'], 'value') else str(c['to'])
                        changes_lines.append(
                            f"{c['date']}: {emoji.get(from_val, '')} {from_val} → "
                            f"{emoji.get(to_val, '')} {to_val}"
                        )
                    self.regime_changes_label.setText("\n".join(changes_lines))
                else:
                    self.regime_changes_label.setText("No regime changes in this period")
                
                # Score chart (ASCII)
                scores = [a.composite_score for a in alerts[-20:]]
                if scores:
                    chart = self._build_ascii_chart(scores)
                    self.score_chart_label.setText(chart)
                else:
                    self.score_chart_label.setText("Not enough data")
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error loading trend analysis: {e}")
            self.regime_dist_label.setText(f"Error: {e}")
    
    def _build_ascii_chart(self, scores: List[float]) -> str:
        """Build ASCII chart of scores."""
        if not scores:
            return "No data"
        
        min_score = min(scores)
        max_score = max(scores)
        score_range = max_score - min_score if max_score != min_score else 1
        
        lines = []
        lines.append("-" * (len(scores) + 4))
        
        for row in range(4, -1, -1):  # 5 rows
            threshold = min_score + (row / 4) * score_range
            line = ""
            for score in scores:
                if score >= threshold:
                    line += "█"
                else:
                    line += "░"
            
            # Add scale label
            if row == 4:
                line += f"  {max_score:+.2f}"
            elif row == 0:
                line += f"  {min_score:+.2f}"
            
            lines.append(line)
        
        lines.append("-" * (len(scores) + 4))
        lines.append("└" + "─" * (len(scores)//2 - 2) + "┴" + "─" * (len(scores)//2 - 2) + "┘")
        lines.append(" " * 3 + "Older" + " " * (len(scores) - 12) + "Recent")
        
        return "\n".join(lines)
    
    def _export_trend_csv(self):
        """Export trend data to CSV."""
        if not self.db_session_factory:
            return
        
        # Get file path
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Trend Data",
            f"regime_trend_{date.today().isoformat()}.csv",
            "CSV Files (*.csv)"
        )
        
        if not file_path:
            return
        
        try:
            # Get days from combo
            days_text = self.trend_days_combo.currentText()
            if days_text == "All":
                days = 9999
            else:
                days = int(days_text.split()[0])
            
            session = self.db_session_factory()
            try:
                from canslim_monitor.regime.models_regime import MarketRegimeAlert
                import csv
                
                alerts = session.query(MarketRegimeAlert).order_by(
                    MarketRegimeAlert.date.asc()
                ).limit(days).all()
                
                with open(file_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'date', 'regime', 'composite_score',
                        'spy_d_count', 'qqq_d_count', 'd_day_trend',
                        'es_change_pct', 'nq_change_pct', 'ym_change_pct',
                        'market_phase', 'rally_day', 'has_confirmed_ftd'
                    ])
                    
                    for alert in alerts:
                        regime_val = alert.regime.value if hasattr(alert.regime, 'value') else str(alert.regime)
                        trend_val = alert.d_day_trend.value if alert.d_day_trend and hasattr(alert.d_day_trend, 'value') else ''
                        
                        writer.writerow([
                            alert.date.isoformat() if hasattr(alert.date, 'isoformat') else str(alert.date),
                            regime_val,
                            alert.composite_score,
                            alert.spy_d_count,
                            alert.qqq_d_count,
                            trend_val,
                            alert.es_change_pct or '',
                            alert.nq_change_pct or '',
                            alert.ym_change_pct or '',
                            alert.market_phase or '',
                            alert.rally_day or '',
                            alert.has_confirmed_ftd or ''
                        ])
                
                QMessageBox.information(
                    self, "Export Complete",
                    f"Exported {len(alerts)} records to:\n{file_path}"
                )
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")
    
    # =========================================================================
    # Reset Tab Methods
    # =========================================================================
    
    def _select_all_reset(self):
        """Select all reset options."""
        self.reset_alerts_check.setChecked(True)
        self.reset_dd_check.setChecked(True)
        self.reset_counts_check.setChecked(True)
        self.reset_futures_check.setChecked(True)
        self.reset_ftd_check.setChecked(True)
        self.reset_ibd_check.setChecked(True)
    
    def _select_none_reset(self):
        """Deselect all reset options."""
        self.reset_alerts_check.setChecked(False)
        self.reset_dd_check.setChecked(False)
        self.reset_counts_check.setChecked(False)
        self.reset_futures_check.setChecked(False)
        self.reset_ftd_check.setChecked(False)
        self.reset_ibd_check.setChecked(False)
    
    def _do_reset(self):
        """Perform the reset."""
        # Check if anything selected
        if not any([
            self.reset_alerts_check.isChecked(),
            self.reset_dd_check.isChecked(),
            self.reset_counts_check.isChecked(),
            self.reset_futures_check.isChecked(),
            self.reset_ftd_check.isChecked(),
            self.reset_ibd_check.isChecked()
        ]):
            QMessageBox.information(self, "Nothing Selected", "Please select data to reset.")
            return
        
        # Confirm
        items = []
        if self.reset_alerts_check.isChecked():
            items.append("Regime Alerts")
        if self.reset_dd_check.isChecked():
            items.append("Distribution Days")
        if self.reset_counts_check.isChecked():
            items.append("Daily Counts History")
        if self.reset_futures_check.isChecked():
            items.append("Overnight Trends")
        if self.reset_ftd_check.isChecked():
            items.append("FTD Tracking Data")
        if self.reset_ibd_check.isChecked():
            items.append("IBD Exposure History")
        
        reply = QMessageBox.warning(
            self, "Confirm Reset",
            f"This will permanently delete:\n\n• " + "\n• ".join(items) + "\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Do reset
        try:
            session = self.db_session_factory()
            try:
                from canslim_monitor.regime.models_regime import (
                    DistributionDay, DistributionDayCount, MarketRegimeAlert,
                    OvernightTrend, IBDExposureHistory
                )
                
                deleted = []
                
                if self.reset_alerts_check.isChecked():
                    count = session.query(MarketRegimeAlert).delete()
                    deleted.append(f"Regime Alerts: {count}")
                
                if self.reset_dd_check.isChecked():
                    count = session.query(DistributionDay).delete()
                    deleted.append(f"Distribution Days: {count}")
                
                if self.reset_counts_check.isChecked():
                    count = session.query(DistributionDayCount).delete()
                    deleted.append(f"Daily Counts: {count}")
                
                if self.reset_futures_check.isChecked():
                    try:
                        count = session.query(OvernightTrend).delete()
                        deleted.append(f"Overnight Trends: {count}")
                    except:
                        deleted.append("Overnight Trends: table not found")
                
                if self.reset_ftd_check.isChecked():
                    try:
                        from canslim_monitor.regime.ftd_tracker import (
                            FollowThroughDay, RallyAttempt, MarketStatus
                        )
                        count1 = session.query(FollowThroughDay).delete()
                        count2 = session.query(RallyAttempt).delete()
                        count3 = session.query(MarketStatus).delete()
                        deleted.append(f"FTD Data: {count1 + count2 + count3}")
                    except Exception as e:
                        deleted.append(f"FTD Data: {e}")
                
                if self.reset_ibd_check.isChecked():
                    try:
                        count = session.query(IBDExposureHistory).delete()
                        deleted.append(f"IBD History: {count}")
                    except:
                        deleted.append("IBD History: table not found")
                
                session.commit()
                
                QMessageBox.information(
                    self, "Reset Complete",
                    "Deleted:\n• " + "\n• ".join(deleted)
                )
                
                # Refresh
                self._load_current_status()
                self._load_trend_analysis()
                self.data_updated.emit()
                
            finally:
                session.close()
                
        except Exception as e:
            logger.exception("Error during reset")
            QMessageBox.critical(self, "Reset Error", f"Failed to reset:\n{e}")
    
    def closeEvent(self, event):
        """Handle dialog close - stop any running workers."""
        if self.seed_worker and self.seed_worker.isRunning():
            self.seed_worker.stop()
            self.seed_worker.wait(5000)  # Wait up to 5 seconds
        super().closeEvent(event)
