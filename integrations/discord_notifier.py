"""
CANSLIM Monitor - Discord Notifier
Send trading alerts to Discord channels via webhooks.

Supports multiple channels for different alert types.
"""

import logging
import requests
from datetime import datetime
from typing import Optional, Dict, List, Any
from enum import Enum
from threading import Lock
import time


class AlertChannel(Enum):
    """Discord channel types for different alerts."""
    BREAKOUT = 'breakout'
    POSITION = 'position'
    MARKET = 'market'
    SYSTEM = 'system'


class DiscordNotifier:
    """
    Discord webhook notifier for trading alerts.
    
    Features:
    - Multiple channels for different alert types
    - Rate limiting to avoid Discord limits
    - Embed formatting for rich messages
    - Retry logic for failed sends
    """
    
    # Discord rate limits
    RATE_LIMIT_MESSAGES = 30
    RATE_LIMIT_WINDOW = 60  # seconds
    
    # Embed colors
    COLORS = {
        'green': 0x00FF00,
        'red': 0xFF0000,
        'yellow': 0xFFFF00,
        'blue': 0x0099FF,
        'orange': 0xFF9900,
        'purple': 0x9900FF,
        'cyan': 0x00FFFF,
    }
    
    def __init__(
        self,
        webhooks: Dict[str, str] = None,
        default_webhook: str = None,
        logger: Optional[logging.Logger] = None,
        enabled: bool = True
    ):
        """
        Initialize Discord notifier.
        
        Args:
            webhooks: Dict mapping channel name to webhook URL
            default_webhook: Default webhook if channel not found
            logger: Logger instance
            enabled: Whether notifications are enabled
        """
        self.webhooks = webhooks or {}
        self.default_webhook = default_webhook
        self.logger = logger or logging.getLogger('canslim.discord')
        self.enabled = enabled
        
        # Rate limiting
        self._message_times: List[datetime] = []
        self._lock = Lock()
    
    # ==================== CONFIGURATION ====================
    
    def set_webhook(self, channel: str, webhook_url: str):
        """Set webhook URL for a channel."""
        self.webhooks[channel] = webhook_url
    
    def set_webhooks(self, webhooks: Dict[str, str]):
        """Set multiple webhook URLs."""
        self.webhooks.update(webhooks)
    
    def set_enabled(self, enabled: bool):
        """Enable or disable notifications."""
        self.enabled = enabled
    
    # ==================== SENDING ====================
    
    def send(
        self,
        content: str = None,
        embed: Dict = None,
        channel: str = None,
        username: str = 'CANSLIM Monitor'
    ) -> bool:
        """
        Send a message to Discord.
        
        Args:
            content: Plain text message
            embed: Embed dict for rich formatting
            channel: Channel name (maps to webhook)
            username: Bot username to display
            
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            self.logger.warning("Discord notifications DISABLED - message not sent")
            return False  # Return False when disabled to indicate no message sent
        
        # Get webhook URL
        webhook_url = self.webhooks.get(channel) or self.default_webhook
        if not webhook_url:
            self.logger.warning(f"No webhook configured for channel: {channel}")
            self.logger.warning(f"Available webhooks: {list(self.webhooks.keys())}")
            self.logger.warning(f"Default webhook: {'configured' if self.default_webhook else 'NOT configured'}")
            return False
        
        # Log what we're sending (redact webhook URL for security)
        webhook_preview = webhook_url[:50] + "..." if len(webhook_url) > 50 else webhook_url
        self.logger.debug(f"Sending to Discord channel={channel}, webhook={webhook_preview}")
        
        # Check rate limit
        if not self._check_rate_limit():
            self.logger.warning("Rate limit reached, delaying message")
            time.sleep(2)
        
        # Build payload
        payload = {'username': username}
        
        if content:
            payload['content'] = content
        
        if embed:
            payload['embeds'] = [embed]
        
        # Send with retry
        return self._send_with_retry(webhook_url, payload)
    
    def _send_with_retry(
        self,
        webhook_url: str,
        payload: Dict,
        max_retries: int = 3
    ) -> bool:
        """Send with retry logic."""
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    webhook_url,
                    json=payload,
                    timeout=10
                )
                
                if response.status_code == 204:
                    self._record_message()
                    self.logger.debug(f"Discord HTTP 204 success (attempt {attempt + 1})")
                    return True
                elif response.status_code == 429:
                    # Rate limited by Discord
                    retry_after = response.json().get('retry_after', 5)
                    self.logger.warning(f"Discord rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                else:
                    self.logger.error(f"Discord error {response.status_code}: {response.text}")
                    
            except Exception as e:
                self.logger.error(f"Error sending to Discord (attempt {attempt + 1}): {e}")
            
            if attempt < max_retries - 1:
                time.sleep(1)
        
        self.logger.error(f"Discord send failed after {max_retries} attempts")
        return False
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        with self._lock:
            now = datetime.now()
            cutoff = now.timestamp() - self.RATE_LIMIT_WINDOW
            
            # Remove old entries
            self._message_times = [
                t for t in self._message_times
                if t.timestamp() > cutoff
            ]
            
            return len(self._message_times) < self.RATE_LIMIT_MESSAGES
    
    def _record_message(self):
        """Record a sent message for rate limiting."""
        with self._lock:
            self._message_times.append(datetime.now())
    
    # ==================== ALERT HELPERS ====================
    
    def send_alert(
        self,
        message: str,
        channel: str = 'breakout',
        alert_type: str = None,
        priority: str = 'P1',
        username: str = 'CANSLIM Monitor'
    ) -> bool:
        """
        Send a generic alert message (used by AlertService).
        
        Args:
            message: Alert message text
            channel: Channel name (breakout, position, market, system)
            alert_type: Type of alert (for logging)
            priority: Priority level (P0, P1, P2)
            username: Bot username to display
            
        Returns:
            True if sent successfully
        """
        self.logger.debug(f"Sending {alert_type} alert to #{channel} (priority={priority})")
        return self.send(content=message, channel=channel, username=username)
    
    def send_message(self, message: str, channel: str = None) -> bool:
        """
        Send a plain text message (legacy method for direct calls).
        
        Args:
            message: Message content
            channel: Optional channel name
            
        Returns:
            True if sent successfully
        """
        return self.send(content=message, channel=channel or 'breakout')
    
    def send_breakout_alert(
        self,
        symbol: str,
        price: float,
        pivot: float,
        grade: str,
        score: int,
        volume_ratio: float,
        rs_rating: int = None,
        portfolio: str = None
    ) -> bool:
        """Send breakout alert."""
        pct_above = ((price - pivot) / pivot) * 100
        
        # Determine color based on grade
        if grade.startswith('A'):
            color = self.COLORS['green']
        elif grade.startswith('B'):
            color = self.COLORS['cyan']
        else:
            color = self.COLORS['yellow']
        
        embed = {
            'title': f'🚀 BREAKOUT: {symbol}',
            'color': color,
            'fields': [
                {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                {'name': 'Pivot', 'value': f'${pivot:.2f}', 'inline': True},
                {'name': 'Above Pivot', 'value': f'{pct_above:+.1f}%', 'inline': True},
                {'name': 'Volume', 'value': f'{volume_ratio:.0%} avg', 'inline': True},
                {'name': 'Grade', 'value': grade, 'inline': True},
                {'name': 'Score', 'value': str(score), 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        if rs_rating:
            embed['fields'].append({'name': 'RS Rating', 'value': str(rs_rating), 'inline': True})
        
        if portfolio:
            embed['fields'].append({'name': 'Portfolio', 'value': portfolio, 'inline': True})
        
        return self.send(embed=embed, channel=AlertChannel.BREAKOUT.value)
    
    def send_buy_zone_alert(
        self,
        symbol: str,
        price: float,
        pivot: float,
        grade: str,
        score: int,
        rs_rating: int = None
    ) -> bool:
        """Send buy zone alert."""
        pct_above = ((price - pivot) / pivot) * 100
        
        embed = {
            'title': f'✅ IN BUY ZONE: {symbol}',
            'color': self.COLORS['cyan'],
            'fields': [
                {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                {'name': 'Pivot', 'value': f'${pivot:.2f}', 'inline': True},
                {'name': 'Above Pivot', 'value': f'{pct_above:+.1f}%', 'inline': True},
                {'name': 'Grade', 'value': grade, 'inline': True},
                {'name': 'Score', 'value': str(score), 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        if rs_rating:
            embed['fields'].append({'name': 'RS Rating', 'value': str(rs_rating), 'inline': True})
        
        return self.send(embed=embed, channel=AlertChannel.BREAKOUT.value)
    
    def send_extended_alert(
        self,
        symbol: str,
        price: float,
        pivot: float
    ) -> bool:
        """Send extended/chase warning alert."""
        pct_above = ((price - pivot) / pivot) * 100
        
        embed = {
            'title': f'⚠️ EXTENDED: {symbol}',
            'description': 'Consider waiting for pullback',
            'color': self.COLORS['yellow'],
            'fields': [
                {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                {'name': 'Pivot', 'value': f'${pivot:.2f}', 'inline': True},
                {'name': 'Above Pivot', 'value': f'{pct_above:+.1f}%', 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        return self.send(embed=embed, channel=AlertChannel.BREAKOUT.value)
    
    def send_stop_alert(
        self,
        symbol: str,
        price: float,
        stop: float,
        avg_cost: float,
        alert_type: str = 'warning'
    ) -> bool:
        """Send stop loss alert."""
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        to_stop_pct = ((price - stop) / price) * 100
        
        if alert_type == 'hit':
            title = f'🛑 STOP HIT: {symbol}'
            color = self.COLORS['red']
        else:
            title = f'⚠️ STOP WARNING: {symbol}'
            color = self.COLORS['orange']
        
        embed = {
            'title': title,
            'color': color,
            'fields': [
                {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                {'name': 'Stop', 'value': f'${stop:.2f}', 'inline': True},
                {'name': 'To Stop', 'value': f'{to_stop_pct:.1f}%', 'inline': True},
                {'name': 'Avg Cost', 'value': f'${avg_cost:.2f}', 'inline': True},
                {'name': 'P&L', 'value': f'{pnl_pct:+.1f}%', 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        return self.send(embed=embed, channel=AlertChannel.POSITION.value)
    
    def send_profit_alert(
        self,
        symbol: str,
        price: float,
        target: float,
        avg_cost: float,
        target_name: str
    ) -> bool:
        """Send profit target alert."""
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        
        embed = {
            'title': f'💰 {target_name} REACHED: {symbol}',
            'color': self.COLORS['green'],
            'fields': [
                {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                {'name': 'Target', 'value': f'${target:.2f}', 'inline': True},
                {'name': 'P&L', 'value': f'{pnl_pct:+.1f}%', 'inline': True},
                {'name': 'Avg Cost', 'value': f'${avg_cost:.2f}', 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        return self.send(embed=embed, channel=AlertChannel.POSITION.value)
    
    def send_pyramid_alert(
        self,
        symbol: str,
        price: float,
        pyramid_level: float,
        avg_cost: float,
        pyramid_number: int
    ) -> bool:
        """Send pyramid opportunity alert."""
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        
        embed = {
            'title': f'📈 PYRAMID {pyramid_number}: {symbol}',
            'color': self.COLORS['blue'],
            'fields': [
                {'name': 'Price', 'value': f'${price:.2f}', 'inline': True},
                {'name': 'Entry Level', 'value': f'${pyramid_level:.2f}', 'inline': True},
                {'name': 'Current P&L', 'value': f'{pnl_pct:+.1f}%', 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        return self.send(embed=embed, channel=AlertChannel.POSITION.value)
    
    def send_health_alert(
        self,
        symbol: str,
        score: int,
        rating: str,
        price: float,
        avg_cost: float,
        issues: List[str] = None
    ) -> bool:
        """Send position health alert."""
        pnl_pct = ((price - avg_cost) / avg_cost) * 100
        
        if score >= 70:
            color = self.COLORS['green']
        elif score >= 50:
            color = self.COLORS['yellow']
        else:
            color = self.COLORS['red']
        
        embed = {
            'title': f'❤️ HEALTH CHECK: {symbol}',
            'color': color,
            'fields': [
                {'name': 'Score', 'value': f'{score}/100', 'inline': True},
                {'name': 'Rating', 'value': rating, 'inline': True},
                {'name': 'P&L', 'value': f'{pnl_pct:+.1f}%', 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        if issues:
            embed['description'] = '⚠️ ' + '\n⚠️ '.join(issues)
        
        return self.send(embed=embed, channel=AlertChannel.POSITION.value)
    
    def send_market_regime_alert(
        self,
        regime: str,
        score: float,
        exposure: int,
        spy_price: float,
        spy_change: float,
        qqq_price: float,
        qqq_change: float,
        distribution_days: int = 0,
        # Extended data for full format
        spy_dist_days: int = 0,
        qqq_dist_days: int = 0,
        spy_5day_delta: int = 0,
        qqq_5day_delta: int = 0,
        dist_trend: str = 'FLAT',
        market_phase: str = 'UNKNOWN',
        ftd_info: str = None,
        overnight_futures: Dict = None,
        # New fields for full format
        spy_dday_positions: List[int] = None,  # Days ago (0=today, 24=25 days ago)
        qqq_dday_positions: List[int] = None,
        rally_day: int = 0,
        rally_failed: int = 0,
        successful_ftds: int = 0,
        prior_score: float = None,
        score_direction: str = 'STABLE',
        verbose: bool = True
    ) -> bool:
        """
        Send market regime alert in format matching morning regime system.
        
        Args:
            regime: BULLISH, NEUTRAL, BEARISH
            score: Composite score (0.0 to 1.5 scale)
            exposure: Recommended exposure 1-5
            spy_price/qqq_price: Current prices
            spy_change/qqq_change: Daily change %
            spy_dist_days/qqq_dist_days: Distribution day counts
            spy_5day_delta/qqq_5day_delta: 5-day change in D-day count
            dist_trend: IMPROVING, WORSENING, FLAT
            market_phase: CONFIRMED_UPTREND, RALLY_ATTEMPT, CORRECTION, etc.
            ftd_info: FTD status string
            overnight_futures: Dict with es_change, nq_change, ym_change
            spy_dday_positions/qqq_dday_positions: D-day positions for histogram
            rally_day: Current rally day count
            rally_failed: Number of failed rallies
            successful_ftds: Number of successful FTDs
            prior_score: Previous day's score for trend context
            score_direction: IMPROVING, WORSENING, STABLE
            verbose: Full format vs condensed
        """
        if not verbose:
            return self._send_condensed_regime(
                regime, spy_dist_days, qqq_dist_days,
                overnight_futures or {}
            )
        
        return self._send_full_regime(
            regime=regime,
            score=score,
            exposure=exposure,
            spy_price=spy_price,
            spy_change=spy_change,
            qqq_price=qqq_price,
            qqq_change=qqq_change,
            spy_dist_days=spy_dist_days,
            qqq_dist_days=qqq_dist_days,
            spy_5day_delta=spy_5day_delta,
            qqq_5day_delta=qqq_5day_delta,
            dist_trend=dist_trend,
            market_phase=market_phase,
            ftd_info=ftd_info,
            overnight_futures=overnight_futures or {},
            spy_dday_positions=spy_dday_positions,
            qqq_dday_positions=qqq_dday_positions,
            rally_day=rally_day,
            rally_failed=rally_failed,
            successful_ftds=successful_ftds,
            prior_score=prior_score,
            score_direction=score_direction
        )
    
    def _send_condensed_regime(
        self,
        regime: str,
        spy_dist: int,
        qqq_dist: int,
        futures: Dict
    ) -> bool:
        """Send one-liner condensed format."""
        regime_emoji = {'BULLISH': '🟢', 'NEUTRAL': '🟡', 'BEARISH': '🔴'}.get(regime, '⚪')
        
        es = futures.get('es_change', 0)
        nq = futures.get('nq_change', 0)
        ym = futures.get('ym_change', 0)
        
        message = (
            f"🌅 REGIME: {regime_emoji} **{regime}** | "
            f"SPY: {spy_dist} D-days | QQQ: {qqq_dist} D-days | "
            f"ES {es:+.2f}% NQ {nq:+.2f}% YM {ym:+.2f}%"
        )
        
        return self.send(content=message, channel=AlertChannel.MARKET.value)
    
    def _build_dday_histogram(
        self,
        spy_positions: List[int],
        qqq_positions: List[int],
        spy_count: int,
        qqq_count: int
    ) -> str:
        """Build D-day histogram showing distribution over 25-day window."""
        # Build 25-char strings showing D-day positions
        spy_bar = ['·'] * 25
        qqq_bar = ['·'] * 25
        
        # Positions are days ago (0=today, 24=25 days ago)
        # Display: left=oldest (24), right=newest (0)
        for pos in (spy_positions or []):
            if 0 <= pos < 25:
                spy_bar[24 - pos] = '■'
        
        for pos in (qqq_positions or []):
            if 0 <= pos < 25:
                qqq_bar[24 - pos] = '■'
        
        spy_str = ''.join(spy_bar)
        qqq_str = ''.join(qqq_bar)
        
        # Clustering analysis
        spy_recent = sum(1 for p in (spy_positions or []) if p < 5)
        qqq_recent = sum(1 for p in (qqq_positions or []) if p < 5)
        total_recent = spy_recent + qqq_recent
        
        if total_recent >= 3:
            clustering_note = "⚠️ Heavy recent clustering"
        elif total_recent >= 2:
            clustering_note = "📍 Some recent clustering"
        elif total_recent == 0 and (spy_count + qqq_count) > 0:
            clustering_note = "✓ D-days aging out"
        else:
            clustering_note = ""
        
        return f"""
