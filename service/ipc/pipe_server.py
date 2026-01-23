"""
CANSLIM Monitor - Named Pipe IPC Server
Service-side server for communicating with GUI clients.

Provides:
- Named pipe server accepting GUI connections
- Command routing to ServiceController
- Push notifications to connected clients
"""

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Optional, Callable, Any, Dict
from queue import Queue

# Windows-specific imports
try:
    import win32pipe
    import win32file
    import win32security
    import pywintypes
    import ntsecuritycon
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class IPCMessage:
    """Represents a message in the IPC protocol."""
    
    def __init__(
        self,
        msg_type: str,
        data: dict = None,
        request_id: str = None
    ):
        self.type = msg_type
        self.data = data or {}
        self.request_id = request_id or str(uuid.uuid4())
        self.timestamp = datetime.now().isoformat()
    
    def to_json(self) -> str:
        """Serialize message to JSON."""
        return json.dumps({
            'type': self.type,
            'request_id': self.request_id,
            'timestamp': self.timestamp,
            'data': self.data
        })
    
    @classmethod
    def from_json(cls, json_str: str) -> 'IPCMessage':
        """Deserialize message from JSON."""
        obj = json.loads(json_str)
        return cls(
            msg_type=obj.get('type', 'UNKNOWN'),
            data=obj.get('data', {}),
            request_id=obj.get('request_id')
        )


class IPCResponse:
    """Represents a response in the IPC protocol."""
    
    def __init__(
        self,
        request_id: str,
        status: str = 'success',
        data: dict = None,
        error: str = None
    ):
        self.request_id = request_id
        self.status = status
        self.data = data or {}
        self.error = error
        self.timestamp = datetime.now().isoformat()
    
    def to_json(self) -> str:
        """Serialize response to JSON."""
        return json.dumps({
            'request_id': self.request_id,
            'status': self.status,
            'timestamp': self.timestamp,
            'data': self.data,
            'error': self.error
        })


