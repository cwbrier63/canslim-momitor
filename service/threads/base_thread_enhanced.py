"""
CANSLIM Monitor - Base Monitor Thread
Enhanced with message counters and status tracking for IPC status reporting.

This is meant to UPDATE the existing base_thread.py with additional counters.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class ThreadState(Enum):
    """Thread lifecycle states"""
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class ThreadStatus:
    """Complete thread status for IPC reporting"""
    name: str
    state: ThreadState
    message_count: int = 0
    error_count: int = 0
    last_check: Optional[datetime] = None
    last_error: Optional[str] = None
    cycle_count: int = 0
    avg_cycle_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        return {
            "name": self.name,
            "state": self.state.value,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_error": self.last_error,
            "cycle_count": self.cycle_count,
            "avg_cycle_ms": round(self.avg_cycle_ms, 2)
        }


class BaseMonitorThread(threading.Thread, ABC):
    """
    Enhanced base class for monitor threads with status tracking.
    
    Tracks:
    - Message counts (alerts sent)
    - Error counts
    - Cycle timing
    - Last check timestamp
    
    Subclasses implement:
    - _do_check(): The actual monitoring logic
    """
    
    def __init__(
        self,
        shutdown_event: threading.Event,
        poll_interval: int = 60,
        name: str = None,
        logger: Optional[logging.Logger] = None
    ):
        super().__init__(name=name or self.__class__.__name__)
        
        self.shutdown_event = shutdown_event
        self.poll_interval = poll_interval
        self.logger = logger or logging.getLogger(self.name)
        
        # Status tracking
        self._state = ThreadState.CREATED
        self._state_lock = threading.Lock()
        
        # Counters (reset on service restart)
        self._message_count = 0
        self._error_count = 0
        self._cycle_count = 0
        self._total_cycle_time_ms = 0.0
        
        # Timestamps
        self._last_check: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._started_at: Optional[datetime] = None
    
    @property
    def state(self) -> ThreadState:
        """Current thread state"""
        with self._state_lock:
            return self._state
    
    @state.setter
    def state(self, value: ThreadState):
        with self._state_lock:
            old_state = self._state
            self._state = value
            if old_state != value:
                self.logger.debug(f"State changed: {old_state.value} → {value.value}")
    
    def get_status(self) -> ThreadStatus:
        """
        Get current thread status for IPC reporting.
        
        Called by ServiceController for GET_STATUS responses.
        """
        avg_cycle = 0.0
        if self._cycle_count > 0:
            avg_cycle = self._total_cycle_time_ms / self._cycle_count
        
        return ThreadStatus(
            name=self.name,
            state=self.state,
            message_count=self._message_count,
            error_count=self._error_count,
            last_check=self._last_check,
            last_error=self._last_error,
            cycle_count=self._cycle_count,
            avg_cycle_ms=avg_cycle
        )
    
    def increment_message_count(self, count: int = 1):
        """
        Increment message counter.
        
        Call this whenever an alert/notification is sent.
        """
        self._message_count += count
        self.logger.debug(f"Message count: {self._message_count}")
    
    def run(self):
        """Main thread loop with timing and error tracking"""
        self.state = ThreadState.STARTING
        self._started_at = datetime.now()
        self.logger.info(
            f"{self.name} started (poll interval: {self.poll_interval}s)"
        )
        
        self.state = ThreadState.RUNNING
        
        while not self.shutdown_event.is_set():
            cycle_start = time.perf_counter()
            
            try:
                self._do_check()
                self._last_check = datetime.now()
                
            except Exception as e:
                self._error_count += 1
                self._last_error = str(e)
                self.logger.error(f"Error in check cycle: {e}", exc_info=True)
            
            finally:
                # Track cycle timing
                cycle_time_ms = (time.perf_counter() - cycle_start) * 1000
                self._cycle_count += 1
                self._total_cycle_time_ms += cycle_time_ms
                
                self.logger.debug(
                    f"Cycle {self._cycle_count} complete in {cycle_time_ms:.1f}ms"
                )
            
            # Wait for next cycle or shutdown
            self.shutdown_event.wait(self.poll_interval)
        
        self.state = ThreadState.STOPPING
        self._cleanup()
        self.state = ThreadState.STOPPED
        self.logger.info(f"{self.name} stopped after {self._cycle_count} cycles")
    
    @abstractmethod
    def _do_check(self):
        """
        Perform the actual monitoring check.
        
        Subclasses implement this with their specific logic.
        Call self.increment_message_count() when sending alerts.
        """
        pass
    
    def _cleanup(self):
        """
        Optional cleanup on shutdown.
        
        Override in subclasses if cleanup is needed.
        """
        pass
    
    def force_check(self) -> bool:
        """
        Force an immediate check outside normal cycle.
        
        Returns True if check was performed.
        """
        if self.state != ThreadState.RUNNING:
            return False
        
        try:
            self.logger.info("Forced check requested")
            self._do_check()
            self._last_check = datetime.now()
            return True
        except Exception as e:
            self._error_count += 1
            self._last_error = str(e)
            self.logger.error(f"Error in forced check: {e}")
            return False


# Example usage showing how to integrate with existing threads:
"""
class BreakoutThread(BaseMonitorThread):
    def __init__(self, shutdown_event, db, ibkr_client, discord_notifier, **kwargs):
        super().__init__(shutdown_event, name="breakout", **kwargs)
        self.db = db
        self.ibkr_client = ibkr_client
        self.discord_notifier = discord_notifier
    
    def _do_check(self):
        positions = self._get_watching_positions()
        self.logger.info(f"Checking {len(positions)} positions")
        
        for pos in positions:
            if self._is_breakout(pos):
                self._send_alert(pos)
                self.increment_message_count()  # <-- Track alert sent
"""
