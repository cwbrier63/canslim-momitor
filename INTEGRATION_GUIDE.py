"""
CANSLIM Monitor - Service Control Integration Guide
====================================================

This document explains how to integrate the new service control components
into your existing codebase.

Components Created:
1. gui/service_control.py - Windows Service management (SCM access)
2. gui/service_status_bar.py - PyQt6 status bar widget
3. service/threads/base_thread_enhanced.py - Thread base class with counters
4. service/ipc/status_endpoint.py - GET_STATUS IPC handler
5. service/ipc/client_status_methods.py - IPCClient status methods

Integration Steps:
"""

# ============================================================================
# STEP 1: Update base_thread.py
# ============================================================================
"""
Replace or merge your existing base_thread.py with base_thread_enhanced.py.

Key additions:
- ThreadState enum for lifecycle states
- ThreadStatus dataclass for IPC reporting  
- get_status() method returning ThreadStatus
- increment_message_count() for tracking alerts sent
- Automatic cycle timing and error tracking

Your existing threads (breakout, position, market) should:
1. Inherit from BaseMonitorThread
2. Call self.increment_message_count() when sending alerts
"""

# Example update to breakout_thread.py:
BREAKOUT_THREAD_EXAMPLE = '''
class BreakoutThread(BaseMonitorThread):
    def __init__(self, shutdown_event, db, ibkr_client, discord_notifier, **kwargs):
        super().__init__(
            shutdown_event=shutdown_event,
            name="breakout",
            poll_interval=kwargs.get('poll_interval', 60),
            logger=kwargs.get('logger')
        )
        self.db = db
        self.ibkr_client = ibkr_client
        self.discord_notifier = discord_notifier
    
    def _do_check(self):
        """Main monitoring logic - called each cycle"""
        positions = self._get_watching_positions()
        self.logger.info(f"Checking {len(positions)} positions")
        
        for pos in positions:
            if self._is_breakout(pos):
                self._send_alert(pos)
                self.increment_message_count()  # <-- ADD THIS
'''


# ============================================================================
# STEP 2: Update service_controller.py
# ============================================================================
"""
Add the GET_STATUS handler from status_endpoint.py to your ServiceController.

Copy these methods:
- _handle_get_status()
- _handle_get_thread_status()
- _handle_reset_counters()

And update _process_command() to route to them.
"""

SERVICE_CONTROLLER_UPDATE = '''
# In ServiceController.__init__():
self._started_at = None

# In ServiceController.start():
self._started_at = datetime.now()

# In ServiceController._process_command():
def _process_command(self, command: dict) -> Dict[str, Any]:
    cmd_type = command.get('type')
    request_id = command.get('request_id')
    
    if cmd_type == 'GET_STATUS':
        return self._handle_get_status(request_id)
    elif cmd_type == 'GET_THREAD_STATUS':
        return self._handle_get_thread_status(command.get('thread'), request_id)
    elif cmd_type == 'RESET_COUNTERS':
        return self._handle_reset_counters(request_id)
    # ... existing handlers ...
'''


# ============================================================================
# STEP 3: Update pipe_client.py
# ============================================================================
"""
Add status methods from client_status_methods.py to your IPCClient class.

Methods to add:
- get_status() - Returns full service status
- get_status_parsed() - Returns ServiceStatusData object
- get_thread_status() - Returns single thread status
- reset_counters() - Resets all counters
"""

PIPE_CLIENT_UPDATE = '''
class IPCClient:
    # ... existing code ...
    
    def get_status(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Request service status via IPC"""
        request = {
            "type": "GET_STATUS",
            "request_id": str(uuid.uuid4())
        }
        
        response = self.send_request(request, timeout=timeout)
        if response and response.get('status') == 'success':
            return response.get('data')
        return None
'''


# ============================================================================
# STEP 4: Update GUI (kanban_window.py)
# ============================================================================
"""
Add the ServiceStatusBar to your main window.
"""

