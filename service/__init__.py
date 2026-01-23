"""
CANSLIM Monitor - Service Package
Windows service layer for background monitoring.
"""

from .service_controller import ServiceController

__all__ = ['ServiceController']