📅 **D-DAY HISTOGRAM** (25-Day Rolling Window)
```
         ← 25 days ago          Today →
SPY [{spy_count}]: {spy_str}
QQQ [{qqq_count}]: {qqq_str}
         └────┴────┴────┴────┴────┘
         Wk5  Wk4  Wk3  Wk2  Wk1
```
{clustering_note}
"""
    
    def _build_rally_visual(self, rally_day: int, rally_failed: int, successful_ftds: int) -> str:
        """Build rally attempt visualization."""
        if rally_day <= 0:
            return ""
        
        # Build the + + + visual for rally days
        days_visual = ' '.join(['+'] * min(rally_day, 25))
        
        return f"""
```
Rally Attempts ({rally_day} trading days)
{'─' * 50}
{days_visual}
{'─' * 50}
· = No rally | 1-9 = Rally day | X = Failed | ✓ = FTD
Failed: {rally_failed} | Successful FTDs: {successful_ftds}
```
"""
    
    def _build_trend_context(self, current_score: float, prior_score: float, direction: str) -> str:
        """Build trend context section."""
        if prior_score is None:
            return ""
        
        delta = current_score - prior_score
        dir_emoji = {'IMPROVING': '📈', 'WORSENING': '📉', 'STABLE': '➡️'}.get(direction, '➡️')
        
        return f"""
