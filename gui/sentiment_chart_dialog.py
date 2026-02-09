"""
CANSLIM Monitor - Market Sentiment Dashboard
==============================================
Multi-panel interactive chart with dynamic panel selection.

Top panel: Daily close prices for multiple symbols (from Massive/Polygon API)
Lower panels: User-selectable regime metrics from DB:
  - D-Days (SPY/QQQ distribution day counts)
  - Scores (Composite + Entry Risk + Market Phase backgrounds)
  - Fear & Greed (CNN F&G with zone bands)
  - Futures (ES/NQ/YM overnight change %)
  - D-Day Deltas (5-day change in SPY/QQQ D-day counts)

Uses pyqtgraph for interactive charts, falls back to tables otherwise.
"""

import logging
import time as _time
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QWidget, QLineEdit, QProgressBar, QSplitter, QDateEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtGui import QFont, QColor

logger = logging.getLogger('canslim.gui')

# Try to import pyqtgraph
try:
    import pyqtgraph as pg
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    PYQTGRAPH_AVAILABLE = False

# Color palette for multiple symbols
SYMBOL_COLORS = ['#00BFFF', '#FF6B6B', '#50C878', '#DA70D6', '#FF8C00', '#00CED1']

# Market phase colors (for background regions on score panel)
PHASE_COLORS = {
    'CONFIRMED_UPTREND': '#28A74518',
    'RALLY_ATTEMPT': '#FFC10718',
    'UPTREND_UNDER_PRESSURE': '#FD7E1418',
    'CORRECTION': '#DC354518',
}

# Panel definitions for dynamic selection
# Each panel: (key, label, lines_config, y_range, special)
# lines_config: list of (field_name, display_name, color)
PANEL_DEFS = {
    'ddays': {
        'label': 'D-Days',
        'lines': [
            ('spy_d_count', 'SPY', '#00BFFF'),
            ('qqq_d_count', 'QQQ', '#FF8C00'),
        ],
        'y_range': (0, 10),
        'y_label': 'Count',
    },
    'scores': {
        'label': 'Scores',
        'lines': [
            ('composite_score', 'Composite', '#FFD700'),
            ('entry_risk_score', 'Entry Risk', '#00BFFF'),
        ],
        'y_range': None,
        'y_label': 'Score',
        'phase_bg': True,  # Show market phase backgrounds
    },
    'fg': {
        'label': 'F&&G',
        'lines': [
            ('fear_greed_score', 'F&G', '#FFD700'),
        ],
        'y_range': (0, 100),
        'y_label': 'Score',
        'zone_bands': True,  # F&G zone bands
    },
    'futures': {
        'label': 'Futures',
        'lines': [
            ('es_change_pct', 'ES', '#00BFFF'),
            ('nq_change_pct', 'NQ', '#FF8C00'),
            ('ym_change_pct', 'YM', '#50C878'),
        ],
        'y_range': None,
        'y_label': 'Change %',
    },
    'deltas': {
        'label': 'D-Day Deltas',
        'lines': [
            ('spy_5day_delta', 'SPY 5d', '#00BFFF'),
            ('qqq_5day_delta', 'QQQ 5d', '#FF8C00'),
        ],
        'y_range': None,
        'y_label': 'Delta',
    },
    'vix': {
        'label': 'VIX',
        'lines': [
            ('vix_close', 'VIX', '#FF6B6B'),
        ],
        'y_range': (0, 50),
        'y_label': 'VIX',
        'vix_bands': True,
    },
}

# Default panels shown on startup
DEFAULT_PANELS = ['ddays', 'scores', 'fg']

# Moving average definitions for IBD methodology (key, label, period, type, color, dash)
MA_DEFS = {
    'ema21': {'label': '21 EMA', 'period': 21, 'type': 'ema', 'color': '#00CED1', 'dash': [4, 4]},
    'sma50': {'label': '50 SMA', 'period': 50, 'type': 'sma', 'color': '#FF4500', 'dash': [6, 3]},
    'sma200': {'label': '200 SMA', 'period': 200, 'type': 'sma', 'color': '#32CD32', 'dash': [8, 4]},
}

# All regime fields we need to query
REGIME_FIELDS = [
    'date', 'spy_d_count', 'qqq_d_count', 'composite_score',
    'entry_risk_score', 'market_phase', 'fear_greed_score',
    'es_change_pct', 'nq_change_pct', 'ym_change_pct',
    'spy_5day_delta', 'qqq_5day_delta', 'vix_close',
]


