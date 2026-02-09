"""
Backtest Data Importer

Imports SwingTrader backtest data from backtest_training.db into
the main canslim_positions.db outcomes table for learning engine analysis.
"""

import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List

from sqlalchemy.orm import Session
from canslim_monitor.data.models import Outcome
from canslim_monitor.data.database import DatabaseManager

logger = logging.getLogger(__name__)


class BacktestImporter:
    """Import backtest data from Polygon factor calculator output."""

    def __init__(self, main_db: DatabaseManager, backtest_db_path: str):
        """
        Args:
            main_db: DatabaseManager for canslim_positions.db
            backtest_db_path: Path to backtest_training.db
        """
        self.main_db = main_db
        self.backtest_db_path = Path(backtest_db_path)
        self.stats = {
            'total_read': 0,
            'imported': 0,
            'skipped_duplicate': 0,
            'skipped_missing_data': 0,
            'errors': 0
        }

    def import_all(self, overwrite: bool = False) -> Dict:
        """
        Import all backtest trades into outcomes table.

        Args:
            overwrite: If True, delete existing backtest outcomes first

        Returns:
            Import statistics dict
        """
        if not self.backtest_db_path.exists():
            raise FileNotFoundError(f"Backtest DB not found: {self.backtest_db_path}")

        # Connect to backtest DB (read-only)
        bt_conn = sqlite3.connect(f"file:{self.backtest_db_path}?mode=ro", uri=True)
        bt_conn.row_factory = sqlite3.Row

        session = self.main_db.get_new_session()

        try:
            if overwrite:
                deleted = session.query(Outcome).filter(
                    Outcome.source == 'swingtrader'
                ).delete()
                logger.info(f"Deleted {deleted} existing SwingTrader outcomes")
                session.commit()

            # Query the calculated_factors table directly
            query = """
                SELECT
                    id,
                    symbol,
                    entry_date,
                    entry_price,
                    -- Base characteristics
                    base_depth_pct,
                    base_length_weeks,
                    base_length_days,
                    prior_uptrend_pct,
                    -- Technical factors
                    relative_strength_52w,
                    relative_strength_13w,
                    price_vs_50ma_pct,
                    price_vs_200ma_pct,
                    ma_aligned,
                    volume_dryup_ratio,
                    breakout_volume_ratio,
                    rsi_14,
                    atr_pct,
                    -- Market context
                    market_regime,
                    spy_price_at_entry,
                    spy_vs_50ma_pct,
                    distribution_days,
                    -- Forward returns
                    return_5d,
                    return_10d,
                    return_20d,
                    return_40d,
                    return_60d,
                    -- Risk metrics
                    max_gain_pct,
                    max_drawdown_pct,
                    days_to_max_gain,
                    hit_7pct_stop,
                    hit_10pct_target,
                    hit_20pct_target,
                    days_to_20pct,
                    -- Outcome classification
                    canslim_outcome,
                    canslim_outcome_score,
                    -- Swing trade metrics
                    swing_optimal_exit_day,
                    swing_optimal_exit_gain
                FROM calculated_factors
                WHERE canslim_outcome IS NOT NULL
                ORDER BY entry_date
            """

            rows = bt_conn.execute(query).fetchall()
            self.stats['total_read'] = len(rows)
            logger.info(f"Read {len(rows)} trades from backtest DB")

            for row in rows:
                try:
                    self._import_row(session, dict(row), overwrite)
                except Exception as e:
                    logger.error(f"Error importing {row['symbol']} {row['entry_date']}: {e}")
                    self.stats['errors'] += 1

            session.commit()
            logger.info(f"Import complete: {self.stats}")

        finally:
            session.close()
            bt_conn.close()

        return self.stats

    def _import_row(self, session: Session, row: Dict, overwrite: bool):
        """Import a single backtest trade into outcomes."""

        # Check for required fields
        if not row.get('symbol') or not row.get('entry_date'):
            self.stats['skipped_missing_data'] += 1
            return

        # Check for duplicates (same symbol + entry_date + source)
        if not overwrite:
            existing = session.query(Outcome).filter(
                Outcome.symbol == row['symbol'],
                Outcome.entry_date == self._parse_date(row['entry_date']),
                Outcome.source == 'swingtrader'
            ).first()

            if existing:
                self.stats['skipped_duplicate'] += 1
                return

        # Calculate holding days estimate based on optimal exit or 20d target
        holding_days = row.get('swing_optimal_exit_day') or row.get('days_to_20pct') or 20

        # Calculate exit price from return
        entry_price = row.get('entry_price') or 0
        return_pct = row.get('return_20d') or 0
        exit_price = entry_price * (1 + return_pct / 100) if entry_price else None

        # Map backtest data to Outcome model
        outcome = Outcome(
            symbol=row['symbol'],
            portfolio='SwingTrader',

            # Entry context
            entry_date=self._parse_date(row['entry_date']),
            entry_price=entry_price,

            # Map Polygon factors to CANSLIM factor columns
            rs_at_entry=self._rs_to_rating(row.get('relative_strength_52w')),
            base_depth_at_entry=row.get('base_depth_pct'),
            base_length_at_entry=self._weeks_to_int(row.get('base_length_weeks')),
            market_regime_at_entry=self._map_regime(row.get('market_regime')),
            spy_at_entry=row.get('spy_price_at_entry'),
            dist_days_at_entry=row.get('distribution_days'),

            # Exit data (estimated)
            exit_price=exit_price,
            exit_reason='BACKTEST',
            holding_days=holding_days,

            # Results - use return_20d as the main result
            gross_pct=return_pct,

            # Risk metrics
            max_gain_pct=row.get('max_gain_pct'),
            max_drawdown_pct=row.get('max_drawdown_pct'),
            days_to_max_gain=row.get('days_to_max_gain'),
            hit_stop=bool(row.get('hit_7pct_stop')),

            # Classification - map outcome names
            outcome=self._map_outcome(row.get('canslim_outcome')),
            outcome_score=int(row.get('canslim_outcome_score') or 0),

            # Source tracking
            source='swingtrader',
            validated=False,
            validation_notes=f"Imported from backtest_training.db id={row.get('id')}"
        )

        session.add(outcome)
        self.stats['imported'] += 1

    def _parse_date(self, date_str) -> Optional[date]:
        """Parse date from string or return None."""
        if not date_str:
            return None
        if isinstance(date_str, date):
            return date_str
        try:
            return datetime.strptime(str(date_str), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    def _rs_to_rating(self, relative_strength_52w: Optional[float]) -> Optional[int]:
        """
        Convert our calculated 52-week relative strength (0-100 percentile)
        to approximate IBD-style RS Rating (1-99).
        """
        if relative_strength_52w is None:
            return None
        return max(1, min(99, int(relative_strength_52w)))

    def _weeks_to_int(self, weeks: Optional[float]) -> Optional[int]:
        """Convert float weeks to integer."""
        if weeks is None:
            return None
        return max(1, int(round(weeks)))

    def _map_regime(self, regime: Optional[str]) -> Optional[str]:
        """Map market regime to our regime enum."""
        if not regime:
            return None
        regime_upper = str(regime).upper()
        if regime_upper in ('BULLISH', 'BULL', 'UPTREND', 'CONFIRMED_UPTREND'):
            return 'BULLISH'
        elif regime_upper in ('BEARISH', 'BEAR', 'DOWNTREND', 'MARKET_IN_CORRECTION'):
            return 'BEARISH'
        return 'NEUTRAL'

    def _map_outcome(self, outcome: Optional[str]) -> Optional[str]:
        """Map backtest outcome to our outcome enum."""
        if not outcome:
            return None
        outcome_upper = str(outcome).upper()
        # Map to: SUCCESS, PARTIAL, STOPPED, FAILED
        outcome_map = {
            'SUCCESS': 'SUCCESS',
            'GOOD': 'SUCCESS',           # GOOD = hit target
            'PARTIAL': 'PARTIAL',
            'PENDING_GOOD': 'PARTIAL',   # Pending but trending good
            'PENDING_PARTIAL': 'PARTIAL',
            'STOPPED': 'STOPPED',        # Hit stop loss
            'FAILED': 'FAILED',
            'PENDING_NEGATIVE': 'FAILED',
            'NEGATIVE': 'FAILED',
        }
        return outcome_map.get(outcome_upper, 'FAILED')

    def get_summary_report(self) -> str:
        """Generate formatted import summary."""
        lines = [
            "=" * 60,
            "BACKTEST IMPORT SUMMARY",
            "=" * 60,
            f"Source: {self.backtest_db_path}",
            f"Total records read: {self.stats['total_read']}",
            f"Successfully imported: {self.stats['imported']}",
            f"Skipped (duplicate): {self.stats['skipped_duplicate']}",
            f"Skipped (missing data): {self.stats['skipped_missing_data']}",
            f"Errors: {self.stats['errors']}",
            "=" * 60,
        ]
        return "\n".join(lines)


def get_backtest_summary(backtest_db_path: str) -> Dict:
    """Get summary statistics from backtest database without importing."""
    if not Path(backtest_db_path).exists():
        return {'error': f'Database not found: {backtest_db_path}'}

    conn = sqlite3.connect(backtest_db_path)
    cursor = conn.cursor()

    summary = {}

    try:
        cursor.execute("SELECT COUNT(*) FROM calculated_factors")
        summary['total_trades'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM calculated_factors WHERE canslim_outcome IS NOT NULL")
        summary['trades_with_outcomes'] = cursor.fetchone()[0]

        cursor.execute("SELECT canslim_outcome, COUNT(*) FROM calculated_factors GROUP BY canslim_outcome")
        summary['outcome_distribution'] = dict(cursor.fetchall())

        cursor.execute("SELECT AVG(return_20d) FROM calculated_factors WHERE return_20d IS NOT NULL")
        avg_return = cursor.fetchone()[0]
        summary['avg_return_pct'] = round(avg_return, 2) if avg_return else 0

        cursor.execute("SELECT MIN(entry_date), MAX(entry_date) FROM calculated_factors")
        row = cursor.fetchone()
        summary['date_range'] = {'start': row[0], 'end': row[1]}

    except Exception as e:
        summary['error'] = str(e)
    finally:
        conn.close()

    return summary