**TREND CONTEXT** {dir_emoji}
```
Prior Score: {prior_score:+.2f} → Current: {current_score:+.2f} ({delta:+.2f})
Direction:   {direction}
```
"""
    
    def _get_regime_guidance(self, regime: str) -> str:
        """Get trading guidance for regime."""
        guidance = {
            'BULLISH': (
                "→ Full position sizes permitted\n"
                "→ Favor long setups on breakouts\n"
                "→ Market supports growth stocks"
            ),
            'NEUTRAL': (
                "→ Reduced position sizes (50-75%)\n"
                "→ Selective entries - A+ setups only\n"
                "→ Tighten stops on existing positions"
            ),
            'BEARISH': (
                "→ Defensive posture - raise cash\n"
                "→ Avoid new long positions\n"
                "→ Wait for follow-through day signal"
            )
        }
        return guidance.get(regime, "")
    
    def _send_full_regime(
        self,
        regime: str,
        score: float,
        exposure: int,
        spy_price: float,
        spy_change: float,
        qqq_price: float,
        qqq_change: float,
        spy_dist_days: int,
        qqq_dist_days: int,
        spy_5day_delta: int,
        qqq_5day_delta: int,
        dist_trend: str,
        market_phase: str,
        ftd_info: str,
        overnight_futures: Dict,
        spy_dday_positions: List[int] = None,
        qqq_dday_positions: List[int] = None,
        rally_day: int = 0,
        rally_failed: int = 0,
        successful_ftds: int = 0,
        prior_score: float = None,
        score_direction: str = 'STABLE'
    ) -> bool:
        """Send full formatted regime alert matching morning system."""
        
        # Emojis
        regime_emoji = {'BULLISH': '🟢', 'NEUTRAL': '🟡', 'BEARISH': '🔴'}.get(regime, '⚪')
        trend_emoji = {'IMPROVING': '🟢', 'WORSENING': '🔴', 'FLAT': '🟡'}.get(dist_trend, '🟡')
        phase_emoji = {
            'CONFIRMED_UPTREND': '🟢',
            'RALLY_ATTEMPT': '🟡', 
            'UPTREND_PRESSURE': '🟠',
            'CORRECTION': '🔴',
            'MARKET_IN_CORRECTION': '🔴'
        }.get(market_phase, '⚪')
        
        # Format 5-day deltas
        spy_delta_str = f"{spy_5day_delta:+d}" if spy_5day_delta != 0 else "+0"
        qqq_delta_str = f"{qqq_5day_delta:+d}" if qqq_5day_delta != 0 else "+0"
        
        # Exposure recommendation based on IBD methodology
        max_d = max(spy_dist_days, qqq_dist_days)
        if max_d <= 4:
            exposure_str = "80-100%"
            exposure_desc = "Confirmed Uptrend"
        elif max_d <= 6:
            exposure_str = "60-80%"
            exposure_desc = "Uptrend Under Pressure"
        elif max_d <= 8:
            exposure_str = "40-60%"
            exposure_desc = "Elevated Caution"
        else:
            exposure_str = "20-40%"
            exposure_desc = "Market in Correction"
        
        # Build D-day histogram
        histogram_section = ""
        if spy_dday_positions is not None or qqq_dday_positions is not None:
            histogram_section = self._build_dday_histogram(
                spy_dday_positions, qqq_dday_positions,
                spy_dist_days, qqq_dist_days
            )
        
        # Build market phase section with rally details
        phase_display = market_phase.replace('_', ' ').title() if market_phase else 'Unknown'
        
        # Build the phase details
        phase_details = []
        if rally_day > 0:
            phase_details.append(f"Rally Attempt: Day {rally_day}")
            if rally_day >= 4:
                phase_details.append("Eligible for Follow-Through Day")
            else:
                phase_details.append(f"Day 4+ needed for FTD signal ({4 - rally_day} more day(s))")
        elif ftd_info:
            phase_details.append(ftd_info)
        
        phase_details_str = '\n'.join(phase_details) if phase_details else ""
        
        # Build rally visual
        rally_section = ""
        if rally_day > 0:
            rally_section = self._build_rally_visual(rally_day, rally_failed, successful_ftds)
        
        # Overnight futures section
        futures_section = ""
        if overnight_futures:
            es = overnight_futures.get('es_change', 0)
            nq = overnight_futures.get('nq_change', 0)
            ym = overnight_futures.get('ym_change', 0)
            
            def fut_emoji(val):
                if val > 0.25: return '🟢'
                elif val < -0.25: return '🔴'
                return '🟡'
            
            def fut_regime(val):
                if val > 0.25: return 'BULL'
                elif val < -0.25: return 'BEAR'
                return 'NEUTRAL'
            
            futures_section = f"""
