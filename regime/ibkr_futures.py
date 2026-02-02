"""
CANSLIM Monitor - IBKR Futures Data
====================================
Fetches overnight futures data (ES, NQ, YM) from IBKR for market regime analysis.

Provides percentage change from Globex session open (6 PM ET) for:
- ES (E-mini S&P 500) - CME
- NQ (E-mini NASDAQ 100) - CME  
- YM (E-mini Dow) - CBOT

Integrates with ThreadSafeIBKRClient for use in the regime thread.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any

import pytz

logger = logging.getLogger('canslim.regime')

# Futures contract specifications
FUTURES_CONTRACTS = {
    'ES': {'symbol': 'ES', 'exchange': 'CME', 'currency': 'USD'},
    'NQ': {'symbol': 'NQ', 'exchange': 'CME', 'currency': 'USD'},
    'YM': {'symbol': 'YM', 'exchange': 'CBOT', 'currency': 'USD'}
}

# Globex session timing
SESSION_OPEN_HOUR = 18  # 6 PM ET
ET_TIMEZONE = pytz.timezone('America/New_York')


def get_futures_snapshot(ibkr_client) -> Tuple[float, float, float]:
    """
    Get overnight futures percentage changes from IBKR.

    Calculates change from 6 PM ET Globex session open to current price.

    Args:
        ibkr_client: ThreadSafeIBKRClient instance

    Returns:
        Tuple of (ES change %, NQ change %, YM change %)
        Returns (0.0, 0.0, 0.0) if data unavailable
    """
    logger.info("Getting futures snapshot...")

    if not ibkr_client:
        logger.warning("IBKR client is None - cannot get futures data")
        return (0.0, 0.0, 0.0)

    if not ibkr_client.is_connected():
        logger.warning("IBKR not connected - cannot get futures data")
        return (0.0, 0.0, 0.0)

    try:
        # Get session open time
        now_et = datetime.now(ET_TIMEZONE)
        session_open_time = _get_session_open_time(now_et)
        front_month = _get_front_month()

        logger.info(f"Fetching futures: now={now_et.strftime('%Y-%m-%d %H:%M')}, "
                   f"session_open={session_open_time.strftime('%Y-%m-%d %H:%M')}, "
                   f"front_month={front_month}")

        # Get quotes for each futures contract
        es_change = _get_futures_change(ibkr_client, 'ES', session_open_time)
        nq_change = _get_futures_change(ibkr_client, 'NQ', session_open_time)
        ym_change = _get_futures_change(ibkr_client, 'YM', session_open_time)

        logger.info(f"Futures result: ES={es_change:+.2f}%, NQ={nq_change:+.2f}%, YM={ym_change:+.2f}%")

        return (es_change, nq_change, ym_change)

    except Exception as e:
        logger.error(f"Error fetching futures data: {e}", exc_info=True)
        return (0.0, 0.0, 0.0)


def _get_session_open_time(now_et: datetime) -> datetime:
    """
    Get the Globex session open time for the current overnight session.
    
    Handles:
    - After 6 PM: Session opened today at 6 PM
    - Before 6 PM weekday: Session opened yesterday at 6 PM
    - Monday before 6 PM: Session opened Sunday at 6 PM
    """
    weekday = now_et.weekday()
    
    if now_et.hour >= SESSION_OPEN_HOUR:
        # After 6 PM - session opened today
        return now_et.replace(
            hour=SESSION_OPEN_HOUR,
            minute=0,
            second=0,
            microsecond=0
        )
    elif weekday == 0:  # Monday
        # Session opened Sunday 6 PM
        sunday = now_et - timedelta(days=1)
        return sunday.replace(
            hour=SESSION_OPEN_HOUR,
            minute=0,
            second=0,
            microsecond=0
        )
    else:
        # Session opened previous day 6 PM
        yesterday = now_et - timedelta(days=1)
        return yesterday.replace(
            hour=SESSION_OPEN_HOUR,
            minute=0,
            second=0,
            microsecond=0
        )


def _get_front_month() -> str:
    """
    Get the front month contract code for quarterly futures.
    
    ES/NQ/YM follow quarterly cycle: H (Mar), M (Jun), U (Sep), Z (Dec)
    Returns format: YYYYMM
    """
    now = datetime.now()
    year = now.year
    month = now.month
    
    # Quarterly months: March (3), June (6), September (9), December (12)
    quarterly = [3, 6, 9, 12]
    
    # Find next quarterly month
    for q in quarterly:
        if month <= q:
            # If we're in the expiration month, check if past 3rd Friday
            if month == q and now.day > 15:
                continue
            return f"{year}{q:02d}"
    
    # Roll to March of next year
    return f"{year + 1}03"


def _get_futures_change(ibkr_client, symbol: str, session_open_time: datetime) -> float:
    """
    Get percentage change for a futures contract from session open.

    Args:
        ibkr_client: ThreadSafeIBKRClient instance
        symbol: 'ES', 'NQ', or 'YM'
        session_open_time: Datetime of session open (6 PM ET)

    Returns:
        Percentage change from session open, or 0.0 if unavailable
    """
    try:
        # Verify IBKR client internals are accessible
        if not hasattr(ibkr_client, '_ib') or not hasattr(ibkr_client, '_loop'):
            logger.warning(f"IBKR client missing _ib or _loop attributes")
            return 0.0

        if ibkr_client._loop is None or not ibkr_client._loop.is_running():
            logger.warning(f"IBKR event loop not running")
            return 0.0

        # Run the async operation in the IBKR client's event loop
        # Increased timeout to 30s since we now wait up to 5s for market data
        future = asyncio.run_coroutine_threadsafe(
            _async_get_futures_change(ibkr_client._ib, symbol, session_open_time),
            ibkr_client._loop
        )
        return future.result(timeout=30.0)

    except asyncio.TimeoutError:
        logger.warning(f"Timeout getting {symbol} futures change")
        return 0.0
    except Exception as e:
        logger.warning(f"Error getting {symbol} change: {e}", exc_info=True)
        return 0.0


async def _async_get_futures_change(ib, symbol: str, session_open_time: datetime) -> float:
    """
    Async operation to get futures change from session open.

    Uses historical data to find the session open price, then compares
    to current market price.
    """
    from ib_insync import Future

    spec = FUTURES_CONTRACTS.get(symbol)
    if not spec:
        logger.warning(f"Unknown futures symbol: {symbol}")
        return 0.0

    try:
        # Get front month contract
        front_month = _get_front_month()
        logger.debug(f"{symbol}: Using front month {front_month}")

        contract = Future(
            symbol=spec['symbol'],
            exchange=spec['exchange'],
            currency=spec['currency'],
            lastTradeDateOrContractMonth=front_month
        )

        # Qualify the contract
        qualified = await ib.qualifyContractsAsync(contract)

        if not qualified or not contract.conId:
            logger.warning(f"Could not qualify contract for {symbol} (front_month={front_month})")
            return 0.0

        logger.debug(f"Qualified {symbol} contract: {contract.localSymbol}, conId={contract.conId}")

        # Get current price via market data - use streaming mode, not snapshot
        # Snapshot mode (True) can be unreliable for futures
        ticker = ib.reqMktData(contract, '', False, False)  # streaming mode

        # Wait for data with retries - futures may need more time
        current_price = 0.0
        for attempt in range(5):  # Try for up to 5 seconds
            await asyncio.sleep(1.0)

            def safe_float(val, default=0.0):
                if val is None or (isinstance(val, float) and val != val):  # NaN check
                    return default
                return float(val)

            # Try last price first
            current_price = safe_float(ticker.last)
            if current_price > 0:
                logger.debug(f"{symbol}: Got last price {current_price} on attempt {attempt+1}")
                break

            # Try close price
            current_price = safe_float(ticker.close)
            if current_price > 0:
                logger.debug(f"{symbol}: Got close price {current_price} on attempt {attempt+1}")
                break

            # Try bid/ask midpoint
            bid = safe_float(ticker.bid)
            ask = safe_float(ticker.ask)
            if bid > 0 and ask > 0:
                current_price = (bid + ask) / 2
                logger.debug(f"{symbol}: Got bid/ask midpoint {current_price} on attempt {attempt+1}")
                break

            logger.debug(f"{symbol}: No price on attempt {attempt+1}, last={ticker.last}, bid={ticker.bid}, ask={ticker.ask}")

        # Cancel market data
        ib.cancelMktData(contract)

        if current_price <= 0:
            logger.warning(f"No current price for {symbol} after 5 attempts")
            return 0.0

        # Get session open price from historical data
        session_open_price = await _get_session_open_price(ib, contract, session_open_time)

        if session_open_price is None or session_open_price <= 0:
            logger.warning(f"Could not get session open price for {symbol}")
            return 0.0

        # Calculate percentage change
        change_pct = ((current_price - session_open_price) / session_open_price) * 100.0

        logger.info(f"{symbol}: Open={session_open_price:.2f}, Current={current_price:.2f}, Change={change_pct:+.2f}%")

        return round(change_pct, 2)

    except Exception as e:
        logger.warning(f"Error in async futures fetch for {symbol}: {e}", exc_info=True)
        return 0.0


async def _get_session_open_price(ib, contract, session_open_time: datetime) -> Optional[float]:
    """
    Get the price at Globex session open using historical data.

    Fetches hourly bars and finds the bar at or near the 6 PM session open.
    """
    try:
        logger.debug(f"Fetching session open price for {contract.symbol}, session_open={session_open_time}")

        # Request historical data for the past 2 days to ensure we have the session open
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime='',  # Current time
            durationStr='2 D',  # 2 days to ensure we capture session open
            barSizeSetting='1 hour',
            whatToShow='TRADES',
            useRTH=False  # Include extended/overnight hours
        )

        if not bars:
            logger.warning(f"No historical bars returned for {contract.symbol}")
            return None

        logger.debug(f"Got {len(bars)} historical bars for {contract.symbol}")

        # Find the bar at or closest to session open hour (6 PM) on the correct day
        session_open_hour = session_open_time.hour
        session_open_date = session_open_time.date()

        # First pass: look for exact match
        for bar in bars:
            bar_time = bar.date

            # Handle timezone conversion if needed
            if hasattr(bar_time, 'astimezone'):
                bar_time_et = bar_time.astimezone(ET_TIMEZONE)
            elif hasattr(bar_time, 'tzinfo') and bar_time.tzinfo is None:
                # Assume ET if no timezone
                bar_time_et = ET_TIMEZONE.localize(bar_time)
            else:
                bar_time_et = bar_time

            # Check if this bar is at the session open hour and date
            if bar_time_et.hour == session_open_hour and bar_time_et.date() == session_open_date:
                logger.debug(f"Found exact session open bar: {bar_time_et} -> {bar.open}")
                return bar.open

        # Second pass: find closest bar after session open
        logger.debug(f"Exact session open not found, searching for closest bar after {session_open_time}")
        for bar in bars:
            bar_time = bar.date
            if hasattr(bar_time, 'astimezone'):
                bar_time_et = bar_time.astimezone(ET_TIMEZONE)
            elif hasattr(bar_time, 'tzinfo') and bar_time.tzinfo is None:
                bar_time_et = ET_TIMEZONE.localize(bar_time)
            else:
                bar_time_et = bar_time

            # Use first bar that's at or after session open time
            if bar_time_et >= session_open_time:
                logger.debug(f"Using nearest bar after session open: {bar_time_et} -> {bar.open}")
                return bar.open

        # Last resort: use the earliest bar available
        if bars:
            first_bar = bars[0]
            logger.warning(f"Session open bar not found for {contract.symbol}, using first available bar: {first_bar.date} -> {first_bar.open}")
            return first_bar.open

        return None

    except Exception as e:
        logger.warning(f"Error getting session open price for {contract.symbol}: {e}", exc_info=True)
        return None

