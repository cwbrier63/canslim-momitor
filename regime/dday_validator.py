"""
D-Day Validator CLI Tool
========================

Standalone tool to validate distribution day detection against MarketSurge counts.

Fetches recent daily bars from Massive.com (Polygon API) and runs distribution day
detection with configurable volume smoothing and price rounding parameters.

Usage:
    python -m regime.dday_validator                   # Use config defaults
    python -m regime.dday_validator --days 60          # Look back 60 days
    python -m regime.dday_validator --vol-min 0        # No volume smoothing
    python -m regime.dday_validator --vol-min 5        # 5% volume floor
    python -m regime.dday_validator --rounding 3       # Round to 3 decimals

Compares detected D-days against MarketSurge expected counts (if provided).
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import yaml

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from regime.historical_data import MassiveHistoricalClient, DailyBar

logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load config from user_config.yaml or config.yaml."""
    base_dir = Path(__file__).parent.parent
    for path in [base_dir / 'user_config.yaml', base_dir / 'config.yaml']:
        if path.exists():
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
    return {}


def detect_ddays(
    bars: List[DailyBar],
    decline_threshold: float = -0.2,
    min_volume_increase_pct: float = 2.0,
    decline_rounding_decimals: int = 2,
    lookback_days: int = 25,
    rally_expiration_pct: float = 5.0
) -> List[Dict]:
    """
    Detect distribution days from daily bars (standalone, no DB required).

    Returns list of dicts with D-day info including near-misses.
    """
    results = []

    if len(bars) < 2:
        return results

    for i in range(1, len(bars)):
        today = bars[i]
        yesterday = bars[i - 1]

        raw_pct = (today.close - yesterday.close) / yesterday.close * 100
        pct_change = round(raw_pct, decline_rounding_decimals)

        vol_inc_pct = ((today.volume - yesterday.volume) / yesterday.volume) * 100 if yesterday.volume > 0 else 0.0
        vol_qualifies = vol_inc_pct >= min_volume_increase_pct
        decline_qualifies = pct_change <= decline_threshold

        is_dday = decline_qualifies and vol_qualifies

        # Track near-misses too
        is_near_miss = False
        near_miss_reason = ""
        if decline_qualifies and not vol_qualifies:
            is_near_miss = True
            near_miss_reason = f"vol +{vol_inc_pct:.1f}% < min {min_volume_increase_pct}%"
        elif vol_qualifies and not decline_qualifies and pct_change <= 0:
            is_near_miss = True
            near_miss_reason = f"pct {pct_change:+.2f}% > threshold {decline_threshold}%"

        if is_dday or is_near_miss:
            results.append({
                'date': today.date,
                'close': today.close,
                'pct_change': pct_change,
                'raw_pct': raw_pct,
                'volume': today.volume,
                'prev_volume': yesterday.volume,
                'vol_inc_pct': vol_inc_pct,
                'is_dday': is_dday,
                'is_near_miss': is_near_miss,
                'near_miss_reason': near_miss_reason
            })

    return results


def check_expirations(
    ddays: List[Dict],
    bars: List[DailyBar],
    lookback_days: int = 25,
    rally_expiration_pct: float = 5.0,
    as_of_date: date = None
) -> List[Dict]:
    """
    Filter D-days to only active ones (not expired by time or rally).

    Returns list of active D-day dicts.
    """
    ref_date = as_of_date or date.today()
    current_close = bars[-1].close if bars else 0

    # Build set of trading dates for accurate day counting
    trading_dates = sorted(set(b.date for b in bars))

    active = []
    for d in ddays:
        if not d['is_dday']:
            continue

        # Time expiration: count trading days
        try:
            d_idx = trading_dates.index(d['date'])
            last_idx = len(trading_dates) - 1
            trading_days_elapsed = last_idx - d_idx
        except ValueError:
            # Date not in bars, estimate
            trading_days_elapsed = (ref_date - d['date']).days

        if trading_days_elapsed >= lookback_days:
            d['expired'] = True
            d['expiry_reason'] = f"TIME ({trading_days_elapsed} trading days)"
            continue

        # Rally expiration
        rally_pct = ((current_close - d['close']) / d['close']) * 100
        if rally_pct >= rally_expiration_pct:
            d['expired'] = True
            d['expiry_reason'] = f"RALLY ({rally_pct:.1f}%)"
            continue

        d['expired'] = False
        d['trading_days_ago'] = trading_days_elapsed
        active.append(d)

    return active


