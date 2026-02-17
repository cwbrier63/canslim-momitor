"""
CANSLIM Monitor - Provider Factory
====================================
Creates and manages provider instances from DB configuration.

The factory:
  1. Reads ``provider_config`` rows from the database
  2. Looks up the implementation class via ``ProviderRegistry``
  3. Constructs a ``ThrottleProfile`` from the stored rate-limit fields
  4. Injects credentials (API key, etc.) from ``provider_credentials``
  5. Returns a connected, ready-to-use provider instance

If no DB rows exist yet (fresh install), the factory can fall back to
YAML config via ``seed_from_yaml()``.

Usage:
    factory = ProviderFactory(db_session_factory)
    historical = factory.get_historical()   # -> HistoricalProvider
    realtime   = factory.get_realtime()     # -> RealtimeProvider (Phase 5)
    futures    = factory.get_futures()      # -> FuturesProvider  (Phase 5)
"""

import json
import logging
from typing import Optional, Callable

from sqlalchemy.orm import Session

from canslim_monitor.providers.types import ThrottleProfile
from canslim_monitor.providers.base import (
    HistoricalProvider,
    RealtimeProvider,
    FuturesProvider,
)
from canslim_monitor.providers.registry import ProviderRegistry
from canslim_monitor.data.models import ProviderConfig, ProviderCredential
from canslim_monitor.data.repositories.provider_repo import ProviderRepository

logger = logging.getLogger(__name__)


