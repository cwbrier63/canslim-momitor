"""
CANSLIM Monitor - Service Status IPC Endpoint
Additions to service_controller.py for the GET_STATUS command.

This file contains the status-related methods to ADD to ServiceController class.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List
import threading


@dataclass
class ServiceStatusResponse:
    """
    Complete service status for IPC GET_STATUS response.
    
    Includes:
    - Overall service state
    - Per-thread status with message counts
    - System health info
    """
    service_running: bool
    uptime_seconds: float
    threads: Dict[str, Dict[str, Any]]
    ibkr_connected: bool
    database_ok: bool
    timestamp: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_running": self.service_running,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "threads": self.threads,
            "ibkr_connected": self.ibkr_connected,
            "database_ok": self.database_ok,
            "timestamp": self.timestamp
        }


# ============================================================================
# Add these methods to ServiceController class
# ============================================================================

class ServiceControllerStatusMixin:
    """
    Mixin methods for ServiceController to handle GET_STATUS requests.
    
    Copy these methods into your existing ServiceController class.
    """
    
    def __init__(self):
        # Add to existing __init__
        self._started_at: Optional[datetime] = None
    
    def _handle_get_status(self, request_id: str = None) -> Dict[str, Any]:
        """
        Handle GET_STATUS IPC command.
        
        Returns comprehensive status including all thread states and message counts.
        """
        # Calculate uptime
        uptime = 0.0
        if self._started_at:
            uptime = (datetime.now() - self._started_at).total_seconds()
        
        # Collect thread statuses
        thread_statuses = {}
        if hasattr(self, 'thread_manager'):
            for name, thread in self.thread_manager.threads.items():
                if hasattr(thread, 'get_status'):
                    status = thread.get_status()
                    thread_statuses[name] = status.to_dict()
                else:
                    # Fallback for threads without enhanced status
                    thread_statuses[name] = {
                        "name": name,
                        "state": "running" if thread.is_alive() else "stopped",
                        "message_count": 0,
                        "error_count": 0,
                        "last_check": None,
                    }
        
        # Check IBKR connection status
        ibkr_connected = False
        if hasattr(self, 'ibkr_client') and self.ibkr_client:
            try:
                ibkr_connected = self.ibkr_client.is_connected()
            except Exception:
                pass
        
        # Check database status
        database_ok = False
        if hasattr(self, 'db') and self.db:
            try:
                # Quick query to verify database
                with self.db.session() as session:
                    session.execute("SELECT 1")
                database_ok = True
            except Exception:
                pass
        
        response = ServiceStatusResponse(
            service_running=not self.shutdown_event.is_set(),
            uptime_seconds=uptime,
            threads=thread_statuses,
            ibkr_connected=ibkr_connected,
            database_ok=database_ok,
            timestamp=datetime.now().isoformat()
        )
        
        return {
            "request_id": request_id,
            "status": "success",
            "data": response.to_dict()
        }
    
    def _process_command(self, command: dict) -> Dict[str, Any]:
        """
        Process IPC command - ADD GET_STATUS handling.
        
        Merge this into your existing _process_command method.
        """
        cmd_type = command.get('type')
        request_id = command.get('request_id')
        
        if cmd_type == 'GET_STATUS':
            return self._handle_get_status(request_id)
        
        elif cmd_type == 'GET_THREAD_STATUS':
            # Get specific thread status
            thread_name = command.get('thread')
            return self._handle_get_thread_status(thread_name, request_id)
        
        elif cmd_type == 'RESET_COUNTERS':
            # Reset message counters (optional admin command)
            return self._handle_reset_counters(request_id)
        
        # ... existing command handlers ...
        
        return {
            "request_id": request_id,
            "status": "error",
            "error": f"Unknown command: {cmd_type}"
        }
    
    def _handle_get_thread_status(
        self, 
        thread_name: str,
        request_id: str = None
    ) -> Dict[str, Any]:
        """Get status for a specific thread"""
        if not hasattr(self, 'thread_manager'):
            return {
                "request_id": request_id,
                "status": "error",
                "error": "Thread manager not initialized"
            }
        
        thread = self.thread_manager.threads.get(thread_name)
        if not thread:
            return {
                "request_id": request_id,
                "status": "error",
                "error": f"Unknown thread: {thread_name}"
            }
        
        if hasattr(thread, 'get_status'):
            status = thread.get_status().to_dict()
        else:
            status = {
                "name": thread_name,
                "state": "running" if thread.is_alive() else "stopped"
            }
        
        return {
            "request_id": request_id,
            "status": "success",
            "data": status
        }
    
    def _handle_reset_counters(self, request_id: str = None) -> Dict[str, Any]:
        """Reset all thread message counters"""
        if not hasattr(self, 'thread_manager'):
            return {
                "request_id": request_id,
                "status": "error",
                "error": "Thread manager not initialized"
            }
        
        reset_count = 0
        for thread in self.thread_manager.threads.values():
            if hasattr(thread, '_message_count'):
                thread._message_count = 0
                thread._error_count = 0
                reset_count += 1
        
        return {
            "request_id": request_id,
            "status": "success",
            "data": {"threads_reset": reset_count}
        }


# ============================================================================
# IPC Message Types for GET_STATUS
# ============================================================================

# Request format:
GET_STATUS_REQUEST = {
    "type": "GET_STATUS",
    "request_id": "uuid-here"
}

# Response format:
GET_STATUS_RESPONSE = {
    "request_id": "uuid-here",
    "status": "success",
    "data": {
        "service_running": True,
        "uptime_seconds": 3600.5,
        "threads": {
            "breakout": {
                "name": "breakout",
                "state": "running",
                "message_count": 12,
                "error_count": 0,
                "last_check": "2026-01-14T10:30:00",
                "cycle_count": 60,
                "avg_cycle_ms": 150.5
            },
            "position": {
                "name": "position",
                "state": "running",
                "message_count": 5,
                "error_count": 1,
                "last_check": "2026-01-14T10:30:15",
                "cycle_count": 120,
                "avg_cycle_ms": 80.2
            },
            "market": {
                "name": "market",
                "state": "running",
                "message_count": 2,
                "error_count": 0,
                "last_check": "2026-01-14T10:25:00",
                "cycle_count": 12,
                "avg_cycle_ms": 500.0
            }
        },
        "ibkr_connected": True,
        "database_ok": True,
        "timestamp": "2026-01-14T10:30:30"
    }
}
