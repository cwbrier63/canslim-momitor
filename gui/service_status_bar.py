"""
CANSLIM Monitor - Service Status Bar Widget
PyQt6 widget for displaying service status, thread health, and control buttons.

Features:
- Service state indicator (●/○ Running/Stopped/Not Installed)
- Per-thread status with message counts
- Install/Start/Stop/Remove control buttons
- Auto-refresh via QTimer
- IPC auto-connect for foreground mode detection

FIX APPLIED: Auto-creates IPC client and checks for running service
even if Windows service is not installed (foreground mode detection).

FIX APPLIED (Jan 17): Stop button now uses IPC shutdown first (no admin needed),
falls back to Windows service API if IPC fails.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFrame, QToolButton, QMenu, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QFont

from .service_control import (
    ServiceController, ServiceState, ServiceStatus,
    create_service_controller
)


@dataclass
class ThreadIndicatorData:
    """Data for a single thread indicator."""
    name: str
    display_name: str
    state: str = "unknown"
    message_count: int = 0
    error_count: int = 0
    last_check: Optional[str] = None


class ThreadIndicator(QWidget):
    """
    Small widget showing thread status and message count.
    
    Display format: "breakout ✓(12)" or "position ○(0)"
    """
    
    def __init__(self, name: str, display_name: str, parent=None):
        super().__init__(parent)
        
        self.name = name
        self.display_name = display_name
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        
        # Thread name
        self.name_label = QLabel(display_name)
        self.name_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.name_label)
        
        # Status indicator
        self.status_label = QLabel("○")
        self.status_label.setStyleSheet("color: #888; font-weight: bold;")
        layout.addWidget(self.status_label)
        
        # Message count
        self.count_label = QLabel("(0)")
        self.count_label.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(self.count_label)
        
        self.setToolTip(f"{display_name} thread status")
    
    def update_status(self, state: str, message_count: int, error_count: int = 0):
        """Update the thread status display."""
        # Status indicator
        if state == "running":
            self.status_label.setText("✓")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif state == "waiting":
            self.status_label.setText("◐")
            self.status_label.setStyleSheet("color: #FFC107; font-weight: bold;")
        elif state == "error":
            self.status_label.setText("✗")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
        else:
            self.status_label.setText("○")
            self.status_label.setStyleSheet("color: #888; font-weight: bold;")
        
        # Message count
        self.count_label.setText(f"({message_count})")
        
        # Error indication
        if error_count > 0:
            self.count_label.setStyleSheet("font-size: 10px; color: #f44336;")
            self.count_label.setToolTip(f"{error_count} errors")
        else:
            self.count_label.setStyleSheet("font-size: 10px; color: #666;")
            self.count_label.setToolTip("")
    
    def clear(self):
        """Clear/reset the indicator."""
        self.status_label.setText("○")
        self.status_label.setStyleSheet("color: #888; font-weight: bold;")
        self.count_label.setText("(0)")
        self.count_label.setStyleSheet("font-size: 10px; color: #666;")


class ServiceStatusBar(QWidget):
    """
    Status bar widget showing service status and controls.
    
    Displays:
    - Service state (Running/Stopped/Not Installed/Running Foreground)
    - Per-thread status indicators
    - Control buttons (Start/Stop/Install/Remove)
    
    Automatically refreshes status via QTimer.
    """
    
    # Signal emitted when status changes (detailed dict)
    status_updated = pyqtSignal(dict)
    
    # Signal emitted when service state changes (for kanban_window compatibility)
    # Emits: state string like "running", "stopped", "not_installed", "foreground"
    service_state_changed = pyqtSignal(str)
    
    REFRESH_INTERVAL_MS = 5000  # 5 seconds
    
    def __init__(
        self,
        service_controller=None,
        ipc_client=None,
        logger: logging.Logger = None,
        parent=None
    ):
        super().__init__(parent)
        
        self.service_controller = service_controller or create_service_controller()
        self.logger = logger or logging.getLogger(__name__)
        
        # === IPC FIX: Auto-create IPC client if not provided ===
        if ipc_client is None:
            try:
                from canslim_monitor.service.ipc import PipeClient
                self.ipc_client = PipeClient()
                self.logger.debug("IPC client auto-created")
            except ImportError as e:
                self.logger.warning(f"Could not import PipeClient: {e}")
                self.ipc_client = None
        else:
            self.ipc_client = ipc_client
        
        self._last_service_state = None
        self._last_ipc_status = None
        
        self._setup_ui()
        self._setup_refresh_timer()
        
        # Initial refresh
        self._refresh_status()
    
    def _setup_ui(self):
        """Build the status bar UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)
        
        # Service status section
        service_frame = QFrame()
        service_layout = QHBoxLayout(service_frame)
        service_layout.setContentsMargins(0, 0, 0, 0)
        service_layout.setSpacing(6)
        
        # Service indicator (●/○)
        self.service_indicator = QLabel("○")
        self.service_indicator.setStyleSheet("color: #888; font-weight: bold; font-size: 14px;")
        service_layout.addWidget(self.service_indicator)
        
        # Service status text
        self.service_status_label = QLabel("Not Installed")
        self.service_status_label.setStyleSheet("font-size: 11px;")
        service_layout.addWidget(self.service_status_label)
        
        layout.addWidget(service_frame)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: #ddd;")
        layout.addWidget(separator)
        
        # Thread indicators
        self.thread_indicators: Dict[str, ThreadIndicator] = {}
        
        for name, display in [('breakout', 'Breakout'), ('position', 'Position'), ('market', 'Market')]:
            indicator = ThreadIndicator(name, display)
            self.thread_indicators[name] = indicator
            layout.addWidget(indicator)
        
        # Spacer
        layout.addStretch()
        
        # Timestamp
        self.timestamp_label = QLabel("")
        self.timestamp_label.setStyleSheet("font-size: 10px; color: #999;")
        layout.addWidget(self.timestamp_label)
        
        # Control buttons
        self.install_btn = QPushButton("Install")
        self.install_btn.setFixedWidth(60)
        self.install_btn.clicked.connect(self._on_install)
        layout.addWidget(self.install_btn)
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedWidth(50)
        self.start_btn.clicked.connect(self._on_start)
        layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(50)
        self.stop_btn.clicked.connect(self._on_stop)
        layout.addWidget(self.stop_btn)
        
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setFixedWidth(60)
        self.remove_btn.clicked.connect(self._on_remove)
        layout.addWidget(self.remove_btn)
    
    def _setup_refresh_timer(self):
        """Set up auto-refresh timer."""
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_status)
        self._refresh_timer.start(self.REFRESH_INTERVAL_MS)
    
    def _refresh_status(self):
        """
        Refresh all status information.
        
        FIX: Now tries IPC connection regardless of Windows service state
        to detect foreground mode.
        """
        # Get Windows service status
        service_status = self.service_controller.get_status()
        
        # === IPC FIX: Try IPC connection regardless of Windows service state ===
        ipc_connected = False
        ipc_status = None
        
        if self.ipc_client:
            try:
                if self.ipc_client.connect(timeout=1.0):
                    ipc_status = self.ipc_client.get_status(timeout=2.0)
                    self.ipc_client.disconnect()
                    
                    if ipc_status:
                        ipc_connected = True
                        self._update_thread_displays(ipc_status.get('threads', {}))
                        self._last_ipc_status = ipc_status
            except Exception as e:
                self.logger.debug(f"IPC status request failed: {e}")
        
        # === IPC FIX: Show "Running (Foreground)" when IPC connected but service not installed ===
        if ipc_connected and service_status.state == ServiceState.NOT_INSTALLED:
            # Service is running in foreground mode (not as Windows service)
            self.service_indicator.setText("●")
            self.service_indicator.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Running (Foreground)")
            
            # Disable Windows service controls when in foreground mode
            self.install_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)  # Can't stop foreground from GUI
            self.remove_btn.setEnabled(False)
        elif ipc_connected and service_status.state == ServiceState.RUNNING:
            # Windows service is running and responding
            self.service_indicator.setText("●")
            self.service_indicator.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Running (Service)")
            
            self.install_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.remove_btn.setEnabled(False)
        else:
            # Standard Windows service state display
            self._update_service_display(service_status)
            
            if not ipc_connected:
                self._clear_thread_displays()
        
        # Update timestamp
        self.timestamp_label.setText(datetime.now().strftime("%H:%M:%S"))
        
        # Determine current state string for signal
        if ipc_connected and service_status.state == ServiceState.NOT_INSTALLED:
            current_state = "foreground"
        elif ipc_connected and service_status.state == ServiceState.RUNNING:
            current_state = "running"
        elif service_status.state == ServiceState.RUNNING:
            current_state = "running"
        elif service_status.state == ServiceState.STOPPED:
            current_state = "stopped"
        elif service_status.state == ServiceState.NOT_INSTALLED:
            current_state = "not_installed"
        else:
            current_state = service_status.state.value
        
        # Emit state change signal if state changed
        if current_state != self._last_service_state:
            self._last_service_state = current_state
            self.service_state_changed.emit(current_state)
        
        # Emit detailed status signal
        self.status_updated.emit({
            "service": current_state,
            "threads": self._last_ipc_status
        })
    
    def _update_service_display(self, status: ServiceStatus):
        """Update service status display based on Windows service state."""
        state = status.state
        
        if state == ServiceState.RUNNING:
            self.service_indicator.setText("●")
            self.service_indicator.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Running")
            
            self.install_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.remove_btn.setEnabled(False)
            
        elif state == ServiceState.STOPPED:
            self.service_indicator.setText("○")
            self.service_indicator.setStyleSheet("color: #f44336; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Stopped")
            
            self.install_btn.setEnabled(False)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(True)
            
        elif state == ServiceState.STARTING:
            self.service_indicator.setText("◐")
            self.service_indicator.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Starting...")
            
            self.install_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            
        elif state == ServiceState.STOPPING:
            self.service_indicator.setText("◐")
            self.service_indicator.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Stopping...")
            
            self.install_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            
        elif state == ServiceState.NOT_INSTALLED:
            self.service_indicator.setText("⊘")
            self.service_indicator.setStyleSheet("color: #888; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Not Installed")
            
            self.install_btn.setEnabled(True)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            
        else:  # UNKNOWN
            self.service_indicator.setText("?")
            self.service_indicator.setStyleSheet("color: #888; font-weight: bold; font-size: 14px;")
            self.service_status_label.setText("Unknown")
            
            self.install_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
    
    def _update_thread_displays(self, threads: Dict[str, Dict[str, Any]]):
        """Update all thread indicators from IPC status."""
        for name, indicator in self.thread_indicators.items():
            thread_info = threads.get(name, {})
            indicator.update_status(
                state=thread_info.get('state', 'unknown'),
                message_count=thread_info.get('message_count', 0),
                error_count=thread_info.get('error_count', 0)
            )
    
    def _clear_thread_displays(self):
        """Clear all thread indicators."""
        for indicator in self.thread_indicators.values():
            indicator.clear()
    
    def _on_install(self):
        """Handle Install button click."""
        reply = QMessageBox.question(
            self,
            "Install Service",
            "Install CANSLIM Monitor as a Windows service?\n\n"
            "Note: This requires administrator privileges.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.service_controller.install():
                QMessageBox.information(self, "Success", "Service installed successfully")
            else:
                QMessageBox.warning(
                    self, "Failed",
                    "Failed to install service.\n\n"
                    "Try running as administrator."
                )
        
        self._refresh_status()
    
    def _on_start(self):
        """Handle Start button click."""
        success, error = self.service_controller.start_with_error()
        if success:
            self._refresh_status()
        else:
            if "Access" in error or "denied" in error.lower() or "5" in error:
                QMessageBox.warning(
                    self, "Failed",
                    "Failed to start service: Access Denied\n\n"
                    "Starting a Windows service requires administrator privileges.\n"
                    "Try running the GUI as Administrator."
                )
            else:
                QMessageBox.warning(self, "Failed", f"Failed to start service:\n{error}")
    
    def _on_stop(self):
        """
        Handle Stop button click.
        
        First tries IPC-based shutdown (doesn't need admin privileges).
        Falls back to Windows service API if IPC fails.
        """
        # Try IPC-based shutdown first (doesn't need admin)
        if self.ipc_client:
            try:
                if self.ipc_client.connect(timeout=2.0):
                    result = self.ipc_client.request_shutdown(timeout=5.0)
                    self.ipc_client.disconnect()
                    
                    if result and result.get('success'):
                        self.logger.info("Service shutdown requested via IPC")
                        # Wait a moment for service to stop, then refresh
                        QTimer.singleShot(2000, self._refresh_status)
                        return
            except Exception as e:
                self.logger.debug(f"IPC shutdown failed: {e}")
        
        # Fallback to Windows service API (needs admin)
        success, error = self.service_controller.stop_with_error()
        if success:
            self._refresh_status()
        else:
            if "Access" in error or "denied" in error.lower() or "5" in error:
                QMessageBox.warning(
                    self, "Failed",
                    "Failed to stop service: Access Denied\n\n"
                    "Stopping a Windows service requires administrator privileges.\n"
                    "Try running the GUI as Administrator, or use:\n"
                    "  services.msc → CANSLIMMonitor → Stop"
                )
            else:
                QMessageBox.warning(self, "Failed", f"Failed to stop service:\n{error}")
    
    def _on_remove(self):
        """Handle Remove button click."""
        reply = QMessageBox.question(
            self,
            "Remove Service",
            "Remove CANSLIM Monitor Windows service?\n\n"
            "Note: This requires administrator privileges.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.service_controller.remove():
                QMessageBox.information(self, "Success", "Service removed successfully")
            else:
                QMessageBox.warning(
                    self, "Failed",
                    "Failed to remove service.\n\n"
                    "Try running as administrator."
                )
        
        self._refresh_status()
    
    def refresh_now(self):
        """Force an immediate refresh."""
        self._refresh_status()
    
    def set_refresh_interval(self, ms: int):
        """Change the refresh interval."""
        self._refresh_timer.setInterval(ms)
