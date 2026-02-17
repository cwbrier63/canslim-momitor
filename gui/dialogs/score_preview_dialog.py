"""
Symbol Score Preview Dialog

Allows scoring any symbol's base characteristics before adding to watchlist.
If scores look good, pre-populates the AddPositionDialog with scoring data.
Supports dynamic scoring when a symbol is provided (fetches historical data).
"""

import logging
from typing import Dict, Any, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QPushButton, QMessageBox, QSizePolicy, QTextEdit, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ..state_config import VALID_PATTERNS, BASE_STAGES

logger = logging.getLogger(__name__)


class ScorePreviewDialog(QDialog):
    """
    Dialog for previewing CANSLIM scores before adding to watchlist.

    Allows user to enter base characteristics and see the calculated
    entry grade and score breakdown before committing to add a position.
    """

    # Grade color mapping
    GRADE_COLORS = {
        'A+': '#28A745', 'A': '#28A745',
        'B+': '#20C997', 'B': '#20C997',
        'C+': '#FFC107', 'C': '#FFC107',
        'D': '#FD7E14',
        'F': '#DC3545'
    }

    def __init__(self, parent=None, config: Dict[str, Any] = None, db_session_factory=None,
                 ibkr_client=None, ibkr_connected: bool = False,
                 historical_provider=None, realtime_provider=None):
        super().__init__(parent)
        self._scorer = None
        self._config = config or {}
        self._db_session_factory = db_session_factory
        self._ibkr_client = ibkr_client
        self._ibkr_connected = ibkr_connected
        self._historical_provider = historical_provider
        self._realtime_provider = realtime_provider
        self._details = None  # Score details dict
        self._score = 0
        self._grade = 'F'
        self._symbol = ""
        self._pivot = None
        self._earnings_date = None  # Next earnings date from Polygon

        # Make dialog independent (modeless) - can interact with main window
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._setup_ui()

    @property
    def scorer(self):
        """Lazy load CANSLIMScorer."""
        if self._scorer is None:
            try:
                from canslim_monitor.utils.scoring import CANSLIMScorer
                self._scorer = CANSLIMScorer()
            except Exception as e:
                logger.error(f"Failed to load CANSLIMScorer: {e}", exc_info=True)
        return self._scorer

    def set_config(self, config: Dict[str, Any]):
        """Set configuration (for API keys, etc.)."""
        self._config = config or {}

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Symbol Score Preview")
        self.setMinimumWidth(500)
        self.setMinimumHeight(500)

        # Apply light theme styling
        self.setStyleSheet("""
            QDialog {
                background-color: #F5F5F5;
            }
            QGroupBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
                color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #333333;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 4px 6px;
                color: #333333;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
                border: 1px solid #0078D4;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                color: #333333;
                selection-background-color: #0078D4;
                selection-color: #FFFFFF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Input section
        self._create_input_section(layout)

        # Calculate button
        self._create_calculate_button(layout)

        # Results section (hidden initially)
        self._create_results_section(layout)

        # Action buttons
        self._create_action_buttons(layout)

    def _create_input_section(self, layout: QVBoxLayout):
        """Create input fields section."""
        input_group = QGroupBox("Scoring Parameters")
        form = QFormLayout()
        form.setSpacing(8)

        # Symbol (optional - enables dynamic scoring)
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("AAPL, NVDA, etc. (enables dynamic scoring)")
        self.symbol_input.setMaxLength(10)
        self.symbol_input.textChanged.connect(self._on_symbol_changed)
        self.symbol_input.setToolTip(
            "Enter symbol for dynamic scoring (Up/Down Ratio, 50-MA, RS Trend, etc.)\n"
            "Leave empty for static scoring only."
        )
        form.addRow("Symbol:", self.symbol_input)

        # Pattern (required)
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems([''] + VALID_PATTERNS)
        self.pattern_combo.setEditable(True)
        self.pattern_combo.setToolTip("Base pattern type from MarketSurge")
        form.addRow("Pattern:", self.pattern_combo)

        # Base Stage (required)
        self.stage_combo = QComboBox()
        self.stage_combo.addItems([''] + BASE_STAGES)
        self.stage_combo.setEditable(True)
        self.stage_combo.setToolTip("Base stage (1-4+), with base-on-base notation like 2(2)")
        form.addRow("Base Stage:", self.stage_combo)

        # Base Depth (required)
        self.depth_input = QDoubleSpinBox()
        self.depth_input.setRange(0, 100)
        self.depth_input.setDecimals(1)
        self.depth_input.setSuffix("%")
        self.depth_input.setToolTip("Base depth as percentage (e.g., 23 for 23%)")
        form.addRow("Base Depth:", self.depth_input)

        # Base Length (required)
        self.length_input = QSpinBox()
        self.length_input.setRange(0, 100)
        self.length_input.setSuffix(" weeks")
        self.length_input.setToolTip("Base length in weeks")
        form.addRow("Base Length:", self.length_input)

        # RS Rating (optional but important)
        self.rs_input = QSpinBox()
        self.rs_input.setRange(0, 99)
        self.rs_input.setToolTip("IBD Relative Strength Rating (1-99). Leave 0 if unknown.")
        form.addRow("RS Rating:", self.rs_input)

        # Pivot Price (optional - for execution feasibility)
        self.pivot_input = QDoubleSpinBox()
        self.pivot_input.setRange(0, 10000)
        self.pivot_input.setDecimals(2)
        self.pivot_input.setPrefix("$")
        self.pivot_input.setToolTip("Pivot/buy point price for execution feasibility analysis")
        form.addRow("Pivot Price:", self.pivot_input)

        input_group.setLayout(form)
        layout.addWidget(input_group)

    def _create_calculate_button(self, layout: QVBoxLayout):
        """Create Calculate Score button."""
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.calc_btn = QPushButton("Calculate Score")
        self.calc_btn.setStyleSheet("""
            QPushButton {
                background-color: #17A2B8;
                color: white;
                padding: 10px 24px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 4px;
                min-width: 150px;
            }
            QPushButton:hover {
                background-color: #138496;
            }
            QPushButton:pressed {
                background-color: #117A8B;
            }
        """)
        self.calc_btn.clicked.connect(self._on_calculate)
        btn_layout.addWidget(self.calc_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _create_results_section(self, layout: QVBoxLayout):
        """Create results display section."""
        self.results_group = QGroupBox("Scoring Results")
        self.results_group.setVisible(False)
        results_layout = QVBoxLayout()
        results_layout.setSpacing(12)

        # Grade display (large, centered)
        grade_container = QHBoxLayout()
        grade_container.addStretch()

        # Grade badge
        self.grade_label = QLabel("A+")
        grade_font = QFont()
        grade_font.setPointSize(32)
        grade_font.setBold(True)
        self.grade_label.setFont(grade_font)
        self.grade_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grade_label.setMinimumWidth(80)
        self.grade_label.setMinimumHeight(60)
        self.grade_label.setStyleSheet("""
            QLabel {
                background-color: #28A745;
                color: white;
                padding: 8px 16px;
                border-radius: 8px;
            }
        """)
        grade_container.addWidget(self.grade_label)

        # Score value
        score_container = QVBoxLayout()
        score_container.setSpacing(2)

        self.score_label = QLabel("Score: 22")
        score_font = QFont()
        score_font.setPointSize(16)
        score_font.setBold(True)
        self.score_label.setFont(score_font)
        score_container.addWidget(self.score_label)

        self.config_label = QLabel("Config v2.3")
        self.config_label.setStyleSheet("color: #666666; font-size: 10px;")
        score_container.addWidget(self.config_label)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #17A2B8; font-size: 10px;")
        score_container.addWidget(self.status_label)

        grade_container.addLayout(score_container)
        grade_container.addStretch()
        results_layout.addLayout(grade_container)

        # Breakdown section - use QTextEdit for better monospace display
        self.breakdown_text = QTextEdit()
        self.breakdown_text.setReadOnly(True)
        self.breakdown_text.setFontFamily("Consolas, Monaco, monospace")
        self.breakdown_text.setMinimumHeight(300)
        self.breakdown_text.setStyleSheet("""
            QTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                font-size: 12px;
                padding: 10px;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
            }
        """)
        results_layout.addWidget(self.breakdown_text)

        # Warning label (for RS floor, etc.)
        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("""
            QLabel {
                color: #856404;
                background-color: #FFF3CD;
                padding: 8px;
                border-radius: 4px;
                font-style: italic;
            }
        """)
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        results_layout.addWidget(self.warning_label)

        # Earnings warning label (progressive colors based on proximity)
        self.earnings_warning_label = QLabel()
        self.earnings_warning_label.setWordWrap(True)
        self.earnings_warning_label.setVisible(False)
        results_layout.addWidget(self.earnings_warning_label)

        self.results_group.setLayout(results_layout)
        layout.addWidget(self.results_group)

    def _create_action_buttons(self, layout: QVBoxLayout):
        """Create action buttons."""
        # Add stretch to push buttons to bottom
        layout.addStretch()

        btn_layout = QHBoxLayout()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        btn_layout.addStretch()

        self.add_btn = QPushButton("Add to Watchlist...")
        self.add_btn.setEnabled(False)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #CCCCCC;
                color: #666666;
            }
        """)
        self.add_btn.clicked.connect(self._on_add_to_watchlist)
        btn_layout.addWidget(self.add_btn)

        layout.addLayout(btn_layout)

    def _on_symbol_changed(self, text: str):
        """Convert symbol to uppercase."""
        cursor = self.symbol_input.cursorPosition()
        self.symbol_input.blockSignals(True)
        self.symbol_input.setText(text.upper())
        self.symbol_input.setCursorPosition(cursor)
        self.symbol_input.blockSignals(False)

    def _on_calculate(self):
        """Calculate and display the score with optional dynamic factors."""
        # Validate inputs
        pattern = self.pattern_combo.currentText().strip()
        stage = self.stage_combo.currentText().strip()
        depth = self.depth_input.value()
        length = self.length_input.value()
        rs = self.rs_input.value() if self.rs_input.value() > 0 else None
        symbol = self.symbol_input.text().strip().upper()
        pivot = self.pivot_input.value() if self.pivot_input.value() > 0 else None

        if not pattern:
            QMessageBox.warning(self, "Missing Pattern",
                "Please select or enter a pattern type.")
            self.pattern_combo.setFocus()
            return

        if not stage:
            QMessageBox.warning(self, "Missing Stage",
                "Please select or enter a base stage.")
            self.stage_combo.setFocus()
            return

        # Check scorer is available
        if not self.scorer:
            QMessageBox.critical(self, "Scoring Error",
                "Scoring engine could not be loaded. Check logs for details.")
            return

        self._symbol = symbol
        self._pivot = pivot

        # Build position data
        position_data = {
            'symbol': symbol or 'PREVIEW',
            'pattern': pattern,
            'base_stage': stage,
            'base_depth': depth,
            'base_length': length,
            'rs_rating': rs,
        }

        # Get market regime (default BULLISH)
        market_regime = 'BULLISH'

        # Disable button during calculation
        self.calc_btn.setEnabled(False)
        self.calc_btn.setText("Calculating...")
        QApplication.processEvents()

        try:
            daily_df = None
            spy_df = None
            adv_50day = 0

            # If symbol is provided, try to fetch historical data for dynamic scoring
            if symbol:
                self.status_label.setText("Fetching data...")
                QApplication.processEvents()
                daily_df, spy_df, adv_50day = self._fetch_historical_data(symbol)

            # Calculate score
            if daily_df is not None and len(daily_df) >= 50:
                self.status_label.setText("Dynamic scoring...")
                QApplication.processEvents()
                self._score, self._grade, self._details = self.scorer.calculate_score_with_dynamic(
                    position_data, daily_df,
                    index_df=spy_df,
                    market_regime=market_regime
                )
                self.status_label.setText(f"Dynamic ({len(daily_df)} days)")
            else:
                self.status_label.setText("Static scoring only")
                QApplication.processEvents()
                self._score, self._grade, self._details = self.scorer.calculate_score(
                    position_data, market_regime
                )
                # More specific status messages
                if symbol:
                    if daily_df is None:
                        if adv_50day > 0:
                            self.status_label.setText("Static (data load failed)")
                        else:
                            self.status_label.setText("Static (no API key)")
                    elif len(daily_df) < 50:
                        self.status_label.setText(f"Static (only {len(daily_df)} days)")

            # Calculate execution feasibility if pivot is provided
            if pivot and adv_50day > 0:
                self.status_label.setText(self.status_label.text() + " + execution")
                exec_data = self._calculate_execution_feasibility(
                    pivot, self._grade, adv_50day, symbol=symbol
                )
                if exec_data:
                    self._details['execution'] = exec_data

            # Fetch earnings date if symbol provided and auto_fetch enabled
            self._earnings_date = None
            if symbol:
                earnings_config = self._config.get('earnings', {})
                if earnings_config.get('auto_fetch', True):
                    self._earnings_date = self._fetch_earnings_date(symbol)

            # Display results
            self._display_results()

            # Enable Add button
            self.add_btn.setEnabled(True)

            logger.info(f"Score preview: {symbol or 'N/A'} - "
                       f"Grade {self._grade}, Score {self._score}")

        except Exception as e:
            logger.error(f"Scoring error: {e}", exc_info=True)
            QMessageBox.warning(self, "Scoring Error",
                f"Error calculating score:\n{str(e)}")
        finally:
            self.calc_btn.setEnabled(True)
            self.calc_btn.setText("Calculate Score")

    def _fetch_historical_data(self, symbol: str):
        """Fetch historical price data for dynamic scoring.

        Returns:
            Tuple of (daily_df, spy_df, adv_50day) or (None, None, 0) if unavailable
        """
        try:
            from canslim_monitor.services.volume_service import VolumeService

            # Use historical_provider's client or create inline
            polygon_client = None
            if self._historical_provider and self._historical_provider.is_connected():
                polygon_client = self._historical_provider.client
                logger.info("Using historical provider for scoring data")
            else:
                from canslim_monitor.integrations.polygon_client import PolygonClient
                market_data_config = self._config.get('market_data', {})
                polygon_config = self._config.get('polygon', {})
                api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
                base_url = market_data_config.get('base_url') or polygon_config.get('base_url', 'https://api.polygon.io')

                logger.info(f"API key found: {'yes (' + api_key[:8] + '...)' if api_key else 'NO - dynamic scoring disabled'}")

                if not api_key:
                    logger.warning("No API key configured in market_data or polygon config sections")
                    return None, None, 0

                polygon_client = PolygonClient(api_key=api_key, base_url=base_url)

            # Use passed session factory or create DatabaseManager with proper path
            if self._db_session_factory:
                session_factory = self._db_session_factory
            else:
                from canslim_monitor.data.database import DatabaseManager
                # Use same db path as config if available
                db_path = self._config.get('database', {}).get('path')
                db = DatabaseManager(db_path=db_path)
                session_factory = db.get_new_session

            volume_service = VolumeService(
                db_session_factory=session_factory,
                polygon_client=polygon_client
            )

            # Fetch symbol data
            logger.info(f"Fetching historical data for {symbol}...")
            result = volume_service.update_symbol(symbol, days=200)

            if not result.success:
                logger.warning(f"Failed to fetch {symbol}: {result.error}")
                return None, None, 0

            logger.info(f"Fetch result: {result.bars_fetched} bars fetched, {result.bars_stored} stored")
            adv_50day = result.avg_volume_50d or 0
            logger.info(f"ADV 50-day: {adv_50day:,}")

            daily_df = volume_service.get_dataframe(symbol, days=200)
            if daily_df is None:
                logger.warning(f"get_dataframe returned None for {symbol}")
            else:
                logger.info(f"DataFrame has {len(daily_df)} rows")

            # Also fetch SPY for RS Trend
            spy_result = volume_service.update_symbol('SPY', days=200)
            spy_df = None
            if spy_result.success:
                spy_df = volume_service.get_dataframe('SPY', days=200)
                logger.info(f"SPY DataFrame has {len(spy_df) if spy_df is not None else 0} rows")

            return daily_df, spy_df, adv_50day

        except ImportError as e:
            logger.debug(f"Import error for data fetching: {e}")
            return None, None, 0
        except Exception as e:
            logger.warning(f"Error fetching historical data: {e}", exc_info=True)
            return None, None, 0

    def _fetch_earnings_date(self, symbol: str):
        """
        Fetch next earnings date from Polygon API.

        Args:
            symbol: Stock ticker symbol

        Returns:
            date object or None if not found
        """
        try:
            self.status_label.setText("Checking earnings...")
            QApplication.processEvents()

            # Try historical_provider first (has get_next_earnings_date pass-through)
            if self._historical_provider and self._historical_provider.is_connected():
                earnings_date = self._historical_provider.get_next_earnings_date(symbol)
            else:
                from canslim_monitor.integrations.polygon_client import PolygonClient
                market_data_config = self._config.get('market_data', {})
                polygon_config = self._config.get('polygon', {})
                api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
                base_url = market_data_config.get('base_url') or polygon_config.get('base_url', 'https://api.polygon.io')
                if not api_key:
                    logger.debug("No API key for earnings lookup")
                    return None
                polygon_client = PolygonClient(api_key=api_key, base_url=base_url)
                earnings_date = polygon_client.get_next_earnings_date(symbol)

            if earnings_date:
                logger.info(f"{symbol}: Next earnings date {earnings_date}")

                # Update position database if session factory available
                if self._db_session_factory:
                    self._update_position_earnings_date(symbol, earnings_date)

            return earnings_date

        except Exception as e:
            logger.warning(f"Error fetching earnings date for {symbol}: {e}")
            return None

    def _update_position_earnings_date(self, symbol: str, earnings_date):
        """Update position's earnings date in database if it exists."""
        try:
            from canslim_monitor.data.repositories import RepositoryManager

            session = self._db_session_factory()
            try:
                repos = RepositoryManager(session)
                position = repos.positions.get_by_symbol(symbol)
                if position:
                    repos.positions.update(position, earnings_date=earnings_date)
                    session.commit()
                    logger.debug(f"Updated {symbol} earnings date to {earnings_date}")
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"Failed to update earnings date in database: {e}")

    def _calculate_execution_feasibility(
        self,
        pivot: float,
        grade: str,
        adv_50day: int,
        symbol: str = None
    ) -> dict:
        """Calculate execution feasibility metrics for the score preview."""
        if adv_50day <= 0 or pivot <= 0:
            return {}

        # Portfolio config from config or defaults
        position_sizing = self._config.get('position_sizing', {})
        portfolio_value = position_sizing.get('portfolio_value', 100000)

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
        shares_needed = int(position_dollars / pivot) if pivot > 0 else 0

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

        # Try realtime provider first, then raw IBKR client
        _got_spread = False
        if self._realtime_provider and self._realtime_provider.is_connected() and symbol:
            try:
                quote = self._realtime_provider.get_quote(symbol)
                if quote and quote.bid and quote.ask and quote.bid > 0:
                    bid_price = quote.bid
                    ask_price = quote.ask
                    spread_pct = ((ask_price - bid_price) / bid_price) * 100
                    spread_available = True
                    if spread_pct <= 0.10:
                        spread_status = "TIGHT"
                    elif spread_pct <= 0.30:
                        spread_status = "NORMAL"
                    else:
                        spread_status = "WIDE"
                    _got_spread = True
            except Exception as e:
                logger.debug(f"Realtime provider spread fetch failed: {e}")

        if not _got_spread and self._ibkr_connected and self._ibkr_client and symbol:
            try:
                quotes = self._ibkr_client.get_quotes([symbol])
                if quotes and symbol in quotes:
                    quote_data = quotes[symbol]
                    bid_price = quote_data.get('bid')
                    ask_price = quote_data.get('ask')

                    if bid_price and ask_price and bid_price > 0:
                        spread_pct = ((ask_price - bid_price) / bid_price) * 100
                        spread_available = True

                        # Classify spread status
                        if spread_pct <= 0.10:
                            spread_status = "TIGHT"
                        elif spread_pct <= 0.30:
                            spread_status = "NORMAL"
                        else:
                            spread_status = "WIDE"
            except Exception as e:
                logger.warning(f"Could not fetch bid/ask for {symbol}: {e}")

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
            'position_dollars': position_dollars,
            'allocation_pct': allocation_pct,
            'shares_needed': shares_needed,
            'pct_of_adv': pct_of_adv,
            'overall_risk': overall_risk,
            'recommendation': recommendation,
            'spread_available': spread_available,
            'spread_pct': spread_pct,
            'spread_status': spread_status,
            'bid': bid_price,
            'ask': ask_price,
        }

    def _display_results(self):
        """Display scoring results using CLI-validator format."""
        self.results_group.setVisible(True)

        # Grade with color
        color = self.GRADE_COLORS.get(self._grade, '#6C757D')
        self.grade_label.setText(self._grade)
        self.grade_label.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                padding: 8px 16px;
                border-radius: 8px;
            }}
        """)

        # Score and config version
        self.score_label.setText(f"Score: {self._score}")
        self.config_label.setText(f"Config v{self._details.get('config_version', '?')}")

        # Use format_details_text for CLI-style output
        details_text = self.scorer.format_details_text(
            self._details,
            symbol=self._symbol or 'PREVIEW',
            pivot=self._pivot
        )
        self.breakdown_text.setPlainText(details_text)

        # Check for RS floor warning in details
        # RS floor is applied when RS < 70 and grade would be better
        rs_rating = self._details.get('components', [])
        rs_comp = next((c for c in rs_rating if c.get('name') == 'RS Rating'), None)
        if rs_comp and 'Weak' in rs_comp.get('reason', ''):
            self.warning_label.setText(
                f"RS Floor Applied: Grade capped at {self._grade} due to RS < 70 rule"
            )
            self.warning_label.setVisible(True)
        else:
            self.warning_label.setVisible(False)

        # Display earnings warning with progressive colors
        self._display_earnings_warning()

        # Adjust dialog size to fit content
        self.setMinimumHeight(650)
        self.adjustSize()

    def _display_earnings_warning(self):
        """Display earnings warning with progressive color coding."""
        from datetime import date

        # Get thresholds from config
        earnings_config = self._config.get('earnings', {})
        thresholds = earnings_config.get('warning_thresholds', {})
        critical_days = thresholds.get('critical', 5)
        caution_days = thresholds.get('caution', 10)

        if self._earnings_date:
            days_until = (self._earnings_date - date.today()).days

            if days_until < 0:
                # Earnings already passed - might be stale data
                self.earnings_warning_label.setText(
                    f"Earnings date ({self._earnings_date}) appears to be in the past. Data may be stale."
                )
                self.earnings_warning_label.setStyleSheet("""
                    QLabel {
                        color: #856404;
                        background-color: #FFF3CD;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                """)
                self.earnings_warning_label.setVisible(True)

            elif days_until <= critical_days:
                # CRITICAL - Big red warning
                self.earnings_warning_label.setText(
                    f"⚠️ EARNINGS IN {days_until} DAY{'S' if days_until != 1 else ''} ({self._earnings_date.strftime('%b %d')}) - "
                    f"HIGH RISK! Consider waiting until after earnings."
                )
                self.earnings_warning_label.setStyleSheet("""
                    QLabel {
                        color: white;
                        background-color: #DC3545;
                        padding: 10px;
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 13px;
                    }
                """)
                self.earnings_warning_label.setVisible(True)

            elif days_until <= caution_days:
                # CAUTION - Yellow warning
                self.earnings_warning_label.setText(
                    f"⚠️ Earnings in {days_until} days ({self._earnings_date.strftime('%b %d')}) - "
                    f"Monitor closely. Consider reducing position size."
                )
                self.earnings_warning_label.setStyleSheet("""
                    QLabel {
                        color: #856404;
                        background-color: #FFC107;
                        padding: 8px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                """)
                self.earnings_warning_label.setVisible(True)

            else:
                # Safe - no warning needed, but show info
                self.earnings_warning_label.setText(
                    f"Next earnings: {self._earnings_date.strftime('%b %d, %Y')} ({days_until} days away)"
                )
                self.earnings_warning_label.setStyleSheet("""
                    QLabel {
                        color: #155724;
                        background-color: #D4EDDA;
                        padding: 6px;
                        border-radius: 4px;
                    }
                """)
                self.earnings_warning_label.setVisible(True)

        elif self._symbol:
            # No earnings date found - warn user
            self.earnings_warning_label.setText(
                f"⚠️ No earnings date found for {self._symbol}. "
                f"Check MarketSurge or enter manually before trading."
            )
            self.earnings_warning_label.setStyleSheet("""
                QLabel {
                    color: #856404;
                    background-color: #FFF3CD;
                    padding: 8px;
                    border-radius: 4px;
                    font-style: italic;
                }
            """)
            self.earnings_warning_label.setVisible(True)
        else:
            self.earnings_warning_label.setVisible(False)

    def _on_add_to_watchlist(self):
        """Prepare data and close dialog for handoff to AddPositionDialog."""
        self.accept()

    def get_prepopulate_data(self) -> Dict[str, Any]:
        """
        Get data to pre-populate AddPositionDialog.

        Returns:
            Dict with keys: pattern, base_stage, base_depth, base_length,
            rs_rating (if set), symbol (if entered), pivot (if set), and internal score info
        """
        if not self._details:
            return {}

        data = {
            'pattern': self.pattern_combo.currentText().strip(),
            'base_stage': self.stage_combo.currentText().strip(),
            'base_depth': self.depth_input.value(),
            'base_length': self.length_input.value(),
        }

        # Add symbol if provided
        if self._symbol:
            data['symbol'] = self._symbol

        # Add RS rating if set
        if self.rs_input.value() > 0:
            data['rs_rating'] = self.rs_input.value()

        # Add pivot if set
        if self._pivot and self._pivot > 0:
            data['pivot'] = self._pivot

        # Store calculated score info (prefixed with _ to indicate internal)
        data['_entry_score'] = self._score
        data['_entry_grade'] = self._grade
        data['_entry_score_details'] = self._details

        # Add earnings date if fetched
        if self._earnings_date:
            data['earnings_date'] = self._earnings_date

        return data
