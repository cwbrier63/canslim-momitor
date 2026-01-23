"""
Technical Indicator Calculations for CANSLIM Scoring

PORTED FROM: canslim_validation/canslim_validation/indicators.py
PORTED TO: canslim_monitor/canslim_monitor/utils/indicators.py
DATE: 2026-01-16

Based on MarketSurge/IBD methodology from webinar transcripts:
- Arnie Gutierrez: "The Anatomy of a Healthy Chart Pattern"
- Jacob: "Base Stage Counting"

Key indicators:
1. Up/Down Volume Ratio (Arnie: "anything above 1.1 tells me there's demand")
2. 50-Day MA Position (price relative to moving average)
3. 10-Week Support Bounces (institutional support signal)
4. RS Line Trend (relative strength vs S&P 500)
5. Volume Dry-Up Score (consolidation quality)
6. Breakout Volume Confirmation (Arnie: "minimum 20% above 50-day average")
"""

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Tuple, Optional, Dict, List
from dataclasses import dataclass


@dataclass
class IndicatorResult:
    """Result of an indicator calculation."""
    name: str
    value: float
    score: int
    description: str
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


@dataclass 
class TechnicalProfile:
    """Complete technical profile for a symbol."""
    symbol: str
    analysis_date: date
    
    # Raw indicator values
    up_down_ratio: float = None
    ma_50: float = None
    ma_200: float = None
    ma_10w: float = None
    current_price: float = None
    avg_volume_50d: float = None
    avg_volume_10w: float = None
    
    # Calculated scores
    updown_ratio_score: int = 0
    ma_position_score: int = 0
    support_bounce_score: int = 0
    rs_trend_score: int = 0
    volume_dryup_score: int = 0
    
    # Composite
    dynamic_score: int = 0
    
    # Details for each indicator
    indicator_details: Dict = None
    
    def __post_init__(self):
        if self.indicator_details is None:
            self.indicator_details = {}


