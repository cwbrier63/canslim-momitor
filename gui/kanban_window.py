"""
CANSLIM Monitor - Main Kanban Window
Primary GUI for position management with drag-and-drop state transitions.

FIXED: Added proper file-based logging and config loading in launch_gui()
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QStatusBar, QMessageBox, QSplitter,
    QToolBar, QMenu, QMenuBar, QDialog, QApplication, QTextEdit,
    QProgressBar, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QFont, QAction, QColor

from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.data.repositories import RepositoryManager
from canslim_monitor.gui.state_config import STATES, get_kanban_columns, get_transition
from canslim_monitor.gui.kanban_column import KanbanColumn, ClosedPositionsPanel
from canslim_monitor.gui.position_card import PositionCard
from canslim_monitor.gui.transition_dialogs import TransitionDialog, AddPositionDialog, EditPositionDialog
from canslim_monitor.gui.service_status_bar import ServiceStatusBar
from canslim_monitor.gui.ibd_exposure_dialog import IBDExposureDialog
from canslim_monitor.gui.position_table_view import PositionTableView


class PriceUpdateWorker(QObject):
    """
    Worker that fetches prices from IBKR in a background thread.
    """
    finished = pyqtSignal(dict)  # Emits {symbol: price_data}
    error = pyqtSignal(str)
    
    def __init__(self, ibkr_client, symbols: List[str]):
        super().__init__()
        self.ibkr_client = ibkr_client
        self.symbols = symbols
    
    def run(self):
        """Fetch prices from IBKR."""
        try:
            if self.ibkr_client and self.symbols:
                prices = self.ibkr_client.get_quotes(self.symbols)
                self.finished.emit(prices)
            else:
                self.finished.emit({})
        except Exception as e:
            self.error.emit(str(e))


class MarketRegimeBanner(QFrame):
    """
    Top banner showing current market regime and index status.
    Double-click on RECOMMENDED EXPOSURE to edit IBD levels.
    """
    
    # Signal emitted when user double-clicks exposure to edit IBD levels
    ibd_edit_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the banner UI."""
        self.setFixedHeight(75)
        self.setStyleSheet("""
            MarketRegimeBanner {
                background-color: #1E3A5F;
                border-radius: 4px;
            }
            QLabel {
                color: white;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)
        
        # Market Regime Section
        regime_section = QVBoxLayout()
        regime_section.setSpacing(2)
        
        regime_title = QLabel("MARKET REGIME")
        regime_title.setStyleSheet("font-size: 10px; color: #AAA;")
        regime_section.addWidget(regime_title)
        
        self.regime_label = QLabel("BULLISH")
        regime_font = QFont()
        regime_font.setBold(True)
        regime_font.setPointSize(16)
        self.regime_label.setFont(regime_font)
        self.regime_label.setStyleSheet("color: #28A745;")
        regime_section.addWidget(self.regime_label)
        
        layout.addLayout(regime_section)
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # Distribution Days Section
        dd_section = QVBoxLayout()
        dd_section.setSpacing(2)
        
        dd_title = QLabel("DISTRIBUTION DAYS")
        dd_title.setStyleSheet("font-size: 10px; color: #AAA;")
        dd_section.addWidget(dd_title)
        
        dd_layout = QHBoxLayout()
        dd_layout.setSpacing(12)
        
        self.spy_dd_label = QLabel("SPY: 2")
        dd_layout.addWidget(self.spy_dd_label)
        
        self.qqq_dd_label = QLabel("QQQ: 3")
        dd_layout.addWidget(self.qqq_dd_label)
        
        dd_section.addLayout(dd_layout)
        layout.addLayout(dd_section)
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # SPY Index Box
        self.spy_box = self._create_index_box("SPY")
        layout.addWidget(self.spy_box)
        
        # QQQ Index Box
        self.qqq_box = self._create_index_box("QQQ")
        layout.addWidget(self.qqq_box)
        
        # DIA Index Box
        self.dia_box = self._create_index_box("DIA")
        layout.addWidget(self.dia_box)
        
        # IWM Index Box (Russell 2000)
        self.iwm_box = self._create_index_box("IWM")
        layout.addWidget(self.iwm_box)
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # Futures Section (ES, NQ, YM)
        futures_section = QVBoxLayout()
        futures_section.setSpacing(2)
        
        futures_title = QLabel("FUTURES")
        futures_title.setStyleSheet("font-size: 10px; color: #AAA;")
        futures_section.addWidget(futures_title)
        
        futures_layout = QVBoxLayout()
        futures_layout.setSpacing(0)
        
        self.es_label = QLabel("ES: --")
        self.es_label.setStyleSheet("font-size: 11px;")
        futures_layout.addWidget(self.es_label)
        
        self.nq_label = QLabel("NQ: --")
        self.nq_label.setStyleSheet("font-size: 11px;")
        futures_layout.addWidget(self.nq_label)
        
        self.ym_label = QLabel("YM: --")
        self.ym_label.setStyleSheet("font-size: 11px;")
        futures_layout.addWidget(self.ym_label)
        
        futures_section.addLayout(futures_layout)
        layout.addLayout(futures_section)
        
        layout.addStretch()
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # Exposure Recommendation
        exposure_section = QVBoxLayout()
        exposure_section.setSpacing(2)
        
        exposure_title = QLabel("RECOMMENDED EXPOSURE")
        exposure_title.setStyleSheet("font-size: 10px; color: #AAA;")
        exposure_section.addWidget(exposure_title)
        
        self.exposure_label = QLabel("40-60%")
        exposure_font = QFont()
        exposure_font.setBold(True)
        exposure_font.setPointSize(14)
        self.exposure_label.setFont(exposure_font)
        self.exposure_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exposure_label.setToolTip("Double-click to edit IBD exposure levels from MarketSurge")
        self.exposure_label.mouseDoubleClickEvent = self._on_exposure_double_click
        exposure_section.addWidget(self.exposure_label)
        
        layout.addLayout(exposure_section)
    
    def _on_exposure_double_click(self, event):
        """Handle double-click on exposure label to open IBD editor."""
        self.ibd_edit_requested.emit()
    
    def update_futures(self, es_pct: float = None, nq_pct: float = None, ym_pct: float = None):
        """Update futures display with overnight change percentages."""
        def format_futures(pct, label):
            if pct is None:
                return f"{label}: --"
            color = "#28A745" if pct >= 0 else "#DC3545"  # Green/Red
            return f"<span style='color:{color}'>{label}: {pct:+.2f}%</span>"
        
        self.es_label.setText(format_futures(es_pct, "ES"))
        self.es_label.setTextFormat(Qt.TextFormat.RichText)
        
        self.nq_label.setText(format_futures(nq_pct, "NQ"))
        self.nq_label.setTextFormat(Qt.TextFormat.RichText)
        
        self.ym_label.setText(format_futures(ym_pct, "YM"))
        self.ym_label.setTextFormat(Qt.TextFormat.RichText)
    
    def _create_separator(self) -> QFrame:
        """Create a vertical separator line."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #444;")
        return sep
    
    def _create_index_box(self, symbol: str) -> QFrame:
        """Create a box widget for an index showing price, day/week %, and SMA distances."""
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background-color: #2A4A6F;
                border-radius: 4px;
            }
        """)
        box.setMinimumWidth(145)
        box.setMaximumWidth(180)
        
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(6, 4, 6, 4)
        box_layout.setSpacing(1)
        
        # Top row: Symbol + Price
        top_row = QLabel(f"<b>{symbol}</b> $---")
        top_row.setTextFormat(Qt.TextFormat.RichText)
        top_row.setStyleSheet("font-size: 11px;")
        box_layout.addWidget(top_row)
        
        # Middle row: Day % | Week %
        change_row = QLabel("<span style='color:#888'>D:</span>-- <span style='color:#888'>W:</span>--")
        change_row.setTextFormat(Qt.TextFormat.RichText)
        change_row.setStyleSheet("font-size: 10px;")
        box_layout.addWidget(change_row)
        
        # Bottom row: SMA percentages (21/50/200) - compact format
        sma_row = QLabel("<span style='color:#888'>21:</span>-- <span style='color:#888'>50:</span>-- <span style='color:#888'>200:</span>--")
        sma_row.setTextFormat(Qt.TextFormat.RichText)
        sma_row.setStyleSheet("font-size: 10px;")
        box_layout.addWidget(sma_row)
        
        # Store references to labels for updates
        box.top_label = top_row
        box.change_label = change_row
        box.sma_label = sma_row
        box.symbol = symbol
        
        return box
    
    def update_regime(
        self,
        regime: str = None,
        spy_dd: int = None,
        qqq_dd: int = None,
        exposure: str = None
    ):
        """Update regime display."""
        if regime:
            self.regime_label.setText(regime.upper())
            colors = {
                'BULLISH': '#28A745',
                'NEUTRAL': '#FFC107',
                'CAUTIOUS': '#FFC107',
                'BEARISH': '#DC3545',
                'CORRECTION': '#DC3545',
                'BEAR': '#DC3545',
            }
            self.regime_label.setStyleSheet(f"color: {colors.get(regime.upper(), 'white')};")
        
        if spy_dd is not None:
            self.spy_dd_label.setText(f"SPY: {spy_dd}")
        
        if qqq_dd is not None:
            self.qqq_dd_label.setText(f"QQQ: {qqq_dd}")
        
        if exposure:
            self.exposure_label.setText(exposure)
    
    def update_indices(self, spy: float = None, qqq: float = None, dia: float = None, iwm: float = None):
        """Update index prices only (for backward compatibility)."""
        if spy:
            self.spy_box.top_label.setText(f"<b>SPY</b> ${spy:.2f}")
        if qqq:
            self.qqq_box.top_label.setText(f"<b>QQQ</b> ${qqq:.2f}")
        if dia:
            self.dia_box.top_label.setText(f"<b>DIA</b> ${dia:.2f}")
        if iwm:
            self.iwm_box.top_label.setText(f"<b>IWM</b> ${iwm:.2f}")
    
    def update_index_box(self, symbol: str, price: float = None, day_pct: float = None, 
                         week_pct: float = None, sma21: float = None, sma50: float = None, 
                         sma200: float = None):
        """
        Update a single index box with all data.
        
        Args:
            symbol: 'SPY', 'QQQ', 'DIA', or 'IWM'
            price: Current price
            day_pct: Day change percentage
            week_pct: Week change percentage
            sma21: % distance from 21-day SMA
            sma50: % distance from 50-day SMA
            sma200: % distance from 200-day SMA
        """
        # Get the right box
        box = getattr(self, f"{symbol.lower()}_box", None)
        if not box:
            return
        
        # Helper for color coding (compact format without %)
        def color_pct(val, show_pct=True):
            if val is None:
                return "#888", "--"
            color = '#28A745' if val >= 0 else '#DC3545'
            if show_pct:
                return color, f"{val:+.1f}%"
            else:
                return color, f"{val:+.1f}"
        
        # Update top row (symbol + price)
        price_str = f"${price:.2f}" if price is not None else "$---"
        box.top_label.setText(f"<b>{symbol}</b> {price_str}")
        
        # Update change row (day/week %)
        d_color, d_text = color_pct(day_pct)
        w_color, w_text = color_pct(week_pct)
        box.change_label.setText(
            f"<span style='color:#888'>D:</span><span style='color:{d_color}'>{d_text}</span> "
            f"<span style='color:#888'>W:</span><span style='color:{w_color}'>{w_text}</span>"
        )
        
        # Update SMA row (compact - no % symbol)
        s21_color, s21_text = color_pct(sma21, show_pct=False)
        s50_color, s50_text = color_pct(sma50, show_pct=False)
        s200_color, s200_text = color_pct(sma200, show_pct=False)
        box.sma_label.setText(
            f"<span style='color:#888'>21:</span><span style='color:{s21_color}'>{s21_text}</span> "
            f"<span style='color:#888'>50:</span><span style='color:{s50_color}'>{s50_text}</span> "
            f"<span style='color:#888'>200:</span><span style='color:{s200_color}'>{s200_text}</span>"
        )
    
    def update_sma(self, spy_sma: dict = None, qqq_sma: dict = None):
        """
        Update SMA distance display (backward compatible).
        
        Args:
            spy_sma: Dict with keys 'sma21', 'sma50', 'sma200' containing % distances
            qqq_sma: Dict with keys 'sma21', 'sma50', 'sma200' containing % distances
        """
        if spy_sma:
            self.update_index_box('SPY', 
                                  sma21=spy_sma.get('sma21'),
                                  sma50=spy_sma.get('sma50'),
                                  sma200=spy_sma.get('sma200'))
        
        if qqq_sma:
            self.update_index_box('QQQ',
                                  sma21=qqq_sma.get('sma21'),
                                  sma50=qqq_sma.get('sma50'),
                                  sma200=qqq_sma.get('sma200'))


class MarketRegimeDialog(QDialog):
    """
    Dialog showing market regime analysis progress and results.
    Displays information similar to the Discord alert format.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Market Regime Analysis")
        self.setMinimumSize(500, 600)
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Progress section
        self.progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(self.progress_group)
        
        self.status_label = QLabel("Initializing...")
        self.status_label.setStyleSheet("font-weight: bold;")
        progress_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addWidget(self.progress_group)
        
        # Results section (hidden until complete)
        self.results_group = QGroupBox("📊 Market Regime Results")
        self.results_group.setVisible(False)
        results_layout = QVBoxLayout(self.results_group)
        
        # Results text area with monospace font for alignment
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setStyleSheet("""
            QTextEdit {
                background-color: #2C2F33;
                color: #FFFFFF;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        self.results_text.setMinimumHeight(400)
        results_layout.addWidget(self.results_text)
        
        layout.addWidget(self.results_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setEnabled(False)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def set_progress(self, value: int, status: str):
        """Update progress bar and status."""
        self.progress_bar.setValue(value)
        self.status_label.setText(status)
        QApplication.processEvents()
    
    def show_results(self, results: dict):
        """Display the analysis results in Discord-like format."""
        self.progress_group.setVisible(False)
        self.results_group.setVisible(True)
        self.close_btn.setEnabled(True)
        
        # Build formatted output similar to Discord message
        lines = []
        
        # Header
        lines.append("═" * 50)
        lines.append("🏛️ MORNING MARKET REGIME ALERT")
        lines.append(f"   {results.get('date', 'Today')}")
        lines.append("═" * 50)
        lines.append("")
        
        # Distribution Day Count
        lines.append("📊 DISTRIBUTION DAY COUNT (Rolling 25-Day)")
        lines.append("─" * 50)
        lines.append(f"{'Index':<8} {'Count':^8} {'5-Day Î”':^10} {'Trend':^12}")
        lines.append("─" * 50)
        
        spy_trend = results.get('trend', 'STABLE')
        qqq_trend = results.get('trend', 'STABLE')
        trend_emoji = "🔴" if spy_trend == "WORSENING" else "🟢" if spy_trend == "IMPROVING" else "🟡"
        
        lines.append(f"{'SPY':<8} {results.get('spy_count', 0):^8} {results.get('spy_delta', 0):^+10d} {trend_emoji} {spy_trend:^10}")
        lines.append(f"{'QQQ':<8} {results.get('qqq_count', 0):^8} {results.get('qqq_delta', 0):^+10d} {trend_emoji} {qqq_trend:^10}")
        lines.append("")
        
        # D-Day Histogram
        if results.get('spy_dates') or results.get('qqq_dates'):
            lines.append("📅 D-DAY HISTOGRAM (25-Day Rolling Window)")
            lines.append("─" * 50)
            lines.append(f"         ← 25 days ago              Today →")
            
            spy_histogram = self._build_histogram(results.get('spy_dates', []), results.get('lookback_start'))
            qqq_histogram = self._build_histogram(results.get('qqq_dates', []), results.get('lookback_start'))
            
            lines.append(f"SPY [{results.get('spy_count', 0)}]: {spy_histogram}")
            lines.append(f"QQQ [{results.get('qqq_count', 0)}]: {qqq_histogram}")
            lines.append("")
        
        # Market Phase
        lines.append("🔄 MARKET PHASE")
        lines.append("─" * 50)
        phase = results.get('market_phase', 'UNKNOWN')
        phase_emoji = "🟢" if "UPTREND" in phase else "🔴" if "CORRECTION" in phase else "🟡"
        lines.append(f"   {phase_emoji} {phase}")
        
        if results.get('in_rally_attempt'):
            lines.append(f"   Rally Day: {results.get('rally_day', 0)}")
        if results.get('has_confirmed_ftd'):
            lines.append(f"   ✅ FTD Confirmed")
        lines.append("")
        
        # Index Performance Section
        spy_stats = results.get('spy_stats', {})
        qqq_stats = results.get('qqq_stats', {})
        dia_stats = results.get('dia_stats', {})
        iwm_stats = results.get('iwm_stats', {})
        if spy_stats or qqq_stats:
            lines.append("📈 INDEX PERFORMANCE")
            lines.append("─" * 60)
            lines.append(f"{'Index':<6} {'Price':^10} {'Day':^8} {'Week':^8} {'21-SMA':^8} {'50-SMA':^8} {'200-SMA':^8}")
            lines.append("─" * 60)
            
            for symbol, stats in [('SPY', spy_stats), ('QQQ', qqq_stats), ('DIA', dia_stats), ('IWM', iwm_stats)]:
                if stats:
                    price = stats.get('price', 0)
                    day = stats.get('day_pct', 0)
                    week = stats.get('week_pct', 0)
                    s21 = stats.get('sma21', 0)
                    s50 = stats.get('sma50', 0)
                    s200 = stats.get('sma200', 0)
                    lines.append(f"{symbol:<6} ${price:>8.2f} {day:>+7.1f}% {week:>+7.1f}% {s21:>+7.1f}% {s50:>+7.1f}% {s200:>+7.1f}%")
            lines.append("")
        
        # Composite Score
        lines.append("🏆 COMPOSITE MARKET REGIME SCORE")
        lines.append("─" * 50)
        score = results.get('composite_score', 0)
        regime = results.get('regime', 'NEUTRAL')
        
        # Score bar visualization
        score_normalized = (score + 1.5) / 3.0  # Normalize -1.5 to +1.5 → 0 to 1
        score_normalized = max(0, min(1, score_normalized))
        bar_width = 40
        filled = int(score_normalized * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        
        regime_emoji = "🟢" if regime == "BULLISH" else "🔴" if regime == "BEARISH" else "🟡"
        
        lines.append(f"   Score: {score:+.2f} / 1.50")
        lines.append(f"   [{bar}]")
        lines.append(f"   {regime_emoji} {regime}")
        lines.append("")
        
        # Exposure Recommendation
        lines.append("💰 EXPOSURE RECOMMENDATION")
        lines.append("─" * 50)
        exposure = results.get('exposure', '40-60%')
        lines.append(f"   Suggested: {exposure}")
        lines.append("")
        
        # Guidance
        lines.append("📋 GUIDANCE")
        lines.append("─" * 50)
        if regime == "BEARISH":
            lines.append("   → Defensive posture - raise cash")
            lines.append("   → Avoid new long positions")
            lines.append("   → Wait for follow-through day signal")
        elif regime == "NEUTRAL":
            lines.append("   → Cautious positioning")
            lines.append("   → Reduce position sizes")
            lines.append("   → Focus on strongest setups only")
        else:  # BULLISH
            lines.append("   → Favorable for new positions")
            lines.append("   → Look for breakouts from sound bases")
            lines.append("   → Let winners run")
        
        lines.append("")
        lines.append("═" * 50)
        
        self.results_text.setText("\n".join(lines))
    
    def _build_histogram(self, dates: list, lookback_start=None) -> str:
        """Build a simple text histogram of distribution days."""
        from datetime import date, timedelta
        
        if not dates:
            return "·" * 25
        
        today = date.today()
        if lookback_start is None:
            lookback_start = today - timedelta(days=25)
        
        # Convert string dates to date objects if needed
        date_set = set()
        for d in dates:
            if isinstance(d, str):
                date_set.add(date.fromisoformat(d))
            else:
                date_set.add(d)
        
        # Build histogram (25 characters for 25 days)
        histogram = ""
        current = lookback_start
        while current <= today:
            if current in date_set:
                histogram += "█"
            else:
                histogram += "·"
            current += timedelta(days=1)
        
        return histogram[-25:] if len(histogram) > 25 else histogram.ljust(25, '·')
    
    def show_error(self, error_msg: str):
        """Show an error message."""
        self.progress_group.setVisible(False)
        self.results_group.setVisible(True)
        self.results_group.setTitle("❌ Error")
        self.results_text.setText(f"Analysis failed:\n\n{error_msg}")
        self.close_btn.setEnabled(True)


class ServiceControlPanel(QFrame):
    """
    Panel for controlling the CANSLIM monitor service.
    """
    
    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the panel UI."""
        self.setStyleSheet("""
            ServiceControlPanel {
                background-color: #F8F9FA;
                border: 1px solid #DEE2E6;
                border-radius: 4px;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        
        # Status indicator
        self.status_dot = QLabel("◉")
        self.status_dot.setStyleSheet("color: #DC3545; font-size: 16px;")
        layout.addWidget(self.status_dot)
        
        self.status_label = QLabel("Service: Stopped")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # Thread status
        self.thread_label = QLabel("Threads: --")
        self.thread_label.setStyleSheet("color: #666;")
        layout.addWidget(self.thread_label)
        
        layout.addSpacing(20)
        
        # Control buttons
        self.start_btn = QPushButton("▶ Start")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        self.start_btn.clicked.connect(self.start_clicked.emit)
        layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #C82333;
            }
        """)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)
    
    def set_running(self, running: bool, thread_status: str = None):
        """Update display for running state."""
        if running:
            self.status_dot.setStyleSheet("color: #28A745; font-size: 16px;")
            self.status_label.setText("Service: Running")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status_dot.setStyleSheet("color: #DC3545; font-size: 16px;")
            self.status_label.setText("Service: Stopped")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        
        if thread_status:
            self.thread_label.setText(f"Threads: {thread_status}")


