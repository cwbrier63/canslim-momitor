"""
CANSLIM Monitor - Base Thread Class
Foundation for all monitoring threads with status tracking and message counters.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, Dict


@dataclass
class ThreadStats:
    """Statistics tracked for each thread."""
    name: str
    state: str = "stopped"  # stopped, running, waiting, error
    message_count: int = 0
    error_count: int = 0
    cycle_count: int = 0
    last_check: Optional[str] = None
    last_error: Optional[str] = None
    avg_cycle_ms: float = 0.0
    is_market_hours: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'state': self.state,
            'message_count': self.message_count,
            'error_count': self.error_count,
            'cycle_count': self.cycle_count,
            'last_check': self.last_check,
            'last_error': self.last_error,
            'avg_cycle_ms': self.avg_cycle_ms,
            'is_market_hours': self.is_market_hours
        }


class BaseThread(threading.Thread, ABC):
    """
    Base class for all monitoring threads.
    
    Provides:
    - Graceful shutdown handling
    - Message/error counting
    - Status reporting for IPC
    - Market hours awareness
    """
    
    def __init__(
        self,
        name: str,
        shutdown_event: threading.Event,
        poll_interval: int = 60,
        logger: Optional[logging.Logger] = None
    ):
        super().__init__(name=name, daemon=True)

        self.thread_name = name
        self.shutdown_event = shutdown_event
        self.poll_interval = poll_interval
        self.logger = logger or logging.getLogger(f'canslim.{name}')

        # Market calendar — set via _init_market_calendar() or by ServiceController
        self._market_calendar = None

        # Statistics tracking
        self._stats = ThreadStats(name=name)
        self._stats_lock = threading.Lock()
        self._cycle_times: list = []
        self._max_cycle_samples = 100
        
    def run(self):
        """Main thread loop with error handling and stats tracking."""
        self.logger.info(f"{self.thread_name} thread starting (poll: {self.poll_interval}s)")
        
        with self._stats_lock:
            self._stats.state = "running"
        
        while not self.shutdown_event.is_set():
            cycle_start = time.time()
            
            try:
                # Check market hours
                is_market = self._is_market_hours()
                with self._stats_lock:
                    self._stats.is_market_hours = is_market
                
                # Only run during appropriate hours (can be overridden)
                if self._should_run():
                    with self._stats_lock:
                        self._stats.state = "running"
                    
                    self._do_work()
                    
                    with self._stats_lock:
                        self._stats.cycle_count += 1
                        self._stats.last_check = datetime.now().isoformat()
                else:
                    with self._stats_lock:
                        self._stats.state = "waiting"
                        
            except Exception as e:
                self.logger.error(f"Error in {self.thread_name}: {e}", exc_info=True)
                with self._stats_lock:
                    self._stats.error_count += 1
                    self._stats.last_error = str(e)
                    self._stats.state = "error"
            
            # Track cycle time
            cycle_ms = (time.time() - cycle_start) * 1000
            self._update_cycle_time(cycle_ms)
            
            # Wait for next cycle
            self.shutdown_event.wait(self.poll_interval)
        
        with self._stats_lock:
            self._stats.state = "stopped"
        
        self.logger.info(f"{self.thread_name} thread stopped")
    
    @abstractmethod
    def _do_work(self):
        """Override this to implement the thread's main work."""
        pass
    
    def _should_run(self) -> bool:
        """
        Determine if thread should execute.
        Override to add market hours restrictions etc.
        """
        return True
    
    def _init_market_calendar(self, config: dict = None):
        """Initialize MarketCalendar from config if not already set."""
        if self._market_calendar is not None:
            return
        try:
            from ...utils.market_calendar import get_market_calendar
            api_key = (config or {}).get('polygon', {}).get('api_key', '')
            self._market_calendar = get_market_calendar(api_key=api_key)
        except Exception as e:
            self.logger.debug(f"MarketCalendar init failed, using fallback: {e}")

    def _is_market_hours(self) -> bool:
        """Check if currently in US market hours using MarketCalendar.

        Uses Polygon API for real-time status (handles holidays, early closes).
        Falls back to hardcoded 9:30-4:00 ET weekday check if unavailable.
        """
        if self._market_calendar:
            try:
                return self._market_calendar.is_market_open()
            except Exception as e:
                self.logger.debug(f"MarketCalendar.is_market_open() failed: {e}")

        # Fallback: basic weekday + time check (no holiday awareness)
        from datetime import datetime
        try:
            import pytz
            et = pytz.timezone('US/Eastern')
            now = datetime.now(et)
        except ImportError:
            now = datetime.now()

        if now.weekday() >= 5:
            return False

        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close

    def _is_trading_day(self) -> bool:
        """Check if today is a trading day (not weekend, not holiday).

        Uses MarketCalendar for holiday awareness.
        Falls back to weekday-only check if unavailable.
        """
        if self._market_calendar:
            try:
                return self._market_calendar.is_trading_day()
            except Exception as e:
                self.logger.debug(f"MarketCalendar.is_trading_day() failed: {e}")

        # Fallback: weekday-only check
        from datetime import datetime
        try:
            import pytz
            now = datetime.now(pytz.timezone('US/Eastern'))
        except ImportError:
            now = datetime.now()
        return now.weekday() < 5
    
    def _update_cycle_time(self, cycle_ms: float):
        """Update rolling average cycle time."""
        self._cycle_times.append(cycle_ms)
        if len(self._cycle_times) > self._max_cycle_samples:
            self._cycle_times.pop(0)
        
        with self._stats_lock:
            self._stats.avg_cycle_ms = sum(self._cycle_times) / len(self._cycle_times)
    
    def increment_message_count(self, count: int = 1):
        """Increment the message counter (call when sending alerts)."""
        with self._stats_lock:
            self._stats.message_count += count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current thread statistics."""
        with self._stats_lock:
            return self._stats.to_dict()
    
    def reset_counters(self):
        """Reset message and error counters."""
        with self._stats_lock:
            self._stats.message_count = 0
            self._stats.error_count = 0
            self._stats.cycle_count = 0