def print_report(
    symbol: str,
    all_ddays: List[Dict],
    active_ddays: List[Dict],
    near_misses: List[Dict],
    expected_count: Optional[int],
    params: Dict
):
    """Print formatted validation report."""
    print(f"\n{'='*70}")
    print(f"  D-Day Validation Report: {symbol}")
    print(f"{'='*70}")
    print(f"  Parameters:")
    print(f"    decline_threshold:      {params['decline_threshold']}%")
    print(f"    min_volume_increase:    {params['min_volume_increase_pct']}%")
    print(f"    decline_rounding:       {params['decline_rounding_decimals']} decimals")
    print(f"    lookback_days:          {params['lookback_days']}")
    print(f"    rally_expiration:       {params['rally_expiration_pct']}%")
    print()

    # Active D-days
    print(f"  Active D-Days: {len(active_ddays)}", end="")
    if expected_count is not None:
        match = "MATCH" if len(active_ddays) == expected_count else "MISMATCH"
        print(f"  (expected: {expected_count}) [{match}]")
    else:
        print()
    print(f"  {'-'*50}")

    if active_ddays:
        for d in sorted(active_ddays, key=lambda x: x['date'], reverse=True):
            days_ago = d.get('trading_days_ago', '?')
            print(
                f"    {d['date']}  {d['pct_change']:+.2f}%  "
                f"vol: {d['volume']:>12,} (+{d['vol_inc_pct']:.1f}%)  "
                f"[{days_ago}d ago]"
            )
    else:
        print("    (none)")

    # Near misses
    if near_misses:
        print(f"\n  Near Misses: {len(near_misses)}")
        print(f"  {'-'*50}")
        for d in sorted(near_misses, key=lambda x: x['date'], reverse=True):
            print(
                f"    {d['date']}  {d['pct_change']:+.2f}%  "
                f"vol: {d['volume']:>12,} (+{d['vol_inc_pct']:.1f}%)  "
                f"-- {d['near_miss_reason']}"
            )

    # Expired D-days
    expired = [d for d in all_ddays if d.get('expired')]
    if expired:
        print(f"\n  Expired D-Days: {len(expired)}")
        print(f"  {'-'*50}")
        for d in sorted(expired, key=lambda x: x['date'], reverse=True):
            print(
                f"    {d['date']}  {d['pct_change']:+.2f}%  "
                f"-- {d.get('expiry_reason', 'unknown')}"
            )

    print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validate distribution day detection against MarketSurge"
    )
    parser.add_argument(
        '--days', type=int, default=60,
        help='Calendar days of data to fetch (default: 60)'
    )
    parser.add_argument(
        '--vol-min', type=float, default=None,
        help='Min volume increase %% (overrides config; default from config or 2.0)'
    )
    parser.add_argument(
        '--rounding', type=int, default=None,
        help='Decline rounding decimals (overrides config; default from config or 2)'
    )
    parser.add_argument(
        '--threshold', type=float, default=None,
        help='Decline threshold %% (overrides config; default -0.2)'
    )
    parser.add_argument(
        '--lookback', type=int, default=None,
        help='Lookback window in trading days (default: 25)'
    )
    parser.add_argument(
        '--rally', type=float, default=None,
        help='Rally expiration %% (default: 5.0)'
    )
    parser.add_argument(
        '--expected-spy', type=int, default=None,
        help='Expected MarketSurge D-day count for SPY/S&P 500'
    )
    parser.add_argument(
        '--expected-qqq', type=int, default=None,
        help='Expected MarketSurge D-day count for QQQ/NASDAQ'
    )
    parser.add_argument(
        '--symbols', nargs='+', default=['SPY', 'QQQ'],
        help='Symbols to check (default: SPY QQQ)'
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Enable verbose/debug logging'
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    # Load config
    config = load_config()
    dd_config = config.get('distribution_days', {})

    # Resolve parameters (CLI overrides > config > defaults)
    params = {
        'decline_threshold': args.threshold or dd_config.get('decline_threshold', -0.2),
        'min_volume_increase_pct': args.vol_min if args.vol_min is not None else dd_config.get('min_volume_increase_pct', 2.0),
        'decline_rounding_decimals': args.rounding if args.rounding is not None else dd_config.get('decline_rounding_decimals', 2),
        'lookback_days': args.lookback or dd_config.get('lookback_days', 25),
        'rally_expiration_pct': args.rally or dd_config.get('rally_expiration_pct', 5.0),
    }

    expected_map = {
        'SPY': args.expected_spy,
        'QQQ': args.expected_qqq,
    }

    # Create API client
    try:
        client = MassiveHistoricalClient.from_config(config)
        client.connect()
    except Exception as e:
        print(f"ERROR: Could not connect to Massive.com API: {e}")
        sys.exit(1)

    # Process each symbol
    for symbol in args.symbols:
        print(f"\nFetching {args.days} days of data for {symbol}...")

        try:
            bars = client.get_daily_bars(symbol, lookback_days=args.days)
        except Exception as e:
            print(f"ERROR: Could not fetch data for {symbol}: {e}")
            continue

        if len(bars) < 2:
            print(f"WARNING: Insufficient data for {symbol} ({len(bars)} bars)")
            continue

        print(f"  Got {len(bars)} bars: {bars[0].date} to {bars[-1].date}")

        # Detect D-days
        all_ddays = detect_ddays(
            bars,
            decline_threshold=params['decline_threshold'],
            min_volume_increase_pct=params['min_volume_increase_pct'],
            decline_rounding_decimals=params['decline_rounding_decimals'],
            lookback_days=params['lookback_days'],
            rally_expiration_pct=params['rally_expiration_pct']
        )

        # Separate D-days and near-misses
        detected_ddays = [d for d in all_ddays if d['is_dday']]
        near_misses = [d for d in all_ddays if d['is_near_miss']]

        # Check expirations to find active ones
        active_ddays = check_expirations(
            detected_ddays, bars,
            lookback_days=params['lookback_days'],
            rally_expiration_pct=params['rally_expiration_pct']
        )

        # Print report
        expected = expected_map.get(symbol.upper())
        print_report(symbol, detected_ddays, active_ddays, near_misses, expected, params)


if __name__ == '__main__':
    main()
