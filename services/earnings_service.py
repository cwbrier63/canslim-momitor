"""
CANSLIM Monitor - Earnings Service
===================================
Fetches upcoming earnings dates from Polygon/Massive and updates positions.

Usage:
    # CLI:
    python -m canslim_monitor.services.earnings_service
    
    # Or from code:
    service = EarningsService(db_session_factory, polygon_client)
    service.update_all_positions()
"""

import logging
from datetime import date, datetime
from typing import List, Dict, Optional, Callable

from sqlalchemy.orm import Session

from ..integrations.polygon_client import PolygonClient
from ..data.models import Position


class EarningsService:
    """
    Service to fetch and update earnings dates for positions.
    
    Integrates with Polygon.io / Massive API to look up upcoming
    earnings dates and update the database.
    """
    
    def __init__(
        self,
        session_factory: Callable[[], Session],
        polygon_client: PolygonClient,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize earnings service.
        
        Args:
            session_factory: Callable that returns a new database session
            polygon_client: Polygon API client
            logger: Logger instance
        """
        self.session_factory = session_factory
        self.polygon_client = polygon_client
        self.logger = logger or logging.getLogger('canslim.earnings')
    
    def get_active_symbols(self) -> List[str]:
        """
        Get all unique symbols with active positions (state >= 0).
        
        Returns:
            List of symbols
        """
        session = self.session_factory()
        try:
            positions = session.query(Position.symbol).filter(
                Position.state >= 0  # Watching or in position
            ).distinct().all()
            
            return [p[0] for p in positions]
        finally:
            session.close()
    
    def update_earnings_date(self, symbol: str, earnings_date: Optional[date]) -> bool:
        """
        Update earnings date for a single symbol.
        
        Args:
            symbol: Stock symbol
            earnings_date: Earnings date to set (or None to clear)
            
        Returns:
            True if update was successful
        """
        session = self.session_factory()
        try:
            # Update all positions with this symbol
            positions = session.query(Position).filter(
                Position.symbol == symbol.upper(),
                Position.state >= 0
            ).all()
            
            updated = 0
            for position in positions:
                old_date = position.earnings_date
                position.earnings_date = earnings_date
                position.updated_at = datetime.now()
                updated += 1
                
                if old_date != earnings_date:
                    self.logger.info(
                        f"{symbol}: Earnings date updated {old_date} -> {earnings_date}"
                    )
            
            session.commit()
            return updated > 0
            
        except Exception as e:
            self.logger.error(f"Error updating earnings for {symbol}: {e}")
            session.rollback()
            return False
        finally:
            session.close()
    
    def update_all_positions(self, force: bool = False) -> Dict[str, any]:
        """
        Update earnings dates for all active positions.
        
        Args:
            force: If True, update even if earnings_date already set
            
        Returns:
            Summary dict with counts
        """
        self.logger.info("Starting earnings date update for all positions...")
        
        results = {
            'symbols_checked': 0,
            'updated': 0,
            'skipped': 0,
            'not_found': 0,
            'errors': 0,
            'details': {}
        }
        
        # Get all active symbols
        symbols = self.get_active_symbols()
        results['symbols_checked'] = len(symbols)
        
        self.logger.info(f"Found {len(symbols)} symbols to check")
        
        for symbol in symbols:
            try:
                # Check if we should skip (already has recent earnings date)
                if not force:
                    session = self.session_factory()
                    try:
                        position = session.query(Position).filter(
                            Position.symbol == symbol,
                            Position.state >= 0
                        ).first()
                        
                        if position and position.earnings_date:
                            # Skip if earnings date is in the future
                            if position.earnings_date >= date.today():
                                self.logger.debug(f"{symbol}: Skipping, has future earnings date {position.earnings_date}")
                                results['skipped'] += 1
                                results['details'][symbol] = f"Skipped (has {position.earnings_date})"
                                continue
                    finally:
                        session.close()
                
                # Look up earnings date from Polygon
                earnings_date = self.polygon_client.get_next_earnings_date(symbol)
                
                if earnings_date:
                    if self.update_earnings_date(symbol, earnings_date):
                        results['updated'] += 1
                        results['details'][symbol] = f"Updated to {earnings_date}"
                    else:
                        results['errors'] += 1
                        results['details'][symbol] = "Update failed"
                else:
                    results['not_found'] += 1
                    results['details'][symbol] = "No earnings date found"
                    
            except Exception as e:
                self.logger.error(f"Error processing {symbol}: {e}")
                results['errors'] += 1
                results['details'][symbol] = f"Error: {e}"
        
        self.logger.info(
            f"Earnings update complete: "
            f"{results['updated']} updated, "
            f"{results['skipped']} skipped, "
            f"{results['not_found']} not found, "
            f"{results['errors']} errors"
        )
        
        return results
    
    def check_upcoming_earnings(self, days: int = 14) -> List[Dict]:
        """
        Find positions with earnings coming up in N days.
        
        Args:
            days: Number of days to look ahead
            
        Returns:
            List of position dicts with upcoming earnings
        """
        session = self.session_factory()
        try:
            today = date.today()
            cutoff = date.today()
            
            # Calculate cutoff date
            from datetime import timedelta
            cutoff = today + timedelta(days=days)
            
            positions = session.query(Position).filter(
                Position.state >= 1,  # In position only
                Position.earnings_date != None,
                Position.earnings_date >= today,
                Position.earnings_date <= cutoff
            ).order_by(Position.earnings_date).all()
            
            results = []
            for p in positions:
                days_until = (p.earnings_date - today).days
                results.append({
                    'symbol': p.symbol,
                    'earnings_date': p.earnings_date,
                    'days_until': days_until,
                    'pnl_pct': p.current_pnl_pct or 0,
                    'shares': p.total_shares or 0,
                    'avg_cost': p.avg_cost or 0
                })
            
            return results
            
        finally:
            session.close()


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    """CLI entry point for updating earnings dates."""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='Update earnings dates from Polygon/Massive')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Force update even if earnings date already set')
    parser.add_argument('--symbol', '-s', type=str,
                        help='Update single symbol only')
    parser.add_argument('--check', '-c', action='store_true',
                        help='Check upcoming earnings (no update)')
    parser.add_argument('--days', '-d', type=int, default=14,
                        help='Days ahead to check for upcoming earnings')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    print("=" * 60)
    print("EARNINGS DATE UPDATE SERVICE")
    print("=" * 60)
    
    # Load config
    try:
        from ..utils.config import load_config
        config = load_config()
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        sys.exit(1)
    
    # Get Polygon/Massive config
    market_data_config = config.get('market_data', {})
    polygon_config = config.get('polygon', {})
    
    api_key = market_data_config.get('api_key') or polygon_config.get('api_key', '')
    base_url = market_data_config.get('base_url') or polygon_config.get('base_url', 'https://api.polygon.io')
    
    if not api_key:
        print("❌ No API key configured")
        print("   Add market_data.api_key to user_config.yaml")
        sys.exit(1)
    
    provider = market_data_config.get('provider', 'polygon')
    if 'massive' in base_url.lower():
        provider = 'massive'
    
    print(f"Provider: {provider}")
    print(f"Base URL: {base_url}")
    
    # Create Polygon client
    polygon_client = PolygonClient(
        api_key=api_key,
        base_url=base_url,
        timeout=market_data_config.get('timeout', 30)
    )
    
    # Test connection
    print("\nTesting API connection...")
    if not polygon_client.test_connection():
        print("❌ API connection failed")
        sys.exit(1)
    print("✅ API connection successful")
    
    # Get database session factory
    try:
        from ..data.database import get_database
        db_path = config.get('database', {}).get('path')
        db = get_database(db_path=db_path)
        session_factory = db.get_new_session
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)
    
    # Create service
    service = EarningsService(
        session_factory=session_factory,
        polygon_client=polygon_client
    )
    
    # Check upcoming earnings mode
    if args.check:
        print(f"\nChecking upcoming earnings (next {args.days} days)...")
        upcoming = service.check_upcoming_earnings(days=args.days)
        
        if not upcoming:
            print("No positions with upcoming earnings")
        else:
            print(f"\n{'Symbol':<8} {'Earnings':<12} {'Days':<6} {'P&L %':<8}")
            print("-" * 40)
            for p in upcoming:
                print(f"{p['symbol']:<8} {str(p['earnings_date']):<12} {p['days_until']:<6} {p['pnl_pct']:+.1f}%")
        
        sys.exit(0)
    
    # Single symbol mode
    if args.symbol:
        print(f"\nLooking up earnings for {args.symbol.upper()}...")
        earnings_date = polygon_client.get_next_earnings_date(args.symbol)
        
        if earnings_date:
            print(f"✅ Found: {earnings_date}")
            if service.update_earnings_date(args.symbol, earnings_date):
                print("✅ Database updated")
            else:
                print("⚠️  No active positions found for this symbol")
        else:
            print("❌ No earnings date found")
        
        sys.exit(0)
    
    # Update all positions
    print(f"\nUpdating earnings for all active positions...")
    if args.force:
        print("   (Force mode: updating all regardless of existing data)")
    
    results = service.update_all_positions(force=args.force)
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Symbols checked: {results['symbols_checked']}")
    print(f"Updated:         {results['updated']}")
    print(f"Skipped:         {results['skipped']}")
    print(f"Not found:       {results['not_found']}")
    print(f"Errors:          {results['errors']}")
    
    if args.verbose and results['details']:
        print("\nDetails:")
        for symbol, detail in sorted(results['details'].items()):
            print(f"  {symbol}: {detail}")
    
    print("=" * 60)


if __name__ == '__main__':
    main()
