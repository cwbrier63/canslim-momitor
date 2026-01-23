"""
CANSLIM Monitor - IPC Client Status Methods
Additions to pipe_client.py for GET_STATUS functionality.

This shows how to add status querying to your existing IPCClient class.
"""

import uuid
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ServiceStatusData:
    """Parsed service status from IPC response"""
    service_running: bool
    uptime_seconds: float
    threads: Dict[str, Dict[str, Any]]
    ibkr_connected: bool
    database_ok: bool
    timestamp: str
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ServiceStatusData':
        return cls(
            service_running=data.get('service_running', False),
            uptime_seconds=data.get('uptime_seconds', 0),
            threads=data.get('threads', {}),
            ibkr_connected=data.get('ibkr_connected', False),
            database_ok=data.get('database_ok', False),
            timestamp=data.get('timestamp', '')
        )
    
    def get_thread_status(self, thread_name: str) -> Optional[Dict[str, Any]]:
        """Get status for a specific thread"""
        return self.threads.get(thread_name)
    
    @property
    def total_messages(self) -> int:
        """Total messages across all threads"""
        return sum(
            t.get('message_count', 0) 
            for t in self.threads.values()
        )
    
    @property
    def total_errors(self) -> int:
        """Total errors across all threads"""
        return sum(
            t.get('error_count', 0) 
            for t in self.threads.values()
        )


# ============================================================================
# Add these methods to your existing IPCClient class
# ============================================================================

class IPCClientStatusMixin:
    """
    Mixin methods for IPCClient to request service status.
    
    Copy these methods into your existing IPCClient class.
    """
    
    def get_status(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """
        Request service status via IPC.
        
        Returns:
            Status dict on success, None on failure
            
        Response format:
        {
            "service_running": True,
            "uptime_seconds": 3600.5,
            "threads": {
                "breakout": {"state": "running", "message_count": 12, ...},
                "position": {"state": "running", "message_count": 5, ...},
                "market": {"state": "running", "message_count": 2, ...}
            },
            "ibkr_connected": True,
            "database_ok": True,
            "timestamp": "2026-01-14T10:30:30"
        }
        """
        request = {
            "type": "GET_STATUS",
            "request_id": str(uuid.uuid4())
        }
        
        try:
            response = self.send_request(request, timeout=timeout)
            if response and response.get('status') == 'success':
                return response.get('data')
            return None
        except Exception as e:
            self.logger.debug(f"GET_STATUS request failed: {e}")
            return None
    
    def get_status_parsed(self, timeout: float = 5.0) -> Optional[ServiceStatusData]:
        """
        Request service status and return parsed dataclass.
        
        Returns:
            ServiceStatusData on success, None on failure
        """
        data = self.get_status(timeout)
        if data:
            return ServiceStatusData.from_dict(data)
        return None
    
    def get_thread_status(
        self, 
        thread_name: str, 
        timeout: float = 5.0
    ) -> Optional[Dict[str, Any]]:
        """
        Request status for a specific thread.
        
        Args:
            thread_name: 'breakout', 'position', or 'market'
            timeout: Request timeout
            
        Returns:
            Thread status dict on success, None on failure
        """
        request = {
            "type": "GET_THREAD_STATUS",
            "thread": thread_name,
            "request_id": str(uuid.uuid4())
        }
        
        try:
            response = self.send_request(request, timeout=timeout)
            if response and response.get('status') == 'success':
                return response.get('data')
            return None
        except Exception as e:
            self.logger.debug(f"GET_THREAD_STATUS request failed: {e}")
            return None
    
    def reset_counters(self, timeout: float = 5.0) -> bool:
        """
        Reset message/error counters on all threads.
        
        Returns:
            True on success, False on failure
        """
        request = {
            "type": "RESET_COUNTERS",
            "request_id": str(uuid.uuid4())
        }
        
        try:
            response = self.send_request(request, timeout=timeout)
            return response and response.get('status') == 'success'
        except Exception as e:
            self.logger.debug(f"RESET_COUNTERS request failed: {e}")
            return False


# ============================================================================
# Integration example showing full IPCClient with status methods
# ============================================================================

"""
Example usage in GUI:

from gui.service_control import create_service_controller
from gui.service_status_bar import ServiceStatusBar
from service.ipc.pipe_client import create_ipc_client

class KanbanWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Create service controller (uses Windows SCM)
        self.service_controller = create_service_controller()
        
        # Create IPC client (uses named pipes)
        self.ipc_client = create_ipc_client()
        
        # Create status bar
        self.status_bar = ServiceStatusBar(
            service_controller=self.service_controller,
            ipc_client=self.ipc_client
        )
        
        # Add to layout
        self.setStatusBar(self.status_bar)
        
        # Or for toolbar placement:
        # self.toolbar.addWidget(self.status_bar)
        
    def on_service_started(self):
        # Connect IPC client when service starts
        if self.ipc_client.connect():
            # Start receiving notifications
            self.ipc_client.start_notification_listener()
"""
