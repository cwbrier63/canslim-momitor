"""
Distribution Day Tracker - ENHANCED VERSION

Calculates and tracks IBD-style distribution days for S&P 500 and NASDAQ.

Supports both ETFs (SPY/QQQ) and actual indices (SPX/COMP) via configuration.

IBD Distribution Day Definition:
- Index closes DOWN >= 0.2% from prior close
- Volume is HIGHER than prior day's volume

STALLING DAY Definition (optional, disabled by default):
- Index closes UP but with minimal price progress (typically < 0.4%)
- Volume is EQUAL TO or HIGHER than prior day's volume
- Represents "stealth" distribution - institutions selling into strength
- Note: IBD only counts ~4-5 stalling days per year, our detection is aggressive

Expiration Rules:
- TIME: 25 trading days have passed
- RALLY: Index rallies 5%+ from the D-day close

Config options (in config.yaml under distribution_days:):
  # Detection thresholds
  decline_threshold: -0.2      # % decline to qualify as D-day
  lookback_days: 25            # Rolling window in trading days
  rally_expiration_pct: 5.0    # % rally to expire D-day
  trend_comparison_days: 5     # Days back for trend calculation
  enable_stalling: false       # Whether to count stalling days (default: false)
  stalling_max_gain: 0.4       # Max % gain for stalling day
  
  # Symbol configuration
  use_indices: false           # true = SPX/COMP (indices), false = SPY/QQQ (ETFs)
  sp500_symbol: "SPY"          # Override S&P 500 symbol (or "SPX" for IBKR index)
  nasdaq_symbol: "QQQ"         # Override NASDAQ symbol (or "COMP" for IBKR index)
  
Symbol Reference:
  ┌─────────────┬─────────┬─────────────────┬─────────────┐
  │ Index       │ ETF     │ IBKR Index      │ Polygon     │
  ├─────────────┼─────────┼─────────────────┼─────────────┤
  │ S&P 500     │ SPY     │ SPX             │ I:SPX       │
  │ NASDAQ Comp │ QQQ     │ COMP            │ I:COMP      │
  └─────────────┴─────────┴─────────────────┴─────────────┘
  
  Note: MarketSurge uses 0S&P5 and 0NDQC internally.

Usage:
    from distribution_tracker import DistributionDayTracker
    
    # Using ETFs (default)
    tracker = DistributionDayTracker.from_config(config, db_session)
    combined = tracker.get_combined_data(spy_bars, qqq_bars)
    
    # Using indices (set use_indices: true in config)
    tracker = DistributionDayTracker.from_config(config, db_session)
    combined = tracker.get_combined_data(spx_bars, comp_bars)
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy import and_

from .models_regime import (
    DistributionDay, DistributionDayCount, 
    DistributionDayOverride, DDayTrend
)
from .historical_data import DailyBar

logger = logging.getLogger(__name__)


class DistributionType(Enum):
    """Type of distribution day."""
    DISTRIBUTION = "DISTRIBUTION"  # Down day on higher volume
    STALLING = "STALLING"          # Up day with little progress on high volume


@dataclass
class DistributionDayResult:
    """Result of distribution day analysis for one symbol."""
    symbol: str
    active_count: int          # Display count (after overrides)
    active_dates: List[date]   # Actual detected D-day dates
    count_5_days_ago: int
    delta_5_day: int
    new_d_days_found: int
    expired_d_days: int
    stalling_days_found: int   # Track stalling days separately
    raw_count: int = None      # Raw detected count (before overrides)
    
    def __post_init__(self):
        # Default raw_count to len(active_dates) if not set
        if self.raw_count is None:
            self.raw_count = len(self.active_dates)
    
    @property
    def has_override(self) -> bool:
        """True if an override is affecting the count."""
        return self.active_count != self.raw_count


@dataclass
class CombinedDistributionData:
    """Combined distribution data for SPY and QQQ."""
    spy_count: int
    qqq_count: int
    spy_5day_delta: int
    qqq_5day_delta: int
    trend: DDayTrend
    spy_dates: List[date]
    qqq_dates: List[date]
    
    @property
    def total_count(self) -> int:
        return self.spy_count + self.qqq_count
    
    @property
    def total_5day_delta(self) -> int:
        return self.spy_5day_delta + self.qqq_5day_delta


class DistributionDayTracker:
    """
    Tracks distribution days using IBD methodology.
    
    Maintains a rolling 25-day window of distribution days,
    expiring them based on time or 5% rally criteria.
    
    Optionally includes STALLING DAY detection (disabled by default).
    
    Symbol Configuration:
        use_indices: false  # Use ETFs (SPY/QQQ) - default
        use_indices: true   # Use actual indices (SPX/COMP for IBKR)
        
        Custom symbols can also be specified:
        sp500_symbol: "SPY"   # or "SPX" for index
        nasdaq_symbol: "QQQ"  # or "COMP" for index
    """
    
    # IBD standard thresholds
    DEFAULT_DECLINE_THRESHOLD = -0.2  # % decline to qualify as distribution
    DEFAULT_LOOKBACK_DAYS = 25        # Trading days window
    DEFAULT_RALLY_EXPIRATION = 5.0    # % rally to expire
    DEFAULT_TREND_DAYS = 5            # Days for trend comparison
    
    # Stalling day thresholds
    DEFAULT_STALLING_MAX_GAIN = 0.4   # Max % gain for stalling (up but little progress)
    DEFAULT_STALLING_MIN_GAIN = 0.0   # Must be positive (up day)
    DEFAULT_ENABLE_STALLING = False   # Disabled by default - too aggressive
    
    # Symbol presets
    SYMBOLS_ETF = {'sp500': 'SPY', 'nasdaq': 'QQQ'}
    SYMBOLS_INDEX_IBKR = {'sp500': 'SPX', 'nasdaq': 'COMP'}
    SYMBOLS_INDEX_POLYGON = {'sp500': 'I:SPX', 'nasdaq': 'I:COMP'}
    
    def __init__(
        self,
        db_session: Session,
        decline_threshold: float = None,
        lookback_days: int = None,
        rally_expiration_pct: float = None,
        trend_comparison_days: int = None,
        enable_stalling: bool = None,
        stalling_max_gain: float = None,
        sp500_symbol: str = None,
        nasdaq_symbol: str = None,
        use_indices: bool = False
    ):
        """
        Initialize tracker.
        
        Args:
            db_session: SQLAlchemy session
            decline_threshold: % decline to qualify as D-day (default: -0.2)
            lookback_days: Rolling window in trading days (default: 25)
            rally_expiration_pct: % rally to expire D-day (default: 5.0)
            trend_comparison_days: Days back for trend calc (default: 5)
            enable_stalling: Whether to count stalling days (default: False)
            stalling_max_gain: Max % gain to qualify as stalling (default: 0.4)
            sp500_symbol: Symbol for S&P 500 tracking (default: SPY or SPX if use_indices)
            nasdaq_symbol: Symbol for NASDAQ tracking (default: QQQ or COMP if use_indices)
            use_indices: If True, use index symbols (SPX/COMP) instead of ETFs (SPY/QQQ)
        """
        self.db = db_session
        self.decline_threshold = decline_threshold if decline_threshold is not None else self.DEFAULT_DECLINE_THRESHOLD
        self.lookback_days = lookback_days if lookback_days is not None else self.DEFAULT_LOOKBACK_DAYS
        self.rally_expiration_pct = rally_expiration_pct if rally_expiration_pct is not None else self.DEFAULT_RALLY_EXPIRATION
        self.trend_days = trend_comparison_days if trend_comparison_days is not None else self.DEFAULT_TREND_DAYS
        self.enable_stalling = enable_stalling if enable_stalling is not None else self.DEFAULT_ENABLE_STALLING
        self.stalling_max_gain = stalling_max_gain if stalling_max_gain is not None else self.DEFAULT_STALLING_MAX_GAIN
        
        # Symbol configuration
        default_symbols = self.SYMBOLS_INDEX_IBKR if use_indices else self.SYMBOLS_ETF
        self.sp500_symbol = sp500_symbol or default_symbols['sp500']
        self.nasdaq_symbol = nasdaq_symbol or default_symbols['nasdaq']
        self.use_indices = use_indices
        
        # Log configuration on init
        logger.info(
            f"DistributionDayTracker initialized: "
            f"sp500={self.sp500_symbol}, nasdaq={self.nasdaq_symbol}, "
            f"use_indices={use_indices}, enable_stalling={self.enable_stalling}"
        )
    
    @classmethod
    def from_config(cls, config: dict, db_session: Session) -> 'DistributionDayTracker':
        """
        Create tracker from config dict.
        
        Expected config.yaml structure:
            distribution_days:
              decline_threshold: -0.2
              lookback_days: 25
              rally_expiration_pct: 5.0
              trend_comparison_days: 5
              enable_stalling: false
              stalling_max_gain: 0.4
              # Symbol configuration (optional)
              use_indices: false        # true = SPX/COMP, false = SPY/QQQ
              sp500_symbol: "SPY"       # Override S&P 500 symbol
              nasdaq_symbol: "QQQ"      # Override NASDAQ symbol
        """
        dd_config = config.get('distribution_days', {})
        
        # Explicitly handle enable_stalling to ensure False is respected
        enable_stalling = dd_config.get('enable_stalling')
        if enable_stalling is None:
            enable_stalling = cls.DEFAULT_ENABLE_STALLING  # False
        
        # Handle use_indices - defaults to False (ETFs)
        use_indices = dd_config.get('use_indices', False)
        
        return cls(
            db_session=db_session,
            decline_threshold=dd_config.get('decline_threshold'),
            lookback_days=dd_config.get('lookback_days'),
            rally_expiration_pct=dd_config.get('rally_expiration_pct'),
            trend_comparison_days=dd_config.get('trend_comparison_days'),
            enable_stalling=enable_stalling,
            stalling_max_gain=dd_config.get('stalling_max_gain'),
            sp500_symbol=dd_config.get('sp500_symbol'),
            nasdaq_symbol=dd_config.get('nasdaq_symbol'),
            use_indices=use_indices
        )
    
    def is_distribution_day(
        self,
        today_close: float,
        today_volume: int,
        yesterday_close: float,
        yesterday_volume: int
    ) -> Tuple[bool, float, Optional[DistributionType]]:
        """
        Check if today qualifies as a distribution day (including stalling).
        
        Args:
            today_close: Today's closing price
            today_volume: Today's volume
            yesterday_close: Yesterday's closing price
            yesterday_volume: Yesterday's volume
        
        Returns:
            (is_d_day, pct_change, distribution_type)
        """
        pct_change = (today_close - yesterday_close) / yesterday_close * 100
        volume_higher = today_volume > yesterday_volume
        volume_equal_or_higher = today_volume >= yesterday_volume
        
        # Standard distribution: Down >= 0.2% on higher volume
        if pct_change <= self.decline_threshold and volume_higher:
            return True, pct_change, DistributionType.DISTRIBUTION
        
        # Stalling: Up day with little progress on high volume (only if enabled)
        if self.enable_stalling:
            is_up_day = pct_change > self.DEFAULT_STALLING_MIN_GAIN
            is_small_gain = pct_change <= self.stalling_max_gain
            if is_up_day and is_small_gain and volume_equal_or_higher:
                return True, pct_change, DistributionType.STALLING
        
        return False, pct_change, None
    
    def update_distribution_days(
        self,
        symbol: str,
        daily_bars: List[DailyBar],
        current_date: date = None
    ) -> DistributionDayResult:
        """
        Scan daily bars and update distribution day records.
        
        Args:
            symbol: 'SPY' or 'QQQ'
            daily_bars: List of DailyBar objects (oldest to newest)
            current_date: Override current date (for backtesting)
        
        Returns:
            DistributionDayResult with counts and details
        """
        if len(daily_bars) < 2:
            logger.warning(f"Insufficient data for {symbol}: {len(daily_bars)} bars")
            return DistributionDayResult(
                symbol=symbol,
                active_count=0,
                active_dates=[],
                count_5_days_ago=0,
                delta_5_day=0,
                new_d_days_found=0,
                expired_d_days=0,
                stalling_days_found=0
            )
        
        current_close = daily_bars[-1].close
        current_dt = current_date or daily_bars[-1].date
        
        new_d_days = 0
        new_stalling_days = 0
        
        # Scan the lookback window for new distribution days
        scan_range = min(self.lookback_days, len(daily_bars) - 1)
        
        for i in range(scan_range):
            today = daily_bars[-(i + 1)]  # Work backwards from most recent
            yesterday = daily_bars[-(i + 2)]
            
            bar_date = today.date
            
            # Check if this day qualifies as distribution day
            is_d_day, pct_change, d_type = self.is_distribution_day(
                today.close, today.volume,
                yesterday.close, yesterday.volume
            )
            
            if is_d_day:
                # Check if already recorded
                existing = self.db.query(DistributionDay).filter(
                    DistributionDay.symbol == symbol,
                    DistributionDay.date == bar_date
                ).first()
                
                if not existing:
                    # Record new distribution day
                    d_day = DistributionDay(
                        symbol=symbol,
                        date=bar_date,
                        close_price=today.close,
                        volume=today.volume,
                        pct_change=pct_change,
                    )
                    self.db.add(d_day)
                    
                    if d_type == DistributionType.STALLING:
                        new_stalling_days += 1
                        logger.info(f"New STALLING day: {symbol} {bar_date} ({pct_change:+.2f}%)")
                    else:
                        new_d_days += 1
                        logger.info(f"New distribution day: {symbol} {bar_date} ({pct_change:+.2f}%)")
        
        # Expire old distribution days
        expired_count = self._expire_distribution_days(symbol, current_close, current_dt, daily_bars)
        
        self.db.commit()
        
        # Get current active count and dates
        active_count, active_dates, raw_count = self._get_active_distribution_days(symbol)
        
        if active_count != raw_count:
            logger.info(f"{symbol}: Display count={active_count}, Raw detected={raw_count} (override active)")
        
        # Get count from 5 days ago for trend
        count_5_ago = self._get_count_n_days_ago(symbol, self.trend_days, current_dt)
        delta = active_count - count_5_ago
        
        return DistributionDayResult(
            symbol=symbol,
            active_count=active_count,
            active_dates=active_dates,
            count_5_days_ago=count_5_ago,
            delta_5_day=delta,
            new_d_days_found=new_d_days,
            expired_d_days=expired_count,
            stalling_days_found=new_stalling_days,
            raw_count=raw_count
        )
    
    def _expire_distribution_days(
        self,
        symbol: str,
        current_close: float,
        current_date: date,
        daily_bars: List[DailyBar]
    ) -> int:
        """
        Mark distribution days as expired based on time or rally.
        
        Returns:
            Number of D-days expired
        """
        expired_count = 0
        
        active_days = self.db.query(DistributionDay).filter(
            DistributionDay.symbol == symbol,
            DistributionDay.expired == False
        ).all()
        
        # Build date->bar lookup for accurate trading day counting
        bar_dates = {bar.date: bar for bar in daily_bars}
        
        for d_day in active_days:
            # Count trading days elapsed
            trading_days_elapsed = self._count_trading_days(
                d_day.date, current_date, bar_dates
            )
            
            # Time expiration: 25 trading days
            if trading_days_elapsed >= self.lookback_days:
                d_day.expired = True
                d_day.expiry_reason = 'TIME'
                d_day.expiry_date = current_date
                expired_count += 1
                logger.info(f"D-day expired (time): {symbol} {d_day.date}")
                continue
            
            # Rally expiration: 5% rally from D-day close
            rally_pct = (current_close - d_day.close_price) / d_day.close_price * 100
            if rally_pct >= self.rally_expiration_pct:
                d_day.expired = True
                d_day.expiry_reason = 'RALLY'
                d_day.expiry_date = current_date
                expired_count += 1
                logger.info(f"D-day expired (rally {rally_pct:.1f}%): {symbol} {d_day.date}")
        
        return expired_count
    
    def _count_trading_days(
        self,
        start_date: date,
        end_date: date,
        bar_dates: Dict[date, DailyBar]
    ) -> int:
        """Count trading days between two dates using available bar data."""
        count = 0
        current = start_date
        
        while current <= end_date:
            if current in bar_dates:
                count += 1
            elif current.weekday() < 5:
                # Weekday not in bars - assume trading day if no data
                count += 1
            current += timedelta(days=1)
        
        return count
    
    def _get_active_distribution_days(self, symbol: str) -> Tuple[int, List[date], int]:
        """
        Get count and dates of active (non-expired) distribution days.
        
        Returns:
            Tuple of (display_count, active_dates, raw_count)
            - display_count: Count after any overrides (for reporting)
            - active_dates: Actual detected D-day dates (for histogram)
            - raw_count: Count before overrides (for debugging)
        """
        active = self.db.query(DistributionDay).filter(
            DistributionDay.symbol == symbol,
            DistributionDay.expired == False
        ).order_by(DistributionDay.date.desc()).all()
        
        raw_count = len(active)
        active_dates = [d.date for d in active]
        
        # Apply any manual overrides to display count only
        override = self._get_active_override(symbol)
        display_count = raw_count
        
        if override:
            if override.action == 'SET':
                display_count = override.adjustment
                logger.info(f"Applied override SET {symbol} count to {display_count} (raw: {raw_count})")
            else:  # ADJUST
                display_count = max(0, raw_count + override.adjustment)
                logger.info(f"Applied override ADJUST {symbol} by {override.adjustment} (raw: {raw_count})")
        
        return display_count, active_dates, raw_count
    
    def _get_active_override(self, symbol: str) -> Optional[DistributionDayOverride]:
        """Get the most recent override for today."""
        today = date.today()
        return self.db.query(DistributionDayOverride).filter(
            DistributionDayOverride.symbol == symbol,
            DistributionDayOverride.date == today
        ).order_by(DistributionDayOverride.created_at.desc()).first()
    
    def _get_count_n_days_ago(self, symbol: str, days: int, current_date: date = None) -> int:
        """
        Get the distribution day count from N trading days ago.
        Used for trend calculation.
        """
        reference_date = current_date or date.today()
        target_date = reference_date - timedelta(days=days)
        
        # Find the closest record on or before target date
        record = self.db.query(DistributionDayCount).filter(
            DistributionDayCount.date <= target_date
        ).order_by(DistributionDayCount.date.desc()).first()
        
        if record:
            # Check if symbol matches our S&P 500 tracker (could be SPY or SPX)
            is_sp500 = symbol == self.sp500_symbol
            return record.spy_count if is_sp500 else record.qqq_count
        
        # No historical record - calculate from active D-day dates
        # Use raw detected dates, not override-affected count
        _, active_dates, _ = self._get_active_distribution_days(symbol)
        
        if not active_dates:
            return 0
        
        # Count D-days that would have been active N days ago
        count_n_ago = 0
        cutoff_for_n_ago = target_date - timedelta(days=25)
        
        for d_date in active_dates:
            if cutoff_for_n_ago <= d_date <= target_date:
                count_n_ago += 1
        
        return count_n_ago
    
    def save_daily_counts(
        self,
        spy_result: DistributionDayResult,
        qqq_result: DistributionDayResult,
        save_date: date = None
    ):
        """Save counts for historical trend tracking."""
        target_date = save_date or date.today()
        
        existing = self.db.query(DistributionDayCount).filter(
            DistributionDayCount.date == target_date
        ).first()
        
        spy_dates_str = ','.join(d.isoformat() for d in spy_result.active_dates)
        qqq_dates_str = ','.join(d.isoformat() for d in qqq_result.active_dates)
        
        if existing:
            existing.spy_count = spy_result.active_count
            existing.qqq_count = qqq_result.active_count
            existing.spy_dates = spy_dates_str
            existing.qqq_dates = qqq_dates_str
        else:
            record = DistributionDayCount(
                date=target_date,
                spy_count=spy_result.active_count,
                qqq_count=qqq_result.active_count,
                spy_dates=spy_dates_str,
                qqq_dates=qqq_dates_str
            )
            self.db.add(record)
        
        self.db.commit()
        logger.info(f"Saved daily counts: SPY={spy_result.active_count}, QQQ={qqq_result.active_count}")
    
    def add_override(
        self,
        symbol: str,
        adjustment: int,
        action: str = 'ADJUST',
        reason: str = None,
        ibd_count: int = None
    ):
        """Add a manual override for distribution day count."""
        override = DistributionDayOverride(
            date=date.today(),
            symbol=symbol,
            adjustment=adjustment,
            action=action,
            reason=reason,
            ibd_count=ibd_count
        )
        self.db.add(override)
        self.db.commit()
        logger.info(f"Added override: {symbol} {action} {adjustment}")
    
    def get_combined_data(
        self,
        sp500_bars: List[DailyBar],
        nasdaq_bars: List[DailyBar],
        current_date: date = None
    ) -> CombinedDistributionData:
        """
        Get combined distribution day data for both indices.
        
        This is the main method to call for regime calculation.
        
        Args:
            sp500_bars: Daily bars for S&P 500 tracking (SPY or SPX)
            nasdaq_bars: Daily bars for NASDAQ tracking (QQQ or COMP)
            current_date: Override current date (for backtesting)
        
        Note: Uses configured symbols (sp500_symbol, nasdaq_symbol) for storage.
              Default is SPY/QQQ unless use_indices=True (then SPX/COMP).
        """
        sp500_result = self.update_distribution_days(self.sp500_symbol, sp500_bars, current_date)
        nasdaq_result = self.update_distribution_days(self.nasdaq_symbol, nasdaq_bars, current_date)
        
        calc_date = current_date or sp500_bars[-1].date if sp500_bars else date.today()
        
        self.save_daily_counts(sp500_result, nasdaq_result, calc_date)
        
        # Determine trend
        total_delta = sp500_result.delta_5_day + nasdaq_result.delta_5_day
        
        if total_delta < 0:
            trend = DDayTrend.IMPROVING
        elif total_delta > 0:
            trend = DDayTrend.WORSENING
        else:
            trend = DDayTrend.FLAT
        
        return CombinedDistributionData(
            spy_count=sp500_result.active_count,
            qqq_count=nasdaq_result.active_count,
            spy_5day_delta=sp500_result.delta_5_day,
            qqq_5day_delta=nasdaq_result.delta_5_day,
            trend=trend,
            spy_dates=sp500_result.active_dates,
            qqq_dates=nasdaq_result.active_dates
        )
    
    def get_distribution_day_details(self, symbol: str) -> List[Dict]:
        """Get details of all active distribution days for a symbol."""
        active = self.db.query(DistributionDay).filter(
            DistributionDay.symbol == symbol,
            DistributionDay.expired == False
        ).order_by(DistributionDay.date.desc()).all()
        
        return [
            {
                'date': d.date,
                'close': d.close_price,
                'pct_change': d.pct_change,
                'volume': d.volume,
                'days_ago': (date.today() - d.date).days,
                'type': 'STALLING' if d.pct_change > 0 else 'DISTRIBUTION'
            }
            for d in active
        ]
    
    def debug_distribution_days(self, symbol: str) -> str:
        """Generate debug output showing all distribution day details."""
        details = self.get_distribution_day_details(symbol)
        
        lines = [f"\n=== {symbol} Distribution Days Debug ==="]
        lines.append(f"Active Count: {len(details)}")
        lines.append(f"Stalling Detection: {'ENABLED' if self.enable_stalling else 'DISABLED'}")
        
        for d in details:
            d_type = d.get('type', 'DISTRIBUTION')
            lines.append(
                f"  {d['date']}: {d['pct_change']:+.2f}% "
                f"({d['days_ago']} days ago) [{d_type}]"
            )
        
        return '\n'.join(lines)


if __name__ == '__main__':
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    print("Distribution Day Tracker - Enhanced Version")
    print("=" * 50)
    print("\nDefault configuration:")
    print(f"  enable_stalling: {DistributionDayTracker.DEFAULT_ENABLE_STALLING} (False)")
    print(f"  decline_threshold: {DistributionDayTracker.DEFAULT_DECLINE_THRESHOLD}%")
    print(f"  lookback_days: {DistributionDayTracker.DEFAULT_LOOKBACK_DAYS}")
    print(f"  rally_expiration_pct: {DistributionDayTracker.DEFAULT_RALLY_EXPIRATION}%")
    
    print("\nSymbol presets:")
    print(f"  ETF mode (default):  {DistributionDayTracker.SYMBOLS_ETF}")
    print(f"  Index mode (IBKR):   {DistributionDayTracker.SYMBOLS_INDEX_IBKR}")
    print(f"  Index mode (Polygon): {DistributionDayTracker.SYMBOLS_INDEX_POLYGON}")
    
    print("\nTo use indices instead of ETFs, add to config.yaml:")
    print("  distribution_days:")
    print("    use_indices: true")
    print("    # Or specify custom symbols:")
    print("    # sp500_symbol: SPX")
    print("    # nasdaq_symbol: COMP")
