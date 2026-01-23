"""
CANSLIM Monitor - Volume Service
=================================
Fetches historical volume data from Polygon/Massive and calculates
50-day average volume for breakout confirmation.

Usage:
    # CLI
    python -m canslim_monitor.services.volume_service update
    python -m canslim_monitor.services.volume_service update --symbol NVDA
    
    # In code
    service = VolumeService(db_session_factory, polygon_client)
    service.update_all_watchlist()
"""

import logging
import sys
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..data.models import Position, HistoricalBar
from ..integrations.polygon_client import PolygonClient, Bar


@dataclass
class VolumeUpdateResult:
    """Result of volume update operation."""
    symbol: str
    bars_fetched: int
    bars_stored: int
    avg_volume_50d: int
    success: bool
    error: Optional[str] = None


class VolumeService:
    """
    Service for managing historical volume data.
    
    Responsibilities:
    - Fetch historical bars from Polygon/Massive
    - Store bars in database
    - Calculate 50-day average volume
    - Update positions with avg_volume_50d
    """
    
    def __init__(
        self,
        db_session_factory,
        polygon_client: PolygonClient,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize volume service.
        
        Args:
            db_session_factory: SQLAlchemy session factory
            polygon_client: Polygon API client
            logger: Logger instance
        """
        self.db_session_factory = db_session_factory
        self.polygon_client = polygon_client
        self.logger = logger or logging.getLogger('canslim.volume')
    
    def update_symbol(self, symbol: str, days: int = 50) -> VolumeUpdateResult:
        """
        Update volume data for a single symbol.
        
        Args:
            symbol: Stock symbol
            days: Number of days to fetch
            
        Returns:
            VolumeUpdateResult with status
        """
        symbol = symbol.upper()
        self.logger.info(f"Updating volume data for {symbol}")
        
        try:
            # 1. Fetch bars from Polygon
            bars = self.polygon_client.get_daily_bars(symbol, days=days)
            
            if not bars:
                return VolumeUpdateResult(
                    symbol=symbol,
                    bars_fetched=0,
                    bars_stored=0,
                    avg_volume_50d=0,
                    success=False,
                    error="No data returned from API"
                )
            
            # 2. Calculate average volume
            avg_volume = self.polygon_client.calculate_average_volume(bars, days)
            
            # 3. Store bars in database
            bars_stored = self._store_bars(bars)
            
            # 4. Update position with avg_volume
            self._update_position_volume(symbol, avg_volume)
            
            self.logger.info(
                f"{symbol}: {len(bars)} bars fetched, {bars_stored} stored, "
                f"avg_vol={avg_volume:,}"
            )
            
            return VolumeUpdateResult(
                symbol=symbol,
                bars_fetched=len(bars),
                bars_stored=bars_stored,
                avg_volume_50d=avg_volume,
                success=True
            )
            
        except Exception as e:
            self.logger.error(f"Error updating {symbol}: {e}")
            return VolumeUpdateResult(
                symbol=symbol,
                bars_fetched=0,
                bars_stored=0,
                avg_volume_50d=0,
                success=False,
                error=str(e)
            )
    
    def _store_bars(self, bars: List[Bar]) -> int:
        """
        Store bars in database, updating existing ones.
        
        Args:
            bars: List of Bar objects
            
        Returns:
            Number of bars stored/updated
        """
        if not bars or not self.db_session_factory:
            return 0
        
        stored = 0
        session = self.db_session_factory()
        
        try:
            for bar in bars:
                # Check if bar exists
                existing = session.query(HistoricalBar).filter(
                    HistoricalBar.symbol == bar.symbol,
                    HistoricalBar.bar_date == bar.bar_date
                ).first()
                
                if existing:
                    # Update existing
                    existing.open = bar.open
                    existing.high = bar.high
                    existing.low = bar.low
                    existing.close = bar.close
                    existing.volume = bar.volume
                    existing.vwap = bar.vwap
                    existing.transactions = bar.transactions
                else:
                    # Insert new
                    new_bar = HistoricalBar(
                        symbol=bar.symbol,
                        bar_date=bar.bar_date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        vwap=bar.vwap,
                        transactions=bar.transactions
                    )
                    session.add(new_bar)
                
                stored += 1
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"Error storing bars: {e}")
            stored = 0
        finally:
            session.close()
        
        return stored
    
    def _update_position_volume(self, symbol: str, avg_volume: int) -> bool:
        """
        Update position with calculated average volume.
        
        Args:
            symbol: Stock symbol
            avg_volume: Calculated 50-day average volume
            
        Returns:
            True if updated
        """
        if not self.db_session_factory:
            return False
        
        session = self.db_session_factory()
        
        try:
            # Update all positions for this symbol (could be in multiple portfolios)
            updated = session.query(Position).filter(
                Position.symbol == symbol
            ).update({
                'avg_volume_50d': avg_volume,
                'volume_updated_at': datetime.now()
            })
            
            session.commit()
            return updated > 0
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"Error updating position volume for {symbol}: {e}")
            return False
        finally:
            session.close()
    
    def update_all_watchlist(self, state: int = 0) -> Dict[str, VolumeUpdateResult]:
        """
        Update volume data for all positions in a given state.
        
        Args:
            state: Position state (0 = watching, 1+ = in position)
            
        Returns:
            Dict mapping symbol to result
        """
        if not self.db_session_factory:
            return {}
        
        # Get unique symbols from watchlist
        session = self.db_session_factory()
        try:
            symbols = session.query(Position.symbol).filter(
                Position.state == state
            ).distinct().all()
            symbols = [s[0] for s in symbols]
        finally:
            session.close()
        
        if not symbols:
            self.logger.info("No symbols to update")
            return {}
        
        self.logger.info(f"Updating volume data for {len(symbols)} symbols")
        
        results = {}
        for i, symbol in enumerate(symbols):
            result = self.update_symbol(symbol)
            results[symbol] = result
            
            # Progress update
            if (i + 1) % 10 == 0:
                self.logger.info(f"Progress: {i+1}/{len(symbols)}")
        
        # Summary
        success_count = sum(1 for r in results.values() if r.success)
        self.logger.info(f"Volume update complete: {success_count}/{len(symbols)} successful")
        
        return results
    
    def get_average_volume(self, symbol: str, days: int = 50) -> int:
        """
        Get stored average volume for a symbol.
        
        First checks position table, then calculates from stored bars if needed.
        
        Args:
            symbol: Stock symbol
            days: Number of days for average
            
        Returns:
            Average volume or 0 if not available
        """
        if not self.db_session_factory:
            return 0
        
        session = self.db_session_factory()
        
        try:
            # First check if position has avg_volume_50d
            position = session.query(Position).filter(
                Position.symbol == symbol.upper()
            ).first()
            
            if position and hasattr(position, 'avg_volume_50d') and position.avg_volume_50d:
                return position.avg_volume_50d
            
            # Calculate from stored bars
            bars = session.query(HistoricalBar).filter(
                HistoricalBar.symbol == symbol.upper()
            ).order_by(
                HistoricalBar.bar_date.desc()
            ).limit(days).all()
            
            if not bars:
                return 0
            
            total_volume = sum(b.volume for b in bars if b.volume)
            return int(total_volume / len(bars)) if bars else 0
            
        finally:
            session.close()
    
    def cleanup_old_bars(self, days_to_keep: int = 100) -> int:
        """
        Remove bars older than specified days.
        
        Args:
            days_to_keep: Keep bars from last N days
            
        Returns:
            Number of bars deleted
        """
        if not self.db_session_factory:
            return 0
        
        cutoff_date = date.today() - timedelta(days=days_to_keep)
        
        session = self.db_session_factory()
        try:
            deleted = session.query(HistoricalBar).filter(
                HistoricalBar.bar_date < cutoff_date
            ).delete()
            session.commit()
            
            if deleted:
                self.logger.info(f"Cleaned up {deleted} old bars")
            
            return deleted
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"Error cleaning up bars: {e}")
            return 0
        finally:
            session.close()
    
    def get_dataframe(self, symbol: str, days: int = 200) -> Optional['pd.DataFrame']:
        """
        Get historical data as a pandas DataFrame for technical analysis.
        
        Used by indicators module for dynamic scoring calculations.
        
        Args:
            symbol: Stock symbol
            days: Number of days to retrieve
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
            Returns None if insufficient data
        """
        try:
            import pandas as pd
        except ImportError:
            self.logger.error("pandas not available for DataFrame conversion")
            return None
        
        if not self.db_session_factory:
            return None
        
        session = self.db_session_factory()
        
        try:
            bars = session.query(HistoricalBar).filter(
                HistoricalBar.symbol == symbol.upper()
            ).order_by(
                HistoricalBar.bar_date.asc()
            ).limit(days).all()
            
            if len(bars) < 50:  # Minimum for meaningful analysis
                self.logger.warning(
                    f"{symbol}: Only {len(bars)} bars available, need at least 50"
                )
                return None
            
            # Convert to DataFrame
            data = [{
                'date': bar.bar_date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            } for bar in bars]
            
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            
            return df
            
        except Exception as e:
            self.logger.error(f"Error getting DataFrame for {symbol}: {e}")
            return None
        finally:
            session.close()
    
    def ensure_data_seeded(self, symbol: str, days: int = 200) -> bool:
        """
        Ensure historical data is available for a symbol, fetching if needed.
        
        Args:
            symbol: Stock symbol
            days: Number of days of history to ensure
            
        Returns:
            True if data is available, False otherwise
        """
        symbol = symbol.upper()
        
        # Check current data availability
        if self.db_session_factory:
            session = self.db_session_factory()
            try:
                bar_count = session.query(HistoricalBar).filter(
                    HistoricalBar.symbol == symbol
                ).count()
                
                if bar_count >= days * 0.8:  # Allow 20% tolerance for non-trading days
                    self.logger.debug(f"{symbol}: {bar_count} bars available, sufficient")
                    return True
            finally:
                session.close()
        
        # Fetch data
        self.logger.info(f"{symbol}: Seeding {days} days of historical data")
        result = self.update_symbol(symbol, days=days)
        
        return result.success and result.bars_stored > 0


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """CLI entry point for volume service."""
    import argparse
    from pathlib import Path
    
    from ..utils.config import load_config
    from ..data.database import get_database
    
    parser = argparse.ArgumentParser(
        description='CANSLIM Volume Service - Update 50-day average volume data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m canslim_monitor.services.volume_service update
    python -m canslim_monitor.services.volume_service update --symbol NVDA
    python -m canslim_monitor.services.volume_service cleanup
        """
    )
    
    parser.add_argument(
        'command',
        choices=['update', 'cleanup', 'test'],
        help='Command to run'
    )
    parser.add_argument(
        '--symbol', '-s',
        help='Update single symbol only'
    )
    parser.add_argument(
        '--config', '-c',
        help='Config file path'
    )
    parser.add_argument(
        '--database', '-d',
        default='C:/Trading/canslim_positions.db',
        help='Database path'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    logger = logging.getLogger('canslim.volume')
    
    # Load config
    config = load_config(args.config)
    
    # Support both new (market_data) and legacy (polygon) config sections
    market_data_config = config.get('market_data', {})
    polygon_config = config.get('polygon', {})
    
    # Prefer market_data, fall back to polygon
    api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
    base_url = market_data_config.get('base_url') or polygon_config.get('base_url', 'https://api.polygon.io')
    timeout = market_data_config.get('timeout') or polygon_config.get('timeout', 30)
    rate_limit_delay = market_data_config.get('rate_limit_delay', 0.5)
    
    if not api_key:
        print("ERROR: No API key configured")
        print("Add your API key to user_config.yaml:")
        print("  market_data:")
        print("    api_key: \"your_key_here\"")
        print("")
        print("Or for legacy config:")
        print("  polygon:")
        print("    api_key: \"your_key_here\"")
        sys.exit(1)
    
    # Initialize components
    db = get_database(db_path=args.database)
    db.initialize()  # Ensure tables exist
    session_factory = db.get_new_session  # Method that returns a new session
    
    polygon_client = PolygonClient(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        rate_limit_delay=rate_limit_delay,
        logger=logger
    )
    
    service = VolumeService(
        db_session_factory=session_factory,
        polygon_client=polygon_client,
        logger=logger
    )
    
    # Determine provider name for display
    provider = market_data_config.get('provider', 'polygon')
    if 'massive' in base_url.lower():
        provider = 'massive'
    
    # Execute command
    print("=" * 60)
    print("CANSLIM VOLUME SERVICE")
    print("=" * 60)
    print(f"Provider: {provider.upper()}")
    print(f"Base URL: {base_url}")
    
    if args.command == 'test':
        print(f"\nTesting {provider.upper()} API connection...")
        if polygon_client.test_connection():
            print("✓ Connection successful!")
        else:
            print("✗ Connection failed!")
            sys.exit(1)
    
    elif args.command == 'update':
        if args.symbol:
            print(f"\nUpdating volume data for: {args.symbol}")
            result = service.update_symbol(args.symbol)
            
            if result.success:
                print(f"✓ {result.symbol}: {result.bars_fetched} bars, avg_vol={result.avg_volume_50d:,}")
            else:
                print(f"✗ {result.symbol}: {result.error}")
        else:
            print("\nUpdating volume data for all watchlist symbols...")
            results = service.update_all_watchlist()
            
            print(f"\nResults:")
            success = 0
            for symbol, result in sorted(results.items()):
                status = "✓" if result.success else "✗"
                if result.success:
                    print(f"  {status} {symbol}: avg_vol={result.avg_volume_50d:,}")
                    success += 1
                else:
                    print(f"  {status} {symbol}: {result.error}")
            
            print(f"\nTotal: {success}/{len(results)} successful")
    
    elif args.command == 'cleanup':
        print("\nCleaning up old historical bars...")
        deleted = service.cleanup_old_bars(days_to_keep=100)
        print(f"Deleted {deleted} old bars")
    
    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
