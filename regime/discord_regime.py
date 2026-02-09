"""
Discord Notifier Extension for Market Regime Alerts

Extends your existing discord_notifier.py with morning regime alert formatting.
Includes trend context showing how the regime is evolving.

Usage:
    from discord_regime import DiscordRegimeNotifier
    
    notifier = DiscordRegimeNotifier(webhook_url)
    notifier.send_regime_alert(regime_score)
"""

import logging
import requests
from datetime import datetime, date, timedelta
from typing import Optional, List

from .market_regime import (
    RegimeScore, 
    calculate_entry_risk_score, 
    get_entry_risk_emoji,
    get_entry_risk_description
)
from .models_regime import (
    RegimeType, TrendType, DDayTrend,
    IBDMarketStatus, EntryRiskLevel,
    IBDExposureCurrent, PhaseChangeType, MarketPhaseHistory
)

logger = logging.getLogger(__name__)


class DiscordRegimeNotifier:
    """
    Discord webhook notifier for market regime alerts.
    
    Sends formatted morning alerts with:
    - Distribution day counts and trend
    - Overnight futures data
    - Composite regime score with visual bar
    - Regime-specific trading guidance
    - Trend vs prior day
    """
    
    # Emoji mappings
    REGIME_EMOJI = {
        RegimeType.BULLISH: '🟢',
        RegimeType.NEUTRAL: '🟡',
        RegimeType.BEARISH: '🔴'
    }
    
    TREND_EMOJI = {
        DDayTrend.IMPROVING: '🟢',
        DDayTrend.WORSENING: '🔴',
        DDayTrend.HEALTHY: '🟢',           # Low count, stable = bullish
        DDayTrend.STABLE: '🟡',            # Moderate count, stable = neutral
        DDayTrend.ELEVATED_STABLE: '🟠'    # High count but stable = caution
    }
    
    FUTURES_EMOJI = {
        TrendType.BULL: '🟢',
        TrendType.NEUTRAL: '🟡',
        TrendType.BEAR: '🔴'
    }
    
    ENTRY_RISK_EMOJI = {
        EntryRiskLevel.LOW: '🟢',
        EntryRiskLevel.MODERATE: '🟡',
        EntryRiskLevel.ELEVATED: '🟠',
        EntryRiskLevel.HIGH: '🔴'
    }
    
    IBD_STATUS_EMOJI = {
        IBDMarketStatus.CONFIRMED_UPTREND: '🟢',
        IBDMarketStatus.UPTREND_UNDER_PRESSURE: '🟠',
        IBDMarketStatus.RALLY_ATTEMPT: '🟡',
        IBDMarketStatus.CORRECTION: '🔴',
    }

    # Market phase emojis (for phase change alerts)
    PHASE_EMOJI = {
        'CONFIRMED_UPTREND': '🟢',
        'UPTREND_PRESSURE': '🟠',
        'RALLY_ATTEMPT': '🟡',
        'CORRECTION': '🔴',
        'MARKET_IN_CORRECTION': '🔴',
    }

    # Phase change type emojis
    PHASE_CHANGE_EMOJI = {
        PhaseChangeType.UPGRADE: '📈',
        PhaseChangeType.DOWNGRADE: '📉',
        PhaseChangeType.LATERAL: '➡️',
        PhaseChangeType.NONE: '•',
    }

    REGIME_TREND_EMOJI = {
        'improving': '📈',
        'worsening': '📉',
        'stable': '➡️'
    }
    
    def __init__(self, webhook_url: str, mention_role: str = None):
        """
        Initialize notifier.
        
        Args:
            webhook_url: Discord webhook URL
            mention_role: Optional role to mention (e.g., "@traders")
        """
        self.webhook_url = webhook_url
        self.mention_role = mention_role
    
    @classmethod
    def from_config(cls, config: dict) -> 'DiscordRegimeNotifier':
        """Create notifier from config dict."""
        discord_config = config.get('discord', {})
        regime_config = discord_config.get('regime_alert', {})
        
        # Get webhook URL - try multiple locations for compatibility
        # New convention: discord.webhooks.market
        # Legacy: discord.regime_webhook_url or discord.webhook_url
        webhooks = discord_config.get('webhooks', {})
        webhook_url = (
            webhooks.get('market') or           # New convention
            webhooks.get('regime_webhook_url') or  # Legacy nested
            discord_config.get('regime_webhook_url') or  # Legacy flat
            discord_config.get('webhook_url')   # Fallback default
        )
        
        return cls(
            webhook_url=webhook_url,
            mention_role=regime_config.get('mention_role')
        )
    
    def _build_score_bar(self, score: float, min_score: float = -1.5, max_score: float = 1.5) -> str:
        """Create visual progress bar for score."""
        # Normalize to 0-1
        normalized = (score - min_score) / (max_score - min_score)
        normalized = max(0, min(1, normalized))
        
        filled = int(normalized * 20)
        # Use simple characters that render well in Discord
        bar = '▓' * filled + '░' * (20 - filled)
        return f"`{bar}`"
    
    def _get_guidance(self, regime: RegimeType) -> str:
        """Get trading guidance for regime."""
        guidance = {
            RegimeType.BULLISH: (
                "→ Full position sizes permitted\n"
                "→ Favor long setups on breakouts\n"
                "→ Market supports growth stocks"
            ),
            RegimeType.NEUTRAL: (
                "→ Reduced position sizes (50-75%)\n"
                "→ Selective entries - A+ setups only\n"
                "→ Tighten stops on existing positions"
            ),
            RegimeType.BEARISH: (
                "→ Defensive posture - raise cash\n"
                "→ Avoid new long positions\n"
                "→ Wait for follow-through day signal"
            )
        }
        return guidance.get(regime, "")
    
    def _build_trend_context(self, score: RegimeScore) -> str:
        """Build the trend context section showing regime evolution."""
        if not score.prior_score:
            return ""
        
        trend_emoji = self.REGIME_TREND_EMOJI.get(score.regime_trend, '➡️')
        score_change = score.composite_score - score.prior_score
        
        # Regime change detection
        regime_change = ""
        if score.prior_regime and score.prior_regime != score.regime:
            prior_emoji = self.REGIME_EMOJI.get(score.prior_regime, '')
            curr_emoji = self.REGIME_EMOJI.get(score.regime, '')
            regime_change = f"\n⚠️ **REGIME CHANGE**: {prior_emoji} {score.prior_regime.value} → {curr_emoji} {score.regime.value}"
        
        return f"""
**TREND CONTEXT** {trend_emoji}
```
Prior Score: {score.prior_score:+.2f} → Current: {score.composite_score:+.2f} ({score_change:+.2f})
Direction:   {score.regime_trend.upper()}
```{regime_change}
"""
    
    def format_regime_alert(
        self,
        score: RegimeScore,
        verbose: bool = True,
        ibd_status: IBDMarketStatus = None,
        ibd_exposure_min: int = None,
        ibd_exposure_max: int = None,
        ibd_updated_at: datetime = None,
        fear_greed_data=None,
        vix_close=None,
        vix_previous_close=None,
    ) -> str:
        """
        Format the regime alert message.

        Args:
            score: RegimeScore to format
            verbose: If True, full format. If False, condensed one-liner.
            ibd_status: Manual IBD market status from MarketSurge
            ibd_exposure_min: Manual IBD exposure minimum %
            ibd_exposure_max: Manual IBD exposure maximum %
            ibd_updated_at: When IBD exposure was last updated
            fear_greed_data: Optional FearGreedData for sentiment display
            vix_close: Current VIX level
            vix_previous_close: Previous day's VIX close

        Returns:
            Formatted message string
        """
        if not verbose:
            return self._format_condensed(score)

        return self._format_full(
            score,
            ibd_status=ibd_status,
            ibd_exposure_min=ibd_exposure_min,
            ibd_exposure_max=ibd_exposure_max,
            ibd_updated_at=ibd_updated_at,
            fear_greed_data=fear_greed_data,
            vix_close=vix_close,
            vix_previous_close=vix_previous_close,
        )
    
    def _format_condensed(self, score: RegimeScore) -> str:
        """One-line condensed format for quick glance."""
        regime_emoji = self.REGIME_EMOJI.get(score.regime, '')
        dist = score.distribution_data
        overnight = score.overnight_data
        
        # Add market phase indicator
        phase_indicator = ""
        if score.ftd_data:
            if score.ftd_data.ftd_today:
                phase_indicator = "| 🎉 FTD TODAY "
            elif score.ftd_data.in_rally_attempt:
                phase_indicator = f"| Rally Day {score.ftd_data.rally_day} "
            elif score.market_phase == "CONFIRMED_UPTREND":
                phase_indicator = "| ✓ Uptrend "
        
        return (
            f"🌅 REGIME: {regime_emoji} **{score.regime.value}** ({score.composite_score:+.2f}) {phase_indicator}| "
            f"SPY: {dist.spy_count} D-days | QQQ: {dist.qqq_count} D-days | "
            f"ES {overnight.es_change_pct:+.2f}% NQ {overnight.nq_change_pct:+.2f}% YM {overnight.ym_change_pct:+.2f}%"
        )
    
    def _format_full(
        self,
        score: RegimeScore,
        ibd_status: IBDMarketStatus = None,
        ibd_exposure_min: int = None,
        ibd_exposure_max: int = None,
        ibd_updated_at: datetime = None,
        fear_greed_data=None,
        vix_close=None,
        vix_previous_close=None,
    ) -> str:
        """
        Full detailed format with separated IBD exposure and entry risk.

        Args:
            score: RegimeScore with calculated entry risk
            ibd_status: Manual IBD market status from MarketSurge
            ibd_exposure_min: Manual IBD exposure minimum %
            ibd_exposure_max: Manual IBD exposure maximum %
            ibd_updated_at: When IBD exposure was last updated
            fear_greed_data: Optional FearGreedData for sentiment section
        """
        dist = score.distribution_data
        overnight = score.overnight_data
        ftd = score.ftd_data
        
        # Get emojis
        trend_emoji = self.TREND_EMOJI.get(dist.trend, '')
        es_emoji = self.FUTURES_EMOJI.get(overnight.es_trend, '')
        nq_emoji = self.FUTURES_EMOJI.get(overnight.nq_trend, '')
        ym_emoji = self.FUTURES_EMOJI.get(overnight.ym_trend, '')
        
        # Entry risk
        entry_risk_emoji = self.ENTRY_RISK_EMOJI.get(score.entry_risk_level, '⚪')
        entry_risk_desc = get_entry_risk_description(score.entry_risk_level)
        
        # Build D-day histogram
        histogram = self._build_dday_histogram(
            spy_dates=dist.spy_dates or [],
            qqq_dates=dist.qqq_dates or [],
            spy_count=dist.spy_count,
            qqq_count=dist.qqq_count,
            reference_date=score.timestamp.date() if score.timestamp else None
        )
        
        # Optional mention
        mention = f"{self.mention_role}\n" if self.mention_role else ""
        
        # Format date
        date_str = score.timestamp.strftime('%A, %B %d, %Y • %I:%M %p ET')
        
        # IBD Market Status section (STRATEGIC - manual from MarketSurge)
        ibd_section = self._build_ibd_status_section(
            ibd_status, ibd_exposure_min, ibd_exposure_max, ibd_updated_at
        )
        
        # Entry Risk section (TACTICAL - calculated daily)
        entry_risk_section = self._build_entry_risk_section(score)
        
        # Combined guidance
        guidance_section = self._build_combined_guidance(
            ibd_status or IBDMarketStatus.CONFIRMED_UPTREND,
            ibd_exposure_min or 80,
            ibd_exposure_max or 100,
            score.entry_risk_level,
            dist
        )
        
        # FTD/Market Phase section
        ftd_section = self._build_ftd_section(ftd, score.market_phase) if ftd else ""

        # Sentiment section (CNN Fear & Greed + VIX)
        fg_data = fear_greed_data or getattr(score, 'fear_greed_data', None)
        _vix = vix_close if vix_close is not None else getattr(score, 'vix_close', None)
        _vix_prev = vix_previous_close if vix_previous_close is not None else getattr(score, 'vix_previous_close', None)
        sentiment_section = self._build_sentiment_section(fg_data, vix_close=_vix, vix_previous_close=_vix_prev)

        message = f"""{mention}__**🌅 MORNING MARKET REGIME ALERT**__
*{date_str}*

━━━━━━━━━━━━━━━━━━━━
{ibd_section}
**📊 D-DAY COUNT** (25-Day Rolling)
```
│ Index │ Cnt │ 5d Δ │ Trend      │
│ SPY   │  {dist.spy_count}  │  {dist.spy_5day_delta:+2d}  │ {dist.trend.value:<10} │
│ QQQ   │  {dist.qqq_count}  │  {dist.qqq_5day_delta:+2d}  │ {dist.trend.value:<10} │
```
{trend_emoji} Trend: **{dist.trend.value}**
{histogram}
**🌙 OVERNIGHT FUTURES**
```
│ ES {overnight.es_change_pct:+.2f}% │ NQ {overnight.nq_change_pct:+.2f}% │ YM {overnight.ym_change_pct:+.2f}% │
```
{es_emoji} ES  {nq_emoji} NQ  {ym_emoji} YM

━━━━━━━━━━━━━━━━━━━━
{ftd_section}
━━━━━━━━━━━━━━━━━━━━
{entry_risk_section}{sentiment_section}
━━━━━━━━━━━━━━━━━━━━
{guidance_section}
"""
        
        return message
    
    def _build_ibd_status_section(
        self,
        status: IBDMarketStatus,
        exposure_min: int,
        exposure_max: int,
        updated_at: datetime
    ) -> str:
        """Build the IBD Market Status section (strategic layer)."""
        if not status:
            status = IBDMarketStatus.CONFIRMED_UPTREND
        if not exposure_min:
            exposure_min, exposure_max = IBDExposureCurrent.get_default_exposure(status)
        
        emoji = self.IBD_STATUS_EMOJI.get(status, '⚪')
        status_display = status.value.replace('_', ' ').title()
        
        # Format updated date
        if updated_at:
            days_ago = (datetime.now() - updated_at).days
            if days_ago <= 0:  # Today or future (timezone edge case)
                updated_str = "Updated today"
            elif days_ago == 1:
                updated_str = "Updated yesterday"
            else:
                updated_str = f"Updated {updated_at.strftime('%b %d')} ({days_ago} days ago)"
        else:
            updated_str = "Not set - using default"
        
        # Status-specific message
        if status == IBDMarketStatus.CONFIRMED_UPTREND:
            status_message = "*Overall environment supports new positions*"
        elif status == IBDMarketStatus.UPTREND_UNDER_PRESSURE:
            status_message = "*Proceed with caution, be selective*"
        elif status == IBDMarketStatus.RALLY_ATTEMPT:
            status_message = "*Testing new uptrend - small positions only*"
        else:  # CORRECTION
            status_message = "*Defensive posture - preserve capital*"
        
        # Compact format
        return f"""
**📊 IBD STATUS:** {emoji} {status_display} | {exposure_min}-{exposure_max}%
*{updated_str}* - {status_message}
"""
    
    def _build_entry_risk_section(self, score: RegimeScore) -> str:
        """Build the Entry Risk section (tactical layer) - compact format."""
        emoji = self.ENTRY_RISK_EMOJI.get(score.entry_risk_level, '⚪')
        level_name = score.entry_risk_level.value
        desc = get_entry_risk_description(score.entry_risk_level)

        return f"""
**⚠️ ENTRY RISK:** {emoji} **{level_name}** ({score.entry_risk_score:+.2f})
*{desc}*
"""
    
    def _build_sentiment_section(self, fear_greed_data, vix_close=None, vix_previous_close=None) -> str:
        """Build the market sentiment section (CNN Fear & Greed + VIX)."""
        lines = []

        # Fear & Greed line
        if fear_greed_data:
            score = fear_greed_data.score
            rating = fear_greed_data.rating

            emoji_map = {
                'Extreme Fear': '\U0001f631',
                'Fear': '\U0001f628',
                'Neutral': '\U0001f610',
                'Greed': '\U0001f60f',
                'Extreme Greed': '\U0001f911',
            }
            emoji = emoji_map.get(rating, '\U0001f610')

            trend_str = ""
            if fear_greed_data.previous_close and fear_greed_data.previous_close > 0:
                prev = fear_greed_data.previous_close
                if score != prev:
                    trend_str = f" ({score - prev:+.0f} from {prev:.0f} yesterday)"
                else:
                    trend_str = f" (unchanged from {prev:.0f})"

            lines.append(f"**{emoji} SENTIMENT** CNN Fear & Greed: **{score:.0f}** — {rating}{trend_str}")

        # VIX line
        if vix_close is not None:
            from .vix_client import classify_vix, get_vix_emoji
            vix_emoji = get_vix_emoji(vix_close)
            vix_rating = classify_vix(vix_close)

            vix_trend = ""
            if vix_previous_close and vix_previous_close > 0:
                delta = vix_close - vix_previous_close
                if delta != 0:
                    vix_trend = f" ({delta:+.2f} from {vix_previous_close:.2f} yesterday)"
                else:
                    vix_trend = f" (unchanged from {vix_previous_close:.2f})"

            lines.append(f"**{vix_emoji} VIX:** {vix_close:.2f} — {vix_rating}{vix_trend}")

        if not lines:
            return ""

        return "\n" + "\n".join(lines) + "\n"

    def _build_entry_risk_bar(self, score: float) -> str:
        """Build visual bar for entry risk score."""
        # Score range: -1.5 to +1.5
        # Map to 0-30 characters
        normalized = (score + 1.5) / 3.0  # 0 to 1
        position = int(normalized * 28)  # 0 to 28
        position = max(0, min(28, position))
        
        bar = ['░'] * 30
        bar[position] = '▓'
        bar[position+1] = '▓' if position < 29 else '▓'
        
        bar_str = ''.join(bar)
        
        return f"""```
{bar_str}
HIGH       ELEVATED    MOD      LOW
```"""
    
    def _build_combined_guidance(
        self,
        ibd_status: IBDMarketStatus,
        exposure_min: int,
        exposure_max: int,
        entry_risk: EntryRiskLevel,
        dist_data
    ) -> str:
        """
        Build combined guidance based on IBD status + today's entry risk.
        
        This is the key logic that provides actionable advice by combining
        the strategic layer (IBD) with the tactical layer (today's risk).
        """
        breakout_guidance = []
        position_guidance = []
        
        # Strategic posture from IBD
        if ibd_status == IBDMarketStatus.CONFIRMED_UPTREND:
            base_posture = "RISK_ON"
        elif ibd_status == IBDMarketStatus.UPTREND_UNDER_PRESSURE:
            base_posture = "CAUTIOUS"
        elif ibd_status == IBDMarketStatus.RALLY_ATTEMPT:
            base_posture = "DEFENSIVE"
        else:  # CORRECTION
            base_posture = "PRESERVATION"
        
        # Combine with today's entry risk
        if base_posture == "RISK_ON":
            if entry_risk == EntryRiskLevel.LOW:
                breakout_guidance = [
                    "✅ Green light for breakout entries",
                    "→ Act on A and B grade setups",
                    "→ Standard position sizing appropriate",
                    "→ Honor 7-8% stop loss rules"
                ]
                position_guidance = [
                    "→ No action needed on existing positions",
                    "→ Continue to hold winners"
                ]
            elif entry_risk == EntryRiskLevel.MODERATE:
                breakout_guidance = [
                    "✅ Act on highest-quality setups",
                    "→ Focus on A-grade setups only",
                    "→ Standard position sizing",
                    "→ Confirm volume on breakout"
                ]
                position_guidance = [
                    "→ No action needed",
                    "→ Monitor positions normally"
                ]
            elif entry_risk == EntryRiskLevel.ELEVATED:
                breakout_guidance = [
                    "⚠️ Consider waiting for better entry day",
                    f"→ IBD supports positions ({exposure_min}-{exposure_max}%)",
                    "→ But short-term risk is elevated",
                    "→ If acting: reduce position size 25-50%",
                    "→ Wait for futures to stabilize"
                ]
                position_guidance = [
                    "→ No action needed based on today's data",
                    "→ Continue to honor your stop levels"
                ]
            else:  # HIGH
                breakout_guidance = [
                    "⚠️ Hold off on new entries today",
                    f"→ IBD still supports positions ({exposure_min}-{exposure_max}%)",
                    "→ But today is unfavorable for new buys",
                    "→ Add to watchlist, wait for better day"
                ]
                position_guidance = [
                    "→ No panic selling needed",
                    "→ Honor existing stops only"
                ]
        
        elif base_posture == "CAUTIOUS":
            if entry_risk in [EntryRiskLevel.LOW, EntryRiskLevel.MODERATE]:
                breakout_guidance = [
                    "⚠️ Very selective entries only",
                    "→ A-grade setups only",
                    "→ Reduce position size by 50%",
                    "→ Use tighter stops (5-6%)"
                ]
            else:
                breakout_guidance = [
                    "⛔ Avoid new entries",
                    "→ Market under pressure + elevated daily risk",
                    "→ Wait for conditions to improve"
                ]
            position_guidance = [
                "→ Review positions for weakness",
                "→ Tighten stops on laggards"
            ]
        
        elif base_posture == "DEFENSIVE":
            breakout_guidance = [
                "⚠️ Test positions only",
                "→ Half size or less after FTD",
                "→ Be ready to cut quickly if rally fails"
            ]
            position_guidance = [
                "→ Maintain tight stops",
                "→ Don't add to positions yet"
            ]
        
        else:  # PRESERVATION
            breakout_guidance = [
                "⛔ No new long positions",
                "→ Market in correction",
                "→ Build watchlist for next uptrend",
                "→ Wait for follow-through day"
            ]
            position_guidance = [
                "→ Honor stops strictly",
                "→ Consider taking profits on strength",
                "→ Raise cash on weakness"
            ]
        
        # Compact guidance - combine and truncate
        max_d = max(dist_data.spy_count, dist_data.qqq_count)
        clustering_warning = f" ⚠️ High D-days ({max_d})" if max_d >= 6 else ""

        # Take only top 2 guidance items to save space
        breakout_lines = '\n'.join(breakout_guidance[:3])
        position_lines = '\n'.join(position_guidance[:2])

        return f"""
**📋 GUIDANCE**{clustering_warning}
{breakout_lines}
*Positions:* {position_guidance[0] if position_guidance else 'Monitor normally'}
"""
    
    def _build_dday_histogram(
        self,
        spy_dates: list,
        qqq_dates: list,
        spy_count: int = None,
        qqq_count: int = None,
        lookback_days: int = 35,  # 35 calendar days to cover 25 trading days
        reference_date: date = None
    ) -> str:
        """
        Build ASCII histogram showing D-day distribution over rolling window.

        Shows clustering of distribution days - recent clustering is more
        concerning than spread-out D-days.

        Uses 35 calendar days to ensure all 25 trading day D-days are shown
        (accounting for weekends and holidays).
        """
        # Use provided reference date or fall back to today
        # This ensures the histogram aligns with the data's actual date
        ref_date = reference_date or date.today()
        
        # Helper to convert various date types to date object
        def to_date(d):
            if d is None:
                return None
            if isinstance(d, datetime):
                return d.date()
            if isinstance(d, date):
                return d
            if isinstance(d, str):
                # Try common formats
                try:
                    return date.fromisoformat(d)
                except:
                    try:
                        return datetime.strptime(d, '%Y-%m-%d').date()
                    except:
                        return None
            return None
        
        # Build day-by-day arrays (True if D-day on that day)
        spy_ddays = [False] * lookback_days
        qqq_ddays = [False] * lookback_days
        
        for d in (spy_dates or []):
            d_date = to_date(d)
            if d_date:
                days_ago = (ref_date - d_date).days
                if 0 <= days_ago < lookback_days:
                    spy_ddays[lookback_days - 1 - days_ago] = True  # Index 0 = oldest
        
        for d in (qqq_dates or []):
            d_date = to_date(d)
            if d_date:
                days_ago = (ref_date - d_date).days
                if 0 <= days_ago < lookback_days:
                    qqq_ddays[lookback_days - 1 - days_ago] = True
        
        # Build histogram strings
        # Use ■ for D-day, · for no D-day (more visible in Discord)
        spy_bar = ''.join(['■' if d else '·' for d in spy_ddays])
        qqq_bar = ''.join(['■' if d else '·' for d in qqq_ddays])
        
        # Use official counts if provided (to match table with overrides)
        # Otherwise fall back to counting actual dates found
        spy_display_count = spy_count if spy_count is not None else sum(spy_ddays)
        qqq_display_count = qqq_count if qqq_count is not None else sum(qqq_ddays)
        
        # Count recent vs older D-days (last 5 days vs prior 20)
        spy_recent = sum(spy_ddays[-5:])
        spy_older = sum(spy_ddays[:-5])
        qqq_recent = sum(qqq_ddays[-5:])
        qqq_older = sum(qqq_ddays[:-5])
        
        total_recent = spy_recent + qqq_recent
        total_older = spy_older + qqq_older
        
        # Clustering warning
        clustering_note = ""
        if total_recent >= 3:
            clustering_note = "⚠️ Heavy recent clustering"
        elif total_recent >= 2:
            clustering_note = "📍 Some recent clustering"
        elif total_recent == 0 and (spy_older + qqq_older) > 0:
            clustering_note = "✓ D-days aging out"
        
        # Compact histogram - just show the bars with minimal chrome
        histogram = f"""
📅 **D-Day Timeline** (■=D-day)
```
SPY[{spy_display_count}]: {spy_bar}
QQQ[{qqq_display_count}]: {qqq_bar}
        ← 5wk ago          Today →
```
{clustering_note}
"""
        return histogram
    
    def _build_ftd_section(self, ftd_data, market_phase: str) -> str:
        """Build the FTD/Market Phase section of the alert."""
        if not ftd_data:
            return ""

        # Phase emoji
        phase_emoji = {
            'CONFIRMED_UPTREND': '🟢',
            'RALLY_ATTEMPT': '🟡',
            'UPTREND_PRESSURE': '🟠',
            'CORRECTION': '🔴',
            'MARKET_IN_CORRECTION': '🔴',
            'UNKNOWN': '⚪'
        }

        emoji = phase_emoji.get(market_phase, '⚪')

        # Format phase name for display
        phase_display = market_phase.replace('_', ' ').title()

        # Build status line based on current state
        if ftd_data.ftd_today:
            status_line = "🎉 **FOLLOW-THROUGH DAY TODAY!** 🎉"
            detail_line = "Signal to begin buying confirmed setups"
        elif ftd_data.rally_failed_today:
            status_line = "⚠️ **RALLY ATTEMPT FAILED** ⚠️"
            detail_line = "Market undercut rally low - back to correction"
        elif ftd_data.in_rally_attempt:
            status_line = f"Rally Attempt: Day {ftd_data.rally_day}"
            if ftd_data.rally_day >= 4:
                detail_line = "Eligible for Follow-Through Day"
            else:
                detail_line = f"Day 4+ needed for FTD signal ({4 - ftd_data.rally_day} more day(s))"
        elif ftd_data.has_confirmed_ftd and ftd_data.ftd_still_valid:
            days_str = f"{ftd_data.days_since_ftd} days ago" if ftd_data.days_since_ftd else "recently"
            status_line = f"✅ FTD Confirmed ({days_str})"
            detail_line = "Uptrend intact - buying permitted"
        else:
            status_line = "No active rally attempt"
            detail_line = "Waiting for low to form, then rally attempt"

        # Rally attempt visualization (only if in rally)
        rally_visual = self._build_rally_visual(ftd_data) if ftd_data.in_rally_attempt or ftd_data.ftd_today else ""

        # Rally/FTD history stats
        history_section = self._build_rally_history_section(ftd_data)

        # FTD dates if available
        ftd_dates_line = ""
        if ftd_data.spy_ftd_date or ftd_data.qqq_ftd_date:
            dates = []
            if ftd_data.spy_ftd_date:
                dates.append(f"SPY: {ftd_data.spy_ftd_date.strftime('%b %d')}")
            if ftd_data.qqq_ftd_date:
                dates.append(f"QQQ: {ftd_data.qqq_ftd_date.strftime('%b %d')}")
            ftd_dates_line = f"\n*Last FTD: {', '.join(dates)}*"

        # Compact output - skip history section to save space
        return f"""
**🎯 PHASE:** {emoji} {phase_display}
{status_line} - {detail_line}{ftd_dates_line}{rally_visual}
"""

    def _build_rally_history_section(self, ftd_data) -> str:
        """Build rally attempt history section."""
        if not ftd_data:
            return ""

        # Get rally histogram if available
        success_count = getattr(ftd_data, 'successful_ftd_count', 0) or 0
        failed_count = getattr(ftd_data, 'failed_rally_count', 0) or 0
        total = success_count + failed_count

        if total == 0:
            return ""

        # Calculate success rate
        success_rate = (success_count / total * 100) if total > 0 else 0

        # Build visual success/fail indicator
        history_visual = ""
        rally_histogram = getattr(ftd_data, 'rally_histogram', None)
        if rally_histogram and hasattr(rally_histogram, 'history'):
            # Show last 10 rally attempts: ✓ = FTD success, ✗ = failed
            recent = rally_histogram.history[-10:] if len(rally_histogram.history) > 10 else rally_histogram.history
            symbols = ['✓' if r.get('success', False) else '✗' for r in recent]
            history_visual = f"\nRecent: {' '.join(symbols)}"

        return f"""
**📊 Rally History** (Rolling 6mo)
```
FTD Success: {success_count} | Failed: {failed_count} | Rate: {success_rate:.0f}%
```{history_visual}
"""
    
    def _build_rally_visual(self, ftd_data) -> str:
        """Build compact visual representation of rally attempt progress."""
        if not ftd_data:
            return ""

        rally_days = ftd_data.rally_day or 0
        max_display = 10  # Show up to 10 days compactly

        # Build compact visual (no spaces between chars)
        if rally_days <= max_display:
            if ftd_data.ftd_today:
                visual = '+' * (rally_days - 1) + '✓'
            else:
                visual = '+' * rally_days
        else:
            # Truncate: show first 4, ellipsis, last 4
            if ftd_data.ftd_today:
                visual = '+' * 4 + '…' + '+' * 4 + '✓'
            else:
                visual = '+' * 4 + '…' + '+' * 5

        return f"\n`Day {rally_days}: [{visual}]`"

    def _send_webhook(self, message: str) -> bool:
        """Send message via Discord webhook."""
        if not self.webhook_url:
            logger.warning("No webhook URL configured")
            return False
        
        try:
            response = requests.post(
                self.webhook_url,
                json={"content": message},
                timeout=10
            )
            response.raise_for_status()
            logger.info("Discord regime alert sent successfully")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Discord alert: {e}")
            return False
    
    def send_regime_alert(
        self,
        score: RegimeScore,
        verbose: bool = True,
        dry_run: bool = False,
        ibd_status: IBDMarketStatus = None,
        ibd_exposure_min: int = None,
        ibd_exposure_max: int = None,
        ibd_updated_at: datetime = None,
        fear_greed_data=None,
        vix_close=None,
        vix_previous_close=None,
    ) -> bool:
        """
        Send a regime alert to Discord.

        Args:
            score: RegimeScore to send
            verbose: If True, send full format. If False, send condensed.
            dry_run: If True, just print the message without sending.
            ibd_status: Manual IBD market status from MarketSurge
            ibd_exposure_min: Manual IBD exposure minimum %
            ibd_exposure_max: Manual IBD exposure maximum %
            ibd_updated_at: When IBD exposure was last updated
            fear_greed_data: Optional FearGreedData for sentiment display
            vix_close: Current VIX level
            vix_previous_close: Previous day's VIX close

        Returns:
            True if sent successfully (or dry run), False otherwise
        """
        message = self.format_regime_alert(
            score,
            verbose=verbose,
            ibd_status=ibd_status,
            ibd_exposure_min=ibd_exposure_min,
            ibd_exposure_max=ibd_exposure_max,
            ibd_updated_at=ibd_updated_at,
            fear_greed_data=fear_greed_data,
            vix_close=vix_close,
            vix_previous_close=vix_previous_close,
        )
        
        if dry_run:
            print("\n" + "="*60)
            print("DRY RUN - Would send to Discord:")
            print("="*60)
            print(message)
            print("="*60 + "\n")
            return True
        
        return self._send_webhook(message)
    
    def send_test_alert(self) -> bool:
        """Send a test alert to verify webhook connectivity."""
        message = "🧪 **Test Alert** - Morning Market Regime system is connected!"
        return self._send_webhook(message)

    def send_phase_change_alert(
        self,
        phase_history: MarketPhaseHistory,
        dist_data=None,
        dry_run: bool = False
    ) -> bool:
        """
        Send a market phase change alert to Discord.

        Args:
            phase_history: MarketPhaseHistory record with phase change details
            dist_data: Optional CombinedDistributionData with current D-day info
            dry_run: If True, just print the message without sending

        Returns:
            True if sent successfully (or dry run), False otherwise
        """
        message = self._format_phase_change_alert(phase_history, dist_data)

        if dry_run:
            print("\n" + "="*60)
            print("DRY RUN - Would send phase change alert to Discord:")
            print("="*60)
            print(message)
            print("="*60 + "\n")
            return True

        return self._send_webhook(message)

    def _format_phase_change_alert(
        self,
        phase_history: MarketPhaseHistory,
        dist_data=None
    ) -> str:
        """
        Format a phase change alert message.

        Args:
            phase_history: MarketPhaseHistory record
            dist_data: Optional distribution data for context

        Returns:
            Formatted message string
        """
        # Get emojis
        prev_emoji = self.PHASE_EMOJI.get(phase_history.previous_phase, '⚪')
        new_emoji = self.PHASE_EMOJI.get(phase_history.new_phase, '⚪')

        change_type = PhaseChangeType(phase_history.change_type) if phase_history.change_type else PhaseChangeType.NONE
        change_emoji = self.PHASE_CHANGE_EMOJI.get(change_type, '•')

        # Format phase names
        prev_display = (phase_history.previous_phase or 'Unknown').replace('_', ' ').title()
        new_display = phase_history.new_phase.replace('_', ' ').title()

        # Determine alert urgency
        if change_type == PhaseChangeType.UPGRADE:
            header = "📈 **MARKET PHASE UPGRADE**"
            color_bar = "🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢"
        elif change_type == PhaseChangeType.DOWNGRADE:
            header = "📉 **MARKET PHASE DOWNGRADE**"
            color_bar = "🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴"
        else:
            header = "➡️ **MARKET PHASE CHANGE**"
            color_bar = "🟡🟡🟡🟡🟡🟡🟡🟡🟡🟡"

        # Format date
        date_str = phase_history.phase_date.strftime('%A, %B %d, %Y')

        # Build transition visual
        transition_visual = f"""
```
{prev_emoji} {prev_display}
       │
       │  {change_emoji} {change_type.value}
       ▼
{new_emoji} {new_display}
```"""

        # Build context section
        context_lines = []
        if phase_history.trigger_reason:
            context_lines.append(f"**Trigger:** {phase_history.trigger_reason}")

        # D-day context
        spy_count = phase_history.spy_dday_count or 0
        qqq_count = phase_history.qqq_dday_count or 0
        total_count = phase_history.total_dday_count or (spy_count + qqq_count)
        context_lines.append(f"**D-Days:** SPY: {spy_count} | QQQ: {qqq_count} | Total: {total_count}")

        # Expiration context
        spy_expired = phase_history.spy_expired_today or 0
        qqq_expired = phase_history.qqq_expired_today or 0
        if spy_expired > 0 or qqq_expired > 0:
            context_lines.append(f"**Expired Today:** SPY: {spy_expired} | QQQ: {qqq_expired}")

        # FTD context
        if phase_history.ftd_active:
            context_lines.append("**FTD Status:** ✅ Active")
            if phase_history.ftd_gain_pct:
                context_lines.append(f"**FTD Gain:** {phase_history.ftd_gain_pct:+.2f}%")
        elif phase_history.rally_day:
            context_lines.append(f"**Rally Day:** {phase_history.rally_day}")

        context_section = '\n'.join(context_lines)

        # Get phase-specific guidance
        guidance = self._get_phase_guidance(phase_history.new_phase, change_type)

        # Optional mention for important changes
        mention = ""
        if self.mention_role and change_type in [PhaseChangeType.UPGRADE, PhaseChangeType.DOWNGRADE]:
            mention = f"{self.mention_role}\n"

        message = f"""{mention}{header}
{color_bar}
*{date_str}*

{transition_visual}

**📊 CONTEXT**
{context_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**📋 ACTION GUIDANCE**
{guidance}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        return message

    def _get_phase_guidance(self, phase: str, change_type: PhaseChangeType) -> str:
        """
        Get trading guidance for a specific phase and change type.

        Args:
            phase: The new market phase
            change_type: Type of phase change (UPGRADE, DOWNGRADE, LATERAL)

        Returns:
            Guidance text
        """
        guidance_map = {
            'CONFIRMED_UPTREND': {
                PhaseChangeType.UPGRADE: (
                    "🟢 **Full Risk-On Mode**\n"
                    "→ Market confirms new uptrend\n"
                    "→ Resume normal buying on breakouts\n"
                    "→ Standard position sizes (full allocation)\n"
                    "→ Focus on leaders emerging from sound bases\n"
                    "→ Honor 7-8% stop loss rules"
                ),
                PhaseChangeType.LATERAL: (
                    "🟢 **Uptrend Confirmed**\n"
                    "→ Continue normal buying\n"
                    "→ Standard position sizes\n"
                    "→ Honor stop loss rules"
                ),
            },
            'UPTREND_PRESSURE': {
                PhaseChangeType.DOWNGRADE: (
                    "🟠 **Caution Mode - Reduce Exposure**\n"
                    "→ Distribution days piling up\n"
                    "→ Tighten stops on existing positions\n"
                    "→ Reduce position sizes on new buys (50%)\n"
                    "→ A-grade setups only\n"
                    "→ Consider taking partial profits on winners"
                ),
                PhaseChangeType.LATERAL: (
                    "🟠 **Cautious Posture**\n"
                    "→ Market under pressure but intact\n"
                    "→ Be selective with new entries\n"
                    "→ Tighter stops recommended"
                ),
            },
            'RALLY_ATTEMPT': {
                PhaseChangeType.UPGRADE: (
                    "🟡 **Rally Attempt Beginning**\n"
                    "→ Market attempting to establish new uptrend\n"
                    "→ Watch for Follow-Through Day (Day 4+)\n"
                    "→ Prepare watchlist of A-grade setups\n"
                    "→ No new buys until FTD confirms\n"
                    "→ Rally days must hold above prior low"
                ),
                PhaseChangeType.LATERAL: (
                    "🟡 **Rally Attempt In Progress**\n"
                    "→ Continue monitoring for FTD\n"
                    "→ Prepare watchlist\n"
                    "→ No new positions yet"
                ),
            },
            'CORRECTION': {
                PhaseChangeType.DOWNGRADE: (
                    "🔴 **Defensive Mode - Preserve Capital**\n"
                    "→ Market in correction\n"
                    "→ NO new long positions\n"
                    "→ Honor all stop losses strictly\n"
                    "→ Consider raising cash on weakness\n"
                    "→ Build watchlist for next uptrend\n"
                    "→ Wait for rally attempt to begin"
                ),
                PhaseChangeType.LATERAL: (
                    "🔴 **Correction Continues**\n"
                    "→ Stay defensive\n"
                    "→ No new long positions\n"
                    "→ Wait for rally attempt"
                ),
            },
            'MARKET_IN_CORRECTION': {
                PhaseChangeType.DOWNGRADE: (
                    "🔴 **Defensive Mode - Preserve Capital**\n"
                    "→ Market in correction\n"
                    "→ NO new long positions\n"
                    "→ Honor all stop losses\n"
                    "→ Build watchlist for next uptrend"
                ),
                PhaseChangeType.LATERAL: (
                    "🔴 **Correction Continues**\n"
                    "→ Stay defensive\n"
                    "→ Wait for rally attempt"
                ),
            },
        }

        phase_guidance = guidance_map.get(phase, {})
        return phase_guidance.get(
            change_type,
            f"→ Phase: {phase.replace('_', ' ').title()}\n→ Monitor market conditions"
        )

    def send_ftd_alert(
        self,
        ftd_date: date,
        ftd_gain_pct: float,
        volume_pct: float = None,
        from_pressure: bool = False,
        dry_run: bool = False
    ) -> bool:
        """
        Send a Follow-Through Day alert to Discord.

        Args:
            ftd_date: Date of the FTD
            ftd_gain_pct: Percentage gain on FTD
            volume_pct: Optional volume percentage vs average
            from_pressure: True if FTD is upgrading from Uptrend Under Pressure
            dry_run: If True, just print without sending

        Returns:
            True if sent successfully
        """
        message = self._format_ftd_alert(ftd_date, ftd_gain_pct, volume_pct, from_pressure)

        if dry_run:
            print("\n" + "="*60)
            print("DRY RUN - Would send FTD alert to Discord:")
            print("="*60)
            print(message)
            print("="*60 + "\n")
            return True

        return self._send_webhook(message)

    def _format_ftd_alert(
        self,
        ftd_date: date,
        ftd_gain_pct: float,
        volume_pct: float = None,
        from_pressure: bool = False
    ) -> str:
        """Format a Follow-Through Day alert message."""
        date_str = ftd_date.strftime('%A, %B %d, %Y')

        if from_pressure:
            header = "🎉 **FOLLOW-THROUGH FROM PRESSURE** 🎉"
            context = "Market recovers from Uptrend Under Pressure"
        else:
            header = "🎉 **FOLLOW-THROUGH DAY CONFIRMED** 🎉"
            context = "New market uptrend confirmed"

        volume_line = ""
        if volume_pct:
            volume_line = f"\n**Volume:** {volume_pct:.0f}% of average"

        mention = f"{self.mention_role}\n" if self.mention_role else ""

        message = f"""{mention}{header}
🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢
*{date_str}*

**Index Gain:** {ftd_gain_pct:+.2f}%{volume_line}

{context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**📋 ACTION GUIDANCE**
→ Begin buying confirmed breakouts
→ Start with half positions, add on strength
→ Focus on leaders with RS 90+
→ Honor 7-8% stop loss rules
→ Not all FTDs lead to sustained rallies - stay disciplined

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        return message

    def send_dday_expiration_alert(
        self,
        expirations: list,
        new_spy_count: int,
        new_qqq_count: int,
        phase_improved: bool = False,
        dry_run: bool = False
    ) -> bool:
        """
        Send an alert when distribution days expire.

        Args:
            expirations: List of expiration details (symbol, date, reason)
            new_spy_count: SPY D-day count after expirations
            new_qqq_count: QQQ D-day count after expirations
            phase_improved: True if phase upgraded due to expirations
            dry_run: If True, just print without sending

        Returns:
            True if sent successfully
        """
        if not expirations:
            return True

        message = self._format_dday_expiration_alert(
            expirations, new_spy_count, new_qqq_count, phase_improved
        )

        if dry_run:
            print("\n" + "="*60)
            print("DRY RUN - Would send D-Day expiration alert:")
            print("="*60)
            print(message)
            print("="*60 + "\n")
            return True

        return self._send_webhook(message)

    def _format_dday_expiration_alert(
        self,
        expirations: list,
        new_spy_count: int,
        new_qqq_count: int,
        phase_improved: bool
    ) -> str:
        """Format a D-day expiration alert message."""
        today_str = datetime.now().strftime('%A, %B %d, %Y')

        # Count by reason
        time_expirations = [e for e in expirations if e.get('reason') == 'TIME']
        rally_expirations = [e for e in expirations if e.get('reason') == 'RALLY']

        header = "📅 **DISTRIBUTION DAYS EXPIRED**"
        if phase_improved:
            header = "📈 **D-DAYS EXPIRED - PHASE IMPROVED**"

        # Format expiration details
        exp_lines = []
        for exp in expirations:
            symbol = exp.get('symbol', '???')
            exp_date = exp.get('date', '???')
            reason = exp.get('reason', '???')
            reason_emoji = '⏰' if reason == 'TIME' else '📈'
            exp_lines.append(f"  {reason_emoji} {symbol} ({exp_date}) - {reason}")

        exp_details = '\n'.join(exp_lines)

        message = f"""{header}
*{today_str}*

**Expirations:**
{exp_details}

**New Counts:**
```
SPY: {new_spy_count} D-days
QQQ: {new_qqq_count} D-days
Total: {new_spy_count + new_qqq_count}
```
"""

        if phase_improved:
            message += """
✅ D-day count dropped below threshold - market phase improved
"""

        return message


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Discord Regime Notifier (dry run)...")
    print("This version has FIXED histogram date handling.")
    
    # Quick test with sample data
    from datetime import date, timedelta
    
    today = date.today()
    
    # Sample dates - mix of recent and older
    spy_dates = [
        today - timedelta(days=2),
        today - timedelta(days=8),
        today - timedelta(days=15),
        today - timedelta(days=22),
    ]
    qqq_dates = [
        today - timedelta(days=1),
        today - timedelta(days=5),
        today - timedelta(days=12),
        today - timedelta(days=18),
    ]
    
    notifier = DiscordRegimeNotifier(webhook_url=None)
    
    # Test histogram directly
    print("\n=== Testing Histogram with sample dates ===")
    histogram = notifier._build_dday_histogram(
        spy_dates=spy_dates,
        qqq_dates=qqq_dates,
        spy_count=4,
        qqq_count=4,
        reference_date=today
    )
    print(histogram)