def _date_to_epoch(d) -> float:
    """Convert date or datetime to epoch seconds."""
    if isinstance(d, datetime):
        return d.timestamp()
    return _time.mktime(d.timetuple())


def _calc_sma(closes: List[float], period: int) -> List[Optional[float]]:
    """Calculate Simple Moving Average. Returns list same length as closes."""
    result = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1:i + 1]) / period
    return result


def _calc_ema(closes: List[float], period: int) -> List[Optional[float]]:
    """Calculate Exponential Moving Average. Returns list same length as closes."""
    result: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period:
        return result
    # Seed with SMA
    result[period - 1] = sum(closes[:period]) / period
    multiplier = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        result[i] = closes[i] * multiplier + result[i - 1] * (1 - multiplier)
    return result


# Custom date axis for pyqtgraph (epoch seconds -> MM/DD labels)
if PYQTGRAPH_AVAILABLE:
    class DateAxisItem(pg.AxisItem):
        """Axis item that displays dates from Unix timestamps."""
        def tickStrings(self, values, scale, spacing):
            min_epoch = 946684800  # 2000-01-01
            return [datetime.fromtimestamp(v).strftime('%m/%d')
                    for v in values if v > min_epoch]


class DataFetchWorker(QThread):
    """Background thread to fetch price data + regime metrics."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, symbols: List[str], start_date: date, end_date: date,
                 config: dict, db_session_factory=None, extra_lookback: int = 0):
        super().__init__()
        self.symbols = symbols
        self.start_date = start_date
        self.end_date = end_date
        self.config = config
        self.db_session_factory = db_session_factory
        self.extra_lookback = extra_lookback

    def run(self):
        visible_days = (self.end_date - self.start_date).days
        lookback_days = visible_days + self.extra_lookback
        result = {
            'symbols': self.symbols,
            'price_data': {},
            'regime_data': [],
            'visible_start': self.start_date,
        }

        # 1. Fetch price data from Massive/Polygon API
        try:
            self.progress.emit(f"Fetching prices for {', '.join(self.symbols)}...")
            from canslim_monitor.regime.historical_data import MassiveHistoricalClient
            client = MassiveHistoricalClient.from_config(self.config)
            client.connect()
            result['price_data'] = client.get_multiple_symbols(
                self.symbols, lookback_days=lookback_days, end_date=self.end_date
            )
        except Exception as e:
            logger.warning(f"Failed to fetch price data: {e}")
            result['price_error'] = str(e)

        # 2. Fetch regime metrics from DB
        if self.db_session_factory:
            try:
                self.progress.emit("Loading regime data from DB...")
                from canslim_monitor.regime.models_regime import MarketRegimeAlert
                session = self.db_session_factory()
                alerts = session.query(MarketRegimeAlert).filter(
                    MarketRegimeAlert.date.between(
                        str(self.start_date), str(self.end_date)
                    )
                ).order_by(MarketRegimeAlert.date.asc()).all()

                for a in alerts:
                    row = {}
                    for field in REGIME_FIELDS:
                        val = getattr(a, field, None)
                        # Convert enums to string
                        if hasattr(val, 'value'):
                            val = val.value
                        row[field] = val
                    result['regime_data'].append(row)
                session.close()
                logger.info(f"Loaded {len(result['regime_data'])} regime records")
            except Exception as e:
                logger.warning(f"Failed to load regime data: {e}")
                result['regime_error'] = str(e)
        else:
            result['regime_error'] = "No database connection"

        self.finished.emit(result)


class SentimentChartDialog(QDialog):
    """Market sentiment dashboard with price + dynamic metric panels."""

    def __init__(self, db_session_factory=None, parent=None):
        super().__init__(parent)
        self.db_session_factory = db_session_factory
        self._symbols = ["SPY"]
        self._worker = None
        self._price_data = {}
        self._regime_data = []
        self._active_panels = list(DEFAULT_PANELS)
        self._panel_plots = {}  # key -> PlotItem
        self._panel_checkboxes = {}  # key -> QCheckBox
        self._active_mas = []  # list of MA keys ('ema21', 'sma50', 'sma200')
        self._ma_checkboxes = {}  # key -> QCheckBox
        self._visible_start = None  # date: trim extra lookback bars

        # Load config internally for API access
        try:
            from canslim_monitor.utils.config import load_config
            self._config = load_config()
        except Exception:
            self._config = {}

        self.setWindowTitle("Market Sentiment Dashboard")
        self.setMinimumSize(1000, 800)
        self.resize(1100, 900)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header
        header = QLabel("Market Sentiment Dashboard")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(13)
        header.setFont(header_font)
        layout.addWidget(header)

        # Controls row 1: symbols + load + date range
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Symbols:"))
        self._symbol_input = QLineEdit("SPY")
        self._symbol_input.setFixedWidth(200)
        self._symbol_input.setPlaceholderText("SPY, QQQ, AAPL")
        self._symbol_input.returnPressed.connect(self._on_load_clicked)
        row1.addWidget(self._symbol_input)

        self._load_btn = QPushButton("Load")
        self._load_btn.clicked.connect(self._on_load_clicked)
        row1.addWidget(self._load_btn)

        row1.addSpacing(15)

        # Quick range buttons
        self._range_buttons = {}
        for days, label in [(30, "30d"), (60, "60d"), (90, "90d")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(days == 90)
            btn.clicked.connect(lambda checked, d=days: self._set_quick_range(d))
            self._range_buttons[days] = btn
            row1.addWidget(btn)

        row1.addSpacing(15)

        # Date pickers
        row1.addWidget(QLabel("From:"))
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        default_start = QDate.currentDate().addDays(-90)
        self._start_date.setDate(default_start)
        row1.addWidget(self._start_date)

        row1.addWidget(QLabel("To:"))
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        self._end_date.setDate(QDate.currentDate())
        row1.addWidget(self._end_date)

        row1.addStretch()
        layout.addLayout(row1)

        # Controls row 2: panel checkboxes + MA checkboxes
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Panels:"))
        for key, pdef in PANEL_DEFS.items():
            cb = QCheckBox(pdef['label'])
            cb.setChecked(key in DEFAULT_PANELS)
            cb.stateChanged.connect(lambda state, k=key: self._on_panel_toggled(k, state))
            self._panel_checkboxes[key] = cb
            row2.addWidget(cb)

        row2.addSpacing(20)
        row2.addWidget(QLabel("MAs:"))
        for key, mdef in MA_DEFS.items():
            cb = QCheckBox(mdef['label'])
            cb.setChecked(False)
            cb.stateChanged.connect(lambda state, k=key: self._on_ma_toggled(k, state))
            self._ma_checkboxes[key] = cb
            row2.addWidget(cb)
        row2.addStretch()
        layout.addLayout(row2)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setFixedHeight(3)
        layout.addWidget(self._progress_bar)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._status_label)

        # Chart or table area
        if PYQTGRAPH_AVAILABLE:
            self._chart_widget = pg.GraphicsLayoutWidget()
            self._chart_widget.setBackground('#1a1a2e')
            layout.addWidget(self._chart_widget, stretch=1)
            self._rebuild_panels()
        else:
            self._fallback_widget = self._create_fallback_tables()
            layout.addWidget(self._fallback_widget, stretch=1)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _rebuild_panels(self):
        """Rebuild pyqtgraph panels based on active panel selection."""
        if not PYQTGRAPH_AVAILABLE:
            return

        self._chart_widget.clear()
        self._panel_plots = {}

        # Row 0: Price panel (always shown)
        self._price_plot = self._chart_widget.addPlot(
            row=0, col=0, title="Daily Close",
            axisItems={'bottom': DateAxisItem(orientation='bottom')}
        )
        self._price_plot.setLabel('left', 'Price ($)')
        self._price_plot.showGrid(x=True, y=True, alpha=0.3)
        self._price_plot.addLegend(offset=(10, 10))

        # Set price panel taller
        self._chart_widget.ci.layout.setRowStretchFactor(0, 3)

        # Dynamic panels
        for i, key in enumerate(self._active_panels):
            pdef = PANEL_DEFS.get(key)
            if not pdef:
                continue
            row_idx = i + 1
            plot = self._chart_widget.addPlot(
                row=row_idx, col=0, title=pdef['label'],
                axisItems={'bottom': DateAxisItem(orientation='bottom')}
            )
            plot.setLabel('left', pdef.get('y_label', ''))
            plot.showGrid(x=True, y=True, alpha=0.3)
            if pdef.get('y_range'):
                plot.setYRange(*pdef['y_range'])
            if len(pdef['lines']) > 1:
                plot.addLegend(offset=(10, 10))

            # F&G zone bands
            if pdef.get('zone_bands'):
                self._add_fg_zone_bands(plot)

            # VIX zone bands
            if pdef.get('vix_bands'):
                self._add_vix_zone_bands(plot)

            self._panel_plots[key] = plot
            self._chart_widget.ci.layout.setRowStretchFactor(row_idx, 1)

        # Redraw data if we have any
        if self._price_data or self._regime_data:
            self._update_chart()

    def _create_fallback_tables(self) -> QWidget:
        """Create fallback tables in a QSplitter."""
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Price table
        self._price_table = QTableWidget()
        self._price_table.setColumnCount(3)
        self._price_table.setHorizontalHeaderLabels(["Date", "Symbol", "Close"])
        self._price_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._price_table.setAlternatingRowColors(True)
        self._price_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        splitter.addWidget(self._price_table)

        # Regime table
        self._regime_table = QTableWidget()
        self._regime_table.setColumnCount(7)
        self._regime_table.setHorizontalHeaderLabels([
            "Date", "SPY D", "QQQ D", "Composite", "Risk", "Phase", "F&G"
        ])
        self._regime_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._regime_table.setAlternatingRowColors(True)
        self._regime_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        splitter.addWidget(self._regime_table)

        return splitter

    def _add_fg_zone_bands(self, plot):
        """Add colored zone bands to a F&G plot."""
        for y_low, y_high, color in [
            (0, 25, '#DC354520'),
            (25, 45, '#FD7E1420'),
            (45, 55, '#FFC10720'),
            (55, 75, '#90EE9020'),
            (75, 100, '#28A74520'),
        ]:
            region = pg.LinearRegionItem(
                values=[y_low, y_high], orientation='horizontal',
                movable=False, brush=pg.mkBrush(color)
            )
            region.setZValue(-10)
            plot.addItem(region)

    def _add_vix_zone_bands(self, plot):
        """Add colored zone bands to a VIX plot (IBD/MarketSurge-aligned 7-tier thresholds)."""
        for y_low, y_high, color in [
            (0, 12, '#5B9BD520'),    # Extreme Complacency - blue
            (12, 15, '#28A74520'),   # Low Volatility - green
            (15, 20, '#90EE9020'),   # Normal - light green
            (20, 25, '#FFC10720'),   # Elevated - yellow
            (25, 30, '#FD7E1420'),   # High - orange
            (30, 45, '#DC354520'),   # Very High - red
            (45, 50, '#8B000020'),   # Extreme Fear - dark red
        ]:
            region = pg.LinearRegionItem(
                values=[y_low, y_high], orientation='horizontal',
                movable=False, brush=pg.mkBrush(color)
            )
            region.setZValue(-10)
            plot.addItem(region)

    def _add_phase_backgrounds(self, plot, regime_data: list):
        """Add market phase colored backgrounds to a plot."""
        if not regime_data:
            return

        # Group consecutive dates by phase
        segments = []
        current_phase = None
        seg_start = None
        for d in regime_data:
            phase = d.get('market_phase', '')
            epoch = _date_to_epoch(d['date'])
            if phase != current_phase:
                if current_phase and seg_start is not None:
                    segments.append((seg_start, epoch, current_phase))
                current_phase = phase
                seg_start = epoch
        # Close last segment
        if current_phase and seg_start is not None:
            segments.append((seg_start, _date_to_epoch(regime_data[-1]['date']), current_phase))

        for start_x, end_x, phase in segments:
            color = PHASE_COLORS.get(phase)
            if color:
                region = pg.LinearRegionItem(
                    values=[start_x, end_x], orientation='vertical',
                    movable=False, brush=pg.mkBrush(color)
                )
                region.setZValue(-10)
                plot.addItem(region)

    # --- Panel toggling ---

    def _on_panel_toggled(self, key: str, state: int):
        """Handle panel checkbox toggle."""
        if state == Qt.CheckState.Checked.value:
            if key not in self._active_panels:
                self._active_panels.append(key)
        else:
            if key in self._active_panels:
                self._active_panels.remove(key)
        if PYQTGRAPH_AVAILABLE:
            self._rebuild_panels()

    def _on_ma_toggled(self, key: str, state: int):
        """Handle MA checkbox toggle — reload data with extra lookback if needed."""
        if state == Qt.CheckState.Checked.value:
            if key not in self._active_mas:
                self._active_mas.append(key)
        else:
            if key in self._active_mas:
                self._active_mas.remove(key)
        # Reload to fetch extra lookback for the new MA periods
        self._load_data()

    # --- Controls ---

    def _get_date_range(self):
        """Get start and end date from pickers."""
        qs = self._start_date.date()
        qe = self._end_date.date()
        return date(qs.year(), qs.month(), qs.day()), date(qe.year(), qe.month(), qe.day())

    def _on_load_clicked(self):
        """Handle Load button or Enter key."""
        text = self._symbol_input.text().strip().upper()
        if text:
            self._symbols = [s.strip() for s in text.split(',') if s.strip()]
            self._load_data()

    def _set_quick_range(self, days: int):
        """Set date range from quick buttons."""
        for d, btn in self._range_buttons.items():
            btn.setChecked(d == days)
        self._end_date.setDate(QDate.currentDate())
        self._start_date.setDate(QDate.currentDate().addDays(-days))
        self._load_data()

    # --- Data loading ---

    def _load_data(self):
        """Launch background worker."""
        if self._worker and self._worker.isRunning():
            return

        start, end = self._get_date_range()
        self._load_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        symbols_str = ', '.join(self._symbols)
        self._status_label.setText(f"Loading {symbols_str} ({start} to {end})...")

        # Extra lookback for MA calculation (only when single symbol)
        extra = 0
        if len(self._symbols) == 1 and self._active_mas:
            extra = max(MA_DEFS[k]['period'] for k in self._active_mas)

        self._worker = DataFetchWorker(
            self._symbols, start, end, self._config, self.db_session_factory,
            extra_lookback=extra
        )
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_data_error)
        self._worker.progress.connect(lambda msg: self._status_label.setText(msg))
        self._worker.start()

    def _on_data_loaded(self, result: dict):
        """Handle data fetch completion."""
        self._load_btn.setEnabled(True)
        self._progress_bar.setVisible(False)

        self._symbols = result.get('symbols', self._symbols)
        self._price_data = result.get('price_data', {})
        self._regime_data = result.get('regime_data', [])
        self._visible_start = result.get('visible_start')

        # Build status
        parts = []
        total_bars = sum(len(bars) for bars in self._price_data.values())
        if total_bars:
            parts.append(f"Price: {total_bars} bars ({len(self._price_data)} symbols)")
        elif 'price_error' in result:
            parts.append(f"Price error: {result['price_error']}")
        if self._regime_data:
            parts.append(f"Regime: {len(self._regime_data)} days")
        elif 'regime_error' in result:
            parts.append(f"Regime: {result['regime_error']}")
        self._status_label.setText(" | ".join(parts) if parts else "No data")
        self._update_display()

    def _on_data_error(self, error_msg: str):
        self._load_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_label.setText(f"Error: {error_msg}")

    # --- Display updates ---

    def _update_display(self):
        if PYQTGRAPH_AVAILABLE:
            self._update_chart()
        else:
            self._update_tables()

    def _update_chart(self):
        """Refresh all pyqtgraph panels with current data."""
        # Clear and re-add legend on price plot
        self._price_plot.clear()
        self._price_plot.addLegend(offset=(10, 10))

        # Determine visible cutoff epoch (for trimming extra MA lookback)
        visible_epoch = None
        if self._visible_start:
            visible_epoch = _date_to_epoch(self._visible_start)

        # Panel 1: Price (multiple symbols) + optional MAs
        symbols_str = ', '.join(self._symbols)
        self._price_plot.setTitle(f"{symbols_str} Daily Close")
        single_symbol = len(self._price_data) == 1

        for i, (symbol, bars) in enumerate(self._price_data.items()):
            if not bars:
                continue
            color = SYMBOL_COLORS[i % len(SYMBOL_COLORS)]
            all_x = [_date_to_epoch(bar.date) for bar in bars]
            all_y = [bar.close for bar in bars]

            # Trim to visible range for the price line
            if visible_epoch:
                vis = [(xi, yi) for xi, yi in zip(all_x, all_y) if xi >= visible_epoch]
                if vis:
                    vx, vy = zip(*vis)
                else:
                    vx, vy = all_x, all_y
            else:
                vx, vy = all_x, all_y

            self._price_plot.plot(
                vx, vy, pen=pg.mkPen(color, width=2),
                symbol='o', symbolSize=3, symbolBrush=color,
                name=symbol
            )

            # Plot MAs (only for single symbol)
            if single_symbol and self._active_mas:
                for ma_key in self._active_mas:
                    mdef = MA_DEFS.get(ma_key)
                    if not mdef:
                        continue
                    if mdef['type'] == 'ema':
                        ma_vals = _calc_ema(all_y, mdef['period'])
                    else:
                        ma_vals = _calc_sma(all_y, mdef['period'])
                    # Trim to visible range, skip None values
                    if visible_epoch:
                        vis_ma = [(xi, mi) for xi, mi in zip(all_x, ma_vals)
                                  if mi is not None and xi >= visible_epoch]
                    else:
                        vis_ma = [(xi, mi) for xi, mi in zip(all_x, ma_vals)
                                  if mi is not None]
                    if not vis_ma:
                        continue
                    ma_x, ma_y = zip(*vis_ma)
                    pen = pg.mkPen(mdef['color'], width=1.5, dash=mdef['dash'])
                    self._price_plot.plot(ma_x, ma_y, pen=pen, name=mdef['label'])

        # Dynamic panels from regime data
        if not self._regime_data:
            return

        x_regime = [_date_to_epoch(d['date']) for d in self._regime_data]

        for key, plot in self._panel_plots.items():
            pdef = PANEL_DEFS.get(key)
            if not pdef:
                continue

            # Clear and re-add legend
            plot.clear()
            if pdef.get('y_range'):
                plot.setYRange(*pdef['y_range'])
            if len(pdef['lines']) > 1:
                plot.addLegend(offset=(10, 10))

            # Re-add zone bands after clear
            if pdef.get('zone_bands'):
                self._add_fg_zone_bands(plot)
            if pdef.get('vix_bands'):
                self._add_vix_zone_bands(plot)

            # Phase backgrounds
            if pdef.get('phase_bg'):
                self._add_phase_backgrounds(plot, self._regime_data)

            # Plot each line in this panel
            for field, display_name, color in pdef['lines']:
                # Filter out None values
                valid = [(x, d.get(field)) for x, d in zip(x_regime, self._regime_data)
                         if d.get(field) is not None]
                if not valid:
                    continue
                xs, ys = zip(*valid)
                plot.plot(
                    xs, ys, pen=pg.mkPen(color, width=2),
                    symbol='o', symbolSize=3, symbolBrush=color,
                    name=display_name
                )

    def _update_tables(self):
        """Update fallback tables."""
        # Price table
        rows = []
        for symbol, bars in self._price_data.items():
            for bar in reversed(bars):
                rows.append((bar.date.strftime('%Y-%m-%d'), symbol, f"${bar.close:.2f}"))
        self._price_table.setRowCount(len(rows))
        for row, (dt, sym, price) in enumerate(rows):
            self._price_table.setItem(row, 0, QTableWidgetItem(dt))
            self._price_table.setItem(row, 1, QTableWidgetItem(sym))
            self._price_table.setItem(row, 2, QTableWidgetItem(price))

        # Regime table
        self._regime_table.setRowCount(len(self._regime_data))
        for row, d in enumerate(reversed(self._regime_data)):
            dt = d['date']
            dt_str = dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)
            self._regime_table.setItem(row, 0, QTableWidgetItem(dt_str))
            self._regime_table.setItem(row, 1, QTableWidgetItem(
                str(d.get('spy_d_count', '--'))
            ))
            self._regime_table.setItem(row, 2, QTableWidgetItem(
                str(d.get('qqq_d_count', '--'))
            ))
            comp = d.get('composite_score')
            self._regime_table.setItem(row, 3, QTableWidgetItem(
                f"{comp:+.2f}" if comp is not None else "--"
            ))
            risk = d.get('entry_risk_score')
            self._regime_table.setItem(row, 4, QTableWidgetItem(
                f"{risk:+.2f}" if risk is not None else "--"
            ))
            self._regime_table.setItem(row, 5, QTableWidgetItem(
                d.get('market_phase', '--')
            ))
            fg = d.get('fear_greed_score')
            self._regime_table.setItem(row, 6, QTableWidgetItem(
                f"{fg:.1f}" if fg is not None else "--"
            ))

    # --- Cleanup ---

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)
