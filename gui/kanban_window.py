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


# Module-level cache to prevent Polygon API rate limiting
# Polygon free tier: 5 calls/minute - cache for 60 seconds minimum
_polygon_price_cache: Dict[str, Dict] = {}
_polygon_cache_time: float = 0
_POLYGON_CACHE_TTL = 60  # seconds


class PriceUpdateWorker(QObject):
    """
    Worker that fetches prices from IBKR in a background thread.
    Falls back to Polygon for index ETFs if IBKR unavailable.
    Uses module-level cache to respect Polygon rate limits (5 calls/min).
    """
    finished = pyqtSignal(dict)  # Emits {symbol: price_data}
    error = pyqtSignal(str)

    INDEX_ETFS = ['SPY', 'QQQ', 'DIA', 'IWM']

    def __init__(self, ibkr_client, symbols: List[str], polygon_api_key: str = None):
        super().__init__()
        self.ibkr_client = ibkr_client
        self.symbols = symbols
        self.polygon_api_key = polygon_api_key

    def run(self):
        """Fetch prices from IBKR with Polygon fallback for indices."""
        import logging
        logger = logging.getLogger('canslim.gui')

        try:
            prices = {}

            # Try IBKR first
            if self.ibkr_client:
                connected = self.ibkr_client.is_connected()
                logger.debug(f"IBKR connected: {connected}, fetching {len(self.symbols)} symbols")
                if connected:
                    prices = self.ibkr_client.get_quotes(self.symbols) or {}
                    logger.debug(f"IBKR returned prices for: {list(prices.keys())}")

            # Check if we're missing index ETFs - use Polygon fallback
            missing_indices = [s for s in self.INDEX_ETFS if s not in prices or not prices.get(s, {}).get('last')]
            if missing_indices:
                logger.debug(f"Missing index prices, using Polygon fallback for: {missing_indices}")
                polygon_prices = self._fetch_from_polygon(missing_indices)
                if polygon_prices:
                    logger.debug(f"Polygon returned prices for: {list(polygon_prices.keys())}")
                prices.update(polygon_prices)

            # VIX fallback - use Yahoo Finance if IBKR didn't return VIX
            vix_data = prices.get('VIX', {})
            if not vix_data.get('last'):
                logger.debug("VIX not available from IBKR, trying Yahoo Finance fallback")
                vix_prices = self._fetch_vix_fallback()
                if vix_prices:
                    prices['VIX'] = vix_prices
                    logger.debug(f"Yahoo Finance VIX: {vix_prices.get('last')}")
                else:
                    logger.warning("VIX data unavailable from both IBKR and Yahoo Finance")

            self.finished.emit(prices)
        except Exception as e:
            logger.error(f"Price fetch error: {e}")
            self.error.emit(str(e))

    def _fetch_from_polygon(self, symbols: List[str]) -> Dict:
        """Fetch current prices from Polygon as fallback with caching.

        Uses module-level cache to prevent rate limiting (5 calls/min on free tier).
        Cache TTL is 60 seconds to stay well under the rate limit.
        """
        import logging
        import time
        logger = logging.getLogger('canslim.gui')

        global _polygon_price_cache, _polygon_cache_time

        try:
            api_key = self.polygon_api_key
            if not api_key:
                logger.debug("No Polygon API key provided for price fallback")
                return {}

            # Check if cache is still valid
            now = time.time()
            if now - _polygon_cache_time < _POLYGON_CACHE_TTL:
                # Return cached prices for requested symbols
                cached = {s: _polygon_price_cache[s] for s in symbols if s in _polygon_price_cache}
                if cached:
                    logger.debug(f"Using cached Polygon prices for: {list(cached.keys())} (age: {now - _polygon_cache_time:.0f}s)")
                    return cached

            # Cache expired or empty - fetch fresh data
            logger.debug(f"Fetching fresh Polygon data for: {symbols}")
            from polygon import RESTClient
            client = RESTClient(api_key=api_key)

            prices = {}
            for symbol in symbols:
                try:
                    # Fetch 2 recent daily bars to get both current close and previous close
                    from datetime import timedelta, date
                    end_dt = date.today()
                    start_dt = end_dt - timedelta(days=10)  # 10 days to ensure 2 trading days
                    bars = client.get_aggs(symbol, 1, 'day', start_dt.isoformat(), end_dt.isoformat(), limit=5)
                    bars = list(bars) if bars else []
                    if bars and len(bars) >= 1:
                        current_bar = bars[-1]
                        prev_bar_close = bars[-2].close if len(bars) >= 2 else current_bar.open
                        prices[symbol] = {
                            'last': current_bar.close,
                            'close': prev_bar_close,  # Previous session close for D% calc
                            'open': current_bar.open,
                            'high': current_bar.high,
                            'low': current_bar.low,
                            'volume': current_bar.volume,
                            'previousClose': prev_bar_close,
                        }
                        logger.debug(f"Polygon {symbol}: ${current_bar.close:.2f} (prev: ${prev_bar_close:.2f})")
                except Exception as e:
                    logger.debug(f"Polygon fetch error for {symbol}: {e}")

            # Update cache if we got any data
            if prices:
                _polygon_price_cache.update(prices)
                _polygon_cache_time = now
                logger.debug(f"Updated Polygon cache with {len(prices)} symbols")

            return prices
        except Exception as e:
            logger.error(f"Polygon fallback failed: {e}")
            return {}

    def _fetch_vix_fallback(self) -> Optional[Dict]:
        """Fetch VIX data from Yahoo Finance as fallback when IBKR unavailable."""
        import logging
        logger = logging.getLogger('canslim.gui')

        try:
            import requests
            url = 'https://query2.finance.yahoo.com/v8/finance/chart/%5EVIX'
            params = {'interval': '1d', 'range': '2d'}
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
            }
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()

            result = data['chart']['result'][0]
            meta = result['meta']
            price = meta.get('regularMarketPrice', 0)
            prev_close = meta.get('chartPreviousClose') or meta.get('previousClose', 0)

            if price and price > 0:
                return {
                    'symbol': 'VIX',
                    'last': float(price),
                    'close': float(prev_close) if prev_close else float(price),
                    'open': float(meta.get('regularMarketOpen', 0) or 0),
                    'high': float(meta.get('regularMarketDayHigh', 0) or 0),
                    'low': float(meta.get('regularMarketDayLow', 0) or 0),
                    'volume': 0,
                    'timestamp': None,
                }

        except Exception as e:
            logger.debug(f"Yahoo Finance VIX fallback failed: {e}")

        return None


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

        # Separator
        layout.addWidget(self._create_separator())

        # Fear & Greed Section
        fg_section = QVBoxLayout()
        fg_section.setSpacing(2)

        fg_title = QLabel("FEAR & GREED")
        fg_title.setStyleSheet("font-size: 10px; color: #AAA;")
        fg_section.addWidget(fg_title)

        self.fg_score_label = QLabel("--")
        fg_font = QFont()
        fg_font.setBold(True)
        fg_font.setPointSize(13)
        self.fg_score_label.setFont(fg_font)
        self.fg_score_label.setStyleSheet("color: #888;")
        self.fg_score_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fg_score_label.setToolTip("CNN Fear & Greed Index — Click for chart")
        self.fg_score_label.mousePressEvent = self._on_fg_click
        fg_section.addWidget(self.fg_score_label)

        self.fg_rating_label = QLabel("")
        self.fg_rating_label.setStyleSheet("font-size: 10px; color: #AAA;")
        fg_section.addWidget(self.fg_rating_label)

        layout.addLayout(fg_section)

        # Separator
        layout.addWidget(self._create_separator())

        # VIX Section
        vix_section = QVBoxLayout()
        vix_section.setSpacing(2)

        vix_title = QLabel("VIX")
        vix_title.setStyleSheet("font-size: 10px; color: #AAA;")
        vix_section.addWidget(vix_title)

        self.vix_score_label = QLabel("--")
        vix_font = QFont()
        vix_font.setBold(True)
        vix_font.setPointSize(13)
        self.vix_score_label.setFont(vix_font)
        self.vix_score_label.setStyleSheet("color: #888;")
        self.vix_score_label.setToolTip("CBOE Volatility Index (VIX)")
        vix_section.addWidget(self.vix_score_label)

        self.vix_rating_label = QLabel("")
        self.vix_rating_label.setStyleSheet("font-size: 10px; color: #AAA;")
        vix_section.addWidget(self.vix_rating_label)

        self.vix_change_label = QLabel("")
        self.vix_change_label.setStyleSheet("font-size: 10px; color: #AAA;")
        vix_section.addWidget(self.vix_change_label)

        layout.addLayout(vix_section)

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
            # Color code: green=bullish, red=bearish, grey=neutral (within ±0.1%)
            if abs(pct) < 0.1:
                color = "#888888"  # Grey for neutral
            elif pct > 0:
                color = "#28A745"  # Green for bullish
            else:
                color = "#DC3545"  # Red for bearish
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
        
        # Middle row: Open/Week % | Day %
        change_row = QLabel("<span style='color:#888'>O:</span>-- <span style='color:#888'>D:</span>--")
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

    def update_fear_greed(self, score: float = None, rating: str = None):
        """Update Fear & Greed Index display."""
        if score is None:
            self.fg_score_label.setText("--")
            self.fg_score_label.setStyleSheet("color: #888;")
            self.fg_rating_label.setText("")
            return

        self.fg_score_label.setText(f"{score:.1f}")
        self.fg_rating_label.setText(rating or "")

        # Color by score range (CNN boundaries)
        if score < 25:
            color = "#DC3545"      # Red - Extreme Fear
        elif score < 45:
            color = "#FD7E14"      # Orange - Fear
        elif score < 55:
            color = "#FFC107"      # Yellow - Neutral
        elif score < 75:
            color = "#90EE90"      # Light green - Greed
        else:
            color = "#28A745"      # Green - Extreme Greed

        self.fg_score_label.setStyleSheet(f"color: {color};")
        self.fg_rating_label.setStyleSheet(f"font-size: 10px; color: {color};")

    def update_vix(self, price: float = None, prev_close: float = None):
        """Update VIX card display.

        IBD/MarketSurge-aligned thresholds:
            0-12:  Extreme Complacency (blue)
            12-15: Low Volatility (green)
            15-20: Normal (green)
            20-25: Elevated (yellow)
            25-30: High (orange)
            30-45: Very High (red)
            45+:   Extreme Fear (dark red)
        """
        if price is None:
            self.vix_score_label.setText("--")
            self.vix_score_label.setStyleSheet("color: #888;")
            self.vix_rating_label.setText("")
            self.vix_change_label.setText("")
            return

        from canslim_monitor.regime.vix_client import classify_vix

        rating = classify_vix(price)

        # Color by VIX level (7-tier IBD)
        if price < 12:
            color = "#5B9BD5"      # Blue - Extreme Complacency
        elif price < 15:
            color = "#28A745"      # Green - Low Volatility
        elif price < 20:
            color = "#28A745"      # Green - Normal
        elif price < 25:
            color = "#FFC107"      # Yellow - Elevated
        elif price < 30:
            color = "#FFA500"      # Orange - High
        elif price < 45:
            color = "#DC3545"      # Red - Very High
        else:
            color = "#8B0000"      # Dark Red - Extreme Fear

        self.vix_score_label.setText(f"{price:.1f}")
        self.vix_score_label.setStyleSheet(f"color: {color};")
        self.vix_rating_label.setText(rating)
        self.vix_rating_label.setStyleSheet(f"font-size: 10px; color: {color};")

        # Intraday change (VIX up = bad = red, VIX down = good = green)
        if prev_close and prev_close > 0:
            change = price - prev_close
            if change > 0:
                arrow = "\u2191"
                chg_color = "#DC3545"   # Red - VIX rising is bad
            elif change < 0:
                arrow = "\u2193"
                chg_color = "#28A745"   # Green - VIX falling is good
            else:
                arrow = "\u2192"
                chg_color = "#AAA"
            self.vix_change_label.setText(f"{arrow} {change:+.1f}")
            self.vix_change_label.setStyleSheet(f"font-size: 10px; color: {chg_color};")
        else:
            self.vix_change_label.setText("")

    def _on_fg_click(self, event):
        """Handle click on Fear & Greed score to open chart dialog."""
        try:
            from canslim_monitor.gui.sentiment_chart_dialog import SentimentChartDialog
            dialog = SentimentChartDialog(self._get_db_session_factory(), parent=self)
            dialog.exec()
        except ImportError:
            pass
        except Exception as e:
            logger = logging.getLogger('canslim.gui')
            logger.warning(f"Could not open sentiment chart: {e}")

    def _get_db_session_factory(self):
        """Get database session factory from the parent window."""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'db'):
                return parent.db.get_new_session
            parent = parent.parent() if hasattr(parent, 'parent') else None
        return None

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
                         open_pct: float = None, week_pct: float = None,
                         sma21: float = None, sma50: float = None, sma200: float = None):
        """
        Update a single index box with all data.
        Only updates fields that have actual values - None values preserve existing display.

        Args:
            symbol: 'SPY', 'QQQ', 'DIA', or 'IWM'
            price: Current price
            day_pct: Day change percentage (from previous close)
            open_pct: Change from today's open (includes premarket) - used when live
            week_pct: Week change percentage - used as fallback when open_pct unavailable
            sma21: % distance from 21-day SMA
            sma50: % distance from 50-day SMA
            sma200: % distance from 200-day SMA
        """
        # Get the right box
        box = getattr(self, f"{symbol.lower()}_box", None)
        if not box:
            return

        # Helper for color coding: green=bull, red=bear, grey=neutral (±0.1%)
        def color_pct(val, show_pct=True):
            if val is None:
                return "#888", "--"
            # Color code with grey for neutral
            if abs(val) < 0.1:
                color = '#888888'  # Grey for neutral
            elif val > 0:
                color = '#28A745'  # Green for bullish
            else:
                color = '#DC3545'  # Red for bearish
            if show_pct:
                return color, f"{val:+.1f}%"
            else:
                return color, f"{val:+.1f}"

        # Update top row (symbol + price) - ONLY if price provided
        if price is not None:
            price_str = f"${price:.2f}"
            box.top_label.setText(f"<b>{symbol}</b> {price_str}")

        # Update change row - ONLY if at least one change value provided
        if open_pct is not None or week_pct is not None or day_pct is not None:
            # Show O (open change) if available, else W (week change)
            if open_pct is not None:
                o_color, o_text = color_pct(open_pct)
                label = "O"  # Open change (live)
            elif week_pct is not None:
                o_color, o_text = color_pct(week_pct)
                label = "W"  # Week change (historical fallback)
            else:
                o_color, o_text = "#888", "--"
                label = "O"
            d_color, d_text = color_pct(day_pct)
            box.change_label.setText(
                f"<span style='color:#888'>{label}:</span><span style='color:{o_color}'>{o_text}</span> "
                f"<span style='color:#888'>D:</span><span style='color:{d_color}'>{d_text}</span>"
            )

        # Update SMA row - ONLY if at least one SMA value provided
        if sma21 is not None or sma50 is not None or sma200 is not None:
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
        """Display the analysis results matching the Discord alert format."""
        self.progress_group.setVisible(False)
        self.results_group.setVisible(True)
        self.close_btn.setEnabled(True)

        lines = []

        # Header
        lines.append("━" * 50)
        lines.append("🏛️ MORNING MARKET REGIME ALERT")
        lines.append(f"   {results.get('date', 'Today')}")
        lines.append("━" * 50)

        # IBD Status (if available)
        ibd_status = results.get('ibd_status')
        if ibd_status:
            ibd_emoji = {"CONFIRMED_UPTREND": "🟢", "UPTREND_UNDER_PRESSURE": "🟡",
                         "RALLY_ATTEMPT": "🟠", "CORRECTION": "🔴"}.get(ibd_status, "⚪")
            exposure = results.get('exposure', '40-60%')
            lines.append(f"📊 IBD STATUS: {ibd_emoji} {ibd_status.replace('_', ' ')} | {exposure}")
            lines.append("")

        # D-Day Count (compact table)
        lines.append("📊 D-DAY COUNT (25-Day Rolling)")
        spy_count = results.get('spy_count', 0)
        qqq_count = results.get('qqq_count', 0)
        spy_delta = results.get('spy_delta', 0)
        qqq_delta = results.get('qqq_delta', 0)
        trend = results.get('trend', 'STABLE')
        trend_emoji = "🔴" if trend == "WORSENING" else "🟢" if trend == "IMPROVING" else "🟡"

        lines.append("┌───────┬─────┬──────┬────────────┐")
        lines.append("│ Index │ Cnt │ 5d Δ │ Trend      │")
        lines.append("├───────┼─────┼──────┼────────────┤")
        lines.append(f"│ SPY   │  {spy_count}  │  {spy_delta:+2d}  │ {trend:<10} │")
        lines.append(f"│ QQQ   │  {qqq_count}  │  {qqq_delta:+2d}  │ {trend:<10} │")
        lines.append("└───────┴─────┴──────┴────────────┘")
        lines.append(f"{trend_emoji} Trend: {trend}")
        lines.append("")

        # D-Day Histogram (35 calendar days to match Discord format)
        if results.get('spy_dates') or results.get('qqq_dates'):
            lines.append("📅 D-Day Timeline (■=D-day)")
            spy_histogram = self._build_histogram(results.get('spy_dates', []))
            qqq_histogram = self._build_histogram(results.get('qqq_dates', []))
            lines.append(f"SPY[{spy_count}]: {spy_histogram}")
            lines.append(f"QQQ[{qqq_count}]: {qqq_histogram}")
            lines.append("        ← 5wk ago          Today →")
            lines.append("")

        # Overnight Futures (always shown, matching Discord format)
        overnight = results.get('overnight')
        if overnight:
            futures_emoji = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}
            es_e = futures_emoji.get(overnight.es_trend.value if hasattr(overnight.es_trend, 'value') else str(overnight.es_trend), "🟡")
            nq_e = futures_emoji.get(overnight.nq_trend.value if hasattr(overnight.nq_trend, 'value') else str(overnight.nq_trend), "🟡")
            ym_e = futures_emoji.get(overnight.ym_trend.value if hasattr(overnight.ym_trend, 'value') else str(overnight.ym_trend), "🟡")
            lines.append("🌙 OVERNIGHT FUTURES")
            lines.append(f"┌──────────────┬──────────────┬──────────────┐")
            lines.append(f"│ ES {overnight.es_change_pct:+.2f}%    │ NQ {overnight.nq_change_pct:+.2f}%    │ YM {overnight.ym_change_pct:+.2f}%    │")
            lines.append(f"└──────────────┴──────────────┴──────────────┘")
            lines.append(f"   {es_e} ES  {nq_e} NQ  {ym_e} YM")
            lines.append("")

        # Market Phase / FTD
        lines.append("🎯 MARKET PHASE")
        phase = results.get('market_phase', 'UNKNOWN')
        phase_emoji = {"CONFIRMED_UPTREND": "🟢", "UPTREND_PRESSURE": "🟡",
                       "RALLY_ATTEMPT": "🟠", "CORRECTION": "🔴"}.get(phase, "⚪")
        lines.append(f"   {phase_emoji} {phase.replace('_', ' ')}")

        if results.get('in_rally_attempt'):
            rally_day = results.get('rally_day', 0)
            visual = '+' * min(rally_day, 10)
            if results.get('has_confirmed_ftd'):
                visual = visual[:-1] + '✓' if visual else '✓'
            lines.append(f"   Day {rally_day}: [{visual}]")
        if results.get('has_confirmed_ftd'):
            ftd_date = results.get('ftd_date')
            ftd_date_str = f" ({ftd_date.strftime('%b %d, %Y')})" if ftd_date else ""
            days_ago = results.get('days_since_ftd')
            days_str = f" — {days_ago} day{'s' if days_ago != 1 else ''} ago" if days_ago else ""
            lines.append(f"   ✅ Follow-Through Day Confirmed{ftd_date_str}{days_str}")
        lines.append("")

        # Entry Risk (if available)
        entry_risk = results.get('entry_risk_level')
        entry_score = results.get('entry_risk_score', 0)
        if entry_risk:
            risk_emoji = {"LOW": "🟢", "MODERATE": "🟡", "ELEVATED": "🟠", "HIGH": "🔴"}.get(entry_risk, "⚪")
            lines.append(f"⚠️ ENTRY RISK: {risk_emoji} {entry_risk} ({entry_score:+.2f})")
            lines.append("")

        # Index Performance Table (KEEP THIS - user requested)
        lines.append("━" * 50)
        lines.append("📈 INDEX PERFORMANCE")
        spy_stats = results.get('spy_stats', {})
        qqq_stats = results.get('qqq_stats', {})
        dia_stats = results.get('dia_stats', {})
        iwm_stats = results.get('iwm_stats', {})

        if spy_stats or qqq_stats:
            lines.append("┌───────┬──────────┬────────┬────────┬────────┬────────┬─────────┐")
            lines.append("│ Index │  Price   │  Day   │  Week  │ 21-SMA │ 50-SMA │ 200-SMA │")
            lines.append("├───────┼──────────┼────────┼────────┼────────┼────────┼─────────┤")

            for symbol, stats in [('SPY', spy_stats), ('QQQ', qqq_stats), ('DIA', dia_stats), ('IWM', iwm_stats)]:
                if stats:
                    price = stats.get('price', 0)
                    day = stats.get('day_pct', 0)
                    week = stats.get('week_pct', 0)
                    s21 = stats.get('sma21', 0)
                    s50 = stats.get('sma50', 0)
                    s200 = stats.get('sma200', 0)
                    lines.append(f"│ {symbol:<5} │ ${price:>7.2f} │ {day:>+5.1f}% │ {week:>+5.1f}% │ {s21:>+5.1f}% │ {s50:>+5.1f}% │ {s200:>+6.1f}% │")

            lines.append("└───────┴──────────┴────────┴────────┴────────┴────────┴─────────┘")
        lines.append("")

        # Composite Score & Regime
        lines.append("━" * 50)
        score = results.get('composite_score', 0)
        regime = results.get('regime', 'NEUTRAL')
        regime_emoji = "🟢" if regime == "BULLISH" else "🔴" if regime == "BEARISH" else "🟡"

        # Score bar visualization
        score_normalized = (score + 1.5) / 3.0
        score_normalized = max(0, min(1, score_normalized))
        bar_width = 30
        filled = int(score_normalized * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        lines.append(f"🏆 REGIME: {regime_emoji} {regime} (Score: {score:+.2f})")
        lines.append(f"   [{bar}]")

        # Exposure
        exposure = results.get('exposure', '40-60%')
        lines.append(f"💰 EXPOSURE: {exposure}")
        lines.append("")

        # Sentiment (F&G + VIX)
        fg_data = results.get('fg_data')
        vix_data = results.get('vix_data')
        if fg_data or vix_data:
            lines.append("━" * 50)
            lines.append("📊 SENTIMENT")
            if fg_data:
                fg_change_str = ""
                if fg_data.previous_close and fg_data.previous_close > 0:
                    fg_delta = fg_data.score - fg_data.previous_close
                    fg_change_str = f" ({fg_delta:+.1f} from yesterday)"
                lines.append(f"   CNN F&G: {fg_data.score:.1f} — {fg_data.rating}{fg_change_str}")
            if vix_data:
                from canslim_monitor.regime.vix_client import classify_vix
                vix_rating = classify_vix(vix_data.close)
                vix_change_str = ""
                if vix_data.previous_close and vix_data.previous_close > 0:
                    vix_delta = vix_data.close - vix_data.previous_close
                    vix_change_str = f" ({vix_delta:+.2f} from yesterday)"
                lines.append(f"   VIX:     {vix_data.close:.2f} — {vix_rating}{vix_change_str}")
            lines.append("")

        # Guidance (compact)
        lines.append("📋 GUIDANCE")
        max_d = max(spy_count, qqq_count)
        if max_d >= 6:
            lines.append(f"   ⚠️ High D-days ({max_d}) - defensive posture")

        if regime == "BEARISH" or phase == "CORRECTION":
            lines.append("   → Honor stops strictly")
            lines.append("   → Avoid new breakout entries")
            lines.append("   → Wait for follow-through day")
        elif regime == "NEUTRAL" or "PRESSURE" in phase:
            lines.append("   → Reduce position sizes")
            lines.append("   → Only highest-conviction setups")
            lines.append("   → Tighten stops on existing")
        else:
            lines.append("   → Environment supports new positions")
            lines.append("   → Look for breakouts from sound bases")
            lines.append("   → Let winners run")

        lines.append("")
        lines.append("━" * 50)

        self.results_text.setText("\n".join(lines))

    def _build_histogram(self, dates: list, lookback_start=None, lookback_days: int = 35) -> str:
        """Build ASCII histogram of distribution days (matches discord_regime format).

        Uses 35 calendar days to cover all 25 trading days (weekends/holidays).
        """
        from datetime import date, timedelta

        ref_date = date.today()

        if not dates:
            return "·" * lookback_days

        # Convert string dates to date objects
        date_set = set()
        for d in dates:
            if isinstance(d, str):
                try:
                    date_set.add(date.fromisoformat(d))
                except ValueError:
                    pass
            elif hasattr(d, 'date'):
                date_set.add(d.date())
            else:
                date_set.add(d)

        # Build day-by-day array (index 0 = oldest, last = today)
        ddays = [False] * lookback_days
        for d in date_set:
            days_ago = (ref_date - d).days
            if 0 <= days_ago < lookback_days:
                ddays[lookback_days - 1 - days_ago] = True

        return ''.join(['■' if d else '·' for d in ddays])
    
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

        # Card tracking for incremental price updates (symbol -> card)
        self._cards_by_symbol: Dict[str, 'PositionCard'] = {}

        # IBKR client (lazy initialized)
        self.ibkr_client = None
        self.ibkr_connected = False
        
        # Price update worker thread
        self.price_worker = None
        self.price_thread = None
        self.price_update_in_progress = False
        
        # Child windows
        self._table_view = None  # Position database spreadsheet view
        
        # GUI refresh intervals from config (with sensible defaults)
        gui_config = self.config.get('gui', {})
        price_interval = gui_config.get('price_refresh_interval', 60)  # Default 60 seconds
        futures_interval = gui_config.get('futures_refresh_interval', 30)  # Default 30 seconds

        # Price update timer
        self.price_timer = QTimer()
        self.price_timer.timeout.connect(self._update_prices)
        self.price_update_interval = price_interval * 1000  # Convert to ms

        # Futures update timer
        self.futures_timer = QTimer()
        self.futures_timer.timeout.connect(self._update_futures)
        self.futures_update_interval = futures_interval * 1000  # Convert to ms

        self.logger.info(f"GUI refresh intervals: prices={price_interval}s, futures={futures_interval}s")

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
        self._load_index_stats()    # Load index SMAs in background
    
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

            # Connect toggle signal for watching column (state 0)
            if state == 0:
                column.view_toggled.connect(self._on_watching_column_toggled)

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

        score_action = QAction("📊 &Score Symbol...", self)
        score_action.setShortcut("Ctrl+Shift+S")
        score_action.setToolTip("Preview score for a symbol before adding to watchlist")
        score_action.triggered.connect(self._on_score_symbol)
        position_menu.addAction(score_action)

        position_menu.addSeparator()

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

        service_menu.addSeparator()

        earnings_action = QAction("&Update All Earnings Dates", self)
        earnings_action.triggered.connect(self._on_update_all_earnings)
        service_menu.addAction(earnings_action)

        volume_action = QAction("&Seed 50-Day Volume Data", self)
        volume_action.triggered.connect(self._on_seed_volume_data)
        service_menu.addAction(volume_action)

        # Reports menu
        reports_menu = menubar.addMenu("&Reports")

        weekly_report_action = QAction("📝 &Weekly Watchlist Report...", self)
        weekly_report_action.triggered.connect(self._on_weekly_report)
        reports_menu.addAction(weekly_report_action)

        reports_menu.addSeparator()

        analytics_action = QAction("📊 &Analytics Dashboard...", self)
        analytics_action.triggered.connect(self._on_analytics_dashboard)
        reports_menu.addAction(analytics_action)

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
            self._cards_by_symbol.clear()  # Clear card tracking

            # Check if watching column is showing Exited Watch (-1.5)
            watching_column = self.columns.get(0)
            showing_exited_watch = watching_column and watching_column.is_showing_exited_watch()

            # Add cards to appropriate columns
            closed_count = 0
            for pos in positions:
                # Get the latest alert for this position (if any)
                latest_alert = latest_alerts.get(pos.id)
                card = self._create_card(pos, latest_alert=latest_alert)

                # Track card by symbol for incremental updates
                if pos.symbol:
                    self._cards_by_symbol[pos.symbol] = card

                # Handle State -1.5 positions
                if pos.state == -1.5:
                    if showing_exited_watch and watching_column:
                        # Show in watching column when toggled to Exited Watch
                        watching_column.add_card(card)
                    else:
                        # Otherwise show in closed panel
                        self.closed_panel.add_card(card)
                        closed_count += 1
                    self.logger.debug(f"Added exited watch position: {pos.symbol}")
                elif pos.state < 0:
                    # Other closed/stopped positions (-1, -2)
                    self.closed_panel.add_card(card)
                    closed_count += 1
                    self.logger.debug(f"Added closed position: {pos.symbol} (state {pos.state})")
                elif pos.state == 0 and showing_exited_watch:
                    # If watching column is showing -1.5, State 0 goes to closed panel temporarily
                    # Actually, this doesn't make sense. Let's skip State 0 when showing -1.5
                    pass  # Don't show State 0 cards when in Exited Watch mode
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

                    # Update Fear & Greed — use latest alert or fall back to most recent with data
                    fg_source = latest if (hasattr(latest, 'fear_greed_score') and latest.fear_greed_score is not None) else None
                    if not fg_source:
                        fg_source = session.query(MarketRegimeAlert).filter(
                            MarketRegimeAlert.fear_greed_score.isnot(None)
                        ).order_by(MarketRegimeAlert.date.desc()).first()
                    if fg_source and fg_source.fear_greed_score is not None:
                        self.regime_banner.update_fear_greed(
                            score=fg_source.fear_greed_score,
                            rating=fg_source.fear_greed_rating
                        )
                        self.logger.info(
                            f"Loaded F&G: {fg_source.fear_greed_score:.1f} ({fg_source.fear_greed_rating}) from {fg_source.date}"
                        )

                    # Update VIX — use latest alert or fall back to most recent with data
                    vix_source = latest if (hasattr(latest, 'vix_close') and latest.vix_close is not None) else None
                    if not vix_source:
                        vix_source = session.query(MarketRegimeAlert).filter(
                            MarketRegimeAlert.vix_close.isnot(None)
                        ).order_by(MarketRegimeAlert.date.desc()).first()
                    if vix_source and vix_source.vix_close is not None:
                        self.regime_banner.update_vix(
                            price=vix_source.vix_close,
                            prev_close=vix_source.vix_previous_close
                        )
                        self.logger.info(
                            f"Loaded VIX: {vix_source.vix_close:.2f} (prev: {vix_source.vix_previous_close}) from {vix_source.date}"
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

    def _load_index_stats(self, background: bool = True):
        """
        Load index statistics (prices, SMAs) from Polygon API.

        Called on GUI startup and after IBKR connects to populate SMA data.

        Args:
            background: If True, run in background thread (non-blocking)
        """
        if background:
            # Run in background to avoid blocking GUI
            import threading
            thread = threading.Thread(target=self._fetch_and_update_index_stats, daemon=True)
            thread.start()
        else:
            self._fetch_and_update_index_stats()

    def _fetch_and_update_index_stats(self):
        """Fetch index data from Polygon and update banner with SMAs."""
        try:
            import yaml

            # Load config for API key
            config = getattr(self, 'config', {}) or {}
            if not config:
                config_paths = ['user_config.yaml', 'config.yaml']
                for path in config_paths:
                    import os
                    if os.path.exists(path):
                        with open(path, 'r') as f:
                            config = yaml.safe_load(f) or {}
                        break

            polygon_key = (
                config.get('market_data', {}).get('api_key') or
                config.get('polygon', {}).get('api_key')
            )

            if not polygon_key:
                self.logger.debug("No Polygon API key - skipping index stats load")
                return

            self.logger.info("Loading index stats from Polygon...")

            # Import and fetch data
            from canslim_monitor.regime.historical_data import fetch_index_daily

            api_config = {'polygon': {'api_key': polygon_key}}
            data = fetch_index_daily(
                symbols=['SPY', 'QQQ', 'DIA', 'IWM'],
                lookback_days=300,  # Need 300 calendar days to get 200+ trading days for SMA
                config=api_config,
                use_indices=False
            )

            if not data:
                self.logger.warning("No data returned from Polygon")
                return

            spy_bars = data.get('SPY', [])
            qqq_bars = data.get('QQQ', [])
            dia_bars = data.get('DIA', [])
            iwm_bars = data.get('IWM', [])

            self.logger.info(
                f"Fetched bars - SPY: {len(spy_bars)}, QQQ: {len(qqq_bars)}, "
                f"DIA: {len(dia_bars)}, IWM: {len(iwm_bars)} "
                f"(need 200+ for 200-day SMA)"
            )
            if len(spy_bars) < 200:
                self.logger.warning(f"SPY has only {len(spy_bars)} bars - 200 SMA will show 0")

            # Calculate stats
            spy_stats = self._calculate_index_stats(spy_bars) if spy_bars else {}
            qqq_stats = self._calculate_index_stats(qqq_bars) if qqq_bars else {}
            dia_stats = self._calculate_index_stats(dia_bars) if dia_bars else {}
            iwm_stats = self._calculate_index_stats(iwm_bars) if iwm_bars else {}

            # Update banner (must be done on main thread)
            from PyQt6.QtCore import QMetaObject, Qt, Q_ARG

            # Use invokeMethod to safely update from background thread
            if spy_stats:
                self._update_index_box_safe('SPY', spy_stats)
                self._cached_spy_stats = {
                    'week_pct': spy_stats.get('week_pct'),
                    'sma21': spy_stats.get('sma21'),
                    'sma50': spy_stats.get('sma50'),
                    'sma200': spy_stats.get('sma200')
                }
            if qqq_stats:
                self._update_index_box_safe('QQQ', qqq_stats)
                self._cached_qqq_stats = {
                    'week_pct': qqq_stats.get('week_pct'),
                    'sma21': qqq_stats.get('sma21'),
                    'sma50': qqq_stats.get('sma50'),
                    'sma200': qqq_stats.get('sma200')
                }
            if dia_stats:
                self._update_index_box_safe('DIA', dia_stats)
                self._cached_dia_stats = {
                    'week_pct': dia_stats.get('week_pct'),
                    'sma21': dia_stats.get('sma21'),
                    'sma50': dia_stats.get('sma50'),
                    'sma200': dia_stats.get('sma200')
                }
            if iwm_stats:
                self._update_index_box_safe('IWM', iwm_stats)
                self._cached_iwm_stats = {
                    'week_pct': iwm_stats.get('week_pct'),
                    'sma21': iwm_stats.get('sma21'),
                    'sma50': iwm_stats.get('sma50'),
                    'sma200': iwm_stats.get('sma200')
                }

            self.logger.info("Index stats loaded successfully")

        except Exception as e:
            self.logger.warning(f"Could not load index stats: {e}")

    def _update_index_box_safe(self, symbol: str, stats: dict):
        """Thread-safe update of index box via signal."""
        from PyQt6.QtCore import QTimer
        # Use QTimer.singleShot to run on main thread
        QTimer.singleShot(0, lambda: self.regime_banner.update_index_box(
            symbol,
            price=stats.get('price'),
            day_pct=stats.get('day_pct'),
            week_pct=stats.get('week_pct'),
            sma21=stats.get('sma21'),
            sma50=stats.get('sma50'),
            sma200=stats.get('sma200')
        ))

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
                
                # Create history table (schema matches regime/models_regime.py)
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS ibd_exposure_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        effective_date DATE NOT NULL,
                        market_status VARCHAR(30) NOT NULL,
                        exposure_min INTEGER NOT NULL,
                        exposure_max INTEGER NOT NULL,
                        distribution_days_spy INTEGER,
                        distribution_days_qqq INTEGER,
                        notes VARCHAR(500),
                        source VARCHAR(50) DEFAULT 'MarketSurge',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
                    (effective_date, market_status, exposure_min, exposure_max, notes, source, created_at)
                    VALUES (:effective_date, :status, :min, :max, :notes, :source, :created_at)
                """), {
                    'effective_date': datetime.now().date(),
                    'status': status, 'min': min_exp, 'max': max_exp,
                    'notes': notes, 'source': 'GUI', 'created_at': datetime.now()
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

            # Map exit_* fields to close_* fields for Position model compatibility
            # TransitionDialog uses exit_price/date/reason but Position model uses close_*
            if to_state < 0:
                if 'exit_price' in result:
                    result['close_price'] = result['exit_price']
                if 'exit_date' in result:
                    result['close_date'] = result['exit_date']
                if 'exit_reason' in result:
                    result['close_reason'] = result['exit_reason']

                # Calculate realized P&L
                close_price = result.get('close_price') or result.get('exit_price', 0)
                avg_cost = position.avg_cost or 0

                if close_price and avg_cost > 0:
                    result['realized_pnl_pct'] = ((close_price - avg_cost) / avg_cost) * 100

                    # Calculate dollar P&L based on total shares at exit
                    total_shares = position.total_shares or 0
                    if total_shares > 0:
                        result['realized_pnl'] = (close_price - avg_cost) * total_shares

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

    def _on_watching_column_toggled(self, new_state: float):
        """
        Handle toggle between Watching (0) and Exited Watch (-1.5) in the first column.

        Args:
            new_state: The state now being displayed (0 or -1.5)
        """
        self.logger.info(f"Watching column toggled to state: {new_state}")

        # Get the watching column (stored under key 0)
        watching_column = self.columns.get(0)
        if not watching_column:
            return

        # Clear existing cards in the column
        watching_column.clear_cards()

        # Load positions for the new state
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)

            if new_state == -1.5:
                # Load State -1.5 positions
                positions = repos.positions.get_watching_exited()
            else:
                # Load State 0 positions
                positions = repos.positions.get_by_state(0)

            self.logger.info(f"Loading {len(positions)} positions for state {new_state}")

            # Get alerts for these positions
            position_ids = [pos.id for pos in positions]
            latest_alerts = self._get_latest_alerts_for_positions(session, position_ids)

            # Add cards to the column
            for pos in positions:
                latest_alert = latest_alerts.get(pos.id)
                card = self._create_card(pos, latest_alert=latest_alert)

                # Track card by symbol
                if pos.symbol:
                    self._cards_by_symbol[pos.symbol] = card

                watching_column.add_card(card)

            state_name = "Exited Watch" if new_state == -1.5 else "Watching"
            self.status_bar.showMessage(f"Showing {len(positions)} {state_name} positions")

        finally:
            session.close()

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
                'prior_fund_count': position.prior_fund_count,
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
                # Exit / Close
                'tp1_sold': position.tp1_sold,
                'tp1_price': position.tp1_price,
                'tp1_date': position.tp1_date,
                'tp2_sold': position.tp2_sold,
                'tp2_price': position.tp2_price,
                'tp2_date': position.tp2_date,
                'close_price': position.close_price,
                'close_date': position.close_date,
                'close_reason': position.close_reason,
                'realized_pnl': position.realized_pnl,
                'realized_pnl_pct': position.realized_pnl_pct,
                # Dates
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

        # Logging for edit save (INFO level for visibility)
        self.logger.info(f"=== EDIT SAVE: {symbol} (id={position_id}) ===")
        key_fields = ['stop_price', 'pivot', 'hard_stop_pct', 'pattern', 'base_stage',
                      'close_price', 'close_date', 'close_reason', 'realized_pnl', 'realized_pnl_pct',
                      'tp1_sold', 'tp1_price', 'tp2_sold', 'tp2_price']
        for key in key_fields:
            if key in result and result[key] is not None:
                self.logger.info(f"  INPUT {key}: {result[key]}")

        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)

            # Update position
            repos.positions.update_by_id(position_id, **result)
            session.commit()

            # Verify save by re-reading from database
            updated_position = repos.positions.get_by_id(position_id)
            if updated_position:
                self.logger.info(f"  SAVED stop_price: {updated_position.stop_price}")
                self.logger.info(f"  SAVED pivot: {updated_position.pivot}")
                self.logger.info(f"  SAVED hard_stop_pct: {updated_position.hard_stop_pct}")
                self.logger.info(f"  SAVED close_price: {updated_position.close_price}")
                self.logger.info(f"  SAVED close_date: {updated_position.close_date}")
                self.logger.info(f"  SAVED realized_pnl: {updated_position.realized_pnl}")
            
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

            # Check alerts action (real-time status check)
            check_alerts_action = menu.addAction("🔍 Check Alerts")
            check_alerts_action.triggered.connect(lambda: self._check_position_alerts(position_id))

            # View history action
            history_action = menu.addAction("📜 View History")
            history_action.triggered.connect(lambda: self._show_position_history(position_id))

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

                # Exit to Re-entry Watch (State -1.5)
                reentry_watch_action = menu.addAction("👁️ Exit to Re-entry Watch")
                reentry_watch_action.setToolTip("Exit position but monitor for MA bounce or pivot retest re-entry")
                reentry_watch_action.triggered.connect(
                    lambda: self._exit_to_reentry_watch(position_id)
                )

                close_action = menu.addAction("✅ Close Position")
                close_action.triggered.connect(
                    lambda: self._trigger_transition(position_id, position.state, -1)
                )

            # State -1.5 (Exited Watch) specific actions
            elif position.state == -1.5:
                # Re-enter from watching exited
                reenter_action = menu.addAction("🚀 Re-enter Position")
                reenter_action.setToolTip("Re-enter this position (MA bounce or pivot retest)")
                reenter_action.triggered.connect(
                    lambda: self._reenter_from_watching_exited(position_id)
                )

                # Return to regular watchlist with new pivot
                return_watchlist_action = menu.addAction("📋 Return to Watchlist")
                return_watchlist_action.setToolTip("Move back to watchlist with a new pivot (new base forming)")
                return_watchlist_action.triggered.connect(
                    lambda: self._return_to_watchlist_from_watching_exited(position_id)
                )

                menu.addSeparator()

                # Archive (give up on re-entry)
                archive_action = menu.addAction("🗄️ Archive (Give Up)")
                archive_action.setToolTip("Stop monitoring - move to Stopped Out")
                archive_action.triggered.connect(
                    lambda: self._remove_from_watching_exited(position_id, -2)
                )

                # Close (manual removal)
                close_action = menu.addAction("✅ Close (Remove)")
                close_action.setToolTip("Remove from re-entry watch - move to Closed")
                close_action.triggered.connect(
                    lambda: self._remove_from_watching_exited(position_id, -1)
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

    def _show_position_history(self, position_id: int):
        """Show the change history for a position in spreadsheet comparison view."""
        try:
            from canslim_monitor.gui.position_history_dialog import PositionHistoryDialog
            from canslim_monitor.data.repositories import HistoryRepository

            session = self.db.get_new_session()
            try:
                repos = RepositoryManager(session)
                position = repos.positions.get_by_id(position_id)

                if not position:
                    QMessageBox.warning(self, "Error", "Position not found")
                    return

                # Get history using the history repository
                history_repo = HistoryRepository(session)
                history_records = history_repo.get_position_history(position_id, limit=200)

                # Convert to list of dicts for the dialog
                history = []
                for record in history_records:
                    history.append({
                        'field_name': record.field_name,
                        'old_value': record.old_value,
                        'new_value': record.new_value,
                        'changed_at': record.changed_at,
                        'change_source': record.change_source,
                    })

                # Build current position dict with all tracked fields
                current_position = {
                    'symbol': position.symbol,
                    'portfolio': position.portfolio,
                    'pattern': position.pattern,
                    'pivot': position.pivot,
                    'stop_price': position.stop_price,
                    'hard_stop_pct': position.hard_stop_pct,
                    'tp1_pct': position.tp1_pct,
                    'tp2_pct': position.tp2_pct,
                    'state': position.state,
                    'watch_date': position.watch_date,
                    'entry_date': position.entry_date,
                    'breakout_date': position.breakout_date,
                    'earnings_date': position.earnings_date,
                    'e1_shares': position.e1_shares,
                    'e1_price': position.e1_price,
                    'e1_date': getattr(position, 'e1_date', None),
                    'e2_shares': position.e2_shares,
                    'e2_price': position.e2_price,
                    'e2_date': getattr(position, 'e2_date', None),
                    'e3_shares': position.e3_shares,
                    'e3_price': position.e3_price,
                    'e3_date': getattr(position, 'e3_date', None),
                    'tp1_sold': position.tp1_sold,
                    'tp1_price': position.tp1_price,
                    'tp1_date': getattr(position, 'tp1_date', None),
                    'tp2_sold': position.tp2_sold,
                    'tp2_price': position.tp2_price,
                    'tp2_date': getattr(position, 'tp2_date', None),
                    'total_shares': position.total_shares,
                    'avg_cost': position.avg_cost,
                    'rs_rating': position.rs_rating,
                    'rs_3mo': position.rs_3mo,
                    'rs_6mo': position.rs_6mo,
                    'eps_rating': position.eps_rating,
                    'comp_rating': position.comp_rating,
                    'smr_rating': position.smr_rating,
                    'ad_rating': position.ad_rating,
                    'ud_vol_ratio': position.ud_vol_ratio,
                    'industry_rank': position.industry_rank,
                    'fund_count': position.fund_count,
                    'prior_fund_count': position.prior_fund_count,
                    'funds_qtr_chg': position.funds_qtr_chg,
                    'base_stage': position.base_stage,
                    'base_depth': position.base_depth,
                    'base_length': position.base_length,
                    'prior_uptrend': position.prior_uptrend,
                    'breakout_vol_pct': position.breakout_vol_pct,
                    'breakout_price_pct': position.breakout_price_pct,
                    'close_price': position.close_price,
                    'close_date': position.close_date,
                    'close_reason': position.close_reason,
                    'realized_pnl': position.realized_pnl,
                    'realized_pnl_pct': position.realized_pnl_pct,
                    'entry_grade': position.entry_grade,
                    'entry_score': position.entry_score,
                    'tp1_target': position.tp1_target,
                    'tp2_target': position.tp2_target,
                    'original_pivot': getattr(position, 'original_pivot', None),
                    'ma_test_count': getattr(position, 'ma_test_count', None),
                    'py1_done': getattr(position, 'py1_done', None),
                    'py2_done': getattr(position, 'py2_done', None),
                    'notes': position.notes,
                }

                # Show dialog
                dialog = PositionHistoryDialog(
                    symbol=position.symbol,
                    position_id=position_id,
                    current_position=current_position,
                    history=history,
                    parent=self
                )
                dialog.exec()

                self.logger.info(f"Opened history dialog for {position.symbol} with {len(history)} records")

            finally:
                session.close()

        except Exception as e:
            self.logger.error(f"Error showing position history: {e}")
            QMessageBox.warning(self, "Error", f"Failed to load history: {e}")

    def _check_position_alerts(self, position_id: int):
        """
        Run real-time alert checks against a position.

        This is a status check tool that runs checkers against the position
        with current data. It does NOT store alerts in the database or send
        Discord notifications.

        Routing:
        - State 0 (Watching): Runs breakout checks (pivot, volume, buy zone)
        - State 1+ (Positions): Runs position checks (stop, profit, pyramid, MA, health)
        """
        try:
            from canslim_monitor.gui.alerts.alert_check_dialog import AlertCheckDialog
            from canslim_monitor.services.technical_data_service import TechnicalDataService

            session = self.db.get_new_session()
            try:
                repos = RepositoryManager(session)
                position = repos.positions.get_by_id(position_id)

                if not position:
                    QMessageBox.warning(self, "Error", "Position not found")
                    return

                # Get current price - use last_price from position or try to get fresh price
                current_price = position.last_price or position.pivot or 0

                if current_price <= 0:
                    QMessageBox.warning(
                        self,
                        "No Price Data",
                        f"No price data available for {position.symbol}. "
                        "Try refreshing prices first."
                    )
                    return

                # Get market regime if available
                market_regime = ""
                try:
                    latest_regime = repos.market_regime.get_latest()
                    if latest_regime:
                        market_regime = latest_regime.regime
                except Exception:
                    pass

                # Route based on position state
                if position.state == 0:
                    # WATCHING (State 0) → Breakout checks
                    alerts, position_summary, check_summary = self._run_breakout_checks(
                        position, current_price, market_regime
                    )
                else:
                    # POSITION (State 1+) → Position checks
                    alerts, position_summary, check_summary = self._run_position_checks(
                        position, current_price, market_regime
                    )

                # Show dialog
                dialog = AlertCheckDialog(
                    symbol=position.symbol,
                    position_summary=position_summary,
                    alerts=alerts,
                    check_summary=check_summary,
                    parent=self,
                )
                dialog.show()  # Modeless

                self.logger.info(
                    f"Alert check for {position.symbol}: {len(alerts)} alerts at ${current_price:.2f}"
                )

            finally:
                session.close()

        except Exception as e:
            self.logger.error(f"Error checking position alerts: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Error", f"Failed to check alerts: {e}")

    def _run_breakout_checks(self, position, current_price: float, market_regime: str):
        """
        Run breakout checks for watchlist (State 0) positions.

        Also runs WatchlistAltEntryChecker for MA pullback opportunities
        on stocks that were previously extended.

        Returns:
            Tuple of (alerts, position_summary, check_summary)
        """
        from canslim_monitor.core.position_monitor.breakout_checker_tool import BreakoutCheckerTool
        from canslim_monitor.services.technical_data_service import TechnicalDataService

        # Get volume data from position attributes
        volume = getattr(position, 'last_volume', 0) or 0
        avg_volume = getattr(position, 'avg_volume_50d', 0) or 500000
        high = getattr(position, 'last_high', current_price) or current_price
        low = getattr(position, 'last_low', current_price) or current_price

        # Fetch technical data (MAs) for alt entry checks
        technical_data = {}
        polygon_api_key = (
            self.config.get('polygon', {}).get('api_key') or
            self.config.get('market_data', {}).get('api_key')
        )
        if polygon_api_key:
            try:
                tech_service = TechnicalDataService(
                    polygon_api_key=polygon_api_key,
                    cache_duration_hours=4,
                    logger=self.logger
                )
                technical_data = tech_service.get_technical_data(position.symbol)
                self.logger.debug(
                    f"Fetched MAs for {position.symbol}: "
                    f"21={technical_data.get('ma_21')}, "
                    f"50={technical_data.get('ma_50')}"
                )
            except Exception as e:
                self.logger.warning(f"Could not fetch technical data for alt entry: {e}")

        # Create breakout checker tool (also includes WatchlistAltEntryChecker)
        checker_tool = BreakoutCheckerTool(
            config=self.config,
            logger=self.logger
        )

        # Run breakout checks + alt entry checks
        alerts = checker_tool.check_position(
            position=position,
            current_price=current_price,
            volume=volume,
            avg_volume=avg_volume,
            high=high,
            low=low,
            market_regime=market_regime,
            technical_data=technical_data,
        )

        # Build position summary for dialog header (watchlist-specific)
        pivot = position.pivot or 0
        distance_pct = ((current_price - pivot) / pivot * 100) if pivot > 0 else 0
        buy_zone_top = pivot * 1.05 if pivot > 0 else 0

        state_name = ""
        if position.state in STATES:
            state_name = f"{STATES[position.state].display_name} ({position.state})"

        position_summary = {
            'current_price': current_price,
            'entry_price': pivot,  # Pivot serves as reference for watchlist
            'pnl_pct': distance_pct,  # Distance from pivot
            'state_name': state_name,
        }

        # Build check summary showing breakout-specific data
        # Calculate RVOL for display
        rvol = checker_tool._calculate_rvol(volume, avg_volume) if volume > 0 else 0

        # Merge MA data with volume data
        merged_technical = {
            'pivot': pivot,
            'buy_zone_top': buy_zone_top,
            'volume': volume,
            'avg_volume': avg_volume,
            'rvol': rvol,
        }
        # Add MA data if available
        if technical_data:
            merged_technical['ma_21'] = technical_data.get('ma_21') or technical_data.get('ema_21')
            merged_technical['ma_50'] = technical_data.get('ma_50')
            merged_technical['ma_200'] = technical_data.get('ma_200')

        check_summary = {
            'checkers_run': ['breakout', 'alt_entry'],  # Now also checks alt entry
            'technical_data': merged_technical,
            'is_breakout_check': True,  # Flag for dialog to customize display
        }

        return alerts, position_summary, check_summary

    def _run_position_checks(self, position, current_price: float, market_regime: str):
        """
        Run position checks for active positions (State 1+).

        Returns:
            Tuple of (alerts, position_summary, check_summary)
        """
        from canslim_monitor.core.position_monitor.alert_checker_tool import AlertCheckerTool
        from canslim_monitor.services.technical_data_service import TechnicalDataService

        # Fetch technical data from Polygon (MAs, volume)
        technical_data = {'volume_ratio': 1.0}  # Default
        # API key can be in 'polygon.api_key' or 'market_data.api_key'
        polygon_api_key = (
            self.config.get('polygon', {}).get('api_key') or
            self.config.get('market_data', {}).get('api_key')
        )
        if polygon_api_key:
            try:
                tech_service = TechnicalDataService(
                    polygon_api_key=polygon_api_key,
                    cache_duration_hours=4,
                    logger=self.logger
                )
                technical_data = tech_service.get_technical_data(position.symbol)
                self.logger.debug(
                    f"Fetched MAs for {position.symbol}: "
                    f"21={technical_data.get('ma_21')}, "
                    f"50={technical_data.get('ma_50')}"
                )
            except Exception as e:
                self.logger.warning(f"Could not fetch technical data: {e}")
        else:
            self.logger.debug("No Polygon API key, MA-based alerts unavailable")

        # Create alert checker tool
        checker_tool = AlertCheckerTool(
            config=self.config,
            logger=self.logger
        )

        # Run checks
        alerts = checker_tool.check_position(
            position=position,
            current_price=current_price,
            technical_data=technical_data,
            market_regime=market_regime,
        )

        # Build position summary for dialog header
        entry_price = position.avg_cost or position.pivot or current_price
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        state_name = ""
        if position.state in STATES:
            state_name = f"{STATES[position.state].display_name} ({position.state})"

        position_summary = {
            'current_price': current_price,
            'entry_price': entry_price,
            'pnl_pct': pnl_pct,
            'state_name': state_name,
        }

        # Build check summary showing what was checked
        check_summary = {
            'checkers_run': ['stop', 'profit', 'pyramid', 'ma', 'health'],
            'technical_data': technical_data,
            'is_breakout_check': False,
        }

        return alerts, position_summary, check_summary

    def _trigger_transition(self, position_id: int, from_state: int, to_state: int):
        """Trigger a state transition (reuse existing drop logic)."""
        self._on_position_dropped(position_id, from_state, to_state)

    def _exit_to_reentry_watch(self, position_id: int):
        """
        Exit a position to State -1.5 (WATCHING_EXITED) for re-entry monitoring.

        Shows a dialog to collect exit price and reason, then transitions the
        position using the specialized repository method.
        """
        from canslim_monitor.gui.transition_dialogs import ExitToReentryWatchDialog

        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)

            if not position:
                self.logger.error(f"Position {position_id} not found")
                return

            if position.state < 1:
                QMessageBox.warning(
                    self,
                    "Invalid State",
                    f"Position {position.symbol} is not in an active state (state={position.state}).\n"
                    "Only positions in states 1-6 can be exited to re-entry watch."
                )
                return

            # Prepare current data for dialog
            current_data = {
                'symbol': position.symbol,
                'pivot': position.pivot,
                'stop_price': position.stop_price,
                'avg_cost': position.avg_cost,
                'total_shares': position.total_shares,
                'last_price': position.last_price,
                'entry_date': position.entry_date,
            }

            # Show dialog
            dialog = ExitToReentryWatchDialog(
                symbol=position.symbol,
                current_data=current_data,
                parent=self
            )

            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.logger.info("Exit to re-entry watch cancelled")
                return

            result = dialog.get_result()
            exit_price = result['exit_price']
            exit_reason = result['exit_reason']
            notes = result.get('notes')

            # Use the repository method to handle the transition
            repos.positions.transition_to_watching_exited(
                position=position,
                exit_price=exit_price,
                exit_reason=exit_reason,
                notes=notes
            )

            session.commit()

            self.logger.info(
                f"{position.symbol}: Exited to re-entry watch "
                f"(reason={exit_reason}, price=${exit_price:.2f})"
            )
            self.status_bar.showMessage(
                f"{position.symbol} moved to Exited Watch - monitoring for re-entry",
                5000
            )

            # Reload positions to update display
            self._load_positions()

        except Exception as e:
            session.rollback()
            self.logger.error(f"Error exiting to re-entry watch: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to exit position to re-entry watch:\n{str(e)}"
            )
        finally:
            session.close()

    def _reenter_from_watching_exited(self, position_id: int):
        """
        Re-enter a position from State -1.5 (WATCHING_EXITED).

        Shows a dialog to collect entry shares, price, and stop price.
        """
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)

            if not position:
                self.logger.error(f"Position {position_id} not found")
                return

            if position.state != -1.5:
                QMessageBox.warning(
                    self,
                    "Invalid State",
                    f"Position {position.symbol} is not in Exited Watch state."
                )
                return

            # Use the existing TransitionDialog for -1.5 → 1 transition
            current_data = {
                'symbol': position.symbol,
                'pivot': position.original_pivot or position.pivot,
                'last_price': position.last_price,
                'close_price': position.close_price,
                'close_reason': position.close_reason,
            }

            dialog = TransitionDialog(
                symbol=position.symbol,
                from_state=-1.5,
                to_state=1,
                current_data=current_data,
                parent=self
            )

            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.logger.info("Re-entry cancelled")
                return

            result = dialog.get_result()

            # Use the repository method
            repos.positions.reenter_from_watching_exited(
                position=position,
                shares=result.get('e1_shares', 0),
                entry_price=result.get('e1_price', 0),
                stop_price=result.get('stop_price', 0),
                entry_date=result.get('entry_date'),
                notes=result.get('notes')
            )

            session.commit()

            self.logger.info(f"{position.symbol}: Re-entered from Exited Watch")
            self.status_bar.showMessage(f"{position.symbol} re-entered!", 5000)

            self._load_positions()

        except Exception as e:
            session.rollback()
            self.logger.error(f"Error re-entering position: {e}")
            QMessageBox.critical(self, "Error", f"Failed to re-enter position:\n{str(e)}")
        finally:
            session.close()

    def _return_to_watchlist_from_watching_exited(self, position_id: int):
        """
        Return a State -1.5 position to regular watchlist (State 0) with new pivot.
        """
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)

            if not position:
                self.logger.error(f"Position {position_id} not found")
                return

            if position.state != -1.5:
                QMessageBox.warning(
                    self,
                    "Invalid State",
                    f"Position {position.symbol} is not in Exited Watch state."
                )
                return

            # Get new pivot price from user
            from PyQt6.QtWidgets import QInputDialog

            new_pivot, ok = QInputDialog.getDouble(
                self,
                f"New Pivot for {position.symbol}",
                "Enter the new pivot price for the fresh base pattern:",
                position.original_pivot or position.pivot or position.last_price or 100.0,
                0.01,
                99999.99,
                2
            )

            if not ok:
                return

            # Optional notes
            notes, ok = QInputDialog.getText(
                self,
                "Notes (Optional)",
                "Add notes about the new base pattern:"
            )

            repos.positions.return_to_watchlist(
                position=position,
                new_pivot=new_pivot,
                notes=notes if ok and notes else None
            )

            session.commit()

            self.logger.info(f"{position.symbol}: Returned to watchlist with pivot ${new_pivot:.2f}")
            self.status_bar.showMessage(
                f"{position.symbol} returned to watchlist with pivot ${new_pivot:.2f}",
                5000
            )

            self._load_positions()

        except Exception as e:
            session.rollback()
            self.logger.error(f"Error returning to watchlist: {e}")
            QMessageBox.critical(self, "Error", f"Failed to return to watchlist:\n{str(e)}")
        finally:
            session.close()

    def _remove_from_watching_exited(self, position_id: int, target_state: int):
        """
        Remove a position from State -1.5 (WATCHING_EXITED).

        Args:
            position_id: Position ID
            target_state: -1 (CLOSED) or -2 (ARCHIVED/STOPPED_OUT)
        """
        session = self.db.get_new_session()
        try:
            repos = RepositoryManager(session)
            position = repos.positions.get_by_id(position_id)

            if not position:
                self.logger.error(f"Position {position_id} not found")
                return

            if position.state != -1.5:
                QMessageBox.warning(
                    self,
                    "Invalid State",
                    f"Position {position.symbol} is not in Exited Watch state."
                )
                return

            # Confirm action
            state_name = "Closed" if target_state == -1 else "Stopped Out (Archive)"
            reply = QMessageBox.question(
                self,
                f"Remove from Re-entry Watch",
                f"Remove {position.symbol} from re-entry watch and move to '{state_name}'?\n\n"
                "This will stop monitoring for re-entry opportunities.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # Optional notes
            from PyQt6.QtWidgets import QInputDialog
            notes, ok = QInputDialog.getText(
                self,
                "Notes (Optional)",
                "Add notes about why you're removing from watch:"
            )

            repos.positions.remove_from_watching_exited(
                position=position,
                target_state=target_state,
                notes=notes if ok and notes else None
            )

            session.commit()

            self.logger.info(f"{position.symbol}: Removed from Exited Watch -> {state_name}")
            self.status_bar.showMessage(f"{position.symbol} moved to {state_name}", 5000)

            self._load_positions()

        except Exception as e:
            session.rollback()
            self.logger.error(f"Error removing from watching exited: {e}")
            QMessageBox.critical(self, "Error", f"Failed to remove position:\n{str(e)}")
        finally:
            session.close()

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

            # Fetch fresh earnings date from API and update database
            earnings_date = self._fetch_and_update_earnings_date(position.symbol, session, repos)
            # Fall back to database value if API didn't find anything
            if earnings_date is None:
                earnings_date = position.earnings_date

            # Show in a dialog
            from PyQt6.QtWidgets import QTextEdit
            from datetime import date as date_type

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Score Details: {position.symbol}")
            dialog.setMinimumSize(720, 750)  # Wider and taller for better readability

            layout = QVBoxLayout(dialog)

            # Header with symbol and grade (no /100 notation)
            header = QLabel(f"<h2>{position.symbol} - Grade: {grade} (Score: {score})</h2>")
            header.setStyleSheet("color: #333;")
            layout.addWidget(header)

            # Earnings warning section (uses freshly fetched or database earnings_date)
            earnings_warning = self._create_earnings_warning_label(position.symbol, earnings_date)
            if earnings_warning:
                layout.addWidget(earnings_warning)

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

    def _create_earnings_warning_label(self, symbol: str, earnings_date) -> QLabel:
        """
        Create earnings warning label with progressive color coding.

        Args:
            symbol: Stock symbol
            earnings_date: Earnings date (date object or None)

        Returns:
            QLabel with appropriate styling, or None if no warning needed
        """
        from datetime import date as date_type

        # Get thresholds from config
        earnings_config = self.config.get('earnings', {})
        thresholds = earnings_config.get('warning_thresholds', {})
        critical_days = thresholds.get('critical', 5)
        caution_days = thresholds.get('caution', 10)

        label = QLabel()
        label.setWordWrap(True)

        if earnings_date:
            today = date_type.today()
            days_until = (earnings_date - today).days

            if days_until < 0:
                # Earnings already passed - might be stale data
                label.setText(
                    f"⚠️ Earnings date ({earnings_date}) appears to be in the past. Data may be stale."
                )
                label.setStyleSheet("""
                    QLabel {
                        color: #856404;
                        background-color: #FFF3CD;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                """)

            elif days_until <= critical_days:
                # CRITICAL - Big red warning
                label.setText(
                    f"⚠️ EARNINGS IN {days_until} DAY{'S' if days_until != 1 else ''} "
                    f"({earnings_date.strftime('%b %d')}) - HIGH RISK!"
                )
                label.setStyleSheet("""
                    QLabel {
                        color: white;
                        background-color: #DC3545;
                        padding: 10px;
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 13px;
                    }
                """)

            elif days_until <= caution_days:
                # CAUTION - Yellow warning
                label.setText(
                    f"⚠️ Earnings in {days_until} days ({earnings_date.strftime('%b %d')}) - "
                    f"Monitor closely."
                )
                label.setStyleSheet("""
                    QLabel {
                        color: #856404;
                        background-color: #FFC107;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                """)

            else:
                # Safe - show info in green
                label.setText(
                    f"📅 Next earnings: {earnings_date.strftime('%b %d, %Y')} ({days_until} days)"
                )
                label.setStyleSheet("""
                    QLabel {
                        color: #155724;
                        background-color: #D4EDDA;
                        padding: 6px;
                        border-radius: 4px;
                    }
                """)

            return label

        else:
            # No earnings date - warn user
            label.setText(
                f"⚠️ No earnings date for {symbol}. Check MarketSurge or enter manually."
            )
            label.setStyleSheet("""
                QLabel {
                    color: #856404;
                    background-color: #FFF3CD;
                    padding: 8px;
                    border-radius: 4px;
                    font-style: italic;
                }
            """)
            return label

    def _fetch_and_update_earnings_date(self, symbol: str, session, repos):
        """
        Fetch earnings date from API and update database if found.

        Args:
            symbol: Stock symbol
            session: Database session
            repos: RepositoryManager instance

        Returns:
            Earnings date if found, None otherwise
        """
        try:
            from canslim_monitor.integrations.polygon_client import PolygonClient

            # Get API config
            market_data_config = self.config.get('market_data', {})
            polygon_config = self.config.get('polygon', {})

            api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
            base_url = market_data_config.get('base_url') or polygon_config.get('base_url', 'https://api.polygon.io')

            if not api_key:
                self.logger.debug("No API key for earnings lookup")
                return None

            # Fetch earnings date (tries Polygon, then Yahoo Finance)
            polygon_client = PolygonClient(api_key=api_key, base_url=base_url)
            earnings_date = polygon_client.get_next_earnings_date(symbol)

            if earnings_date:
                self.logger.info(f"{symbol}: Fetched earnings date {earnings_date}")

                # Update position in database
                position = repos.positions.get_by_symbol(symbol)
                if position and position.earnings_date != earnings_date:
                    repos.positions.update(position, earnings_date=earnings_date)
                    session.commit()
                    self.logger.info(f"{symbol}: Updated earnings date in database")

                return earnings_date

        except Exception as e:
            self.logger.warning(f"Error fetching earnings date for {symbol}: {e}")

        return None

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

                    # Log IBKR connection state for debugging
                    log(f"  IBKR connected: {self.ibkr_connected}")
                    log(f"  IBKR client: {'available' if self.ibkr_client else 'not available'}")
                    if self.ibkr_client:
                        try:
                            is_conn = self.ibkr_client.is_connected()
                            log(f"  IBKR client.is_connected(): {is_conn}")
                        except Exception as e:
                            log(f"  IBKR client.is_connected() error: {e}")

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
                            log(f"  Spread: {spread_pct:.3f}% ({exec_data.get('spread_status', 'N/A')})")
                        else:
                            if not self.ibkr_connected:
                                log("  Spread: N/A (GUI IBKR service not started)")
                                log("    → Start via: Service > Start Service")
                            elif not self.ibkr_client:
                                log("  Spread: N/A (IBKR client not initialized)")
                            else:
                                log("  Spread: Could not fetch bid/ask from IBKR")
                                log("    → Check logs for details")
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

        # Debug logging for IBKR connection state
        self.logger.debug(f"Spread fetch for {symbol}: ibkr_connected={self.ibkr_connected}, "
                         f"ibkr_client={'exists' if self.ibkr_client else 'None'}")

        if self.ibkr_connected and self.ibkr_client:
            try:
                # Verify client is still connected
                client_connected = self.ibkr_client.is_connected()
                self.logger.debug(f"IBKR client.is_connected() = {client_connected}")

                if not client_connected:
                    self.logger.warning(f"IBKR client reports disconnected - cannot fetch spread for {symbol}")
                else:
                    # Fetch quote for this symbol
                    self.logger.debug(f"Fetching quote for {symbol}...")
                    quotes = self.ibkr_client.get_quotes([symbol])
                    self.logger.debug(f"Quote response for {symbol}: {quotes}")

                    if quotes and symbol in quotes:
                        quote_data = quotes[symbol]
                        bid_price = quote_data.get('bid')
                        ask_price = quote_data.get('ask')
                        self.logger.debug(f"{symbol} bid={bid_price}, ask={ask_price}")

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
                            self.logger.debug(f"{symbol} spread_pct={spread_pct:.4f}%, status={spread_status}")
                        else:
                            self.logger.debug(f"{symbol}: bid/ask invalid or zero (bid={bid_price}, ask={ask_price})")
                    else:
                        self.logger.warning(f"No quote data returned for {symbol}")
            except Exception as e:
                self.logger.warning(f"Could not fetch bid/ask for {symbol}: {e}", exc_info=True)
        else:
            self.logger.debug(f"Skipping spread fetch - IBKR not available (connected={self.ibkr_connected}, client={self.ibkr_client is not None})")
        
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

    def _on_score_symbol(self):
        """Open Score Preview dialog to preview a symbol's entry grade."""
        from .dialogs.score_preview_dialog import ScorePreviewDialog

        # Create modeless dialog with config, db access, and IBKR client for dynamic scoring
        self._score_dialog = ScorePreviewDialog(
            None,
            config=self.config,
            db_session_factory=self.db.get_new_session,
            ibkr_client=self.ibkr_client,
            ibkr_connected=self.ibkr_connected
        )
        self._score_dialog.accepted.connect(self._on_score_dialog_accepted)

        # Show as modeless (non-blocking)
        self._score_dialog.show()
        self._score_dialog.raise_()
        self._score_dialog.activateWindow()

    def _on_score_dialog_accepted(self):
        """Handle ScorePreviewDialog accepted - open AddPositionDialog with data."""
        if not hasattr(self, '_score_dialog') or not self._score_dialog:
            return

        # Get pre-populate data from score preview
        prepopulate_data = self._score_dialog.get_prepopulate_data()
        self._score_dialog = None

        # Open AddPositionDialog with pre-populated scoring fields
        self._add_dialog = AddPositionDialog(None, initial_data=prepopulate_data)
        self._add_dialog.accepted.connect(self._on_add_dialog_accepted)
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

                # Do initial futures update
                self._update_futures()

                # Refresh index stats (SMAs) from Polygon in background
                self._load_index_stats()

                # Start timers for continuous updates
                self.price_timer.start(self.price_update_interval)
                self.futures_timer.start(self.futures_update_interval)

                self.logger.info(f"IBKR service started (prices: {self.price_update_interval/1000}s, futures: {self.futures_update_interval/1000}s)")
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

        # Stop timers first (prevents new updates from starting)
        self.price_timer.stop()
        self.futures_timer.stop()
        
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
            
            # Import regime components (same imports as CLI test_regime_alert.py)
            from canslim_monitor.regime.historical_data import fetch_spy_qqq_daily, fetch_index_daily
            from canslim_monitor.regime.distribution_tracker import DistributionDayTracker
            from canslim_monitor.regime.ftd_tracker import (
                FollowThroughDayTracker, RallyAttempt, FollowThroughDay, MarketStatus
            )
            from canslim_monitor.regime.market_regime import (
                MarketRegimeCalculator, DistributionData, FTDData, create_overnight_data,
                calculate_entry_risk_score, OvernightData, RegimeScore
            )
            from canslim_monitor.regime.market_phase_manager import MarketPhaseManager
            from canslim_monitor.regime.models_regime import (
                Base, DistributionDay, DistributionDayCount, DistributionDayOverride,
                OvernightTrend, MarketRegimeAlert, DDayTrend, TrendType
            )
            
            dialog.set_progress(15, "Ensuring database tables exist...")
            QApplication.processEvents()
            
            # Ensure regime tables exist in main database
            self._ensure_regime_tables()
            self.logger.info("Database tables ensured")

            # Use main database session for all trackers (same as CLI)
            # This ensures access to historical data, overrides, and phase history
            regime_session = self.db.get_new_session()
            self.logger.info("Using main database session for regime analysis")
            
            dialog.set_progress(25, "Fetching index data from Polygon...")
            QApplication.processEvents()
            self.logger.info("Fetching SPY, QQQ, DIA, IWM data...")
            
            # Fetch market data for all index ETFs
            api_config = {'polygon': {'api_key': polygon_key}}
            data = fetch_index_daily(
                symbols=['SPY', 'QQQ', 'DIA', 'IWM'],
                lookback_days=300,  # Need 300 calendar days to get 200+ trading days for SMA
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

            # Get config parameters (same as CLI)
            dist_config = config.get('distribution_days', {})
            use_indices = config.get('market_regime', {}).get('use_indices', False)

            # Calculate distribution days with config params
            dist_tracker = DistributionDayTracker(
                db_session=regime_session,
                decline_threshold=dist_config.get('decline_threshold'),
                lookback_days=dist_config.get('lookback_days', 25),
                rally_expiration_pct=dist_config.get('rally_expiration_pct', 5.0),
                min_volume_increase_pct=dist_config.get('min_volume_increase_pct'),
                decline_rounding_decimals=dist_config.get('decline_rounding_decimals'),
                enable_stalling=dist_config.get('enable_stalling'),
                use_indices=use_indices
            )
            combined = dist_tracker.get_combined_data(spy_bars, qqq_bars)
            self.logger.info(f"Distribution days - SPY: {combined.spy_count}, QQQ: {combined.qqq_count}")
            
            dialog.set_progress(60, f"SPY: {combined.spy_count} D-days, QQQ: {combined.qqq_count} D-days...")
            QApplication.processEvents()
            
            dialog.set_progress(65, "Checking Follow-Through Day status...")
            QApplication.processEvents()
            self.logger.info("Checking FTD status...")

            # Check FTD status with config params (same as CLI)
            ftd_tracker = FollowThroughDayTracker(
                db_session=regime_session,
                ftd_min_gain=config.get('ftd_min_gain', 1.25),
                ftd_earliest_day=config.get('ftd_earliest_day', 4)
            )
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
            
            # Check phase transitions (same as CLI)
            dialog.set_progress(75, "Checking phase transitions...")
            QApplication.processEvents()
            self.logger.info("Checking phase transitions...")

            phase_config = config.get('market_phase', {})
            phase_manager = MarketPhaseManager(
                db_session=regime_session,
                thresholds={
                    'pressure_min_ddays': phase_config.get('pressure_threshold', 5),
                    'correction_min_ddays': phase_config.get('correction_threshold', 7),
                    'confirmed_max_ddays': phase_config.get('confirmed_max_ddays', 4),
                }
            )

            phase_transition = phase_manager.update_phase(
                dist_data=combined,
                ftd_data=ftd_status
            )

            if phase_transition.phase_changed:
                self.logger.info(f"PHASE CHANGE: {phase_transition.previous_phase.value} -> {phase_transition.current_phase.value}")
                self.logger.info(f"Reason: {phase_transition.trigger_reason}")

            dialog.set_progress(80, "Calculating composite regime score...")
            QApplication.processEvents()
            self.logger.info("Calculating regime score...")

            # Build distribution data for calculator
            dist_data = DistributionData(
                spy_count=combined.spy_count,
                qqq_count=combined.qqq_count,
                spy_5day_delta=combined.spy_5day_delta,
                qqq_5day_delta=combined.qqq_5day_delta,
                trend=combined.trend,
                spy_dates=combined.spy_dates,
                qqq_dates=combined.qqq_dates
            )

            # Fetch overnight futures from IBKR (same as regime_thread)
            overnight = create_overnight_data(0.0, 0.0, 0.0)
            if hasattr(self, 'ibkr_client') and self.ibkr_client:
                try:
                    if self.ibkr_client.is_connected():
                        dialog.set_progress(78, "Fetching overnight futures...")
                        QApplication.processEvents()
                        from canslim_monitor.regime.ibkr_futures import get_futures_snapshot
                        es_pct, nq_pct, ym_pct = get_futures_snapshot(self.ibkr_client)
                        overnight = create_overnight_data(es_pct, nq_pct, ym_pct)
                        self.logger.info(f"Overnight futures: ES={es_pct:+.2f}%, NQ={nq_pct:+.2f}%, YM={ym_pct:+.2f}%")
                except Exception as e:
                    self.logger.warning(f"Futures fetch failed (non-critical): {e}")

            # Fetch Fear & Greed data (same as regime_thread)
            dialog.set_progress(82, "Fetching Fear & Greed data...")
            QApplication.processEvents()
            fg_data = None
            try:
                from canslim_monitor.regime.fear_greed_client import FearGreedClient
                fg_client = FearGreedClient.from_config(config)
                fg_data = fg_client.fetch_current()
                if fg_data:
                    self.logger.info(f"F&G: {fg_data.score:.0f} ({fg_data.rating})")
            except Exception as e:
                self.logger.warning(f"F&G fetch failed (non-critical): {e}")

            # Fetch VIX data (same as regime_thread)
            dialog.set_progress(84, "Fetching VIX data...")
            QApplication.processEvents()
            vix_data = None
            try:
                from canslim_monitor.regime.vix_client import VixClient
                vix_client = VixClient.from_config(config)
                vix_data = vix_client.fetch_current()
                if vix_data:
                    self.logger.info(f"VIX: {vix_data.close:.2f} (prev: {vix_data.previous_close:.2f})")
            except Exception as e:
                self.logger.warning(f"VIX fetch failed (non-critical): {e}")

            # DB fallback for VIX if live fetch failed
            if not vix_data:
                try:
                    from canslim_monitor.regime.vix_client import VixData
                    latest_alert = regime_session.query(MarketRegimeAlert).filter(
                        MarketRegimeAlert.vix_close.isnot(None)
                    ).order_by(MarketRegimeAlert.date.desc()).first()
                    if latest_alert and latest_alert.vix_close:
                        vix_data = VixData(
                            close=latest_alert.vix_close,
                            previous_close=latest_alert.vix_previous_close or 0.0,
                            timestamp=datetime.combine(latest_alert.date, datetime.min.time())
                        )
                        self.logger.info(f"VIX from DB fallback: {vix_data.close:.2f} (date: {latest_alert.date})")
                except Exception as e:
                    self.logger.debug(f"VIX DB fallback failed: {e}")

            # Load prior score for trend tracking (same as CLI)
            prior_score = None
            try:
                prior = regime_session.query(MarketRegimeAlert).filter(
                    MarketRegimeAlert.date < date.today()
                ).order_by(MarketRegimeAlert.date.desc()).first()

                if prior:
                    prior_dist = DistributionData(
                        spy_count=prior.spy_d_count,
                        qqq_count=prior.qqq_d_count,
                        spy_5day_delta=prior.spy_5day_delta or 0,
                        qqq_5day_delta=prior.qqq_5day_delta or 0,
                        trend=prior.d_day_trend or DDayTrend.STABLE
                    )
                    prior_overnight = OvernightData(
                        es_change_pct=0, es_trend=TrendType.NEUTRAL,
                        nq_change_pct=0, nq_trend=TrendType.NEUTRAL,
                        ym_change_pct=0, ym_trend=TrendType.NEUTRAL
                    )
                    prior_score = RegimeScore(
                        composite_score=prior.composite_score,
                        regime=prior.regime,
                        distribution_data=prior_dist,
                        overnight_data=prior_overnight,
                        component_scores={},
                        timestamp=datetime.combine(prior.date, datetime.min.time())
                    )
                    self.logger.info(f"Loaded prior score: {prior.regime.value} ({prior.composite_score:+.2f})")
            except Exception as e:
                self.logger.warning(f"Could not load prior regime: {e}")

            # Calculate regime with prior score for trend tracking
            calculator = MarketRegimeCalculator(config.get('market_regime', {}))
            score = calculator.calculate_regime(dist_data, overnight, prior_score, ftd_data=ftd_data)

            # Calculate entry risk (same as CLI)
            entry_risk_score_val, entry_risk_level_val = calculate_entry_risk_score(
                overnight, dist_data, ftd_data
            )
            score.entry_risk_score = entry_risk_score_val
            score.entry_risk_level = entry_risk_level_val

            # Attach sentiment data to score (same as regime_thread)
            score.fear_greed_data = fg_data
            if vix_data:
                score.vix_close = vix_data.close
                score.vix_previous_close = vix_data.previous_close

            self.logger.info(f"Regime calculated: {score.regime.value}, score: {score.composite_score:+.2f}")
            self.logger.info(f"Entry risk: {entry_risk_level_val.value} ({entry_risk_score_val:+.2f})")
            
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

                        # Get entry risk from score
                        _entry_risk_level = None
                        _entry_risk_score = 0.0
                        if hasattr(score, 'entry_risk_level') and score.entry_risk_level:
                            _entry_risk_level = score.entry_risk_level.value if hasattr(score.entry_risk_level, 'value') else str(score.entry_risk_level)
                            _entry_risk_score = score.entry_risk_score or 0.0

                        # Try to get IBD status
                        _ibd_status = None
                        try:
                            from sqlalchemy import text
                            ibd_result = main_session.execute(text("SELECT status FROM ibd_exposure_current WHERE id=1")).fetchone()
                            if ibd_result:
                                _ibd_status = ibd_result[0]
                        except Exception:
                            pass

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
                            'ftd_date': ftd_data.spy_ftd_date or ftd_data.qqq_ftd_date,
                            'days_since_ftd': ftd_data.days_since_ftd,
                            'composite_score': score.composite_score,
                            'regime': score.regime.value if hasattr(score.regime, 'value') else str(score.regime),
                            'exposure': f"{min_exp}-{max_exp}%",
                            'spy_stats': spy_stats,
                            'qqq_stats': qqq_stats,
                            'dia_stats': dia_stats,
                            'iwm_stats': iwm_stats,
                            'entry_risk_level': _entry_risk_level,
                            'entry_risk_score': _entry_risk_score,
                            'ibd_status': _ibd_status,
                            'fg_data': fg_data,
                            'vix_data': vix_data,
                            'overnight': overnight,
                            'not_saved': True,  # Flag to indicate this wasn't saved
                        }

                        # Show results in dialog without saving
                        dialog.show_results(results)
                        main_session.close()
                        regime_session.close()
                        dialog.exec()
                        return

                    # User confirmed - proceed with update
                    self.logger.info("User confirmed overwrite of existing record")

                # Build full alert with ALL fields (same as regime_thread._save_regime_alert)
                spy_dates_str = ','.join(d.isoformat() for d in combined.spy_dates)
                qqq_dates_str = ','.join(d.isoformat() for d in combined.qqq_dates)

                alert = MarketRegimeAlert(
                    date=today,
                    spy_d_count=combined.spy_count,
                    qqq_d_count=combined.qqq_count,
                    spy_5day_delta=combined.spy_5day_delta,
                    qqq_5day_delta=combined.qqq_5day_delta,
                    d_day_trend=combined.trend,
                    spy_d_dates=spy_dates_str,
                    qqq_d_dates=qqq_dates_str,
                    es_change_pct=overnight.es_change_pct,
                    nq_change_pct=overnight.nq_change_pct,
                    ym_change_pct=overnight.ym_change_pct,
                    spy_d_score=score.component_scores.get('spy_distribution'),
                    qqq_d_score=score.component_scores.get('qqq_distribution'),
                    trend_score=score.component_scores.get('distribution_trend'),
                    es_score=score.component_scores.get('overnight_es'),
                    nq_score=score.component_scores.get('overnight_nq'),
                    ym_score=score.component_scores.get('overnight_ym'),
                    ftd_adjustment=score.component_scores.get('ftd_adjustment'),
                    market_phase=ftd_status.phase.value,
                    composite_score=score.composite_score,
                    regime=score.regime,
                    prior_regime=score.prior_regime,
                    prior_score=score.prior_score,
                    regime_changed=(score.prior_regime != score.regime if score.prior_regime else False),
                )

                # FTD data
                alert.in_rally_attempt = ftd_data.in_rally_attempt
                alert.rally_day = ftd_data.rally_day
                alert.has_confirmed_ftd = ftd_data.has_confirmed_ftd
                alert.ftd_date = ftd_data.spy_ftd_date or ftd_data.qqq_ftd_date
                alert.days_since_ftd = ftd_data.days_since_ftd

                # Entry risk
                alert.entry_risk_score = score.entry_risk_score
                alert.entry_risk_level = score.entry_risk_level

                # CNN Fear & Greed data
                if fg_data:
                    alert.fear_greed_score = fg_data.score
                    alert.fear_greed_rating = fg_data.rating
                    alert.fear_greed_previous = fg_data.previous_close
                    alert.fear_greed_timestamp = fg_data.timestamp

                # VIX data
                if vix_data:
                    alert.vix_close = vix_data.close
                    alert.vix_previous_close = vix_data.previous_close

                if existing:
                    # Update existing record (same pattern as regime_thread)
                    preserve_fields = {
                        'fear_greed_score', 'fear_greed_rating', 'fear_greed_previous',
                        'fear_greed_timestamp', 'vix_close', 'vix_previous_close',
                    }
                    for key, value in alert.__dict__.items():
                        if not key.startswith('_') and key != 'id':
                            if key in preserve_fields and value is None:
                                continue  # Don't overwrite existing data with None
                            setattr(existing, key, value)
                    self.logger.info(f"Updated existing regime record for {today}")
                else:
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

            # Update banner F&G + VIX directly (freshly fetched data)
            if fg_data:
                self.regime_banner.update_fear_greed(score=fg_data.score, rating=fg_data.rating)
            if vix_data:
                self.regime_banner.update_vix(price=vix_data.close, prev_close=vix_data.previous_close)

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
            # Get entry risk level/score from score object
            entry_risk_level = None
            entry_risk_score = 0.0
            if hasattr(score, 'entry_risk_level') and score.entry_risk_level:
                entry_risk_level = score.entry_risk_level.value if hasattr(score.entry_risk_level, 'value') else str(score.entry_risk_level)
                entry_risk_score = score.entry_risk_score or 0.0

            # Try to get IBD status from database
            ibd_status = None
            try:
                from sqlalchemy import text
                ibd_result = main_session.execute(text("SELECT status FROM ibd_exposure_current WHERE id=1")).fetchone()
                if ibd_result:
                    ibd_status = ibd_result[0]
            except Exception:
                pass  # Table may not exist

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
                'ftd_date': ftd_data.spy_ftd_date or ftd_data.qqq_ftd_date,
                'days_since_ftd': ftd_data.days_since_ftd,
                'composite_score': score.composite_score,
                'regime': score.regime.value if hasattr(score.regime, 'value') else str(score.regime),
                'exposure': f"{min_exp}-{max_exp}%",
                'spy_stats': spy_stats,
                'qqq_stats': qqq_stats,
                'dia_stats': dia_stats,
                'iwm_stats': iwm_stats,
                # New fields for updated dialog format
                'entry_risk_level': entry_risk_level,
                'entry_risk_score': entry_risk_score,
                'ibd_status': ibd_status,
                'fg_data': fg_data,
                'vix_data': vix_data,
                'overnight': overnight,
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

        finally:
            # Clean up regime session
            try:
                regime_session.close()
            except Exception:
                pass  # Session may not exist if error occurred early

        # Keep dialog open for user to review
        dialog.exec()

    def _on_update_all_earnings(self):
        """Update earnings dates for all active (non-closed) positions."""
        from PyQt6.QtWidgets import QProgressDialog, QMessageBox
        from PyQt6.QtCore import Qt

        self.logger.info("Starting earnings date update for all active positions")

        # Load config for API key
        import yaml

        config = getattr(self, 'config', {}) or {}
        if not config:
            config_paths = [
                'user_config.yaml',
                'canslim_monitor/user_config.yaml',
            ]
            for path in config_paths:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        config = yaml.safe_load(f) or {}
                    break

        api_key = (
            config.get('market_data', {}).get('api_key') or
            config.get('polygon', {}).get('api_key')
        )
        base_url = (
            config.get('market_data', {}).get('base_url') or
            'https://api.polygon.io'
        )

        if not api_key:
            QMessageBox.warning(
                self,
                "No API Key",
                "No Polygon/Massive API key found in config.\n\n"
                "Add to your config:\n"
                "  market_data:\n"
                "    api_key: 'your-api-key'"
            )
            return

        # Create progress dialog
        progress = QProgressDialog("Updating earnings dates...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Update Earnings Dates")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(5)
        QApplication.processEvents()

        try:
            # Import and create service
            from canslim_monitor.integrations.polygon_client import PolygonClient
            from canslim_monitor.services.earnings_service import EarningsService

            progress.setLabelText("Creating API client...")
            progress.setValue(10)
            QApplication.processEvents()

            polygon_client = PolygonClient(api_key=api_key, base_url=base_url)

            earnings_service = EarningsService(
                session_factory=self.db.get_new_session,
                polygon_client=polygon_client
            )

            # Get active symbols
            progress.setLabelText("Getting active symbols...")
            progress.setValue(15)
            QApplication.processEvents()

            symbols = earnings_service.get_active_symbols()

            if not symbols:
                progress.close()
                QMessageBox.information(
                    self,
                    "No Positions",
                    "No active positions found to update."
                )
                return

            progress.setMaximum(len(symbols) + 10)
            progress.setValue(10)

            results = {
                'updated': 0,
                'skipped': 0,
                'not_found': 0,
                'errors': 0,
                'details': []
            }

            from datetime import date as date_type

            for i, symbol in enumerate(symbols):
                if progress.wasCanceled():
                    break

                progress.setLabelText(f"Checking {symbol}... ({i+1}/{len(symbols)})")
                progress.setValue(10 + i)
                QApplication.processEvents()

                try:
                    # Check if already has future earnings date
                    session = self.db.get_new_session()
                    try:
                        from canslim_monitor.data.models import Position
                        position = session.query(Position).filter(
                            Position.symbol == symbol,
                            Position.state >= 0
                        ).first()

                        if position and position.earnings_date and position.earnings_date >= date_type.today():
                            results['skipped'] += 1
                            results['details'].append(f"{symbol}: Skipped (has {position.earnings_date})")
                            continue
                    finally:
                        session.close()

                    # Fetch earnings date
                    earnings_date = polygon_client.get_next_earnings_date(symbol)

                    if earnings_date:
                        if earnings_service.update_earnings_date(symbol, earnings_date):
                            results['updated'] += 1
                            results['details'].append(f"{symbol}: Updated to {earnings_date}")
                        else:
                            results['errors'] += 1
                            results['details'].append(f"{symbol}: Update failed")
                    else:
                        results['not_found'] += 1
                        results['details'].append(f"{symbol}: No earnings date found")

                except Exception as e:
                    self.logger.error(f"Error fetching earnings for {symbol}: {e}")
                    results['errors'] += 1
                    results['details'].append(f"{symbol}: Error - {e}")

            progress.close()

            # Refresh UI
            self._load_positions()

            # Show summary
            summary = (
                f"Earnings Update Complete\n\n"
                f"Symbols checked: {len(symbols)}\n"
                f"Updated: {results['updated']}\n"
                f"Skipped (already set): {results['skipped']}\n"
                f"Not found: {results['not_found']}\n"
                f"Errors: {results['errors']}"
            )

            if results['details'] and len(results['details']) <= 20:
                summary += "\n\nDetails:\n" + "\n".join(results['details'][:20])
            elif results['details']:
                summary += f"\n\n(Showing first 20 of {len(results['details'])} results)\n"
                summary += "\n".join(results['details'][:20])

            QMessageBox.information(self, "Earnings Update", summary)

            self.logger.info(
                f"Earnings update complete: {results['updated']} updated, "
                f"{results['skipped']} skipped, {results['not_found']} not found, "
                f"{results['errors']} errors"
            )

        except Exception as e:
            progress.close()
            self.logger.error(f"Earnings update failed: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to update earnings dates:\n\n{e}"
            )

    def _on_seed_volume_data(self):
        """Seed 50-day volume data for all active (non-closed) positions."""
        from PyQt6.QtWidgets import QProgressDialog, QMessageBox
        from PyQt6.QtCore import Qt

        self.logger.info("Starting 50-day volume data seeding for all active positions")

        # Load config for API key
        import yaml

        config = getattr(self, 'config', {}) or {}
        if not config:
            config_paths = [
                'user_config.yaml',
                'canslim_monitor/user_config.yaml',
            ]
            for path in config_paths:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        config = yaml.safe_load(f) or {}
                    break

        api_key = (
            config.get('market_data', {}).get('api_key') or
            config.get('polygon', {}).get('api_key')
        )
        base_url = (
            config.get('market_data', {}).get('base_url') or
            'https://api.polygon.io'
        )
        # Use faster rate limit for paid tiers
        rate_limit_delay = config.get('market_data', {}).get('rate_limit_delay', 0.1)

        if not api_key:
            QMessageBox.warning(
                self,
                "No API Key",
                "No Polygon/Massive API key found in config.\n\n"
                "Add to your config:\n"
                "  market_data:\n"
                "    api_key: 'your-api-key'"
            )
            return

        # Create progress dialog
        progress = QProgressDialog("Seeding volume data...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Seed 50-Day Volume Data")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(5)
        QApplication.processEvents()

        try:
            # Import and create service
            from canslim_monitor.integrations.polygon_client import PolygonClient
            from canslim_monitor.services.volume_service import VolumeService

            progress.setLabelText("Creating API client...")
            progress.setValue(10)
            QApplication.processEvents()

            polygon_client = PolygonClient(
                api_key=api_key,
                base_url=base_url,
                rate_limit_delay=rate_limit_delay
            )

            volume_service = VolumeService(
                db_session_factory=self.db.get_new_session,
                polygon_client=polygon_client
            )

            # Get active symbols (state >= 0 means not closed)
            progress.setLabelText("Getting active symbols...")
            progress.setValue(15)
            QApplication.processEvents()

            session = self.db.get_new_session()
            try:
                from canslim_monitor.data.models import Position
                symbols = session.query(Position.symbol).filter(
                    Position.state >= 0
                ).distinct().all()
                symbols = [s[0] for s in symbols]
            finally:
                session.close()

            if not symbols:
                progress.close()
                QMessageBox.information(
                    self,
                    "No Positions",
                    "No active positions found to update."
                )
                return

            progress.setMaximum(len(symbols) + 15)
            progress.setValue(15)

            results = {
                'success': 0,
                'failed': 0,
                'details': []
            }

            for i, symbol in enumerate(symbols):
                if progress.wasCanceled():
                    break

                progress.setLabelText(f"Fetching {symbol}... ({i+1}/{len(symbols)})")
                progress.setValue(15 + i)
                QApplication.processEvents()

                try:
                    result = volume_service.update_symbol(symbol, days=50)

                    if result.success:
                        results['success'] += 1
                        results['details'].append(
                            f"{symbol}: {result.bars_fetched} bars, avg={result.avg_volume_50d:,}"
                        )
                    else:
                        results['failed'] += 1
                        results['details'].append(f"{symbol}: {result.error}")

                except Exception as e:
                    self.logger.error(f"Error seeding volume for {symbol}: {e}")
                    results['failed'] += 1
                    results['details'].append(f"{symbol}: Error - {e}")

            progress.close()

            # Refresh UI
            self._load_positions()

            # Show summary
            summary = (
                f"Volume Data Seeding Complete\n\n"
                f"Symbols processed: {len(symbols)}\n"
                f"Successful: {results['success']}\n"
                f"Failed: {results['failed']}"
            )

            if results['details'] and len(results['details']) <= 25:
                summary += "\n\nDetails:\n" + "\n".join(results['details'][:25])
            elif results['details']:
                summary += f"\n\n(Showing first 25 of {len(results['details'])} results)\n"
                summary += "\n".join(results['details'][:25])

            QMessageBox.information(self, "Volume Data Seeding", summary)

            self.logger.info(
                f"Volume seeding complete: {results['success']} successful, "
                f"{results['failed']} failed"
            )

        except Exception as e:
            progress.close()
            self.logger.error(f"Volume seeding failed: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to seed volume data:\n\n{e}"
            )

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
            
            # Always include index ETFs + VIX for the banner
            for idx in ['SPY', 'QQQ', 'DIA', 'IWM', 'VIX']:
                if idx not in symbols:
                    symbols.append(idx)
        finally:
            session.close()
        
        if not symbols:
            return
        
        # Create worker and thread for IBKR fetch (slow operation)
        self.price_update_in_progress = True

        # Get Polygon API key from config for fallback
        polygon_api_key = self.config.get('market_data', {}).get('api_key') if self.config else None

        self.price_thread = QThread()
        self.price_worker = PriceUpdateWorker(self.ibkr_client, symbols, polygon_api_key=polygon_api_key)
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

            # Build position lookup for P&L calculation
            position_data = {}
            for pos in positions:
                position_data[pos.symbol] = {
                    'avg_cost': pos.avg_cost,
                    'state': pos.state
                }

            # Update database prices
            updated_count = 0
            for pos in positions:
                if pos.symbol in prices:
                    price_data = prices[pos.symbol]
                    last_price = price_data.get('last') or price_data.get('close')

                    if last_price and last_price > 0:
                        repos.positions.update_price(pos, last_price)
                        updated_count += 1

            session.commit()

            # Incremental card updates (no rebuild) - much faster!
            self._update_card_prices(prices, position_data)

            # Update market regime banner with index prices
            self._update_market_banner(prices)

            self.status_bar.showMessage(f"Updated {updated_count} prices at {datetime.now().strftime('%H:%M:%S')}")

        except Exception as e:
            self.logger.error(f"Error processing prices: {e}")
        finally:
            session.close()

    def _update_card_prices(self, prices: Dict, position_data: Dict):
        """
        Update card prices incrementally without rebuilding the board.
        This is much more efficient than calling _load_positions().
        """
        updated = 0
        for symbol, card in self._cards_by_symbol.items():
            if symbol in prices:
                price_data = prices[symbol]
                last_price = price_data.get('last') or price_data.get('close')

                if last_price and last_price > 0:
                    # Calculate P&L if in position
                    pnl_pct = None
                    pos_info = position_data.get(symbol, {})
                    avg_cost = pos_info.get('avg_cost')
                    if avg_cost and avg_cost > 0 and pos_info.get('state', 0) > 0:
                        pnl_pct = ((last_price - avg_cost) / avg_cost) * 100

                    card.update_price(last_price, pnl_pct)
                    updated += 1

        self.logger.debug(f"Incrementally updated {updated} card prices")
    
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
        """Update market regime banner with index prices and change from open/day from IBKR."""
        for symbol in ['SPY', 'QQQ', 'DIA', 'IWM']:
            price_data = prices.get(symbol, {})
            last_price = price_data.get('last') or price_data.get('close')

            # Skip update if no price data - preserve existing display
            if not last_price or last_price <= 0:
                continue

            prev_close = price_data.get('close') or price_data.get('previousClose')
            open_price = price_data.get('open')

            # Calculate day change (from previous close)
            day_pct = None
            if last_price and prev_close and prev_close > 0:
                day_pct = ((last_price - prev_close) / prev_close) * 100

            # Calculate change from open (includes premarket movement)
            open_pct = None
            if last_price and open_price and open_price > 0:
                open_pct = ((last_price - open_price) / open_price) * 100

            # Get cached SMA data if available (set by regime analysis)
            cached = getattr(self, f'_cached_{symbol.lower()}_stats', {})

            # Update the index box
            self.regime_banner.update_index_box(
                symbol,
                price=last_price,
                day_pct=day_pct,
                open_pct=open_pct,
                sma21=cached.get('sma21'),
                sma50=cached.get('sma50'),
                sma200=cached.get('sma200')
            )

        # Update VIX card
        vix_data = prices.get('VIX', {})
        vix_price = vix_data.get('last') or vix_data.get('close')
        if vix_price and vix_price > 0:
            vix_prev = vix_data.get('close') or vix_data.get('previousClose')
            self.logger.debug(f"VIX update: price={vix_price}, prev={vix_prev}")
            self.regime_banner.update_vix(price=vix_price, prev_close=vix_prev)
        else:
            self.logger.debug(f"VIX data missing or invalid: {vix_data}")

    def _update_futures(self):
        """Fetch live futures data from IBKR and update banner."""
        if not self.ibkr_connected or not self.ibkr_client:
            return

        try:
            # Import the futures snapshot function
            from canslim_monitor.regime.ibkr_futures import get_futures_snapshot

            # Get futures percentages (ES, NQ, YM) - calculates change from 6 PM Globex open
            es_pct, nq_pct, ym_pct = get_futures_snapshot(self.ibkr_client)

            # Update the banner with live futures data
            self.regime_banner.update_futures(es_pct=es_pct, nq_pct=nq_pct, ym_pct=ym_pct)

            self.logger.debug(f"Futures update: ES={es_pct:+.2f}%, NQ={nq_pct:+.2f}%, YM={ym_pct:+.2f}%")

        except Exception as e:
            self.logger.warning(f"Futures update error: {e}")

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

    def _on_analytics_dashboard(self):
        """Open the analytics dashboard."""
        from canslim_monitor.gui.analytics import AnalyticsDashboard

        try:
            # Keep reference to prevent garbage collection
            self.analytics_dashboard = AnalyticsDashboard(self.db, parent=self)
            self.analytics_dashboard.show()
        except Exception as e:
            QMessageBox.critical(self, "Analytics Error", f"Error opening analytics dashboard: {str(e)}")
            self.logger.error(f"Analytics dashboard error: {e}", exc_info=True)

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
