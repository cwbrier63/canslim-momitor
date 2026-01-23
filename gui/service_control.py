"""
CANSLIM Monitor - GUI Service Control
Wrapper for Windows Service management from the GUI.

Provides:
- Query Windows service status
- Start/Stop/Install/Remove commands
- Works even when service isn't running
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

# Windows service utilities
try:
    import win32serviceutil
    import win32service
    HAS_WIN32SERVICE = True
except ImportError:
    HAS_WIN32SERVICE = False


class ServiceState(Enum):
    """Windows service states."""
    STOPPED = "stopped"
    RUNNING = "running"
    STARTING = "starting"
    STOPPING = "stopping"
    PAUSED = "paused"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


@dataclass
class ServiceStatus:
    """Service status information."""
    state: ServiceState
    pid: Optional[int] = None
    checkpoint: int = 0
    wait_hint: int = 0
    
    @property
    def is_running(self) -> bool:
        return self.state == ServiceState.RUNNING
    
    @property
    def is_installed(self) -> bool:
        return self.state != ServiceState.NOT_INSTALLED


class ServiceController:
    """
    Controller for managing the CANSLIM Monitor Windows service.
    
    Wraps win32serviceutil for service management operations.
    """
    
    SERVICE_NAME = "CANSLIMMonitor"
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger('canslim.service_control')
    
    def get_status(self) -> ServiceStatus:
        """
        Get current service status.
        
        Returns:
            ServiceStatus with current state
        """
        if not HAS_WIN32SERVICE:
            return ServiceStatus(state=ServiceState.UNKNOWN)
        
        try:
            status = win32serviceutil.QueryServiceStatus(self.SERVICE_NAME)
            
            # status is a tuple: (type, state, controls, exitcode, serviceexitcode, checkpoint, waithint)
            state_code = status[1]
            
            state_map = {
                win32service.SERVICE_STOPPED: ServiceState.STOPPED,
                win32service.SERVICE_START_PENDING: ServiceState.STARTING,
                win32service.SERVICE_STOP_PENDING: ServiceState.STOPPING,
                win32service.SERVICE_RUNNING: ServiceState.RUNNING,
                win32service.SERVICE_PAUSED: ServiceState.PAUSED,
            }
            
            state = state_map.get(state_code, ServiceState.UNKNOWN)
            
            return ServiceStatus(
                state=state,
                checkpoint=status[5],
                wait_hint=status[6]
            )
            
        except Exception as e:
            if "1060" in str(e):  # ERROR_SERVICE_DOES_NOT_EXIST
                return ServiceStatus(state=ServiceState.NOT_INSTALLED)
            
            self.logger.warning(f"Error querying service: {e}")
            return ServiceStatus(state=ServiceState.UNKNOWN)
    
    def is_installed(self) -> bool:
        """Check if service is installed."""
        status = self.get_status()
        return status.is_installed
    
    def is_running(self) -> bool:
        """Check if service is running."""
        status = self.get_status()
        return status.is_running
    
    def start(self) -> bool:
        """
        Start the service.
        
        Returns:
            True if started successfully
        """
        success, _ = self.start_with_error()
        return success
    
    def start_with_error(self) -> Tuple[bool, str]:
        """
        Start the service with error details.
        
        Returns:
            Tuple of (success, error_message)
        """
        if not HAS_WIN32SERVICE:
            return False, "Windows service utilities not available"
        
        try:
            win32serviceutil.StartService(self.SERVICE_NAME)
            self.logger.info(f"Service {self.SERVICE_NAME} started")
            return True, ""
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Failed to start service: {error_msg}")
            return False, error_msg
    
    def stop(self) -> bool:
        """
        Stop the service.
        
        Returns:
            True if stopped successfully
        """
        success, _ = self.stop_with_error()
        return success
    
    def stop_with_error(self) -> Tuple[bool, str]:
        """
        Stop the service with error details.
        
        Returns:
            Tuple of (success, error_message)
        """
        if not HAS_WIN32SERVICE:
            return False, "Windows service utilities not available"
        
        try:
            win32serviceutil.StopService(self.SERVICE_NAME)
            self.logger.info(f"Service {self.SERVICE_NAME} stopped")
            return True, ""
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Failed to stop service: {error_msg}")
            return False, error_msg
    
    def restart(self) -> bool:
        """
        Restart the service.
        
        Returns:
            True if restarted successfully
        """
        if not HAS_WIN32SERVICE:
            self.logger.error("Windows service utilities not available")
            return False
        
        try:
            win32serviceutil.RestartService(self.SERVICE_NAME)
            self.logger.info(f"Service {self.SERVICE_NAME} restarted")
            return True
        except Exception as e:
            self.logger.error(f"Failed to restart service: {e}")
            return False
    
    def install(self) -> bool:
        """
        Install the service.
        
        Note: Requires administrator privileges.
        
        Returns:
            True if installed successfully
        """
        if not HAS_WIN32SERVICE:
            self.logger.error("Windows service utilities not available")
            return False
        
        try:
            # This would need the actual service module path
            # win32serviceutil.InstallService(...)
            self.logger.warning("Service installation requires administrator privileges")
            return False
        except Exception as e:
            self.logger.error(f"Failed to install service: {e}")
            return False
    
    def remove(self) -> bool:
        """
        Remove/uninstall the service.
        
        Note: Requires administrator privileges.
        
        Returns:
            True if removed successfully
        """
        if not HAS_WIN32SERVICE:
            self.logger.error("Windows service utilities not available")
            return False
        
        try:
            win32serviceutil.RemoveService(self.SERVICE_NAME)
            self.logger.info(f"Service {self.SERVICE_NAME} removed")
            return True
        except Exception as e:
            self.logger.error(f"Failed to remove service: {e}")
            return False


def create_service_controller(logger: logging.Logger = None) -> ServiceController:
    """Factory function to create a ServiceController."""
    return ServiceController(logger=logger)
