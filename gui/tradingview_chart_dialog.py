"""
CANSLIM Monitor - TradingView Lightweight Charts Dashboard
===========================================================
Professional candlestick charting with TradingView's open-source
Lightweight Charts library via PyQt6 WebEngine.

Provides candlestick OHLCV + MA overlays on the main chart,
with synced indicator subcharts for D-Days, Scores, F&G, and VIX.

Reuses DataFetchWorker and config constants from sentiment_chart_dialog.
"""

import logging
from datetime import date, timedelta
from typing import Optional, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QProgressBar,
)
from PyQt6.QtCore import Qt

logger = logging.getLogger('canslim.gui')

# Try importing lightweight-charts QtChart
# The library's import chain (PyQt5 → PySide6 → PyQt6) can fail inside a running
# PyQt6 app. We force-patch PyQt6 WebEngine into the module if needed.
LIGHTWEIGHT_CHARTS_AVAILABLE = False
try:
    import pandas as pd
    import lightweight_charts.widgets as _lcw

    if _lcw.QWebEngineView is None:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebChannel import QWebChannel
        from PyQt6.QtCore import QObject, pyqtSlot as Slot, QUrl, QTimer

        _lcw.QWebEngineView = QWebEngineView
        _lcw.using_pyside6 = False

        class _Bridge(QObject):
            def __init__(self, chart):
                super().__init__()
                self.win = chart.win

            @Slot(str)
            def callback(self, message):
                _lcw.emit_callback(self.win, message)

        _lcw.Bridge = _Bridge

    from lightweight_charts.widgets import QtChart
    LIGHTWEIGHT_CHARTS_AVAILABLE = True
except Exception as e:
    print(f"[TradingView] lightweight-charts init failed: {type(e).__name__}: {e}")
    logger.warning(f"lightweight-charts not available: {e}")
    LIGHTWEIGHT_CHARTS_AVAILABLE = False

# Reuse from sentiment_chart_dialog
from canslim_monitor.gui.sentiment_chart_dialog import (
    DataFetchWorker, PANEL_DEFS, MA_DEFS, REGIME_FIELDS,
    _calc_sma, _calc_ema, PHASE_COLORS,
)


def daily_bars_to_dataframe(bars) -> 'pd.DataFrame':
    """Convert List[DailyBar] to pandas DataFrame for lightweight-charts."""
    # Safety-net: clean bars before chart rendering (primary cleaning is in _fetch_bars)
    try:
        from canslim_monitor.utils.data_cleaner import clean_daily_bars
        bars = clean_daily_bars(bars)
    except Exception:
        pass  # Don't block chart rendering if cleaner fails

    rows = []
    for bar in bars:
        rows.append({
            'time': bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': getattr(bar, 'volume', 0) or 0,
        })
    return pd.DataFrame(rows)


def regime_to_line_dataframe(regime_data: list, field: str, col_name: str = 'value') -> 'pd.DataFrame':
    """Convert regime dicts to 2-column DataFrame (time, <col_name>) for line series.
    col_name must match the Line's name= parameter for lightweight-charts."""
    rows = []
    for d in regime_data:
        val = d.get(field)
        if val is not None:
            dt = d['date']
            time_str = dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)
            rows.append({'time': time_str, col_name: float(val)})
    return pd.DataFrame(rows)