class PipeServer(threading.Thread):
    """
    Named pipe server for IPC with GUI.
    
    Creates a named pipe and listens for connections from GUI clients.
    Handles commands and sends responses/notifications.
    """
    
    PIPE_NAME = r'\\.\pipe\CANSLIMMonitor'
    BUFFER_SIZE = 65536
    
    def __init__(
        self,
        command_queue: Queue,
        shutdown_event: threading.Event,
        command_handler: Callable[[dict], dict] = None,
        logger: Optional[logging.Logger] = None
    ):
        super().__init__(name='ipc_server', daemon=True)
        
        self.command_queue = command_queue
        self.shutdown_event = shutdown_event
        self.command_handler = command_handler
        self.logger = logger or logging.getLogger('canslim.ipc')
        
        self._pipe_handle = None
        self._connected = False
    
    def run(self):
        """Main server loop."""
        if not HAS_WIN32:
            self.logger.error("win32pipe not available - IPC server cannot run")
            return
        
        self.logger.info(f"IPC server starting on {self.PIPE_NAME}")
        
        while not self.shutdown_event.is_set():
            try:
                # Create named pipe
                self._pipe_handle = self._create_pipe()
                
                if self._pipe_handle is None:
                    self.logger.error("Failed to create pipe")
                    time.sleep(1)
                    continue
                
                self.logger.debug("Waiting for client connection...")
                
                # Wait for client connection
                try:
                    win32pipe.ConnectNamedPipe(self._pipe_handle, None)
                    self._connected = True
                    self.logger.info("Client connected")
                except pywintypes.error as e:
                    if e.winerror == 233:  # ERROR_PIPE_NOT_CONNECTED
                        self.logger.debug("No client connected")
                    else:
                        self.logger.error(f"Pipe connection error: {e}")
                    self._cleanup_pipe()
                    continue
                
                # Handle client communication
                self._handle_client()
                
            except Exception as e:
                self.logger.error(f"Server error: {e}", exc_info=True)
                time.sleep(1)
            finally:
                self._cleanup_pipe()
        
        self.logger.info("IPC server stopped")
    
    def _create_pipe(self):
        """Create the named pipe with appropriate security."""
        try:
            # Create security attributes allowing all users to connect
            security_attributes = win32security.SECURITY_ATTRIBUTES()
            security_attributes.bInheritHandle = False
            
            # Create a security descriptor that allows everyone to access
            sd = win32security.SECURITY_DESCRIPTOR()
            sd.SetSecurityDescriptorDacl(1, None, 0)  # Allow all access
            security_attributes.SECURITY_DESCRIPTOR = sd
            
            pipe = win32pipe.CreateNamedPipe(
                self.PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                (win32pipe.PIPE_TYPE_MESSAGE |
                 win32pipe.PIPE_READMODE_MESSAGE |
                 win32pipe.PIPE_WAIT),
                1,  # Max instances
                self.BUFFER_SIZE,
                self.BUFFER_SIZE,
                0,  # Default timeout
                security_attributes
            )
            
            return pipe
            
        except pywintypes.error as e:
            self.logger.error(f"Failed to create pipe: {e}")
            return None
    
    def _handle_client(self):
        """Handle communication with connected client."""
        while self._connected and not self.shutdown_event.is_set():
            try:
                # Read message from client
                result, data = win32file.ReadFile(self._pipe_handle, self.BUFFER_SIZE)
                
                if result == 0 and data:
                    message = data.decode('utf-8')
                    self.logger.debug(f"Received: {message[:100]}...")
                    
                    # Parse and handle command
                    response = self._process_message(message)
                    
                    # Send response
                    if response:
                        response_bytes = response.encode('utf-8')
                        win32file.WriteFile(self._pipe_handle, response_bytes)
                        
            except pywintypes.error as e:
                if e.winerror == 109:  # ERROR_BROKEN_PIPE - client disconnected
                    self.logger.info("Client disconnected")
                    self._connected = False
                elif e.winerror == 232:  # ERROR_NO_DATA - pipe closing
                    self._connected = False
                else:
                    self.logger.error(f"Read error: {e}")
                    self._connected = False
            except Exception as e:
                self.logger.error(f"Error handling client: {e}", exc_info=True)
                self._connected = False
    
    def _process_message(self, message: str) -> str:
        """Process incoming message and return response."""
        try:
            msg = IPCMessage.from_json(message)
            
            # Handle directly if we have a command handler
            if self.command_handler:
                result = self.command_handler({
                    'type': msg.type,
                    'data': msg.data,
                    'request_id': msg.request_id
                })
                
                return IPCResponse(
                    request_id=msg.request_id,
                    status='success',
                    data=result
                ).to_json()
            
            # Otherwise put in queue for ServiceController
            self.command_queue.put({
                'type': msg.type,
                'data': msg.data,
                'request_id': msg.request_id
            })
            
            return IPCResponse(
                request_id=msg.request_id,
                status='queued'
            ).to_json()
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON: {e}")
            return IPCResponse(
                request_id='unknown',
                status='error',
                error=f'Invalid JSON: {e}'
            ).to_json()
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            return IPCResponse(
                request_id='unknown',
                status='error',
                error=str(e)
            ).to_json()
    
    def _cleanup_pipe(self):
        """Clean up pipe handle."""
        self._connected = False
        if self._pipe_handle:
            try:
                win32pipe.DisconnectNamedPipe(self._pipe_handle)
                win32file.CloseHandle(self._pipe_handle)
            except Exception:
                pass
            self._pipe_handle = None
    
    def send_notification(self, notification: dict):
        """
        Send a push notification to connected client.
        
        Args:
            notification: Notification dict to send
        """
        if not self._connected or not self._pipe_handle:
            return
        
        try:
            data = json.dumps(notification).encode('utf-8')
            win32file.WriteFile(self._pipe_handle, data)
        except Exception as e:
            self.logger.warning(f"Failed to send notification: {e}")
    
    def is_client_connected(self) -> bool:
        """Check if a client is connected."""
        return self._connected


class MockPipeServer(threading.Thread):
    """
    Mock pipe server for testing/development on non-Windows platforms.
    """
    
    def __init__(
        self,
        command_queue: Queue,
        shutdown_event: threading.Event,
        command_handler: Callable[[dict], dict] = None,
        logger: Optional[logging.Logger] = None
    ):
        super().__init__(name='mock_ipc_server', daemon=True)
        
        self.command_queue = command_queue
        self.shutdown_event = shutdown_event
        self.command_handler = command_handler
        self.logger = logger or logging.getLogger('canslim.mock_ipc')
        
        self._connected = False
    
    def run(self):
        """Mock server loop - just wait for shutdown."""
        self.logger.info("Mock IPC server started")
        
        while not self.shutdown_event.is_set():
            self.shutdown_event.wait(1)
        
        self.logger.info("Mock IPC server stopped")
    
    def send_notification(self, notification: dict):
        """Mock notification - just log."""
        self.logger.debug(f"Mock notification: {notification}")
    
    def is_client_connected(self) -> bool:
        """Mock always returns False."""
        return False


def create_pipe_server(
    command_queue: Queue,
    shutdown_event: threading.Event,
    command_handler: Callable[[dict], dict] = None,
    logger: logging.Logger = None
) -> Any:
    """
    Create appropriate pipe server for the platform.
    
    Returns PipeServer on Windows, MockPipeServer otherwise.
    """
    if HAS_WIN32:
        return PipeServer(
            command_queue=command_queue,
            shutdown_event=shutdown_event,
            command_handler=command_handler,
            logger=logger
        )
    else:
        return MockPipeServer(
            command_queue=command_queue,
            shutdown_event=shutdown_event,
            command_handler=command_handler,
            logger=logger
        )
