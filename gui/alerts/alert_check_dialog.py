"""
CANSLIM Monitor - Alert Check Dialog
=====================================
Dialog showing real-time alert status check for a position.

This dialog runs all alert checkers against a position and displays
the results. It does NOT store alerts - it's purely for status checking.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGroupBox, QGridLayout, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from .alert_table_widget import AlertTableWidget, TypeFilterButton
from .alert_detail_dialog import AlertDetailDialog


class AlertCheckDialog(QDialog):
    """
    Dialog showing real-time alert status check for a position.

    Features:
    - Shows what checkers ran and what data was used
    - Displays triggered alerts in sortable/filterable table
    - Double-click for IBD methodology details
    - Does NOT store alerts - purely informational
    """

    def __init__(
        self,
        symbol: str,
        position_summary: Dict[str, Any],
        alerts: List[Dict[str, Any]],
        check_summary: Dict[str, Any] = None,
        parent=None,
    ):
        """
        Initialize the alert check dialog.

        Args:
            symbol: Stock symbol
            position_summary: Dict with price, entry, pnl_pct, state info
            alerts: List of alert dictionaries from AlertCheckerTool
            check_summary: Dict with checkers_run, technical_data, etc.
            parent: Parent widget
        """
        super().__init__(parent)

        self.symbol = symbol
        self.position_summary = position_summary
        self.alerts = alerts
        self.check_summary = check_summary or {}

        self._setup_ui()
        self._populate_data()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle(f"Alert Status Check: {self.symbol}")
        self.setMinimumSize(800, 600)
        self.setModal(False)  # Modeless - don't block main window

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header with position info
        header = self._create_header()
        layout.addWidget(header)

        # Check summary panel (what was checked)
        summary_panel = self._create_summary_panel()
        layout.addWidget(summary_panel)

        # Filter row
        filter_row = self._create_filter_row()
        layout.addLayout(filter_row)

        # Alert table (no symbol column since all same symbol)
        self.table = AlertTableWidget(show_symbol_column=False)
        self.table.alert_double_clicked.connect(self._on_alert_double_click)
        layout.addWidget(self.table, stretch=1)

        # No alerts message (hidden initially)
        self.no_alerts_label = QLabel("All checks passed - no alerts triggered")
        self.no_alerts_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_alerts_label.setStyleSheet("""
            QLabel {
                color: #28A745;
                font-size: 14px;
                padding: 20px;
                background-color: #E8F5E9;
                border-radius: 5px;
            }
        """)
        self.no_alerts_label.setVisible(False)
        layout.addWidget(self.no_alerts_label)

        # Footer
        footer = self._create_footer()
        layout.addLayout(footer)

    def _create_header(self) -> QFrame:
        """Create the header frame with position info."""
        is_breakout = self.check_summary.get('is_breakout_check', False)

        frame = QFrame()
        # Use different background color for breakout vs position checks
        bg_color = "#2E5090" if is_breakout else "#1E3A5F"
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 5px;
                padding: 5px;
            }}
            QLabel {{
                color: white;
            }}
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)

        # Title - different for breakout vs position
        if is_breakout:
            title = QLabel(f"🎯 Breakout Status: {self.symbol}")
        else:
            title = QLabel(f"🔍 Alert Status Check: {self.symbol}")
        title.setFont(QFont('Arial', 14, QFont.Weight.Bold))
        layout.addWidget(title)

        layout.addStretch()

        # Position info
        price = self.position_summary.get('current_price', 0)
        entry = self.position_summary.get('entry_price', 0)
        pnl = self.position_summary.get('pnl_pct', 0)
        state_name = self.position_summary.get('state_name', '')

        info_parts = []
        if price > 0:
            info_parts.append(f"Price: ${price:.2f}")
        if entry > 0:
            # Show "Pivot" for breakout checks, "Entry" for position checks
            label = "Pivot" if is_breakout else "Entry"
            info_parts.append(f"{label}: ${entry:.2f}")
        if pnl != 0:
            pnl_color = '#90EE90' if pnl >= 0 else '#FF6B6B'
            # Show "Dist" for breakout checks, just % for position checks
            if is_breakout:
                info_parts.append(f"<span style='color:{pnl_color};font-weight:bold'>Dist: {pnl:+.1f}%</span>")
            else:
                info_parts.append(f"<span style='color:{pnl_color};font-weight:bold'>{pnl:+.1f}%</span>")
        if state_name:
            info_parts.append(f"State: {state_name}")

        info_text = "  |  ".join(info_parts)
        info_label = QLabel(info_text)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setFont(QFont('Arial', 10))
        layout.addWidget(info_label)

        return frame

    def _create_summary_panel(self) -> QGroupBox:
        """Create the summary panel showing what was checked."""
        is_breakout = self.check_summary.get('is_breakout_check', False)
        title = "Breakout Check" if is_breakout else "Checkers Run"

        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #DEE2E6;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        if is_breakout:
            # Breakout-specific summary panel
            self._create_breakout_summary(layout)
        else:
            # Position checker summary panel
            self._create_position_checker_summary(layout)

        return group

    def _create_breakout_summary(self, layout: QVBoxLayout):
        """Create summary panel for breakout checks (watchlist items)."""
        tech_data = self.check_summary.get('technical_data', {})
        current_price = self.position_summary.get('current_price', 0)

        # Checker status row - Breakout + Alt Entry
        checkers_layout = QHBoxLayout()
        checkers_layout.setSpacing(15)

        # Separate alerts by type
        breakout_alerts = [a for a in self.alerts if a.get('alert_type', '').upper() == 'BREAKOUT']
        alt_entry_alerts = [a for a in self.alerts if a.get('alert_type', '').upper() == 'ALT_ENTRY']

        # --- Breakout Checker ---
        breakout_frame = QFrame()
        breakout_layout = QHBoxLayout(breakout_frame)
        breakout_layout.setContentsMargins(5, 2, 5, 2)
        breakout_layout.setSpacing(3)

        # Determine breakout status from alerts
        if breakout_alerts:
            subtype = breakout_alerts[0].get('subtype', '')
            if subtype in ('CONFIRMED', 'IN_BUY_ZONE'):
                status_icon = "🟢"  # Green - in breakout territory
                bg_color = "#D4EDDA"
            elif subtype == 'EXTENDED':
                status_icon = "🟡"  # Yellow - extended
                bg_color = "#FFF3CD"
            elif subtype == 'SUPPRESSED':
                status_icon = "🔴"  # Red - suppressed
                bg_color = "#F8D7DA"
            elif subtype == 'APPROACHING':
                status_icon = "🔵"  # Blue - approaching
                bg_color = "#CCE5FF"
            else:
                status_icon = "⚪"  # Gray - below pivot
                bg_color = "#F8F9FA"
        else:
            status_icon = "⚪"
            bg_color = "#F8F9FA"

        breakout_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 3px;
                padding: 2px;
            }}
        """)

        label = QLabel(f"{status_icon} 🎯 Breakout")
        label.setToolTip("Pivot breakout detection: confirmed, buy zone, approaching, extended")
        label.setFont(QFont('Arial', 9))
        breakout_layout.addWidget(label)

        if breakout_alerts:
            subtype = breakout_alerts[0].get('subtype', 'CHECKING')
            status_label = QLabel(f"({subtype.replace('_', ' ')})")
            status_label.setStyleSheet("font-weight: bold;")
            breakout_layout.addWidget(status_label)

        checkers_layout.addWidget(breakout_frame)

        # --- Alt Entry Checker ---
        alt_entry_frame = QFrame()
        alt_entry_layout = QHBoxLayout(alt_entry_frame)
        alt_entry_layout.setContentsMargins(5, 2, 5, 2)
        alt_entry_layout.setSpacing(3)

        if alt_entry_alerts:
            # Alt entry opportunity found
            alt_status_icon = "🔔"
            alt_bg_color = "#CCE5FF"  # Blue - opportunity
        else:
            # No alt entry (either not extended or no pullback)
            alt_status_icon = "✅"
            alt_bg_color = "#D4EDDA"  # Green - checked, no alert

        alt_entry_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {alt_bg_color};
                border-radius: 3px;
                padding: 2px;
            }}
        """)

        alt_label = QLabel(f"{alt_status_icon} 📉 Alt Entry")
        alt_label.setToolTip("MA pullback opportunities: 21 EMA, 50 MA, pivot retest after extension")
        alt_label.setFont(QFont('Arial', 9))
        alt_entry_layout.addWidget(alt_label)

        if alt_entry_alerts:
            subtype = alt_entry_alerts[0].get('subtype', '')
            status_text = subtype.replace('_', ' ') if subtype else 'OPPORTUNITY'
            alt_status_label = QLabel(f"({status_text})")
            alt_status_label.setStyleSheet("font-weight: bold; color: #004085;")
            alt_entry_layout.addWidget(alt_status_label)

        checkers_layout.addWidget(alt_entry_frame)
        checkers_layout.addStretch()
        layout.addLayout(checkers_layout)

        # Breakout data row (pivot, buy zone, volume)
        if tech_data:
            data_layout = QHBoxLayout()
            data_layout.setSpacing(20)

            data_label = QLabel("Breakout Data:")
            data_label.setStyleSheet("font-weight: bold; color: #666;")
            data_layout.addWidget(data_label)

            pivot = tech_data.get('pivot', 0)
            buy_zone_top = tech_data.get('buy_zone_top', 0)
            rvol = tech_data.get('rvol', 0)
            avg_volume = tech_data.get('avg_volume', 0)

            # Pivot with distance %
            if pivot > 0:
                distance_pct = ((current_price - pivot) / pivot * 100) if current_price > 0 else 0
                pct_color = '#28A745' if distance_pct >= 0 else '#DC3545'
                pct_str = f"<span style='color:{pct_color};'>({distance_pct:+.1f}%)</span>"
                pivot_label = QLabel(f"Pivot: ${pivot:.2f} {pct_str}")
                pivot_label.setTextFormat(Qt.TextFormat.RichText)
                data_layout.addWidget(pivot_label)

            # Buy zone
            if pivot > 0 and buy_zone_top > 0:
                data_layout.addWidget(QLabel(f"Buy Zone: ${pivot:.2f} - ${buy_zone_top:.2f}"))

            # RVOL with color coding
            if rvol > 0:
                if rvol >= 1.4:
                    rvol_color = '#28A745'  # Green - confirmed volume
                    rvol_label_text = f"RVOL: <span style='color:{rvol_color};font-weight:bold;'>{rvol:.1f}x ✓</span>"
                elif rvol >= 1.0:
                    rvol_color = '#FFC107'  # Yellow - average
                    rvol_label_text = f"RVOL: <span style='color:{rvol_color};'>{rvol:.1f}x</span>"
                else:
                    rvol_color = '#DC3545'  # Red - below average
                    rvol_label_text = f"RVOL: <span style='color:{rvol_color};'>{rvol:.1f}x</span>"
                rvol_label = QLabel(rvol_label_text)
                rvol_label.setTextFormat(Qt.TextFormat.RichText)
                data_layout.addWidget(rvol_label)
            elif avg_volume > 0:
                # Show that RVOL couldn't be calculated
                data_layout.addWidget(QLabel("RVOL: N/A (no intraday vol)"))

            # Average volume
            if avg_volume > 0:
                if avg_volume >= 1_000_000:
                    avg_vol_str = f"{avg_volume/1_000_000:.1f}M"
                else:
                    avg_vol_str = f"{avg_volume/1_000:.0f}K"
                data_layout.addWidget(QLabel(f"Avg Vol: {avg_vol_str}"))

            data_layout.addStretch()
            layout.addLayout(data_layout)

        # MA data row (for alt entry checks)
        ma_21 = tech_data.get('ma_21')
        ma_50 = tech_data.get('ma_50')
        ma_200 = tech_data.get('ma_200')

        if ma_21 or ma_50:
            ma_layout = QHBoxLayout()
            ma_layout.setSpacing(20)

            ma_label = QLabel("Alt Entry Data:")
            ma_label.setStyleSheet("font-weight: bold; color: #666;")
            ma_layout.addWidget(ma_label)

            def ma_label_with_pct(name: str, ma_value: float) -> QLabel:
                """Create MA label with percentage distance from current price."""
                if current_price > 0 and ma_value > 0:
                    pct_diff = ((current_price - ma_value) / ma_value) * 100
                    pct_color = '#28A745' if pct_diff >= 0 else '#DC3545'
                    pct_str = f"<span style='color:{pct_color};'>({pct_diff:+.1f}%)</span>"
                    lbl = QLabel(f"{name}: ${ma_value:.2f} {pct_str}")
                    lbl.setTextFormat(Qt.TextFormat.RichText)
                else:
                    lbl = QLabel(f"{name}: ${ma_value:.2f}")
                return lbl

            if ma_21:
                ma_layout.addWidget(ma_label_with_pct("21 EMA", ma_21))
            if ma_50:
                ma_layout.addWidget(ma_label_with_pct("50 MA", ma_50))
            if ma_200:
                ma_layout.addWidget(ma_label_with_pct("200 MA", ma_200))

            ma_layout.addStretch()
            layout.addLayout(ma_layout)
        elif not tech_data.get('ma_21') and not tech_data.get('ma_50'):
            # No MA data available - show notice
            no_ma_layout = QHBoxLayout()
            no_ma_label = QLabel("Alt Entry Data: (No MA data - alt entry alerts unavailable)")
            no_ma_label.setStyleSheet("color: #999; font-style: italic;")
            no_ma_layout.addWidget(no_ma_label)
            no_ma_layout.addStretch()
            layout.addLayout(no_ma_layout)

    def _create_position_checker_summary(self, layout: QVBoxLayout):
        """Create summary panel for position checks (state 1+)."""
        # Checkers status row
        checkers_layout = QHBoxLayout()
        checkers_layout.setSpacing(15)

        # Define checkers with their icons and what they check
        checker_info = [
            ('Stop', '🛑', 'Hard stop, trailing stop, stop warning'),
            ('Profit', '💰', 'TP1, TP2, 8-week hold rule'),
            ('Pyramid', '📈', 'P1/P2 zones, pullback to 21 EMA'),
            ('MA', '📊', '50 MA, 21 EMA, 10-week violations'),
            ('Health', '⚠️', 'Critical health, earnings, late stage'),
        ]

        checkers_run = self.check_summary.get('checkers_run', [])

        for name, icon, tooltip in checker_info:
            checker_frame = QFrame()
            checker_layout = QHBoxLayout(checker_frame)
            checker_layout.setContentsMargins(5, 2, 5, 2)
            checker_layout.setSpacing(3)

            # Determine if this checker ran and found alerts
            ran = name.lower() in [c.lower() for c in checkers_run] or not checkers_run
            alerts_for_checker = [a for a in self.alerts if self._alert_matches_checker(a, name)]

            if ran:
                if alerts_for_checker:
                    status_icon = "🔴"  # Found alerts
                    bg_color = "#FFF3CD"  # Yellow background
                else:
                    status_icon = "✅"  # Passed
                    bg_color = "#D4EDDA"  # Green background
            else:
                status_icon = "⚪"  # Not run
                bg_color = "#F8F9FA"  # Gray background

            checker_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg_color};
                    border-radius: 3px;
                    padding: 2px;
                }}
            """)

            label = QLabel(f"{status_icon} {icon} {name}")
            label.setToolTip(tooltip)
            label.setFont(QFont('Arial', 9))
            checker_layout.addWidget(label)

            if alerts_for_checker:
                count_label = QLabel(f"({len(alerts_for_checker)})")
                count_label.setStyleSheet("color: #856404; font-weight: bold;")
                checker_layout.addWidget(count_label)

            checkers_layout.addWidget(checker_frame)

        checkers_layout.addStretch()
        layout.addLayout(checkers_layout)

        # Technical data row (if available)
        tech_data = self.check_summary.get('technical_data', {})
        if tech_data:
            tech_layout = QHBoxLayout()
            tech_layout.setSpacing(20)

            tech_label = QLabel("Technical Data:")
            tech_label.setStyleSheet("font-weight: bold; color: #666;")
            tech_layout.addWidget(tech_label)

            ma_21 = tech_data.get('ma_21')
            ma_50 = tech_data.get('ma_50')
            ma_200 = tech_data.get('ma_200')
            ma_10w = tech_data.get('ma_10_week')

            # Get current price for percentage calculation
            current_price = self.position_summary.get('current_price', 0)

            def ma_label_with_pct(name: str, ma_value: float) -> QLabel:
                """Create MA label with percentage distance from current price."""
                if current_price > 0 and ma_value > 0:
                    pct_diff = ((current_price - ma_value) / ma_value) * 100
                    pct_color = '#28A745' if pct_diff >= 0 else '#DC3545'
                    pct_str = f"<span style='color:{pct_color};'>({pct_diff:+.1f}%)</span>"
                    label = QLabel(f"{name}: ${ma_value:.2f} {pct_str}")
                    label.setTextFormat(Qt.TextFormat.RichText)
                else:
                    label = QLabel(f"{name}: ${ma_value:.2f}")
                return label

            if ma_21:
                tech_layout.addWidget(ma_label_with_pct("21 EMA", ma_21))
            if ma_50:
                tech_layout.addWidget(ma_label_with_pct("50 MA", ma_50))
            if ma_200:
                tech_layout.addWidget(ma_label_with_pct("200 MA", ma_200))
            if ma_10w:
                tech_layout.addWidget(ma_label_with_pct("10W", ma_10w))

            if not any([ma_21, ma_50, ma_200, ma_10w]):
                no_data_label = QLabel("(No MA data available - MA alerts disabled)")
                no_data_label.setStyleSheet("color: #999; font-style: italic;")
                tech_layout.addWidget(no_data_label)

            tech_layout.addStretch()
            layout.addLayout(tech_layout)

    def _alert_matches_checker(self, alert: Dict, checker_name: str) -> bool:
        """Check if an alert came from a specific checker."""
        alert_type = alert.get('alert_type', '').upper()
        checker_map = {
            'STOP': ['STOP'],
            'PROFIT': ['PROFIT'],
            'PYRAMID': ['PYRAMID', 'ADD'],
            'MA': ['TECHNICAL'],
            'HEALTH': ['HEALTH'],
            'BREAKOUT': ['BREAKOUT'],
            'ALT_ENTRY': ['ALT_ENTRY'],  # Watchlist MA bounce/pivot retest
        }
        return alert_type in checker_map.get(checker_name, [])

    def _create_filter_row(self) -> QHBoxLayout:
        """Create the filter row."""
        layout = QHBoxLayout()

        # Results label
        results_label = QLabel("Results:")
        results_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(results_label)

        # Type filter
        self.type_filter = TypeFilterButton()
        self.type_filter.filter_changed.connect(self._on_type_filter_changed)
        layout.addWidget(self.type_filter)

        layout.addStretch()

        # Alert count
        self.count_label = QLabel()
        layout.addWidget(self.count_label)

        return layout

    def _create_footer(self) -> QHBoxLayout:
        """Create the footer row."""
        layout = QHBoxLayout()

        # Info label
        self.info_label = QLabel("Double-click row for IBD methodology details")
        self.info_label.setStyleSheet("color: #888;")
        layout.addWidget(self.info_label)

        layout.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setMinimumWidth(80)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        return layout

    def _populate_data(self):
        """Populate the table with alerts."""
        is_breakout = self.check_summary.get('is_breakout_check', False)

        if is_breakout:
            # Breakout check - always show the alert (even status alerts like BELOW_PIVOT)
            if not self.alerts:
                self.table.setVisible(False)
                self.no_alerts_label.setVisible(True)
                self.no_alerts_label.setText("No breakout status available")
                self.no_alerts_label.setStyleSheet("""
                    QLabel {
                        color: #666;
                        font-size: 14px;
                        padding: 20px;
                        background-color: #F8F9FA;
                        border-radius: 5px;
                    }
                """)
                self.count_label.setText("Breakout check complete")
                self.info_label.setText("No pivot set or no price data")
            else:
                # For breakout, we typically have 1 alert showing the status
                self.table.setVisible(True)
                self.no_alerts_label.setVisible(False)
                self.table.set_alerts(self.alerts)

                # Update type filter options
                available_types = self.table.get_available_types()
                self.type_filter.set_available_types(available_types)

                self._update_count()
                self.info_label.setText("Double-click row for breakout methodology details")
        else:
            # Position check - 5 checkers
            total_checks = 5  # Stop, Profit, Pyramid, MA, Health

            if not self.alerts:
                # No alerts - show success message
                self.table.setVisible(False)
                self.no_alerts_label.setVisible(True)
                self.no_alerts_label.setText("All checks passed - no alerts triggered")
                self.no_alerts_label.setStyleSheet("""
                    QLabel {
                        color: #28A745;
                        font-size: 14px;
                        padding: 20px;
                        background-color: #E8F5E9;
                        border-radius: 5px;
                    }
                """)
                self.count_label.setText(f"0 alerts from {total_checks} checkers")
                self.info_label.setText("Position passed all alert checks")
            else:
                self.table.setVisible(True)
                self.no_alerts_label.setVisible(False)
                self.table.set_alerts(self.alerts)

                # Update type filter options
                available_types = self.table.get_available_types()
                self.type_filter.set_available_types(available_types)

                # Update count
                self._update_count()
                self.info_label.setText("Double-click row for IBD methodology details")

    def _update_count(self):
        """Update the alert count label."""
        total = self.table.get_alert_count()
        filtered = self.table.get_filtered_count()

        if total == filtered:
            self.count_label.setText(f"{total} alert(s) triggered")
        else:
            self.count_label.setText(f"Showing: {filtered} of {total} alerts")

    def _on_type_filter_changed(self, types: set):
        """Handle type filter change."""
        self.table.set_type_filter(types)
        self._update_count()

    def _on_alert_double_click(self, alert: Dict[str, Any]):
        """Handle double-click on alert row."""
        # Open detail dialog for IBD methodology
        dialog = AlertDetailDialog(
            alert=alert,
            parent=self,
            alert_service=None,  # No acknowledge functionality
            db_session_factory=None
        )
        dialog.exec()

    def update_alerts(self, alerts: List[Dict[str, Any]], position_summary: Dict[str, Any] = None):
        """
        Update the displayed alerts.

        Args:
            alerts: New list of alerts
            position_summary: Updated position summary (optional)
        """
        self.alerts = alerts
        if position_summary:
            self.position_summary = position_summary
        self._populate_data()


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Test data - position summary
    test_summary = {
        'current_price': 145.20,
        'entry_price': 135.00,
        'pnl_pct': 7.6,
        'state_name': 'Building (2)',
    }

    # Test check summary
    test_check_summary = {
        'checkers_run': ['stop', 'profit', 'pyramid', 'ma', 'health'],
        'technical_data': {
            'ma_21': 142.50,
            'ma_50': 138.00,
            'ma_200': 125.00,
            'ma_10_week': 140.00,
        }
    }

    # Test data - alerts
    test_alerts = [
        {
            'id': None,
            'symbol': 'NVDA',
            'alert_type': 'PYRAMID',
            'subtype': 'P1_READY',
            'alert_time': '2026-01-18T09:32:00',
            'price': 145.20,
            'pnl_pct_at_alert': 7.6,
            'severity': 'info',
            'acknowledged': False,
            'message': 'EMBED:{"title":"P1 Ready","description":"First pyramid zone"}',
            'action': 'ADD 25% TO POSITION',
        },
        {
            'id': None,
            'symbol': 'NVDA',
            'alert_type': 'HEALTH',
            'subtype': 'EARNINGS',
            'alert_time': '2026-01-18T09:32:00',
            'price': 145.20,
            'pnl_pct_at_alert': 7.6,
            'severity': 'warning',
            'acknowledged': False,
            'message': 'Earnings in 12 days',
            'action': 'SELL BEFORE EARNINGS',
        },
    ]

    dialog = AlertCheckDialog("NVDA", test_summary, test_alerts, test_check_summary)
    dialog.exec()

    # Test empty alerts (all passed)
    dialog2 = AlertCheckDialog(
        "AMD",
        {'current_price': 150.0, 'entry_price': 140.0, 'pnl_pct': 7.1, 'state_name': 'Entry 1 (1)'},
        [],
        {'checkers_run': ['stop', 'profit', 'pyramid', 'ma', 'health'], 'technical_data': {'ma_50': 145.0}}
    )
    dialog2.exec()
