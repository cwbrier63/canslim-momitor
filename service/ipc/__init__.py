"""
CANSLIM Monitor - IPC Package
Named pipe server/client for GUI-Service communication.
"""

from .pipe_server import PipeServer, create_pipe_server
from .pipe_client import PipeClient, ServiceStatusData

__all__ = [
    'PipeServer',
    'PipeClient',
    'ServiceStatusData',
    'create_pipe_server'
]