class TradingViewChartDialog(QDialog):
    """TradingView-style candlestick chart with indicator subcharts."""

    def __init__(self, db_session_factory=None, parent=None):
        super().__init__(parent)
        self.db_session_factory = db_session_factory
        self._symbols = ["SPY"]
        self._worker = None
        self._price_data = {}
        self._regime_data = []
        self._visible_start = None
        self._chart = None
        self._subcharts = {}
        self._lines = {}

        try:
            from canslim_monitor.utils.config import load_config
            self._config = load_config()
        except Exception:
            self._config = {}

        self.setWindowTitle("TradingView Market Chart")
        self.setMinimumSize(1100, 850)
        self.resize(1200, 950)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Controls row
        row = QHBoxLayout()
        row.addWidget(QLabel("Symbol:"))
        self._symbol_input = QLineEdit("SPY")
        self._symbol_input.setFixedWidth(100)
        self._symbol_input.setPlaceholderText("SPY")
        self._symbol_input.returnPressed.connect(self._on_symbol_changed)
        row.addWidget(self._symbol_input)

        self._load_btn = QPushButton("Load")
        self._load_btn.clicked.connect(self._on_symbol_changed)
        row.addWidget(self._load_btn)

        row.addSpacing(15)

        # Range buttons — zoom controls (no data reload)
        self._range_buttons = {}
        self._visible_days = 90
        for days, label in [(30, "30d"), (60, "60d"), (90, "90d"), (180, "6m"), (365, "1y"), (730, "2y"), (1095, "3y"), (1460, "4y")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(days == 90)
            btn.clicked.connect(lambda checked, d=days: self._set_visible_range_days(d))
            self._range_buttons[days] = btn
            row.addWidget(btn)

        row.addStretch()

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        row.addWidget(self._status_label)

        layout.addLayout(row)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setFixedHeight(3)
        layout.addWidget(self._progress_bar)

        # Chart container - we'll add the QtChart webview here after data loads
        self._chart_container = QVBoxLayout()
        layout.addLayout(self._chart_container, stretch=1)

        # Placeholder label until chart loads
        self._placeholder = QLabel("Loading chart data...")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #666; font-size: 14px; background: #1a1a2e; padding: 40px;")
        self._chart_container.addWidget(self._placeholder)

    def _on_symbol_changed(self):
        text = self._symbol_input.text().strip().upper()
        if text:
            self._symbols = [text.split(',')[0].strip()]
            self._load_data()

    def _set_visible_range_days(self, days: int):
        """Re-trim and re-populate chart data for the selected range."""
        for d, btn in self._range_buttons.items():
            btn.setChecked(d == days)
        self._visible_days = days
        self._visible_start = date.today() - timedelta(days=days)
        if self._chart and self._price_data:
            self._populate_chart()

    def _load_data(self):
        if self._worker and self._worker.isRunning():
            return

        self._progress_bar.setVisible(True)
        self._load_btn.setEnabled(False)
        self._status_label.setText(f"Loading {self._symbols[0]}...")

        # Fetch a large dataset — user can scroll left through all of it.
        # visible_start = 90 days ago (initial view), but we fetch ~2 years
        # of price data so the user has plenty of history to scroll through.
        end = date.today()
        start = end - timedelta(days=self._visible_days)
        extra = 500  # ~2 years of trading days beyond visible start

        self._worker = DataFetchWorker(
            self._symbols, start, end, self._config, self.db_session_factory,
            extra_lookback=extra
        )
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_data_error)
        self._worker.progress.connect(lambda msg: self._status_label.setText(msg))
        self._worker.start()

    def _on_data_loaded(self, result: dict):
        self._load_btn.setEnabled(True)
        self._progress_bar.setVisible(False)

        self._symbols = result.get('symbols', self._symbols)
        self._price_data = result.get('price_data', {})
        self._regime_data = result.get('regime_data', [])
        self._visible_start = result.get('visible_start')

        parts = []
        total_bars = sum(len(bars) for bars in self._price_data.values())
        if total_bars:
            parts.append(f"Price: {total_bars} bars")
        elif 'price_error' in result:
            parts.append(f"Price error: {result['price_error']}")
        if self._regime_data:
            parts.append(f"Regime: {len(self._regime_data)} days")
        elif 'regime_error' in result:
            parts.append(f"Regime: {result['regime_error']}")
        self._status_label.setText(" | ".join(parts) if parts else "No data")

        self._build_chart()
        self._populate_chart()

    def _on_data_error(self, error_msg: str):
        self._progress_bar.setVisible(False)
        self._load_btn.setEnabled(True)
        self._status_label.setText(f"Error: {error_msg}")

    def _build_chart(self):
        """Create the QtChart with subcharts."""
        if not LIGHTWEIGHT_CHARTS_AVAILABLE:
            return

        # Remove old chart/placeholder
        if self._placeholder:
            self._placeholder.setParent(None)
            self._placeholder = None
        if self._chart:
            webview = self._chart.get_webview()
            if webview:
                webview.setParent(None)
            self._chart = None
            self._subcharts = {}
            self._lines = {}

        # Create main chart — inner_height < 1.0 leaves room for bottom subcharts
        self._chart = QtChart(inner_height=0.4)

        # Dark theme
        self._chart.layout(background_color='#1a1a2e', text_color='#d1d4dc', font_size=11)
        self._chart.grid(color='rgba(255, 255, 255, 0.06)')
        self._chart.candle_style(
            up_color='#26a69a', down_color='#ef5350',
            wick_up_color='#26a69a', wick_down_color='#ef5350',
        )
        self._chart.volume_config(
            up_color='rgba(38, 166, 154, 0.4)',
            down_color='rgba(239, 83, 80, 0.4)',
        )
        self._chart.legend(visible=True, font_size=11, font_family='Consolas')
        self._chart.crosshair(mode='normal')
        self._chart.time_scale(right_offset=5)
        self._chart.price_scale(minimum_width=70)

        # MA line overlays on main chart
        for ma_key in ['ema21', 'sma50', 'sma200']:
            mdef = MA_DEFS[ma_key]
            style = 'dashed' if mdef['type'] == 'ema' else 'dotted'
            line = self._chart.create_line(
                name=mdef['label'], color=mdef['color'],
                style=style, width=2,
                price_line=False, price_label=False,
            )
            self._lines[ma_key] = line

        # Helper to create a styled subchart
        def _make_sub(height, label):
            sub = self._chart.create_subchart(
                position='bottom', width=1, height=height, sync=True
            )
            sub.layout(background_color='#1a1a2e', text_color='#d1d4dc', font_size=10)
            sub.grid(color='rgba(255, 255, 255, 0.06)')
            sub.legend(visible=True, ohlc=False, percent=False, font_size=10, text=label)
            sub.time_scale(right_offset=5)  # Match main chart right_offset
            sub.price_scale(minimum_width=70)  # Match main chart for vertical alignment
            return sub

        # Subcharts (synced to main, stacked vertically)
        # Hide time axis on all except the bottom chart (VIX) so they
        # share the main chart's time scale and can't scroll independently
        ddays_chart = _make_sub(0.15, 'D-Days')
        ddays_chart.time_scale(visible=False)
        self._subcharts['ddays'] = ddays_chart

        scores_chart = _make_sub(0.15, 'Scores')
        scores_chart.time_scale(visible=False)
        self._subcharts['scores'] = scores_chart

        fg_chart = _make_sub(0.15, 'F&G')
        fg_chart.time_scale(visible=False)
        self._subcharts['fg'] = fg_chart

        vix_chart = _make_sub(0.15, 'VIX')
        self._subcharts['vix'] = vix_chart

        # Create line series on subcharts
        self._lines['spy_ddays'] = ddays_chart.create_line(
            name='SPY', color='#00BFFF', width=2, price_line=False, price_label=False,
        )
        self._lines['qqq_ddays'] = ddays_chart.create_line(
            name='QQQ', color='#FF8C00', width=2, price_line=False, price_label=False,
        )

        self._lines['composite'] = scores_chart.create_line(
            name='Composite', color='#FFD700', width=2, price_line=False, price_label=False,
        )
        self._lines['entry_risk'] = scores_chart.create_line(
            name='Entry Risk', color='#00BFFF', width=2, price_line=False, price_label=False,
        )

        self._lines['fg'] = fg_chart.create_line(
            name='F&G', color='#FFD700', width=2, price_line=False, price_label=False,
        )

        self._lines['vix'] = vix_chart.create_line(
            name='VIX', color='#FF6B6B', width=2, price_line=False, price_label=False,
        )

        # Force-sync main chart zoom/scroll to ALL subcharts permanently.
        # The library's built-in sync=True handles mouseover-driven swapping,
        # but this explicit JS subscription ensures reliable propagation.
        # (The .get() console errors are cosmetic — the sync works correctly.)
        main_id = self._chart.id
        for sub in self._subcharts.values():
            sub_id = sub.id
            self._chart.run_script(f'''
                {main_id}.chart.timeScale().subscribeVisibleLogicalRangeChange(function(range) {{
                    if (range) {{
                        {sub_id}.chart.timeScale().setVisibleLogicalRange(range);
                    }}
                }});
            ''')

        # Add to layout
        webview = self._chart.get_webview()
        self._chart_container.addWidget(webview)

    def _populate_chart(self):
        """Set data on chart and all subcharts.

        Trims displayed candle/MA data to visible_start so the main chart's
        time range matches the subchart regime data (~same bar count).
        MAs are still calculated on the full dataset for accuracy.
        """
        if not LIGHTWEIGHT_CHARTS_AVAILABLE or not self._chart:
            return

        symbol = self._symbols[0]
        bars = self._price_data.get(symbol, [])
        if not bars:
            self._status_label.setText("No price data available")
            return

        # Calculate MAs on FULL data for accuracy (need lookback for 200 SMA)
        all_closes = [bar.close for bar in bars]
        all_times = [bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date) for bar in bars]

        # Trim candle bars to visible range only
        vis_start = self._visible_start
        if vis_start:
            visible_bars = [b for b in bars if b.date >= vis_start]
        else:
            visible_bars = bars

        if not visible_bars:
            visible_bars = bars[-90:]  # fallback

        vis_df = daily_bars_to_dataframe(visible_bars)
        self._chart.set(vis_df)

        # Trim cutoff for MAs
        vis_start_str = visible_bars[0].date.isoformat() if visible_bars else None

        # Calculate MAs on full data, trim to visible range for display
        for ma_key in ['ema21', 'sma50', 'sma200']:
            mdef = MA_DEFS[ma_key]
            line = self._lines.get(ma_key)
            if not line:
                continue

            if mdef['type'] == 'ema':
                ma_vals = _calc_ema(all_closes, mdef['period'])
            else:
                ma_vals = _calc_sma(all_closes, mdef['period'])

            ma_rows = []
            col_name = mdef['label']
            for t, v in zip(all_times, ma_vals):
                if v is not None and (not vis_start_str or t >= vis_start_str):
                    ma_rows.append({'time': t, col_name: round(v, 2)})

            if ma_rows:
                line.set(pd.DataFrame(ma_rows))

        # Populate subcharts from regime data
        if not self._regime_data:
            return

        spy_df = regime_to_line_dataframe(self._regime_data, 'spy_d_count', 'SPY')
        qqq_df = regime_to_line_dataframe(self._regime_data, 'qqq_d_count', 'QQQ')
        if not spy_df.empty:
            self._lines['spy_ddays'].set(spy_df)
        if not qqq_df.empty:
            self._lines['qqq_ddays'].set(qqq_df)

        comp_df = regime_to_line_dataframe(self._regime_data, 'composite_score', 'Composite')
        risk_df = regime_to_line_dataframe(self._regime_data, 'entry_risk_score', 'Entry Risk')
        if not comp_df.empty:
            self._lines['composite'].set(comp_df)
        if not risk_df.empty:
            self._lines['entry_risk'].set(risk_df)

        fg_df = regime_to_line_dataframe(self._regime_data, 'fear_greed_score', 'F&G')
        if not fg_df.empty:
            self._lines['fg'].set(fg_df)

        vix_df = regime_to_line_dataframe(self._regime_data, 'vix_close', 'VIX')
        if not vix_df.empty:
            self._lines['vix'].set(vix_df)

        self._add_zone_lines()
        self._add_phase_markers()

    def _add_zone_lines(self):
        """Add horizontal threshold lines to subcharts."""
        # D-Day danger thresholds
        ddays = self._subcharts.get('ddays')
        if ddays:
            ddays.horizontal_line(5, color='rgba(255, 193, 7, 0.6)', width=1, style='dotted', text='Caution')
            ddays.horizontal_line(7, color='rgba(220, 53, 69, 0.6)', width=1, style='dotted', text='Danger')

        # F&G zone boundaries
        fg = self._subcharts.get('fg')
        if fg:
            fg.horizontal_line(25, color='rgba(220, 53, 69, 0.4)', width=1, style='dotted', text='Extreme Fear')
            fg.horizontal_line(45, color='rgba(253, 126, 20, 0.4)', width=1, style='dotted', text='Fear')
            fg.horizontal_line(55, color='rgba(255, 193, 7, 0.4)', width=1, style='dotted', text='Neutral')
            fg.horizontal_line(75, color='rgba(40, 167, 69, 0.4)', width=1, style='dotted', text='Greed')

        # VIX thresholds
        vix = self._subcharts.get('vix')
        if vix:
            vix.horizontal_line(12, color='rgba(40, 167, 69, 0.4)', width=1, style='dotted', text='Low')
            vix.horizontal_line(20, color='rgba(255, 193, 7, 0.4)', width=1, style='dotted', text='Elevated')
            vix.horizontal_line(30, color='rgba(220, 53, 69, 0.4)', width=1, style='dotted', text='High')

    def _add_phase_markers(self):
        """Add vertical spans for market phase changes on main chart."""
        if not self._regime_data or not self._chart:
            return

        # Group consecutive dates by phase
        segments = []
        current_phase = None
        seg_start = None
        for d in self._regime_data:
            phase = d.get('market_phase', '')
            dt = d['date']
            time_str = dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)
            if phase != current_phase:
                if current_phase and seg_start is not None:
                    segments.append((seg_start, time_str, current_phase))
                current_phase = phase
                seg_start = time_str
        # Close last segment
        if current_phase and seg_start is not None:
            last_dt = self._regime_data[-1]['date']
            last_str = last_dt.isoformat() if hasattr(last_dt, 'isoformat') else str(last_dt)
            segments.append((seg_start, last_str, current_phase))

        # Phase -> rgba color (more opaque than pyqtgraph since these are pure CSS)
        phase_colors = {
            'CONFIRMED_UPTREND': 'rgba(40, 167, 69, 0.08)',
            'RALLY_ATTEMPT': 'rgba(255, 193, 7, 0.08)',
            'UPTREND_UNDER_PRESSURE': 'rgba(253, 126, 20, 0.08)',
            'CORRECTION': 'rgba(220, 53, 69, 0.08)',
        }

        for start_str, end_str, phase in segments:
            color = phase_colors.get(phase)
            if color:
                self._chart.vertical_span(start_str, end_str, color=color)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)