📈 **OVERNIGHT FUTURES** (Since 6PM Globex Open)
```
┌─────────┬──────────┬──────────────┐
│ Symbol  │ Change   │ Regime       │
├─────────┼──────────┼──────────────┤
│ ES      │  {es:+.2f}%  │ {fut_emoji(es)} {fut_regime(es):8} │
│ NQ      │  {nq:+.2f}%  │ {fut_emoji(nq)} {fut_regime(nq):8} │
│ YM      │  {ym:+.2f}%  │ {fut_emoji(ym)} {fut_regime(ym):8} │
└─────────┴──────────┴──────────────┘
```"""
        
        # Build trend context
        trend_context = ""
        if prior_score is not None:
            trend_context = self._build_trend_context(score, prior_score, score_direction)
        
        # Build score bar (normalized to 1.5 max like your system)
        # Convert int score to float if needed, normalize to 0-1.5 scale
        score_float = float(score) if isinstance(score, int) else score
        if score_float > 10:  # Old int format (-50 to +50)
            score_float = (score_float + 50) / 100 * 1.5  # Convert to 0-1.5
        normalized = max(0, min(1, score_float / 1.5))
        filled = int(normalized * 20)
        score_bar = '▓' * filled + '░' * (20 - filled)
        
        # Format timestamp
        date_str = datetime.now().strftime('%A, %B %d, %Y • %I:%M %p ET')
        
        # Guidance
        guidance = self._get_regime_guidance(regime)
        
        message = f"""🌅 **MORNING MARKET REGIME ALERT**
