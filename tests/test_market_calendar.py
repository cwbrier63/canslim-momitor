"""
CANSLIM Monitor - Market Calendar Tests
Tests for market hours and holiday detection.

Tests both API-based and fallback calendar functionality.
"""

import unittest
from datetime import date, datetime, time as dt_time
from unittest.mock import patch, Mock
import pytz

# Add project root to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from canslim_monitor.utils.market_calendar import MarketCalendar, get_market_calendar, init_market_calendar


class TestMarketCalendarFallback(unittest.TestCase):
    """Test market calendar fallback functionality (no API key)."""
    
    def setUp(self):
        """Set up test fixtures - calendar without API key uses fallback."""
        self.calendar = MarketCalendar(api_key=None)
        self.tz = pytz.timezone('America/New_York')
    
    def test_regular_trading_day(self):
        """Test regular trading day detection."""
        # Wednesday January 8, 2025 - regular trading day
        d = date(2025, 1, 8)
        self.assertTrue(self.calendar.is_trading_day(d))
    
    def test_weekend_not_trading(self):
        """Test weekends are not trading days."""
        # Saturday January 11, 2025
        saturday = date(2025, 1, 11)
        self.assertFalse(self.calendar.is_trading_day(saturday))
        
        # Sunday January 12, 2025
        sunday = date(2025, 1, 12)
        self.assertFalse(self.calendar.is_trading_day(sunday))
    
    def test_new_years_day_holiday(self):
        """Test New Year's Day holiday."""
        # January 1, 2025 is Wednesday - holiday
        self.assertTrue(self.calendar.is_holiday(date(2025, 1, 1)))
        self.assertFalse(self.calendar.is_trading_day(date(2025, 1, 1)))
    
    def test_new_years_weekend_observed(self):
        """Test New Year's Day weekend observation."""
        # January 1, 2028 is Saturday - Friday Dec 31, 2027 observed
        self.assertTrue(self.calendar.is_holiday(date(2027, 12, 31)))
        
        # January 1, 2023 is Sunday - Monday Jan 2, 2023 observed
        self.assertTrue(self.calendar.is_holiday(date(2023, 1, 2)))
    
    def test_mlk_day(self):
        """Test Martin Luther King Jr. Day (3rd Monday in January)."""
        # 2025: January 20
        mlk_2025 = date(2025, 1, 20)
        self.assertTrue(self.calendar.is_holiday(mlk_2025))
        
        # 2026: January 19
        mlk_2026 = date(2026, 1, 19)
        self.assertTrue(self.calendar.is_holiday(mlk_2026))
    
    def test_presidents_day(self):
        """Test Presidents Day (3rd Monday in February)."""
        # 2025: February 17
        pres_2025 = date(2025, 2, 17)
        self.assertTrue(self.calendar.is_holiday(pres_2025))
    
    def test_good_friday(self):
        """Test Good Friday holiday."""
        # 2025: April 18
        gf_2025 = date(2025, 4, 18)
        self.assertTrue(self.calendar.is_holiday(gf_2025))
        
        # 2026: April 3
        gf_2026 = date(2026, 4, 3)
        self.assertTrue(self.calendar.is_holiday(gf_2026))
    
    def test_memorial_day(self):
        """Test Memorial Day (last Monday in May)."""
        # 2025: May 26
        mem_2025 = date(2025, 5, 26)
        self.assertTrue(self.calendar.is_holiday(mem_2025))
    
    def test_juneteenth(self):
        """Test Juneteenth (June 19, observed starting 2022)."""
        # 2025: June 19 is Thursday
        self.assertTrue(self.calendar.is_holiday(date(2025, 6, 19)))
        
        # 2021: Not yet observed
        self.assertFalse(self.calendar.is_holiday(date(2021, 6, 19)))
        
        # 2027: June 19 is Saturday - Friday June 18 observed
        self.assertTrue(self.calendar.is_holiday(date(2027, 6, 18)))
    
    def test_independence_day(self):
        """Test Independence Day (July 4)."""
        # 2025: July 4 is Friday
        self.assertTrue(self.calendar.is_holiday(date(2025, 7, 4)))
        
        # 2026: July 4 is Saturday - Friday July 3 observed
        self.assertTrue(self.calendar.is_holiday(date(2026, 7, 3)))
    
    def test_labor_day(self):
        """Test Labor Day (1st Monday in September)."""
        # 2025: September 1
        labor_2025 = date(2025, 9, 1)
        self.assertTrue(self.calendar.is_holiday(labor_2025))
    
    def test_thanksgiving(self):
        """Test Thanksgiving (4th Thursday in November)."""
        # 2025: November 27
        thanks_2025 = date(2025, 11, 27)
        self.assertTrue(self.calendar.is_holiday(thanks_2025))
        
        # 2026: November 26
        thanks_2026 = date(2026, 11, 26)
        self.assertTrue(self.calendar.is_holiday(thanks_2026))
    
    def test_christmas(self):
        """Test Christmas Day (December 25)."""
        # 2025: December 25 is Thursday
        self.assertTrue(self.calendar.is_holiday(date(2025, 12, 25)))
        
        # 2027: December 25 is Saturday - Friday Dec 24 observed
        self.assertTrue(self.calendar.is_holiday(date(2027, 12, 24)))
    
    def test_early_close_black_friday(self):
        """Test early close on Black Friday."""
        # 2025: Thanksgiving is Nov 27, Black Friday is Nov 28
        black_friday_2025 = date(2025, 11, 28)
        self.assertTrue(self.calendar.is_early_close(black_friday_2025))
        self.assertTrue(self.calendar.is_trading_day(black_friday_2025))
    
    def test_early_close_christmas_eve(self):
        """Test early close on Christmas Eve."""
        # 2025: December 24 is Wednesday
        christmas_eve_2025 = date(2025, 12, 24)
        self.assertTrue(self.calendar.is_early_close(christmas_eve_2025))
    
    def test_early_close_july_3(self):
        """Test early close on July 3 (day before Independence Day)."""
        # 2025: July 3 is Thursday (day before July 4 Friday)
        july_3_2025 = date(2025, 7, 3)
        self.assertTrue(self.calendar.is_early_close(july_3_2025))
    
    def test_market_hours_regular(self):
        """Test regular market hours."""
        # Regular trading day
        d = date(2025, 1, 8)  # Wednesday
        open_time, close_time = self.calendar.get_market_hours(d)
        
        self.assertEqual(open_time, dt_time(9, 30))
        self.assertEqual(close_time, dt_time(16, 0))
    
    def test_market_hours_early_close(self):
        """Test early close market hours."""
        # Black Friday 2025
        d = date(2025, 11, 28)
        open_time, close_time = self.calendar.get_market_hours(d)
        
        self.assertEqual(open_time, dt_time(9, 30))
        self.assertEqual(close_time, dt_time(13, 0))
    
    def test_market_hours_closed(self):
        """Test closed day returns None hours."""
        # Weekend
        d = date(2025, 1, 11)  # Saturday
        open_time, close_time = self.calendar.get_market_hours(d)
        
        self.assertIsNone(open_time)
        self.assertIsNone(close_time)
    
    def test_is_market_open_during_hours_fallback(self):
        """Test market open during trading hours using fallback."""
        # Wednesday Jan 8, 2025 at 10:00 AM ET
        dt = self.tz.localize(datetime(2025, 1, 8, 10, 0))
        self.assertTrue(self.calendar._is_market_open_fallback(dt))
    
    def test_is_market_closed_before_open_fallback(self):
        """Test market closed before open using fallback."""
        # Wednesday Jan 8, 2025 at 9:00 AM ET
        dt = self.tz.localize(datetime(2025, 1, 8, 9, 0))
        self.assertFalse(self.calendar._is_market_open_fallback(dt))
    
    def test_is_market_closed_after_close_fallback(self):
        """Test market closed after close using fallback."""
        # Wednesday Jan 8, 2025 at 4:30 PM ET
        dt = self.tz.localize(datetime(2025, 1, 8, 16, 30))
        self.assertFalse(self.calendar._is_market_open_fallback(dt))
    
    def test_next_trading_day(self):
        """Test finding next trading day."""
        # Friday Jan 10, 2025 -> Monday Jan 13, 2025
        friday = date(2025, 1, 10)
        next_day = self.calendar.next_trading_day(friday)
        self.assertEqual(next_day, date(2025, 1, 13))
    
    def test_next_trading_day_over_holiday(self):
        """Test next trading day skips holiday."""
        # Wednesday Dec 24, 2025 -> Friday Dec 26, 2025 (skip Christmas)
        christmas_eve = date(2025, 12, 24)
        next_day = self.calendar.next_trading_day(christmas_eve)
        self.assertEqual(next_day, date(2025, 12, 26))
    
    def test_previous_trading_day(self):
        """Test finding previous trading day."""
        # Monday Jan 13, 2025 -> Friday Jan 10, 2025
        monday = date(2025, 1, 13)
        prev_day = self.calendar.previous_trading_day(monday)
        self.assertEqual(prev_day, date(2025, 1, 10))
    
    def test_2026_holidays(self):
        """Test 2026 holiday dates for project relevance."""
        # Key 2026 holidays
        self.assertTrue(self.calendar.is_holiday(date(2026, 1, 1)))   # New Year's
        self.assertTrue(self.calendar.is_holiday(date(2026, 1, 19)))  # MLK Day
        self.assertTrue(self.calendar.is_holiday(date(2026, 2, 16)))  # Presidents Day
        self.assertTrue(self.calendar.is_holiday(date(2026, 4, 3)))   # Good Friday
        self.assertTrue(self.calendar.is_holiday(date(2026, 5, 25)))  # Memorial Day
        self.assertTrue(self.calendar.is_holiday(date(2026, 6, 19)))  # Juneteenth
        self.assertTrue(self.calendar.is_holiday(date(2026, 7, 3)))   # Independence (observed)
        self.assertTrue(self.calendar.is_holiday(date(2026, 9, 7)))   # Labor Day
        self.assertTrue(self.calendar.is_holiday(date(2026, 11, 26))) # Thanksgiving
        self.assertTrue(self.calendar.is_holiday(date(2026, 12, 25))) # Christmas


