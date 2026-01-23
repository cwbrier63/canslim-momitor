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
    IBDExposureCurrent
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
        DDayTrend.FLAT: '🟡'
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
        ibd_updated_at: datetime = None
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
            ibd_updated_at=ibd_updated_at
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
        ibd_updated_at: datetime = None
    ) -> str:
        """
        Full detailed format with separated IBD exposure and entry risk.
        
        Args:
            score: RegimeScore with calculated entry risk
            ibd_status: Manual IBD market status from MarketSurge
            ibd_exposure_min: Manual IBD exposure minimum %
            ibd_exposure_max: Manual IBD exposure maximum %
            ibd_updated_at: When IBD exposure was last updated
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
        
        message = f"""{mention}__**🌅 MORNING MARKET REGIME ALERT**__
*{date_str}*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{ibd_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**📊 DISTRIBUTION DAY COUNT** (Rolling 25-Day)
```
┌─────────┬───────┬─────────┬────────────┐
│ Index   │ Count │ 5-Day Δ │ Trend      │
├─────────┼───────┼─────────┼────────────┤
│ SPY     │   {dist.spy_count}   │   {dist.spy_5day_delta:+2d}    │ {dist.trend.value:<10} │
│ QQQ     │   {dist.qqq_count}   │   {dist.qqq_5day_delta:+2d}    │ {dist.trend.value:<10} │
└─────────┴───────┴─────────┴────────────┘
```
{trend_emoji} D-Day Trend: **{dist.trend.value}**
{histogram}
**🌙 OVERNIGHT FUTURES** (Since 6PM Globex Open)
```
┌────────┬──────────┬─────────┐
│ Symbol │  Change  │ Signal  │
├────────┼──────────┼─────────┤
│ ES     │ {overnight.es_change_pct:+7.2f}% │ {overnight.es_trend.value:<7} │
│ NQ     │ {overnight.nq_change_pct:+7.2f}% │ {overnight.nq_trend.value:<7} │
│ YM     │ {overnight.ym_change_pct:+7.2f}% │ {overnight.ym_trend.value:<7} │
└────────┴──────────┴─────────┘
```
{es_emoji} ES  {nq_emoji} NQ  {ym_emoji} YM

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{entry_risk_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{guidance_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
        
        # Simple format without box (Discord renders these inconsistently)
        return f"""
**📊 IBD MARKET STATUS** (from MarketSurge)
```
Status:   {status_display}
Exposure: {exposure_min}-{exposure_max}%
{updated_str}
```
{status_message}
"""
    
    def _build_entry_risk_section(self, score: RegimeScore) -> str:
        """Build the Entry Risk section (tactical layer)."""
        emoji = self.ENTRY_RISK_EMOJI.get(score.entry_risk_level, '⚪')
        level_name = score.entry_risk_level.value
        desc = get_entry_risk_description(score.entry_risk_level)
        
        # Build visual bar
        risk_bar = self._build_entry_risk_bar(score.entry_risk_score)
        
        return f"""
**⚠️ TODAY'S ENTRY RISK**

Risk Score: {score.entry_risk_score:+.2f}
{risk_bar}
{emoji} **{level_name}** - {desc}
"""
    
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
        
        # Check for D-day clustering warning
        max_d = max(dist_data.spy_count, dist_data.qqq_count)
        clustering_warning = ""
        if max_d >= 6:
            clustering_warning = f"\n⚠️ *High D-day count ({max_d}) - watch for distribution clustering*"
        
        breakout_lines = '\n'.join(breakout_guidance)
        position_lines = '\n'.join(position_guidance)
        
        return f"""
**📋 TODAY'S GUIDANCE**

**For Watchlist Breakouts:**
{breakout_lines}

**For Existing Positions:**
{position_lines}{clustering_warning}
"""
    
    def _build_dday_histogram(
        self, 
        spy_dates: list, 
        qqq_dates: list, 
        spy_count: int = None,
        qqq_count: int = None,
        lookback_days: int = 25,
        reference_date: date = None
    ) -> str:
        """
        Build ASCII histogram showing D-day distribution over 25 days.
        
        Shows clustering of distribution days - recent clustering is more
        concerning than spread-out D-days.
        
        FIXED: 
        - Uses reference_date instead of date.today() for consistency
        - Uses official counts if provided (to match table with overrides)
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
        
        # Week markers for scale reference
        # 25 days ≈ 5 weeks, mark every 5 days
        scale_line = "└" + "────┴" * 4 + "────┘"
        
        histogram = f"""
📅 **D-DAY HISTOGRAM** (25-Day Rolling Window)
```
         ← 25 days ago          Today →
SPY [{spy_display_count}]: {spy_bar}
QQQ [{qqq_display_count}]: {qqq_bar}
         {scale_line}
         Wk5  Wk4  Wk3  Wk2  Wk1
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
        
        # Build status line
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
            status_line = f"FTD Confirmed ({ftd_data.days_since_ftd} days ago)"
            detail_line = "Uptrend intact - buying permitted"
        else:
            status_line = "No active rally"
            detail_line = "Waiting for rally attempt"
        
        # Rally attempt visualization
        rally_visual = self._build_rally_visual(ftd_data) if ftd_data.in_rally_attempt or ftd_data.ftd_today else ""
        
        return f"""
**🎯 MARKET PHASE:** {emoji} {phase_display}
{status_line}
{detail_line}
{rally_visual}
"""
    
    def _build_rally_visual(self, ftd_data) -> str:
        """Build visual representation of rally attempt progress."""
        if not ftd_data:
            return ""
        
        rally_days = ftd_data.rally_day or 0
        max_display = 20  # Show up to 20 days
        
        # Build the visual
        # - = No rally, + = Rally day, X = Failed, ✓ = FTD
        days = []
        for i in range(1, min(rally_days + 1, max_display + 1)):
            if ftd_data.ftd_today and i == rally_days:
                days.append('✓')
            else:
                days.append('+')
        
        visual = ' '.join(days)
        legend = "· = No rally | 1-9 = Rally day | X = Failed | ✓ = FTD"
        
        return f"""
```
Rally Attempts ({rally_days} trading days)
{'─' * 50}
{visual}
{'─' * 50}
{legend}
Failed: 0 | Successful FTDs: {1 if ftd_data.has_confirmed_ftd else 0}
```
"""

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
        ibd_updated_at: datetime = None
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
        
        Returns:
            True if sent successfully (or dry run), False otherwise
        """
        message = self.format_regime_alert(
            score, 
            verbose=verbose,
            ibd_status=ibd_status,
            ibd_exposure_min=ibd_exposure_min,
            ibd_exposure_max=ibd_exposure_max,
            ibd_updated_at=ibd_updated_at
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