GUI_INTEGRATION = '''
from gui.service_control import create_service_controller
from gui.service_status_bar import ServiceStatusBar
from service.ipc import create_ipc_client

class KanbanWindow(QMainWindow):
    def __init__(self, config: dict, db: DatabaseManager, logger=None):
        super().__init__()
        self.logger = logger or logging.getLogger(__name__)
        
        # Create service controller (queries Windows SCM)
        self.service_controller = create_service_controller(
            logger=self.logger
        )
        
        # Create IPC client (communicates with service via named pipes)
        self.ipc_client = create_ipc_client(
            notification_callback=self._handle_service_notification,
            logger=self.logger
        )
        
        # ... existing setup ...
        
        self._setup_status_bar()
    
    def _setup_status_bar(self):
        """Add service status bar"""
        self.service_status_bar = ServiceStatusBar(
            service_controller=self.service_controller,
            ipc_client=self.ipc_client,
            logger=self.logger
        )
        
        # Option 1: Add to toolbar
        self.toolbar.addWidget(self.service_status_bar)
        
        # Option 2: Use as status bar
        # self.setStatusBar(QStatusBar())
        # self.statusBar().addPermanentWidget(self.service_status_bar)
        
        # Connect signals
        self.service_status_bar.service_state_changed.connect(
            self._on_service_state_changed
        )
    
    def _on_service_state_changed(self, state: str):
        """Handle service state changes"""
        if state == "running":
            # Connect IPC client when service starts
            self.ipc_client.connect()
        elif state == "stopped":
            # Disconnect when service stops
            self.ipc_client.disconnect()
    
    def _handle_service_notification(self, notification: dict):
        """Handle push notifications from service"""
        notif_type = notification.get('type')
        if notif_type == 'ALERT':
            # Handle alert notification
            data = notification.get('data', {})
            self.logger.info(f"Alert: {data.get('symbol')} - {data.get('alert_type')}")
'''


# ============================================================================
# STEP 5: Update gui/__init__.py
# ============================================================================

GUI_INIT_UPDATE = '''
"""CANSLIM Monitor - GUI Components"""

from gui.kanban_window import KanbanWindow
from gui.kanban_column import KanbanColumn
from gui.position_card import PositionCard
from gui.transition_dialogs import AddPositionDialog, TransitionDialog
from gui.service_control import (
    ServiceController,
    ServiceStatus,
    ServiceState,
    create_service_controller
)
from gui.service_status_bar import (
    ServiceStatusBar,
    CompactServiceIndicator,
    ThreadIndicator
)

__all__ = [
    'KanbanWindow',
    'KanbanColumn', 
    'PositionCard',
    'AddPositionDialog',
    'TransitionDialog',
    'ServiceController',
    'ServiceStatus',
    'ServiceState',
    'create_service_controller',
    'ServiceStatusBar',
    'CompactServiceIndicator',
    'ThreadIndicator',
]
'''


# ============================================================================
# IPC Protocol Summary
# ============================================================================

IPC_PROTOCOL = """
GET_STATUS Request:
{
    "type": "GET_STATUS",
    "request_id": "uuid"
}

GET_STATUS Response:
{
    "request_id": "uuid",
    "status": "success",
    "data": {
        "service_running": true,
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
            "position": { ... },
            "market": { ... }
        },
        "ibkr_connected": true,
        "database_ok": true,
        "timestamp": "2026-01-14T10:30:30"
    }
}

GET_THREAD_STATUS Request:
{
    "type": "GET_THREAD_STATUS",
    "thread": "breakout",
    "request_id": "uuid"
}

RESET_COUNTERS Request:
{
    "type": "RESET_COUNTERS",
    "request_id": "uuid"
}
"""


# ============================================================================
# Testing
# ============================================================================

TESTING_GUIDE = """
Test the components individually:

1. Test ServiceController (no service needed):
   
   from gui.service_control import create_service_controller
   
   controller = create_service_controller()
   status = controller.get_status()
   print(f"Service: {status.status_text}")
   print(f"Indicator: {status.status_indicator}")

2. Test StatusBar widget (GUI only):
   
   from PyQt6.QtWidgets import QApplication
   from gui.service_status_bar import ServiceStatusBar
   
   app = QApplication([])
   bar = ServiceStatusBar()
   bar.show()
   app.exec()

3. Test with mock service (development):
   
   from gui.service_control import create_service_controller
   
   mock = create_service_controller(use_mock=True)
   mock.start()
   print(mock.get_status())  # Shows running

4. Test IPC status (service must be running):
   
   from service.ipc import create_ipc_client
   
   client = create_ipc_client()
   if client.connect():
       status = client.get_status()
       print(f"Threads: {list(status['threads'].keys())}")
       for name, data in status['threads'].items():
           print(f"  {name}: {data['message_count']} messages")
"""


if __name__ == "__main__":
    print(__doc__)
    print("\n" + "="*70)
    print("See INTEGRATION_GUIDE.py for step-by-step instructions")
    print("="*70)
