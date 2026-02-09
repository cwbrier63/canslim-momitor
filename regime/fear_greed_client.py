"""
CANSLIM Monitor - CNN Fear & Greed Index Client
=================================================
Fetches CNN's Fear & Greed Index data for market sentiment analysis.

The index ranges from 0 (Extreme Fear) to 100 (Extreme Greed) and is based
on seven market indicators including stock momentum, put/call ratio,
junk bond demand, market volatility, and safe haven demand.

Uses the undocumented CNN dataviz API endpoint. Requires User-Agent header.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

import requests

logger = logging.getLogger('canslim.regime')

# CNN dataviz API endpoint
API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# Rotate User-Agent to avoid blocks
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

@dataclass
class FearGreedData:
    """CNN Fear & Greed Index data point."""
    score: float            # 0-100
    rating: str             # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    previous_close: float   # Yesterday's score
    one_week_ago: float     # Score 1 week ago
    one_month_ago: float    # Score 1 month ago
    one_year_ago: float     # Score 1 year ago
    timestamp: datetime     # When the data was recorded


@dataclass
class FearGreedHistoryPoint:
    """Single historical data point."""
    date: datetime
    score: float


def classify_score(score: float) -> str:
    """Map a 0-100 score to a CNN rating string.

    CNN boundaries: 0-24 Extreme Fear, 25-44 Fear, 45-55 Neutral,
    56-75 Greed, 76-100 Extreme Greed.
    """
    if score >= 75:
        return "Extreme Greed"
    elif score >= 55:
        return "Greed"
    elif score >= 45:
        return "Neutral"
    elif score >= 25:
        return "Fear"
    else:
        return "Extreme Fear"


class FearGreedClient:
    """
    Client for CNN's Fear & Greed Index API.

    Fetches current and historical sentiment data from CNN's dataviz endpoint.
    Results are cached in-memory for the configured cache duration.
    """

    def __init__(self, cache_minutes: int = 60):
        self._cache_minutes = cache_minutes
        self._cached_data: Optional[FearGreedData] = None
        self._cache_time: Optional[datetime] = None
        self._timeout = 10

    @classmethod
    def from_config(cls, config: dict) -> 'FearGreedClient':
        """Create client from application config."""
        fg_config = config.get('market_regime', {}).get('fear_greed', {})
        cache_minutes = fg_config.get('cache_minutes', 60)
        return cls(cache_minutes=cache_minutes)

    def fetch_current(self) -> Optional[FearGreedData]:
        """
        Fetch current Fear & Greed Index value.

        Returns cached data if within cache window.
        Returns None on any failure (non-critical data source).
        """
        # Check cache
        if self._cached_data and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds()
            if elapsed < self._cache_minutes * 60:
                logger.debug(f"Using cached F&G data (age: {elapsed:.0f}s)")
                return self._cached_data

        try:
            response = self._make_request(API_URL)
            if response is None:
                return self._cached_data  # Return stale cache if available

            data = response.json()
            result = self._parse_current(data)

            if result:
                self._cached_data = result
                self._cache_time = datetime.now()
                logger.info(f"CNN F&G: {result.score:.0f} ({result.rating})")

            return result

        except Exception as e:
            logger.warning(f"Failed to fetch CNN Fear & Greed: {e}")
            return self._cached_data

    def fetch_historical(self, days: int = 90) -> List[FearGreedHistoryPoint]:
        """
        Fetch historical Fear & Greed data for the given number of days.

        Returns list of (date, score) points, newest first.
        """
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        url = f"{API_URL}/{start_date}"

        try:
            response = self._make_request(url)
            if response is None:
                return []

            data = response.json()
            return self._parse_historical(data)

        except Exception as e:
            logger.warning(f"Failed to fetch F&G history: {e}")
            return []

    def _make_request(self, url: str) -> Optional[requests.Response]:
        """Make HTTP request with User-Agent rotation and retry."""
        headers = {'User-Agent': random.choice(USER_AGENTS)}

        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=self._timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 418:
                    # "I'm a teapot" - try different User-Agent
                    headers = {'User-Agent': random.choice(USER_AGENTS)}
                    logger.debug(f"Got 418, retrying with different User-Agent (attempt {attempt + 1})")
                    time.sleep(1)
                    continue
                logger.warning(f"HTTP error fetching F&G: {e}")
                return None
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error fetching F&G (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    time.sleep(1)

        return None

    def _parse_current(self, data: dict) -> Optional[FearGreedData]:
        """Parse the current F&G value from API response."""
        try:
            fg = data.get('fear_and_greed', {})
            score = float(fg.get('score', 0))
            rating = fg.get('rating', classify_score(score))
            timestamp_str = fg.get('timestamp', '')

            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                timestamp = datetime.now()

            # Extract comparison values from historical data
            previous_close = 0.0
            one_week_ago = 0.0
            one_month_ago = 0.0
            one_year_ago = 0.0

            # Try to get comparison values from the response
            # CNN sometimes includes these as separate keys
            prev = data.get('fear_and_greed_previous_close', {})
            if prev:
                previous_close = float(prev.get('score', prev.get('y', 0)))

            week = data.get('fear_and_greed_previous_1_week', {})
            if week:
                one_week_ago = float(week.get('score', week.get('y', 0)))

            month = data.get('fear_and_greed_previous_1_month', {})
            if month:
                one_month_ago = float(month.get('score', month.get('y', 0)))

            year = data.get('fear_and_greed_previous_1_year', {})
            if year:
                one_year_ago = float(year.get('score', year.get('y', 0)))

            # If previous_close not found, try computing from historical data
            if previous_close == 0.0:
                hist = self._parse_historical(data)
                if len(hist) >= 2:
                    previous_close = hist[1].score  # Second most recent

            return FearGreedData(
                score=score,
                rating=self._normalize_rating(rating),
                previous_close=previous_close,
                one_week_ago=one_week_ago,
                one_month_ago=one_month_ago,
                one_year_ago=one_year_ago,
                timestamp=timestamp,
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse F&G response: {e}")
            return None

    def _parse_historical(self, data: dict) -> List[FearGreedHistoryPoint]:
        """Parse historical F&G data from API response."""
        points = []
        try:
            hist_data = data.get('fear_and_greed_historical', {}).get('data', [])

            for point in hist_data:
                x = point.get('x', 0)
                y = point.get('y', 0)

                if x and y is not None:
                    # x is Unix timestamp in milliseconds
                    dt = datetime.fromtimestamp(x / 1000)
                    points.append(FearGreedHistoryPoint(date=dt, score=float(y)))

            # Sort newest first
            points.sort(key=lambda p: p.date, reverse=True)

        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse F&G historical data: {e}")

        return points

    @staticmethod
    def _normalize_rating(rating: str) -> str:
        """Normalize API rating string to consistent format."""
        rating_lower = rating.lower().strip()
        mapping = {
            'extreme fear': 'Extreme Fear',
            'fear': 'Fear',
            'neutral': 'Neutral',
            'greed': 'Greed',
            'extreme greed': 'Extreme Greed',
        }
        return mapping.get(rating_lower, classify_score(0))