class ProviderFactory:
    """Creates provider instances from database configuration."""

    def __init__(self, db_session_factory: Callable[[], Session]):
        """
        Args:
            db_session_factory: Callable that returns a new SQLAlchemy Session.
                                Typically ``db_manager.get_new_session``.
        """
        self._session_factory = db_session_factory

        # Cache live provider instances so repeated calls return the same
        # connected object (important for shared IBKR connections).
        self._instances: dict = {}

    # ------------------------------------------------------------------
    # Public: get provider by domain
    # ------------------------------------------------------------------

    def get_historical(self) -> Optional[HistoricalProvider]:
        """Return the primary enabled historical provider, or None."""
        return self._get_for_domain("historical")

    def get_realtime(self) -> Optional[RealtimeProvider]:
        """Return the primary enabled realtime provider, or None."""
        return self._get_for_domain("realtime")

    def get_futures(self) -> Optional[FuturesProvider]:
        """Return the primary enabled futures provider, or None."""
        return self._get_for_domain("futures")

    # ------------------------------------------------------------------
    # Public: seed DB from YAML (one-time migration helper)
    # ------------------------------------------------------------------

    def seed_from_yaml(self, config: dict):
        """Populate ``provider_config`` + ``provider_credentials`` from a
        YAML config dict (e.g. the merged user_config / config.yaml).

        Only inserts rows that don't already exist (safe to re-run).
        """
        session = self._session_factory()
        try:
            repo = ProviderRepository(session)
            self._seed_massive(repo, config)
            self._seed_ibkr(repo, config)
            session.commit()
            logger.info("Provider config seeded from YAML")
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Internal: create instance from DB row
    # ------------------------------------------------------------------

    def _get_for_domain(self, domain: str):
        """Look up the primary provider for *domain*, create & cache it."""
        # Return cached instance if available
        if domain in self._instances:
            inst = self._instances[domain]
            if inst.is_connected():
                return inst

        session = self._session_factory()
        try:
            repo = ProviderRepository(session)
            provider_cfg = repo.get_primary_for_domain(domain)

            if not provider_cfg:
                logger.warning("No enabled %s provider configured in DB", domain)
                return None

            credentials = repo.get_all_credentials(provider_cfg.id)
            instance = self._create_instance(provider_cfg, credentials)

            if instance:
                self._instances[domain] = instance

            return instance
        finally:
            session.close()

    def _create_instance(self, cfg: ProviderConfig, credentials: dict):
        """Instantiate a provider from its DB config row + credentials."""
        impl_name = cfg.implementation
        domain = cfg.provider_type

        # Look up class in registry
        lookup = {
            "historical": ProviderRegistry.get_historical,
            "realtime": ProviderRegistry.get_realtime,
            "futures": ProviderRegistry.get_futures,
        }
        provider_cls = lookup.get(domain, lambda n: None)(impl_name)

        if provider_cls is None:
            logger.error(
                "No registered %s provider for implementation '%s'. "
                "Available: %s",
                domain,
                impl_name,
                ProviderRegistry.list_all(),
            )
            return None

        # Build ThrottleProfile if rate-limit fields are populated
        throttle = None
        if cfg.calls_per_minute:
            throttle = ThrottleProfile(
                calls_per_minute=cfg.calls_per_minute,
                burst_size=cfg.burst_size or 0,
                min_delay_seconds=cfg.min_delay_seconds or 0.0,
            )

        # Parse JSON settings
        settings = cfg.get_settings()

        # Merge credentials into kwargs
        kwargs = dict(settings)
        if "api_key" in credentials:
            kwargs["api_key"] = credentials["api_key"]

        kwargs["throttle_profile"] = throttle

        # Shared IBKR connection: if another IBKR domain is already cached,
        # inject its underlying client so both providers share one connection.
        if impl_name == "ibkr":
            shared_client = self._find_shared_ibkr_client()
            if shared_client is not None:
                kwargs["ibkr_client"] = shared_client
                logger.info(
                    "Sharing existing IBKR client with '%s' provider",
                    cfg.name,
                )

        try:
            instance = provider_cls(**kwargs)
        except TypeError as exc:
            logger.error(
                "Failed to construct %s(%s): %s. kwargs=%s",
                provider_cls.__name__,
                impl_name,
                exc,
                list(kwargs.keys()),
            )
            return None

        # Connect
        try:
            if instance.connect():
                logger.info(
                    "Provider '%s' (%s/%s) connected",
                    cfg.name,
                    domain,
                    impl_name,
                )
                return instance
            else:
                logger.warning("Provider '%s' connect() returned False", cfg.name)
                return None
        except Exception as exc:
            logger.error("Provider '%s' connect() raised: %s", cfg.name, exc)
            return None

    # ------------------------------------------------------------------
    # Shared IBKR connection
    # ------------------------------------------------------------------

    def _find_shared_ibkr_client(self):
        """Return an already-connected ThreadSafeIBKRClient from any cached
        IBKR provider, or None if no IBKR provider is cached yet."""
        for inst in self._instances.values():
            if hasattr(inst, "client") and inst.client is not None:
                # Check if this is an IBKR provider by looking at the
                # underlying client type name (avoids importing IBKR at
                # module level).
                client = inst.client
                if type(client).__name__ == "ThreadSafeIBKRClient":
                    return client
        return None

    # ------------------------------------------------------------------
    # YAML seeding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _seed_massive(repo: ProviderRepository, config: dict):
        """Seed Massive/Polygon providers from YAML (historical + realtime)."""
        # Pull from market_data or polygon section
        md = config.get("market_data", {})
        pg = config.get("polygon", {})

        api_key = md.get("api_key") or pg.get("api_key", "")
        base_url = md.get("base_url") or pg.get("base_url", "https://api.polygon.io")
        timeout = md.get("timeout") or pg.get("timeout", 30)
        rate_limit_delay = md.get("rate_limit_delay", 0.5)

        # Historical provider
        if not repo.get_by_name("massive_historical"):
            provider = repo.create_provider(
                name="massive_historical",
                display_name="Massive (Polygon API)",
                provider_type="historical",
                implementation="massive",
                settings={
                    "base_url": base_url,
                    "timeout": timeout,
                    "rate_limit_delay": rate_limit_delay,
                },
                tier_name="starter",
                calls_per_minute=5,
                min_delay_seconds=0.5,
            )

            if api_key:
                repo.set_credential(provider.id, "api_key", api_key)

            logger.info("Seeded massive_historical from YAML config")

        # Delayed-realtime provider (same API key, lower priority than IBKR)
        if not repo.get_by_name("massive_realtime"):
            rt_provider = repo.create_provider(
                name="massive_realtime",
                display_name="Massive Delayed Quotes",
                provider_type="realtime",
                implementation="massive",
                settings={
                    "base_url": base_url,
                    "timeout": timeout,
                    "rate_limit_delay": rate_limit_delay,
                    "cache_seconds": 60,
                },
                tier_name="starter",
                calls_per_minute=5,
                min_delay_seconds=0.5,
                priority=10,  # Higher number = lower priority
            )
            if api_key:
                repo.set_credential(rt_provider.id, "api_key", api_key)
            logger.info("Seeded massive_realtime from YAML config")

    @staticmethod
    def _seed_ibkr(repo: ProviderRepository, config: dict):
        """Seed IBKR realtime + futures providers from YAML."""
        ibkr = config.get("ibkr", {})
        if not ibkr:
            return

        host = ibkr.get("host", "127.0.0.1")
        port = ibkr.get("port", 4001)
        client_id = ibkr.get("client_id_base", 10)
        timeout = ibkr.get("timeout", 30)
        max_retries = ibkr.get("max_retries", 3)
        reconnect = ibkr.get("reconnect", {})

        shared_settings = {
            "host": host,
            "port": port,
            "client_id": client_id,
            "timeout": timeout,
            "max_retries": max_retries,
            "reconnect": reconnect,
        }

        # Realtime provider
        if not repo.get_by_name("ibkr_realtime"):
            repo.create_provider(
                name="ibkr_realtime",
                display_name="Interactive Brokers",
                provider_type="realtime",
                implementation="ibkr",
                settings=shared_settings,
            )
            logger.info("Seeded ibkr_realtime from YAML config")

        # Futures provider
        if not repo.get_by_name("ibkr_futures"):
            repo.create_provider(
                name="ibkr_futures",
                display_name="Interactive Brokers",
                provider_type="futures",
                implementation="ibkr",
                settings=shared_settings,
            )
            logger.info("Seeded ibkr_futures from YAML config")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def disconnect_all(self):
        """Disconnect and clear all cached provider instances.

        Handles shared IBKR connections: only disconnects the underlying
        client once, even if multiple providers reference it.
        """
        disconnected_clients = set()
        for domain, instance in self._instances.items():
            try:
                # For IBKR providers sharing a client, only disconnect once
                underlying = getattr(instance, "client", None)
                client_id = id(underlying) if underlying else None

                if client_id and client_id in disconnected_clients:
                    # Another provider already disconnected this client;
                    # just clear the reference.
                    logger.debug(
                        "Skipping disconnect for '%s' (shared client already disconnected)",
                        domain,
                    )
                else:
                    instance.disconnect()
                    if client_id:
                        disconnected_clients.add(client_id)
                    logger.info("Disconnected provider for domain '%s'", domain)
            except Exception as exc:
                logger.warning("Error disconnecting %s: %s", domain, exc)
        self._instances.clear()
