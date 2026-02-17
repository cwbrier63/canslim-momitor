"""
CANSLIM Monitor - Provider Repository
======================================
CRUD operations for ProviderConfig, ProviderCredential, and ProviderHealthLog.
"""

import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from canslim_monitor.data.models import (
    ProviderConfig,
    ProviderCredential,
    ProviderHealthLog,
)


class ProviderRepository:
    """Repository for provider configuration, credentials, and health."""

    def __init__(self, session: Session):
        self.session = session

    # ==================================================================
    # ProviderConfig — CRUD
    # ==================================================================

    # -------------------- CREATE --------------------

    def create_provider(
        self,
        name: str,
        provider_type: str,
        implementation: str,
        *,
        display_name: str = None,
        enabled: bool = True,
        priority: int = 0,
        settings: dict = None,
        tier_name: str = None,
        calls_per_minute: int = None,
        burst_size: int = 0,
        min_delay_seconds: float = 0.0,
    ) -> ProviderConfig:
        """Create a new provider configuration."""
        provider = ProviderConfig(
            name=name,
            display_name=display_name,
            provider_type=provider_type,
            implementation=implementation,
            enabled=enabled,
            priority=priority,
            settings=json.dumps(settings or {}),
            tier_name=tier_name,
            calls_per_minute=calls_per_minute,
            burst_size=burst_size,
            min_delay_seconds=min_delay_seconds,
        )
        self.session.add(provider)
        self.session.flush()
        return provider

    # -------------------- READ --------------------

    def get_by_name(self, name: str) -> Optional[ProviderConfig]:
        """Get a provider by unique name (e.g. 'massive_historical')."""
        return (
            self.session.query(ProviderConfig)
            .filter_by(name=name)
            .first()
        )

    def get_by_id(self, provider_id: int) -> Optional[ProviderConfig]:
        return (
            self.session.query(ProviderConfig)
            .filter_by(id=provider_id)
            .first()
        )

    def get_all(self, *, enabled_only: bool = False) -> List[ProviderConfig]:
        """Get all providers, optionally filtering to enabled only."""
        query = self.session.query(ProviderConfig)
        if enabled_only:
            query = query.filter(ProviderConfig.enabled == True)
        return query.order_by(ProviderConfig.priority).all()

    def get_for_domain(self, provider_type: str, *, enabled_only: bool = True) -> List[ProviderConfig]:
        """Get providers for a domain (historical/realtime/futures), ordered by priority."""
        query = self.session.query(ProviderConfig).filter_by(
            provider_type=provider_type
        )
        if enabled_only:
            query = query.filter(ProviderConfig.enabled == True)
        return query.order_by(ProviderConfig.priority).all()

    def get_primary_for_domain(self, provider_type: str) -> Optional[ProviderConfig]:
        """Get the highest-priority enabled provider for a domain."""
        providers = self.get_for_domain(provider_type, enabled_only=True)
        return providers[0] if providers else None

    def get_by_implementation(self, implementation: str) -> List[ProviderConfig]:
        """Get all provider configs that use a given implementation (e.g. 'ibkr')."""
        return (
            self.session.query(ProviderConfig)
            .filter_by(implementation=implementation)
            .order_by(ProviderConfig.priority)
            .all()
        )

    # -------------------- UPDATE --------------------

    def update_provider(self, provider: ProviderConfig, **kwargs) -> ProviderConfig:
        """Update arbitrary fields on a provider config."""
        for key, value in kwargs.items():
            if key == 'settings' and isinstance(value, dict):
                provider.settings = json.dumps(value)
            elif hasattr(provider, key):
                setattr(provider, key, value)
        self.session.flush()
        return provider

    def update_settings(self, provider: ProviderConfig, settings: dict) -> ProviderConfig:
        """Replace the JSON settings blob."""
        provider.set_settings(settings)
        self.session.flush()
        return provider

    def merge_settings(self, provider: ProviderConfig, partial: dict) -> ProviderConfig:
        """Merge partial settings into existing settings dict."""
        current = provider.get_settings()
        current.update(partial)
        provider.set_settings(current)
        self.session.flush()
        return provider

    def set_enabled(self, provider: ProviderConfig, enabled: bool) -> ProviderConfig:
        provider.enabled = enabled
        self.session.flush()
        return provider

    # -------------------- DELETE --------------------

    def delete_provider(self, provider: ProviderConfig):
        """Delete a provider and cascade to credentials + health log."""
        self.session.delete(provider)
        self.session.flush()

    # ==================================================================
    # ProviderCredential — CRUD
    # ==================================================================

    def get_credential(
        self, provider_id: int, credential_type: str
    ) -> Optional[str]:
        """Get a credential value (plain-text) for a provider."""
        cred = (
            self.session.query(ProviderCredential)
            .filter_by(provider_id=provider_id, credential_type=credential_type)
            .first()
        )
        return cred.credential_value if cred else None

    def get_all_credentials(self, provider_id: int) -> Dict[str, str]:
        """Get all credentials for a provider as {type: value} dict."""
        creds = (
            self.session.query(ProviderCredential)
            .filter_by(provider_id=provider_id)
            .all()
        )
        return {c.credential_type: c.credential_value for c in creds}

    def set_credential(
        self,
        provider_id: int,
        credential_type: str,
        credential_value: str,
        *,
        expires_at: datetime = None,
    ) -> ProviderCredential:
        """Create or update a credential (upsert)."""
        cred = (
            self.session.query(ProviderCredential)
            .filter_by(provider_id=provider_id, credential_type=credential_type)
            .first()
        )
        if cred:
            cred.credential_value = credential_value
            if expires_at is not None:
                cred.expires_at = expires_at
        else:
            cred = ProviderCredential(
                provider_id=provider_id,
                credential_type=credential_type,
                credential_value=credential_value,
                expires_at=expires_at,
            )
            self.session.add(cred)
        self.session.flush()
        return cred

    def delete_credential(self, provider_id: int, credential_type: str) -> bool:
        """Delete a specific credential. Returns True if deleted."""
        deleted = (
            self.session.query(ProviderCredential)
            .filter_by(provider_id=provider_id, credential_type=credential_type)
            .delete()
        )
        self.session.flush()
        return deleted > 0

    # ==================================================================
    # ProviderHealthLog — append + query
    # ==================================================================

    def log_health(
        self,
        provider_id: int,
        status: str,
        *,
        latency_ms: float = None,
        error_message: str = None,
    ) -> ProviderHealthLog:
        """Append a health-check entry."""
        entry = ProviderHealthLog(
            provider_id=provider_id,
            status=status,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def get_recent_health(
        self, provider_id: int, limit: int = 50
    ) -> List[ProviderHealthLog]:
        """Get most recent health entries for a provider."""
        return (
            self.session.query(ProviderHealthLog)
            .filter_by(provider_id=provider_id)
            .order_by(desc(ProviderHealthLog.recorded_at))
            .limit(limit)
            .all()
        )

    def get_latest_health(self, provider_id: int) -> Optional[ProviderHealthLog]:
        """Get the single most recent health entry."""
        return (
            self.session.query(ProviderHealthLog)
            .filter_by(provider_id=provider_id)
            .order_by(desc(ProviderHealthLog.recorded_at))
            .first()
        )

    def cleanup_health_log(self, days: int = 30) -> int:
        """Delete health entries older than *days*."""
        cutoff = datetime.now() - timedelta(days=days)
        deleted = (
            self.session.query(ProviderHealthLog)
            .filter(ProviderHealthLog.recorded_at < cutoff)
            .delete(synchronize_session=False)
        )
        self.session.flush()
        return deleted