def calculate_sma(prices: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average."""
    return prices.rolling(window=period, min_periods=period).mean()


def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return prices.ewm(span=period, adjust=False).mean()


def aggregate_to_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate daily OHLCV data to weekly.
    
    Expects columns: date, open, high, low, close, volume
    Returns weekly bars with same columns.
    """
    df = daily_df.copy()
    
    # Ensure date is datetime
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'])
    
    df.set_index('date', inplace=True)
    
    # Resample to weekly (Friday close)
    weekly = df.resample('W-FRI').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    weekly.reset_index(inplace=True)
    return weekly


def calculate_up_down_volume_ratio(
    daily_df: pd.DataFrame,
    lookback_days: int = 50
) -> IndicatorResult:
    """
    Calculate Up/Down Volume Ratio.
    
    Arnie: "anything above 1.1 tells me there's demand...
           below 1.0 tells me there's more down days than up days on above average volume"
    
    Method:
    1. Identify up days (close > previous close) with above-average volume
    2. Identify down days (close < previous close) with above-average volume
    3. Ratio = up_count / down_count
    
    Scoring:
    - >= 1.5: +3 (Strong accumulation)
    - 1.2-1.49: +2 (Good demand)
    - 1.1-1.19: +1 (Acceptable - Arnie's minimum)
    - 0.9-1.09: 0 (Neutral)
    - < 0.9: -2 (Distribution concern)
    """
    df = daily_df.tail(lookback_days).copy()
    
    if len(df) < 20:
        return IndicatorResult(
            name="Up/Down Volume Ratio",
            value=0,
            score=0,
            description="Insufficient data",
            details={"error": "Need at least 20 days of data"}
        )
    
    # Calculate price change
    df['price_change'] = df['close'].diff()
    
    # Calculate average volume (use all available data for more stable average)
    avg_volume = df['volume'].mean()
    
    # Flag above-average volume days
    df['above_avg_vol'] = df['volume'] > avg_volume
    
    # Count up days with above-average volume
    up_days = df[(df['price_change'] > 0) & df['above_avg_vol']]
    up_count = len(up_days)
    
    # Count down days with above-average volume  
    down_days = df[(df['price_change'] < 0) & df['above_avg_vol']]
    down_count = len(down_days)
    
    # Calculate ratio (avoid division by zero)
    if down_count == 0:
        ratio = 3.0 if up_count > 0 else 1.0  # Cap at 3.0
    else:
        ratio = round(up_count / down_count, 2)
    
    # Determine score
    if ratio >= 1.5:
        score = 3
        desc = "Strong accumulation"
    elif ratio >= 1.2:
        score = 2
        desc = "Good demand"
    elif ratio >= 1.1:
        score = 1
        desc = "Acceptable demand"
    elif ratio >= 0.9:
        score = 0
        desc = "Neutral"
    else:
        score = -2
        desc = "Distribution concern"
    
    return IndicatorResult(
        name="Up/Down Volume Ratio",
        value=ratio,
        score=score,
        description=desc,
        details={
            "up_days_above_avg": up_count,
            "down_days_above_avg": down_count,
            "avg_volume": int(avg_volume),
            "lookback_days": lookback_days
        }
    )


def calculate_ma_position(
    daily_df: pd.DataFrame,
    current_price: float = None
) -> IndicatorResult:
    """
    Determine price position relative to 50-day MA.
    
    Arnie: "Is it trading above the 50-day? Is it trading below?"
    
    Scoring:
    - Price > 50-MA and MA trending up: +2 (Ideal position)
    - Price > 50-MA, MA flat: +1 (Good position)
    - Price ≈ 50-MA (within 2%): 0 (Testing support)
    - Price < 50-MA, recently crossed: -1 (Caution)
    - Price < 50-MA for extended period: -2 (Weak position)
    """
    if len(daily_df) < 50:
        return IndicatorResult(
            name="50-Day MA Position",
            value=0,
            score=0,
            description="Insufficient data for 50-day MA",
            details={"error": "Need at least 50 days of data"}
        )
    
    df = daily_df.copy()
    
    # Calculate 50-day MA
    df['ma_50'] = calculate_sma(df['close'], 50)
    
    # Get current values
    if current_price is None:
        current_price = df['close'].iloc[-1]
    
    ma_50 = df['ma_50'].iloc[-1]
    ma_50_prev = df['ma_50'].iloc[-6] if len(df) > 55 else ma_50  # 5 days ago
    
    # Calculate MA slope (positive = trending up)
    ma_slope = (ma_50 - ma_50_prev) / ma_50_prev * 100 if ma_50_prev > 0 else 0
    
    # Calculate percent from MA
    pct_from_ma = (current_price - ma_50) / ma_50 * 100 if ma_50 > 0 else 0
    
    # Determine score and description
    if pct_from_ma > 2 and ma_slope > 0.5:
        score = 2
        desc = "Above rising 50-MA"
    elif pct_from_ma > 2:
        score = 1
        desc = "Above flat 50-MA"
    elif abs(pct_from_ma) <= 2:
        score = 0
        desc = "Testing 50-MA support"
    elif pct_from_ma > -5:
        score = -1
        desc = "Below 50-MA (recent)"
    else:
        score = -2
        desc = "Below 50-MA (extended)"
    
    return IndicatorResult(
        name="50-Day MA Position",
        value=round(pct_from_ma, 2),
        score=score,
        description=desc,
        details={
            "current_price": round(current_price, 2),
            "ma_50": round(ma_50, 2),
            "ma_slope_pct": round(ma_slope, 2),
            "pct_from_ma": round(pct_from_ma, 2)
        }
    )


def detect_10week_support_bounces(
    daily_df: pd.DataFrame,
    base_weeks: int = 12
) -> IndicatorResult:
    """
    Count bounces off 10-week MA during base formation.
    
    Arnie: "stock living above or finding support at 10-week line
           is a sign of institutional support"
           "Anytime it tries to get to that line, either bounces off,
           and if it does pop through, it immediately comes right back up"
    
    A bounce is defined as:
    - Weekly low touches or penetrates 10-week MA (within 2%)
    - Weekly close is above 10-week MA
    
    Scoring:
    - 3+ bounces: +3 (Strong institutional support)
    - 2 bounces: +2 (Good support)
    - 1 bounce: +1 (Some support)
    - 0 bounces, living above: 0 (Neutral)
    - Broke below, slow recovery: -1 (Weak support)
    - Broke below on heavy volume: -2 (Distribution)
    """
    # Aggregate to weekly
    weekly_df = aggregate_to_weekly(daily_df)
    
    if len(weekly_df) < 12:
        return IndicatorResult(
            name="10-Week Support Bounces",
            value=0,
            score=0,
            description="Insufficient weekly data",
            details={"error": "Need at least 12 weeks of data"}
        )
    
    # Calculate 10-week MA
    weekly_df['ma_10w'] = calculate_sma(weekly_df['close'], 10)
    
    # Analyze last N weeks (base period)
    analysis_period = weekly_df.tail(base_weeks).copy()
    
    bounces = 0
    breakdowns = 0
    bounce_weeks = []
    
    for i, row in analysis_period.iterrows():
        ma = row['ma_10w']
        if pd.isna(ma):
            continue
            
        # Check for bounce: low touches MA (within 2%) and close above
        low_near_ma = row['low'] <= ma * 1.02
        closed_above = row['close'] > ma
        
        if low_near_ma and closed_above:
            bounces += 1
            bounce_weeks.append(row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date']))
        
        # Check for breakdown: close below MA
        if row['close'] < ma * 0.98:
            breakdowns += 1
    
    # Determine score
    if bounces >= 3:
        score = 3
        desc = f"Strong support ({bounces} bounces)"
    elif bounces == 2:
        score = 2
        desc = f"Good support ({bounces} bounces)"
    elif bounces == 1:
        score = 1
        desc = f"Some support ({bounces} bounce)"
    elif breakdowns == 0:
        score = 0
        desc = "Living above 10-week MA"
    elif breakdowns <= 2:
        score = -1
        desc = f"Weak support ({breakdowns} breakdowns)"
    else:
        score = -2
        desc = f"Distribution ({breakdowns} breakdowns)"
    
    return IndicatorResult(
        name="10-Week Support Bounces",
        value=bounces,
        score=score,
        description=desc,
        details={
            "bounces": bounces,
            "breakdowns": breakdowns,
            "bounce_weeks": bounce_weeks,
            "weeks_analyzed": len(analysis_period),
            "ma_10w_current": round(weekly_df['ma_10w'].iloc[-1], 2) if not pd.isna(weekly_df['ma_10w'].iloc[-1]) else None
        }
    )


def calculate_rs_trend(
    stock_daily_df: pd.DataFrame,
    index_daily_df: pd.DataFrame,
    lookback_days: int = 50
) -> IndicatorResult:
    """
    Calculate Relative Strength line trend.
    
    Arnie: "RS line pointing 12 o'clock, 1 o'clock, 2 o'clock...
           if making all-time high, added value"
           "That's also a great technical indicator, meaning that this
           stock's price action is outperforming the S&P 500"
    
    RS = Stock Price / Index Price (normalized)
    
    Scoring:
    - RS at new high (before price breakout): +2 (Leading indicator - bullish)
    - RS trending up (positive slope): +1 (Outperforming market)
    - RS flat: 0 (In line with market)
    - RS trending down: -1 (Underperforming market)
    """
    stock_df = stock_daily_df.tail(lookback_days).copy()
    index_df = index_daily_df.tail(lookback_days).copy()
    
    if len(stock_df) < 20 or len(index_df) < 20:
        return IndicatorResult(
            name="RS Line Trend",
            value=0,
            score=0,
            description="Insufficient data",
            details={"error": "Need at least 20 days of data"}
        )
    
    # Ensure both have date column and merge
    stock_df['date'] = pd.to_datetime(stock_df['date'])
    index_df['date'] = pd.to_datetime(index_df['date'])
    
    merged = stock_df.merge(
        index_df[['date', 'close']], 
        on='date', 
        suffixes=('_stock', '_index')
    )
    
    if len(merged) < 20:
        return IndicatorResult(
            name="RS Line Trend",
            value=0,
            score=0,
            description="Insufficient overlapping data",
            details={"error": "Stock and index dates don't align"}
        )
    
    # Calculate RS line
    merged['rs'] = merged['close_stock'] / merged['close_index']
    
    # Normalize to start at 100
    merged['rs_normalized'] = merged['rs'] / merged['rs'].iloc[0] * 100
    
    # Calculate trend (linear regression slope)
    x = np.arange(len(merged))
    slope, intercept = np.polyfit(x, merged['rs_normalized'].values, 1)
    
    # Check if RS is at or near new high
    rs_current = merged['rs_normalized'].iloc[-1]
    rs_max = merged['rs_normalized'].max()
    rs_at_high = rs_current >= rs_max * 0.98  # Within 2% of high
    
    # Determine score
    if rs_at_high and slope > 0:
        score = 2
        desc = "RS at new high"
    elif slope > 0.05:  # Meaningful upward slope
        score = 1
        desc = "RS trending up"
    elif abs(slope) <= 0.05:
        score = 0
        desc = "RS flat"
    else:
        score = -1
        desc = "RS trending down"
    
    return IndicatorResult(
        name="RS Line Trend",
        value=round(slope, 4),
        score=score,
        description=desc,
        details={
            "rs_slope": round(slope, 4),
            "rs_current": round(rs_current, 2),
            "rs_high": round(rs_max, 2),
            "rs_at_new_high": rs_at_high,
            "days_analyzed": len(merged)
        }
    )


def calculate_volume_dryup(
    daily_df: pd.DataFrame,
    base_days: int = 50,
    recent_days: int = 10
) -> IndicatorResult:
    """
    Measure volume contraction during consolidation.
    
    Arnie: "volume dries up... no selling taking place, holding steady"
           "consolidation part... volume dries up. We had a huge move.
           And then it just dries up."
    
    Compare recent average volume to base period average volume.
    Lower recent volume = tighter consolidation = more bullish.
    
    Scoring:
    - Recent vol < 50% of base avg: +2 (Classic dry-up - bullish)
    - Recent vol 50-75% of base avg: +1 (Moderate dry-up)
    - Recent vol > 75% of base avg: 0 (No significant dry-up)
    """
    if len(daily_df) < base_days:
        return IndicatorResult(
            name="Volume Dry-Up",
            value=1.0,
            score=0,
            description="Insufficient data",
            details={"error": f"Need at least {base_days} days of data"}
        )
    
    # Calculate base period average (excluding recent days)
    base_period = daily_df.tail(base_days).head(base_days - recent_days)
    base_avg_vol = base_period['volume'].mean()
    
    # Calculate recent average
    recent_period = daily_df.tail(recent_days)
    recent_avg_vol = recent_period['volume'].mean()
    
    # Calculate ratio
    if base_avg_vol > 0:
        ratio = recent_avg_vol / base_avg_vol
    else:
        ratio = 1.0
    
    # Determine score
    if ratio < 0.5:
        score = 2
        desc = "Classic volume dry-up"
    elif ratio < 0.75:
        score = 1
        desc = "Moderate volume contraction"
    else:
        score = 0
        desc = "No significant dry-up"
    
    return IndicatorResult(
        name="Volume Dry-Up",
        value=round(ratio, 2),
        score=score,
        description=desc,
        details={
            "base_avg_volume": int(base_avg_vol),
            "recent_avg_volume": int(recent_avg_vol),
            "ratio": round(ratio, 2),
            "base_days": base_days,
            "recent_days": recent_days
        }
    )


def calculate_breakout_volume_score(
    current_volume: int,
    avg_50d_volume: float
) -> IndicatorResult:
    """
    Validate breakout volume.
    
    Arnie: "minimum of 20% above 50-day average volume"
           "if it breaks through the pivot, I want to see above average volume"
           "91% above his 50 day average volume... that's when it hit its pivot price"
    
    Scoring:
    - Vol >= 150% above avg: +5 (Exceptional - like Arnie's 91% example)
    - Vol >= 100% above avg: +3 (Strong)
    - Vol >= 50% above avg: +2 (Good)
    - Vol >= 20% above avg: +1 (Minimum acceptable - Arnie's threshold)
    - Vol 0-20% above avg: 0 (Below threshold)
    - Vol below avg: -3 (Weak/suspect breakout)
    """
    if avg_50d_volume <= 0:
        return IndicatorResult(
            name="Breakout Volume",
            value=0,
            score=0,
            description="Invalid average volume",
            details={"error": "Average volume must be positive"}
        )
    
    pct_above = ((current_volume - avg_50d_volume) / avg_50d_volume) * 100
    
    if pct_above >= 150:
        score = 5
        desc = "Exceptional volume"
    elif pct_above >= 100:
        score = 3
        desc = "Strong volume"
    elif pct_above >= 50:
        score = 2
        desc = "Good volume"
    elif pct_above >= 20:
        score = 1
        desc = "Minimum acceptable"
    elif pct_above >= 0:
        score = 0
        desc = "Below threshold"
    else:
        score = -3
        desc = "Weak breakout volume"
    
    return IndicatorResult(
        name="Breakout Volume",
        value=round(pct_above, 1),
        score=score,
        description=desc,
        details={
            "current_volume": current_volume,
            "avg_50d_volume": int(avg_50d_volume),
            "pct_above_avg": round(pct_above, 1)
        }
    )


def calculate_50day_avg_volume(daily_df: pd.DataFrame) -> float:
    """Calculate 50-day average volume."""
    if len(daily_df) < 50:
        return daily_df['volume'].mean()
    return daily_df.tail(50)['volume'].mean()


def build_technical_profile(
    symbol: str,
    daily_df: pd.DataFrame,
    index_df: pd.DataFrame = None,
    analysis_date: date = None,
    base_length_weeks: int = 12
) -> TechnicalProfile:
    """
    Build complete technical profile for a symbol.
    
    Args:
        symbol: Stock ticker
        daily_df: Daily OHLCV data with columns: date, open, high, low, close, volume
        index_df: S&P 500 daily data for RS calculation (optional)
        analysis_date: Date of analysis (defaults to last date in data)
        base_length_weeks: Length of base for analysis
    
    Returns:
        TechnicalProfile with all indicators calculated
    """
    if analysis_date is None:
        analysis_date = daily_df['date'].max()
        if hasattr(analysis_date, 'date'):
            analysis_date = analysis_date.date()
    
    profile = TechnicalProfile(
        symbol=symbol,
        analysis_date=analysis_date
    )
    
    # Current price and volume metrics
    profile.current_price = daily_df['close'].iloc[-1]
    profile.avg_volume_50d = calculate_50day_avg_volume(daily_df)
    
    # Calculate 50-day MA
    if len(daily_df) >= 50:
        profile.ma_50 = calculate_sma(daily_df['close'], 50).iloc[-1]
    
    # Calculate 200-day MA
    if len(daily_df) >= 200:
        profile.ma_200 = calculate_sma(daily_df['close'], 200).iloc[-1]
    
    # Calculate weekly 10-week MA
    weekly_df = aggregate_to_weekly(daily_df)
    if len(weekly_df) >= 10:
        weekly_df['ma_10w'] = calculate_sma(weekly_df['close'], 10)
        profile.ma_10w = weekly_df['ma_10w'].iloc[-1]
        profile.avg_volume_10w = weekly_df.tail(10)['volume'].mean()
    
    # Calculate all indicators
    base_days = base_length_weeks * 5  # Approximate trading days
    
    # 1. Up/Down Volume Ratio
    updown_result = calculate_up_down_volume_ratio(daily_df, lookback_days=base_days)
    profile.up_down_ratio = updown_result.value
    profile.updown_ratio_score = updown_result.score
    profile.indicator_details['up_down_ratio'] = updown_result
    
    # 2. 50-Day MA Position
    ma_result = calculate_ma_position(daily_df, profile.current_price)
    profile.ma_position_score = ma_result.score
    profile.indicator_details['ma_position'] = ma_result
    
    # 3. 10-Week Support Bounces
    bounce_result = detect_10week_support_bounces(daily_df, base_weeks=base_length_weeks)
    profile.support_bounce_score = bounce_result.score
    profile.indicator_details['support_bounces'] = bounce_result
    
    # 4. RS Line Trend (if index data provided)
    if index_df is not None and len(index_df) > 0:
        rs_result = calculate_rs_trend(daily_df, index_df)
        profile.rs_trend_score = rs_result.score
        profile.indicator_details['rs_trend'] = rs_result
    
    # 5. Volume Dry-Up
    dryup_result = calculate_volume_dryup(daily_df, base_days=base_days)
    profile.volume_dryup_score = dryup_result.score
    profile.indicator_details['volume_dryup'] = dryup_result
    
    # Calculate composite dynamic score
    profile.dynamic_score = (
        profile.updown_ratio_score +
        profile.ma_position_score +
        profile.support_bounce_score +
        profile.rs_trend_score +
        profile.volume_dryup_score
    )
    
    return profile
