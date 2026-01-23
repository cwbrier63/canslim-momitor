#!/usr/bin/env python3
"""
CANSLIM Monitor - CLI Demo Tool
Phase 2: Service Architecture Testing

Run the monitoring logic interactively without the Windows service.
Tests all thread logic with mock or real price data.

Usage:
    python demo.py                    # Full interactive demo (mock data)
    python demo.py breakout           # Test breakout detection
    python demo.py positions          # Test position monitoring  
    python demo.py market             # Test market regime
    python demo.py seed               # Seed test data
    python demo.py status             # Show database status
    
Live Mode (requires TWS running):
    python demo.py --live             # Use real IBKR data
    python demo.py breakout --live    # Live breakout check
    python demo.py --live --discord   # Send alerts to Discord
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import random
import yaml

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data import init_database, DatabaseManager
from canslim_monitor.data.repositories import RepositoryManager


# ==================== CONFIG LOADER ====================

def load_config(config_path: str = None) -> Dict:
    """
    Load configuration from YAML file.
    
    Searches for config in order:
    1. Provided path
    2. user_config.yaml (user overrides)
    3. config/default_config.yaml
    """
    base_dir = Path(__file__).parent
    
    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    
    search_paths.extend([
        base_dir / 'user_config.yaml',
        base_dir / 'config' / 'user_config.yaml',
        base_dir / 'config' / 'default_config.yaml',
    ])
    
    for path in search_paths:
        if path.exists():
            try:
                with open(path, 'r') as f:
                    config = yaml.safe_load(f)
                    config['_config_path'] = str(path)
                    return config
            except Exception as e:
                print(f"Warning: Failed to load {path}: {e}")
    
    # Return defaults if no config found
    return {
        'ibkr': {
            'host': '127.0.0.1',
            'port': 7497,
            'client_id': 10,
        },
        'discord': {
            'webhooks': {}
        },
        'database': {
            'path': 'canslim_monitor.db'
        },
        'polygon': {
            'api_key': ''
        },
        '_config_path': None
    }


# ==================== ANSI COLORS ====================

class Colors:
    """ANSI color codes for terminal output."""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # Colors
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    
    # Background
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    
    @classmethod
    def disable(cls):
        """Disable colors (for non-ANSI terminals)."""
        for attr in dir(cls):
            if not attr.startswith('_') and attr.isupper():
                setattr(cls, attr, '')


# ==================== MOCK DATA GENERATOR ====================

class MockPriceGenerator:
    """Generate realistic mock price data for testing."""
    
    def __init__(self, seed: int = None):
        if seed:
            random.seed(seed)
    
    def get_quote(self, symbol: str, pivot: float = None, scenario: str = 'random') -> Dict:
        """
        Generate mock quote data.
        
        Scenarios:
        - 'breakout': Price above pivot with high volume
        - 'breakdown': Price below pivot
        - 'buy_zone': Price 0-5% above pivot
        - 'extended': Price >5% above pivot
        - 'random': Random scenario
        """
        base_price = pivot or random.uniform(50, 500)
        
        if scenario == 'random':
            scenario = random.choice(['breakout', 'breakdown', 'buy_zone', 'extended', 'consolidating'])
        
        if scenario == 'breakout':
            price = base_price * random.uniform(1.01, 1.03)
            volume_ratio = random.uniform(1.3, 2.5)
        elif scenario == 'breakdown':
            price = base_price * random.uniform(0.92, 0.98)
            volume_ratio = random.uniform(0.8, 1.2)
        elif scenario == 'buy_zone':
            price = base_price * random.uniform(1.00, 1.05)
            volume_ratio = random.uniform(1.0, 1.5)
        elif scenario == 'extended':
            price = base_price * random.uniform(1.06, 1.15)
            volume_ratio = random.uniform(0.8, 1.2)
        else:  # consolidating
            price = base_price * random.uniform(0.98, 1.02)
            volume_ratio = random.uniform(0.6, 1.0)
        
        avg_volume = random.randint(500_000, 5_000_000)
        
        return {
            'symbol': symbol,
            'last': round(price, 2),
            'bid': round(price - 0.02, 2),
            'ask': round(price + 0.02, 2),
            'volume': int(avg_volume * volume_ratio),
            'avg_volume': avg_volume,
            'volume_ratio': round(volume_ratio, 2),
            'prev_close': round(price * random.uniform(0.97, 1.03), 2),
            'open': round(price * random.uniform(0.99, 1.01), 2),
            'high': round(price * random.uniform(1.00, 1.02), 2),
            'low': round(price * random.uniform(0.98, 1.00), 2),
            'spread_pct': round(random.uniform(0.01, 0.15), 3),
            'ma21': round(price * random.uniform(0.95, 1.02), 2),
            'ma50': round(price * random.uniform(0.90, 1.00), 2),
            'ma200': round(price * random.uniform(0.80, 0.95), 2),
        }
    
    def get_position_quote(self, symbol: str, avg_cost: float, scenario: str = 'random') -> Dict:
        """Generate quote for position monitoring scenarios."""
        if scenario == 'random':
            scenario = random.choice([
                'profitable', 'at_stop', 'near_tp1', 'at_tp2',
                'pullback_21ema', 'below_50ma', 'healthy'
            ])
        
        if scenario == 'profitable':
            price = avg_cost * random.uniform(1.05, 1.15)
        elif scenario == 'at_stop':
            price = avg_cost * random.uniform(0.92, 0.94)
        elif scenario == 'near_tp1':
            price = avg_cost * random.uniform(1.18, 1.22)
        elif scenario == 'at_tp2':
            price = avg_cost * random.uniform(1.23, 1.27)
        elif scenario == 'pullback_21ema':
            price = avg_cost * random.uniform(1.08, 1.12)
            ma21 = price * 0.99  # Price near 21 EMA
        elif scenario == 'below_50ma':
            price = avg_cost * random.uniform(1.00, 1.05)
        else:  # healthy
            price = avg_cost * random.uniform(1.10, 1.20)
        
        quote = self.get_quote(symbol, pivot=avg_cost)
        quote['last'] = round(price, 2)
        
        # Adjust MAs for scenario
        if scenario == 'pullback_21ema':
            quote['ma21'] = round(price * 0.99, 2)
        elif scenario == 'below_50ma':
            quote['ma50'] = round(price * 1.02, 2)
        else:
            quote['ma21'] = round(price * random.uniform(0.96, 0.99), 2)
            quote['ma50'] = round(price * random.uniform(0.90, 0.96), 2)
        
        return quote
    
    def get_index_quote(self, symbol: str, scenario: str = 'random') -> Dict:
        """Generate index quote for market regime testing."""
        base_prices = {'SPY': 590, 'QQQ': 510, 'DIA': 430}
        base = base_prices.get(symbol, 500)
        
        if scenario == 'random':
            scenario = random.choice(['bullish', 'bearish', 'distribution', 'ftd', 'neutral'])
        
        if scenario == 'bullish':
            change_pct = random.uniform(0.5, 1.5)
            volume_ratio = random.uniform(0.9, 1.2)
        elif scenario == 'bearish':
            change_pct = random.uniform(-1.5, -0.5)
            volume_ratio = random.uniform(0.9, 1.2)
        elif scenario == 'distribution':
            change_pct = random.uniform(-0.5, -0.2)
            volume_ratio = random.uniform(1.1, 1.5)
        elif scenario == 'ftd':
            change_pct = random.uniform(1.3, 2.0)
            volume_ratio = random.uniform(1.2, 1.8)
        else:  # neutral
            change_pct = random.uniform(-0.3, 0.3)
            volume_ratio = random.uniform(0.8, 1.1)
        
        prev_close = base
        price = base * (1 + change_pct / 100)
        avg_volume = 80_000_000 if symbol == 'SPY' else 50_000_000
        
        return {
            'symbol': symbol,
            'last': round(price, 2),
            'prev_close': round(prev_close, 2),
            'change_pct': round(change_pct, 2),
            'volume': int(avg_volume * volume_ratio),
            'prev_volume': avg_volume,
            'volume_ratio': round(volume_ratio, 2),
            'ma50': round(base * 0.98, 2),
            'ma200': round(base * 0.92, 2),
        }


# ==================== ALERT FORMATTERS ====================

class AlertFormatter:
    """Format alerts for console output."""
    
    EMOJI = {
        'breakout': '🚀',
        'breakdown': '🔻',
        'buy_zone': '✅',
        'watch': '👀',
        'stop': '🛑',
        'warning': '⚠️',
        'profit': '💰',
        'pyramid': '📈',
        'health': '❤️',
        'market': '📊',
    }
    
    @classmethod
    def breakout_alert(cls, symbol: str, price: float, pivot: float, 
                       grade: str, score: int, volume_ratio: float) -> str:
        """Format breakout alert."""
        pct_above = ((price - pivot) / pivot) * 100
        
        lines = [
            f"{Colors.GREEN}{Colors.BOLD}{cls.EMOJI['breakout']} BREAKOUT: {symbol}{Colors.RESET}",
            f"   Price: ${price:.2f} | Pivot: ${pivot:.2f} ({pct_above:+.1f}%)",
            f"   Volume: {volume_ratio:.0%} of average",
            f"   Grade: {cls._grade_color(grade)}{grade}{Colors.RESET} | Score: {score}",
        ]
        return '\n'.join(lines)
    
    @classmethod
    def buy_zone_alert(cls, symbol: str, price: float, pivot: float,
                       grade: str, score: int) -> str:
        """Format buy zone alert."""
        pct_above = ((price - pivot) / pivot) * 100
        
        lines = [
            f"{Colors.CYAN}{cls.EMOJI['buy_zone']} IN BUY ZONE: {symbol}{Colors.RESET}",
            f"   Price: ${price:.2f} | Pivot: ${pivot:.2f} ({pct_above:+.1f}%)",
            f"   Grade: {cls._grade_color(grade)}{grade}{Colors.RESET} | Score: {score}",
        ]
        return '\n'.join(lines)
    
    @classmethod
    def extended_alert(cls, symbol: str, price: float, pivot: float) -> str:
        """Format extended/chase alert."""
        pct_above = ((price - pivot) / pivot) * 100
        
        lines = [
            f"{Colors.YELLOW}{cls.EMOJI['warning']} EXTENDED: {symbol}{Colors.RESET}",
            f"   Price: ${price:.2f} | Pivot: ${pivot:.2f} ({pct_above:+.1f}%)",
            f"   {Colors.DIM}Consider waiting for pullback{Colors.RESET}",
        ]
        return '\n'.join(lines)
    
    @classmethod
    def stop_alert(cls, symbol: str, price: float, stop: float, 
                   avg_cost: float, alert_type: str = 'warning') -> str:
        """Format stop alert."""
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        to_stop_pct = ((price - stop) / price) * 100
        
        if alert_type == 'hit':
            emoji = cls.EMOJI['stop']
            color = Colors.RED
            title = "STOP HIT"
        else:
            emoji = cls.EMOJI['warning']
            color = Colors.YELLOW
            title = "STOP WARNING"
        
        lines = [
            f"{color}{emoji} {title}: {symbol}{Colors.RESET}",
            f"   Price: ${price:.2f} | Stop: ${stop:.2f} ({to_stop_pct:.1f}% away)",
            f"   P&L: {pnl_pct:+.1f}% | Avg Cost: ${avg_cost:.2f}",
        ]
        return '\n'.join(lines)
    
    @classmethod
    def profit_alert(cls, symbol: str, price: float, target: float,
                     avg_cost: float, target_name: str) -> str:
        """Format profit target alert."""
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        
        lines = [
            f"{Colors.GREEN}{cls.EMOJI['profit']} {target_name} REACHED: {symbol}{Colors.RESET}",
            f"   Price: ${price:.2f} | Target: ${target:.2f}",
            f"   P&L: {Colors.GREEN}{pnl_pct:+.1f}%{Colors.RESET}",
        ]
        return '\n'.join(lines)
    
    @classmethod
    def health_alert(cls, symbol: str, score: int, rating: str,
                     price: float, avg_cost: float) -> str:
        """Format position health alert."""
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        
        if score >= 70:
            color = Colors.GREEN
        elif score >= 50:
            color = Colors.YELLOW
        else:
            color = Colors.RED
        
        lines = [
            f"{color}{cls.EMOJI['health']} HEALTH CHECK: {symbol}{Colors.RESET}",
            f"   Score: {color}{score}/100 ({rating}){Colors.RESET}",
            f"   P&L: {pnl_pct:+.1f}% | Price: ${price:.2f}",
        ]
        return '\n'.join(lines)
    
    @classmethod
    def market_regime_alert(cls, regime: str, score: int, exposure: int,
                            spy_data: Dict, qqq_data: Dict) -> str:
        """Format market regime alert."""
        if regime == 'BULLISH':
            color = Colors.GREEN
        elif regime == 'BEARISH':
            color = Colors.RED
        else:
            color = Colors.YELLOW
        
        lines = [
            f"{color}{cls.EMOJI['market']} MARKET REGIME: {regime}{Colors.RESET}",
            f"   Score: {score:+d} | Recommended Exposure: {exposure}/5",
            f"   SPY: ${spy_data['last']:.2f} ({spy_data['change_pct']:+.2f}%)",
            f"   QQQ: ${qqq_data['last']:.2f} ({qqq_data['change_pct']:+.2f}%)",
        ]
        return '\n'.join(lines)
    
    @classmethod
    def distribution_day_alert(cls, symbol: str, change_pct: float, 
                               volume_ratio: float, total_dist_days: int) -> str:
        """Format distribution day alert."""
        lines = [
            f"{Colors.RED}{cls.EMOJI['warning']} DISTRIBUTION DAY: {symbol}{Colors.RESET}",
            f"   Change: {change_pct:.2f}% | Volume: {volume_ratio:.0%} of prev",
            f"   Total Distribution Days: {total_dist_days}",
        ]
        return '\n'.join(lines)
    
    @staticmethod
    def _grade_color(grade: str) -> str:
        """Get color for grade."""
        if grade.startswith('A'):
            return Colors.GREEN
        elif grade.startswith('B'):
            return Colors.CYAN
        elif grade.startswith('C'):
            return Colors.YELLOW
        else:
            return Colors.RED


# ==================== SCORING ENGINE (SIMPLIFIED) ====================

class DemoScoringEngine:
    """Simplified scoring for demo purposes."""
    
    @staticmethod
    def score_breakout(rs_rating: int, volume_ratio: float, 
                       market_regime: str = 'NEUTRAL') -> Dict:
        """Score a breakout setup."""
        score = 0
        details = []
        
        # RS Rating (max 10 points)
        if rs_rating >= 95:
            score += 10
            details.append(f"RS {rs_rating}: +10 (elite)")
        elif rs_rating >= 90:
            score += 8
            details.append(f"RS {rs_rating}: +8 (strong)")
        elif rs_rating >= 80:
            score += 5
            details.append(f"RS {rs_rating}: +5 (good)")
        elif rs_rating >= 70:
            score += 2
            details.append(f"RS {rs_rating}: +2 (acceptable)")
        else:
            details.append(f"RS {rs_rating}: +0 (weak)")
        
        # Volume (max 5 points)
        if volume_ratio >= 2.0:
            score += 5
            details.append(f"Volume {volume_ratio:.0%}: +5 (exceptional)")
        elif volume_ratio >= 1.5:
            score += 4
            details.append(f"Volume {volume_ratio:.0%}: +4 (strong)")
        elif volume_ratio >= 1.25:
            score += 2
            details.append(f"Volume {volume_ratio:.0%}: +2 (confirming)")
        else:
            details.append(f"Volume {volume_ratio:.0%}: +0 (weak)")
        
        # Market regime (max 5 points)
        if market_regime == 'BULLISH':
            score += 5
            details.append("Market BULLISH: +5")
        elif market_regime == 'NEUTRAL':
            score += 2
            details.append("Market NEUTRAL: +2")
        else:
            details.append("Market BEARISH: +0")
        
        # Determine grade
        if score >= 18:
            grade = 'A+'
        elif score >= 15:
            grade = 'A'
        elif score >= 12:
            grade = 'B+'
        elif score >= 10:
            grade = 'B'
        elif score >= 7:
            grade = 'C+'
        else:
            grade = 'C'
        
        # RS floor rule
        if rs_rating < 70:
            grade = 'C'
            details.append("RS < 70: Grade capped at C")
        
        return {
            'grade': grade,
            'score': score,
            'max_score': 20,
            'details': details
        }
    
    @staticmethod
    def calculate_health(price: float, avg_cost: float, ma21: float,
                         ma50: float, volume_ratio: float, rs_rating: int) -> Dict:
        """Calculate position health score."""
        score = 0
        details = []
        
        # P&L component (40 points max)
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        if pnl_pct >= 20:
            score += 40
            details.append(f"P&L {pnl_pct:+.1f}%: +40")
        elif pnl_pct >= 10:
            score += 30
            details.append(f"P&L {pnl_pct:+.1f}%: +30")
        elif pnl_pct >= 5:
            score += 20
            details.append(f"P&L {pnl_pct:+.1f}%: +20")
        elif pnl_pct >= 0:
            score += 10
            details.append(f"P&L {pnl_pct:+.1f}%: +10")
        else:
            details.append(f"P&L {pnl_pct:+.1f}%: +0")
        
        # MA position (30 points max)
        if price > ma21 > ma50:
            score += 30
            details.append("Above 21 & 50 MA: +30")
        elif price > ma50:
            score += 20
            details.append("Above 50 MA: +20")
        elif price > ma21:
            score += 10
            details.append("Above 21 MA only: +10")
        else:
            details.append("Below MAs: +0")
        
        # Volume (15 points max)
        if volume_ratio >= 1.0:
            score += 15
            details.append(f"Volume {volume_ratio:.0%}: +15")
        elif volume_ratio >= 0.7:
            score += 8
            details.append(f"Volume {volume_ratio:.0%}: +8")
        else:
            details.append(f"Volume {volume_ratio:.0%}: +0")
        
        # RS Rating (15 points max)
        if rs_rating >= 80:
            score += 15
            details.append(f"RS {rs_rating}: +15")
        elif rs_rating >= 70:
            score += 10
            details.append(f"RS {rs_rating}: +10")
        else:
            score += 5
            details.append(f"RS {rs_rating}: +5")
        
        # Rating
        if score >= 80:
            rating = 'EXCELLENT'
        elif score >= 60:
            rating = 'GOOD'
        elif score >= 40:
            rating = 'FAIR'
        else:
            rating = 'POOR'
        
        return {
            'score': score,
            'rating': rating,
            'pnl_pct': pnl_pct,
            'details': details
        }


# ==================== DEMO RUNNER ====================

class LiveDataProvider:
    """Provides live data from IBKR."""
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 10):
        self.host = host
        self.port = port
        self.client_id = client_id
        self._client = None
        self._connected = False
    
    def connect(self) -> bool:
        """Connect to IBKR TWS."""
        try:
            from integrations import init_ibkr_client, IB_AVAILABLE
            
            if not IB_AVAILABLE:
                print(f"{Colors.RED}ib_insync not installed. Run: pip install ib_insync{Colors.RESET}")
                return False
            
            print(f"{Colors.CYAN}Connecting to TWS at {self.host}:{self.port} (client_id={self.client_id})...{Colors.RESET}")
            self._client = init_ibkr_client(
                host=self.host,
                port=self.port,
                client_id=self.client_id,
                auto_connect=True
            )
            
            if self._client.is_connected():
                self._connected = True
                print(f"{Colors.GREEN}Connected to IBKR!{Colors.RESET}")
                return True
            else:
                print(f"{Colors.RED}Failed to connect to TWS{Colors.RESET}")
                return False
                
        except Exception as e:
            print(f"{Colors.RED}IBKR connection error: {e}{Colors.RESET}")
            return False
    
    def disconnect(self):
        """Disconnect from IBKR."""
        if self._client:
            self._client.disconnect()
            self._connected = False
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected and self._client and self._client.is_connected()
    
    def get_quote(self, symbol: str, pivot: float = None, scenario: str = None) -> Optional[Dict]:
        """Get live quote from IBKR."""
        if not self.is_connected():
            return None
        
        quote = self._client.get_quote_with_technicals(symbol)
        if quote:
            # Add volume_ratio if not present
            if 'volume_ratio' not in quote and quote.get('volume') and quote.get('avg_volume'):
                quote['volume_ratio'] = quote['volume'] / quote['avg_volume']
            elif 'volume_ratio' not in quote:
                quote['volume_ratio'] = 1.0
        
        return quote
    
    def get_position_quote(self, symbol: str, avg_cost: float, scenario: str = None) -> Optional[Dict]:
        """Get live quote for position."""
        return self.get_quote(symbol)
    
    def get_index_quote(self, symbol: str, scenario: str = None) -> Optional[Dict]:
        """Get live index quote."""
        if not self.is_connected():
            return None
        
        quote = self._client.get_index_quote(symbol)
        if quote and 'change_pct' not in quote:
            if quote.get('last') and quote.get('prev_close'):
                change = quote['last'] - quote['prev_close']
                quote['change_pct'] = (change / quote['prev_close']) * 100
        
        return quote


class DemoRunner:
    """Main demo runner class."""
    
    def __init__(
        self,
        config: Dict = None,
        db_path: str = None,
        live_mode: bool = False,
        discord_enabled: bool = False,
        discord_webhook: str = None,
        ibkr_host: str = None,
        ibkr_port: int = None,
        ibkr_client_id: int = None
    ):
        # Load config if not provided
        self.config = config or load_config()
        
        # Database path (CLI override > config > default)
        self.db_path = db_path or self.config.get('database', {}).get('path', 'canslim_monitor.db')
        
        # IBKR settings (CLI override > config > default)
        ibkr_config = self.config.get('ibkr', {})
        self.ibkr_host = ibkr_host or ibkr_config.get('host', '127.0.0.1')
        self.ibkr_port = ibkr_port or ibkr_config.get('port', 7497)
        self.ibkr_client_id = ibkr_client_id or ibkr_config.get('client_id', 10)
        
        # Discord settings (CLI override > config)
        discord_config = self.config.get('discord', {})
        self.discord_enabled = discord_enabled
        
        # Use CLI webhook, or get default from config
        if discord_webhook:
            self.discord_webhook = discord_webhook
        else:
            webhooks = discord_config.get('webhooks', {})
            # Use breakout webhook as default, or first non-empty webhook
            self.discord_webhook = webhooks.get('breakout') or next(
                (v for v in webhooks.values() if v), None
            )
        
        self.live_mode = live_mode
        self.db: Optional[DatabaseManager] = None
        
        # Show config source
        config_path = self.config.get('_config_path')
        if config_path:
            print(f"{Colors.DIM}Config: {config_path}{Colors.RESET}")
        
        # Data provider (mock or live)
        if live_mode:
            self.data_provider = LiveDataProvider(
                host=self.ibkr_host,
                port=self.ibkr_port,
                client_id=self.ibkr_client_id
            )
        else:
            self.data_provider = MockPriceGenerator(seed=42)
        
        # Discord notifier
        self.discord = None
        if self.discord_enabled:
            if self.discord_webhook:
                try:
                    from integrations import init_discord_notifier
                    
                    # Get all webhooks from config
                    webhooks = discord_config.get('webhooks', {})
                    
                    self.discord = init_discord_notifier(
                        webhooks=webhooks if any(webhooks.values()) else None,
                        default_webhook=self.discord_webhook,
                        enabled=True
                    )
                    print(f"{Colors.GREEN}Discord notifications enabled{Colors.RESET}")
                except Exception as e:
                    print(f"{Colors.YELLOW}Discord init failed: {e}{Colors.RESET}")
            else:
                print(f"{Colors.YELLOW}Discord enabled but no webhook configured{Colors.RESET}")
        
        self.scoring = DemoScoringEngine()
        self.formatter = AlertFormatter()
    
    def _init_db(self):
        """Initialize database connection."""
        if self.db is None:
            self.db = init_database(db_path=self.db_path)
        return self.db
    
    def _init_live(self) -> bool:
        """Initialize live data connection if in live mode."""
        if self.live_mode and isinstance(self.data_provider, LiveDataProvider):
            if not self.data_provider.is_connected():
                return self.data_provider.connect()
            return True
        return True
    
    def _cleanup_live(self):
        """Cleanup live connections."""
        if self.live_mode and isinstance(self.data_provider, LiveDataProvider):
            self.data_provider.disconnect()
    
    def _print_header(self, title: str):
        """Print section header."""
        width = 60
        print()
        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * width}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.BLUE}{title.center(width)}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * width}{Colors.RESET}")
        print()
    
    def _print_subheader(self, title: str):
        """Print subsection header."""
        print(f"\n{Colors.CYAN}--- {title} ---{Colors.RESET}\n")
    
    def run_status(self):
        """Show database status."""
        self._print_header("DATABASE STATUS")
        
        db = self._init_db()
        session = db.get_new_session()
        repos = RepositoryManager(session)
        
        # Count positions by state
        all_positions = repos.positions.get_all()
        state_counts = {}
        for pos in all_positions:
            state = pos.state
            state_counts[state] = state_counts.get(state, 0) + 1
        
        state_names = {0: 'Watching', 1: 'Active', 2: 'Scaling', 3: 'Exiting', 4: 'Closed'}
        
        print(f"Database: {self.db_path}")
        print(f"Total Positions: {len(all_positions)}")
        print()
        
        for state, count in sorted(state_counts.items()):
            name = state_names.get(state, f'State {state}')
            print(f"  {name}: {count}")
        
        if all_positions:
            print(f"\n{Colors.DIM}Recent positions:{Colors.RESET}")
            for pos in all_positions[:5]:
                state_name = state_names.get(pos.state, '?')
                print(f"  {pos.symbol} ({state_name}) - Pivot: ${pos.pivot or 0:.2f}, RS: {pos.rs_rating or 0}")
        
        session.close()
    
    def run_breakout_demo(self, scenarios: List[str] = None):
        """Demo breakout detection."""
        self._print_header("BREAKOUT DETECTION DEMO")
        
        # Initialize live connection if needed
        if self.live_mode:
            if not self._init_live():
                print(f"{Colors.RED}Failed to connect to IBKR. Run with mock data instead.{Colors.RESET}")
                return
            print(f"{Colors.GREEN}Using LIVE data from IBKR{Colors.RESET}\n")
        else:
            print(f"{Colors.DIM}Using MOCK data (use --live for real prices){Colors.RESET}\n")
        
        db = self._init_db()
        session = db.get_new_session()
        repos = RepositoryManager(session)
        
        # Get watching positions
        positions = repos.positions.get_by_state(0)
        
        if not positions:
            print(f"{Colors.YELLOW}No watching positions (State 0) found.{Colors.RESET}")
            print("Run 'python demo.py seed' to add test data.")
            session.close()
            return
        
        print(f"Checking {len(positions)} watching positions...\n")
        
        scenarios = scenarios or ['breakout', 'buy_zone', 'extended', 'consolidating', 'breakdown']
        
        for i, pos in enumerate(positions):
            scenario = scenarios[i % len(scenarios)] if not self.live_mode else None
            
            # Get quote from data provider
            quote = self.data_provider.get_quote(pos.symbol, pivot=pos.pivot, scenario=scenario)
            
            if not quote:
                print(f"{Colors.RED}  Failed to get quote for {pos.symbol}{Colors.RESET}")
                continue
            
            self._print_subheader(f"{pos.symbol}" + (f" (Scenario: {scenario})" if scenario else " (LIVE)"))
            
            print(f"  Pivot: ${pos.pivot:.2f} | RS Rating: {pos.rs_rating}")
            print(f"  Price: ${quote['last']:.2f} | Volume: {quote.get('volume_ratio', 1.0):.0%} avg")
            print()
            
            # Calculate breakout status
            price = quote['last']
            pivot = pos.pivot
            pct_above = ((price - pivot) / pivot) * 100
            volume_ratio = quote.get('volume_ratio', 1.0)
            
            # Score the setup
            score_result = self.scoring.score_breakout(
                rs_rating=pos.rs_rating or 80,
                volume_ratio=volume_ratio,
                market_regime='BULLISH'
            )
            
            # Determine alert type and display
            if price > pivot:
                if pct_above <= 5:
                    if volume_ratio >= 1.25:
                        print(self.formatter.breakout_alert(
                            pos.symbol, price, pivot,
                            score_result['grade'], score_result['score'],
                            volume_ratio
                        ))
                        # Send Discord alert
                        if self.discord:
                            self.discord.send_breakout_alert(
                                pos.symbol, price, pivot,
                                score_result['grade'], score_result['score'],
                                volume_ratio, pos.rs_rating, pos.portfolio
                            )
                    else:
                        print(self.formatter.buy_zone_alert(
                            pos.symbol, price, pivot,
                            score_result['grade'], score_result['score']
                        ))
                        if self.discord:
                            self.discord.send_buy_zone_alert(
                                pos.symbol, price, pivot,
                                score_result['grade'], score_result['score'],
                                pos.rs_rating
                            )
                else:
                    print(self.formatter.extended_alert(pos.symbol, price, pivot))
                    if self.discord:
                        self.discord.send_extended_alert(pos.symbol, price, pivot)
            else:
                print(f"{Colors.DIM}  No breakout - price below pivot ({pct_above:+.1f}%){Colors.RESET}")
            
            # Show scoring details
            print(f"\n  {Colors.DIM}Scoring breakdown:{Colors.RESET}")
            for detail in score_result['details']:
                print(f"    {Colors.DIM}{detail}{Colors.RESET}")
            
            print()
        
        session.close()
    
    def run_position_demo(self, scenarios: List[str] = None):
        """Demo position monitoring."""
        self._print_header("POSITION MONITORING DEMO")
        
        # Initialize live connection if needed
        if self.live_mode:
            if not self._init_live():
                print(f"{Colors.RED}Failed to connect to IBKR. Run with mock data instead.{Colors.RESET}")
                return
            print(f"{Colors.GREEN}Using LIVE data from IBKR{Colors.RESET}\n")
        else:
            print(f"{Colors.DIM}Using MOCK data (use --live for real prices){Colors.RESET}\n")
        
        db = self._init_db()
        session = db.get_new_session()
        repos = RepositoryManager(session)
        
        # Get active positions (state >= 1)
        all_positions = repos.positions.get_all()
        positions = [p for p in all_positions if p.state >= 1]
        
        if not positions:
            print(f"{Colors.YELLOW}No active positions (State 1+) found.{Colors.RESET}")
            print("Run 'python demo.py seed' to add test data.")
            session.close()
            return
        
        print(f"Monitoring {len(positions)} active positions...\n")
        
        scenarios = scenarios or ['profitable', 'at_stop', 'near_tp1', 'pullback_21ema', 'healthy']
        
        for i, pos in enumerate(positions):
            scenario = scenarios[i % len(scenarios)] if not self.live_mode else None
            avg_cost = pos.avg_cost or pos.pivot or 100
            
            # Get quote from data provider
            quote = self.data_provider.get_position_quote(pos.symbol, avg_cost, scenario=scenario)
            
            if not quote:
                print(f"{Colors.RED}  Failed to get quote for {pos.symbol}{Colors.RESET}")
                continue
            
            state_names = {1: 'Active', 2: 'Scaling', 3: 'Exiting'}
            state_name = state_names.get(pos.state, f'State {pos.state}')
            
            self._print_subheader(f"{pos.symbol} ({state_name})" + (f" - Scenario: {scenario}" if scenario else " - LIVE"))
            
            price = quote['last']
            pnl_pct = ((price - avg_cost) / avg_cost) * 100
            
            ma21 = quote.get('ma21', price * 0.98)
            ma50 = quote.get('ma50', price * 0.95)
            
            print(f"  Avg Cost: ${avg_cost:.2f} | Price: ${price:.2f} | P&L: {pnl_pct:+.1f}%")
            print(f"  RS Rating: {pos.rs_rating} | 21 MA: ${ma21:.2f} | 50 MA: ${ma50:.2f}")
            print()
            
            # Calculate stop and targets
            stop = avg_cost * 0.93  # 7% stop
            tp1 = avg_cost * 1.20   # 20% target
            tp2 = avg_cost * 1.25   # 25% target
            
            # Check for alerts
            alerts_fired = []
            
            # Stop check
            if price <= stop:
                alerts_fired.append(('stop_hit', self.formatter.stop_alert(
                    pos.symbol, price, stop, avg_cost, 'hit'
                )))
                if self.discord:
                    self.discord.send_stop_alert(pos.symbol, price, stop, avg_cost, 'hit')
            elif price <= stop * 1.02:  # Within 2% of stop
                alerts_fired.append(('stop_warning', self.formatter.stop_alert(
                    pos.symbol, price, stop, avg_cost, 'warning'
                )))
                if self.discord:
                    self.discord.send_stop_alert(pos.symbol, price, stop, avg_cost, 'warning')
            
            # Profit target check
            if price >= tp2:
                alerts_fired.append(('tp2', self.formatter.profit_alert(
                    pos.symbol, price, tp2, avg_cost, 'TP2 (25%)'
                )))
                if self.discord:
                    self.discord.send_profit_alert(pos.symbol, price, tp2, avg_cost, 'TP2 (25%)')
            elif price >= tp1:
                alerts_fired.append(('tp1', self.formatter.profit_alert(
                    pos.symbol, price, tp1, avg_cost, 'TP1 (20%)'
                )))
                if self.discord:
                    self.discord.send_profit_alert(pos.symbol, price, tp1, avg_cost, 'TP1 (20%)')
            
            # Health check
            health = self.scoring.calculate_health(
                price, avg_cost, ma21, ma50,
                quote.get('volume_ratio', 1.0), pos.rs_rating or 80
            )
            alerts_fired.append(('health', self.formatter.health_alert(
                pos.symbol, health['score'], health['rating'],
                price, avg_cost
            )))
            
            # Only send health alerts to Discord if score is poor
            if self.discord and health['score'] < 50:
                self.discord.send_health_alert(
                    pos.symbol, health['score'], health['rating'],
                    price, avg_cost
                )
            
            for alert_type, alert_msg in alerts_fired:
                print(alert_msg)
                print()
            
            # Show health details
            print(f"  {Colors.DIM}Health breakdown:{Colors.RESET}")
            for detail in health['details']:
                print(f"    {Colors.DIM}{detail}{Colors.RESET}")
            
            print()
        
        session.close()
    
    def run_market_demo(self, scenario: str = 'random'):
        """Demo market regime detection."""
        self._print_header("MARKET REGIME DEMO")
        
        # Initialize live connection if needed
        if self.live_mode:
            if not self._init_live():
                print(f"{Colors.RED}Failed to connect to IBKR. Run with mock data instead.{Colors.RESET}")
                return
            print(f"{Colors.GREEN}Using LIVE data from IBKR{Colors.RESET}\n")
        else:
            print(f"Scenario: {scenario}\n")
        
        # Get index quotes
        spy = self.data_provider.get_index_quote('SPY', scenario if not self.live_mode else None)
        qqq = self.data_provider.get_index_quote('QQQ', scenario if not self.live_mode else None)
        dia = self.data_provider.get_index_quote('DIA', scenario if not self.live_mode else None)
        
        if not spy or not qqq:
            print(f"{Colors.RED}Failed to get index quotes{Colors.RESET}")
            return
        
        # Ensure change_pct is present
        for idx in [spy, qqq, dia]:
            if idx and 'change_pct' not in idx:
                if idx.get('last') and idx.get('prev_close'):
                    idx['change_pct'] = ((idx['last'] - idx['prev_close']) / idx['prev_close']) * 100
                else:
                    idx['change_pct'] = 0.0
        
        # Generate mock distribution day data based on scenario
        if scenario == 'bullish' or (self.live_mode and random.random() > 0.5):
            spy_dist_days = random.randint(1, 3)
            qqq_dist_days = random.randint(1, 3)
            spy_5day_delta = random.choice([-1, -1, 0])
            qqq_5day_delta = random.choice([-1, 0, 0])
            dist_trend = 'IMPROVING'
            market_phase = 'CONFIRMED_UPTREND'
            ftd_info = "Uptrend intact - buying permitted"
            rally_day = 0
            prior_score = 0.70
            score_direction = 'STABLE'
            # D-day positions (days ago) - spread out for bullish
            spy_dday_positions = [random.randint(10, 24) for _ in range(spy_dist_days)]
            qqq_dday_positions = [random.randint(10, 24) for _ in range(qqq_dist_days)]
        elif scenario == 'bearish':
            spy_dist_days = random.randint(5, 8)
            qqq_dist_days = random.randint(5, 8)
            spy_5day_delta = random.choice([1, 1, 2])
            qqq_5day_delta = random.choice([1, 2, 2])
            dist_trend = 'WORSENING'
            market_phase = 'MARKET_IN_CORRECTION'
            ftd_info = "No active rally - waiting for rally attempt"
            rally_day = 0
            prior_score = 0.30
            score_direction = 'WORSENING'
            # D-day positions - clustered recent for bearish
            spy_dday_positions = [random.randint(0, 15) for _ in range(spy_dist_days)]
            qqq_dday_positions = [random.randint(0, 15) for _ in range(qqq_dist_days)]
        elif scenario == 'distribution':
            spy_dist_days = random.randint(4, 6)
            qqq_dist_days = random.randint(4, 6)
            spy_5day_delta = random.choice([1, 2])
            qqq_5day_delta = random.choice([1, 1])
            dist_trend = 'WORSENING'
            market_phase = 'UPTREND_PRESSURE'
            ftd_info = "Uptrend under pressure - reduce exposure"
            rally_day = 0
            prior_score = 0.55
            score_direction = 'WORSENING'
            spy_dday_positions = [random.randint(0, 20) for _ in range(spy_dist_days)]
            qqq_dday_positions = [random.randint(0, 20) for _ in range(qqq_dist_days)]
        elif scenario == 'ftd':
            spy_dist_days = random.randint(2, 4)
            qqq_dist_days = random.randint(2, 4)
            spy_5day_delta = -1
            qqq_5day_delta = -1
            dist_trend = 'IMPROVING'
            market_phase = 'RALLY_ATTEMPT'
            ftd_info = "Eligible for Follow-Through Day"
            rally_day = random.randint(4, 12)
            prior_score = 0.40
            score_direction = 'IMPROVING'
            spy_dday_positions = [random.randint(8, 24) for _ in range(spy_dist_days)]
            qqq_dday_positions = [random.randint(8, 24) for _ in range(qqq_dist_days)]
        else:  # neutral/random
            spy_dist_days = random.randint(2, 5)
            qqq_dist_days = random.randint(2, 5)
            spy_5day_delta = random.choice([-1, 0, 1])
            qqq_5day_delta = random.choice([-1, 0, 1])
            dist_trend = 'FLAT' if spy_5day_delta == 0 else ('IMPROVING' if spy_5day_delta < 0 else 'WORSENING')
            market_phase = 'CONFIRMED_UPTREND' if max(spy_dist_days, qqq_dist_days) <= 4 else 'UPTREND_PRESSURE'
            ftd_info = "Uptrend intact - buying permitted" if market_phase == 'CONFIRMED_UPTREND' else "Selectivity required"
            rally_day = 0
            prior_score = random.uniform(0.4, 0.8)
            score_direction = 'STABLE'
            spy_dday_positions = [random.randint(0, 24) for _ in range(spy_dist_days)]
            qqq_dday_positions = [random.randint(0, 24) for _ in range(qqq_dist_days)]
        
        # Mock overnight futures
        overnight_futures = {
            'es_change': random.uniform(-0.8, 0.8),
            'nq_change': random.uniform(-1.0, 1.0),
            'ym_change': random.uniform(-0.6, 0.6),
        }
        
        # Display index data
        self._print_subheader("Index Status")
        
        for idx in [spy, qqq, dia]:
            if not idx:
                continue
            color = Colors.GREEN if idx['change_pct'] > 0 else Colors.RED
            ma50 = idx.get('ma50', idx['last'] * 0.98)
            ma200 = idx.get('ma200', idx['last'] * 0.92)
            ma50_status = "✅" if idx['last'] > ma50 else "❌"
            ma200_status = "✅" if idx['last'] > ma200 else "❌"
            
            vol_ratio = idx.get('volume_ratio', 1.0)
            print(f"  {idx['symbol']}: ${idx['last']:.2f} ({color}{idx['change_pct']:+.2f}%{Colors.RESET})")
            print(f"    Volume: {vol_ratio:.0%} of prev | 50 MA: {ma50_status} | 200 MA: {ma200_status}")
            print()
        
        # Distribution day summary
        self._print_subheader("Distribution Day Analysis")
        
        trend_emoji = {'IMPROVING': '🟢', 'WORSENING': '🔴', 'FLAT': '🟡'}.get(dist_trend, '🟡')
        print(f"  SPY: {spy_dist_days} D-days (5-day Δ: {spy_5day_delta:+d})")
        print(f"  QQQ: {qqq_dist_days} D-days (5-day Δ: {qqq_5day_delta:+d})")
        print(f"  Trend: {trend_emoji} {dist_trend}")
        print(f"  Phase: {market_phase.replace('_', ' ').title()}")
        if rally_day > 0:
            print(f"  Rally Day: {rally_day}")
        print()
        
        # Overnight futures
        self._print_subheader("Overnight Futures")
        for sym, key in [('ES', 'es_change'), ('NQ', 'nq_change'), ('YM', 'ym_change')]:
            val = overnight_futures[key]
            color = Colors.GREEN if val > 0.25 else Colors.RED if val < -0.25 else Colors.YELLOW
            print(f"  {sym}: {color}{val:+.2f}%{Colors.RESET}")
        print()
        
        # Calculate regime score (0 to 1.5 scale like your system)
        self._print_subheader("Market Regime")
        
        score = 0.75  # Base score
        
        # MA position scoring
        for idx in [spy, qqq]:
            if not idx:
                continue
            ma50 = idx.get('ma50', idx['last'] * 0.98)
            ma200 = idx.get('ma200', idx['last'] * 0.92)
            if idx['last'] > ma50:
                score += 0.15
            if idx['last'] > ma200:
                score += 0.10
        
        # Momentum scoring
        spy_change = spy.get('change_pct', 0) if spy else 0
        qqq_change = qqq.get('change_pct', 0) if qqq else 0
        avg_change = (spy_change + qqq_change) / 2
        if avg_change > 1.0:
            score += 0.20
        elif avg_change > 0:
            score += 0.10
        elif avg_change < -1.0:
            score -= 0.30
        else:
            score -= 0.10
        
        # Distribution penalty
        max_dist = max(spy_dist_days, qqq_dist_days)
        score -= max_dist * 0.08
        
        # Clamp to 0-1.5 range
        score = max(0.0, min(1.5, score))
        
        # Determine regime
        if score >= 0.8:
            regime = 'BULLISH'
            exposure = 5
        elif score >= 0.5:
            regime = 'NEUTRAL'
            exposure = 3
        else:
            regime = 'BEARISH'
            exposure = 1
        
        # Console output
        regime_emoji = {'BULLISH': '🟢', 'NEUTRAL': '🟡', 'BEARISH': '🔴'}.get(regime, '⚪')
        print(f"  {regime_emoji} {Colors.BOLD}REGIME: {regime}{Colors.RESET}")
        print(f"  Score: {score:+.2f} / 1.50")
        print(f"  Recommended Exposure: {exposure}/5")
        
        # IBD-aligned exposure
        if max_dist <= 4:
            exposure_str = "80-100%"
        elif max_dist <= 6:
            exposure_str = "60-80%"
        elif max_dist <= 8:
            exposure_str = "40-60%"
        else:
            exposure_str = "20-40%"
        print(f"  IBD Exposure Level: {exposure_str}")
        
        # Send Discord alert with full format
        if self.discord:
            self.discord.send_market_regime_alert(
                regime=regime,
                score=score,
                exposure=exposure,
                spy_price=spy['last'],
                spy_change=spy['change_pct'],
                qqq_price=qqq['last'],
                qqq_change=qqq['change_pct'],
                spy_dist_days=spy_dist_days,
                qqq_dist_days=qqq_dist_days,
                spy_5day_delta=spy_5day_delta,
                qqq_5day_delta=qqq_5day_delta,
                dist_trend=dist_trend,
                market_phase=market_phase,
                ftd_info=ftd_info,
                overnight_futures=overnight_futures,
                spy_dday_positions=spy_dday_positions,
                qqq_dday_positions=qqq_dday_positions,
                rally_day=rally_day,
                rally_failed=0,
                successful_ftds=1 if market_phase == 'CONFIRMED_UPTREND' else 0,
                prior_score=prior_score,
                score_direction=score_direction,
                verbose=True
            )
        
        print(f"\n  {Colors.DIM}Regime factors:{Colors.RESET}")
        ma_score = sum(0.25 for idx in [spy, qqq] if idx and idx['last'] > idx.get('ma50', idx['last'] * 0.98))
        print(f"    {Colors.DIM}MA positions: +{ma_score:.2f}{Colors.RESET}")
        print(f"    {Colors.DIM}Momentum: {'+' if avg_change > 0 else ''}{avg_change * 0.1:.2f}{Colors.RESET}")
        print(f"    {Colors.DIM}Distribution penalty: -{max_dist * 0.08:.2f}{Colors.RESET}")
    
    def run_full_demo(self):
        """Run complete demo of all features."""
        self._print_header("CANSLIM MONITOR - FULL DEMO")
        
        mode_str = "LIVE (IBKR)" if self.live_mode else "MOCK DATA"
        print(f"{Colors.CYAN}Mode: {mode_str}{Colors.RESET}")
        if self.discord:
            print(f"{Colors.CYAN}Discord: ENABLED{Colors.RESET}")
        print(f"{Colors.DIM}This demo tests the Phase 2 plumbing.{Colors.RESET}")
        
        # Database status
        self.run_status()
        
        input(f"\n{Colors.YELLOW}Press Enter to continue to Breakout Demo...{Colors.RESET}")
        self.run_breakout_demo()
        
        input(f"\n{Colors.YELLOW}Press Enter to continue to Position Demo...{Colors.RESET}")
        self.run_position_demo()
        
        input(f"\n{Colors.YELLOW}Press Enter to continue to Market Demo...{Colors.RESET}")
        self.run_market_demo()
        
        # Cleanup
        self._cleanup_live()
        
        self._print_header("DEMO COMPLETE")
        print("All Phase 2 logic tested successfully!")
        print()
        if not self.live_mode:
            print("Next: Run with --live to use real IBKR data")
        if not self.discord:
            print("Next: Run with --discord to send real alerts")
    
    def seed_test_data(self):
        """Seed database with test positions."""
        self._print_header("SEEDING TEST DATA")
        
        db = self._init_db()
        session = db.get_new_session()
        repos = RepositoryManager(session)
        
        # Test positions - watching (state 0)
        watching = [
            {'symbol': 'NVDA', 'pivot': 140.00, 'rs_rating': 95, 'portfolio': 'IRA'},
            {'symbol': 'PLTR', 'pivot': 75.00, 'rs_rating': 92, 'portfolio': 'IRA'},
            {'symbol': 'META', 'pivot': 585.00, 'rs_rating': 88, 'portfolio': 'Taxable'},
            {'symbol': 'CRWD', 'pivot': 365.00, 'rs_rating': 90, 'portfolio': 'IRA'},
            {'symbol': 'AXON', 'pivot': 640.00, 'rs_rating': 94, 'portfolio': 'Taxable'},
        ]
        
        # Test positions - active (state 1)
        active = [
            {'symbol': 'AMZN', 'pivot': 185.00, 'avg_cost': 188.50, 'rs_rating': 85, 'portfolio': 'IRA'},
            {'symbol': 'GOOGL', 'pivot': 175.00, 'avg_cost': 178.00, 'rs_rating': 82, 'portfolio': 'Taxable'},
            {'symbol': 'TSLA', 'pivot': 250.00, 'avg_cost': 255.00, 'rs_rating': 78, 'portfolio': 'IRA'},
        ]
        
        print("Adding watching positions (State 0)...")
        for pos in watching:
            existing = repos.positions.get_by_symbol(pos['symbol'], pos['portfolio'])
            if not existing:
                repos.positions.create(state=0, **pos)
                print(f"  Added: {pos['symbol']} (Pivot: ${pos['pivot']})")
            else:
                print(f"  Skipped: {pos['symbol']} (already exists)")
        
        print("\nAdding active positions (State 1)...")
        for pos in active:
            existing = repos.positions.get_by_symbol(pos['symbol'], pos['portfolio'])
            if not existing:
                repos.positions.create(state=1, **pos)
                print(f"  Added: {pos['symbol']} (Avg Cost: ${pos['avg_cost']})")
            else:
                print(f"  Skipped: {pos['symbol']} (already exists)")
        
        session.commit()
        session.close()
        
        print(f"\n{Colors.GREEN}Test data seeded successfully!{Colors.RESET}")
        print("Run 'python demo.py' to test with this data.")


# ==================== MAIN ====================

def main():
    # Load config first to get defaults
    config = load_config()
    ibkr_config = config.get('ibkr', {})
    db_config = config.get('database', {})
    
    parser = argparse.ArgumentParser(
        description='CANSLIM Monitor CLI Demo',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python demo.py                Run full interactive demo (mock data)
  python demo.py breakout       Test breakout detection only
  python demo.py positions      Test position monitoring only
  python demo.py market         Test market regime only
  python demo.py seed           Seed test data
  python demo.py status         Show database status

Live Mode (requires TWS running):
  python demo.py --live                     Use real IBKR data
  python demo.py breakout --live            Live breakout check
  python demo.py --live --discord           Send alerts to Discord (uses config webhooks)
  python demo.py --live --discord WEBHOOK   Send alerts to specific webhook

Config file is loaded from:
  1. user_config.yaml (if exists)
  2. config/default_config.yaml

Scenarios (for mock mode):
  python demo.py breakout --scenarios breakout,breakout,buy_zone
  python demo.py positions --scenarios at_stop,near_tp1,healthy
        """
    )
    
    parser.add_argument(
        'command',
        nargs='?',
        default='full',
        choices=['full', 'breakout', 'positions', 'market', 'seed', 'status'],
        help='Demo command to run'
    )
    
    parser.add_argument(
        '--config',
        help='Path to config YAML file'
    )
    
    parser.add_argument(
        '--db',
        default=None,
        help=f"Database path (default from config: {db_config.get('path', 'canslim_monitor.db')})"
    )
    
    parser.add_argument(
        '--scenarios',
        help='Comma-separated list of scenarios to test (mock mode only)'
    )
    
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )
    
    parser.add_argument(
        '--live',
        action='store_true',
        help='Use live IBKR data (requires TWS/Gateway running)'
    )
    
    parser.add_argument(
        '--ibkr-host',
        default=None,
        help=f"IBKR TWS/Gateway host (default from config: {ibkr_config.get('host', '127.0.0.1')})"
    )
    
    parser.add_argument(
        '--ibkr-port',
        type=int,
        default=None,
        help=f"IBKR TWS/Gateway port (default from config: {ibkr_config.get('port', 7497)})"
    )
    
    parser.add_argument(
        '--ibkr-client-id',
        type=int,
        default=None,
        help=f"IBKR client ID (default from config: {ibkr_config.get('client_id', 10)})"
    )
    
    parser.add_argument(
        '--discord',
        nargs='?',
        const='USE_CONFIG',
        metavar='WEBHOOK',
        help='Enable Discord alerts. Optionally provide webhook URL (default: from config)'
    )
    
    args = parser.parse_args()
    
    if args.no_color:
        Colors.disable()
    
    # Reload config if custom path provided
    if args.config:
        config = load_config(args.config)
    
    # Determine discord webhook
    discord_webhook = None
    discord_enabled = args.discord is not None
    if args.discord and args.discord != 'USE_CONFIG':
        discord_webhook = args.discord
    
    runner = DemoRunner(
        config=config,
        db_path=args.db,
        live_mode=args.live,
        discord_enabled=discord_enabled,
        discord_webhook=discord_webhook,
        ibkr_host=args.ibkr_host,
        ibkr_port=args.ibkr_port,
        ibkr_client_id=args.ibkr_client_id
    )
    
    scenarios = args.scenarios.split(',') if args.scenarios else None
    
    try:
        if args.command == 'full':
            runner.run_full_demo()
        elif args.command == 'breakout':
            runner.run_breakout_demo(scenarios)
        elif args.command == 'positions':
            runner.run_position_demo(scenarios)
        elif args.command == 'market':
            scenario = scenarios[0] if scenarios else 'random'
            runner.run_market_demo(scenario)
        elif args.command == 'seed':
            runner.seed_test_data()
        elif args.command == 'status':
            runner.run_status()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Demo interrupted.{Colors.RESET}")
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.RESET}")
        raise
    finally:
        runner._cleanup_live()


if __name__ == '__main__':
    main()
