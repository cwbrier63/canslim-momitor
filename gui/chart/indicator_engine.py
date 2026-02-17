"""
Indicator calculation engine wrapping pandas-ta-classic.
Takes provider Bar objects, returns JSON-serializable indicator data.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Any, Optional

import pandas as pd

logger = logging.getLogger('canslim.gui.chart.indicators')

# Guard pandas-ta import
PANDAS_TA_AVAILABLE = False
try:
    import pandas_ta_classic as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    try:
        import pandas_ta as ta
        PANDAS_TA_AVAILABLE = True
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IndicatorSeries:
    """A single drawable series from an indicator."""
    name: str           # display name, e.g. "RSI(14)"
    series_type: str    # "line", "histogram", "band_fill", "dots"
    color: str
    width: float = 1.5
    dash_style: str = "solid"  # "solid", "dashed", "dotted"
    data: List[Dict] = field(default_factory=list)  # [{timestamp, value}]
    # For band_fill: second data array for lower boundary
    data2: List[Dict] = field(default_factory=list)


@dataclass
class IndicatorResult:
    """Complete output of an indicator calculation."""
    indicator_id: str
    display_name: str
    panel_type: str         # "overlay" or "subchart"
    y_range: Optional[tuple] = None
    ref_lines: List[Dict] = field(default_factory=list)
    series: List[IndicatorSeries] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Indicator catalog
# ---------------------------------------------------------------------------

INDICATOR_CATALOG = {
    # --- Overlay indicators (drawn on price chart) ---
    'bbands': {
        'name': 'Bollinger Bands',
        'panel': 'overlay',
        'params': {'length': 20, 'std': 2.0},
        'category': 'Volatility',
    },
    'supertrend': {
        'name': 'Supertrend',
        'panel': 'overlay',
        'params': {'length': 10, 'multiplier': 3.0},
        'category': 'Trend',
    },
    'psar': {
        'name': 'Parabolic SAR',
        'panel': 'overlay',
        'params': {'af0': 0.02, 'af': 0.02, 'max_af': 0.2},
        'category': 'Trend',
    },
    'ichimoku': {
        'name': 'Ichimoku Cloud',
        'panel': 'overlay',
        'params': {'tenkan': 9, 'kijun': 26, 'senkou': 52},
        'category': 'Trend',
    },
    'vwap': {
        'name': 'VWAP',
        'panel': 'overlay',
        'params': {},
        'category': 'Volume',
    },
    # --- Sub-chart indicators (separate panel) ---
    'rsi': {
        'name': 'RSI',
        'panel': 'subchart',
        'params': {'length': 14},
        'y_range': (0, 100),
        'ref_lines': [
            {'value': 70, 'color': '#ef5350', 'style': 'dashed'},
            {'value': 30, 'color': '#26a69a', 'style': 'dashed'},
        ],
        'category': 'Momentum',
    },
    'macd': {
        'name': 'MACD',
        'panel': 'subchart',
        'params': {'fast': 12, 'slow': 26, 'signal': 9},
        'y_range': None,
        'ref_lines': [{'value': 0, 'color': '#555', 'style': 'solid'}],
        'category': 'Momentum',
    },
    'stoch': {
        'name': 'Stochastic',
        'panel': 'subchart',
        'params': {'k': 14, 'd': 3, 'smooth_k': 3},
        'y_range': (0, 100),
        'ref_lines': [
            {'value': 80, 'color': '#ef5350', 'style': 'dashed'},
            {'value': 20, 'color': '#26a69a', 'style': 'dashed'},
        ],
        'category': 'Momentum',
    },
    'adx': {
        'name': 'ADX',
        'panel': 'subchart',
        'params': {'length': 14},
        'y_range': (0, 100),
        'ref_lines': [{'value': 25, 'color': '#888', 'style': 'dashed'}],
        'category': 'Trend',
    },
    'atr': {
        'name': 'ATR',
        'panel': 'subchart',
        'params': {'length': 14},
        'y_range': None,
        'category': 'Volatility',
    },
    'obv': {
        'name': 'OBV',
        'panel': 'subchart',
        'params': {},
        'y_range': None,
        'category': 'Volume',
    },
    'mfi': {
        'name': 'MFI',
        'panel': 'subchart',
        'params': {'length': 14},
        'y_range': (0, 100),
        'ref_lines': [
            {'value': 80, 'color': '#ef5350', 'style': 'dashed'},
            {'value': 20, 'color': '#26a69a', 'style': 'dashed'},
        ],
        'category': 'Volume',
    },
    'cci': {
        'name': 'CCI',
        'panel': 'subchart',
        'params': {'length': 20},
        'y_range': None,
        'ref_lines': [
            {'value': 100, 'color': '#ef5350', 'style': 'dashed'},
            {'value': -100, 'color': '#26a69a', 'style': 'dashed'},
        ],
        'category': 'Momentum',
    },
    # --- Performance indicators (require benchmark data) ---
    'rs_line': {
        'name': 'RS Line',
        'panel': 'subchart',
        'params': {},
        'y_range': None,
        'ref_lines': [],
        'category': 'Performance',
    },
}


# ---------------------------------------------------------------------------
# DataFrame conversion
# ---------------------------------------------------------------------------

def bars_to_dataframe(bars) -> pd.DataFrame:
    """Convert list of Bar objects to a pandas DataFrame for pandas-ta."""
    rows = []
    for bar in bars:
        ts_ms = getattr(bar, '_timestamp_ms', None)
        if ts_ms is None:
            bar_dt = bar.bar_date
            if isinstance(bar_dt, date) and not isinstance(bar_dt, datetime):
                bar_dt = datetime.combine(bar_dt, datetime.min.time())
            ts_ms = int(bar_dt.timestamp() * 1000)
        rows.append({
            'timestamp': ts_ms,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': getattr(bar, 'volume', 0) or 0,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helper: convert pandas Series to point list
# ---------------------------------------------------------------------------

def _series_to_points(timestamps, series, decimals=2):
    """Convert a pandas Series to [{timestamp, value}] list, skipping NaN."""
    points = []
    for i, val in enumerate(series):
        if pd.notna(val) and i < len(timestamps):
            points.append({'timestamp': timestamps[i], 'value': round(float(val), decimals)})
    return points


# ---------------------------------------------------------------------------
# Calculator functions
# ---------------------------------------------------------------------------

def _calc_rsi(df, timestamps, params):
    result = ta.rsi(df['close'], length=params['length'])
    if result is None:
        return None
    return IndicatorResult(
        indicator_id='rsi',
        display_name=f"RSI ({params['length']})",
        panel_type='subchart',
        y_range=(0, 100),
        ref_lines=INDICATOR_CATALOG['rsi']['ref_lines'],
        series=[IndicatorSeries(
            name='RSI', series_type='line', color='#E040FB',
            data=_series_to_points(timestamps, result),
        )],
    )


def _calc_macd(df, timestamps, params):
    result = ta.macd(df['close'], fast=params['fast'], slow=params['slow'], signal=params['signal'])
    if result is None:
        return None
    macd_col = [c for c in result.columns if c.startswith('MACD_')][0]
    hist_col = [c for c in result.columns if c.startswith('MACDh_')][0]
    sig_col = [c for c in result.columns if c.startswith('MACDs_')][0]
    return IndicatorResult(
        indicator_id='macd',
        display_name=f"MACD ({params['fast']},{params['slow']},{params['signal']})",
        panel_type='subchart',
        y_range=None,
        ref_lines=INDICATOR_CATALOG['macd']['ref_lines'],
        series=[
            IndicatorSeries(
                name='MACD', series_type='line', color='#2196F3',
                data=_series_to_points(timestamps, result[macd_col]),
            ),
            IndicatorSeries(
                name='Signal', series_type='line', color='#FF9800',
                data=_series_to_points(timestamps, result[sig_col]),
            ),
            IndicatorSeries(
                name='Histogram', series_type='histogram', color='#26a69a',
                data=_series_to_points(timestamps, result[hist_col]),
            ),
        ],
    )


def _calc_stoch(df, timestamps, params):
    result = ta.stoch(df['high'], df['low'], df['close'],
                      k=params['k'], d=params['d'], smooth_k=params['smooth_k'])
    if result is None:
        return None
    k_col = [c for c in result.columns if c.startswith('STOCHk_')][0]
    d_col = [c for c in result.columns if c.startswith('STOCHd_')][0]
    return IndicatorResult(
        indicator_id='stoch',
        display_name=f"Stoch ({params['k']},{params['d']})",
        panel_type='subchart',
        y_range=(0, 100),
        ref_lines=INDICATOR_CATALOG['stoch']['ref_lines'],
        series=[
            IndicatorSeries(
                name='%K', series_type='line', color='#2196F3',
                data=_series_to_points(timestamps, result[k_col]),
            ),
            IndicatorSeries(
                name='%D', series_type='line', color='#FF9800',
                dash_style='dashed',
                data=_series_to_points(timestamps, result[d_col]),
            ),
        ],
    )


def _calc_adx(df, timestamps, params):
    result = ta.adx(df['high'], df['low'], df['close'], length=params['length'])
    if result is None:
        return None
    adx_col = [c for c in result.columns if c.startswith('ADX_')][0]
    dmp_col = [c for c in result.columns if c.startswith('DMP_')][0]
    dmn_col = [c for c in result.columns if c.startswith('DMN_')][0]
    return IndicatorResult(
        indicator_id='adx',
        display_name=f"ADX ({params['length']})",
        panel_type='subchart',
        y_range=(0, 100),
        ref_lines=INDICATOR_CATALOG['adx']['ref_lines'],
        series=[
            IndicatorSeries(
                name='ADX', series_type='line', color='#FFFFFF', width=2,
                data=_series_to_points(timestamps, result[adx_col]),
            ),
            IndicatorSeries(
                name='+DI', series_type='line', color='#26a69a',
                data=_series_to_points(timestamps, result[dmp_col]),
            ),
            IndicatorSeries(
                name='-DI', series_type='line', color='#ef5350',
                data=_series_to_points(timestamps, result[dmn_col]),
            ),
        ],
    )


def _calc_atr(df, timestamps, params):
    result = ta.atr(df['high'], df['low'], df['close'], length=params['length'])
    if result is None:
        return None
    return IndicatorResult(
        indicator_id='atr',
        display_name=f"ATR ({params['length']})",
        panel_type='subchart',
        y_range=None,
        series=[IndicatorSeries(
            name='ATR', series_type='line', color='#FF9800',
            data=_series_to_points(timestamps, result),
        )],
    )


def _calc_obv(df, timestamps, params):
    result = ta.obv(df['close'], df['volume'])
    if result is None:
        return None
    return IndicatorResult(
        indicator_id='obv',
        display_name='OBV',
        panel_type='subchart',
        y_range=None,
        series=[IndicatorSeries(
            name='OBV', series_type='line', color='#29B6F6',
            data=_series_to_points(timestamps, result, decimals=0),
        )],
    )


def _calc_mfi(df, timestamps, params):
    result = ta.mfi(df['high'], df['low'], df['close'], df['volume'],
                    length=params['length'])
    if result is None:
        return None
    return IndicatorResult(
        indicator_id='mfi',
        display_name=f"MFI ({params['length']})",
        panel_type='subchart',
        y_range=(0, 100),
        ref_lines=INDICATOR_CATALOG['mfi']['ref_lines'],
        series=[IndicatorSeries(
            name='MFI', series_type='line', color='#AB47BC',
            data=_series_to_points(timestamps, result),
        )],
    )


def _calc_cci(df, timestamps, params):
    result = ta.cci(df['high'], df['low'], df['close'], length=params['length'])
    if result is None:
        return None
    return IndicatorResult(
        indicator_id='cci',
        display_name=f"CCI ({params['length']})",
        panel_type='subchart',
        y_range=None,
        ref_lines=INDICATOR_CATALOG['cci']['ref_lines'],
        series=[IndicatorSeries(
            name='CCI', series_type='line', color='#26C6DA',
            data=_series_to_points(timestamps, result),
        )],
    )


def _calc_bbands(df, timestamps, params):
    result = ta.bbands(df['close'], length=params['length'], std=params['std'])
    if result is None:
        return None
    cols = result.columns.tolist()
    lower_col = [c for c in cols if c.startswith('BBL_')][0]
    mid_col = [c for c in cols if c.startswith('BBM_')][0]
    upper_col = [c for c in cols if c.startswith('BBU_')][0]

    upper_pts = _series_to_points(timestamps, result[upper_col])
    lower_pts = _series_to_points(timestamps, result[lower_col])

    return IndicatorResult(
        indicator_id='bbands',
        display_name=f"BB ({params['length']},{params['std']})",
        panel_type='overlay',
        series=[
            IndicatorSeries(
                name='BB Upper', series_type='line', color='#42A5F5',
                dash_style='dashed', width=1,
                data=upper_pts,
            ),
            IndicatorSeries(
                name='BB Mid', series_type='line', color='#42A5F5',
                dash_style='dotted', width=1,
                data=_series_to_points(timestamps, result[mid_col]),
            ),
            IndicatorSeries(
                name='BB Lower', series_type='line', color='#42A5F5',
                dash_style='dashed', width=1,
                data=lower_pts,
            ),
            IndicatorSeries(
                name='BB Fill', series_type='band_fill', color='rgba(66, 165, 245, 0.08)',
                data=upper_pts,
                data2=lower_pts,
            ),
        ],
    )


def _calc_supertrend(df, timestamps, params):
    result = ta.supertrend(df['high'], df['low'], df['close'],
                           length=params['length'], multiplier=params['multiplier'])
    if result is None:
        return None
    cols = result.columns.tolist()
    trend_col = [c for c in cols if c.startswith('SUPERT_') and 'd' not in c.split('_')[-1]][0]
    dir_col = [c for c in cols if c.startswith('SUPERTd_')][0]

    # Split into bullish (green) and bearish (red) segments
    bull_pts = []
    bear_pts = []
    for i in range(len(result)):
        if pd.isna(result[trend_col].iloc[i]) or i >= len(timestamps):
            continue
        pt = {'timestamp': timestamps[i], 'value': round(float(result[trend_col].iloc[i]), 2)}
        if result[dir_col].iloc[i] > 0:
            bull_pts.append(pt)
            bear_pts.append(None)  # gap marker
        else:
            bear_pts.append(pt)
            bull_pts.append(None)

    # Filter None gaps for series data, but keep segment structure
    def _segments(pts):
        """Convert point list with None gaps into clean points."""
        return [p for p in pts if p is not None]

    return IndicatorResult(
        indicator_id='supertrend',
        display_name=f"ST ({params['length']},{params['multiplier']})",
        panel_type='overlay',
        series=[
            IndicatorSeries(
                name='ST Bull', series_type='line', color='#26a69a', width=2,
                data=_segments(bull_pts),
            ),
            IndicatorSeries(
                name='ST Bear', series_type='line', color='#ef5350', width=2,
                data=_segments(bear_pts),
            ),
        ],
    )


def _calc_psar(df, timestamps, params):
    result = ta.psar(df['high'], df['low'], df['close'],
                     af0=params['af0'], af=params['af'], max_af=params['max_af'])
    if result is None:
        return None
    cols = result.columns.tolist()
    long_col = [c for c in cols if c.startswith('PSARl_')][0]
    short_col = [c for c in cols if c.startswith('PSARs_')][0]
    return IndicatorResult(
        indicator_id='psar',
        display_name='PSAR',
        panel_type='overlay',
        series=[
            IndicatorSeries(
                name='PSAR Long', series_type='dots', color='#26a69a',
                data=_series_to_points(timestamps, result[long_col]),
            ),
            IndicatorSeries(
                name='PSAR Short', series_type='dots', color='#ef5350',
                data=_series_to_points(timestamps, result[short_col]),
            ),
        ],
    )


def _calc_ichimoku(df, timestamps, params):
    ichimoku_result, span_result = ta.ichimoku(
        df['high'], df['low'], df['close'],
        tenkan=params['tenkan'], kijun=params['kijun'], senkou=params['senkou'],
    )
    if ichimoku_result is None:
        return None
    cols = ichimoku_result.columns.tolist()
    tenkan_col = [c for c in cols if c.startswith('ITS_')][0]
    kijun_col = [c for c in cols if c.startswith('IKS_')][0]
    span_a_col = [c for c in cols if c.startswith('ISA_')][0]
    span_b_col = [c for c in cols if c.startswith('ISB_')][0]
    chikou_col = [c for c in cols if c.startswith('ICS_')][0]

    span_a_pts = _series_to_points(timestamps, ichimoku_result[span_a_col])
    span_b_pts = _series_to_points(timestamps, ichimoku_result[span_b_col])

    return IndicatorResult(
        indicator_id='ichimoku',
        display_name='Ichimoku',
        panel_type='overlay',
        series=[
            IndicatorSeries(
                name='Tenkan', series_type='line', color='#2196F3', width=1,
                data=_series_to_points(timestamps, ichimoku_result[tenkan_col]),
            ),
            IndicatorSeries(
                name='Kijun', series_type='line', color='#ef5350', width=1,
                data=_series_to_points(timestamps, ichimoku_result[kijun_col]),
            ),
            IndicatorSeries(
                name='Span A', series_type='line', color='#26a69a',
                dash_style='dotted', width=1,
                data=span_a_pts,
            ),
            IndicatorSeries(
                name='Span B', series_type='line', color='#ef5350',
                dash_style='dotted', width=1,
                data=span_b_pts,
            ),
            IndicatorSeries(
                name='Cloud', series_type='band_fill', color='rgba(38, 166, 154, 0.06)',
                data=span_a_pts,
                data2=span_b_pts,
            ),
            IndicatorSeries(
                name='Chikou', series_type='line', color='#AB47BC',
                dash_style='dashed', width=1,
                data=_series_to_points(timestamps, ichimoku_result[chikou_col]),
            ),
        ],
    )


def _calc_rs_line(df, timestamps, params):
    """Relative Strength line: stock close / SPY close, normalized to 100."""
    if 'spy_close' not in df.columns:
        logger.warning("RS Line requires spy_close column in DataFrame")
        return None
    mask = df['close'].notna() & df['spy_close'].notna() & (df['spy_close'] > 0)
    if mask.sum() == 0:
        return None
    raw_rs = df['close'] / df['spy_close']
    # Normalize so the first valid value = 100
    first_valid = raw_rs[mask].iloc[0]
    rs_norm = (raw_rs / first_valid) * 100
    return IndicatorResult(
        indicator_id='rs_line',
        display_name='RS Line vs SPY',
        panel_type='subchart',
        y_range=None,
        ref_lines=[{'value': 100, 'color': '#555', 'style': 'dashed'}],
        series=[IndicatorSeries(
            name='RS Line', series_type='line', color='#4a90d9', width=2,
            data=_series_to_points(timestamps, rs_norm),
        )],
    )


def _calc_vwap(df, timestamps, params):
    # VWAP needs a DatetimeIndex; build one from timestamps
    df_copy = df.copy()
    df_copy.index = pd.to_datetime(df_copy['timestamp'], unit='ms')
    try:
        result = ta.vwap(df_copy['high'], df_copy['low'], df_copy['close'], df_copy['volume'])
    except Exception:
        return None
    if result is None:
        return None
    return IndicatorResult(
        indicator_id='vwap',
        display_name='VWAP',
        panel_type='overlay',
        series=[IndicatorSeries(
            name='VWAP', series_type='line', color='#FFD54F', width=1.5,
            data=_series_to_points(timestamps, result),
        )],
    )


# ---------------------------------------------------------------------------
# Calculator dispatch
# ---------------------------------------------------------------------------

_CALCULATORS = {
    'rsi': _calc_rsi,
    'macd': _calc_macd,
    'stoch': _calc_stoch,
    'adx': _calc_adx,
    'atr': _calc_atr,
    'obv': _calc_obv,
    'mfi': _calc_mfi,
    'cci': _calc_cci,
    'bbands': _calc_bbands,
    'supertrend': _calc_supertrend,
    'psar': _calc_psar,
    'ichimoku': _calc_ichimoku,
    'vwap': _calc_vwap,
    'rs_line': _calc_rs_line,
}


def calculate_indicator(indicator_id: str, df: pd.DataFrame,
                        params: Dict = None) -> Optional[IndicatorResult]:
    """Calculate a single indicator. Returns IndicatorResult or None."""
    catalog = INDICATOR_CATALOG.get(indicator_id)
    if not PANDAS_TA_AVAILABLE and catalog and catalog.get('category') != 'Performance':
        return None
    if not catalog:
        logger.warning(f"Unknown indicator: {indicator_id}")
        return None

    merged_params = {**catalog.get('params', {}), **(params or {})}
    timestamps = df['timestamp'].tolist()

    calc_fn = _CALCULATORS.get(indicator_id)
    if not calc_fn:
        logger.warning(f"No calculator for: {indicator_id}")
        return None

    try:
        return calc_fn(df, timestamps, merged_params)
    except Exception:
        logger.warning(f"Indicator calculation failed: {indicator_id}", exc_info=True)
        return None