class TestMarketCalendarAPI(unittest.TestCase):
    """Test market calendar with mocked API responses."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.calendar = MarketCalendar(api_key='test_key')
        self.tz = pytz.timezone('America/New_York')
    
    @patch('utils.market_calendar.requests.get')
    def test_is_market_open_api(self, mock_get):
        """Test market open check using API."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'market': 'open',
            'exchanges': {
                'nyse': 'open',
                'nasdaq': 'open',
                'otc': 'open'
            },
            'earlyHours': False,
            'afterHours': False
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        # Clear cache to force API call
        self.calendar.clear_cache()
        
        result = self.calendar.is_market_open()
        self.assertTrue(result)
        
        # Verify API was called
        mock_get.assert_called()
    
    @patch('utils.market_calendar.requests.get')
    def test_is_market_closed_api(self, mock_get):
        """Test market closed check using API."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'market': 'closed',
            'exchanges': {
                'nyse': 'closed',
                'nasdaq': 'closed',
                'otc': 'closed'
            },
            'earlyHours': False,
            'afterHours': False
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        self.calendar.clear_cache()
        
        result = self.calendar.is_market_open()
        self.assertFalse(result)
    
    @patch('utils.market_calendar.requests.get')
    def test_get_market_status_api(self, mock_get):
        """Test getting full market status from API."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'market': 'open',
            'exchanges': {
                'nyse': 'open',
                'nasdaq': 'open',
                'otc': 'open'
            },
            'earlyHours': False,
            'afterHours': False,
            'serverTime': '2025-01-08T10:00:00-05:00'
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        self.calendar.clear_cache()
        
        status = self.calendar.get_market_status()
        
        self.assertEqual(status['market'], 'open')
        self.assertEqual(status['nyse'], 'open')
        self.assertEqual(status['source'], 'api')
    
    @patch('utils.market_calendar.requests.get')
    def test_get_holidays_api(self, mock_get):
        """Test getting holidays from API."""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'date': '2025-01-20',
                'name': 'Martin Luther King Jr. Day',
                'status': 'closed',
                'exchange': 'NYSE'
            },
            {
                'date': '2025-02-17',
                'name': 'Presidents Day',
                'status': 'closed',
                'exchange': 'NYSE'
            }
        ]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        self.calendar.clear_cache()
        
        holidays = self.calendar.get_upcoming_holidays()
        
        self.assertGreaterEqual(len(holidays), 1)
        self.assertEqual(holidays[0]['source'], 'api')
    
    @patch('utils.market_calendar.requests.get')
    def test_api_failure_fallback(self, mock_get):
        """Test fallback when API fails."""
        mock_get.side_effect = Exception("API Error")
        
        self.calendar.clear_cache()
        
        # Should not raise, should fall back
        status = self.calendar.get_market_status()
        
        self.assertEqual(status['source'], 'fallback')
    
    def test_cache_prevents_repeated_calls(self):
        """Test that caching prevents repeated API calls."""
        with patch('utils.market_calendar.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                'market': 'open',
                'exchanges': {'nyse': 'open', 'nasdaq': 'open'}
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            self.calendar.clear_cache()
            
            # First call should hit API
            self.calendar.is_market_open()
            
            # Second call should use cache
            self.calendar.is_market_open()
            
            # Should only have called API once
            self.assertEqual(mock_get.call_count, 1)


class TestGoodFridayCalculation(unittest.TestCase):
    """Specific tests for Good Friday Easter calculation."""
    
    def setUp(self):
        self.calendar = MarketCalendar()
    
    def test_good_friday_dates(self):
        """Test Good Friday dates for multiple years."""
        # Known Good Friday dates
        expected = {
            2020: date(2020, 4, 10),
            2021: date(2021, 4, 2),
            2022: date(2022, 4, 15),
            2023: date(2023, 4, 7),
            2024: date(2024, 3, 29),
            2025: date(2025, 4, 18),
            2026: date(2026, 4, 3),
            2027: date(2027, 3, 26),
            2028: date(2028, 4, 14),
            2029: date(2029, 3, 30),
            2030: date(2030, 4, 19),
        }
        
        for year, expected_date in expected.items():
            calculated = self.calendar._good_friday(year)
            self.assertEqual(calculated, expected_date, 
                           f"Good Friday {year}: expected {expected_date}, got {calculated}")


class TestMarketCalendarSingleton(unittest.TestCase):
    """Test singleton pattern and initialization."""
    
    def test_init_with_api_key(self):
        """Test initializing calendar with API key."""
        # Reset singleton
        import utils.market_calendar as mc
        mc._calendar = None
        mc._calendar_api_key = None
        
        cal = init_market_calendar('test_api_key')
        
        self.assertIsNotNone(cal)
        self.assertEqual(cal.api_key, 'test_api_key')
    
    def test_singleton_returns_same_instance(self):
        """Test singleton returns same instance."""
        import utils.market_calendar as mc
        mc._calendar = None
        mc._calendar_api_key = None
        
        cal1 = get_market_calendar('key1')
        cal2 = get_market_calendar()  # Should return same instance
        
        self.assertIs(cal1, cal2)
    
    def test_singleton_reinit_with_different_key(self):
        """Test singleton reinitializes with different key."""
        import utils.market_calendar as mc
        mc._calendar = None
        mc._calendar_api_key = None
        
        cal1 = get_market_calendar('key1')
        cal2 = get_market_calendar('key2')  # Different key -> new instance
        
        self.assertIsNot(cal1, cal2)
        self.assertEqual(cal2.api_key, 'key2')


if __name__ == '__main__':
    unittest.main(verbosity=2)
