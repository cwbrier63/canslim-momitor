"""
CANSLIM Monitor - Market Calendar (Polygon/Massive API)
Phase 2: Service Architecture

Uses Polygon.io (now Massive.com) API for market status and holidays:
- /v1/marketstatus/now - Real-time market status
- /v1/marketstatus/upcoming - Upcoming market holidays

Falls back to hardcoded calendar when API is unavailable.
"""

import logging
import requests
from datetime import date, datetime, time as dt_time, timedelta
from typing import Optional, Set, Tuple, List, Dict, Any
from threading import Lock
import pytz


class MarketCalendar:
    """
    US stock market calendar using Polygon/Massive API.
    
    Features:
    - Real-time market status from API
    - Upcoming holidays from API
    - Caching to minimize API calls
    - Fallback to hardcoded calendar when API unavailable
    """
    
    # API Configuration
    BASE_URL = "https://api.polygon.io"
    STATUS_ENDPOINT = "/v1/marketstatus/now"
    HOLIDAYS_ENDPOINT = "/v1/marketstatus/upcoming"
    
    # Regular market hours (ET) - used for fallback
    REGULAR_OPEN = dt_time(9, 30)
    REGULAR_CLOSE = dt_time(16, 0)
    EARLY_CLOSE = dt_time(13, 0)
    
    # Extended hours
    PREMARKET_OPEN = dt_time(4, 0)
    AFTERHOURS_CLOSE = dt_time(20, 0)
    
    # Cache settings
    STATUS_CACHE_SECONDS = 60  # Cache status for 1 minute
    HOLIDAYS_CACHE_SECONDS = 3600  # Cache holidays for 1 hour
    
    def __init__(
        self,
        api_key: str = None,
        timezone: str = 'America/New_York',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize market calendar.
        
        Args:
            api_key: Polygon.io/Massive API key
            timezone: Market timezone (default: US Eastern)
            logger: Logger instance
        """
        self.api_key = api_key
        self.timezone = pytz.timezone(timezone)
        self.logger = logger or logging.getLogger('canslim.market_calendar')
        
        # Cache
        self._status_cache: Optional[Dict] = None
        self._status_cache_time: Optional[datetime] = None
        self._holidays_cache: Optional[List[Dict]] = None
        self._holidays_cache_time: Optional[datetime] = None
        self._lock = Lock()
        
        # Fallback holiday cache (computed)
        self._fallback_holidays: Dict[int, Set[date]] = {}
        self._fallback_early_close: Dict[int, Set[date]] = {}
    
    # ==================== PUBLIC API ====================
    
    def is_market_open(self, dt: datetime = None) -> bool:
        """
        Check if market is currently open using API.
        
        Args:
            dt: Datetime to check (default: now). Note: API only returns current status.
            
        Returns:
            True if market is open for regular trading
        """
        # If checking a specific time that's not now, use fallback
        if dt is not None:
            if dt.tzinfo is None:
                dt = self.timezone.localize(dt)
            else:
                dt = dt.astimezone(self.timezone)
            
            now = datetime.now(self.timezone)
            # If checking more than 5 minutes from now, use fallback
            if abs((dt - now).total_seconds()) > 300:
                return self._is_market_open_fallback(dt)
        
        # Use API for current status
        status = self._get_market_status()
        
        if status:
            # Check exchanges status
            exchanges = status.get('exchanges', {})
            nyse_status = exchanges.get('nyse', '')
            nasdaq_status = exchanges.get('nasdaq', '')
            
            # Market is open if either major exchange is open
            return nyse_status == 'open' or nasdaq_status == 'open'
        
        # Fallback to computed calendar
        return self._is_market_open_fallback(dt)
    
    def is_trading_day(self, d: date = None) -> bool:
        """
        Check if a date is a trading day.
        
        Args:
            d: Date to check (default: today)
            
        Returns:
            True if market is open on this date
        """
        if d is None:
            d = datetime.now(self.timezone).date()
        
        # Weekend check
        if d.weekday() >= 5:
            return False
        
        # Holiday check
        if self.is_holiday(d):
            return False
        
        return True
    
    def is_holiday(self, d: date) -> bool:
        """
        Check if a date is a market holiday.
        
        Args:
            d: Date to check
            
        Returns:
            True if market is closed for holiday
        """
        holidays = self._get_holidays()
        
        if holidays:
            for holiday in holidays:
                holiday_date = self._parse_date(holiday.get('date'))
                if holiday_date == d:
                    status = holiday.get('status', '')
                    return status == 'closed'
        
        # Fallback to computed calendar
        return self._is_holiday_fallback(d)
    
    def is_early_close(self, d: date) -> bool:
        """
        Check if a date is an early close day.
        
        Args:
            d: Date to check
            
        Returns:
            True if market closes early (typically 1:00 PM ET)
        """
        holidays = self._get_holidays()
        
        if holidays:
            for holiday in holidays:
                holiday_date = self._parse_date(holiday.get('date'))
                if holiday_date == d:
                    status = holiday.get('status', '')
                    close_time = holiday.get('close')
                    # Early close if status is 'early-close' or close time is before 16:00
                    if status == 'early-close':
                        return True
                    if close_time and self._parse_time(close_time) < self.REGULAR_CLOSE:
                        return True
        
        # Fallback to computed calendar
        return self._is_early_close_fallback(d)
    
    def get_market_hours(self, d: date = None) -> Tuple[Optional[dt_time], Optional[dt_time]]:
        """
        Get market hours for a specific date.
        
        Args:
            d: Date to check (default: today)
            
        Returns:
            Tuple of (open_time, close_time) or (None, None) if closed
        """
        if d is None:
            d = datetime.now(self.timezone).date()
        
        if not self.is_trading_day(d):
            return (None, None)
        
        # Check holidays for special hours
        holidays = self._get_holidays()
        
        if holidays:
            for holiday in holidays:
                holiday_date = self._parse_date(holiday.get('date'))
                if holiday_date == d:
                    open_time = holiday.get('open')
                    close_time = holiday.get('close')
                    
                    if open_time and close_time:
                        return (
                            self._parse_time(open_time),
                            self._parse_time(close_time)
                        )
        
        # Regular hours or early close
        close_time = self.EARLY_CLOSE if self.is_early_close(d) else self.REGULAR_CLOSE
        return (self.REGULAR_OPEN, close_time)
    
    def get_market_status(self) -> Dict[str, Any]:
        """
        Get comprehensive current market status.
        
        Returns:
            Dict with market status details
        """
        status = self._get_market_status()
        
        if status:
            return {
                'market': status.get('market', 'unknown'),
                'nyse': status.get('exchanges', {}).get('nyse', 'unknown'),
                'nasdaq': status.get('exchanges', {}).get('nasdaq', 'unknown'),
                'otc': status.get('exchanges', {}).get('otc', 'unknown'),
                'early_hours': status.get('earlyHours', False),
                'after_hours': status.get('afterHours', False),
                'server_time': status.get('serverTime'),
                'source': 'api'
            }
        
        # Fallback response
        is_open = self._is_market_open_fallback()
        return {
            'market': 'open' if is_open else 'closed',
            'nyse': 'open' if is_open else 'closed',
            'nasdaq': 'open' if is_open else 'closed',
            'source': 'fallback'
        }
    
    def get_upcoming_holidays(self) -> List[Dict[str, Any]]:
        """
        Get list of upcoming market holidays.
        
        Returns:
            List of holiday dicts with date, name, status, open/close times
        """
        holidays = self._get_holidays()
        
        if holidays:
            result = []
            for h in holidays:
                # Only include stock market holidays
                if h.get('exchange') in (None, 'NYSE', 'NASDAQ', 'XNYS', 'XNAS'):
                    result.append({
                        'date': h.get('date'),
                        'name': h.get('name'),
                        'status': h.get('status'),
                        'open': h.get('open'),
                        'close': h.get('close'),
                        'source': 'api'
                    })
            return result
        
        # Fallback - return next 30 days of holidays
        return self._get_fallback_upcoming_holidays()
    
    def next_trading_day(self, d: date = None) -> date:
        """
        Get the next trading day.
        
        Args:
            d: Starting date (default: today)
            
        Returns:
            Next date when market is open
        """
        if d is None:
            d = datetime.now(self.timezone).date()
        
        next_day = d + timedelta(days=1)
        
        for _ in range(10):
            if self.is_trading_day(next_day):
                return next_day
            next_day += timedelta(days=1)
        
        return next_day
    
    def previous_trading_day(self, d: date = None) -> date:
        """
        Get the previous trading day.
        
        Args:
            d: Starting date (default: today)
            
        Returns:
            Previous date when market was open
        """
        if d is None:
            d = datetime.now(self.timezone).date()
        
        prev_day = d - timedelta(days=1)
        
        for _ in range(10):
            if self.is_trading_day(prev_day):
                return prev_day
            prev_day -= timedelta(days=1)
        
        return prev_day
    
    def seconds_until_open(self, dt: datetime = None) -> int:
        """Get seconds until market opens (0 if already open)."""
        if dt is None:
            dt = datetime.now(self.timezone)
        elif dt.tzinfo is None:
            dt = self.timezone.localize(dt)
        else:
            dt = dt.astimezone(self.timezone)
        
        if self.is_market_open():
            return 0
        
        # Find next trading day
        check_date = dt.date()
        current_time = dt.time()
        
        if self.is_trading_day(check_date) and current_time < self.REGULAR_OPEN:
            open_dt = self.timezone.localize(
                datetime.combine(check_date, self.REGULAR_OPEN)
            )
        else:
            next_day = self.next_trading_day(check_date)
            open_dt = self.timezone.localize(
                datetime.combine(next_day, self.REGULAR_OPEN)
            )
        
        delta = open_dt - dt
        return max(0, int(delta.total_seconds()))
    
    def seconds_until_close(self, dt: datetime = None) -> int:
        """Get seconds until market closes (0 if already closed)."""
        if dt is None:
            dt = datetime.now(self.timezone)
        elif dt.tzinfo is None:
            dt = self.timezone.localize(dt)
        else:
            dt = dt.astimezone(self.timezone)
        
        if not self.is_market_open():
            return 0
        
        open_time, close_time = self.get_market_hours(dt.date())
        if close_time is None:
            return 0
        
        close_dt = self.timezone.localize(
            datetime.combine(dt.date(), close_time)
        )
        
        delta = close_dt - dt
        return max(0, int(delta.total_seconds()))
    
    # ==================== API METHODS ====================
    
    def _get_market_status(self) -> Optional[Dict]:
        """
        Fetch current market status from API with caching.
        
        Returns:
            Market status dict or None if unavailable
        """
        if not self.api_key:
            return None
        
        with self._lock:
            # Check cache
            if self._status_cache and self._status_cache_time:
                elapsed = (datetime.now() - self._status_cache_time).total_seconds()
                if elapsed < self.STATUS_CACHE_SECONDS:
                    return self._status_cache
            
            # Fetch from API
            try:
                url = f"{self.BASE_URL}{self.STATUS_ENDPOINT}"
                params = {'apiKey': self.api_key}
                
                response = requests.get(url, params=params, timeout=5)
                response.raise_for_status()
                
                data = response.json()
                
                self._status_cache = data
                self._status_cache_time = datetime.now()
                
                return data
                
            except Exception as e:
                self.logger.warning(f"Failed to fetch market status: {e}")
                return self._status_cache  # Return stale cache if available
    
    def _get_holidays(self) -> Optional[List[Dict]]:
        """
        Fetch upcoming holidays from API with caching.
        
        Returns:
            List of holiday dicts or None if unavailable
        """
        if not self.api_key:
            return None
        
        with self._lock:
            # Check cache
            if self._holidays_cache and self._holidays_cache_time:
                elapsed = (datetime.now() - self._holidays_cache_time).total_seconds()
                if elapsed < self.HOLIDAYS_CACHE_SECONDS:
                    return self._holidays_cache
            
            # Fetch from API
            try:
                url = f"{self.BASE_URL}{self.HOLIDAYS_ENDPOINT}"
                params = {'apiKey': self.api_key}
                
                response = requests.get(url, params=params, timeout=5)
                response.raise_for_status()
                
                data = response.json()
                
                self._holidays_cache = data
                self._holidays_cache_time = datetime.now()
                
                return data
                
            except Exception as e:
                self.logger.warning(f"Failed to fetch market holidays: {e}")
                return self._holidays_cache  # Return stale cache if available
    
    # ==================== FALLBACK METHODS ====================
    
    def _is_market_open_fallback(self, dt: datetime = None) -> bool:
        """Fallback market hours check using hardcoded calendar."""
        if dt is None:
            dt = datetime.now(self.timezone)
        elif dt.tzinfo is None:
            dt = self.timezone.localize(dt)
        else:
            dt = dt.astimezone(self.timezone)
        
        # Weekend check
        if dt.weekday() >= 5:
            return False
        
        # Holiday check
        if self._is_holiday_fallback(dt.date()):
            return False
        
        # Time check
        current_time = dt.time()
        close_time = self.EARLY_CLOSE if self._is_early_close_fallback(dt.date()) else self.REGULAR_CLOSE
        
        return self.REGULAR_OPEN <= current_time <= close_time
    
    def _is_holiday_fallback(self, d: date) -> bool:
        """Fallback holiday check using hardcoded calendar."""
        holidays = self._get_fallback_holidays(d.year)
        if d in holidays:
            return True
        
        # Handle cross-year edge case
        if d.month == 12 and d.day == 31:
            next_year_holidays = self._get_fallback_holidays(d.year + 1)
            if d in next_year_holidays:
                return True
        
        return False
    
    def _is_early_close_fallback(self, d: date) -> bool:
        """Fallback early close check using hardcoded calendar."""
        early_close = self._get_fallback_early_close(d.year)
        return d in early_close
    
    def _get_fallback_holidays(self, year: int) -> Set[date]:
        """Get hardcoded holidays for a year."""
        if year in self._fallback_holidays:
            return self._fallback_holidays[year]
        
        holidays = set()
        
        # New Year's Day
        holidays.add(self._observe_holiday(date(year, 1, 1)))
        
        # MLK Day (3rd Monday in January)
        holidays.add(self._nth_weekday(year, 1, 0, 3))
        
        # Presidents Day (3rd Monday in February)
        holidays.add(self._nth_weekday(year, 2, 0, 3))
        
        # Good Friday
        holidays.add(self._good_friday(year))
        
        # Memorial Day (Last Monday in May)
        holidays.add(self._last_weekday(year, 5, 0))
        
        # Juneteenth (since 2022)
        if year >= 2022:
            holidays.add(self._observe_holiday(date(year, 6, 19)))
        
        # Independence Day
        holidays.add(self._observe_holiday(date(year, 7, 4)))
        
        # Labor Day (1st Monday in September)
        holidays.add(self._nth_weekday(year, 9, 0, 1))
        
        # Thanksgiving (4th Thursday in November)
        holidays.add(self._nth_weekday(year, 11, 3, 4))
        
        # Christmas
        holidays.add(self._observe_holiday(date(year, 12, 25)))
        
        self._fallback_holidays[year] = holidays
        return holidays
    
    def _get_fallback_early_close(self, year: int) -> Set[date]:
        """Get hardcoded early close days for a year."""
        if year in self._fallback_early_close:
            return self._fallback_early_close[year]
        
        early_close = set()
        holidays = self._get_fallback_holidays(year)
        
        # Day before Independence Day
        july_3 = date(year, 7, 3)
        if july_3 not in holidays and july_3.weekday() < 5:
            early_close.add(july_3)
        
        # Black Friday
        thanksgiving = self._nth_weekday(year, 11, 3, 4)
        early_close.add(thanksgiving + timedelta(days=1))
        
        # Christmas Eve
        christmas_eve = date(year, 12, 24)
        if christmas_eve not in holidays and christmas_eve.weekday() < 5:
            early_close.add(christmas_eve)
        
        self._fallback_early_close[year] = early_close
        return early_close
    
    def _get_fallback_upcoming_holidays(self) -> List[Dict]:
        """Get hardcoded upcoming holidays."""
        today = datetime.now(self.timezone).date()
        result = []
        
        for year in [today.year, today.year + 1]:
            holidays = self._get_fallback_holidays(year)
            early_close = self._get_fallback_early_close(year)
            
            for h in sorted(holidays):
                if h >= today:
                    result.append({
                        'date': h.isoformat(),
                        'name': 'Market Holiday',
                        'status': 'closed',
                        'source': 'fallback'
                    })
            
            for e in sorted(early_close):
                if e >= today and e not in holidays:
                    result.append({
                        'date': e.isoformat(),
                        'name': 'Early Close',
                        'status': 'early-close',
                        'open': '09:30',
                        'close': '13:00',
                        'source': 'fallback'
                    })
        
        return sorted(result, key=lambda x: x['date'])[:20]
    
    # ==================== HELPER METHODS ====================
    
    def _observe_holiday(self, d: date) -> date:
        """Get observed date for holiday (Sat->Fri, Sun->Mon)."""
        if d.weekday() == 5:  # Saturday
            return d - timedelta(days=1)
        elif d.weekday() == 6:  # Sunday
            return d + timedelta(days=1)
        return d
    
    def _nth_weekday(self, year: int, month: int, weekday: int, n: int) -> date:
        """Get nth occurrence of weekday in month."""
        first_day = date(year, month, 1)
        days_ahead = weekday - first_day.weekday()
        if days_ahead < 0:
            days_ahead += 7
        first_occurrence = first_day + timedelta(days=days_ahead)
        return first_occurrence + timedelta(weeks=n-1)
    
    def _last_weekday(self, year: int, month: int, weekday: int) -> date:
        """Get last occurrence of weekday in month."""
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        
        days_back = last_day.weekday() - weekday
        if days_back < 0:
            days_back += 7
        return last_day - timedelta(days=days_back)
    
    def _good_friday(self, year: int) -> date:
        """Calculate Good Friday using Easter algorithm."""
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        easter = date(year, month, day)
        return easter - timedelta(days=2)
    
    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string to date object."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        except:
            return None
    
    def _parse_time(self, time_str: str) -> Optional[dt_time]:
        """Parse time string to time object."""
        if not time_str:
            return None
        try:
            # Handle various formats
            if 'T' in time_str:
                time_str = time_str.split('T')[1][:5]
            return datetime.strptime(time_str[:5], '%H:%M').time()
        except:
            return None
    
    def clear_cache(self):
        """Clear all cached data."""
        with self._lock:
            self._status_cache = None
            self._status_cache_time = None
            self._holidays_cache = None
            self._holidays_cache_time = None


# Singleton instance
_calendar: Optional[MarketCalendar] = None
_calendar_api_key: Optional[str] = None


def get_market_calendar(api_key: str = None) -> MarketCalendar:
    """
    Get the singleton market calendar instance.
    
    Args:
        api_key: Polygon.io API key (only used on first call)
        
    Returns:
        MarketCalendar instance
    """
    global _calendar, _calendar_api_key
    
    if _calendar is None or (api_key and api_key != _calendar_api_key):
        _calendar = MarketCalendar(api_key=api_key)
        _calendar_api_key = api_key
    
    return _calendar


def init_market_calendar(api_key: str) -> MarketCalendar:
    """
    Initialize market calendar with API key.
    
    Args:
        api_key: Polygon.io API key
        
    Returns:
        MarketCalendar instance
    """
    return get_market_calendar(api_key=api_key)
