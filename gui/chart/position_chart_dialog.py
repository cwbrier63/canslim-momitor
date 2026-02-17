"""
CANSLIM Monitor - dxCharts Lite Position Chart Dialog (Pilot)
==============================================================
Candlestick charting with dxCharts Lite, launched from position card
right-click menu. Displays OHLCV data with CANSLIM level overlays.

Supports multiple timeframes (W/D/1H/30m) via the abstract provider layer.

Requires: PyQt6-WebEngine
"""

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QMessageBox
from PyQt6.QtCore import Qt, QThread, pyqtSignal

logger = logging.getLogger('canslim.gui.chart')

# Guard WebEngine import
WEBENGINE_AVAILABLE = False
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtCore import QUrl
    WEBENGINE_AVAILABLE = True
except ImportError:
    pass

ASSETS_DIR = Path(__file__).parent / "assets"

# Default bar counts per timeframe (request max available from provider)
DEFAULT_BAR_COUNTS = {
    'week': 1500,   # ~29 years
    'day': 1500,    # ~6 years
    'hour': 5000,   # ~2.8 years
    '30min': 10000, # ~3 years
}


class PositionChartDataWorker(QThread):
    """Background thread to fetch bar data for a single symbol at any timeframe."""
    finished = pyqtSignal(list, list, str)   # bars, spy_bars, provider_name
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, symbol: str, timeframe: str, count: int, db_session_factory):
        super().__init__()
        self.symbol = symbol
        self.timeframe = timeframe
        self.count = count
        self.db_session_factory = db_session_factory

    def run(self):
        try:
            tf_label = {'week': 'weekly', 'day': 'daily', 'hour': 'hourly', '30min': '30-min'}.get(
                self.timeframe, self.timeframe
            )
            self.progress.emit(f"Fetching {self.symbol} {tf_label} data...")

            from canslim_monitor.providers.factory import ProviderFactory
            from canslim_monitor.providers.types import Timeframe

            factory = ProviderFactory(self.db_session_factory)
            provider = factory.get_historical()
            if not provider:
                self.error.emit("No historical data provider configured")
                return

            # Map string timeframe to Timeframe enum
            tf_map = {
                'week': Timeframe.WEEK,
                'day': Timeframe.DAY,
                'hour': Timeframe.HOUR,
                '30min': Timeframe.MINUTE_30,
            }
            tf_enum = tf_map.get(self.timeframe, Timeframe.DAY)

            bars = provider.get_bars(self.symbol, timeframe=tf_enum, count=self.count)
            if not bars:
                self.error.emit(f"No {tf_label} data returned for {self.symbol}")
                return

            # Fetch SPY bars for RS Line calculation (same timeframe/count)
            spy_bars = []
            if self.symbol.upper() != 'SPY':
                try:
                    self.progress.emit(f"Fetching SPY {tf_label} data for RS Line...")
                    spy_bars = provider.get_bars('SPY', timeframe=tf_enum, count=self.count)
                except Exception as e:
                    logger.warning(f"Failed to fetch SPY bars for RS Line: {e}")

            provider_name = getattr(provider, '_name', 'Unknown')
            self.progress.emit(f"{self.symbol}: {len(bars)} {tf_label} bars loaded")
            self.finished.emit(bars, spy_bars, provider_name)
        except Exception as e:
            logger.error(f"Chart data fetch error for {self.symbol}: {e}", exc_info=True)
            self.error.emit(str(e))


# Chunk size for lazy-loading historical intraday data
HISTORY_CHUNK_BARS = 5000
# Maximum lookback in years for intraday lazy loading
MAX_INTRADAY_YEARS = 5


class HistoryChunkWorker(QThread):
    """Background worker to fetch an older chunk of intraday bars."""
    finished = pyqtSignal(list)   # older bars
    error = pyqtSignal(str)

    def __init__(self, symbol: str, timeframe: str, count: int,
                 end_date, db_session_factory):
        super().__init__()
        self.symbol = symbol
        self.timeframe = timeframe
        self.count = count
        self.end_date = end_date
        self.db_session_factory = db_session_factory

    def run(self):
        try:
            from canslim_monitor.providers.factory import ProviderFactory
            from canslim_monitor.providers.types import Timeframe

            factory = ProviderFactory(self.db_session_factory)
            provider = factory.get_historical()
            if not provider:
                self.error.emit("No provider")
                return

            tf_map = {
                'hour': Timeframe.HOUR,
                '30min': Timeframe.MINUTE_30,
            }
            tf_enum = tf_map.get(self.timeframe, Timeframe.HOUR)
            bars = provider.get_bars(
                self.symbol, timeframe=tf_enum,
                count=self.count, end_date=self.end_date,
            )
            self.finished.emit(bars or [])
        except Exception as e:
            logger.error(f"History chunk fetch error: {e}", exc_info=True)
            self.error.emit(str(e))