class KanbanMainWindow(QMainWindow):
    """
    Main window for CANSLIM Position Manager.
    """
    
    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        
        self.db = db
        
        # Use LoggingManager's logger for proper file logging
        try:
            from canslim_monitor.utils.logging import get_logger
            self.logger = get_logger('gui')
        except Exception:
            # Fallback to basic logger
            self.logger = logging.getLogger('canslim.gui')
        
        # Load configuration
        try:
            from canslim_monitor.utils.config import load_config
            self.config = load_config()
        except Exception as e:
            self.logger.warning(f"Could not load config: {e}")
            self.config = {}
        
        # Columns by state
        self.columns: Dict[int, KanbanColumn] = {}
        self.closed_panel: Optional[ClosedPositionsPanel] = None
        
        # IBKR client (lazy initialized)
        self.ibkr_client = None
        self.ibkr_connected = False
        
        # Price update worker thread
        self.price_worker = None
        self.price_thread = None
        self.price_update_in_progress = False
        
        # Child windows
        self._table_view = None  # Position database spreadsheet view
        
        # Price update timer (5 second interval)
        self.price_timer = QTimer()
        self.price_timer.timeout.connect(self._update_prices)
        self.price_update_interval = 5000  # 5 seconds

        # Google Sheets auto-sync timer
        self.auto_sync_timer = QTimer()
        self.auto_sync_timer.timeout.connect(self._auto_sync_check)
        sheets_config = self.config.get('google_sheets', {})
        auto_sync_enabled = sheets_config.get('auto_sync', False)
        sync_interval = sheets_config.get('sync_interval', 300)  # Default 5 minutes
        if auto_sync_enabled:
            self.auto_sync_timer.start(sync_interval * 1000)  # Convert to milliseconds
            self.logger.info(f"Auto-sync enabled: checking every {sync_interval} seconds")

        # Cached index stats for persistence between price updates
        self._cached_spy_stats = {}
        self._cached_qqq_stats = {}
        self._cached_dia_stats = {}
        self._cached_iwm_stats = {}
        
        self._setup_ui()
        self._setup_menu()
        self._load_positions()
        self._load_market_regime()  # Load regime data from database
    
    def _setup_ui(self):
        """Set up the main window UI."""
        self.setWindowTitle("CANSLIM Position Manager")
        self.setMinimumSize(1400, 800)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)
        
        # Market regime banner
        self.regime_banner = MarketRegimeBanner()
        self.regime_banner.ibd_edit_requested.connect(self._open_ibd_editor)
        main_layout.addWidget(self.regime_banner)
        
        # Kanban board
        board_layout = QHBoxLayout()
        board_layout.setSpacing(12)
        
        # Create columns for each state
        for state, title, color in get_kanban_columns():
            column = KanbanColumn(state, title, color)
            column.position_dropped.connect(self._on_position_dropped)
            column.card_clicked.connect(self._on_card_clicked)
            column.card_double_clicked.connect(self._on_card_double_clicked)
            column.card_context_menu.connect(self._on_card_context_menu)
            column.card_alert_clicked.connect(self._on_alert_clicked)
            column.add_clicked.connect(self._on_add_clicked)
            
            self.columns[state] = column
            board_layout.addWidget(column)
        
        main_layout.addLayout(board_layout, stretch=1)
        
        # Closed positions panel
        self.closed_panel = ClosedPositionsPanel()
        self.closed_panel.card_clicked.connect(self._on_card_clicked)
        self.closed_panel.card_double_clicked.connect(self._on_card_double_clicked)
        self.closed_panel.card_context_menu.connect(self._on_card_context_menu)
        self.closed_panel.card_alert_clicked.connect(self._on_alert_clicked)
        main_layout.addWidget(self.closed_panel)
        
        # Service control panel (for GUI IBKR connection)
        self.service_panel = ServiceControlPanel()
        self.service_panel.start_clicked.connect(self._on_start_service)
        self.service_panel.stop_clicked.connect(self._on_stop_service)
        main_layout.addWidget(self.service_panel)
        
        # Windows Service Status Bar (for background service threads)
        self.service_status_bar = ServiceStatusBar(parent=self)
        self.service_status_bar.service_state_changed.connect(self._on_windows_service_state_changed)
        main_layout.addWidget(self.service_status_bar)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def _setup_menu(self):
        """Set up the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        import_action = QAction("&Import from Excel...", self)
        import_action.triggered.connect(self._on_import)
        file_menu.addAction(import_action)
        
        export_action = QAction("&Export to Excel...", self)
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()

        sync_action = QAction("&Sync to Google Sheets", self)
        sync_action.triggered.connect(self._on_sync_sheets)
        file_menu.addAction(sync_action)

        sync_all_action = QAction("Sync &All (Force)", self)
        sync_all_action.triggered.connect(lambda: self._on_sync_sheets(force=True))
        file_menu.addAction(sync_all_action)

        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Position menu
        position_menu = menubar.addMenu("&Position")
        
        add_action = QAction("&Add to Watchlist...", self)
        add_action.setShortcut("Ctrl+N")
        add_action.triggered.connect(lambda: self._on_add_clicked(0))
        position_menu.addAction(add_action)
        
        refresh_action = QAction("&Refresh Prices", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._update_prices)
        position_menu.addAction(refresh_action)
        
        position_menu.addSeparator()
        
        recalc_action = QAction("Recalculate All &Scores", self)
        recalc_action.triggered.connect(self._recalculate_all_scores)
        position_menu.addAction(recalc_action)
        
        ack_alerts_action = QAction("✔ Acknowledge All &Alerts", self)
        ack_alerts_action.setShortcut("Ctrl+Shift+A")
        ack_alerts_action.triggered.connect(self._on_acknowledge_all_alerts)
        position_menu.addAction(ack_alerts_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        db_view_action = QAction("📊 &Database View", self)
        db_view_action.setShortcut("Ctrl+D")
        db_view_action.setToolTip("View all positions in spreadsheet format")
        db_view_action.triggered.connect(self._open_table_view)
        view_menu.addAction(db_view_action)
        
        view_menu.addSeparator()
        
        alert_monitor_action = QAction("🔔 &Alert Monitor", self)
        alert_monitor_action.setShortcut("Ctrl+Shift+M")
        alert_monitor_action.triggered.connect(self._on_open_alert_monitor)
        view_menu.addAction(alert_monitor_action)
        
        view_menu.addSeparator()
        
        refresh_view_action = QAction("&Refresh All", self)
        refresh_view_action.setShortcut("Ctrl+R")
        refresh_view_action.triggered.connect(self._load_positions)
        view_menu.addAction(refresh_view_action)
        
        # Service menu
        service_menu = menubar.addMenu("&Service")
        
        start_action = QAction("&Start Service", self)
        start_action.triggered.connect(self._on_start_service)
        service_menu.addAction(start_action)
        
        stop_action = QAction("S&top Service", self)
        stop_action.triggered.connect(self._on_stop_service)
        service_menu.addAction(stop_action)
        
        service_menu.addSeparator()
        
        regime_action = QAction("&Run Market Regime Analysis", self)
        regime_action.triggered.connect(self._on_run_market_regime)
        service_menu.addAction(regime_action)

        # Reports menu
        reports_menu = menubar.addMenu("&Reports")

        weekly_report_action = QAction("📝 &Weekly Watchlist Report...", self)
        weekly_report_action.triggered.connect(self._on_weekly_report)
        reports_menu.addAction(weekly_report_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _load_positions(self):
        """Load positions from database and populate columns."""
        session = self.db.get_new_session()
        
        try:
            repos = RepositoryManager(session)
            positions = repos.positions.get_all(include_closed=True)  # Include closed!
            
            # Debug: count by state
            state_counts = {}
            for pos in positions:
                state_counts[pos.state] = state_counts.get(pos.state, 0) + 1
            self.logger.info(f"Loaded positions by state: {state_counts}")
            
            # Fetch latest alerts for all positions in one query
            position_ids = [pos.id for pos in positions]
            latest_alerts = self._get_latest_alerts_for_positions(session, position_ids)
            self.logger.debug(f"Fetched alerts for {len(latest_alerts)} positions")
            
            # Clear existing cards
            for column in self.columns.values():
                column.clear_cards()
            self.closed_panel.clear_cards()
            
            # Add cards to appropriate columns
            closed_count = 0
            for pos in positions:
                # Get the latest alert for this position (if any)
                latest_alert = latest_alerts.get(pos.id)
                card = self._create_card(pos, latest_alert=latest_alert)
                
                if pos.state < 0:
                    # Closed/stopped positions
                    self.closed_panel.add_card(card)
                    closed_count += 1
                    self.logger.debug(f"Added closed position: {pos.symbol} (state {pos.state})")
                elif pos.state in self.columns:
                    self.columns[pos.state].add_card(card)
            
            self.logger.info(f"Added {closed_count} closed positions to panel")
            self.status_bar.showMessage(f"Loaded {len(positions)} positions ({closed_count} closed)")
            
        finally:
            session.close()
    
    def _get_latest_alerts_for_positions(self, session, position_ids: list) -> dict:
        """
        Get the most recent alert for each position in one efficient query.
        
        Args:
            session: Database session
            position_ids: List of position IDs
            
        Returns:
            Dict mapping position_id -> alert dict with severity
        """
        if not position_ids:
            return {}
        
        try:
            from sqlalchemy import func
            from canslim_monitor.data.models import Alert
            from canslim_monitor.services.alert_service import AlertService
            
            # Subquery to get max alert_time per position
            subq = (
                session.query(
                    Alert.position_id,
                    func.max(Alert.alert_time).label('max_time')
                )
                .filter(Alert.position_id.in_(position_ids))
                .group_by(Alert.position_id)
                .subquery()
            )
            
            # Join to get the full alert records
            alerts = (
                session.query(Alert)
                .join(
                    subq,
                    (Alert.position_id == subq.c.position_id) &
                    (Alert.alert_time == subq.c.max_time)
                )
                .all()
            )
            
            # Convert to dict with severity and acknowledgment status
            result = {}
            for alert in alerts:
                severity = AlertService.get_alert_severity(
                    alert.alert_type or '',
                    alert.alert_subtype or ''
                )
                # Handle backwards compatibility - acknowledged may not exist
                acknowledged = getattr(alert, 'acknowledged', None) or False
                acknowledged_at = getattr(alert, 'acknowledged_at', None)
                
                result[alert.position_id] = {
                    'id': alert.id,
                    'symbol': alert.symbol,
                    'position_id': alert.position_id,
                    'alert_type': alert.alert_type,
                    'subtype': alert.alert_subtype,
                    'alert_time': alert.alert_time.isoformat() if alert.alert_time else None,
                    'price': alert.price,
                    'severity': severity,
                    'acknowledged': acknowledged,
                    'acknowledged_at': acknowledged_at.isoformat() if acknowledged_at else None,
                }
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Failed to fetch latest alerts: {e}")
            return {}
    
    def _load_market_regime(self):
        """Load latest market regime data from database and update banner."""
        try:
            # Ensure regime tables exist
            self._ensure_regime_tables()
            
            session = self.db.get_new_session()
            try:
                # Import the model
                from canslim_monitor.regime.models_regime import MarketRegimeAlert
                
                # Get the most recent regime alert
                latest = session.query(MarketRegimeAlert).order_by(
                    MarketRegimeAlert.date.desc()
                ).first()
                
                if latest:
                    self.logger.info(
                        f"Loaded regime from DB: {latest.regime.value} "
                        f"(SPY:{latest.spy_d_count}, QQQ:{latest.qqq_d_count}) "
                        f"from {latest.date}"
                    )
                    
                    # Calculate exposure based on regime and d-day count
                    total_d = latest.spy_d_count + latest.qqq_d_count
                    exposure = self._get_exposure_from_regime(latest.regime.value, total_d)
                    
                    # Update banner
                    self.regime_banner.update_regime(
                        regime=latest.regime.value,
                        spy_dd=latest.spy_d_count,
                        qqq_dd=latest.qqq_d_count,
                        exposure=exposure
                    )
                    
                    # Update futures from latest alert
                    if hasattr(latest, 'es_change_pct') and latest.es_change_pct is not None:
                        self.regime_banner.update_futures(
                            es_pct=latest.es_change_pct,
                            nq_pct=latest.nq_change_pct,
                            ym_pct=latest.ym_change_pct
                        )
                        self.logger.info(
                            f"Loaded futures: ES:{latest.es_change_pct:+.2f}% "
                            f"NQ:{latest.nq_change_pct:+.2f}% YM:{latest.ym_change_pct:+.2f}%"
                        )
                else:
                    self.logger.info("No regime data in database yet")
                
                # Also load IBD exposure if available
                self._load_ibd_exposure(session)
                    
            finally:
                session.close()
                
        except Exception as e:
            self.logger.warning(f"Could not load market regime: {e}")
    
    def _load_ibd_exposure(self, session=None):
        """Load IBD exposure settings from database."""
        close_session = False
        try:
            if session is None:
                session = self.db.get_new_session()
                close_session = True
            
            # Try to import and query IBD exposure table
            try:
                from sqlalchemy import text
                result = session.execute(text(
                    "SELECT market_status, exposure_min, exposure_max FROM ibd_exposure_current WHERE id=1"
                )).fetchone()
                
                if result:
                    status, min_exp, max_exp = result
                    self.regime_banner.exposure_label.setText(f"{min_exp}-{max_exp}%")
                    self.logger.info(f"Loaded IBD exposure: {status} ({min_exp}-{max_exp}%)")
            except Exception as e:
                # Table may not exist yet
                self.logger.debug(f"IBD exposure table not available: {e}")
                
        finally:
            if close_session and session:
                session.close()
    
    def _ensure_regime_tables(self):
        """Ensure regime tables exist in the database."""
        try:
            from canslim_monitor.regime.models_regime import Base as RegimeBase
            from canslim_monitor.regime.ftd_tracker import RallyAttempt, FollowThroughDay, MarketStatus
            
            # Create tables if they don't exist
            RegimeBase.metadata.create_all(self.db.engine)
            self.logger.debug("Regime tables verified/created")
        except Exception as e:
            self.logger.warning(f"Could not create regime tables: {e}")
    
    def _get_exposure_from_regime(self, regime: str, total_d_days: int) -> str:
        """Calculate exposure recommendation based on D-day count (matches MarketRegimeCalculator)."""
        # This matches the logic in MarketRegimeCalculator.get_exposure_percentage()
        # Exposure is primarily driven by D-day count, not regime
        if total_d_days <= 4:
            return "80-100%"
        elif total_d_days <= 6:
            return "70-90%"
        elif total_d_days <= 8:
            return "60-80%"
        elif total_d_days <= 10:
            return "40-60%"
        elif total_d_days <= 12:
            return "20-40%"
        else:
            return "0-20%"
    
    def _calculate_sma_distances(self, bars: list) -> dict:
        """
        Calculate percentage distance from current price to 21, 50, and 200 day SMAs.
        
        Args:
            bars: List of DailyBar objects with .close attribute, ordered oldest to newest
            
        Returns:
            Dict with keys 'sma21', 'sma50', 'sma200' containing % distances
            Positive means price is above SMA, negative means below
        """
        if not bars or len(bars) < 21:
            return {'sma21': 0, 'sma50': 0, 'sma200': 0}
        
        # Get closing prices
        closes = [bar.close for bar in bars]
        current_price = closes[-1]
        
        result = {}
        
        # Calculate SMAs
        for period, key in [(21, 'sma21'), (50, 'sma50'), (200, 'sma200')]:
            if len(closes) >= period:
                sma = sum(closes[-period:]) / period
                pct_distance = ((current_price - sma) / sma) * 100
                result[key] = round(pct_distance, 2)
            else:
                result[key] = 0
        
        return result
    
    def _calculate_index_stats(self, bars: list) -> dict:
        """
        Calculate comprehensive index statistics including price, day/week %, and SMA distances.
        
        Args:
            bars: List of DailyBar objects with .close attribute, ordered oldest to newest
            
        Returns:
            Dict with keys: 'price', 'day_pct', 'week_pct', 'sma21', 'sma50', 'sma200'
        """
        result = {
            'price': 0,
            'day_pct': 0,
            'week_pct': 0,
            'sma21': 0,
            'sma50': 0,
            'sma200': 0
        }
        
        if not bars or len(bars) < 2:
            return result
        
        closes = [bar.close for bar in bars]
        current_price = closes[-1]
        result['price'] = current_price
        
        # Day change (current vs previous day)
        if len(closes) >= 2:
            prev_close = closes[-2]
            if prev_close > 0:
                result['day_pct'] = round(((current_price - prev_close) / prev_close) * 100, 2)
        
        # Week change (current vs 5 trading days ago)
        if len(closes) >= 6:
            week_ago_close = closes[-6]
            if week_ago_close > 0:
                result['week_pct'] = round(((current_price - week_ago_close) / week_ago_close) * 100, 2)
        
        # SMA calculations
        for period, key in [(21, 'sma21'), (50, 'sma50'), (200, 'sma200')]:
            if len(closes) >= period:
                sma = sum(closes[-period:]) / period
                pct_distance = ((current_price - sma) / sma) * 100
                result[key] = round(pct_distance, 2)
        
        return result
    
    def _create_card(self, position, latest_alert: dict = None) -> PositionCard:
        """Create a position card from a database position.
        
        Args:
            position: Position model instance
            latest_alert: Optional dict with latest alert data including severity
        """
        return PositionCard(
            position_id=position.id,
            symbol=position.symbol,
            state=position.state,
            pattern=position.pattern,
            pivot=position.pivot,
            last_price=position.last_price,
            pnl_pct=position.current_pnl_pct,
            rs_rating=position.rs_rating,
            total_shares=position.total_shares,
            avg_cost=position.avg_cost,
            watch_date=position.watch_date,
            entry_date=position.entry_date or position.breakout_date,
            portfolio=position.portfolio,
            entry_grade=position.entry_grade,
            entry_score=position.entry_score,
            latest_alert=latest_alert
        )
    
    def _open_ibd_editor(self):
        """Open the IBD Exposure editor dialog."""
        try:
            from sqlalchemy import text
            
            # Get current IBD exposure from database
            session = self.db.get_new_session()
            try:
                # Ensure table exists
                self._ensure_ibd_tables(session)
                
                result = session.execute(text(
                    "SELECT market_status, exposure_min, exposure_max, notes, updated_at "
                    "FROM ibd_exposure_current WHERE id=1"
                )).fetchone()
                
                if result:
                    status, min_exp, max_exp, notes, updated = result
                    notes = notes or ''
                else:
                    status = 'CONFIRMED_UPTREND'
                    min_exp = 80
                    max_exp = 100
                    notes = ''
                    updated = None
            finally:
                session.close()
            
            # Open dialog
            dialog = IBDExposureDialog(
                parent=self,
                current_status=status,
                current_min=min_exp,
                current_max=max_exp,
                current_notes=notes,
                last_updated=updated,
                db_session_factory=self.db.get_new_session
            )
            
            dialog.exposure_updated.connect(self._on_ibd_exposure_updated)
            dialog.exec()
            
        except Exception as e:
            self.logger.error(f"Failed to open IBD editor: {e}")
            QMessageBox.warning(
                self,
                "Error",
                f"Could not open IBD Exposure editor:\n{str(e)}"
            )
    
    def _ensure_ibd_tables(self, session):
        """Create IBD exposure tables if they don't exist."""
        from sqlalchemy import text
        try:
            # Check if table exists
            result = session.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ibd_exposure_current'"
            )).fetchone()
            
            if not result:
                # Create current table
                session.execute(text("""
                    CREATE TABLE ibd_exposure_current (
                        id INTEGER PRIMARY KEY,
                        market_status VARCHAR(30) NOT NULL,
                        exposure_min INTEGER NOT NULL,
                        exposure_max INTEGER NOT NULL,
                        notes TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_by VARCHAR(50) DEFAULT 'user'
                    )
                """))
                
                # Create history table
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS ibd_exposure_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        market_status VARCHAR(30) NOT NULL,
                        exposure_min INTEGER NOT NULL,
                        exposure_max INTEGER NOT NULL,
                        notes TEXT,
                        changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        changed_by VARCHAR(50) DEFAULT 'user',
                        source VARCHAR(20) DEFAULT 'manual'
                    )
                """))
                
                # Insert default
                session.execute(text("""
                    INSERT INTO ibd_exposure_current 
                    (id, market_status, exposure_min, exposure_max, notes)
                    VALUES (1, 'CONFIRMED_UPTREND', 80, 100, 'Default initial value')
                """))
                
                session.commit()
                self.logger.info("Created IBD exposure tables")
        except Exception as e:
            self.logger.warning(f"Could not ensure IBD tables: {e}")
    
    def _on_ibd_exposure_updated(self, status: str, min_exp: int, max_exp: int, notes: str):
        """Handle IBD exposure update from dialog."""
        try:
            from sqlalchemy import text
            from datetime import datetime
            
            session = self.db.get_new_session()
            try:
                # Update current
                session.execute(text("""
                    UPDATE ibd_exposure_current 
                    SET market_status=:status, exposure_min=:min, exposure_max=:max, 
                        notes=:notes, updated_at=:updated
                    WHERE id=1
                """), {
                    'status': status, 'min': min_exp, 'max': max_exp, 
                    'notes': notes, 'updated': datetime.now()
                })
                
                # Record history
                session.execute(text("""
                    INSERT INTO ibd_exposure_history 
                    (market_status, exposure_min, exposure_max, notes, changed_at)
                    VALUES (:status, :min, :max, :notes, :changed)
                """), {
                    'status': status, 'min': min_exp, 'max': max_exp,
                    'notes': notes, 'changed': datetime.now()
                })
                
                session.commit()
            finally:
                session.close()
            
            # Update the banner display
            self.regime_banner.exposure_label.setText(f"{min_exp}-{max_exp}%")
            self.logger.info(f"IBD exposure updated: {status} ({min_exp}-{max_exp}%)")
            
        except Exception as e:
            self.logger.error(f"Failed to update IBD exposure: {e}")
            QMessageBox.warning(
                self,
                "Error", 
                f"Could not save IBD exposure:\n{str(e)}"
            )
    
    def _on_position_dropped(self, position_id: int, from_state: int, to_state: int):
        """Handle position dropped on a column (state transition)."""
        self.logger.info(f"Position {position_id} dropped: {from_state} → {to_state}")
        
        # Get position data
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)
            
            if not position:
                self.logger.error(f"Position {position_id} not found")
                return
            
            # Prepare current data for dialog
            current_data = {
                'symbol': position.symbol,
                'pivot': position.pivot,
                'stop_price': position.stop_price,
                'avg_cost': position.avg_cost,
                'total_shares': position.total_shares,
                'last_price': position.last_price,
                'e1_shares': position.e1_shares,
                'e1_price': position.e1_price,
                'e2_shares': position.e2_shares,
                'e2_price': position.e2_price,
                'e3_shares': position.e3_shares,
                'e3_price': position.e3_price,
                'entry_date': position.entry_date,
                'breakout_date': position.breakout_date,
                'watch_date': position.watch_date,
                'current_pnl_pct': position.current_pnl_pct,
                'notes': position.notes,
            }
            
            # Show transition dialog
            transition = get_transition(from_state, to_state)
            if transition and (transition.required_fields or transition.optional_fields):
                dialog = TransitionDialog(
                    symbol=position.symbol,
                    from_state=from_state,
                    to_state=to_state,
                    current_data=current_data,
                    parent=self
                )
                
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    self.logger.info("Transition cancelled")
                    return
                
                result = dialog.get_result()
            else:
                result = {}
            
            # Apply transition
            result['state'] = to_state
            result['state_updated_at'] = datetime.now()
            
            # Calculate derived fields
            if to_state == 1 and 'e1_shares' in result:
                result['total_shares'] = result['e1_shares']
                result['avg_cost'] = result.get('e1_price')
                result['entry_date'] = result.get('entry_date', datetime.now().date())
            
            elif to_state == 2 and 'e2_shares' in result:
                e1 = position.e1_shares or 0
                e2 = result['e2_shares']
                p1 = position.e1_price or 0
                p2 = result.get('e2_price', 0)
                result['total_shares'] = e1 + e2
                if e1 + e2 > 0:
                    result['avg_cost'] = (e1 * p1 + e2 * p2) / (e1 + e2)
                result['py1_done'] = True
            
            elif to_state == 3 and 'e3_shares' in result:
                e1 = position.e1_shares or 0
                e2 = position.e2_shares or 0
                e3 = result['e3_shares']
                p1 = position.e1_price or 0
                p2 = position.e2_price or 0
                p3 = result.get('e3_price', 0)
                result['total_shares'] = e1 + e2 + e3
                if e1 + e2 + e3 > 0:
                    result['avg_cost'] = (e1 * p1 + e2 * p2 + e3 * p3) / (e1 + e2 + e3)
                result['py2_done'] = True
            
            # Handle closing positions - create Outcome record
            if to_state < 0:
                self._create_outcome_record(session, position, result, to_state)
            
            # Update position
            repos.positions.update(position, **result)
            session.commit()
            
            self.logger.info(f"Position {position.symbol} transitioned to state {to_state}")
            
            # Refresh the board
            self._load_positions()
            self.status_bar.showMessage(f"Moved {position.symbol} to {STATES[to_state].display_name}")
            
        except Exception as e:
            self.logger.error(f"Error processing transition: {e}")
            session.rollback()
            QMessageBox.warning(self, "Error", f"Failed to process transition: {e}")
        finally:
            session.close()
    
    def _create_outcome_record(self, session, position, result: Dict[str, Any], to_state: int):
        """Create an Outcome record when closing a position."""
        from canslim_monitor.data.models import Outcome
        
        # Calculate P&L
        exit_price = result.get('exit_price', 0)
        avg_cost = position.avg_cost or 0
        total_shares = position.total_shares or 0
        
        gross_pnl = (exit_price - avg_cost) * total_shares if avg_cost > 0 else 0
        gross_pct = ((exit_price / avg_cost) - 1) * 100 if avg_cost > 0 else 0
        
        # Calculate holding days
        entry_date = position.entry_date or position.breakout_date
        exit_date = result.get('exit_date')
        holding_days = (exit_date - entry_date).days if entry_date and exit_date else 0
        
        # Determine exit reason for stops
        exit_reason = result.get('exit_reason')
        if to_state == -2 and not exit_reason:
            exit_reason = 'STOP_HIT'
        
        # Determine trade outcome if not specified
        trade_outcome = result.get('trade_outcome')
        if not trade_outcome:
            if to_state == -2:
                trade_outcome = 'STOPPED'
            elif gross_pct >= 20:
                trade_outcome = 'SUCCESS'
            elif gross_pct >= 5:
                trade_outcome = 'PARTIAL'
            elif gross_pct >= -2:
                trade_outcome = 'BREAKEVEN'
            else:
                trade_outcome = 'FAILED'
        
        # Create outcome record
        outcome = Outcome(
            position_id=position.id,
            symbol=position.symbol,
            portfolio=position.portfolio,
            
            # Entry context
            entry_date=entry_date,
            entry_price=avg_cost,
            entry_shares=total_shares,
            entry_grade=position.entry_grade,
            entry_score=position.entry_score,
            
            # CANSLIM factors at entry
            rs_at_entry=position.rs_rating,
            eps_at_entry=position.eps_rating,
            comp_at_entry=position.comp_rating,
            ad_at_entry=position.ad_rating,
            stage_at_entry=position.base_stage,
            pattern=position.pattern,
            base_depth_at_entry=position.base_depth,
            base_length_at_entry=position.base_length,
            
            # Exit data
            exit_date=exit_date,
            exit_price=exit_price,
            exit_shares=total_shares,
            exit_reason=exit_reason,
            
            # Results
            holding_days=holding_days,
            gross_pnl=gross_pnl,
            gross_pct=gross_pct,
            
            # Classification
            outcome=trade_outcome,
            outcome_score=1 if trade_outcome in ('SUCCESS', 'PARTIAL') else 0
        )
        
        session.add(outcome)
        self.logger.info(
            f"Created Outcome for {position.symbol}: {trade_outcome} "
            f"({gross_pct:.1f}%, {holding_days} days)"
        )
    
    def _on_card_clicked(self, position_id: int):
        """Handle card click - show quick info."""
        self.logger.debug(f"Card clicked: {position_id}")
    
    def _on_card_double_clicked(self, position_id: int):
        """Handle card double-click - open editor."""
        self.logger.debug(f"Card double-clicked: {position_id}")
        
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)
            
            if not position:
                self.logger.error(f"Position {position_id} not found")
                return
            
            # Convert position to dict for dialog
            position_data = {
                'id': position_id,  # Store ID for later update
                'symbol': position.symbol,
                'pattern': position.pattern,
                'pivot': position.pivot,
                'stop_price': position.stop_price,
                'hard_stop_pct': position.hard_stop_pct,
                'portfolio': position.portfolio,
                'base_stage': position.base_stage,
                'base_depth': position.base_depth,
                'base_length': position.base_length,
                # Ratings (Left Panel)
                'rs_rating': position.rs_rating,
                'rs_3mo': position.rs_3mo,
                'rs_6mo': position.rs_6mo,
                'eps_rating': position.eps_rating,
                'comp_rating': position.comp_rating,
                'smr_rating': position.smr_rating,
                'ad_rating': position.ad_rating,
                'ud_vol_ratio': position.ud_vol_ratio,
                # Industry data
                'group_rank': position.group_rank,  # Legacy
                'industry_rank': position.industry_rank,
                'industry_eps_rank': position.industry_eps_rank,
                'industry_rs_rank': position.industry_rs_rank,
                # Institutional
                'fund_count': position.fund_count,
                'funds_qtr_chg': position.funds_qtr_chg,
                'prior_uptrend': position.prior_uptrend,
                # Breakout quality
                'breakout_vol_pct': position.breakout_vol_pct,
                'breakout_price_pct': position.breakout_price_pct,
                # Position details
                'e1_shares': position.e1_shares,
                'e1_price': position.e1_price,
                'e2_shares': position.e2_shares,
                'e2_price': position.e2_price,
                'e3_shares': position.e3_shares,
                'e3_price': position.e3_price,
                'watch_date': position.watch_date,
                'breakout_date': position.breakout_date,
                'earnings_date': position.earnings_date,
                'notes': position.notes,
            }
            
            # Create modeless dialog with no parent - truly independent window
            self._edit_dialog = EditPositionDialog(position_data, None)  # None parent = independent window
            self._edit_position_id = position_id
            self._edit_symbol = position.symbol
            
            # Connect accepted signal to handler
            self._edit_dialog.accepted.connect(self._on_edit_dialog_accepted)
            
            # Show as modeless (non-blocking)
            self._edit_dialog.show()
            self._edit_dialog.raise_()
            self._edit_dialog.activateWindow()
                
        finally:
            session.close()
    
    def _on_edit_dialog_accepted(self):
        """Handle EditPositionDialog accepted."""
        if not hasattr(self, '_edit_dialog') or not self._edit_dialog:
            return
        
        result = self._edit_dialog.get_result()
        position_id = self._edit_position_id
        symbol = self._edit_symbol
        
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            
            # Update position
            repos.positions.update_by_id(position_id, **result)
            session.commit()
            
            self.status_bar.showMessage(f"Updated {symbol}")
            self._load_positions()
            
        except Exception as e:
            self.logger.error(f"Error updating position: {e}")
            session.rollback()
            QMessageBox.warning(self, "Error", f"Failed to update position: {e}")
        finally:
            session.close()
            self._edit_dialog = None
            self._edit_position_id = None
            self._edit_symbol = None
    
    def _on_card_context_menu(self, position_id: int, global_pos):
        """Handle card right-click - show context menu."""
        self.logger.debug(f"Context menu for position {position_id}")
        
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)
            
            if not position:
                return
            
            menu = QMenu(self)
            
            # Edit action
            edit_action = menu.addAction("✏️ Edit Position")
            edit_action.triggered.connect(lambda: self._on_card_double_clicked(position_id))
            
            # Score details action
            score_action = menu.addAction("📊 View Score Details")
            score_action.triggered.connect(lambda: self._show_score_details(position_id))
            
            # View alerts action
            alerts_action = menu.addAction("🔔 View Alerts")
            alerts_action.triggered.connect(lambda: self._show_position_alerts(position.symbol, position_id))
            
            menu.addSeparator()
            
            # State transition actions
            from canslim_monitor.gui.state_config import get_valid_transitions
            valid_transitions = get_valid_transitions(position.state)
            
            if valid_transitions:
                move_menu = menu.addMenu("📦 Move to...")
                for transition in valid_transitions:
                    to_state = transition.to_state
                    to_name = STATES[to_state].display_name
                    action = move_menu.addAction(f"{to_name}")
                    action.triggered.connect(
                        lambda checked, ts=to_state: self._trigger_transition(position_id, position.state, ts)
                    )
            
            menu.addSeparator()
            
            # Quick actions based on state
            if position.state >= 1:  # In position
                stop_action = menu.addAction("🛑 Stop Out")
                stop_action.triggered.connect(
                    lambda: self._trigger_transition(position_id, position.state, -2)
                )
                
                close_action = menu.addAction("✅ Close Position")
                close_action.triggered.connect(
                    lambda: self._trigger_transition(position_id, position.state, -1)
                )
            
            menu.addSeparator()
            
            # Delete action
            delete_action = menu.addAction("🗑️ Delete")
            delete_action.triggered.connect(lambda: self._delete_position(position_id))
            
            menu.exec(global_pos)
            
        finally:
            session.close()
    
    def _on_alert_clicked(self, alert_id: int, position_id: int):
        """Handle click on alert row - acknowledge the alert."""
        self.logger.debug(f"Alert clicked: alert_id={alert_id}, position_id={position_id}")
        
        try:
            from canslim_monitor.services.alert_service import AlertService
            
            # Create alert service with our DB session factory
            alert_service = AlertService(
                db_session_factory=self.db.get_new_session,
                logger=self.logger
            )
            
            # Acknowledge the alert
            if alert_service.acknowledge_alert(alert_id):
                self.logger.info(f"Acknowledged alert {alert_id}")
                self.status_bar.showMessage(f"Alert acknowledged", 3000)
                
                # Reload positions to update the card display
                self._load_positions()
            else:
                self.logger.warning(f"Failed to acknowledge alert {alert_id}")
                
        except Exception as e:
            self.logger.error(f"Error acknowledging alert: {e}")
    
    def _on_acknowledge_all_alerts(self):
        """Acknowledge all unacknowledged alerts."""
        try:
            from canslim_monitor.services.alert_service import AlertService
            
            alert_service = AlertService(
                db_session_factory=self.db.get_new_session,
                logger=self.logger
            )
            
            count = alert_service.acknowledge_all_alerts()
            self.logger.info(f"Acknowledged {count} alerts")
            self.status_bar.showMessage(f"Acknowledged {count} alerts", 3000)
            
            # Reload positions to update card displays
            self._load_positions()
            
        except Exception as e:
            self.logger.error(f"Error acknowledging all alerts: {e}")
            QMessageBox.warning(self, "Error", f"Failed to acknowledge alerts: {e}")
    
    def _on_open_alert_monitor(self):
        """Open the global alert monitor window."""
        try:
            from canslim_monitor.gui.alerts import GlobalAlertWindow
            from canslim_monitor.services.alert_service import AlertService
            from canslim_monitor.utils.config import get_config
            
            # Create alert service
            alert_service = AlertService(
                db_session_factory=self.db.get_new_session,
                logger=self.logger
            )
            
            # Get config
            config = get_config()
            
            # Get or create singleton window
            window = GlobalAlertWindow.get_instance(
                parent=self,
                db_session_factory=self.db.get_new_session,
                alert_service=alert_service,
                config=config
            )
            window.show()
            
            self.logger.info("Opened Alert Monitor window")
            
        except Exception as e:
            self.logger.error(f"Error opening Alert Monitor: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open Alert Monitor: {e}")
    
    def _show_position_alerts(self, symbol: str, position_id: int = None):
        """Show alerts for a specific symbol/position."""
        try:
            from canslim_monitor.gui.alerts import PositionAlertDialog
            from canslim_monitor.services.alert_service import AlertService
            
            # Create alert service
            alert_service = AlertService(
                db_session_factory=self.db.get_new_session,
                logger=self.logger
            )
            
            # Fetch alerts for this symbol
            alerts = alert_service.get_recent_alerts(
                symbol=symbol,
                hours=24 * 90,  # 90 days
                limit=500
            )
            
            if not alerts:
                self.status_bar.showMessage(f"No alerts found for {symbol}", 3000)
                return
            
            # Show dialog
            dialog = PositionAlertDialog(
                symbol=symbol,
                alerts=alerts,
                parent=self,
                alert_service=alert_service,
                db_session_factory=self.db.get_new_session
            )
            dialog.alert_acknowledged.connect(lambda _: self._load_positions())
            dialog.show()  # Modeless
            
            self.logger.info(f"Opened alerts dialog for {symbol} with {len(alerts)} alerts")
            
        except Exception as e:
            self.logger.error(f"Error showing position alerts: {e}")
            QMessageBox.warning(self, "Error", f"Failed to load alerts: {e}")
    
    def _trigger_transition(self, position_id: int, from_state: int, to_state: int):
        """Trigger a state transition (reuse existing drop logic)."""
        self._on_position_dropped(position_id, from_state, to_state)
    
    def _show_score_details(self, position_id: int):
        """Show detailed score breakdown for a position."""
        import json
        from canslim_monitor.utils.scoring import CANSLIMScorer
        
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)
            
            if not position:
                return
            
            # Get current market regime (default to BULLISH)
            market_regime = 'BULLISH'
            try:
                market_config = repos.market_config.get_current()
                if market_config:
                    market_regime = market_config.regime
            except:
                pass
            
            scorer = CANSLIMScorer()
            
            # Try to load stored details first (includes dynamic components from recalculation)
            details = None
            if position.entry_score_details:
                try:
                    details = json.loads(position.entry_score_details)
                    # Ensure we have the required fields
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
            
            # Format details text (will include dynamic components if present)
            details_text = scorer.format_details_text(details, symbol=position.symbol, pivot=position.pivot)
            
            # If no execution data, append a hint
            if 'execution' not in details:
                details_text += "\n\n════════════════════════════════════════════════════════════"
                details_text += "\n--- EXECUTION FEASIBILITY ---"
                details_text += "\n  No execution data available."
                details_text += "\n  Click 'Recalculate' to fetch historical data and analyze."
                details_text += "\n════════════════════════════════════════════════════════════"
            
            # Update position if score changed (only for static recalc)
            if position.entry_score != score or position.entry_grade != grade:
                position.entry_score = score
                position.entry_grade = grade
                position.entry_score_details = json.dumps(details)
                session.commit()
                # Refresh display
                self._load_positions()
            
            # Show in a dialog
            from PyQt6.QtWidgets import QTextEdit
            
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Score Details: {position.symbol}")
            dialog.setMinimumSize(720, 750)  # Wider and taller for better readability
            
            layout = QVBoxLayout(dialog)
            
            # Header with symbol and grade (no /100 notation)
            header = QLabel(f"<h2>{position.symbol} - Grade: {grade} (Score: {score})</h2>")
            header.setStyleSheet("color: #333;")
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
            
            # Recalculate button
            btn_layout = QHBoxLayout()
            
            recalc_btn = QPushButton("🔄 Recalculate")
            recalc_btn.setToolTip("Fetch latest data and recalculate score with execution feasibility")
            recalc_btn.clicked.connect(lambda: self._recalculate_score(position_id, dialog))
            btn_layout.addWidget(recalc_btn)
            
            btn_layout.addStretch()
            
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(close_btn)
            
            layout.addLayout(btn_layout)
            
            dialog.exec()
            
        finally:
            session.close()
    
    def _recalculate_score(self, position_id: int, parent_dialog: QDialog = None):
        """Recalculate and update the score for a position with full data refresh.
        
        Uses QTimer for step-by-step processing to keep UI responsive and 
        prevent the dialog from closing prematurely.
        """
        import json
        from datetime import datetime
        from canslim_monitor.utils.scoring import CANSLIMScorer
        
        # CRITICAL: Ensure event loop exists for any async libraries that might be imported
        # Python 3.10+ no longer auto-creates event loops
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Event loop is closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        session = self.db.get_new_session()
        repos = RepositoryManager(session)
        position = repos.positions.get_by_id(position_id)
        
        if not position:
            session.close()
            return
        
        symbol = position.symbol
        
        # Create progress dialog
        progress = QDialog(parent_dialog or self)
        progress.setWindowTitle(f"Recalculating {symbol}")
        progress.setMinimumSize(550, 400)
        progress.setModal(True)
        
        progress_layout = QVBoxLayout(progress)
        
        status_label = QLabel(f"<h3>Recalculating {symbol}...</h3>")
        progress_layout.addWidget(status_label)
        
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: Consolas, monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        progress_layout.addWidget(log_text)
        
        close_btn = QPushButton("Processing...")
        close_btn.setEnabled(False)
        close_btn.clicked.connect(progress.accept)
        progress_layout.addWidget(close_btn)
        
        def log(msg):
            log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            scrollbar = log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            QApplication.processEvents()
        
        # State for step-by-step processing
        state = {
            'step': 0,
            'daily_df': None,
            'spy_df': None,  # SPY data for RS Trend calculation
            'adv_50day': 0,
            'market_regime': 'BULLISH',
            'score': 0,
            'grade': 'F',
            'details': {},
            'complete': False
        }
        
        def process_step():
            """Process one step at a time using QTimer."""
            try:
                if state['step'] == 0:
                    # Step 0: Initialize
                    log("=" * 50)
                    log(f"Starting recalculation for {symbol}")
                    log("=" * 50)
                    log("")
                    
                    # Get market regime
                    try:
                        market_config = repos.market_config.get_current()
                        if market_config:
                            state['market_regime'] = market_config.regime
                    except:
                        pass
                    log(f"Market regime: {state['market_regime']}")
                    
                    state['step'] = 1
                    QTimer.singleShot(50, process_step)
                    
                elif state['step'] == 1:
                    # Step 1: Fetch historical data
                    log("")
                    log("--- Fetching Historical Data ---")
                    
                    try:
                        from canslim_monitor.services.volume_service import VolumeService
                        from canslim_monitor.integrations.polygon_client import PolygonClient
                        
                        # Check both market_data and polygon config sections
                        market_data_config = self.config.get('market_data', {})
                        polygon_config = self.config.get('polygon', {})
                        
                        # Prefer market_data, fall back to polygon
                        api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
                        base_url = market_data_config.get('base_url') or polygon_config.get('base_url', 'https://api.polygon.io')
                        
                        if api_key:
                            log(f"Using API: {base_url}")
                            polygon_client = PolygonClient(
                                api_key=api_key,
                                base_url=base_url
                            )
                            volume_service = VolumeService(
                                db_session_factory=self.db.get_new_session,
                                polygon_client=polygon_client
                            )
                            
                            log(f"Updating {symbol} historical data...")
                            result = volume_service.update_symbol(symbol, days=200)
                            
                            if result.success:
                                log(f"✔ Fetched {result.bars_fetched} bars, stored {result.bars_stored}")
                                state['adv_50day'] = result.avg_volume_50d
                                log(f"✔ 50-day ADV: {state['adv_50day']:,}")
                                
                                state['daily_df'] = volume_service.get_dataframe(symbol, days=200)
                                if state['daily_df'] is not None:
                                    log(f"✔ Loaded {len(state['daily_df'])} days for analysis")
                                
                                # Also fetch SPY data for RS Trend calculation
                                log("Fetching SPY data for RS calculation...")
                                spy_result = volume_service.update_symbol('SPY', days=200)
                                if spy_result.success:
                                    state['spy_df'] = volume_service.get_dataframe('SPY', days=200)
                                    if state['spy_df'] is not None:
                                        log(f"✔ Loaded {len(state['spy_df'])} days of SPY data")
                                    else:
                                        log("⚠  Could not load SPY DataFrame")
                                else:
                                    log(f"⚠  SPY fetch failed: {spy_result.error}")
                            else:
                                log(f"⚠  Data fetch failed: {result.error}")
                        else:
                            log("⚠  No Polygon API key configured")
                            log("  Add polygon.api_key to user_config.yaml")
                    except ImportError as e:
                        log(f"⚠  Import error: {e}")
                    except Exception as e:
                        log(f"⚠  Data fetch error: {e}")
                    
                    state['step'] = 2
                    QTimer.singleShot(50, process_step)
                    
                elif state['step'] == 2:
                    # Step 2: Calculate score
                    log("")
                    log("--- Calculating Score ---")
                    
                    # Build position data
                    position_data = {
                        'symbol': symbol,
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
                    
                    scorer = CANSLIMScorer()
                    daily_df = state.get('daily_df')
                    spy_df = state.get('spy_df')
                    
                    if daily_df is not None and len(daily_df) >= 50:
                        log("Using dynamic scoring with technical analysis...")
                        try:
                            score, grade, details = scorer.calculate_score_with_dynamic(
                                position_data, daily_df, 
                                index_df=spy_df,  # Pass SPY data for RS Trend
                                market_regime=state['market_regime']
                            )
                            log(f"✔ Dynamic score: {details.get('dynamic_score', 0)} pts")
                        except Exception as e:
                            log(f"⚠  Dynamic scoring failed: {e}, using static")
                            score, grade, details = scorer.calculate_score(
                                position_data, state['market_regime']
                            )
                    else:
                        log("Using static scoring only (no historical data)")
                        score, grade, details = scorer.calculate_score(
                            position_data, state['market_regime']
                        )
                    
                    log(f"✔ Total score: {score}, Grade: {grade}")
                    
                    # Show dynamic components breakdown
                    dyn_comps = details.get('dynamic_components', [])
                    if dyn_comps:
                        log(f"  Dynamic factors: {len(dyn_comps)} items")
                        for dc in dyn_comps:
                            sign = '+' if dc.get('points', 0) >= 0 else ''
                            log(f"    {dc.get('name')}: {sign}{dc.get('points')} pts")
                    
                    state['score'] = score
                    state['grade'] = grade
                    state['details'] = details
                    
                    state['step'] = 3
                    QTimer.singleShot(50, process_step)
                    
                elif state['step'] == 3:
                    # Step 3: Calculate execution feasibility
                    log("")
                    log("--- Calculating Execution Feasibility ---")
                    
                    exec_data = self._calculate_execution_feasibility(
                        symbol, position, state['grade'], state['adv_50day']
                    )
                    
                    if exec_data:
                        state['details']['execution'] = exec_data
                        log(f"✔ Execution risk: {exec_data.get('overall_risk', 'N/A')}")
                        
                        if exec_data.get('adv_50day'):
                            log(f"  ADV: {exec_data['adv_50day']:,} shares")
                            log(f"  ADV Status: {exec_data.get('adv_status', 'N/A')}")
                        if exec_data.get('pct_of_adv'):
                            log(f"  Position % of ADV: {exec_data['pct_of_adv']:.2f}%")
                        if exec_data.get('recommendation'):
                            log(f"  Recommendation: {exec_data['recommendation']}")
                        
                        # Log spread data if available
                        if exec_data.get('spread_available'):
                            bid = exec_data.get('bid', 0)
                            ask = exec_data.get('ask', 0)
                            spread_pct = exec_data.get('spread_pct', 0)
                            log(f"  Bid/Ask: ${bid:.2f} / ${ask:.2f}")
                            log(f"  Spread: {spread_pct:.3f}%")
                        else:
                            if self.ibkr_connected:
                                log("  Spread: Could not fetch bid/ask")
                            else:
                                log("  Spread: N/A (IBKR not connected)")
                    else:
                        log("⚠  Execution feasibility: N/A (no ADV data)")
                    
                    state['step'] = 4
                    QTimer.singleShot(50, process_step)
                    
                elif state['step'] == 4:
                    # Step 4: Save to database
                    log("")
                    log("--- Saving to Database ---")
                    
                    position.entry_score = state['score']
                    position.entry_grade = state['grade']
                    position.entry_score_details = json.dumps(state['details'])
                    session.commit()
                    
                    log("✔ Saved score to database")
                    
                    state['step'] = 5
                    QTimer.singleShot(50, process_step)
                    
                elif state['step'] == 5:
                    # Step 5: Complete
                    log("")
                    log("=" * 50)
                    log(f"✔ COMPLETE!")
                    log(f"  {symbol}: {state['grade']} ({state['score']} pts)")
                    log("=" * 50)
                    log("")
                    log("Click 'Close' to view the updated score details.")
                    
                    self.status_bar.showMessage(
                        f"Recalculated {symbol}: {state['grade']} (Score: {state['score']})"
                    )
                    
                    # Refresh the position list
                    self._load_positions()
                    
                    # Enable close button
                    close_btn.setEnabled(True)
                    close_btn.setText("Close")
                    
                    state['complete'] = True
                    
                    # Close session
                    session.close()
                    
            except Exception as e:
                log(f"❌ Error: {e}")
                import traceback
                log(traceback.format_exc())
                close_btn.setEnabled(True)
                close_btn.setText("Close")
                session.close()
        
        # Show dialog and start processing
        progress.show()
        QTimer.singleShot(100, process_step)
        
        # Wait for dialog to close
        result = progress.exec()
        
        # If completed, close parent and reopen score details
        if state['complete'] and parent_dialog:
            parent_dialog.accept()
            self._show_score_details(position_id)
    
    def _calculate_execution_feasibility(
        self, 
        symbol: str, 
        position, 
        grade: str,
        adv_50day: int = 0
    ) -> dict:
        """
        Calculate execution feasibility metrics.
        
        Returns dict with execution data for the score report.
        """
        if adv_50day <= 0:
            return {}
        
        # Portfolio config
        portfolio_value = self.config.get('position_sizing', {}).get('portfolio_value', 100000)
        
        # Grade allocations
        grade_allocations = {
            "A+": 0.50, "A": 0.50,
            "B+": 0.30, "B": 0.30,
            "C+": 0.20, "C": 0.20,
            "D": 0.00, "F": 0.00
        }
        allocation_pct = grade_allocations.get(grade, 0)
        
        # Position sizing
        position_dollars = portfolio_value * allocation_pct
        current_price = position.pivot or position.last_price or 100
        shares_needed = int(position_dollars / current_price) if current_price > 0 else 0
        
        # ADV analysis
        pct_of_adv = (shares_needed / adv_50day * 100) if adv_50day > 0 else 0
        
        # ADV status
        if adv_50day >= 500000:
            adv_status = "PASS"
            adv_pct_of_min = adv_50day / 500000 * 100
        elif adv_50day >= 400000:
            adv_status = "CAUTION"
            adv_pct_of_min = adv_50day / 500000 * 100
        else:
            adv_status = "FAIL"
            adv_pct_of_min = adv_50day / 500000 * 100
        
        # Try to get bid/ask spread from IBKR if connected
        spread_available = False
        spread_pct = None
        spread_status = None
        bid_price = None
        ask_price = None
        
        if self.ibkr_connected and self.ibkr_client:
            try:
                # Fetch quote for this symbol
                quotes = self.ibkr_client.get_quotes([symbol])
                if quotes and symbol in quotes:
                    quote_data = quotes[symbol]
                    bid_price = quote_data.get('bid')
                    ask_price = quote_data.get('ask')
                    
                    if bid_price and ask_price and bid_price > 0:
                        spread_pct = ((ask_price - bid_price) / bid_price) * 100
                        spread_available = True
                        
                        # Classify spread status for scoring.py display
                        if spread_pct <= 0.10:
                            spread_status = "TIGHT"
                        elif spread_pct <= 0.30:
                            spread_status = "NORMAL"
                        else:
                            spread_status = "WIDE"
            except Exception as e:
                self.logger.warning(f"Could not fetch bid/ask for {symbol}: {e}")
        
        # Overall execution risk
        if adv_status == "FAIL":
            overall_risk = "DO_NOT_TRADE"
            recommendation = "Volume too low for institutional quality"
        elif pct_of_adv > 5:
            overall_risk = "DO_NOT_TRADE"
            recommendation = "Position too large relative to liquidity"
        elif pct_of_adv > 2:
            overall_risk = "HIGH"
            recommendation = "Reduce position size or use limit orders"
        elif pct_of_adv > 1 or adv_status == "CAUTION":
            overall_risk = "MODERATE"
            recommendation = "Use limit orders; may need multiple fills"
        else:
            overall_risk = "LOW"
            recommendation = "Normal execution; standard limit order"
        
        # Adjust risk if spread is wide
        if spread_available and spread_pct is not None:
            if spread_pct > 0.5 and overall_risk == "LOW":
                overall_risk = "MODERATE"
                recommendation = "Wide spread - use limit orders"
            elif spread_pct > 1.0:
                overall_risk = "HIGH"
                recommendation = f"Very wide spread ({spread_pct:.2f}%) - use limit orders carefully"
        
        return {
            'adv_50day': adv_50day,
            'adv_status': adv_status,
            'adv_pct_of_min': adv_pct_of_min,
            'spread_available': spread_available,
            'spread_pct': spread_pct,
            'spread_status': spread_status,
            'bid': bid_price,      # scoring.py expects 'bid'
            'ask': ask_price,      # scoring.py expects 'ask'
            'position_dollars': position_dollars,
            'allocation_pct': allocation_pct,
            'shares_needed': shares_needed,
            'pct_of_adv': pct_of_adv,
            'overall_risk': overall_risk,
            'recommendation': recommendation,
        }
    
    def _recalculate_all_scores(self):
        """Recalculate entry scores for all active positions with full dynamic scoring."""
        import json
        import asyncio
        from datetime import datetime
        from canslim_monitor.utils.scoring import CANSLIMScorer
        
        # Ensure event loop exists
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Event loop is closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        session = self.db.get_new_session()
        repos = RepositoryManager(session)
        
        # Get all active positions
        positions = repos.positions.get_all(include_closed=False)
        
        if not positions:
            session.close()
            QMessageBox.information(self, "No Positions", "No active positions to score.")
            return
        
        # Get market regime
        market_regime = 'BULLISH'
        try:
            market_config = repos.market_config.get_current()
            if market_config:
                market_regime = market_config.regime
        except:
            pass
        
        # Create progress dialog
        progress = QDialog(self)
        progress.setWindowTitle("Recalculating All Scores")
        progress.setMinimumSize(650, 500)
        progress.setModal(True)
        
        progress_layout = QVBoxLayout(progress)
        
        status_label = QLabel(f"<h3>Recalculating {len(positions)} positions...</h3>")
        progress_layout.addWidget(status_label)
        
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: Consolas, monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        progress_layout.addWidget(log_text)
        
        close_btn = QPushButton("Processing...")
        close_btn.setEnabled(False)
        close_btn.clicked.connect(progress.accept)
        progress_layout.addWidget(close_btn)
        
        def log(msg):
            log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            scrollbar = log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            QApplication.processEvents()
        
        # State for batch processing
        state = {
            'index': 0,
            'positions': positions,
            'updated': 0,
            'failed': 0,
            'market_regime': market_regime,
            'volume_service': None,
            'scorer': CANSLIMScorer()
        }
        
        def process_next():
            """Process the next position in the queue."""
            try:
                # Check if done
                if state['index'] >= len(state['positions']):
                    # All done
                    session.commit()
                    log("")
                    log("=" * 50)
                    log(f"✔ COMPLETE: {state['updated']} updated, {state['failed']} failed")
                    log("=" * 50)
                    
                    close_btn.setText("Close")
                    close_btn.setEnabled(True)
                    status_label.setText(f"<h3>Completed {state['updated']} positions</h3>")
                    
                    # Refresh the board
                    self._load_positions()
                    return
                
                position = state['positions'][state['index']]
                symbol = position.symbol
                current = state['index'] + 1
                total = len(state['positions'])
                
                log("")
                log(f"[{current}/{total}] Processing {symbol}...")
                status_label.setText(f"<h3>Processing {symbol} ({current}/{total})...</h3>")
                
                # Initialize volume service if needed
                if state['volume_service'] is None:
                    try:
                        from canslim_monitor.services.volume_service import VolumeService
                        
                        market_data_config = self.config.get('market_data', {})
                        polygon_config = self.config.get('polygon', {})
                        api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
                        
                        if api_key:
                            from canslim_monitor.integrations.polygon_client import PolygonClient
                            polygon_client = PolygonClient(api_key=api_key)
                            state['volume_service'] = VolumeService(
                                db_session_factory=self.db.get_new_session,
                                polygon_client=polygon_client
                            )
                            log("✔ Volume service initialized")
                        else:
                            log("⚠  No API key - using static scoring only")
                    except Exception as e:
                        log(f"⚠  Volume service init failed: {e}")
                
                # Fetch historical data
                daily_df = None
                spy_df = None
                adv_50day = 0
                
                if state['volume_service']:
                    try:
                        result = state['volume_service'].update_symbol(symbol, days=200)
                        if result.success:
                            adv_50day = result.avg_volume_50d
                            daily_df = state['volume_service'].get_dataframe(symbol, days=200)
                            log(f"  Fetched data: ADV={adv_50day:,.0f}")
                            
                            # Fetch SPY for RS Trend
                            spy_result = state['volume_service'].update_symbol('SPY', days=200)
                            if spy_result.success:
                                spy_df = state['volume_service'].get_dataframe('SPY', days=200)
                        else:
                            log(f"  ⚠  Data fetch failed: {result.error}")
                    except Exception as e:
                        log(f"  ⚠  Data error: {e}")
                
                # Build position data
                position_data = {
                    'symbol': symbol,
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
                    'pivot': position.pivot,
                }
                
                # Calculate score
                if daily_df is not None and len(daily_df) >= 50:
                    try:
                        score, grade, details = state['scorer'].calculate_score_with_dynamic(
                            position_data, daily_df,
                            index_df=spy_df,
                            market_regime=state['market_regime']
                        )
                        log(f"  Score: {score} ({grade}) [Dynamic: {details.get('dynamic_score', 0):+d}]")
                    except Exception as e:
                        log(f"  ⚠  Dynamic scoring failed: {e}, using static")
                        score, grade, details = state['scorer'].calculate_score(
                            position_data, state['market_regime']
                        )
                else:
                    score, grade, details = state['scorer'].calculate_score(
                        position_data, state['market_regime']
                    )
                    log(f"  Score: {score} ({grade}) [Static only]")
                
                # Add execution feasibility
                if adv_50day > 0 and position.pivot:
                    try:
                        grade_allocations = {'A+': 0.50, 'A': 0.50, 'B+': 0.35, 'B': 0.30, 'C+': 0.20, 'C': 0.20}
                        allocation_pct = grade_allocations.get(grade, 0)
                        position_value = 100000 * allocation_pct
                        shares_needed = int(position_value / position.pivot) if position.pivot > 0 else 0
                        pct_of_adv = (shares_needed / adv_50day * 100) if adv_50day > 0 else 0
                        
                        if adv_50day >= 500000:
                            exec_risk = 'LOW'
                        elif adv_50day >= 250000:
                            exec_risk = 'MODERATE'
                        else:
                            exec_risk = 'HIGH'
                        
                        details['execution'] = {
                            'adv_50day': adv_50day,
                            'position_value': position_value,
                            'shares_needed': shares_needed,
                            'pct_of_adv': pct_of_adv,
                            'risk': exec_risk
                        }
                    except:
                        pass
                
                # Update position
                position.entry_score = score
                position.entry_grade = grade
                position.entry_score_details = json.dumps(details)
                state['updated'] += 1
                
                # Move to next
                state['index'] += 1
                QTimer.singleShot(100, process_next)
                
            except Exception as e:
                log(f"  ✗ Error: {e}")
                state['failed'] += 1
                state['index'] += 1
                QTimer.singleShot(100, process_next)
        
        # Start processing
        log("=" * 50)
        log(f"Batch Recalculation - {len(positions)} positions")
        log(f"Market Regime: {market_regime}")
        log("=" * 50)
        
        progress.show()
        QTimer.singleShot(100, process_next)
        
        # Keep session open until dialog closes
        progress.finished.connect(lambda: session.close())
    
    def _delete_position(self, position_id: int):
        """Delete a position after confirmation."""
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)
            
            if not position:
                return
            
            reply = QMessageBox.question(
                self,
                "Delete Position",
                f"Are you sure you want to delete {position.symbol}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                repos.positions.delete_by_id(position_id)
                session.commit()
                self.status_bar.showMessage(f"Deleted {position.symbol}")
                self._load_positions()
                
        finally:
            session.close()
    
    def _on_add_clicked(self, state: int):
        """Handle add button click."""
        # Create modeless dialog with no parent - truly independent window
        self._add_dialog = AddPositionDialog(None)  # None parent = independent window
        
        # Connect accepted signal to handler
        self._add_dialog.accepted.connect(self._on_add_dialog_accepted)
        
        # Show as modeless (non-blocking)
        self._add_dialog.show()
        self._add_dialog.raise_()
        self._add_dialog.activateWindow()
    
    def _on_add_dialog_accepted(self):
        """Handle AddPositionDialog accepted."""
        import json
        from canslim_monitor.utils.scoring import CANSLIMScorer
        
        if not hasattr(self, '_add_dialog') or not self._add_dialog:
            return
        
        result = self._add_dialog.get_result()
        
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            
            # Check if symbol already exists in same portfolio (only check ACTIVE positions)
            existing = repos.positions.get_by_symbol(result['symbol'])
            if existing:
                # Check if same portfolio AND position is still active (state >= 0)
                # Allow re-adding if the existing position is closed (state < 0)
                if existing.portfolio == result.get('portfolio') and existing.state >= 0:
                    QMessageBox.warning(
                        self,
                        "Duplicate Symbol",
                        f"{result['symbol']} is already in portfolio '{result.get('portfolio', 'default')}'."
                    )
                    return
            
            # Calculate entry score before creating
            market_regime = 'BULLISH'
            try:
                market_config = repos.market_config.get_current()
                if market_config:
                    market_regime = market_config.regime
            except:
                pass
            
            scorer = CANSLIMScorer()
            score, grade, details = scorer.calculate_score(result, market_regime)
            
            # Add score to result
            result['entry_score'] = score
            result['entry_grade'] = grade
            result['entry_score_details'] = json.dumps(details)
            
            # Create position
            position = repos.positions.create(**result)
            session.commit()
            
            self.logger.info(f"Added position: {position.symbol} (Grade: {grade}, Score: {score})")
            self._load_positions()
            self.status_bar.showMessage(f"Added {position.symbol} to watchlist (Grade: {grade})")
            
        except Exception as e:
            self.logger.error(f"Error adding position: {e}")
            session.rollback()
            QMessageBox.warning(self, "Error", f"Failed to add position: {e}")
        finally:
            session.close()
            self._add_dialog = None
    
    def _on_start_service(self):
        """Start the monitoring service and connect to IBKR."""
        self.logger.info("Starting service...")
        
        try:
            # CRITICAL: Ensure event loop exists BEFORE importing ib_insync
            # ib_insync tries to access the event loop at import time
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self.logger.debug("Created new event loop for IBKR")
            
            # Load config
            from canslim_monitor.utils.config import get_ibkr_config, get_service_config, get_ibkr_client_id
            
            ibkr_config = get_ibkr_config()
            service_config = get_service_config()
            
            host = ibkr_config.get('host', '127.0.0.1')
            port = ibkr_config.get('port', 4001)  # Default to IB Gateway
            
            # GUI uses client_id_base + 5 to avoid conflict with service (which uses base + 0 to +4)
            client_id_base = ibkr_config.get('client_id_base', 20)
            client_id = client_id_base + 5  # GUI offset = 5
            
            self.logger.info(f"IBKR config: {host}:{port} (client {client_id})")
            
            # Update price interval from config
            self.price_update_interval = service_config.get('price_update_interval', 5) * 1000
            
            # Connect ib_insync loggers to our file logging
            try:
                from canslim_monitor.utils.logging import get_logger
                ibkr_logger = get_logger('ibkr')
                
                # Route ib_insync logs to our ibkr logger
                for ib_logger_name in ['ib_insync.client', 'ib_insync.wrapper', 'ib_insync.ib']:
                    ib_logger = logging.getLogger(ib_logger_name)
                    ib_logger.handlers = ibkr_logger.handlers.copy()
                    ib_logger.setLevel(logging.DEBUG)
            except Exception as e:
                self.logger.warning(f"Could not redirect ib_insync logs: {e}")
            
            # Import IBKR client (AFTER event loop is set up)
            from canslim_monitor.integrations.ibkr_client_threadsafe import ThreadSafeIBKRClient
            
            # Create client if needed
            if self.ibkr_client is None:
                self.ibkr_client = ThreadSafeIBKRClient(
                    host=host,
                    port=port,
                    client_id=client_id
                )
            
            # Connect
            self.status_bar.showMessage(f"Connecting to IBKR TWS ({host}:{port}, client {client_id})...")
            QApplication.processEvents()
            
            if self.ibkr_client.connect():
                self.ibkr_connected = True
                self.service_panel.set_running(True, "IBKR connected")
                self.status_bar.showMessage("Connected to IBKR TWS - fetching prices...")
                
                # Do initial price update
                self._update_prices()
                
                # Start timer for continuous updates
                self.price_timer.start(self.price_update_interval)
                
                self.logger.info(f"IBKR service started (refresh every {self.price_update_interval/1000}s)")
            else:
                self.ibkr_connected = False
                self.service_panel.set_running(False)
                self.status_bar.showMessage("Failed to connect to IBKR TWS")
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to IBKR TWS at {host}:{port}.\n\n"
                    "Make sure:\n"
                    "1. TWS or IB Gateway is running\n"
                    "2. API connections are enabled\n"
                    f"3. Port {port} is correct (7496=TWS live, 7497=TWS paper, 4001/4002=Gateway)\n\n"
                    "Check user_config.yaml to change settings."
                )
                
        except ImportError as e:
            self.logger.error(f"Failed to import IBKR client: {e}")
            QMessageBox.warning(self, "Import Error", f"IBKR client not available: {e}")
        except Exception as e:
            self.logger.error(f"Error starting service: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            QMessageBox.warning(self, "Error", f"Failed to start service: {e}")
    
    def _on_stop_service(self):
        """Stop the monitoring service and disconnect from IBKR."""
        self.logger.info("Stopping service...")
        
        # Stop price timer first (prevents new updates from starting)
        self.price_timer.stop()
        
        # Wait briefly for any in-progress price update, but don't block forever
        if self.price_thread is not None and self.price_thread.isRunning():
            self.logger.info("Waiting for price update to complete...")
            self.status_bar.showMessage("Stopping service...")
            
            # Wait up to 2 seconds with GUI responsiveness
            for _ in range(20):  # 20 x 100ms = 2 seconds
                QApplication.processEvents()
                if self.price_thread.wait(100):  # 100ms timeout
                    break
            
            # If still running after timeout, disconnect IBKR which will cause it to fail
            if self.price_thread.isRunning():
                self.logger.info("Price update still running, disconnecting IBKR...")
        
        self.price_update_in_progress = False
        
        # Disconnect IBKR (will cause any pending requests to fail)
        if self.ibkr_client:
            try:
                self.ibkr_client.disconnect()
            except:
                pass
        
        # Wait a bit more for thread to finish after disconnect
        if self.price_thread is not None and self.price_thread.isRunning():
            self.price_thread.wait(1000)  # 1 more second
        
        self.price_thread = None
        self.price_worker = None
        
        # Reset client so it gets recreated with fresh config on next start
        self.ibkr_client = None
        self.ibkr_connected = False
        self.service_panel.set_running(False)
        self.status_bar.showMessage("Service stopped")
    
    def _on_run_market_regime(self):
        """Run market regime analysis, save to database, and show results in dialog."""
        self.logger.info("=" * 50)
        self.logger.info("Starting market regime analysis from GUI menu")
        self.logger.info("=" * 50)
        
        # Create and show the dialog
        dialog = MarketRegimeDialog(self)
        dialog.show()
        dialog.raise_()  # Bring to front
        dialog.activateWindow()
        QApplication.processEvents()
        
        try:
            # Load config for API key
            import yaml
            from datetime import date, timedelta
            
            dialog.set_progress(5, "Loading configuration...")
            QApplication.processEvents()
            
            # Try to use already-loaded config first
            config = getattr(self, 'config', {}) or {}
            self.logger.info(f"Config from self.config: {bool(config)}, keys: {list(config.keys()) if config else []}")
            
            # If no config loaded, try to find config file
            if not config:
                config_paths = [
                    'user_config.yaml',
                    'canslim_monitor/user_config.yaml',
                    'config.yaml',
                    'canslim_monitor/config.yaml',
                ]
                for path in config_paths:
                    self.logger.info(f"Checking config path: {path} - exists: {os.path.exists(path)}")
                    if os.path.exists(path):
                        self.logger.info(f"Loading config from: {path}")
                        with open(path, 'r') as f:
                            config = yaml.safe_load(f) or {}
                        break
            
            polygon_key = (
                config.get('market_data', {}).get('api_key') or
                config.get('polygon', {}).get('api_key')
            )
            
            self.logger.info(f"Polygon API key found: {bool(polygon_key)}")
            if polygon_key:
                self.logger.info(f"Polygon API key prefix: {polygon_key[:10]}...")
            
            if not polygon_key:
                self.logger.error("No Polygon API key found!")
                dialog.show_error(
                    "No Polygon API key found in config.\n\n"
                    "Add to your config:\n"
                    "  market_data:\n"
                    "    api_key: 'your-api-key'"
                )
                dialog.exec()
                return
            
            dialog.set_progress(10, "Importing regime components...")
            QApplication.processEvents()
            self.logger.info("Importing regime components...")
            
            # Import regime components
            from canslim_monitor.regime.historical_data import fetch_spy_qqq_daily, fetch_index_daily
            from canslim_monitor.regime.distribution_tracker import DistributionDayTracker
            from canslim_monitor.regime.ftd_tracker import (
                FollowThroughDayTracker, RallyAttempt, FollowThroughDay, MarketStatus
            )
            from canslim_monitor.regime.market_regime import (
                MarketRegimeCalculator, DistributionData, FTDData, create_overnight_data
            )
            from canslim_monitor.regime.models_regime import (
                Base, DistributionDay, DistributionDayCount, DistributionDayOverride,
                OvernightTrend, MarketRegimeAlert, DDayTrend
            )
            
            dialog.set_progress(15, "Ensuring database tables exist...")
            QApplication.processEvents()
            
            # Ensure regime tables exist in main database
            self._ensure_regime_tables()
            self.logger.info("Database tables ensured")
            
            # Use in-memory session for intermediate tracking calculations
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            
            temp_engine = create_engine('sqlite:///:memory:')
            Base.metadata.create_all(temp_engine)
            TempSession = sessionmaker(bind=temp_engine)
            temp_session = TempSession()
            self.logger.info("Temp session created")
            
            dialog.set_progress(25, "Fetching index data from Polygon...")
            QApplication.processEvents()
            self.logger.info("Fetching SPY, QQQ, DIA, IWM data...")
            
            # Fetch market data for all index ETFs
            api_config = {'polygon': {'api_key': polygon_key}}
            data = fetch_index_daily(
                symbols=['SPY', 'QQQ', 'DIA', 'IWM'],
                lookback_days=250,  # Need 200+ for 200-day SMA
                config=api_config,
                use_indices=False
            )
            self.logger.info(f"Fetch complete. Data keys: {list(data.keys()) if data else 'None'}")
            
            spy_bars = data.get('SPY', [])
            qqq_bars = data.get('QQQ', [])
            dia_bars = data.get('DIA', [])
            iwm_bars = data.get('IWM', [])
            self.logger.info(f"SPY: {len(spy_bars)}, QQQ: {len(qqq_bars)}, DIA: {len(dia_bars)}, IWM: {len(iwm_bars)} bars")
            
            if not spy_bars or not qqq_bars:
                self.logger.error("No market data returned from Polygon")
                # Check if all symbols failed (likely rate limiting)
                all_empty = not spy_bars and not qqq_bars and not dia_bars and not iwm_bars
                if all_empty:
                    error_msg = (
                        "Failed to fetch market data from Polygon API.\n\n"
                        "This is likely due to API rate limiting.\n"
                        "The free Polygon tier allows only 5 requests per minute.\n\n"
                        "Please wait 1-2 minutes before trying again."
                    )
                else:
                    error_msg = (
                        "Failed to fetch complete market data from Polygon API.\n\n"
                        f"SPY: {len(spy_bars)} bars, QQQ: {len(qqq_bars)} bars\n"
                        "Both SPY and QQQ data are required for regime analysis."
                    )
                dialog.show_error(error_msg)
                dialog.exec()
                return
            
            dialog.set_progress(45, f"Fetched {len(spy_bars)} SPY, {len(qqq_bars)} QQQ bars...")
            QApplication.processEvents()
            
            dialog.set_progress(50, "Calculating distribution days...")
            QApplication.processEvents()
            self.logger.info("Calculating distribution days...")
            
            # Calculate distribution days
            dist_tracker = DistributionDayTracker(db_session=temp_session)
            combined = dist_tracker.get_combined_data(spy_bars, qqq_bars)
            self.logger.info(f"Distribution days - SPY: {combined.spy_count}, QQQ: {combined.qqq_count}")
            
            dialog.set_progress(60, f"SPY: {combined.spy_count} D-days, QQQ: {combined.qqq_count} D-days...")
            QApplication.processEvents()
            
            dialog.set_progress(65, "Checking Follow-Through Day status...")
            QApplication.processEvents()
            self.logger.info("Checking FTD status...")
            
            # Check FTD status
            ftd_tracker = FollowThroughDayTracker(db_session=temp_session)
            ftd_status = ftd_tracker.get_market_phase_status(
                spy_bars, qqq_bars,
                spy_d_count=combined.spy_count,
                qqq_d_count=combined.qqq_count
            )
            self.logger.info(f"Market phase: {ftd_status.phase.value}")
            
            dialog.set_progress(70, f"Market Phase: {ftd_status.phase.value}...")
            QApplication.processEvents()
            
            # Build rally histogram
            trading_days = [bar.date for bar in spy_bars]
            rally_histogram = ftd_tracker.build_rally_histogram(trading_days)
            
            # Create FTD data
            ftd_data = FTDData(
                market_phase=ftd_status.phase.value,
                in_rally_attempt=(ftd_status.spy_status.in_rally_attempt or 
                                  ftd_status.qqq_status.in_rally_attempt),
                rally_day=max(ftd_status.spy_status.rally_day, ftd_status.qqq_status.rally_day),
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
            
            dialog.set_progress(80, "Calculating composite regime score...")
            QApplication.processEvents()
            self.logger.info("Calculating regime score...")
            
            # Calculate regime
            calculator = MarketRegimeCalculator(config.get('market_regime', {}))
            
            dist_data = DistributionData(
                spy_count=combined.spy_count,
                qqq_count=combined.qqq_count,
                spy_5day_delta=combined.spy_5day_delta,
                qqq_5day_delta=combined.qqq_5day_delta,
                trend=combined.trend,
                spy_dates=combined.spy_dates,
                qqq_dates=combined.qqq_dates
            )
            
            overnight = create_overnight_data(0.0, 0.0, 0.0)  # No IBKR data
            
            score = calculator.calculate_regime(dist_data, overnight, None, ftd_data=ftd_data)
            self.logger.info(f"Regime calculated: {score.regime.value}, score: {score.composite_score}")
            
            min_exp, max_exp = calculator.get_exposure_percentage(score.regime, dist_data.total_count)
            self.logger.info(f"Exposure: {min_exp}-{max_exp}%")
            
            dialog.set_progress(90, "Saving to database...")
            QApplication.processEvents()
            self.logger.info("Saving to database...")
            
            # Save to main database
            main_session = self.db.get_new_session()
            try:
                today = date.today()
                
                # Check for existing record for today
                existing = main_session.query(MarketRegimeAlert).filter(
                    MarketRegimeAlert.date == today
                ).first()

                if existing:
                    # Prompt user before overwriting
                    from PyQt6.QtWidgets import QMessageBox

                    # Build info about existing record
                    score_str = f"{existing.composite_score:.2f}" if existing.composite_score is not None else "N/A"
                    existing_info = (
                        f"A regime record already exists for today ({today}).\n\n"
                        f"Existing Record:\n"
                        f"  • Regime: {existing.regime.value if existing.regime else 'N/A'}\n"
                        f"  • Score: {score_str}\n"
                        f"  • SPY D-days: {existing.spy_d_count}\n"
                        f"  • QQQ D-days: {existing.qqq_d_count}\n"
                        f"  • Alert sent: {'Yes (morning run)' if existing.alert_sent else 'No'}\n"
                        f"  • Created: {existing.created_at.strftime('%I:%M %p') if existing.created_at else 'Unknown'}\n\n"
                        f"Do you want to overwrite this record?"
                    )

                    reply = QMessageBox.question(
                        dialog,
                        "Overwrite Existing Record?",
                        existing_info,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No  # Default to No
                    )

                    if reply != QMessageBox.StandardButton.Yes:
                        self.logger.info("User declined to overwrite existing record")
                        dialog.set_progress(100, "Showing results (not saved)")
                        QApplication.processEvents()

                        # Calculate index stats for display
                        spy_stats = self._calculate_index_stats(spy_bars)
                        qqq_stats = self._calculate_index_stats(qqq_bars)
                        dia_stats = self._calculate_index_stats(dia_bars) if dia_bars else {}
                        iwm_stats = self._calculate_index_stats(iwm_bars) if iwm_bars else {}

                        # Build results dict (same format as normal flow)
                        results = {
                            'date': today.strftime("%A, %B %d, %Y"),
                            'spy_count': combined.spy_count,
                            'qqq_count': combined.qqq_count,
                            'spy_delta': combined.spy_5day_delta,
                            'qqq_delta': combined.qqq_5day_delta,
                            'trend': combined.trend.value if hasattr(combined.trend, 'value') else str(combined.trend),
                            'spy_dates': [d.isoformat() for d in combined.spy_dates],
                            'qqq_dates': [d.isoformat() for d in combined.qqq_dates],
                            'lookback_start': today - timedelta(days=25),
                            'market_phase': ftd_status.phase.value,
                            'in_rally_attempt': ftd_data.in_rally_attempt,
                            'rally_day': ftd_data.rally_day,
                            'has_confirmed_ftd': ftd_data.has_confirmed_ftd,
                            'composite_score': score.composite_score,
                            'regime': score.regime.value if hasattr(score.regime, 'value') else str(score.regime),
                            'exposure': f"{min_exp}-{max_exp}%",
                            'spy_stats': spy_stats,
                            'qqq_stats': qqq_stats,
                            'dia_stats': dia_stats,
                            'iwm_stats': iwm_stats,
                            'not_saved': True,  # Flag to indicate this wasn't saved
                        }

                        # Show results in dialog without saving
                        dialog.show_results(results)
                        main_session.close()
                        temp_session.close()
                        dialog.exec()
                        return

                    # User confirmed - proceed with update
                    self.logger.info("User confirmed overwrite of existing record")

                    # Update existing record
                    existing.spy_d_count = combined.spy_count
                    existing.qqq_d_count = combined.qqq_count
                    existing.spy_5day_delta = combined.spy_5day_delta
                    existing.qqq_5day_delta = combined.qqq_5day_delta
                    existing.d_day_trend = combined.trend
                    existing.spy_d_dates = ','.join(d.isoformat() for d in combined.spy_dates)
                    existing.qqq_d_dates = ','.join(d.isoformat() for d in combined.qqq_dates)
                    existing.market_phase = ftd_status.phase.value
                    existing.in_rally_attempt = ftd_data.in_rally_attempt
                    existing.rally_day = ftd_data.rally_day
                    existing.has_confirmed_ftd = ftd_data.has_confirmed_ftd
                    existing.composite_score = score.composite_score
                    existing.regime = score.regime
                    self.logger.info(f"Updated existing regime record for {today}")
                else:
                    # Create new record
                    alert = MarketRegimeAlert(
                        date=today,
                        spy_d_count=combined.spy_count,
                        qqq_d_count=combined.qqq_count,
                        spy_5day_delta=combined.spy_5day_delta,
                        qqq_5day_delta=combined.qqq_5day_delta,
                        d_day_trend=combined.trend,
                        spy_d_dates=','.join(d.isoformat() for d in combined.spy_dates),
                        qqq_d_dates=','.join(d.isoformat() for d in combined.qqq_dates),
                        market_phase=ftd_status.phase.value,
                        in_rally_attempt=ftd_data.in_rally_attempt,
                        rally_day=ftd_data.rally_day,
                        has_confirmed_ftd=ftd_data.has_confirmed_ftd,
                        composite_score=score.composite_score,
                        regime=score.regime,
                    )
                    main_session.add(alert)
                    self.logger.info(f"Created new regime record for {today}")
                
                main_session.commit()
                
            finally:
                main_session.close()
            
            dialog.set_progress(100, "Complete!")
            QApplication.processEvents()
            self.logger.info("Analysis complete, building results...")
            
            # Refresh banner from database (single source of truth)
            self._load_market_regime()
            
            # Calculate comprehensive index stats (price, day%, week%, SMAs)
            spy_stats = self._calculate_index_stats(spy_bars)
            qqq_stats = self._calculate_index_stats(qqq_bars)
            dia_stats = self._calculate_index_stats(dia_bars) if dia_bars else {}
            iwm_stats = self._calculate_index_stats(iwm_bars) if iwm_bars else {}
            
            # Update index boxes with all data
            self.regime_banner.update_index_box(
                'SPY',
                price=spy_stats['price'],
                day_pct=spy_stats['day_pct'],
                week_pct=spy_stats['week_pct'],
                sma21=spy_stats['sma21'],
                sma50=spy_stats['sma50'],
                sma200=spy_stats['sma200']
            )
            self.regime_banner.update_index_box(
                'QQQ',
                price=qqq_stats['price'],
                day_pct=qqq_stats['day_pct'],
                week_pct=qqq_stats['week_pct'],
                sma21=qqq_stats['sma21'],
                sma50=qqq_stats['sma50'],
                sma200=qqq_stats['sma200']
            )
            if dia_stats:
                self.regime_banner.update_index_box(
                    'DIA',
                    price=dia_stats.get('price'),
                    day_pct=dia_stats.get('day_pct'),
                    week_pct=dia_stats.get('week_pct'),
                    sma21=dia_stats.get('sma21'),
                    sma50=dia_stats.get('sma50'),
                    sma200=dia_stats.get('sma200')
                )
            if iwm_stats:
                self.regime_banner.update_index_box(
                    'IWM',
                    price=iwm_stats.get('price'),
                    day_pct=iwm_stats.get('day_pct'),
                    week_pct=iwm_stats.get('week_pct'),
                    sma21=iwm_stats.get('sma21'),
                    sma50=iwm_stats.get('sma50'),
                    sma200=iwm_stats.get('sma200')
                )
            
            self.logger.info(f"Index stats - SPY: {spy_stats}, QQQ: {qqq_stats}, DIA: {dia_stats}, IWM: {iwm_stats}")
            
            # Cache stats for use during regular price updates
            self._cached_spy_stats = {
                'week_pct': spy_stats['week_pct'],
                'sma21': spy_stats['sma21'],
                'sma50': spy_stats['sma50'],
                'sma200': spy_stats['sma200']
            }
            self._cached_qqq_stats = {
                'week_pct': qqq_stats['week_pct'],
                'sma21': qqq_stats['sma21'],
                'sma50': qqq_stats['sma50'],
                'sma200': qqq_stats['sma200']
            }
            if dia_stats:
                self._cached_dia_stats = {
                    'week_pct': dia_stats.get('week_pct'),
                    'sma21': dia_stats.get('sma21'),
                    'sma50': dia_stats.get('sma50'),
                    'sma200': dia_stats.get('sma200')
                }
            if iwm_stats:
                self._cached_iwm_stats = {
                    'week_pct': iwm_stats.get('week_pct'),
                    'sma21': iwm_stats.get('sma21'),
                    'sma50': iwm_stats.get('sma50'),
                    'sma200': iwm_stats.get('sma200')
                }
            
            # Build results dictionary for dialog
            results = {
                'date': today.strftime("%A, %B %d, %Y"),
                'spy_count': combined.spy_count,
                'qqq_count': combined.qqq_count,
                'spy_delta': combined.spy_5day_delta,
                'qqq_delta': combined.qqq_5day_delta,
                'trend': combined.trend.value if hasattr(combined.trend, 'value') else str(combined.trend),
                'spy_dates': [d.isoformat() for d in combined.spy_dates],
                'qqq_dates': [d.isoformat() for d in combined.qqq_dates],
                'lookback_start': today - timedelta(days=25),
                'market_phase': ftd_status.phase.value,
                'in_rally_attempt': ftd_data.in_rally_attempt,
                'rally_day': ftd_data.rally_day,
                'has_confirmed_ftd': ftd_data.has_confirmed_ftd,
                'composite_score': score.composite_score,
                'regime': score.regime.value if hasattr(score.regime, 'value') else str(score.regime),
                'exposure': f"{min_exp}-{max_exp}%",
                'spy_stats': spy_stats,
                'qqq_stats': qqq_stats,
                'dia_stats': dia_stats,
                'iwm_stats': iwm_stats,
            }
            
            self.logger.info(f"Results built: {results['regime']}, SPY={results['spy_count']}, QQQ={results['qqq_count']}")
            
            # Show results in dialog
            dialog.show_results(results)
            self.logger.info("Results dialog displayed")
            
            self.status_bar.showMessage(
                f"Market Regime: {score.regime.value} | "
                f"SPY: {combined.spy_count} D-days | QQQ: {combined.qqq_count} D-days | "
                f"Exposure: {min_exp}-{max_exp}%"
            )
            
            self.logger.info(
                f"Market regime analysis complete: {score.regime.value}, "
                f"SPY={combined.spy_count}, QQQ={combined.qqq_count}"
            )
            
        except Exception as e:
            self.logger.error(f"Market regime analysis failed: {e}", exc_info=True)
            dialog.show_error(str(e))
            self.status_bar.showMessage("Market regime analysis failed")
        
        # Keep dialog open for user to review
        dialog.exec()
    
    def _on_windows_service_state_changed(self, state: str):
        """Handle Windows service state changes from ServiceStatusBar."""
        self.logger.info(f"Windows service state changed: {state}")
        # The ServiceStatusBar handles its own UI updates
        # This handler is for any additional actions needed when service state changes
    
    def _update_prices(self):
        """Start background price update from IBKR."""
        if not self.ibkr_connected or not self.ibkr_client:
            return
        
        # Skip if update already in progress
        if self.price_update_in_progress:
            self.logger.debug("Price update already in progress, skipping...")
            return
        
        # Ensure old thread is cleaned up before creating new one
        if self.price_thread is not None:
            if self.price_thread.isRunning():
                self.logger.debug("Waiting for previous price thread to finish...")
                self.price_thread.quit()
                self.price_thread.wait(2000)
            self.price_thread = None
            self.price_worker = None
        
        self.logger.debug("Starting price update...")
        
        # Collect symbols from database (fast operation, OK in main thread)
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            positions = repos.positions.get_all(include_closed=False)
            symbols = list(set(pos.symbol for pos in positions))
            
            # Always include index ETFs for the banner
            for idx in ['SPY', 'QQQ', 'DIA', 'IWM']:
                if idx not in symbols:
                    symbols.append(idx)
        finally:
            session.close()
        
        if not symbols:
            return
        
        # Create worker and thread for IBKR fetch (slow operation)
        self.price_update_in_progress = True
        
        self.price_thread = QThread()
        self.price_worker = PriceUpdateWorker(self.ibkr_client, symbols)
        self.price_worker.moveToThread(self.price_thread)
        
        # Connect signals
        self.price_thread.started.connect(self.price_worker.run)
        self.price_worker.finished.connect(self._on_prices_received)
        self.price_worker.error.connect(self._on_price_error)
        self.price_worker.finished.connect(self.price_thread.quit)
        self.price_worker.error.connect(self.price_thread.quit)
        self.price_thread.finished.connect(self._on_price_thread_finished)
        
        # Start the thread
        self.price_thread.start()
    
    def _on_prices_received(self, prices: Dict):
        """Handle prices received from background worker."""
        self.logger.debug(f"Received prices for {len(prices)} symbols")
        
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            positions = repos.positions.get_all(include_closed=False)
            
            # Update positions
            updated_count = 0
            for pos in positions:
                if pos.symbol in prices:
                    price_data = prices[pos.symbol]
                    last_price = price_data.get('last') or price_data.get('close')
                    
                    if last_price and last_price > 0:
                        repos.positions.update_price(pos, last_price)
                        updated_count += 1
            
            session.commit()
            
            # Refresh the board
            self._load_positions()
            
            # Update market regime banner with index prices
            self._update_market_banner(prices)
            
            self.status_bar.showMessage(f"Updated {updated_count} prices at {datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            self.logger.error(f"Error processing prices: {e}")
        finally:
            session.close()
    
    def _on_price_error(self, error_msg: str):
        """Handle error from price update worker."""
        self.logger.error(f"Price update error: {error_msg}")
        self.status_bar.showMessage(f"Price update error: {error_msg}")
    
    def _on_price_thread_finished(self):
        """Clean up after price thread finishes."""
        self.price_update_in_progress = False
        
        # Clean up worker and thread safely
        worker = self.price_worker
        thread = self.price_thread
        self.price_worker = None
        self.price_thread = None
        
        if worker:
            try:
                worker.deleteLater()
            except RuntimeError:
                pass  # Already deleted
        if thread:
            try:
                thread.deleteLater()
            except RuntimeError:
                pass  # Already deleted
    
    def _update_market_banner(self, prices: Dict):
        """Update market regime banner with index prices and day change from IBKR."""
        for symbol in ['SPY', 'QQQ', 'DIA', 'IWM']:
            price_data = prices.get(symbol, {})
            last_price = price_data.get('last') or price_data.get('close')
            prev_close = price_data.get('close') or price_data.get('previousClose')
            
            # Calculate day change if we have both prices
            day_pct = None
            if last_price and prev_close and prev_close > 0:
                day_pct = ((last_price - prev_close) / prev_close) * 100
            
            # Get cached SMA/week data if available (set by regime analysis)
            cached = getattr(self, f'_cached_{symbol.lower()}_stats', {})
            
            # Update the index box
            self.regime_banner.update_index_box(
                symbol,
                price=last_price,
                day_pct=day_pct,
                week_pct=cached.get('week_pct'),
                sma21=cached.get('sma21'),
                sma50=cached.get('sma50'),
                sma200=cached.get('sma200')
            )
    
    def _on_import(self):
        """Import from Excel."""
        from PyQt6.QtWidgets import QFileDialog
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import from Excel",
            "",
            "Excel Files (*.xlsx *.xls)"
        )
        
        if file_path:
            try:
                from migration.excel_importer import ExcelImporter
                
                importer = ExcelImporter(file_path, self.db.db_path)
                stats = importer.run(clear_existing=False)
                
                self._load_positions()
                
                QMessageBox.information(
                    self,
                    "Import Complete",
                    f"Imported {stats['imported']} positions\n"
                    f"Skipped: {stats['skipped']}\n"
                    f"Errors: {stats['errors']}"
                )
            except Exception as e:
                QMessageBox.warning(self, "Import Error", str(e))
    
    def _on_export(self):
        """Export to Excel."""
        QMessageBox.information(self, "Export", "Export to Excel (coming soon)")
    
    def _open_table_view(self):
        """Open the spreadsheet view of all positions."""
        session = self.db.get_new_session()
        
        try:
            # Create the view if it doesn't exist or was closed
            if self._table_view is None:
                self._table_view = PositionTableView(session, self)
                
                # Connect the edit signal to handle updates
                self._table_view.position_edited.connect(self._on_position_edited_from_table)
            else:
                # Refresh data if window already exists
                self._table_view._load_data()
            
            self._table_view.show()
            self._table_view.raise_()
            self._table_view.activateWindow()
            
            self.logger.info("Opened Position Table View")
            
        except Exception as e:
            session.close()
            self.logger.error(f"Failed to open table view: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open database view: {e}")
    
    def _on_position_edited_from_table(self, position_id: int, updated_data: dict):
        """Handle position edits from the table view."""
        # Check if this is a delete notification - just refresh
        if updated_data.get('deleted'):
            self.logger.info(f"Position {position_id} was deleted from table view")
            self._load_positions()
            return

        session = self.db.get_new_session()

        try:
            from canslim_monitor.data.models import Position

            position = session.query(Position).filter_by(id=position_id).first()
            if position:
                for key, value in updated_data.items():
                    if hasattr(position, key) and key != 'id':
                        setattr(position, key, value)

                session.commit()
                self.logger.info(f"Updated position {position.symbol} (ID: {position_id}) from table view")

                # Refresh the kanban view to show changes
                self._load_positions()

        except Exception as e:
            session.rollback()
            self.logger.error(f"Failed to update position from table view: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update position: {e}")
        finally:
            session.close()
    
    def _on_sync_sheets(self, force: bool = False):
        """Trigger Google Sheets sync.

        Args:
            force: If True, sync all active positions regardless of needs_sheet_sync flag
        """
        from canslim_monitor.integrations.sheets_sync import SheetsSync

        # Load config
        sheets_config = self.config.get('google_sheets', {})

        # Validate config
        if not sheets_config.get('enabled'):
            QMessageBox.warning(self, "Sync Disabled",
                "Google Sheets sync is disabled. Enable in config.yaml.")
            return

        if not sheets_config.get('spreadsheet_id') or not sheets_config.get('credentials_path'):
            QMessageBox.warning(self, "Config Missing",
                "Please configure spreadsheet_id and credentials_path in user_config.yaml")
            return

        # Show status
        sync_type = "Force syncing all" if force else "Syncing"
        self.statusBar().showMessage(f"{sync_type} to Google Sheets...")
        QApplication.processEvents()

        try:
            # Create sync service
            sync = SheetsSync(self.config, self.db)

            # Run sync
            result = sync.sync_all(force=force)

            if result.success:
                force_text = " (forced)" if force else ""
                msg = (f"Sync complete{force_text}:\n"
                       f"• {result.updated} updated\n"
                       f"• {result.inserted} inserted\n"
                       f"• {result.deleted} removed (closed positions)")
                self.statusBar().showMessage(
                    f"Sync: {result.updated} updated, {result.inserted} new, {result.deleted} removed",
                    5000
                )
                QMessageBox.information(self, "Sync Complete", msg)
            else:
                errors = "\n".join(result.error_messages[:5])
                QMessageBox.warning(self, "Sync Failed", f"Sync failed:\n{errors}")
                self.statusBar().showMessage("Sync failed", 5000)

        except Exception as e:
            QMessageBox.critical(self, "Sync Error", f"Error: {str(e)}")
            self.statusBar().showMessage("Sync error", 5000)
            self.logger.error(f"Sync error: {e}", exc_info=True)

    def _auto_sync_check(self):
        """Automatically sync positions that need syncing (background timer)."""
        from canslim_monitor.integrations.sheets_sync import SheetsSync
        from canslim_monitor.data.repositories import RepositoryManager

        # Check if any positions need syncing
        try:
            session = self.db.get_new_session()
            repos = RepositoryManager(session)
            positions_needing_sync = repos.positions.get_needing_sync()
            session.close()

            if not positions_needing_sync:
                return  # Nothing to sync

            # Run sync silently in background
            self.logger.info(f"Auto-sync: {len(positions_needing_sync)} positions need syncing")

            sync = SheetsSync(self.config, self.db)
            result = sync.sync_all()

            if result.success:
                self.logger.info(f"Auto-sync complete: {result.updated} updated, "
                               f"{result.inserted} inserted, {result.deleted} deleted")
                # Brief status message (don't interrupt user)
                self.statusBar().showMessage(
                    f"Auto-synced: {result.updated + result.inserted} positions, {result.deleted} removed",
                    3000
                )
            else:
                self.logger.error(f"Auto-sync failed: {result.error_messages}")

        except Exception as e:
            self.logger.error(f"Auto-sync error: {e}", exc_info=True)

    def _on_weekly_report(self):
        """Generate weekly watchlist report."""
        from canslim_monitor.gui.dialogs.report_generator_dialog import ReportGeneratorDialog

        try:
            dialog = ReportGeneratorDialog(self.config, self.db, parent=self)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Report Error", f"Error opening report dialog: {str(e)}")
            self.logger.error(f"Report dialog error: {e}", exc_info=True)

    def _on_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About CANSLIM Position Manager",
            "CANSLIM Position Manager v1.0\n\n"
            "A Kanban-style position tracker based on\n"
            "William O'Neil's CANSLIM methodology.\n\n"
            "Built for managing the complete trade lifecycle\n"
            "from watchlist to closed positions."
        )
    
    def closeEvent(self, event):
        """Handle window close - clean up resources."""
        self.logger.info("Closing window...")
        
        # Stop service if running
        if self.ibkr_connected:
            self._on_stop_service()
        
        # Clean up database
        if self.db:
            self.db.close()
        
        event.accept()


def launch_gui(db_path: str):
    """
    Launch the Kanban GUI application.
    
    FIXED: Uses proper file-based logging via LoggingManager and loads config correctly.
    """
    import sys
    
    # =========================================================================
    # STEP 1: Set working directory to C:\Trading for proper config loading
    # =========================================================================
    TRADING_DIR = r"C:\Trading"
    if os.path.exists(TRADING_DIR):
        os.chdir(TRADING_DIR)
    
    # =========================================================================
    # STEP 2: Load configuration FIRST (before setting up logging)
    # =========================================================================
    config = {}
    config_file = None
    
    try:
        from canslim_monitor.utils.config import load_config
        
        # Search for config file in priority order
        config_paths = [
            os.path.join(TRADING_DIR, 'canslim_monitor', 'user_config.yaml'),
            os.path.join(TRADING_DIR, 'user_config.yaml'),
            os.path.join(os.getcwd(), 'canslim_monitor', 'user_config.yaml'),
            os.path.join(os.getcwd(), 'user_config.yaml'),
        ]
        
        for path in config_paths:
            if os.path.exists(path):
                config_file = path
                break
        
        # Load config (pass explicit path if found)
        if config_file:
            config = load_config(config_file)
        else:
            config = load_config()
            
    except Exception as e:
        print(f"Warning: Failed to load config: {e}")
        import traceback
        traceback.print_exc()
    
    # =========================================================================
    # STEP 3: Set up FILE-BASED logging using LoggingManager
    # =========================================================================
    log_dir = config.get('logging', {}).get('base_dir', r'C:\Trading\canslim_monitor\logs')
    
    try:
        from canslim_monitor.utils.logging import setup_logging as setup_file_logging, get_logger
        
        # Ensure log directory exists
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize file logging with LoggingManager
        setup_file_logging(
            log_dir=log_dir,
            console_level=logging.INFO,
            retention_days=30
        )
        
        # Get GUI-specific logger (writes to logs/gui/gui_YYYY-MM-DD.log)
        logger = get_logger('gui')
        
    except Exception as e:
        # Fallback to basic console logging if LoggingManager fails
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        )
        logger = logging.getLogger('canslim.gui')
        logger.warning(f"Using fallback console logging: {e}")
        import traceback
        traceback.print_exc()
    
    # =========================================================================
    # STEP 4: Log startup information for debugging
    # =========================================================================
    logger.info("=" * 60)
    logger.info("CANSLIM Monitor GUI Starting")
    logger.info("=" * 60)
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Config file: {config_file or 'not found, using defaults'}")
    logger.info(f"Log directory: {log_dir}")
    logger.info(f"Database: {db_path}")
    
    # Log IBKR config for debugging connection issues
    ibkr_config = config.get('ibkr', {})
    logger.info(f"IBKR config: host={ibkr_config.get('host', '127.0.0.1')}, "
                f"port={ibkr_config.get('port', 4001)}, "
                f"client_id_base={ibkr_config.get('client_id_base', 20)}")
    
    # =========================================================================
    # STEP 5: Initialize database and launch GUI
    # =========================================================================
    db = DatabaseManager(db_path)
    db.initialize()
    logger.info("Database initialized")
    
    # Create and run application
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = KanbanMainWindow(db)
    window.show()
    
    logger.info("GUI window created and displayed")
    
    sys.exit(app.exec())


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python kanban_window.py <database_path>")
        sys.exit(1)
    
    launch_gui(sys.argv[1])
