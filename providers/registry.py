"""
CANSLIM Monitor - Provider Registry
====================================
Plugin-style registry that maps provider names to their implementation
classes.  Concrete providers register themselves at import time so the
factory can instantiate them by name from DB / YAML config.

Usage:
    # In providers/massive.py (at module level):
    from canslim_monitor.providers.registry import ProviderRegistry
    ProviderRegistry.register_historical("massive", MassiveHistoricalProvider)

    # In the factory:
    cls = ProviderRegistry.get_historical("massive")
    provider = cls(name="massive", throttle_profile=profile, **kwargs)
"""

import logging
from typing import Dict, List, Optional, Type

from canslim_monitor.providers.base import (
    HistoricalProvider,
    RealtimeProvider,
    FuturesProvider,
)

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Central registry mapping provider names -> implementation classes."""

    _historical: Dict[str, Type[HistoricalProvider]] = {}
    _realtime: Dict[str, Type[RealtimeProvider]] = {}
    _futures: Dict[str, Type[FuturesProvider]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @classmethod
    def register_historical(cls, name: str, provider_class: Type[HistoricalProvider]):
        if name in cls._historical:
            logger.warning("Overwriting historical provider '%s'", name)
        cls._historical[name] = provider_class
        logger.debug("Registered historical provider: %s", name)

    @classmethod
    def register_realtime(cls, name: str, provider_class: Type[RealtimeProvider]):
        if name in cls._realtime:
            logger.warning("Overwriting realtime provider '%s'", name)
        cls._realtime[name] = provider_class
        logger.debug("Registered realtime provider: %s", name)

    @classmethod
    def register_futures(cls, name: str, provider_class: Type[FuturesProvider]):
        if name in cls._futures:
            logger.warning("Overwriting futures provider '%s'", name)
        cls._futures[name] = provider_class
        logger.debug("Registered futures provider: %s", name)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    @classmethod
    def get_historical(cls, name: str) -> Optional[Type[HistoricalProvider]]:
        return cls._historical.get(name)

    @classmethod
    def get_realtime(cls, name: str) -> Optional[Type[RealtimeProvider]]:
        return cls._realtime.get(name)

    @classmethod
    def get_futures(cls, name: str) -> Optional[Type[FuturesProvider]]:
        return cls._futures.get(name)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @classmethod
    def list_historical(cls) -> List[str]:
        return list(cls._historical.keys())

    @classmethod
    def list_realtime(cls) -> List[str]:
        return list(cls._realtime.keys())

    @classmethod
    def list_futures(cls) -> List[str]:
        return list(cls._futures.keys())

    @classmethod
    def list_all(cls) -> Dict[str, List[str]]:
        return {
            'historical': cls.list_historical(),
            'realtime': cls.list_realtime(),
            'futures': cls.list_futures(),
        }
