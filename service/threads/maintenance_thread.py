"""
CANSLIM Monitor - Maintenance Thread
====================================
Handles scheduled maintenance tasks like nightly volume updates,
earnings date updates, and database cleanup.

Runs after market close to update data for the next trading day.
"""

import logging
from datetime import datetime, time
from typing import Dict, Any, Optional

import pytz

from .base_thread import BaseThread


class MaintenanceThread(BaseThread):
    """
    Thread for handling scheduled maintenance tasks.

    Tasks:
    - Update 50-day volume averages for all active positions
    - Update earnings dates
    - Clean up old historical data

    Runs after market close (default: 5:00 PM ET) once per day.
    """

    # Default run time: 5:00 PM ET (after market close)
    DEFAULT_RUN_HOUR = 17
    DEFAULT_RUN_MINUTE = 0

    def __init__(
        self,
        shutdown_event,
        poll_interval: int = 300,  # Check every 5 minutes
        db_session_factory=None,
        polygon_client=None,
        config: Dict[str, Any] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(
            name="maintenance",
            shutdown_event=shutdown_event,
            poll_interval=poll_interval,
            logger=logger or logging.getLogger('canslim.maintenance')
        )

        self.db_session_factory = db_session_factory
        self.polygon_client = polygon_client
        self.config = config or {}

        # Configuration
        maintenance_config = self.config.get('maintenance', {})
        self.run_hour = maintenance_config.get('run_hour', self.DEFAULT_RUN_HOUR)
        self.run_minute = maintenance_config.get('run_minute', self.DEFAULT_RUN_MINUTE)
        self.enable_volume_update = maintenance_config.get('enable_volume_update', True)
        self.enable_earnings_update = maintenance_config.get('enable_earnings_update', True)
        self.enable_cleanup = maintenance_config.get('enable_cleanup', True)

        # Track last run date to ensure we only run once per day
        self._last_run_date: Optional[datetime.date] = None

        self.logger.info(
            f"Maintenance thread initialized. Run time: {self.run_hour}:{self.run_minute:02d} ET, "
            f"volume_update={self.enable_volume_update}, earnings_update={self.enable_earnings_update}"
        )

    def _should_run(self) -> bool:
        """Check if it's time to run maintenance tasks."""
        et_tz = pytz.timezone('America/New_York')
        now_et = datetime.now(et_tz)

        # Don't run on weekends
        if now_et.weekday() >= 5:
            return False

        # Check if already ran today
        if self._last_run_date == now_et.date():
            return False

        # Check if it's time to run (within the poll interval window)
        run_time = now_et.replace(
            hour=self.run_hour,
            minute=self.run_minute,
            second=0,
            microsecond=0
        )

        # Run if we're past the scheduled time
        return now_et >= run_time

    def _do_work(self):
        """Execute maintenance tasks."""
        et_tz = pytz.timezone('America/New_York')
        now_et = datetime.now(et_tz)

        self.logger.info("=" * 50)
        self.logger.info("Starting nightly maintenance tasks")
        self.logger.info("=" * 50)

        results = {
            'volume_update': None,
            'earnings_update': None,
            'cleanup': None,
        }

        # Update volume data
        if self.enable_volume_update:
            try:
                results['volume_update'] = self._update_volume_data()
            except Exception as e:
                self.logger.error(f"Volume update failed: {e}", exc_info=True)
                results['volume_update'] = {'error': str(e)}

        # Update earnings dates
        if self.enable_earnings_update:
            try:
                results['earnings_update'] = self._update_earnings_dates()
            except Exception as e:
                self.logger.error(f"Earnings update failed: {e}", exc_info=True)
                results['earnings_update'] = {'error': str(e)}

        # Cleanup old data
        if self.enable_cleanup:
            try:
                results['cleanup'] = self._cleanup_old_data()
            except Exception as e:
                self.logger.error(f"Cleanup failed: {e}", exc_info=True)
                results['cleanup'] = {'error': str(e)}

        # Mark as run for today
        self._last_run_date = now_et.date()

        self.logger.info("=" * 50)
        self.logger.info(f"Maintenance complete: {results}")
        self.logger.info("=" * 50)

    def _update_volume_data(self) -> Dict[str, Any]:
        """Update 50-day volume averages for all active positions."""
        if not self.db_session_factory or not self.polygon_client:
            self.logger.warning("Volume update skipped - missing dependencies")
            return {'skipped': 'missing dependencies'}

        from ...services.volume_service import VolumeService

        self.logger.info("Updating 50-day volume data for active positions...")

        volume_service = VolumeService(
            db_session_factory=self.db_session_factory,
            polygon_client=self.polygon_client,
            logger=self.logger
        )

        # Get all active positions (state >= 0)
        session = self.db_session_factory()
        try:
            from ...data.models import Position
            symbols = session.query(Position.symbol).filter(
                Position.state >= 0
            ).distinct().all()
            symbols = [s[0] for s in symbols]
        finally:
            session.close()

        if not symbols:
            self.logger.info("No active symbols to update")
            return {'symbols': 0, 'success': 0, 'failed': 0}

        self.logger.info(f"Updating volume data for {len(symbols)} symbols")

        success = 0
        failed = 0

        for symbol in symbols:
            try:
                result = volume_service.update_symbol(symbol, days=50)
                if result.success:
                    success += 1
                    self.logger.debug(f"{symbol}: avg_vol={result.avg_volume_50d:,}")
                else:
                    failed += 1
                    self.logger.warning(f"{symbol}: {result.error}")
            except Exception as e:
                failed += 1
                self.logger.error(f"{symbol}: {e}")

        self.logger.info(f"Volume update complete: {success}/{len(symbols)} successful")
        return {'symbols': len(symbols), 'success': success, 'failed': failed}

    def _update_earnings_dates(self) -> Dict[str, Any]:
        """Update earnings dates for positions missing or past dates."""
        if not self.db_session_factory or not self.polygon_client:
            self.logger.warning("Earnings update skipped - missing dependencies")
            return {'skipped': 'missing dependencies'}

        from ...services.earnings_service import EarningsService
        from datetime import date

        self.logger.info("Updating earnings dates for active positions...")

        earnings_service = EarningsService(
            session_factory=self.db_session_factory,
            polygon_client=self.polygon_client
        )

        # Get active positions that need earnings update
        session = self.db_session_factory()
        try:
            from ...data.models import Position
            positions = session.query(Position).filter(
                Position.state >= 0
            ).all()

            symbols_to_update = []
            today = date.today()

            for pos in positions:
                # Update if no earnings date or earnings date is past
                if not pos.earnings_date or pos.earnings_date < today:
                    symbols_to_update.append(pos.symbol)
        finally:
            session.close()

        if not symbols_to_update:
            self.logger.info("No positions need earnings update")
            return {'symbols': 0, 'updated': 0}

        self.logger.info(f"Updating earnings for {len(symbols_to_update)} symbols")

        updated = 0
        for symbol in symbols_to_update:
            try:
                earnings_date = self.polygon_client.get_next_earnings_date(symbol)
                if earnings_date:
                    if earnings_service.update_earnings_date(symbol, earnings_date):
                        updated += 1
                        self.logger.debug(f"{symbol}: earnings={earnings_date}")
            except Exception as e:
                self.logger.warning(f"{symbol}: earnings lookup failed: {e}")

        self.logger.info(f"Earnings update complete: {updated}/{len(symbols_to_update)} updated")
        return {'symbols': len(symbols_to_update), 'updated': updated}

    def _cleanup_old_data(self) -> Dict[str, Any]:
        """Clean up old historical bars and alerts."""
        if not self.db_session_factory:
            return {'skipped': 'no database'}

        from ...services.volume_service import VolumeService

        self.logger.info("Cleaning up old historical data...")

        # Create a temporary volume service just for cleanup
        volume_service = VolumeService(
            db_session_factory=self.db_session_factory,
            polygon_client=self.polygon_client,
            logger=self.logger
        )

        # Keep 100 days of bars (50 for average + buffer)
        deleted_bars = volume_service.cleanup_old_bars(days_to_keep=100)

        self.logger.info(f"Cleanup complete: {deleted_bars} old bars deleted")
        return {'deleted_bars': deleted_bars}
