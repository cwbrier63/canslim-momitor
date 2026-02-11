"""
CANSLIM Monitor - Market Data Cleaner
Validates and cleans OHLCV bars from Polygon to remove erroneous data.

Industry-standard approach:
1. Hard reject impossible values (negative prices, high < low)
2. Spike detection vs previous bar (clamp extreme deviations)
3. Wick reasonableness (clamp extreme wicks when body is normal)
4. Deduplicate dates
"""

import logging
from typing import List, Tuple, Optional

logger = logging.getLogger('canslim.data_clean')


def _bar_date(bar):
    """Get the date from a bar, supporting both DailyBar.date and Bar.bar_date."""
    return getattr(bar, 'date', None) or getattr(bar, 'bar_date', None)


# Maximum single-day price move allowed (as fraction of previous close).
# 50% accommodates legitimate large moves (earnings, biotech, splits)
# while catching clearly erroneous data (e.g., -400 on a $600 stock).
MAX_DAY_MOVE_PCT = 0.50

# Maximum wick extension beyond the candle body (as multiple of body range).
# A wick extending more than 3x the body range from open/close is suspicious.
MAX_WICK_BODY_MULTIPLE = 3.0


def validate_bar(bar) -> Tuple[bool, str]:
    """
    Hard validation of a single OHLCV bar. Returns (is_valid, reason).
    These checks have zero false positives - failures are always bad data.
    """
    if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
        return False, f"non-positive price (O={bar.open} H={bar.high} L={bar.low} C={bar.close})"

    if bar.high < bar.low:
        return False, f"high ({bar.high}) < low ({bar.low})"

    if bar.open > bar.high or bar.open < bar.low:
        return False, f"open ({bar.open}) outside [low={bar.low}, high={bar.high}]"

    if bar.close > bar.high or bar.close < bar.low:
        return False, f"close ({bar.close}) outside [low={bar.low}, high={bar.high}]"

    return True, ""


def clean_daily_bars(bars: list) -> list:
    """
    Clean a list of DailyBar objects by detecting and correcting anomalies.

    Pipeline:
    1. Remove duplicate dates (keep last)
    2. Hard-reject impossible bars (negative, high<low, etc.)
    3. Spike detection: clamp OHLC values that deviate >50% from previous close
    4. Wick reasonableness: clamp extreme wicks when candle body is normal

    Returns a new list of cleaned bars (original bars are not mutated).
    """
    if not bars:
        return bars

    # Step 1: Deduplicate dates (keep last occurrence)
    seen_dates = {}
    for i, bar in enumerate(bars):
        seen_dates[_bar_date(bar)] = i
    unique_indices = sorted(seen_dates.values())

    if len(unique_indices) < len(bars):
        dupes = len(bars) - len(unique_indices)
        logger.warning(f"[DATA_CLEAN] Removed {dupes} duplicate date(s)")
        bars = [bars[i] for i in unique_indices]

    cleaned = []
    prev_close = None

    for bar in bars:
        # Step 2: Hard reject impossible values
        is_valid, reason = validate_bar(bar)
        if not is_valid:
            logger.warning(
                f"[DATA_CLEAN] Dropped {_bar_date(bar)}: {reason}"
            )
            continue

        # Step 3: Spike detection vs previous bar
        if prev_close is not None and prev_close > 0:
            bar = _clamp_spike(bar, prev_close)

        # Step 4: Wick reasonableness
        bar = _clamp_wicks(bar)

        cleaned.append(bar)
        prev_close = bar.close

    return cleaned


def _clamp_spike(bar, prev_close: float):
    """
    If any OHLC value deviates more than MAX_DAY_MOVE_PCT from previous close,
    clamp it. This catches extreme erroneous values while preserving the bar.
    """
    from dataclasses import replace as dc_replace

    upper = prev_close * (1 + MAX_DAY_MOVE_PCT)
    lower = prev_close * (1 - MAX_DAY_MOVE_PCT)

    new_open = bar.open
    new_high = bar.high
    new_low = bar.low
    new_close = bar.close
    changed = False

    if bar.open > upper:
        new_open = upper
        changed = True
    elif bar.open < lower:
        new_open = lower
        changed = True

    if bar.close > upper:
        new_close = upper
        changed = True
    elif bar.close < lower:
        new_close = lower
        changed = True

    if bar.high > upper:
        new_high = upper
        changed = True
    elif bar.high < lower:
        new_high = lower
        changed = True

    if bar.low > upper:
        new_low = upper
        changed = True
    elif bar.low < lower:
        new_low = lower
        changed = True

    if changed:
        # Ensure OHLC integrity after clamping
        new_high = max(new_open, new_close, new_high, new_low)
        new_low = min(new_open, new_close, new_high, new_low)

        logger.warning(
            f"[DATA_CLEAN] Clamped spike on {_bar_date(bar)}: "
            f"prev_close={prev_close:.2f}, "
            f"O={bar.open:.2f}->{new_open:.2f}, H={bar.high:.2f}->{new_high:.2f}, "
            f"L={bar.low:.2f}->{new_low:.2f}, C={bar.close:.2f}->{new_close:.2f}"
        )
        return dc_replace(bar, open=new_open, high=new_high, low=new_low, close=new_close)

    return bar


def _clamp_wicks(bar):
    """
    If a wick extends more than MAX_WICK_BODY_MULTIPLE times the candle body
    beyond the body, clamp it. This catches false wicks while allowing
    legitimate hammer/shooting star patterns.
    """
    from dataclasses import replace as dc_replace

    body_high = max(bar.open, bar.close)
    body_low = min(bar.open, bar.close)
    body_range = body_high - body_low

    # For very small bodies (doji), use a minimum range based on price
    min_range = body_high * 0.005  # 0.5% of price
    effective_range = max(body_range, min_range)

    max_extension = effective_range * MAX_WICK_BODY_MULTIPLE

    new_high = bar.high
    new_low = bar.low
    changed = False

    # Check upper wick
    upper_wick = bar.high - body_high
    if upper_wick > max_extension:
        new_high = body_high + max_extension
        changed = True

    # Check lower wick
    lower_wick = body_low - bar.low
    if lower_wick > max_extension:
        new_low = body_low - max_extension
        changed = True

    # Ensure low doesn't go negative after clamping
    if new_low < 0:
        new_low = body_low * 0.95  # 5% below body low

    if changed:
        logger.warning(
            f"[DATA_CLEAN] Clamped wick on {_bar_date(bar)}: "
            f"H={bar.high:.2f}->{new_high:.2f}, L={bar.low:.2f}->{new_low:.2f} "
            f"(body={body_low:.2f}-{body_high:.2f}, range={body_range:.2f})"
        )
        return dc_replace(bar, high=new_high, low=new_low)

    return bar
