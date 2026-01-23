"""
Follow-Through Day (FTD) Tracker

Tracks IBD-style Follow-Through Days to identify market bottoms and
confirm new uptrends. Complements distribution day tracking.

IBD Follow-Through Day Definition:
- Occurs on Day 4 or later of an attempted rally
- Major index gains 1.25%+ (conservative) or 1.5%+ (traditional)
- Volume must be higher than the previous day
- Signals potential start of new uptrend

Rally Attempt Rules:
- Day 1: First up day after market makes a new low during correction
- Days 2-3: Market must NOT undercut the rally low
- Day 4+: Eligible for FTD if criteria met
- Rally fails if low of Day 1 is undercut before FTD

Usage:
    from ftd_tracker import FollowThroughDayTracker
    
    tracker = FollowThroughDayTracker(db_session)
    status = tracker.update_rally_status('SPY', daily_bars)
    
    if status.ftd_today:
        print(f"FOLLOW-THROUGH DAY on {status.ftd_date}!")
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, Enum as SQLEnum
from sqlalchemy.orm import Session
from sqlalchemy.ext.declarative import declarative_base

from .historical_data import DailyBar

logger = logging.getLogger(__name__)

# Use same Base as models_regime
from .models_regime import Base


class MarketPhase(Enum):
    """Current market phase based on IBD methodology."""
    CONFIRMED_UPTREND = "CONFIRMED_UPTREND"      # After valid FTD
    RALLY_ATTEMPT = "RALLY_ATTEMPT"              # Days 1-3, waiting for FTD
    UPTREND_PRESSURE = "UPTREND_PRESSURE"        # Uptrend with elevated D-days
    CORRECTION = "CORRECTION"                    # In correction, no rally attempt
    MARKET_IN_CORRECTION = "MARKET_IN_CORRECTION"  # IBD's "Market in Correction" status


class RallyAttempt(Base):
    """
    Tracks rally attempts after market corrections.
    
    A rally attempt begins on the first up day after making a new low.
    It either succeeds (FTD on Day 4+) or fails (undercuts rally low).
    """
    __tablename__ = 'rally_attempts'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False, index=True)  # SPY, QQQ, or DIA
    
    # Rally attempt start
    start_date = Column(Date, nullable=False)
    rally_low = Column(Float, nullable=False)  # Low to watch for undercut
    rally_low_date = Column(Date, nullable=False)
    day_count = Column(Integer, default=1)  # Current day of rally attempt
    
    # Status
    active = Column(Boolean, default=True)
    
    # Outcome (when no longer active)
    succeeded = Column(Boolean)  # True = FTD, False = Failed
    ftd_date = Column(Date)
    ftd_gain_pct = Column(Float)
    ftd_volume_ratio = Column(Float)  # Today vol / yesterday vol
    failure_date = Column(Date)
    failure_reason = Column(String(50))  # 'UNDERCUT', 'STALLED', etc.
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        status = "ACTIVE" if self.active else ("FTD" if self.succeeded else "FAILED")
        return f"<RallyAttempt {self.symbol} Day {self.day_count} [{status}]>"


class FollowThroughDay(Base):
    """
    Records confirmed Follow-Through Days.
    
    Tracks both the FTD event and whether it subsequently failed
    (market undercut the FTD day's low or rally low).
    """
    __tablename__ = 'follow_through_days'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # FTD metrics
    rally_day = Column(Integer, nullable=False)  # Day 4, 5, 6, etc.
    gain_pct = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    prior_volume = Column(Integer, nullable=False)
    volume_ratio = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    
    # Reference prices for failure detection
    rally_low = Column(Float, nullable=False)  # Original rally attempt low
    ftd_low = Column(Float, nullable=False)    # Low on FTD day
    
    # Failure tracking
    confirmed = Column(Boolean, default=True)  # Still valid?
    failed = Column(Boolean, default=False)
    failure_date = Column(Date)
    failure_reason = Column(String(50))  # 'UNDERCUT_RALLY_LOW', 'UNDERCUT_FTD_LOW'
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        status = "CONFIRMED" if self.confirmed else "FAILED"
        return f"<FTD {self.symbol} {self.date} Day {self.rally_day} +{self.gain_pct:.1f}% [{status}]>"


class MarketStatus(Base):
    """
    Daily snapshot of market status for regime tracking.
    
    Combines distribution day count, FTD status, and overall market phase.
    """
    __tablename__ = 'market_status'
    
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True, index=True)
    
    # Market phase
    phase = Column(SQLEnum(MarketPhase), nullable=False)
    
    # Rally attempt status
    in_rally_attempt = Column(Boolean, default=False)
    rally_day = Column(Integer)  # Day of current rally attempt
    
    # FTD status
    has_confirmed_ftd = Column(Boolean, default=False)
    last_ftd_date = Column(Date)
    days_since_ftd = Column(Integer)
    
    # Distribution context
    spy_d_count = Column(Integer)
    qqq_d_count = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)


@dataclass
class RallyStatus:
    """Current rally attempt status."""
    symbol: str
    in_rally_attempt: bool
    rally_day: int
    rally_low: float
    rally_low_date: date
    
    # FTD info
    ftd_today: bool = False
    ftd_date: Optional[date] = None
    ftd_gain_pct: Optional[float] = None
    
    # Failure info
    failed_today: bool = False
    failure_reason: Optional[str] = None
    
    # Overall status
    has_confirmed_ftd: bool = False
    last_ftd_date: Optional[date] = None
    ftd_still_valid: bool = False


@dataclass 
class MarketPhaseStatus:
    """Combined market phase status across indexes."""
    phase: MarketPhase
    spy_status: RallyStatus
    qqq_status: RallyStatus
    
    # Combined signals
    any_ftd_today: bool = False
    any_rally_failed: bool = False
    days_since_last_ftd: Optional[int] = None
    
    # Regime integration
    ftd_score_adjustment: float = 0.0  # Add to regime score


class FollowThroughDayTracker:
    """
    Tracks Follow-Through Days using IBD methodology.
    
    Monitors rally attempts and identifies valid FTDs that signal
    the potential start of a new market uptrend.
    """
    
    # IBD thresholds
    DEFAULT_FTD_MIN_GAIN = 1.25      # Minimum % gain for FTD (conservative)
    TRADITIONAL_FTD_MIN_GAIN = 1.5   # Traditional IBD threshold
    FTD_EARLIEST_DAY = 4             # Earliest day for valid FTD
    CORRECTION_THRESHOLD = -5.0      # % decline to trigger correction mode
    
    def __init__(
        self,
        db_session: Session,
        ftd_min_gain: float = None,
        ftd_earliest_day: int = None
    ):
        """
        Initialize tracker.
        
        Args:
            db_session: SQLAlchemy session
            ftd_min_gain: Minimum % gain for FTD (default: 1.25)
            ftd_earliest_day: Earliest day for FTD (default: 4)
        """
        self.db = db_session
        self.ftd_min_gain = ftd_min_gain or self.DEFAULT_FTD_MIN_GAIN
        self.ftd_earliest_day = ftd_earliest_day or self.FTD_EARLIEST_DAY
    
    def _is_up_day(self, today: DailyBar, yesterday: DailyBar) -> bool:
        """Check if today closed higher than yesterday."""
        return today.close > yesterday.close
    
    def _get_pct_change(self, today: DailyBar, yesterday: DailyBar) -> float:
        """Calculate percentage change."""
        return (today.close - yesterday.close) / yesterday.close * 100
    
    def _is_valid_ftd(
        self,
        today: DailyBar,
        yesterday: DailyBar,
        rally_day: int
    ) -> Tuple[bool, float, float]:
        """
        Check if today qualifies as a Follow-Through Day.
        
        Returns:
            (is_ftd, gain_pct, volume_ratio)
        """
        # Must be Day 4 or later
        if rally_day < self.ftd_earliest_day:
            return False, 0, 0
        
        # Calculate gain
        gain_pct = self._get_pct_change(today, yesterday)
        
        # Must gain at least minimum threshold
        if gain_pct < self.ftd_min_gain:
            return False, gain_pct, 0
        
        # Volume must be higher than yesterday
        volume_ratio = today.volume / yesterday.volume if yesterday.volume > 0 else 0
        if volume_ratio <= 1.0:
            return False, gain_pct, volume_ratio
        
        return True, gain_pct, volume_ratio
    
    def _find_rally_start(self, bars: List[DailyBar], lookback: int = 30) -> Optional[int]:
        """
        Find the start of a rally attempt (first up day after new low).
        
        Returns:
            Index into bars where rally started, or None
        """
        if len(bars) < 3:
            return None
        
        # Look for pattern: new low -> up day
        for i in range(len(bars) - 2, max(0, len(bars) - lookback), -1):
            today = bars[i]
            yesterday = bars[i - 1]
            
            # Check if yesterday made a new recent low
            recent_lows = [b.low for b in bars[max(0, i-20):i]]
            if recent_lows and yesterday.low <= min(recent_lows):
                # Today is up from yesterday
                if self._is_up_day(today, yesterday):
                    return i
        
        return None
    
    def update_rally_status(
        self,
        symbol: str,
        daily_bars: List[DailyBar]
    ) -> RallyStatus:
        """
        Update rally attempt status for a symbol.
        
        This is the main method to call daily. It will:
        1. Check if we're in an active rally attempt
        2. Detect if today is an FTD
        3. Detect if the rally attempt failed
        4. Start new rally attempts when appropriate
        
        Args:
            symbol: 'SPY', 'QQQ', or 'DIA'
            daily_bars: List of DailyBar (oldest to newest)
        
        Returns:
            RallyStatus with current state
        """
        if len(daily_bars) < 5:
            return RallyStatus(
                symbol=symbol,
                in_rally_attempt=False,
                rally_day=0,
                rally_low=0,
                rally_low_date=date.today()
            )
        
        today = daily_bars[-1]
        yesterday = daily_bars[-2]
        current_date = today.date
        
        # Get active rally attempt
        active_rally = self.db.query(RallyAttempt).filter(
            RallyAttempt.symbol == symbol,
            RallyAttempt.active == True
        ).first()
        
        # Check for confirmed FTD (still valid)
        last_ftd = self.db.query(FollowThroughDay).filter(
            FollowThroughDay.symbol == symbol,
            FollowThroughDay.confirmed == True
        ).order_by(FollowThroughDay.date.desc()).first()
        
        ftd_still_valid = False
        if last_ftd:
            # Check if FTD has been undercut
            ftd_still_valid = not self._check_ftd_failure(last_ftd, today)
        
        # Initialize result
        result = RallyStatus(
            symbol=symbol,
            in_rally_attempt=active_rally is not None,
            rally_day=active_rally.day_count if active_rally else 0,
            rally_low=active_rally.rally_low if active_rally else 0,
            rally_low_date=active_rally.rally_low_date if active_rally else current_date,
            has_confirmed_ftd=last_ftd is not None and last_ftd.confirmed,
            last_ftd_date=last_ftd.date if last_ftd else None,
            ftd_still_valid=ftd_still_valid
        )
        
        if active_rally:
            # Check if rally failed (undercut rally low)
            if today.low < active_rally.rally_low:
                active_rally.active = False
                active_rally.succeeded = False
                active_rally.failure_date = current_date
                active_rally.failure_reason = 'UNDERCUT'
                self.db.commit()
                
                result.in_rally_attempt = False
                result.failed_today = True
                result.failure_reason = 'UNDERCUT'
                
                logger.info(f"{symbol} rally attempt FAILED - undercut rally low")
                return result
            
            # Increment day count
            active_rally.day_count += 1
            
            # Check for FTD
            is_ftd, gain_pct, vol_ratio = self._is_valid_ftd(
                today, yesterday, active_rally.day_count
            )
            
            if is_ftd:
                # Record FTD
                active_rally.active = False
                active_rally.succeeded = True
                active_rally.ftd_date = current_date
                active_rally.ftd_gain_pct = gain_pct
                active_rally.ftd_volume_ratio = vol_ratio
                
                ftd = FollowThroughDay(
                    symbol=symbol,
                    date=current_date,
                    rally_day=active_rally.day_count,
                    gain_pct=gain_pct,
                    volume=today.volume,
                    prior_volume=yesterday.volume,
                    volume_ratio=vol_ratio,
                    close_price=today.close,
                    rally_low=active_rally.rally_low,
                    ftd_low=today.low
                )
                self.db.add(ftd)
                self.db.commit()
                
                result.ftd_today = True
                result.ftd_date = current_date
                result.ftd_gain_pct = gain_pct
                result.has_confirmed_ftd = True
                result.last_ftd_date = current_date
                result.ftd_still_valid = True
                
                logger.info(
                    f"{symbol} FOLLOW-THROUGH DAY! "
                    f"Day {active_rally.day_count}, +{gain_pct:.2f}%, "
                    f"Vol ratio: {vol_ratio:.2f}x"
                )
            else:
                self.db.commit()
                result.rally_day = active_rally.day_count
        
        else:
            # No active rally - check if we should start one
            # Start rally on first up day after decline
            if self._is_up_day(today, yesterday):
                # Check if we're coming off a decline
                recent_bars = daily_bars[-20:]
                if len(recent_bars) >= 5:
                    high_point = max(b.high for b in recent_bars[:-1])
                    decline_pct = (yesterday.close - high_point) / high_point * 100
                    
                    if decline_pct <= self.CORRECTION_THRESHOLD:
                        # Start new rally attempt
                        rally = RallyAttempt(
                            symbol=symbol,
                            start_date=current_date,
                            rally_low=yesterday.low,
                            rally_low_date=yesterday.date,
                            day_count=1
                        )
                        self.db.add(rally)
                        self.db.commit()
                        
                        result.in_rally_attempt = True
                        result.rally_day = 1
                        result.rally_low = yesterday.low
                        result.rally_low_date = yesterday.date
                        
                        logger.info(
                            f"{symbol} NEW RALLY ATTEMPT started. "
                            f"Rally low: {yesterday.low:.2f} on {yesterday.date}"
                        )
        
        return result
    
    def _check_ftd_failure(self, ftd: FollowThroughDay, today: DailyBar) -> bool:
        """
        Check if an FTD has failed (been undercut).
        
        FTD fails if price undercuts either:
        1. The rally low (original low before rally started)
        2. The FTD day's low (more conservative)
        """
        if ftd.failed:
            return True
        
        # Check undercut of rally low (primary failure condition)
        if today.low < ftd.rally_low:
            ftd.confirmed = False
            ftd.failed = True
            ftd.failure_date = today.date
            ftd.failure_reason = 'UNDERCUT_RALLY_LOW'
            self.db.commit()
            
            logger.info(f"{ftd.symbol} FTD FAILED - undercut rally low")
            return True
        
        return False
    
    def get_market_phase_status(
        self,
        spy_bars: List[DailyBar],
        qqq_bars: List[DailyBar],
        spy_d_count: int = 0,
        qqq_d_count: int = 0
    ) -> MarketPhaseStatus:
        """
        Get combined market phase status across SPY and QQQ.
        
        This determines the overall market phase for regime calculation.
        
        Args:
            spy_bars: SPY daily bars
            qqq_bars: QQQ daily bars
            spy_d_count: Current SPY distribution day count
            qqq_d_count: Current QQQ distribution day count
        
        Returns:
            MarketPhaseStatus with combined signals
        """
        spy_status = self.update_rally_status('SPY', spy_bars)
        qqq_status = self.update_rally_status('QQQ', qqq_bars)
        
        # Determine overall phase
        any_ftd_today = spy_status.ftd_today or qqq_status.ftd_today
        any_confirmed_ftd = spy_status.has_confirmed_ftd or qqq_status.has_confirmed_ftd
        any_ftd_valid = spy_status.ftd_still_valid or qqq_status.ftd_still_valid
        any_rally_attempt = spy_status.in_rally_attempt or qqq_status.in_rally_attempt
        any_rally_failed = spy_status.failed_today or qqq_status.failed_today
        
        total_d_days = spy_d_count + qqq_d_count
        
        # Determine phase
        if any_confirmed_ftd and any_ftd_valid:
            if total_d_days >= 5:
                phase = MarketPhase.UPTREND_PRESSURE
            else:
                phase = MarketPhase.CONFIRMED_UPTREND
        elif any_rally_attempt:
            phase = MarketPhase.RALLY_ATTEMPT
        else:
            phase = MarketPhase.CORRECTION
        
        # Calculate FTD score adjustment for regime
        ftd_score_adjustment = 0.0
        
        if any_ftd_today:
            ftd_score_adjustment = 0.5  # Significant bullish boost
        elif any_confirmed_ftd and any_ftd_valid:
            # Confirmed uptrend - moderate boost
            days_since = 0
            if spy_status.last_ftd_date:
                days_since = max(days_since, (date.today() - spy_status.last_ftd_date).days)
            if qqq_status.last_ftd_date:
                days_since = max(days_since, (date.today() - qqq_status.last_ftd_date).days)
            
            # Boost decays over time
            if days_since <= 5:
                ftd_score_adjustment = 0.3
            elif days_since <= 15:
                ftd_score_adjustment = 0.2
            elif days_since <= 25:
                ftd_score_adjustment = 0.1
        elif any_rally_attempt:
            # In rally attempt - slight positive bias
            ftd_score_adjustment = 0.1
        elif any_rally_failed:
            # Rally failed today - negative
            ftd_score_adjustment = -0.3
        
        # Days since last FTD
        days_since_ftd = None
        for status in [spy_status, qqq_status]:
            if status.last_ftd_date:
                days = (date.today() - status.last_ftd_date).days
                if days_since_ftd is None or days < days_since_ftd:
                    days_since_ftd = days
        
        return MarketPhaseStatus(
            phase=phase,
            spy_status=spy_status,
            qqq_status=qqq_status,
            any_ftd_today=any_ftd_today,
            any_rally_failed=any_rally_failed,
            days_since_last_ftd=days_since_ftd,
            ftd_score_adjustment=ftd_score_adjustment
        )
    
    def get_ftd_history(self, symbol: str = None, limit: int = 10) -> List[Dict]:
        """Get recent FTD history."""
        query = self.db.query(FollowThroughDay)
        if symbol:
            query = query.filter(FollowThroughDay.symbol == symbol)
        
        ftds = query.order_by(FollowThroughDay.date.desc()).limit(limit).all()
        
        return [
            {
                'symbol': f.symbol,
                'date': f.date,
                'rally_day': f.rally_day,
                'gain_pct': f.gain_pct,
                'volume_ratio': f.volume_ratio,
                'confirmed': f.confirmed,
                'failed': f.failed,
                'failure_reason': f.failure_reason
            }
            for f in ftds
        ]
    
    def get_rally_attempt_history(
        self, 
        symbol: str = None, 
        lookback_days: int = 60
    ) -> List[Dict]:
        """
        Get rally attempt history for histogram building.
        
        Returns list of rally attempts with their outcomes.
        """
        from datetime import timedelta
        cutoff = date.today() - timedelta(days=lookback_days)
        
        query = self.db.query(RallyAttempt).filter(
            RallyAttempt.start_date >= cutoff
        )
        if symbol:
            query = query.filter(RallyAttempt.symbol == symbol)
        
        rallies = query.order_by(RallyAttempt.start_date).all()
        
        return [
            {
                'symbol': r.symbol,
                'start_date': r.start_date,
                'rally_low': r.rally_low,
                'day_count': r.day_count,
                'active': r.active,
                'succeeded': r.succeeded,
                'ftd_date': r.ftd_date,
                'failure_date': r.failure_date,
                'failure_reason': r.failure_reason
            }
            for r in rallies
        ]
    
    def build_rally_histogram(
        self,
        trading_days: List[date],
        symbol: str = None
    ) -> 'RallyHistogram':
        """
        Build a rally attempt histogram for a list of trading days.
        
        Args:
            trading_days: List of trading dates (oldest to newest)
            symbol: Filter by symbol (None = combined SPY/QQQ)
            
        Returns:
            RallyHistogram object with visualization data
        """
        # Get all rally attempts that overlap with our date range
        if not trading_days:
            return RallyHistogram(days=[], failed_count=0, success_count=0)
        
        start_date = trading_days[0]
        end_date = trading_days[-1]
        
        query = self.db.query(RallyAttempt).filter(
            RallyAttempt.start_date <= end_date
        )
        if symbol:
            query = query.filter(RallyAttempt.symbol == symbol)
        
        rallies = query.order_by(RallyAttempt.start_date).all()
        
        # Build day-by-day status
        days = []
        failed_count = 0
        success_count = 0
        
        for day in trading_days:
            day_status = RallyDayStatus(
                date=day,
                status='neutral',  # neutral, rally_1-10, failed, ftd
                rally_day=0,
                symbol=None
            )
            
            # Check each rally attempt to see if it was active on this day
            for rally in rallies:
                # Calculate what day of the rally this date would be
                if rally.start_date <= day:
                    # Check if rally ended before this day
                    end_date_for_rally = rally.ftd_date or rally.failure_date
                    
                    if end_date_for_rally and day > end_date_for_rally:
                        # Rally ended before this day
                        # Check if this is the failure day
                        if rally.failure_date == day:
                            day_status.status = 'failed'
                            day_status.symbol = rally.symbol
                            failed_count += 1
                        continue
                    
                    if rally.ftd_date == day:
                        # FTD happened this day
                        day_status.status = 'ftd'
                        day_status.rally_day = rally.day_count
                        day_status.symbol = rally.symbol
                        success_count += 1
                        break
                    
                    if rally.failure_date == day:
                        # Rally failed this day
                        day_status.status = 'failed'
                        day_status.rally_day = rally.day_count
                        day_status.symbol = rally.symbol
                        # Don't increment failed_count here - we do it above
                        break
                    
                    # Calculate day number within the rally
                    # This is approximate - would need trading calendar for accuracy
                    days_since_start = (day - rally.start_date).days
                    # Rough estimate: ~5 trading days per 7 calendar days
                    trading_days_estimate = int(days_since_start * 5 / 7) + 1
                    
                    if rally.active or (end_date_for_rally and day <= end_date_for_rally):
                        day_status.status = f'rally_{min(trading_days_estimate, 10)}'
                        day_status.rally_day = min(trading_days_estimate, 10)
                        day_status.symbol = rally.symbol
                        break
            
            days.append(day_status)
        
        # Recount failures and successes more accurately
        failed_count = sum(1 for d in days if d.status == 'failed')
        success_count = sum(1 for d in days if d.status == 'ftd')
        
        return RallyHistogram(
            days=days,
            failed_count=failed_count,
            success_count=success_count
        )


@dataclass
class RallyDayStatus:
    """Status of a single day in the rally histogram."""
    date: date
    status: str  # 'neutral', 'rally_1' through 'rally_10', 'failed', 'ftd'
    rally_day: int
    symbol: Optional[str]


@dataclass 
class RallyHistogram:
    """Rally attempt histogram data."""
    days: List[RallyDayStatus]
    failed_count: int
    success_count: int
    
    def to_ascii(self, width: int = 25) -> str:
        """
        Generate ASCII histogram representation.
        
        Shows last `width` trading days with:
        · = Neutral (no rally)
        1-9 = Rally day number
        ✗ = Rally failed
        ✓ = FTD success
        """
        if not self.days:
            return "No data available"
        
        # Take last `width` days
        display_days = self.days[-width:] if len(self.days) > width else self.days
        
        # Build the histogram line
        chars = []
        for day in display_days:
            if day.status == 'neutral':
                chars.append('·')
            elif day.status == 'failed':
                chars.append('✗')
            elif day.status == 'ftd':
                chars.append('✓')
            elif day.status.startswith('rally_'):
                day_num = day.rally_day
                if day_num <= 9:
                    chars.append(str(day_num))
                else:
                    chars.append('+')  # Day 10+
            else:
                chars.append('·')
        
        histogram_line = ' '.join(chars)
        
        # Build date markers
        if display_days:
            start_str = display_days[0].date.strftime('%m/%d')
            end_str = display_days[-1].date.strftime('%m/%d')
            date_line = f"{start_str}" + " " * (len(histogram_line) - len(start_str) - len(end_str)) + f"{end_str}"
        else:
            date_line = ""
        
        # Summary
        total_attempts = self.failed_count + self.success_count
        if total_attempts > 0:
            success_rate = self.success_count / total_attempts * 100
        else:
            success_rate = 0
        
        summary = f"Attempts: {total_attempts} | Failed: {self.failed_count} | FTDs: {self.success_count}"
        if total_attempts > 0:
            summary += f" ({success_rate:.0f}% success)"
        
        return f"{histogram_line}\n{date_line}\n{summary}"
    
    def to_discord(self, width: int = 25) -> str:
        """Generate Discord-formatted histogram."""
        if not self.days:
            return "```\nNo rally attempt data available\n```"
        
        # Take last `width` days
        display_days = self.days[-width:] if len(self.days) > width else self.days
        
        # Build the histogram with better symbols for Discord
        chars = []
        for day in display_days:
            if day.status == 'neutral':
                chars.append('·')
            elif day.status == 'failed':
                chars.append('✗')
            elif day.status == 'ftd':
                chars.append('✓')
            elif day.status.startswith('rally_'):
                day_num = day.rally_day
                if day_num <= 9:
                    chars.append(str(day_num))
                else:
                    chars.append('+')
            else:
                chars.append('·')
        
        histogram_line = ' '.join(chars)
        
        # Date markers
        if display_days:
            start_str = display_days[0].date.strftime('%m/%d')
            end_str = display_days[-1].date.strftime('%m/%d')
        else:
            start_str = end_str = ""
        
        # Legend
        legend = "· = No rally | 1-9 = Rally day | ✗ = Failed | ✓ = FTD"
        
        # Summary with emphasis on failures
        total_attempts = self.failed_count + self.success_count
        
        if self.failed_count >= 3 and self.success_count == 0:
            warning = "⚠️ Multiple failed rallies - weak market"
        elif self.failed_count >= 2 and self.success_count == 0:
            warning = "⚠️ Consecutive failures - use caution"
        elif self.success_count > 0 and self.failed_count == 0:
            warning = "✅ Clean FTD - favorable conditions"
        else:
            warning = ""
        
        result = f"""```
Rally Attempts ({len(display_days)} trading days)
{'─' * 50}
{histogram_line}
{start_str:<25}{end_str:>25}
{'─' * 50}
{legend}
Failed: {self.failed_count} | Successful FTDs: {self.success_count}
```"""
        
        if warning:
            result += f"\n{warning}"
        
        return result


# Create tables helper
def create_ftd_tables(engine):
    """Create FTD-related tables."""
    Base.metadata.create_all(engine)


if __name__ == '__main__':
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from historical_data import fetch_spy_qqq_daily
    
    print("Testing Follow-Through Day Tracker...")
    
    # Create in-memory database
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Fetch data
    data = fetch_spy_qqq_daily(lookback_days=60)
    
    # Create tracker
    tracker = FollowThroughDayTracker(session)
    
    # Get market phase
    status = tracker.get_market_phase_status(
        data['SPY'], data['QQQ'],
        spy_d_count=3, qqq_d_count=2
    )
    
    print(f"\n=== Market Phase Status ===")
    print(f"Phase: {status.phase.value}")
    print(f"SPY Rally: Day {status.spy_status.rally_day}, FTD Valid: {status.spy_status.ftd_still_valid}")
    print(f"QQQ Rally: Day {status.qqq_status.rally_day}, FTD Valid: {status.qqq_status.ftd_still_valid}")
    print(f"FTD Score Adjustment: {status.ftd_score_adjustment:+.2f}")
    
    if status.any_ftd_today:
        print("\n🎉 FOLLOW-THROUGH DAY TODAY!")
