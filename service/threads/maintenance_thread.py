"""
CANSLIM Monitor - Maintenance Thread
====================================
Handles scheduled maintenance tasks like nightly volume updates,
earnings date updates, database cleanup, and database backups.

Runs after market close to update data for the next trading day.
"""

import logging
import shutil
from datetime import datetime, time
from pathlib import Path
from typing import Dict, Any, Optional, List

import pytz

from .base_thread import BaseThread


class MaintenanceThread(BaseThread):
    """
    Thread for handling scheduled maintenance tasks.

    Tasks:
    - Update 50-day volume averages for all active positions
    - Update earnings dates
    - Clean up old historical data
    - Backup database

    Runs after market close (default: 5:00 PM ET) once per day.
    """

    # Default run time: 5:00 PM ET (after market close)
    DEFAULT_RUN_HOUR = 17
    DEFAULT_RUN_MINUTE = 0

    # Default cleanup settings
    DEFAULT_BARS_DAYS_TO_KEEP = 200  # Keep more for backtesting/ML work

    # Default backup settings
    DEFAULT_BACKUP_COUNT = 7  # Keep 7 daily backups
    DEFAULT_BACKUP_DIR = None  # Same directory as database

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
        self.enable_backup = maintenance_config.get('enable_backup', True)

        # Cleanup settings - configurable for backtesting/ML needs
        self.bars_days_to_keep = maintenance_config.get(
            'bars_days_to_keep', self.DEFAULT_BARS_DAYS_TO_KEEP
        )

        # Backup settings
        self.backup_count = maintenance_config.get('backup_count', self.DEFAULT_BACKUP_COUNT)
        self.backup_dir = maintenance_config.get('backup_dir', self.DEFAULT_BACKUP_DIR)

        # Get database path from config for backup
        self.db_path = self.config.get('database', {}).get('path')

        # Track last run date to ensure we only run once per day
        self._last_run_date: Optional[datetime.date] = None

        self.logger.info(
            f"Maintenance thread initialized. Run time: {self.run_hour}:{self.run_minute:02d} ET, "
            f"volume_update={self.enable_volume_update}, earnings_update={self.enable_earnings_update}, "
            f"backup={self.enable_backup}, bars_keep={self.bars_days_to_keep} days"
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
            'backup': None,
        }

        # Backup database first (before any modifications)
        if self.enable_backup:
            try:
                results['backup'] = self._backup_database()
            except Exception as e:
                self.logger.error(f"Database backup failed: {e}", exc_info=True)
                results['backup'] = {'error': str(e)}

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

        self.logger.info(
            f"Cleaning up old historical data (keeping {self.bars_days_to_keep} days)..."
        )

        # Create a temporary volume service just for cleanup
        volume_service = VolumeService(
            db_session_factory=self.db_session_factory,
            polygon_client=self.polygon_client,
            logger=self.logger
        )

        # Use configurable retention period
        deleted_bars = volume_service.cleanup_old_bars(days_to_keep=self.bars_days_to_keep)

        self.logger.info(f"Cleanup complete: {deleted_bars} old bars deleted")
        return {'deleted_bars': deleted_bars, 'days_kept': self.bars_days_to_keep}

    def _backup_database(self) -> Dict[str, Any]:
        """
        Create a backup of the database file.

        Maintains a rotating set of backups based on backup_count setting.
        """
        if not self.db_path:
            self.logger.warning("Database backup skipped - no database path configured")
            return {'skipped': 'no database path'}

        db_file = Path(self.db_path)
        if not db_file.exists():
            self.logger.warning(f"Database backup skipped - file not found: {db_file}")
            return {'skipped': 'database file not found'}

        # Determine backup directory
        if self.backup_dir:
            backup_dir = Path(self.backup_dir)
        else:
            backup_dir = db_file.parent / 'backups'

        # Create backup directory if it doesn't exist
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{db_file.stem}_{timestamp}{db_file.suffix}"
        backup_path = backup_dir / backup_name

        self.logger.info(f"Creating database backup: {backup_path}")

        try:
            # Copy database file
            shutil.copy2(db_file, backup_path)
            backup_size = backup_path.stat().st_size

            self.logger.info(
                f"Backup created: {backup_name} ({backup_size / 1024 / 1024:.1f} MB)"
            )

            # Rotate old backups
            deleted_backups = self._rotate_backups(backup_dir, db_file.stem, db_file.suffix)

            return {
                'backup_path': str(backup_path),
                'backup_size_mb': round(backup_size / 1024 / 1024, 2),
                'deleted_old_backups': deleted_backups
            }

        except Exception as e:
            self.logger.error(f"Database backup failed: {e}")
            return {'error': str(e)}

    def _rotate_backups(
        self,
        backup_dir: Path,
        db_stem: str,
        db_suffix: str
    ) -> int:
        """
        Remove old backups beyond the configured backup_count.

        Args:
            backup_dir: Directory containing backups
            db_stem: Database filename stem (without extension)
            db_suffix: Database file extension

        Returns:
            Number of old backups deleted
        """
        # Find all backup files matching the pattern
        pattern = f"{db_stem}_*{db_suffix}"
        backup_files = sorted(
            backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True  # Newest first
        )

        deleted = 0

        # Keep only the configured number of backups
        if len(backup_files) > self.backup_count:
            for old_backup in backup_files[self.backup_count:]:
                try:
                    old_backup.unlink()
                    deleted += 1
                    self.logger.debug(f"Deleted old backup: {old_backup.name}")
                except Exception as e:
                    self.logger.warning(f"Could not delete old backup {old_backup}: {e}")

        if deleted > 0:
            self.logger.info(f"Rotated {deleted} old backup(s), keeping {self.backup_count}")

        return deleted
