"""
CANSLIM Monitor - Integrations Package
External service integrations for market data and alerts.

Note: Using lazy imports to avoid asyncio issues with ib_insync on Python 3.14+
"""

# Lazy imports - only loaded when accessed
def __getattr__(name):
    """Lazy import handler."""
    if name in ('IBKRClient', 'get_ibkr_client', 'init_ibkr_client', 'IB_AVAILABLE'):
        from canslim_monitor.integrations.ibkr_client import (
            IBKRClient,
            get_ibkr_client,
            init_ibkr_client,
            IB_AVAILABLE,
        )
        return locals()[name]
    
    if name == 'ThreadSafeIBKRClient':
        from canslim_monitor.integrations.ibkr_client_threadsafe import ThreadSafeIBKRClient
        return ThreadSafeIBKRClient
    
    if name in ('DiscordNotifier', 'AlertChannel', 'get_discord_notifier', 'init_discord_notifier'):
        from canslim_monitor.integrations.discord_notifier import (
            DiscordNotifier,
            AlertChannel,
            get_discord_notifier,
            init_discord_notifier,
        )
        return locals()[name]
    
    if name == 'PolygonClient':
        from canslim_monitor.integrations.polygon_client import PolygonClient
        return PolygonClient
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # IBKR
    'IBKRClient',
    'ThreadSafeIBKRClient',
    'get_ibkr_client',
    'init_ibkr_client',
    'IB_AVAILABLE',
    # Discord
    'DiscordNotifier',
    'AlertChannel',
    'get_discord_notifier',
    'init_discord_notifier',
    # Polygon
    'PolygonClient',
]
