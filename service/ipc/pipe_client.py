"""
CANSLIM Monitor - Named Pipe IPC Client
GUI-side client for communicating with the service.

Provides:
- Connection to service via named pipes
- Command/response communication
- Status queries (GET_STATUS)
- Async notification handling
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Callable, Any, Dict
from datetime import datetime

# Windows-specific imports
try:
    import win32file
    import win32pipe
    import pywintypes
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


@dataclass
class ServiceStatusData:
    """Parsed service status from IPC response."""
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
        """Get status for a specific thread."""
        return self.threads.get(thread_name)
    
    @property
    def total_messages(self) -> int:
        """Total messages across all threads."""
        return sum(
            t.get('message_count', 0) 
            for t in self.threads.values()
        )
    
    @property
    def total_errors(self) -> int:
        """Total errors across all threads."""
        return sum(
            t.get('error_count', 0) 
            for t in self.threads.values()
        )


class PipeClient:
    """
    Named pipe client for connecting to CANSLIM Monitor service.
    
    Provides synchronous command/response communication.
    Can detect if service is running (foreground or Windows service).
    """
    
    PIPE_NAME = r'\\.\pipe\CANSLIMMonitor'
    BUFFER_SIZE = 65536
    
    def __init__(
        self,
        notification_callback: Callable[[dict], None] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize IPC client.
        
        Args:
            notification_callback: Callback for push notifications from service
            logger: Logger instance
        """
        self.notification_callback = notification_callback
        self.logger = logger or logging.getLogger('canslim.ipc_client')
        
        self._pipe_handle = None
        self._connected = False
    
    def connect(self, timeout: float = 5.0) -> bool:
        """
        Connect to the service's named pipe.
        
        Args:
            timeout: How long to wait for connection (seconds)
            
        Returns:
            True if connected, False otherwise
        """
        if not HAS_WIN32:
            self.logger.debug("win32file not available - cannot connect")
            return False
        
        if self._connected:
            return True
        
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            try:
                # Try to open the pipe
                self._pipe_handle = win32file.CreateFile(
                    self.PIPE_NAME,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,  # No sharing
                    None,  # Default security
                    win32file.OPEN_EXISTING,
                    0,  # Default attributes
                    None  # No template
                )
                
                # Set pipe to message mode
                win32pipe.SetNamedPipeHandleState(
                    self._pipe_handle,
                    win32pipe.PIPE_READMODE_MESSAGE,
                    None,
                    None
                )
                
                self._connected = True
                self.logger.debug("Connected to service pipe")
                return True
                
            except pywintypes.error as e:
                if e.winerror == 2:  # ERROR_FILE_NOT_FOUND - pipe doesn't exist
                    self.logger.debug("Pipe not found - service not running?")
                    time.sleep(0.1)
                elif e.winerror == 231:  # ERROR_PIPE_BUSY
                    self.logger.debug("Pipe busy, waiting...")
                    win32pipe.WaitNamedPipe(self.PIPE_NAME, 1000)
                else:
                    self.logger.warning(f"Connection error: {e}")
                    break
        
        return False
    
    def disconnect(self):
        """Disconnect from the service."""
        if self._pipe_handle:
            try:
                win32file.CloseHandle(self._pipe_handle)
            except Exception:
                pass
            self._pipe_handle = None
        self._connected = False
        self.logger.debug("Disconnected from service")
    
    def is_connected(self) -> bool:
        """Check if currently connected to service."""
        return self._connected
    
    def send_command(self, command_type: str, data: dict = None, timeout: float = 5.0) -> Optional[dict]:
        """
        Send a command to the service and wait for response.
        
        Args:
            command_type: Type of command (GET_STATUS, RELOAD_CONFIG, etc.)
            data: Optional command data
            timeout: Response timeout in seconds
            
        Returns:
            Response data dict, or None on error
        """
        if not self._connected:
            self.logger.warning("Not connected - cannot send command")
            return None
        
        request_id = str(uuid.uuid4())
        
        message = json.dumps({
            'type': command_type,
            'request_id': request_id,
            'timestamp': datetime.now().isoformat(),
            'data': data or {}
        })
        
        try:
            # Send command
            message_bytes = message.encode('utf-8')
            win32file.WriteFile(self._pipe_handle, message_bytes)
            
            # Wait for response
            result, response_bytes = win32file.ReadFile(self._pipe_handle, self.BUFFER_SIZE)
            
            if result == 0 and response_bytes:
                response = json.loads(response_bytes.decode('utf-8'))
                
                if response.get('request_id') == request_id:
                    return response.get('data', {})
                else:
                    self.logger.warning("Response ID mismatch")
                    return None
                    
        except pywintypes.error as e:
            self.logger.error(f"Command error: {e}")
            self._connected = False
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid response JSON: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            self._connected = False
        
        return None
    
    def get_status(self, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        """
        Get service status including thread states.
        
        Convenience method for GET_STATUS command.
        
        Returns:
            Status dict with service_running, threads, etc.
        """
        return self.send_command('GET_STATUS', timeout=timeout)
    
    def get_stats(self, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        """
        Alias for get_status() - for compatibility.
        """
        return self.get_status(timeout=timeout)
    
    def force_check(self, symbol: str = None, timeout: float = 5.0) -> Optional[dict]:
        """Force an immediate check cycle."""
        return self.send_command('FORCE_CHECK', {'symbol': symbol}, timeout=timeout)
    
    def reload_config(self, timeout: float = 5.0) -> Optional[dict]:
        """Tell service to reload configuration."""
        return self.send_command('RELOAD_CONFIG', timeout=timeout)
    
    def request_shutdown(self, timeout: float = 5.0) -> Optional[dict]:
        """
        Request graceful shutdown of the service.
        
        This sends a SHUTDOWN command via IPC, which doesn't require
        admin privileges (unlike stopping the Windows service directly).
        
        Returns:
            Response dict with success/message, or None on failure
        """
        return self.send_command('SHUTDOWN', timeout=timeout)
    
    def is_service_running(self, timeout: float = 1.0) -> bool:
        """
        Quick check if service is running.
        
        Attempts to connect and immediately disconnect.
        Useful for status checks without full communication.
        """
        if self._connected:
            return True
        
        try:
            if self.connect(timeout=timeout):
                self.disconnect()
                return True
        except Exception:
            pass
        
        return False


class MockPipeClient:
    """
    Mock pipe client for testing/development on non-Windows platforms.
    """
    
    def __init__(
        self,
        notification_callback: Callable[[dict], None] = None,
        logger: Optional[logging.Logger] = None
    ):
        self.notification_callback = notification_callback
        self.logger = logger or logging.getLogger('canslim.mock_client')
        self._connected = False
    
    def connect(self, timeout: float = 5.0) -> bool:
        self.logger.debug("Mock connect - returning False")
        return False
    
    def disconnect(self):
        self._connected = False
    
    def is_connected(self) -> bool:
        return False
    
    def send_command(self, command_type: str, data: dict = None, timeout: float = 5.0) -> Optional[dict]:
        return None
    
    def get_status(self, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        return None
    
    def get_stats(self, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        return None
    
    def is_service_running(self, timeout: float = 1.0) -> bool:
        return False
    
    def request_shutdown(self, timeout: float = 5.0) -> Optional[dict]:
        return None


def create_pipe_client(
    notification_callback: Callable[[dict], None] = None,
    logger: logging.Logger = None
) -> Any:
    """
    Create appropriate pipe client for the platform.
    
    Returns PipeClient on Windows, MockPipeClient otherwise.
    """
    if HAS_WIN32:
        return PipeClient(
            notification_callback=notification_callback,
            logger=logger
        )
    else:
        return MockPipeClient(
            notification_callback=notification_callback,
            logger=logger
        )
