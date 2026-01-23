"""
CANSLIM Monitor - Configuration Loader
Handles loading and merging configuration from YAML files.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger('config')


# Default configuration (used if no config file found)
DEFAULT_CONFIG = {
    'ibkr': {
        'host': '127.0.0.1',
        'port': 7497,  # TWS paper trading
        'client_id_base': 10,
        'timeout': 30,
        'max_retries': 3,
    },
    'service': {
        'poll_intervals': {
            'breakout': 60,
            'position': 30,
            'market': 300,
        },
        'market_hours_only': True,
        'price_update_interval': 5,  # seconds
    },
    'database': {
        'path': 'canslim_positions.db',
    },
    'discord': {
        'webhooks': {},
        'rate_limit': 30,
    },
}

# Client ID offsets for each connection type
CLIENT_ID_OFFSETS = {
    'gui': 0,
    'breakout': 1,
    'position': 2,
    'market': 3,
    'backup': 4,  # For additional connections
}

_loaded_config: Optional[Dict[str, Any]] = None


def deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


def _get_search_paths() -> List[Path]:
    """
    Build the list of paths to search for config files.
    
    Priority order:
    1. Command line argument (handled in load_config)
    2. canslim_monitor/user_config.yaml (user overrides)
    3. canslim_monitor/config/config.yaml (default)
    """
    pkg_dir = Path(__file__).parent.parent  # canslim_monitor/
    
    return [
        pkg_dir / 'user_config.yaml',           # User overrides
        pkg_dir / 'config' / 'config.yaml',     # Default config
    ]


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from YAML file.
    
    Priority order:
    1. config_path argument (from command line -c)
    2. canslim_monitor/user_config.yaml
    3. canslim_monitor/config/config.yaml
    
    Args:
        config_path: Optional explicit path to config file
        
    Returns:
        Configuration dictionary
    """
    global _loaded_config
    
    # If already loaded and no explicit path, return cached
    if _loaded_config is not None and config_path is None:
        return _loaded_config
    
    config = deep_merge({}, DEFAULT_CONFIG)  # Start with defaults
    
    # Build search paths in priority order
    search_paths = []
    
    # Priority 1: Explicit path from command line
    if config_path:
        explicit = Path(config_path)
        if explicit.is_absolute():
            search_paths.append(explicit)
        else:
            # Try relative to cwd first, then as-is
            search_paths.append(Path.cwd() / config_path)
            search_paths.append(explicit)
    
    # Priority 2 & 3: Standard locations
    search_paths.extend(_get_search_paths())
    
    # Find first existing config file
    config_file = None
    for path in search_paths:
        if path.exists():
            config_file = path
            break
    
    if config_file:
        try:
            import yaml
            with open(config_file, 'r') as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    config = deep_merge(config, file_config)
            logger.info(f"Loaded config from: {config_file}")
        except ImportError:
            logger.warning("PyYAML not installed, using default config")
        except Exception as e:
            logger.error(f"Error loading config from {config_file}: {e}")
    else:
        logger.warning("No config file found, using defaults")
        logger.info("Searched: " + ", ".join(str(p) for p in search_paths))
    
    _loaded_config = config
    return config


def get_config() -> Dict[str, Any]:
    """Get the loaded configuration."""
    if _loaded_config is None:
        return load_config()
    return _loaded_config


def get_ibkr_config() -> Dict[str, Any]:
    """Get IBKR-specific configuration."""
    config = get_config()
    return config.get('ibkr', DEFAULT_CONFIG['ibkr'])


def get_ibkr_client_id(connection_type: str = 'gui') -> int:
    """
    Get the client ID for a specific connection type.
    
    Args:
        connection_type: Type of connection ('gui', 'breakout', 'position', 'market', 'backup')
        
    Returns:
        Unique client ID for this connection type
    """
    ibkr_config = get_ibkr_config()
    base_id = ibkr_config.get('client_id_base', ibkr_config.get('client_id', 10))
    offset = CLIENT_ID_OFFSETS.get(connection_type, 0)
    return base_id + offset


def get_service_config() -> Dict[str, Any]:
    """Get service-specific configuration."""
    config = get_config()
    return config.get('service', DEFAULT_CONFIG['service'])


def get_discord_config() -> Dict[str, Any]:
    """Get Discord-specific configuration."""
    config = get_config()
    return config.get('discord', DEFAULT_CONFIG['discord'])
