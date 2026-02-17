"""
CANSLIM Monitor - IBKR Realtime & Futures Providers
=====================================================
Wraps the existing ``ThreadSafeIBKRClient`` and ``ibkr_futures`` module
behind the ``RealtimeProvider`` and ``FuturesProvider`` ABCs.

Both providers share a single ``ThreadSafeIBKRClient`` connection.  The
``ProviderFactory`` detects matching host/port/client_id settings across
the ``ibkr_realtime`` and ``ibkr_futures`` DB rows and passes the same
underlying client to both providers.

Usage (via factory):
    factory = ProviderFactory(db_session_factory)
    realtime = factory.get_realtime()
    futures  = factory.get_futures()

    quote = realtime.get_quote("AAPL")      # -> providers.Quote
    snap  = futures.get_futures_snapshot()   # -> providers.FuturesSnapshot
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable

from canslim_monitor.providers.base import RealtimeProvider, FuturesProvider
from canslim_monitor.providers.types import Quote, FuturesSnapshot, ThrottleProfile
from canslim_monitor.providers.registry import ProviderRegistry


class IBKRRealtimeProvider(RealtimeProvider):
    """Live-quote provider backed by Interactive Brokers via ThreadSafeIBKRClient."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4001,
        client_id: int = 10,
        timeout: int = 30,
        max_retries: int = 3,
        reconnect: dict = None,
        *,
        ibkr_client=None,
        throttle_profile: ThrottleProfile = None,
        logger: logging.Logger = None,
        **kwargs,
    ):
        super().__init__(
            name="ibkr_realtime",
            throttle_profile=throttle_profile,
            logger=logger,
        )
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._reconnect_cfg = reconnect or {}

        # May be injected by the factory to share a single IB connection
        self._client = ibkr_client

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if self._client is not None and self._client.is_connected():
            self._record_success()
            return True

        try:
            from canslim_monitor.integrations.ibkr_client_threadsafe import (
                ThreadSafeIBKRClient,
                ReconnectConfig,
            )

            rc = ReconnectConfig(
                enabled=self._reconnect_cfg.get("enabled", True),
                initial_delay=self._reconnect_cfg.get("initial_delay", 30.0),
                max_delay=self._reconnect_cfg.get("max_delay", 300.0),
                backoff_factor=self._reconnect_cfg.get("backoff_factor", 1.5),
                max_attempts=self._reconnect_cfg.get("max_attempts", 0),
                health_check_interval=self._reconnect_cfg.get("health_check_interval", 30.0),
                gateway_restart_delay=self._reconnect_cfg.get("gateway_restart_delay", 120.0),
            )

            self._client = ThreadSafeIBKRClient(
                host=self._host,
                port=self._port,
                client_id=self._client_id,
                reconnect_config=rc,
            )

            if self._client.connect(timeout=self._timeout):
                self._record_success()
                return True

            self._record_failure("connect() returned False")
            self._client = None
            return False

        except Exception as exc:
            self._record_failure(str(exc))
            self._client = None
            return False

    def disconnect(self):
        if self._client:
            try:
                if self._client.is_connected():
                    self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    @property
    def client(self):
        """Expose underlying ThreadSafeIBKRClient for legacy callers."""
        return self._client

    # ------------------------------------------------------------------
    # RealtimeProvider interface
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str) -> Optional[Quote]:
        if not self.is_connected():
            return None

        try:
            raw = self._timed_call(self._client.get_quote, symbol)
            if raw is None:
                return None
            return self._dict_to_quote(raw)
        except Exception as exc:
            self._logger.debug("get_quote(%s) failed: %s", symbol, exc)
            return None

    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        if not self.is_connected():
            return {}

        try:
            raw_dict = self._timed_call(self._client.get_quotes, symbols)
            return {
                sym: self._dict_to_quote(data)
                for sym, data in raw_dict.items()
            }
        except Exception as exc:
            self._logger.debug("get_quotes failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _dict_to_quote(d: dict) -> Quote:
        """Convert IBKR get_quote() dict → canonical Quote."""
        return Quote(
            symbol=d.get("symbol", ""),
            last=d.get("last", 0.0),
            bid=d.get("bid"),
            ask=d.get("ask"),
            volume=d.get("volume"),
            avg_volume=d.get("avg_volume"),
            high=d.get("high"),
            low=d.get("low"),
            open=d.get("open"),
            close=d.get("close"),
            timestamp=datetime.now(),
            volume_available=d.get("volume_available", True),
        )


class IBKRFuturesProvider(FuturesProvider):
    """Overnight futures provider backed by Interactive Brokers."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4001,
        client_id: int = 10,
        timeout: int = 30,
        max_retries: int = 3,
        reconnect: dict = None,
        *,
        ibkr_client=None,
        throttle_profile: ThrottleProfile = None,
        logger: logging.Logger = None,
        **kwargs,
    ):
        super().__init__(
            name="ibkr_futures",
            throttle_profile=throttle_profile,
            logger=logger,
        )
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._reconnect_cfg = reconnect or {}

        # Shared IBKR connection (injected by factory)
        self._client = ibkr_client

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if self._client is not None and self._client.is_connected():
            self._record_success()
            return True

        try:
            from canslim_monitor.integrations.ibkr_client_threadsafe import (
                ThreadSafeIBKRClient,
                ReconnectConfig,
            )

            rc = ReconnectConfig(
                enabled=self._reconnect_cfg.get("enabled", True),
                initial_delay=self._reconnect_cfg.get("initial_delay", 30.0),
                max_delay=self._reconnect_cfg.get("max_delay", 300.0),
                backoff_factor=self._reconnect_cfg.get("backoff_factor", 1.5),
                max_attempts=self._reconnect_cfg.get("max_attempts", 0),
                health_check_interval=self._reconnect_cfg.get("health_check_interval", 30.0),
                gateway_restart_delay=self._reconnect_cfg.get("gateway_restart_delay", 120.0),
            )

            self._client = ThreadSafeIBKRClient(
                host=self._host,
                port=self._port,
                client_id=self._client_id,
                reconnect_config=rc,
            )

            if self._client.connect(timeout=self._timeout):
                self._record_success()
                return True

            self._record_failure("connect() returned False")
            self._client = None
            return False

        except Exception as exc:
            self._record_failure(str(exc))
            self._client = None
            return False

    def disconnect(self):
        if self._client:
            try:
                if self._client.is_connected():
                    self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    @property
    def client(self):
        """Expose underlying ThreadSafeIBKRClient for legacy callers."""
        return self._client

    # ------------------------------------------------------------------
    # FuturesProvider interface
    # ------------------------------------------------------------------

    def get_futures_snapshot(self) -> FuturesSnapshot:
        if not self.is_connected():
            return FuturesSnapshot()

        try:
            from canslim_monitor.regime.ibkr_futures import get_futures_snapshot

            es, nq, ym = self._timed_call(get_futures_snapshot, self._client)
            return FuturesSnapshot(
                es_change_pct=es,
                nq_change_pct=nq,
                ym_change_pct=ym,
                timestamp=datetime.now(),
            )
        except Exception as exc:
            self._logger.error("get_futures_snapshot failed: %s", exc)
            return FuturesSnapshot()


# ---------------------------------------------------------------------------
# Auto-register with the provider registry at import time
# ---------------------------------------------------------------------------
ProviderRegistry.register_realtime("ibkr", IBKRRealtimeProvider)
ProviderRegistry.register_futures("ibkr", IBKRFuturesProvider)
