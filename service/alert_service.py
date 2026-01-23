"""
CANSLIM Monitor - Alert Service
================================
Central service for alert generation, filtering, and routing.

Handles:
- Alert creation from various threads (breakout, position, market)
- Cooldown management to prevent duplicate alerts
- Discord routing based on alert type
- Alert persistence to database
- Suppression based on market regime

Version: 1.0
Created: January 15, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

from ..data.models import Alert, Position, MarketRegime


class AlertType(Enum):
    """Alert type categories."""
    # Entry signals
    BREAKOUT = "BREAKOUT"
    
    # Pyramid signals
    PYRAMID = "PYRAMID"
    ADD = "ADD"
    
    # Profit signals
    PROFIT = "PROFIT"
    
    # Stop/Sell signals
    STOP = "STOP"
    TECHNICAL = "TECHNICAL"
    
    # Health signals
    HEALTH = "HEALTH"
    
    # Market signals
    MARKET = "MARKET"
    
    # Alternative entry signals
    ALT_ENTRY = "ALT_ENTRY"


class AlertSubtype(Enum):
    """Alert subtypes within each category."""
    # Breakout subtypes
    CONFIRMED = "CONFIRMED"
    SUPPRESSED = "SUPPRESSED"
    IN_BUY_ZONE = "IN_BUY_ZONE"
    APPROACHING = "APPROACHING"
    EXTENDED = "EXTENDED"
    
    # Pyramid subtypes
    P1_READY = "P1_READY"
    P1_EXTENDED = "P1_EXTENDED"
    P2_READY = "P2_READY"
    P2_EXTENDED = "P2_EXTENDED"
    
    # Add subtypes
    PULLBACK = "PULLBACK"
    EMA_21 = "21_EMA"
    
    # Profit subtypes
    TP1 = "TP1"
    TP2 = "TP2"
    EIGHT_WEEK_HOLD = "8_WEEK_HOLD"
    
    # Stop subtypes
    HARD_STOP = "HARD_STOP"
    WARNING = "WARNING"
    TRAILING_STOP = "TRAILING_STOP"
    
    # Technical subtypes
    MA_50_WARNING = "50_MA_WARNING"
    MA_50_SELL = "50_MA_SELL"
    EMA_21_SELL = "21_EMA_SELL"
    TEN_WEEK_SELL = "10_WEEK_SELL"
    CLIMAX_TOP = "CLIMAX_TOP"
    
    # Health subtypes
    CRITICAL = "CRITICAL"
    EARNINGS = "EARNINGS"
    LATE_STAGE = "LATE_STAGE"
    
    # Market subtypes
    WEAK = "WEAK"
    FTD = "FTD"
    RALLY_ATTEMPT = "RALLY_ATTEMPT"
    CORRECTION = "CORRECTION"
    REGIME_CHANGE = "REGIME_CHANGE"
    
    # Alternative entry subtypes
    MA_BOUNCE = "MA_BOUNCE"
    PIVOT_RETEST = "PIVOT_RETEST"
    CONFLUENCE = "CONFLUENCE"
    SHAKEOUT_3 = "SHAKEOUT_3"
    THREE_WEEKS_TIGHT = "THREE_WEEKS_TIGHT"
    NEW_BASE = "NEW_BASE"


@dataclass
class AlertContext:
    """Context captured at alert time for ML learning."""
    # Price context
    current_price: float = 0.0
    pivot_price: float = 0.0
    avg_cost: float = 0.0
    pnl_pct: float = 0.0
    
    # Technical context
    ma_50: float = 0.0
    ma_21: float = 0.0
    ma_200: float = 0.0
    volume_ratio: float = 0.0
    
    # Scoring context
    grade: str = ""
    score: int = 0
    static_score: int = 0
    dynamic_score: int = 0
    
    # Health context
    health_score: int = 0
    health_rating: str = ""
    
    # Market context
    market_regime: str = ""
    spy_price: float = 0.0
    
    # Position sizing context
    shares_recommended: int = 0
    position_value: float = 0.0
    
    # Additional context
    state_at_alert: int = 0
    days_in_position: int = 0
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self))
    
    @classmethod
    def from_json(cls, json_str: str) -> 'AlertContext':
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls(**data)


@dataclass
class AlertData:
    """Complete alert data for generation."""
    # Identity
    symbol: str
    position_id: Optional[int] = None
    
    # Classification
    alert_type: AlertType = AlertType.BREAKOUT
    subtype: AlertSubtype = AlertSubtype.CONFIRMED
    
    # Context
    context: AlertContext = field(default_factory=AlertContext)
    
    # Message
    title: str = ""
    message: str = ""
    action: str = ""
    
    # Metadata
    thread_source: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    # Discord routing
    discord_channel: str = "breakout"  # breakout, position, market, system
    priority: str = "P1"  # P0 (immediate), P1 (normal), P2 (low)


class AlertService:
    """
    Central service for alert management.
    
    Responsibilities:
    - Create alerts from thread detections
    - Apply cooldown filters
    - Check market suppression rules
    - Route to Discord channels
    - Persist to database
    """
    
    # Discord channel mapping
    CHANNEL_MAPPING = {
        AlertType.BREAKOUT: "breakout",
        AlertType.PYRAMID: "position",
        AlertType.ADD: "position",
        AlertType.PROFIT: "position",
        AlertType.STOP: "position",
        AlertType.TECHNICAL: "position",
        AlertType.HEALTH: "position",
        AlertType.MARKET: "market",
        AlertType.ALT_ENTRY: "breakout",
    }
    
    # Priority mapping
    PRIORITY_MAPPING = {
        # P0: Immediate - capital protection
        (AlertType.STOP, AlertSubtype.HARD_STOP): "P0",
        (AlertType.HEALTH, AlertSubtype.CRITICAL): "P0",
        (AlertType.TECHNICAL, AlertSubtype.MA_50_SELL): "P0",
        (AlertType.MARKET, AlertSubtype.CORRECTION): "P0",
        
        # P1: Normal - actionable
        (AlertType.BREAKOUT, AlertSubtype.CONFIRMED): "P1",
        (AlertType.PYRAMID, AlertSubtype.P1_READY): "P1",
        (AlertType.PYRAMID, AlertSubtype.P2_READY): "P1",
        (AlertType.PROFIT, AlertSubtype.TP1): "P1",
        (AlertType.PROFIT, AlertSubtype.TP2): "P1",
        
        # P2: Informational
        (AlertType.BREAKOUT, AlertSubtype.APPROACHING): "P2",
        (AlertType.HEALTH, AlertSubtype.WARNING): "P2",
    }
    
    def __init__(
        self,
        db_session_factory=None,
        discord_notifier=None,
        cooldown_minutes: int = 60,
        enable_cooldown: bool = False,
        enable_suppression: bool = True,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize alert service.
        
        Args:
            db_session_factory: SQLAlchemy session factory
            discord_notifier: Discord notifier instance
            cooldown_minutes: Minutes between same alert for same symbol
            enable_cooldown: Enable cooldown filtering (False = all alerts pass through)
            enable_suppression: Enable market-based suppression
            logger: Logger instance
        """
        self.db_session_factory = db_session_factory
        self.discord_notifier = discord_notifier
        self.cooldown_minutes = cooldown_minutes
        self.enable_cooldown = enable_cooldown
        self.enable_suppression = enable_suppression
        self.logger = logger or logging.getLogger('canslim.alerts')
        
        # In-memory cooldown cache: {(symbol, type, subtype): last_alert_time}
        self._cooldown_cache: Dict[Tuple[str, str, str], datetime] = {}
    
    def create_alert(
        self,
        symbol: str,
        alert_type: AlertType,
        subtype: AlertSubtype,
        context: AlertContext,
        position_id: Optional[int] = None,
        message: str = "",
        action: str = "",
        thread_source: str = "",
        force: bool = False
    ) -> Optional[AlertData]:
        """
        Create and process an alert.
        
        Args:
            symbol: Stock symbol
            alert_type: Alert type category
            subtype: Alert subtype
            context: Alert context data
            position_id: Associated position ID
            message: Alert message body
            action: Recommended action
            thread_source: Source thread name
            force: Bypass cooldown checks
        
        Returns:
            AlertData if alert was created, None if filtered
        """
        # Save original subtype for cooldown tracking
        # (cooldown should be based on what was requested, not what it became after suppression)
        original_subtype = subtype
        
        # Check cooldown using original subtype
        if not force and self._is_on_cooldown(symbol, alert_type, original_subtype):
            self.logger.info(f"Alert BLOCKED by cooldown: {symbol} {alert_type.value}/{original_subtype.value}")
            return None
        
        # Check market suppression for entry alerts (breakouts)
        if (self.enable_suppression and 
            alert_type == AlertType.BREAKOUT and 
            subtype == AlertSubtype.CONFIRMED):
            if self._should_suppress_entry(context.market_regime):
                # Convert to SUPPRESSED
                subtype = AlertSubtype.SUPPRESSED
                self.logger.info(f"Entry suppressed by market regime: {symbol}")
        
        # Check market suppression for pyramid alerts
        # IBD Rule: Don't add to positions when market is in correction
        if (self.enable_suppression and 
            alert_type == AlertType.PYRAMID and 
            subtype in (AlertSubtype.P1_READY, AlertSubtype.P2_READY, AlertSubtype.PULLBACK)):
            if self._should_suppress_entry(context.market_regime):
                # Convert to SUPPRESSED - still log but mark as suppressed
                subtype = AlertSubtype.SUPPRESSED
                message = f"[MARKET SUPPRESSED - was {original_subtype.value}] {message}"
                self.logger.info(f"Pyramid suppressed by market regime: {symbol} ({original_subtype.value})")
        
        # Build alert data
        alert_data = AlertData(
            symbol=symbol,
            position_id=position_id,
            alert_type=alert_type,
            subtype=subtype,
            context=context,
            title=self._build_title(symbol, alert_type, subtype),
            message=message,
            action=action,
            thread_source=thread_source,
            discord_channel=self._get_channel(alert_type),
            priority=self._get_priority(alert_type, subtype)
        )
        
        # Update cooldown using ORIGINAL subtype (before any suppression)
        # This ensures repeated requests for CONFIRMED are properly throttled
        # even if they get converted to SUPPRESSED
        self._update_cooldown(symbol, alert_type, original_subtype)
        
        # Persist to database
        self._persist_alert(alert_data)
        
        # Send to Discord
        self._send_discord(alert_data)
        
        return alert_data
    
    def _is_on_cooldown(
        self,
        symbol: str,
        alert_type: AlertType,
        subtype: AlertSubtype
    ) -> bool:
        """
        Check if alert is on cooldown.
        
        Returns False (not on cooldown) if:
        - Cooldown is disabled (enable_cooldown=False)
        - No previous alert exists for this symbol/type/subtype
        - Cooldown period has expired
        """
        # If cooldown disabled, always pass through
        if not self.enable_cooldown:
            return False
        
        key = (symbol, alert_type.value, subtype.value)
        
        if key not in self._cooldown_cache:
            return False
        
        last_alert = self._cooldown_cache[key]
        cooldown_end = last_alert + timedelta(minutes=self.cooldown_minutes)
        
        return datetime.now() < cooldown_end
    
    def _update_cooldown(
        self,
        symbol: str,
        alert_type: AlertType,
        subtype: AlertSubtype
    ):
        """Update cooldown cache."""
        key = (symbol, alert_type.value, subtype.value)
        self._cooldown_cache[key] = datetime.now()
    
    def _should_suppress_entry(self, market_regime: str) -> bool:
        """
        Check if entry should be suppressed based on market regime.
        
        IBD Rule: "Don't fight the market. When in correction, stop entries."
        """
        if not market_regime:
            return False
        
        regime_upper = market_regime.upper()
        return regime_upper in ("CORRECTION", "BEARISH", "DOWNTREND")
    
    def _get_channel(self, alert_type: AlertType) -> str:
        """Get Discord channel for alert type."""
        return self.CHANNEL_MAPPING.get(alert_type, "system")
    
    def _get_priority(self, alert_type: AlertType, subtype: AlertSubtype) -> str:
        """Get priority for alert type/subtype combination."""
        return self.PRIORITY_MAPPING.get((alert_type, subtype), "P1")
    
    def _build_title(
        self,
        symbol: str,
        alert_type: AlertType,
        subtype: AlertSubtype
    ) -> str:
        """Build alert title."""
        emoji = self._get_emoji(alert_type, subtype)
        return f"{emoji} {symbol} - {alert_type.value} {subtype.value}"
    
    def _get_emoji(self, alert_type: AlertType, subtype: AlertSubtype) -> str:
        """Get emoji for alert type."""
        emoji_map = {
            AlertType.BREAKOUT: "🚀",
            AlertType.PYRAMID: "📈",
            AlertType.ADD: "➕",
            AlertType.PROFIT: "💰",
            AlertType.STOP: "🛑",
            AlertType.TECHNICAL: "📉",
            AlertType.HEALTH: "⚠️",
            AlertType.MARKET: "📊",
            AlertType.ALT_ENTRY: "🔄",
        }
        
        # Override for specific subtypes
        if subtype == AlertSubtype.CRITICAL:
            return "🚨"
        if subtype == AlertSubtype.HARD_STOP:
            return "🛑"
        if subtype == AlertSubtype.SUPPRESSED:
            return "⏸️"
        
        return emoji_map.get(alert_type, "📢")
    
    def _persist_alert(self, alert_data: AlertData):
        """Save alert to database."""
        if not self.db_session_factory:
            return
        
        try:
            session = self.db_session_factory()
            try:
                alert = Alert(
                    symbol=alert_data.symbol,
                    position_id=alert_data.position_id,
                    alert_time=alert_data.created_at,
                    alert_type=alert_data.alert_type.value,
                    alert_subtype=alert_data.subtype.value,
                    price=alert_data.context.current_price,
                    message=alert_data.message,  # Full formatted message
                    action=alert_data.action,    # Recommended action
                    state_at_alert=alert_data.context.state_at_alert,
                    pivot_at_alert=alert_data.context.pivot_price,
                    avg_cost_at_alert=alert_data.context.avg_cost,
                    pnl_pct_at_alert=alert_data.context.pnl_pct,
                    ma50=alert_data.context.ma_50,
                    ma21=alert_data.context.ma_21,
                    volume_ratio=alert_data.context.volume_ratio,
                    health_score=alert_data.context.health_score,
                    health_rating=alert_data.context.health_rating,
                    market_regime=alert_data.context.market_regime,
                    spy_price=alert_data.context.spy_price,
                    canslim_grade=alert_data.context.grade,
                    canslim_score=alert_data.context.score,
                    static_score=alert_data.context.static_score,
                    dynamic_score=alert_data.context.dynamic_score,
                    discord_channel=alert_data.discord_channel,
                )
                session.add(alert)
                session.commit()
                
                # Update alert_data with ID
                alert_data.position_id = alert.id
                
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error(f"Failed to persist alert: {e}")
    
    def _send_discord(self, alert_data: AlertData):
        """Send alert to Discord."""
        if not self.discord_notifier:
            self.logger.warning(f"Discord notifier not configured - cannot send alert for {alert_data.symbol}")
            return
        
        try:
            message = alert_data.message or ""
            channel = alert_data.discord_channel
            
            self.logger.debug(f"Attempting Discord send: {alert_data.symbol} to channel={channel}, message_len={len(message)}")
            
            # Check if message is an embed (starts with EMBED: prefix)
            if message.strip().startswith("EMBED:"):
                # Parse embed JSON and send as rich embed
                embed_json = message.strip()[6:]  # Remove "EMBED:" prefix
                embed = json.loads(embed_json)
                
                self.logger.debug(f"Sending embed to Discord: title={embed.get('title', 'N/A')}")
                
                # Send via notifier with embed
                success = self.discord_notifier.send(
                    embed=embed,
                    channel=channel,
                    username='CANSLIM Monitor'
                )
                
                if success:
                    self.logger.info(f"Discord embed sent: {alert_data.symbol} - {alert_data.subtype.value}")
                else:
                    self.logger.error(f"Discord embed failed to send: {alert_data.symbol}")
            else:
                # Legacy format - format as plain text
                formatted_message = self._format_discord_message(alert_data)
                
                self.logger.debug(f"Sending plain text to Discord: {len(formatted_message)} chars")
                
                # Send via notifier as plain text
                success = self.discord_notifier.send_alert(
                    message=formatted_message,
                    channel=channel,
                    alert_type=alert_data.alert_type.value,
                    priority=alert_data.priority
                )
                
                if success:
                    self.logger.info(f"Discord alert sent: {alert_data.title}")
                else:
                    self.logger.error(f"Discord alert failed to send: {alert_data.title}")
            
        except Exception as e:
            self.logger.error(f"Failed to send Discord alert: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
    
    def _format_discord_message(self, alert_data: AlertData) -> str:
        """
        Format alert for Discord.
        
        If the message is already in card format (starts with ```), 
        just add timestamp and pass through to avoid duplication.
        """
        ctx = alert_data.context
        message = alert_data.message or ""
        
        # Check if message is already in card format (compact card style)
        # Card format starts with ``` for code block
        is_card_format = message.strip().startswith("```")
        
        if is_card_format:
            # Card already contains all info - just add timestamp
            return f"{message}\nTime: {alert_data.created_at.strftime('%H:%M:%S ET')}"
        
        # Legacy format - build full message with context
        lines = [
            alert_data.title,
            "",
            message,
        ]
        
        # Add price context
        if ctx.current_price > 0:
            lines.append(f"Price: ${ctx.current_price:.2f}")
        
        if ctx.pivot_price > 0:
            pct_from_pivot = ((ctx.current_price - ctx.pivot_price) / ctx.pivot_price * 100)
            lines.append(f"Pivot: ${ctx.pivot_price:.2f} ({pct_from_pivot:+.1f}%)")
        
        # Add scoring context for breakout alerts
        if alert_data.alert_type == AlertType.BREAKOUT and ctx.grade:
            lines.extend([
                "",
                f"Grade: {ctx.grade} (Score: {ctx.score})"
            ])
        
        # Add action
        if alert_data.action:
            lines.extend([
                "",
                alert_data.action
            ])
        
        # Add market context
        if ctx.market_regime:
            lines.extend([
                "",
                f"Market: {ctx.market_regime}"
            ])
        
        # Add timestamp
        lines.extend([
            "",
            f"Time: {alert_data.created_at.strftime('%H:%M:%S ET')}"
        ])
        
        return "\n".join(lines)
    
    def get_recent_alerts(
        self,
        symbol: Optional[str] = None,
        alert_type: Optional[AlertType] = None,
        hours: int = 24,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get recent alerts from database.
        
        Args:
            symbol: Filter by symbol
            alert_type: Filter by type
            hours: Look back period
            limit: Max results
        
        Returns:
            List of alert dictionaries
        """
        if not self.db_session_factory:
            return []
        
        try:
            session = self.db_session_factory()
            try:
                query = session.query(Alert)
                
                # Apply filters
                cutoff = datetime.now() - timedelta(hours=hours)
                query = query.filter(Alert.alert_time >= cutoff)
                
                if symbol:
                    query = query.filter(Alert.symbol == symbol)
                if alert_type:
                    query = query.filter(Alert.alert_type == alert_type.value)
                
                # Order and limit
                query = query.order_by(Alert.alert_time.desc()).limit(limit)
                
                return [self._alert_to_dict(a) for a in query.all()]
                
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error(f"Failed to get recent alerts: {e}")
            return []
    
    def _alert_to_dict(self, alert: Alert) -> Dict[str, Any]:
        """Convert Alert model to dictionary."""
        return {
            'id': alert.id,
            'symbol': alert.symbol,
            'position_id': alert.position_id,
            'alert_type': alert.alert_type,
            'subtype': alert.alert_subtype,
            'alert_time': alert.alert_time.isoformat() if alert.alert_time else None,
            'price': alert.price,
            # Full message content
            'message': alert.message,
            'action': alert.action,
            # Context at alert time
            'pivot_at_alert': alert.pivot_at_alert,
            'avg_cost_at_alert': alert.avg_cost_at_alert,
            'pnl_pct_at_alert': alert.pnl_pct_at_alert,
            'state_at_alert': alert.state_at_alert,
            # Technical context
            'ma50': alert.ma50,
            'ma21': alert.ma21,
            'ma200': alert.ma200,
            'volume_ratio': alert.volume_ratio,
            # Health context
            'health_score': alert.health_score,
            'health_rating': alert.health_rating,
            # Scoring
            'grade': alert.canslim_grade,
            'score': alert.canslim_score,
            'static_score': alert.static_score,
            'dynamic_score': alert.dynamic_score,
            # Market context
            'market_regime': alert.market_regime,
            'spy_price': alert.spy_price,
            # Delivery status
            'discord_sent': alert.discord_sent,
            'discord_channel': alert.discord_channel,
            # UI helpers
            'severity': self.get_alert_severity(alert.alert_type, alert.alert_subtype),
            'acknowledged': alert.acknowledged or False,
            'acknowledged_at': alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        }
    
    # Alert severity levels for color coding
    SEVERITY_CRITICAL = "critical"   # Red - immediate action required
    SEVERITY_WARNING = "warning"     # Yellow/Orange - attention needed
    SEVERITY_PROFIT = "profit"       # Green - profit opportunity
    SEVERITY_INFO = "info"           # Blue - informational
    SEVERITY_NEUTRAL = "neutral"     # Gray - no action needed
    
    # Severity mapping by (type, subtype)
    SEVERITY_MAPPING = {
        # Critical (Red) - Sell signals, stops
        ("STOP", "HARD_STOP"): "critical",
        ("STOP", "TRAILING_STOP"): "critical",
        ("TECHNICAL", "50_MA_SELL"): "critical",
        ("TECHNICAL", "21_EMA_SELL"): "critical",
        ("TECHNICAL", "10_WEEK_SELL"): "critical",
        ("TECHNICAL", "CLIMAX_TOP"): "critical",
        ("HEALTH", "CRITICAL"): "critical",
        
        # Warning (Orange/Yellow) - Attention needed
        ("STOP", "WARNING"): "warning",
        ("TECHNICAL", "50_MA_WARNING"): "warning",
        ("HEALTH", "EXTENDED"): "warning",
        ("HEALTH", "EARNINGS"): "warning",
        ("HEALTH", "LATE_STAGE"): "warning",
        ("BREAKOUT", "EXTENDED"): "warning",
        ("BREAKOUT", "SUPPRESSED"): "warning",
        ("PYRAMID", "P1_EXTENDED"): "warning",
        ("PYRAMID", "P2_EXTENDED"): "warning",
        
        # Profit (Green) - Profit targets
        ("PROFIT", "TP1"): "profit",
        ("PROFIT", "TP2"): "profit",
        ("PROFIT", "8_WEEK_HOLD"): "profit",
        
        # Info (Blue) - Entry/Pyramid opportunities
        ("BREAKOUT", "CONFIRMED"): "info",
        ("BREAKOUT", "IN_BUY_ZONE"): "info",
        ("BREAKOUT", "APPROACHING"): "info",
        ("PYRAMID", "P1_READY"): "info",
        ("PYRAMID", "P2_READY"): "info",
        ("ADD", "PULLBACK"): "info",
        ("ADD", "21_EMA"): "info",
        ("ALT_ENTRY", "MA_BOUNCE"): "info",
        ("ALT_ENTRY", "PIVOT_RETEST"): "info",
    }
    
    @classmethod
    def get_alert_severity(cls, alert_type: str, subtype: str) -> str:
        """
        Get severity level for an alert type/subtype combination.
        
        Args:
            alert_type: Alert type string (e.g., "STOP", "PROFIT")
            subtype: Alert subtype string (e.g., "HARD_STOP", "TP1")
        
        Returns:
            Severity string: "critical", "warning", "profit", "info", "neutral"
        """
        key = (alert_type, subtype)
        return cls.SEVERITY_MAPPING.get(key, "neutral")
    
    @classmethod
    def get_severity_color(cls, severity: str) -> str:
        """
        Get hex color for a severity level.
        
        Args:
            severity: Severity string from get_alert_severity()
        
        Returns:
            Hex color code
        """
        colors = {
            "critical": "#DC3545",  # Red
            "warning": "#FFC107",   # Yellow/Amber
            "profit": "#28A745",    # Green
            "info": "#17A2B8",      # Blue
            "neutral": "#6C757D",   # Gray
        }
        return colors.get(severity, "#6C757D")
    
    @classmethod
    def get_severity_emoji(cls, severity: str) -> str:
        """Get emoji for severity level."""
        emojis = {
            "critical": "🔴",
            "warning": "🟡",
            "profit": "🟢",
            "info": "🔵",
            "neutral": "⚪",
        }
        return emojis.get(severity, "⚪")
    
    def get_latest_alert_for_position(self, position_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the most recent alert for a specific position.
        
        Args:
            position_id: Position ID to query
        
        Returns:
            Alert dictionary or None
        """
        if not self.db_session_factory:
            return None
        
        try:
            session = self.db_session_factory()
            try:
                alert = (
                    session.query(Alert)
                    .filter(Alert.position_id == position_id)
                    .order_by(Alert.alert_time.desc())
                    .first()
                )
                
                if alert:
                    return self._alert_to_dict(alert)
                return None
                
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error(f"Failed to get latest alert for position {position_id}: {e}")
            return None
    
    def get_latest_alerts_for_positions(self, position_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Get the most recent alert for multiple positions in one query.
        
        Args:
            position_ids: List of position IDs
        
        Returns:
            Dictionary mapping position_id -> alert_dict
        """
        if not self.db_session_factory or not position_ids:
            return {}
        
        try:
            session = self.db_session_factory()
            try:
                from sqlalchemy import func
                
                # Subquery to get max alert_time per position
                subq = (
                    session.query(
                        Alert.position_id,
                        func.max(Alert.alert_time).label('max_time')
                    )
                    .filter(Alert.position_id.in_(position_ids))
                    .group_by(Alert.position_id)
                    .subquery()
                )
                
                # Join to get the full alert records
                alerts = (
                    session.query(Alert)
                    .join(
                        subq,
                        (Alert.position_id == subq.c.position_id) &
                        (Alert.alert_time == subq.c.max_time)
                    )
                    .all()
                )
                
                return {
                    alert.position_id: self._alert_to_dict(alert)
                    for alert in alerts
                }
                
            finally:
                session.close()
                
        except Exception as e:
            self.logger.error(f"Failed to get latest alerts for positions: {e}")
            return {}
    
    def acknowledge_alert(self, alert_id: int) -> bool:
        """
        Mark a single alert as acknowledged.
        
        Args:
            alert_id: ID of the alert to acknowledge
            
        Returns:
            True if successful, False otherwise
        """
        if not self.db_session_factory:
            return False
        
        try:
            session = self.db_session_factory()
            try:
                alert = session.query(Alert).filter(Alert.id == alert_id).first()
                if alert:
                    alert.acknowledged = True
                    alert.acknowledged_at = datetime.now()
                    session.commit()
                    self.logger.debug(f"Acknowledged alert {alert_id}")
                    return True
                return False
            finally:
                session.close()
        except Exception as e:
            self.logger.error(f"Failed to acknowledge alert {alert_id}: {e}")
            return False
    
    def acknowledge_alerts_for_position(self, position_id: int) -> int:
        """
        Mark all unacknowledged alerts for a position as acknowledged.
        
        Args:
            position_id: Position ID
            
        Returns:
            Number of alerts acknowledged
        """
        if not self.db_session_factory:
            return 0
        
        try:
            session = self.db_session_factory()
            try:
                count = (
                    session.query(Alert)
                    .filter(Alert.position_id == position_id)
                    .filter(Alert.acknowledged == False)
                    .update({
                        'acknowledged': True,
                        'acknowledged_at': datetime.now()
                    })
                )
                session.commit()
                self.logger.debug(f"Acknowledged {count} alerts for position {position_id}")
                return count
            finally:
                session.close()
        except Exception as e:
            self.logger.error(f"Failed to acknowledge alerts for position {position_id}: {e}")
            return 0
    
    def acknowledge_all_alerts(self) -> int:
        """
        Mark all unacknowledged alerts as acknowledged.
        
        Returns:
            Number of alerts acknowledged
        """
        if not self.db_session_factory:
            return 0
        
        try:
            session = self.db_session_factory()
            try:
                count = (
                    session.query(Alert)
                    .filter(Alert.acknowledged == False)
                    .update({
                        'acknowledged': True,
                        'acknowledged_at': datetime.now()
                    })
                )
                session.commit()
                self.logger.info(f"Acknowledged all {count} alerts")
                return count
            finally:
                session.close()
        except Exception as e:
            self.logger.error(f"Failed to acknowledge all alerts: {e}")
            return 0
    
    def auto_acknowledge_old_alerts(self, hours: int = 24) -> int:
        """
        Auto-acknowledge alerts older than specified hours.
        
        Args:
            hours: Age threshold in hours (default 24)
            
        Returns:
            Number of alerts auto-acknowledged
        """
        if not self.db_session_factory:
            return 0
        
        try:
            session = self.db_session_factory()
            try:
                cutoff = datetime.now() - timedelta(hours=hours)
                count = (
                    session.query(Alert)
                    .filter(Alert.acknowledged == False)
                    .filter(Alert.alert_time < cutoff)
                    .update({
                        'acknowledged': True,
                        'acknowledged_at': datetime.now()
                    })
                )
                session.commit()
                if count > 0:
                    self.logger.info(f"Auto-acknowledged {count} alerts older than {hours}h")
                return count
            finally:
                session.close()
        except Exception as e:
            self.logger.error(f"Failed to auto-acknowledge old alerts: {e}")
            return 0
    
    def get_unacknowledged_count(self, position_id: int = None) -> int:
        """
        Get count of unacknowledged alerts.
        
        Args:
            position_id: Optional position ID to filter by
            
        Returns:
            Number of unacknowledged alerts
        """
        if not self.db_session_factory:
            return 0
        
        try:
            session = self.db_session_factory()
            try:
                query = session.query(Alert).filter(Alert.acknowledged == False)
                if position_id:
                    query = query.filter(Alert.position_id == position_id)
                return query.count()
            finally:
                session.close()
        except Exception as e:
            self.logger.error(f"Failed to get unacknowledged count: {e}")
            return 0
    
    def clear_cooldown(self, symbol: str = None):
        """
        Clear cooldown cache.
        
        Args:
            symbol: Clear for specific symbol, or all if None
        """
        if symbol:
            keys_to_remove = [k for k in self._cooldown_cache if k[0] == symbol]
            for key in keys_to_remove:
                del self._cooldown_cache[key]
        else:
            self._cooldown_cache.clear()


# =============================================================================
# STANDALONE TESTING
# =============================================================================

def main():
    """Test the alert service."""
    print("=" * 60)
    print("ALERT SERVICE TEST")
    print("=" * 60)
    
    # Test 1: Cooldown DISABLED (default) - all alerts pass through
    print("\n--- Test 1: Cooldown DISABLED (default) ---")
    service_no_cooldown = AlertService(cooldown_minutes=5, enable_cooldown=False)
    
    context = AlertContext(
        current_price=52.50,
        pivot_price=50.00,
        grade="A",
        score=18,
        volume_ratio=2.3,
        market_regime="CONFIRMED_UPTREND"
    )
    
    alert1 = service_no_cooldown.create_alert(
        symbol="NVDA",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="First NVDA breakout alert",
        thread_source="test"
    )
    print(f"First alert created: {alert1 is not None}")  # Should be True
    
    alert2 = service_no_cooldown.create_alert(
        symbol="NVDA",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="Second NVDA breakout alert (same type)",
        thread_source="test"
    )
    print(f"Second alert created (cooldown disabled): {alert2 is not None}")  # Should be True
    
    # Test 2: Cooldown ENABLED - duplicate alerts filtered
    print("\n--- Test 2: Cooldown ENABLED ---")
    service_with_cooldown = AlertService(cooldown_minutes=5, enable_cooldown=True)
    
    alert3 = service_with_cooldown.create_alert(
        symbol="AMD",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="First AMD breakout alert",
        thread_source="test"
    )
    print(f"First alert created: {alert3 is not None}")  # Should be True
    
    alert4 = service_with_cooldown.create_alert(
        symbol="AMD",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="Second AMD breakout alert (should be filtered)",
        thread_source="test"
    )
    print(f"Second alert created (cooldown enabled): {alert4 is not None}")  # Should be False
    
    # Different symbol should still work
    alert5 = service_with_cooldown.create_alert(
        symbol="MSFT",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="MSFT breakout (different symbol)",
        thread_source="test"
    )
    print(f"Different symbol alert: {alert5 is not None}")  # Should be True
    
    # Test 3: Market suppression (unchanged)
    print("\n--- Test 3: Market Suppression ---")
    context.market_regime = "CORRECTION"
    alert6 = service_with_cooldown.create_alert(
        symbol="TSLA",
        alert_type=AlertType.BREAKOUT,
        subtype=AlertSubtype.CONFIRMED,
        context=context,
        message="TSLA breakout during correction"
    )
    if alert6:
        print(f"Subtype after suppression: {alert6.subtype.value}")  # Should be SUPPRESSED
    
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  enable_cooldown=False: All alerts pass through")
    print(f"  enable_cooldown=True:  Duplicate alerts filtered")
    print("=" * 60)


if __name__ == "__main__":
    main()