*{date_str}*

📊 **DISTRIBUTION DAY COUNT** (Rolling 25-Day)
```
┌─────────┬───────┬─────────┬──────────────┐
│ Index   │ Count │ 5-Day Δ │ Trend        │
├─────────┼───────┼─────────┼──────────────┤
│ SPY     │   {spy_dist_days}   │   {spy_delta_str:3}   │ {trend_emoji} {dist_trend:10} │
│ QQQ     │   {qqq_dist_days}   │   {qqq_delta_str:3}   │ {trend_emoji} {dist_trend:10} │
└─────────┴───────┴─────────┴──────────────┘
```
{histogram_section}
🎯 **MARKET PHASE:** {phase_emoji} {phase_display}
{phase_details_str}
{rally_section}{futures_section}
{trend_context}
⚖️ **COMPOSITE MARKET REGIME SCORE**

Score: {score_float:+.2f} / 1.50

`{score_bar}` {regime_emoji} **{regime}**

💰 **IBD EXPOSURE:** {exposure_str} ({exposure_desc})

📋 **GUIDANCE:**
{guidance}
"""
        
        return self.send(content=message, channel=AlertChannel.MARKET.value)
    
    def send_distribution_day_alert(
        self,
        symbol: str,
        change_pct: float,
        volume_ratio: float,
        total_dist_days: int
    ) -> bool:
        """Send distribution day alert."""
        embed = {
            'title': f'⚠️ DISTRIBUTION DAY: {symbol}',
            'color': self.COLORS['red'],
            'fields': [
                {'name': 'Change', 'value': f'{change_pct:.2f}%', 'inline': True},
                {'name': 'Volume', 'value': f'{volume_ratio:.0%} of prev', 'inline': True},
                {'name': 'Total Dist Days', 'value': str(total_dist_days), 'inline': True},
            ],
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        return self.send(embed=embed, channel=AlertChannel.MARKET.value)
    
    def send_system_alert(
        self,
        title: str,
        message: str,
        level: str = 'info'
    ) -> bool:
        """Send system/status alert."""
        colors = {
            'info': self.COLORS['blue'],
            'warning': self.COLORS['yellow'],
            'error': self.COLORS['red'],
            'success': self.COLORS['green'],
        }
        
        embed = {
            'title': f'🔧 {title}',
            'description': message,
            'color': colors.get(level, self.COLORS['blue']),
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        return self.send(embed=embed, channel=AlertChannel.SYSTEM.value)


# Singleton instance
_notifier: Optional[DiscordNotifier] = None


def get_discord_notifier() -> DiscordNotifier:
    """Get the singleton Discord notifier instance."""
    global _notifier
    
    if _notifier is None:
        _notifier = DiscordNotifier()
    
    return _notifier


def init_discord_notifier(
    webhooks: Dict[str, str] = None,
    default_webhook: str = None,
    enabled: bool = True
) -> DiscordNotifier:
    """
    Initialize Discord notifier with webhooks.
    
    Args:
        webhooks: Dict mapping channel name to webhook URL
        default_webhook: Default webhook URL
        enabled: Whether notifications are enabled
        
    Returns:
        DiscordNotifier instance
    """
    global _notifier
    
    _notifier = DiscordNotifier(
        webhooks=webhooks,
        default_webhook=default_webhook,
        enabled=enabled
    )
    
    return _notifier
