"""
CANSLIM Monitor - Position Thread
Monitors State 1+ (active) positions for stops, targets, and health changes.

Uses the PositionMonitor core module to run all alert checkers.
Uses TechnicalDataService to fetch MAs and volume from Polygon.

Version: 1.1 - Integrated with TechnicalDataService
"""

import logging
from typing import Optional, List, Any, Dict
from datetime import datetime

from .base_thread import BaseThread
from canslim_monitor.core.position_monitor import PositionMonitor
from canslim_monitor.services.alert_service import (
    AlertService, AlertType, AlertSubtype, AlertContext, AlertData
)
from canslim_monitor.services.technical_data_service import TechnicalDataService
from canslim_monitor.utils.config import get_config


class PositionThread(BaseThread):
    """
    Monitors active positions for exits and health changes.
    
    Scope: State 1+ positions
    Checks (via PositionMonitor):
        - Price vs stop levels (hard stop, trailing stop)
        - Price vs take-profit levels (TP1, TP2, 8-week hold)
        - Price vs pyramid levels (PY1, PY2, pullback)
        - Price vs moving averages (50, 21, 200, 10-week)
        - Health score factors
        - Earnings proximity
    Actions:
        - Generate position alerts via AlertService
        - Update health scores
        - Track max gain/drawdown
    """
    
    def __init__(
        self,
        shutdown_event,
        poll_interval: int = 30,
        db_session_factory=None,
        ibkr_client=None,
        discord_notifier=None,
        config: Dict[str, Any] = None,
        logger: Optional[logging.Logger] = None,
        # Provider abstraction layer (Phase 6)
        realtime_provider=None,
    ):
        super().__init__(
            name="position",
            shutdown_event=shutdown_event,
            poll_interval=poll_interval,
            logger=logger or logging.getLogger('canslim.position')
        )
        
        self.db_session_factory = db_session_factory
        self.ibkr_client = ibkr_client
        self.discord_notifier = discord_notifier

        # Provider abstraction layer — prefers provider over raw client
        self.realtime_provider = realtime_provider
        
        # Load config
        if config is None:
            config = get_config()
        self.config = config
        
        # Get position monitoring config
        pm_config = config.get('position_monitoring', {})
        
        # Get alert settings
        alert_config = config.get('alerts', {})
        cooldown_enabled = alert_config.get('enable_cooldown', False)
        cooldown_minutes = alert_config.get('cooldown_minutes', 60)
        
        # Initialize AlertService
        self.alert_service = AlertService(
            db_session_factory=db_session_factory,
            discord_notifier=discord_notifier,
            cooldown_minutes=cooldown_minutes,
            enable_cooldown=cooldown_enabled,
            enable_suppression=alert_config.get('enable_suppression', True),
            alert_routing=alert_config.get('alert_routing', {}),
            logger=logging.getLogger('canslim.alerts'),
        )
        
        # Log cooldown status
        self.logger.info(
            f"Position AlertService initialized "
            f"(cooldown={'enabled' if cooldown_enabled else 'disabled'}, "
            f"cooldown_minutes={cooldown_minutes})"
        )
        
        # Initialize PositionMonitor
        self.position_monitor = PositionMonitor(
            config=pm_config,
            logger=logging.getLogger('canslim.position_monitor'),
        )
        
        # Initialize TechnicalDataService for MAs and volume
        # Try market_data config first (new format), fall back to polygon config (legacy)
        market_data_config = config.get('market_data', {})
        polygon_config = config.get('polygon', {})
        polygon_key = market_data_config.get('api_key', '') or polygon_config.get('api_key', '')
        self.technical_service = TechnicalDataService(
            polygon_api_key=polygon_key,
            cache_duration_hours=4,  # Refresh MAs every 4 hours
            logger=logging.getLogger('canslim.technical_data'),
        )
        
        # Track max prices for trailing stop calculation
        self._max_prices: Dict[str, float] = {}
        self._max_gains: Dict[str, float] = {}
    
    def _should_run(self) -> bool:
        """Only run during market hours."""
        return self._is_market_hours()
    
    def _do_work(self):
        """Check all active positions."""
        self.logger.debug("Starting position check cycle")
        
        try:
            # Get active positions from database
            positions = self._get_active_positions()
            
            if not positions:
                self.logger.debug("No active positions to monitor")
                return
            
            self.logger.debug(f"Checking {len(positions)} active positions")
            
            # Get price data for all symbols
            symbols = [p.symbol for p in positions]
            price_data = self._get_prices(symbols)
            
            if not price_data:
                self.logger.warning("No price data received")
                return
            
            # Get technical data
            technical_data = self._get_technical_data(symbols, price_data)

            # Get market regime and SPY price for context
            market_regime, spy_price = self._get_market_context()

            # Merge max prices and max gains into price_data for position monitor
            for symbol in price_data:
                price_data[symbol]['max_price'] = self._max_prices.get(symbol, price_data[symbol]['price'])
                price_data[symbol]['max_gain_pct'] = self._max_gains.get(symbol, 0)

            # Run monitoring cycle with market context
            result = self.position_monitor.run_cycle(
                positions, price_data, technical_data,
                market_regime=market_regime, spy_price=spy_price
            )
            
            # Route alerts through AlertService
            self._route_alerts(result.alerts)
            
            # Update position tracking in database
            self._update_position_tracking(positions, price_data)
            
            # Log results
            if result.alerts_generated > 0:
                self.logger.info(
                    f"Position cycle: {result.positions_checked} checked, "
                    f"{result.alerts_generated} alerts generated"
                )
            else:
                self.logger.debug(
                    f"Position cycle complete: {result.positions_checked} positions, "
                    f"no alerts"
                )
            
            if result.has_errors:
                for error in result.errors:
                    self.logger.error(f"Cycle error: {error}")
            
        except Exception as e:
            self.logger.error(f"Error in position cycle: {e}", exc_info=True)
            raise
    
    def _get_active_positions(self) -> List:
        """Get all State 1+ positions from database."""
        if not self.db_session_factory:
            return []
        
        try:
            session = self.db_session_factory()
            try:
                from canslim_monitor.data.repositories import PositionRepository
                repo = PositionRepository(session)
                positions = repo.get_in_position()  # state >= 1
                return positions
            finally:
                session.close()
        except Exception as e:
            self.logger.error(f"Error fetching active positions: {e}")
            return []
    
    def _get_prices(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get current prices and volume from realtime provider (or IBKR fallback)."""
        # Prefer provider abstraction — returns canonical Quote objects
        if self.realtime_provider and self.realtime_provider.is_connected():
            try:
                provider_quotes = self.realtime_provider.get_quotes(symbols)
                if provider_quotes:
                    price_data = {}
                    for symbol, quote in provider_quotes.items():
                        if quote:
                            qd = quote.to_dict()
                            if qd.get('last', 0) > 0:
                                price = qd['last']
                                volume = qd.get('volume', 0)
                                avg_volume = qd.get('avg_volume', 500000)
                                volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

                                max_price = self._max_prices.get(symbol, price)
                                if price > max_price:
                                    self._max_prices[symbol] = price
                                    max_price = price

                                price_data[symbol] = {
                                    'price': price,
                                    'volume_ratio': volume_ratio,
                                    'max_price': max_price,
                                    'max_gain_pct': self._max_gains.get(symbol, 0),
                                    'high': qd.get('high', price),
                                    'low': qd.get('low', price),
                                    'open': qd.get('open', price),
                                }
                    if price_data:
                        return price_data
            except Exception as e:
                self.logger.warning(f"Provider get_quotes failed: {e}, falling back to raw client")

        if not self.ibkr_client:
            return {}

        price_data = {}

        # Try batch quote first (more efficient)
        if hasattr(self.ibkr_client, 'get_quotes'):
            try:
                quotes = self.ibkr_client.get_quotes(symbols)
                for symbol, quote in quotes.items():
                    if quote and quote.get('last', 0) > 0:
                        price = quote['last']
                        volume = quote.get('volume', 0)
                        
                        # Calculate volume ratio using quote data
                        avg_volume = quote.get('avg_volume', 500000)
                        volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
                        
                        # Track max price for trailing stop
                        max_price = self._max_prices.get(symbol, price)
                        if price > max_price:
                            self._max_prices[symbol] = price
                            max_price = price
                        
                        price_data[symbol] = {
                            'price': price,
                            'volume_ratio': volume_ratio,
                            'max_price': max_price,
                            'max_gain_pct': self._max_gains.get(symbol, 0),
                            'high': quote.get('high', price),
                            'low': quote.get('low', price),
                            'open': quote.get('open', price),
                        }
                
                if price_data:
                    return price_data
                    
            except Exception as e:
                self.logger.warning(f"Batch quote failed: {e}, falling back to individual quotes")
        
        # Fallback to individual quotes
        for symbol in symbols:
            try:
                # Get real-time quote from IBKR
                if hasattr(self.ibkr_client, 'get_quote'):
                    quote = self.ibkr_client.get_quote(symbol)
                else:
                    self.logger.warning(f"IBKR client has no get_quote method")
                    continue
                    
                if quote and quote.get('last', 0) > 0:
                    price = quote['last']
                    volume = quote.get('volume', 0)
                    avg_volume = quote.get('avg_volume', 500000)
                    volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
                    
                    # Track max price for trailing stop
                    max_price = self._max_prices.get(symbol, price)
                    if price > max_price:
                        self._max_prices[symbol] = price
                        max_price = price
                    
                    price_data[symbol] = {
                        'price': price,
                        'volume_ratio': volume_ratio,
                        'max_price': max_price,
                        'max_gain_pct': self._max_gains.get(symbol, 0),
                        'high': quote.get('high', price),
                        'low': quote.get('low', price),
                        'open': quote.get('open', price),
                    }
                    
            except Exception as e:
                self.logger.debug(f"Could not get price for {symbol}: {e}")
        
        return price_data
    
    def _get_volume_ratio(self, symbol: str, current_volume: int = None) -> float:
        """
        Get current volume ratio (today's volume / 50-day avg).
        
        Uses TechnicalDataService for time-adjusted volume ratio calculation.
        """
        if current_volume is None:
            # Try to get from IBKR if available
            if self.ibkr_client:
                try:
                    # Some IBKR implementations provide volume
                    current_volume = getattr(self.ibkr_client, 'get_volume', lambda x: None)(symbol)
                except Exception:
                    pass
            
            if current_volume is None:
                return 1.0
        
        return self.technical_service.calculate_volume_ratio(
            symbol, 
            current_volume,
            use_time_adjusted=True
        )
    
    def _get_market_context(self) -> tuple:
        """
        Get current market regime and SPY price.

        Returns:
            Tuple of (market_regime: str, spy_price: float)
        """
        market_regime = ""
        spy_price = 0.0

        # Try to get market regime from database
        if self.db_session_factory:
            try:
                session = self.db_session_factory()
                try:
                    from canslim_monitor.regime.models_regime import MarketRegimeAlert
                    from sqlalchemy import desc

                    # Get most recent regime alert
                    latest = (
                        session.query(MarketRegimeAlert)
                        .order_by(desc(MarketRegimeAlert.date))
                        .first()
                    )
                    if latest and latest.regime:
                        market_regime = latest.regime.value
                finally:
                    session.close()
            except Exception as e:
                self.logger.debug(f"Could not fetch market regime: {e}")

        # Try to get SPY price from IBKR
        if self.ibkr_client:
            try:
                if hasattr(self.ibkr_client, 'get_quote'):
                    spy_quote = self.ibkr_client.get_quote('SPY')
                    if spy_quote and spy_quote.get('last', 0) > 0:
                        spy_price = spy_quote['last']
            except Exception as e:
                self.logger.debug(f"Could not fetch SPY price: {e}")

        return market_regime, spy_price

    def _get_technical_data(
        self,
        symbols: List[str],
        price_data: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get technical indicators for symbols from TechnicalDataService.
        
        Fetches MAs (21, 50, 200, 10-week) and volume data from Polygon.
        """
        # Batch fetch from TechnicalDataService
        technical_data = self.technical_service.get_multiple(symbols)
        
        # Log summary
        fetched = sum(1 for d in technical_data.values() if d.get('ma_50'))
        self.logger.debug(f"Technical data: {fetched}/{len(symbols)} symbols with MA50")
        
        return technical_data
    
    def _route_alerts(self, alerts: List):
        """Route alerts through AlertService with proper type mapping."""
        for alert in alerts:
            try:
                # Persist 8-week hold state if this alert activates it
                if alert.subtype == AlertSubtype.EIGHT_WEEK_HOLD:
                    self._persist_eight_week_hold(alert)

                # Route through AlertService for cooldown, suppression, Discord
                self.alert_service.create_alert(
                    symbol=alert.symbol,
                    alert_type=alert.alert_type,
                    subtype=alert.subtype,
                    context=alert.context,
                    position_id=alert.position_id,
                    message=alert.message,
                    action=alert.action,
                    thread_source=alert.thread_source or "position_thread",
                )

            except Exception as e:
                self.logger.error(f"Failed to route alert: {e}")

    def _persist_eight_week_hold(self, alert: AlertData):
        """
        Persist 8-week hold activation to the database.

        Position objects are detached from SQLAlchemy by the time alerts fire,
        so we open a fresh session here to write the hold state.
        """
        metadata = getattr(alert, '_eight_week_metadata', None)
        if not metadata or not alert.position_id:
            return

        if not self.db_session_factory:
            self.logger.warning("No DB session factory - cannot persist 8-week hold")
            return

        try:
            session = self.db_session_factory()
            try:
                from canslim_monitor.data.models import Position
                position = session.query(Position).get(alert.position_id)
                if position:
                    position.eight_week_hold_active = True
                    position.eight_week_hold_start = metadata['hold_start']
                    position.eight_week_hold_end = metadata['hold_end']
                    position.eight_week_power_move_pct = metadata['power_move_pct']
                    position.eight_week_power_move_weeks = metadata['power_move_weeks']
                    session.commit()
                    self.logger.info(
                        f"8-week hold persisted for {alert.symbol} "
                        f"(+{metadata['power_move_pct']:.1f}% in {metadata['power_move_weeks']:.1f}w, "
                        f"hold until {metadata['hold_end']})"
                    )
                else:
                    self.logger.warning(
                        f"Position {alert.position_id} not found for 8-week hold persist"
                    )
            finally:
                session.close()
        except Exception as e:
            self.logger.error(f"Error persisting 8-week hold for {alert.symbol}: {e}")
    
    def _update_position_tracking(
        self,
        positions: List,
        price_data: Dict[str, Dict[str, Any]],
    ):
        """Update position tracking fields in database."""
        if not self.db_session_factory:
            return
        
        try:
            session = self.db_session_factory()
            try:
                from canslim_monitor.data.repositories import PositionRepository
                repo = PositionRepository(session)
                
                for position in positions:
                    symbol = position.symbol
                    price_info = price_data.get(symbol, {})
                    price = price_info.get('price')
                    
                    if price:
                        # Update last price
                        repo.update_price(position, price, datetime.now())
                        
                        # Update max gain tracking
                        # Use avg_cost if set, otherwise fall back to e1_price
                        cost_basis = position.avg_cost or position.e1_price
                        if cost_basis and cost_basis > 0:
                            gain_pct = ((price - cost_basis) / cost_basis) * 100
                            current_max = self._max_gains.get(symbol, 0)
                            if gain_pct > current_max:
                                self._max_gains[symbol] = gain_pct
                
                session.commit()
                
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error(f"Error updating position tracking: {e}")
    
    def reset_tracking(self, symbol: str = None):
        """
        Reset max price/gain tracking.
        
        Call when position is closed or state changes.
        """
        if symbol:
            self._max_prices.pop(symbol, None)
            self._max_gains.pop(symbol, None)
        else:
            self._max_prices.clear()
            self._max_gains.clear()
