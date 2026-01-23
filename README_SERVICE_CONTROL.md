# CANSLIM Monitor - Service Control Components

## Files to Replace

```
canslim_monitor/
├── gui/
│   ├── __init__.py              # REPLACE
│   ├── service_control.py       # NEW - Windows SCM management
│   ├── service_status_bar.py    # NEW - PyQt6 status bar widget
│   └── kanban_window.py         # REPLACE - now includes ServiceStatusBar
│
└── service/
    ├── __init__.py              # REPLACE
    ├── service_controller.py    # REPLACE - includes GET_STATUS handler
    │
    ├── threads/
    │   ├── __init__.py          # REPLACE
    │   ├── base_thread.py       # REPLACE - includes message counters
    │   ├── breakout_thread.py   # TEMPLATE - merge with your existing
    │   ├── position_thread.py   # TEMPLATE - merge with your existing
    │   └── market_thread.py     # TEMPLATE - merge with your existing
    │
    └── ipc/
        ├── __init__.py          # REPLACE
        └── pipe_client.py       # REPLACE - includes get_status()
```

## What's New in kanban_window.py

The `KanbanMainWindow` now includes:

```python
# In __init__:
self.service_controller = create_service_controller(logger=self.logger)
self.ipc_client = create_ipc_client(
    notification_callback=self._handle_service_notification,
    logger=self.logger
)

# In _setup_ui():
self.service_status_bar = ServiceStatusBar(
    service_controller=self.service_controller,
    ipc_client=self.ipc_client,
    logger=self.logger
)
main_layout.addWidget(self.service_status_bar)

# Connect service state changes
self.service_status_bar.service_state_changed.connect(
    self._on_service_state_changed
)
```

## Status Bar Layout

```
[Service: ● Running] | [Breakout: 12] [Position: 5] [Market: 2] | [▶ Start] [■ Stop] [⋮]
```

- **Service indicator**: ● Running, ○ Stopped, ○ Not Installed
- **Thread indicators**: Show message counts, errors in parentheses
- **Control buttons**: Start, Stop, plus menu for Install/Remove/Restart
- **Auto-refresh**: Every 5 seconds

## Quick Install

```powershell
# Extract to your canslim_monitor directory
Expand-Archive -Path canslim_service_control_v2.zip -DestinationPath C:\Trading -Force

# The files will merge with your existing structure
# Backup your existing files first if needed!
```

## Key Integration Points

### 1. Thread Message Counting

In your thread implementations, add:

```python
# When sending Discord alerts:
if self.discord_notifier:
    self.discord_notifier.send_alert(...)
    self.increment_message_count()  # Track the message
```

### 2. Service State Changes

The status bar emits `service_state_changed(state: str)` signal when service starts/stops:

```python
def _on_service_state_changed(self, state: str):
    if state == "running":
        # Connect IPC, start price updates
        self._check_service_connection()
    else:
        # Stop price updates
        self.price_timer.stop()
```

### 3. Service Notifications

Handle push notifications from service:

```python
def _handle_service_notification(self, notification: dict):
    notif_type = notification.get('type')
    if notif_type == 'ALERT':
        # Show in status bar or popup
        ...
```

## IPC Protocol - GET_STATUS

Request:
```json
{"type": "GET_STATUS", "request_id": "uuid"}
```

Response:
```json
{
    "status": "success",
    "data": {
        "service_running": true,
        "uptime_seconds": 3600.5,
        "threads": {
            "breakout": {
                "state": "running",
                "message_count": 12,
                "error_count": 0
            },
            ...
        },
        "ibkr_connected": true,
        "database_ok": true
    }
}
```