class PositionChartDialog(QDialog):
    """dxCharts Lite candlestick chart for a single position."""

    def __init__(
        self,
        symbol: str,
        position_data: Dict[str, Any],
        db_session_factory,
        parent=None,
    ):
        super().__init__(None)  # No parent — independent top-level window
        self.symbol = symbol
        self.position_data = position_data
        self.db_session_factory = db_session_factory
        self._worker = None
        self._bars = []
        self._spy_bars = []
        self._web_view = None
        self._chart_ready = False
        self._current_timeframe = 'day'
        self._provider_name = ''
        self._ticker_details = None  # cached: {name, industry, sector}
        self._active_indicators = set()  # indicator IDs currently enabled
        self._indicator_df = None        # cached DataFrame from bars (includes spy_close)
        self._current_price = None       # real current price (from daily load or position)
        self._daily_bars = None          # cached daily bars for scoring (never overwritten)
        self._rth_only = True            # RTH filter for intraday charts
        self._history_worker = None      # background worker for lazy-loading history
        self._can_fetch_more = False     # whether more historical data is available
        self._fetching_more = False      # guard against duplicate fetch requests

        self.setWindowTitle(f"Chart - {symbol}")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(900, 600)
        self.resize(1100, 750)
        self._setup_ui()
        self._load_data(timeframe='day')

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if WEBENGINE_AVAILABLE:
            self._web_view = QWebEngineView()
            html_path = ASSETS_DIR / "chart_template.html"
            self._web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
            self._web_view.loadFinished.connect(self._on_page_loaded)
            # Listen for title changes from JS (resolution switch signal)
            self._web_view.page().titleChanged.connect(self._on_title_changed)
            layout.addWidget(self._web_view, stretch=1)
        else:
            fallback = QLabel(
                "PyQt6-WebEngine is required for charts.\n\n"
                "Install with: pip install PyQt6-WebEngine"
            )
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setStyleSheet(
                "color: #d1d4dc; background: #1a1a2e; padding: 40px; font-size: 14px;"
            )
            layout.addWidget(fallback, stretch=1)

        self._status_label = QLabel("Loading...")
        self._status_label.setStyleSheet(
            "color: #888; font-size: 11px; padding: 4px 8px; background: #1a1a2e;"
        )
        layout.addWidget(self._status_label)

    def _on_page_loaded(self, ok: bool):
        if not ok:
            self._status_label.setText("Failed to load chart template")
            return
        self._chart_ready = True
        self._run_js("initChart();")
        self._run_js(f"setSymbolLabel('{self.symbol}');")
        self._push_indicator_catalog()
        if self._bars:
            self._push_candles_to_chart()

    def _on_title_changed(self, title: str):
        """Handle JS→Python signals via document.title changes."""
        if title.startswith('TF:'):
            new_tf = title[3:]
            if new_tf in DEFAULT_BAR_COUNTS and new_tf != self._current_timeframe:
                self._load_data(timeframe=new_tf)
        elif title.startswith('IND_ADD:'):
            indicator_id = title[8:]
            self._calculate_and_push_indicator(indicator_id)
        elif title.startswith('IND_REM:'):
            indicator_id = title[8:]
            self._active_indicators.discard(indicator_id)
        elif title.startswith('SESSION:'):
            session_mode = title[8:]  # 'rth' or 'eth'
            self._rth_only = (session_mode == 'rth')
            self._on_session_filter_changed()
        elif title == 'FETCH_MORE':
            self._fetch_more_history()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self, timeframe: str = 'day'):
        if self._worker and self._worker.isRunning():
            return
        self._current_timeframe = timeframe
        count = DEFAULT_BAR_COUNTS.get(timeframe, 400)

        tf_label = {'week': 'weekly', 'day': 'daily', 'hour': 'hourly', '30min': '30-min'}.get(
            timeframe, timeframe
        )
        self._status_label.setText(f"Loading {self.symbol} {tf_label}...")

        self._worker = PositionChartDataWorker(
            self.symbol, timeframe, count, self.db_session_factory
        )
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_data_error)
        self._worker.progress.connect(lambda msg: self._status_label.setText(msg))
        self._worker.start()

    def _on_data_loaded(self, bars: list, spy_bars: list, provider_name: str):
        self._bars = bars
        self._spy_bars = spy_bars
        self._provider_name = provider_name

        # Capture real current price and daily bars from the first (daily) load
        if self._current_price is None and bars:
            self._current_price = bars[-1].close
        if self._daily_bars is None and self._current_timeframe == 'day' and bars:
            self._daily_bars = bars

        # Enable lazy-loading for intraday timeframes
        self._fetching_more = False
        if self._current_timeframe in ('hour', '30min') and bars:
            self._can_fetch_more = self._has_more_history()
        else:
            self._can_fetch_more = False

        tf_label = {'week': 'W', 'day': 'D', 'hour': '1H', '30min': '30m'}.get(
            self._current_timeframe, self._current_timeframe
        )
        self._status_label.setText(
            f"{self.symbol} [{tf_label}]: {len(bars)} bars | Source: {provider_name}"
        )
        if self._chart_ready:
            self._push_candles_to_chart()
            # Tell JS whether more history is available
            self._run_js(f"setCanFetchMore({'true' if self._can_fetch_more else 'false'});")

    def _on_data_error(self, error_msg: str):
        self._status_label.setText(f"Error: {error_msg}")

    # ------------------------------------------------------------------
    # Lazy-load historical intraday data
    # ------------------------------------------------------------------

    def _has_more_history(self) -> bool:
        """Check if oldest loaded bar is within the 5-year cap."""
        if not self._bars:
            return False
        oldest = self._bars[0]
        oldest_date = oldest.bar_date
        if isinstance(oldest_date, datetime):
            oldest_date = oldest_date.date()
        cutoff = date.today() - timedelta(days=MAX_INTRADAY_YEARS * 365)
        return oldest_date > cutoff

    def _fetch_more_history(self):
        """Fetch an older chunk of intraday bars and prepend."""
        if self._fetching_more or not self._can_fetch_more:
            return
        if self._current_timeframe not in ('hour', '30min'):
            return
        if not self._bars:
            return

        self._fetching_more = True
        self._run_js("setFetchingMore(true);")

        # End date = day before oldest loaded bar
        oldest = self._bars[0]
        oldest_date = oldest.bar_date
        if isinstance(oldest_date, datetime):
            oldest_date = oldest_date.date()
        end_date = oldest_date - timedelta(days=1)

        tf_label = {'hour': '1H', '30min': '30m'}.get(self._current_timeframe, '')
        self._status_label.setText(
            f"Loading older {tf_label} data for {self.symbol}..."
        )

        self._history_worker = HistoryChunkWorker(
            self.symbol, self._current_timeframe,
            HISTORY_CHUNK_BARS, end_date, self.db_session_factory,
        )
        self._history_worker.finished.connect(self._on_history_chunk_loaded)
        self._history_worker.error.connect(self._on_history_chunk_error)
        self._history_worker.start()

    def _on_history_chunk_loaded(self, new_bars: list):
        """Prepend older bars to existing data and refresh chart."""
        self._fetching_more = False

        if new_bars:
            # Deduplicate: only keep bars older than what we already have
            oldest_ts = getattr(self._bars[0], '_timestamp_ms', None) if self._bars else None
            if oldest_ts:
                new_bars = [b for b in new_bars
                            if getattr(b, '_timestamp_ms', 0) < oldest_ts]

            if new_bars:
                self._bars = new_bars + self._bars
                # Invalidate indicator cache
                self._indicator_df = None

        # Check if we can still fetch more
        self._can_fetch_more = bool(new_bars) and self._has_more_history()

        # Re-push all candles to chart (JS will preserve viewport)
        self._push_candles_to_chart(preserve_viewport=True)
        self._run_js(f"setCanFetchMore({'true' if self._can_fetch_more else 'false'});")
        self._run_js("setFetchingMore(false);")

        tf_label = {'week': 'W', 'day': 'D', 'hour': '1H', '30min': '30m'}.get(
            self._current_timeframe, ''
        )
        self._status_label.setText(
            f"{self.symbol} [{tf_label}]: {len(self._bars)} bars | Source: {self._provider_name}"
        )

    def _on_history_chunk_error(self, error_msg: str):
        self._fetching_more = False
        self._run_js("setFetchingMore(false);")
        self._status_label.setText(f"History load error: {error_msg}")

    # ------------------------------------------------------------------
    # Push data to chart
    # ------------------------------------------------------------------

    def _push_candles_to_chart(self, preserve_viewport: bool = False):
        """Convert bars to dxCharts candle format and push to JS."""
        # Clear previous overlays
        self._run_js("clearOverlays();")

        # Tell JS which timeframe is active
        self._run_js(f"setTimeframe('{self._current_timeframe}');")

        # Set data source label
        source_text = f"Source: {self._provider_name}" if self._provider_name else ""
        self._run_js(f"setSourceLabel('{self._escape_js(source_text)}');")

        # For intraday, determine RTH (Regular Trading Hours) per bar
        is_intraday = self._current_timeframe in ('hour', '30min')
        et_tz = None
        if is_intraday:
            try:
                import pytz
                et_tz = pytz.timezone('US/Eastern')
            except ImportError:
                pass

        candles = []
        for i, bar in enumerate(self._bars):
            # Use intraday timestamp if available (set by PolygonClient.get_bars)
            ts_ms = getattr(bar, '_timestamp_ms', None)
            if ts_ms is None:
                bar_dt = bar.bar_date
                if isinstance(bar_dt, date) and not isinstance(bar_dt, datetime):
                    bar_dt = datetime.combine(bar_dt, datetime.min.time())
                ts_ms = int(bar_dt.timestamp() * 1000)

            candle = {
                'id': str(i),
                'hi': bar.high,
                'lo': bar.low,
                'open': bar.open,
                'close': bar.close,
                'timestamp': ts_ms,
                'volume': getattr(bar, 'volume', 0) or 0,
            }

            # Tag intraday bars with RTH flag
            if is_intraday and et_tz:
                from datetime import timezone as tz
                dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=tz.utc)
                dt_et = dt_utc.astimezone(et_tz)
                # RTH = 9:30 AM to 4:00 PM ET
                t = dt_et.hour * 60 + dt_et.minute  # minutes since midnight
                candle['rth'] = (570 <= t < 960)  # 9:30=570, 16:00=960

            candles.append(candle)

        candles_json = json.dumps(candles)
        preserve_js = 'true' if preserve_viewport else 'false'
        self._run_js(f"setCandles('{self._escape_js(candles_json)}', {preserve_js});")

        # Set default visible range (skip when preserving viewport during history load)
        if not preserve_viewport:
            range_map = {
                'week': 52,     # ~1 year of weekly bars
                'day': 252,     # ~1 year of daily bars
                'hour': 100,    # ~2 weeks of hourly bars
                '30min': 100,   # ~1 week of 30-min bars
            }
            self._run_js(f"setRange({range_map.get(self._current_timeframe, 252)});")

        # Push overlays
        self._push_ma_overlays()
        self._push_levels_to_chart()
        if self._current_timeframe in ('day', 'week'):
            self._push_trade_markers()

        # Scorecard always shown (uses position data, not timeframe-dependent)
        self._push_scorecard()

        # Re-push active indicators for new timeframe
        self._indicator_df = None  # invalidate cached DataFrame
        for ind_id in list(self._active_indicators):
            self._calculate_and_push_indicator(ind_id)

    def _push_levels_to_chart(self):
        """Push CANSLIM levels to the chart, reading from position table first."""
        pd = self.position_data
        state = pd.get('state', 0)

        # Watchlist (state=0): show pivot, buy zone, stop, and TP1 based on pivot
        if state == 0:
            self._push_watchlist_levels()
            return

        # Entry = first purchase price (e1), Avg = weighted average cost
        e1_price = pd.get('e1_price')
        avg_cost = pd.get('avg_cost')
        # Reference price for level calculations (avg_cost is what position thread uses)
        ref_price = avg_cost or e1_price
        if not ref_price or ref_price <= 0:
            return

        # Read pre-calculated prices from position table
        stop_price = pd.get('stop_price')
        tp1_target = pd.get('tp1_target')
        tp2_target = pd.get('tp2_target')
        py1_price = pd.get('pyramid1_price')
        py2_price = pd.get('pyramid2_price')

        # Calculate warning stop from stop_price (2% buffer above hard stop)
        warning_stop = None
        if stop_price and stop_price > 0 and ref_price > 0:
            stop_pct = ((ref_price - stop_price) / ref_price) * 100
            warning_stop = round(ref_price * (1 - (stop_pct - 2.0) / 100), 2)

        # Fall back to LevelCalculator only for missing values
        calc_levels = None
        if not all([stop_price, tp1_target, tp2_target]):
            try:
                from canslim_monitor.utils.level_calculator import LevelCalculator
                from canslim_monitor.utils.config import load_config
                config = load_config()
                pm_config = config.get('position_monitoring', {})
            except Exception:
                pm_config = {}
            try:
                calc = LevelCalculator(pm_config)
                base_stage = 1
                bs_raw = pd.get('base_stage', '')
                if bs_raw:
                    try:
                        base_stage = int(str(bs_raw)[0])
                    except (ValueError, IndexError):
                        pass
                calc_levels = calc.calculate_levels(
                    ref_price,
                    base_stage=base_stage,
                    tp1_pct=pd.get('tp1_pct', 20.0),
                    tp2_pct=pd.get('tp2_pct', 30.0),
                    hard_stop_pct=pd.get('hard_stop_pct', 7.0),
                )
            except Exception:
                logger.warning("LevelCalculator fallback failed", exc_info=True)

        # Use DB values first, fall back to calculated
        hard_stop = stop_price or (calc_levels.hard_stop if calc_levels else None)
        warn_stop = warning_stop or (calc_levels.warning_stop if calc_levels else None)
        tp1 = tp1_target or (calc_levels.tp1 if calc_levels else None)
        tp2 = tp2_target or (calc_levels.tp2 if calc_levels else None)
        py1 = py1_price or (calc_levels.py1_min if calc_levels else None)
        py2 = py2_price or (calc_levels.py2_min if calc_levels else None)

        # Level definitions: (id, price, label, color, lineStyle)
        level_defs = [
            ('hard_stop', hard_stop, 'Stop', '#DC3545', 'solid'),
            ('warn_stop', warn_stop, 'Warn', '#FFC107', 'dashed'),
            ('tp1', tp1, 'TP1', '#28A745', 'dashed'),
            ('tp2', tp2, 'TP2', '#28A745', 'solid'),
        ]

        # Add pyramid levels (only show range lines if from calculator)
        if py1_price and py1_price > 0:
            level_defs.append(('py1', py1_price, 'PY1', '#9B59B6', 'dotted'))
        elif calc_levels:
            level_defs.append(('py1_min', calc_levels.py1_min, 'PY1', '#9B59B6', 'dotted'))
            level_defs.append(('py1_max', calc_levels.py1_max, 'PY1+', '#9B59B6', 'dotted'))

        if py2_price and py2_price > 0:
            level_defs.append(('py2', py2_price, 'PY2', '#8E44AD', 'dotted'))
        elif calc_levels:
            level_defs.append(('py2_min', calc_levels.py2_min, 'PY2', '#8E44AD', 'dotted'))
            level_defs.append(('py2_max', calc_levels.py2_max, 'PY2+', '#8E44AD', 'dotted'))

        # Add pivot if available
        pivot = pd.get('pivot')
        if pivot and pivot > 0:
            level_defs.insert(0, ('pivot', pivot, 'Pivot', '#4a90d9', 'solid'))

        # Add entry line at first purchase price (e1)
        if e1_price and e1_price > 0:
            level_defs.append(('entry', e1_price, 'Entry', '#17A2B8', 'dashed'))

        # Add avg cost line (white) when different from entry
        state = pd.get('state', 0)
        if avg_cost and avg_cost > 0:
            # Show avg cost if it differs from e1 (i.e. pyramided position)
            if not e1_price or abs(avg_cost - e1_price) > 0.005:
                level_defs.append(('avg_cost', avg_cost, 'Avg', '#FFFFFF', 'solid'))

        for lid, price, label, color, style in level_defs:
            if price and price > 0:
                self._run_js(
                    f"addLevelLine('{lid}', {price}, '{label}', '{color}', '{style}');"
                )

        self._run_js("showOverlaySection();")

    def _push_watchlist_levels(self):
        """Push pivot, buy zone, stop loss, and TP1 for watchlist (state=0) positions."""
        pd = self.position_data
        pivot = pd.get('pivot')
        if not pivot or pivot <= 0:
            return

        hard_stop_pct = pd.get('hard_stop_pct', 7.0)
        tp1_pct = pd.get('tp1_pct', 20.0)

        # Buy zone: pivot to pivot + 5%
        buy_zone_top = round(pivot * 1.05, 2)
        # Stop loss: hard_stop_pct below pivot
        stop_price = round(pivot * (1 - hard_stop_pct / 100), 2)
        # TP1: tp1_pct above pivot
        tp1_price = round(pivot * (1 + tp1_pct / 100), 2)

        # Buy zone (semi-transparent blue fill)
        self._run_js(
            f"addZone('buy_zone', {buy_zone_top}, {pivot}, 'Buy Zone', 'rgba(74, 144, 217, 0.15)');"
        )

        # Level lines
        level_defs = [
            ('pivot', pivot, 'Pivot', '#4a90d9', 'solid'),
            ('buy_top', buy_zone_top, '+5%', '#4a90d9', 'dotted'),
            ('hard_stop', stop_price, 'Stop', '#DC3545', 'solid'),
            ('tp1', tp1_price, 'TP1', '#28A745', 'dashed'),
        ]

        for lid, price, label, color, style in level_defs:
            if price and price > 0:
                self._run_js(
                    f"addLevelLine('{lid}', {price}, '{label}', '{color}', '{style}');"
                )

        self._run_js("showOverlaySection();")

    # ------------------------------------------------------------------
    # Indicator integration (pandas-ta)
    # ------------------------------------------------------------------

    def _push_indicator_catalog(self):
        """Push the indicator catalog to JS for the picker UI."""
        try:
            from canslim_monitor.gui.chart.indicator_engine import (
                INDICATOR_CATALOG, PANDAS_TA_AVAILABLE,
            )
        except ImportError:
            return
        catalog_js = {}
        for ind_id, config in INDICATOR_CATALOG.items():
            catalog_js[ind_id] = {
                'name': config['name'],
                'panel': config['panel'],
                'category': config.get('category', 'Other'),
            }
        catalog_json = json.dumps(catalog_js)
        available = 'true' if PANDAS_TA_AVAILABLE else 'false'
        self._run_js(f"setIndicatorCatalog('{self._escape_js(catalog_json)}', {available});")

    def _calculate_and_push_indicator(self, indicator_id: str):
        """Calculate indicator with pandas-ta and push result to JS."""
        try:
            from canslim_monitor.gui.chart.indicator_engine import (
                PANDAS_TA_AVAILABLE, bars_to_dataframe, calculate_indicator,
            )
        except ImportError:
            return
        if not self._bars:
            return
        # Performance indicators (like RS Line) don't need pandas-ta
        from canslim_monitor.gui.chart.indicator_engine import INDICATOR_CATALOG
        cat = INDICATOR_CATALOG.get(indicator_id, {})
        if not PANDAS_TA_AVAILABLE and cat.get('category') != 'Performance':
            return

        self._active_indicators.add(indicator_id)

        # Build DataFrame (cached per data load), enriched with SPY close for RS Line
        if self._indicator_df is None:
            display_bars = self._get_display_bars()
            self._indicator_df = bars_to_dataframe(display_bars)
            if self._spy_bars:
                spy_df = bars_to_dataframe(self._spy_bars)
                spy_close = spy_df[['timestamp', 'close']].rename(columns={'close': 'spy_close'})
                self._indicator_df = self._indicator_df.merge(spy_close, on='timestamp', how='left')
                self._indicator_df['spy_close'] = self._indicator_df['spy_close'].ffill()

        result = calculate_indicator(indicator_id, self._indicator_df)
        if not result:
            return

        # Serialize and push to JS
        result_json = json.dumps({
            'indicator_id': result.indicator_id,
            'display_name': result.display_name,
            'panel_type': result.panel_type,
            'y_range': list(result.y_range) if result.y_range else None,
            'ref_lines': result.ref_lines,
            'series': [
                {
                    'name': s.name,
                    'series_type': s.series_type,
                    'color': s.color,
                    'width': s.width,
                    'dash_style': s.dash_style,
                    'data': s.data,
                    'data2': s.data2 if s.data2 else None,
                }
                for s in result.series
            ],
        })
        self._run_js(f"addIndicator('{self._escape_js(result_json)}');")

    def _get_display_bars(self):
        """Return bars filtered by the current session mode (RTH/ETH)."""
        if not self._rth_only or self._current_timeframe not in ('hour', '30min'):
            return self._bars

        try:
            import pytz
            et_tz = pytz.timezone('US/Eastern')
        except ImportError:
            return self._bars

        from datetime import timezone as tz
        filtered = []
        for bar in self._bars:
            ts_ms = getattr(bar, '_timestamp_ms', None)
            if ts_ms is None:
                filtered.append(bar)
                continue
            dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=tz.utc)
            dt_et = dt_utc.astimezone(et_tz)
            t = dt_et.hour * 60 + dt_et.minute
            if 570 <= t < 960:  # 9:30 AM - 4:00 PM ET
                filtered.append(bar)
        return filtered

    def _on_session_filter_changed(self):
        """Called when RTH/ETH toggle changes — re-push MAs and indicators."""
        self._run_js("clearOverlays();")
        self._push_ma_overlays()
        self._push_levels_to_chart()
        self._push_scorecard()
        self._indicator_df = None
        for ind_id in list(self._active_indicators):
            self._calculate_and_push_indicator(ind_id)

    def _push_ma_overlays(self):
        """Push MAs to chart per timeframe.

        Weekly:  10 SMA (red), 40 SMA (green)
        Daily:   50 SMA (red), 200 SMA (green)
        1H/30m:  21 SMA (red), 50 SMA (white), 200 SMA (green)
        """
        if not self._bars or len(self._bars) < 10:
            return

        display_bars = self._get_display_bars()
        closes = [b.close for b in display_bars]
        timestamps = []
        for b in display_bars:
            ts_ms = getattr(b, '_timestamp_ms', None)
            if ts_ms is None:
                bar_dt = b.bar_date
                if isinstance(bar_dt, date) and not isinstance(bar_dt, datetime):
                    bar_dt = datetime.combine(bar_dt, datetime.min.time())
                ts_ms = int(bar_dt.timestamp() * 1000)
            timestamps.append(ts_ms)

        try:
            from canslim_monitor.gui.sentiment_chart_dialog import _calc_sma
        except ImportError:
            logger.warning("MA calculation functions not available")
            return

        # Timeframe-specific MA periods
        if self._current_timeframe == 'week':
            ma_defs = [
                ('sma10', 10, '#ef5350', '10 SMA'),
                ('sma40', 40, '#26a69a', '40 SMA'),
            ]
        elif self._current_timeframe in ('hour', '30min'):
            ma_defs = [
                ('sma21', 21, '#ef5350', '21 SMA'),
                ('sma50', 50, '#ffffff', '50 SMA'),
                ('sma200', 200, '#26a69a', '200 SMA'),
            ]
        else:
            ma_defs = [
                ('sma50', 50, '#ef5350', '50 SMA'),
                ('sma200', 200, '#26a69a', '200 SMA'),
            ]

        for ma_id, period, color, label in ma_defs:
            sma = _calc_sma(closes, min(period, len(closes)))
            # Fill leading None values with partial-period averages
            for i in range(len(sma)):
                if sma[i] is not None:
                    break
                sma[i] = sum(closes[:i + 1]) / (i + 1)
            points = [
                {'timestamp': ts, 'value': round(v, 2)}
                for ts, v in zip(timestamps, sma) if v is not None
            ]
            if points:
                sma_json = json.dumps(points)
                self._run_js(f"addMALine('{ma_id}', '{self._escape_js(sma_json)}', '{color}', 1.5, '{label}');")

    def _push_trade_markers(self):
        """Push buy/sell transaction markers to the chart."""
        pd = self.position_data
        if not self._bars:
            return

        # Build date→timestamp map from bar data
        date_ts_map = {}
        for bar in self._bars:
            bar_dt = bar.bar_date
            if isinstance(bar_dt, datetime):
                bar_dt = bar_dt.date()
            # Use the bar's actual timestamp for consistency
            ts_ms = getattr(bar, '_timestamp_ms', None)
            if ts_ms is None:
                dt = datetime.combine(bar_dt, datetime.min.time())
                ts_ms = int(dt.timestamp() * 1000)
            date_ts_map[bar_dt] = ts_ms

        # Collect buy transactions (e1, e2, e3), aggregate by date
        buys_by_date = {}
        for prefix in ('e1', 'e2', 'e3'):
            tx_date = pd.get(f'{prefix}_date')
            tx_shares = pd.get(f'{prefix}_shares')
            if tx_date and tx_shares and tx_shares > 0:
                if isinstance(tx_date, datetime):
                    tx_date = tx_date.date()
                buys_by_date[tx_date] = buys_by_date.get(tx_date, 0) + tx_shares

        for tx_date, total in buys_by_date.items():
            ts = date_ts_map.get(tx_date)
            if ts:
                self._run_js(f"addTradeMarker({ts}, {total}, 'buy');")

        # Sell transaction (close)
        close_date = pd.get('close_date')
        total_shares = pd.get('total_shares')
        if close_date and total_shares and total_shares > 0:
            if isinstance(close_date, datetime):
                close_date = close_date.date()
            ts = date_ts_map.get(close_date)
            if ts:
                self._run_js(f"addTradeMarker({ts}, {total_shares}, 'sell');")

    # ------------------------------------------------------------------
    # Scorecard
    # ------------------------------------------------------------------

    def _push_scorecard(self):
        """Build and push the CANSLIM scorecard overlay data to JS."""
        pd = self.position_data

        # Current price: use the real price captured from daily load,
        # falling back to position table's last_price, then last bar
        current_price = (
            self._current_price
            or pd.get('last_price')
            or (self._bars[-1].close if self._bars else 0)
        )

        # P&L calculation
        avg_cost = pd.get('avg_cost') or pd.get('e1_price')
        pnl_pct = None
        if avg_cost and avg_cost > 0 and current_price > 0:
            pnl_pct = round(((current_price - avg_cost) / avg_cost) * 100, 1)

        # State label
        state_labels = {
            -2: 'STOPPED', -1.5: 'EXIT WATCH', -1: 'CLOSED',
            0: 'WATCHING', 1: 'ENTRY 1', 2: 'ENTRY 2',
            3: 'FULL POS', 4: 'TP1 HIT', 5: 'TP2 HIT', 6: 'TRAILING',
        }
        state = pd.get('state', 0)
        state_label = state_labels.get(state, f'STATE {state}')

        # Hold days
        hold_days = None
        entry_date = pd.get('entry_date') or pd.get('e1_date')
        if entry_date:
            if isinstance(entry_date, datetime):
                entry_date = entry_date.date()
            from datetime import date as date_cls
            hold_days = (date_cls.today() - entry_date).days

        # Dollar P&L
        total_shares = pd.get('total_shares') or 0
        pnl_dollar = None
        if avg_cost and avg_cost > 0 and current_price > 0 and total_shares > 0:
            pnl_dollar = round((current_price - avg_cost) * total_shares, 2)

        # Use DB fields first; fall back to API lookup once if missing
        if self._ticker_details is None:
            if pd.get('company_name'):
                self._ticker_details = {
                    'name': pd.get('company_name'),
                    'industry': pd.get('industry'),
                    'sector': pd.get('sector'),
                }
            else:
                self._ticker_details = self._fetch_ticker_details() or {}

        scorecard = {
            'symbol': self.symbol,
            'company_name': self._ticker_details.get('name'),
            'industry': self._ticker_details.get('industry'),
            'sector': self._ticker_details.get('sector'),
            'current_price': current_price,
            'avg_cost': avg_cost,
            'pnl_pct': pnl_pct,
            'pnl_dollar': pnl_dollar,
            'state': state,
            'state_label': state_label,
            'base_stage': pd.get('base_stage'),
            'ad_rating': pd.get('ad_rating'),
            'health_rating': pd.get('health_rating'),
            'health_score': pd.get('health_score'),
            'stop_price': pd.get('stop_price'),
            'hard_stop_pct': pd.get('hard_stop_pct'),
            'tp1_target': pd.get('tp1_target'),
            'tp1_pct': pd.get('tp1_pct'),
            'tp2_target': pd.get('tp2_target'),
            'tp2_pct': pd.get('tp2_pct'),
            'e1_shares': pd.get('e1_shares'),
            'e2_shares': pd.get('e2_shares'),
            'e3_shares': pd.get('e3_shares'),
            'total_shares': pd.get('total_shares'),
            'hold_days': hold_days,
            'industry_rank': pd.get('industry_rank'),
        }

        # Run score recalculation and add breakdown
        score_breakdown = self._recalculate_score()
        if score_breakdown:
            scorecard['score_breakdown'] = score_breakdown

        # Fetch current market regime (read-only, no storage)
        regime_data = self._fetch_market_regime()
        if regime_data:
            scorecard['regime'] = regime_data

        scorecard_json = json.dumps(scorecard)
        self._run_js(f"setScorecard('{self._escape_js(scorecard_json)}');")

    def _recalculate_score(self) -> Optional[Dict]:
        """Run CANSLIMScorer on position data + loaded bars, return breakdown."""
        pd = self.position_data
        try:
            from canslim_monitor.utils.scoring import CANSLIMScorer
            scorer = CANSLIMScorer()
        except Exception as e:
            logger.warning(f"Could not load scorer: {e}")
            return None

        position_data = {
            'symbol': self.symbol,
            'pattern': pd.get('pattern'),
            'base_stage': pd.get('base_stage'),
            'base_depth': pd.get('base_depth'),
            'base_length': pd.get('base_length'),
            'rs_rating': pd.get('rs_rating'),
            'eps_rating': pd.get('eps_rating'),
            'ad_rating': pd.get('ad_rating'),
        }

        # Try dynamic scoring with cached daily bars (not current timeframe bars)
        daily_df = None
        score_bars = self._daily_bars or self._bars
        if score_bars and len(score_bars) >= 50:
            try:
                import pandas as _pd
                rows = []
                for bar in score_bars:
                    bar_dt = bar.bar_date
                    if isinstance(bar_dt, datetime):
                        bar_dt = bar_dt.date()
                    rows.append({
                        'date': bar_dt,
                        'open': bar.open,
                        'high': bar.high,
                        'low': bar.low,
                        'close': bar.close,
                        'volume': getattr(bar, 'volume', 0) or 0,
                    })
                daily_df = _pd.DataFrame(rows)
            except ImportError:
                pass

        try:
            if daily_df is not None and len(daily_df) >= 50:
                score, grade, details = scorer.calculate_score_with_dynamic(
                    position_data, daily_df, market_regime='BULLISH'
                )
            else:
                score, grade, details = scorer.calculate_score(
                    position_data, market_regime='BULLISH'
                )
        except Exception as e:
            logger.warning(f"Score recalculation failed: {e}", exc_info=True)
            return None

        # Build compact breakdown for JS
        components = []
        for comp in details.get('components', []):
            components.append({
                'name': comp.get('name', ''),
                'points': comp.get('points', 0),
                'reason': comp.get('reason', ''),
            })
        dynamic = []
        for comp in details.get('dynamic_components', []):
            dynamic.append({
                'name': comp.get('name', ''),
                'points': comp.get('points', 0),
                'reason': comp.get('reason', ''),
            })

        return {
            'grade': grade,
            'score': score,
            'static_score': details.get('static_score', 0),
            'dynamic_score': details.get('dynamic_score', 0),
            'components': components,
            'dynamic_components': dynamic,
        }

    def _fetch_market_regime(self) -> Optional[Dict]:
        """Read the latest market regime from DB (read-only, no writes)."""
        try:
            from canslim_monitor.regime.models_regime import MarketRegimeAlert
            session = self.db_session_factory()
            try:
                latest = session.query(MarketRegimeAlert).order_by(
                    MarketRegimeAlert.date.desc()
                ).first()
                if not latest:
                    return None
                return {
                    'date': str(latest.date) if latest.date else None,
                    # Regime
                    'regime': latest.regime.value if latest.regime else None,
                    'score': round(latest.composite_score, 1) if latest.composite_score is not None else None,
                    # IBD status
                    'ibd_status': latest.ibd_market_status.value if latest.ibd_market_status else None,
                    'exposure_min': latest.ibd_exposure_min,
                    'exposure_max': latest.ibd_exposure_max,
                    # D-day counts
                    'spy_d': latest.spy_d_count,
                    'qqq_d': latest.qqq_d_count,
                    'spy_delta': latest.spy_5day_delta,
                    'qqq_delta': latest.qqq_5day_delta,
                    'trend': latest.d_day_trend.value if latest.d_day_trend else None,
                    # Futures
                    'es_pct': round(latest.es_change_pct, 2) if latest.es_change_pct is not None else None,
                    'nq_pct': round(latest.nq_change_pct, 2) if latest.nq_change_pct is not None else None,
                    'ym_pct': round(latest.ym_change_pct, 2) if latest.ym_change_pct is not None else None,
                    # Phase
                    'phase': latest.market_phase,
                    'rally_day': latest.rally_day,
                    'has_ftd': latest.has_confirmed_ftd,
                    'days_since_ftd': latest.days_since_ftd,
                    # Entry risk
                    'entry_risk': latest.entry_risk_level.value if latest.entry_risk_level else None,
                    'risk_score': round(latest.entry_risk_score, 2) if latest.entry_risk_score is not None else None,
                    # Sentiment
                    'fg_score': round(latest.fear_greed_score, 0) if latest.fear_greed_score is not None else None,
                    'fg_rating': latest.fear_greed_rating,
                    'vix': round(latest.vix_close, 2) if latest.vix_close is not None else None,
                }
            finally:
                session.close()
        except Exception as e:
            logger.debug(f"Could not fetch market regime: {e}")
            return None

    def _fetch_ticker_details(self) -> Optional[Dict]:
        """Fetch company name, industry, sector from Polygon (one API call)."""
        try:
            from canslim_monitor.providers.factory import ProviderFactory
            factory = ProviderFactory(self.db_session_factory)
            provider = factory.get_historical()
            if provider and hasattr(provider, 'get_ticker_details'):
                return provider.get_ticker_details(self.symbol)
        except Exception as e:
            logger.debug(f"Could not fetch ticker details for {self.symbol}: {e}")
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_js(self, code: str):
        """Execute JavaScript in the WebEngineView."""
        if self._web_view and self._chart_ready:
            self._web_view.page().runJavaScript(code)

    @staticmethod
    def _escape_js(s: str) -> str:
        """Escape a string for embedding in a JS single-quoted string literal."""
        return s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)
