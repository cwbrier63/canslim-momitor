"""
CANSLIM Monitor - Alert Repository
Phase 1: Database Foundation

Provides CRUD operations and queries for Alert entities.
"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import and_, or_, func, desc
from sqlalchemy.orm import Session

from canslim_monitor.data.models import Alert


class AlertRepository:
    """Repository for Alert entity operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== CREATE ====================
    
    def create(self, **kwargs) -> Alert:
        """
        Create a new alert.
        
        Args:
            **kwargs: Alert attributes
        
        Returns:
            Created Alert instance
        """
        alert = Alert(**kwargs)
        self.session.add(alert)
        self.session.flush()
        return alert
    
    def create_breakout_alert(
        self,
        symbol: str,
        price: float,
        pivot: float,
        position_id: int = None,
        grade: str = None,
        score: int = None,
        static_score: int = None,
        dynamic_score: int = None,
        volume_ratio: float = None,
        market_regime: str = None,
        exec_verdict: str = None,
        adv: float = None,
        spread_pct: float = None,
        score_details: str = None,
        **kwargs
    ) -> Alert:
        """
        Create a breakout alert with all relevant context.
        
        Args:
            symbol: Stock ticker
            price: Current price
            pivot: Pivot price
            position_id: Related position ID
            grade: CANSLIM grade (A+, A, B, C)
            score: Total CANSLIM score
            static_score: Static component score
            dynamic_score: Dynamic component score
            volume_ratio: Current volume / average volume
            market_regime: Market regime at alert time
            exec_verdict: Execution risk verdict
            adv: Average daily volume
            spread_pct: Bid-ask spread percentage
            score_details: JSON details
            **kwargs: Additional alert attributes
        
        Returns:
            Created Alert instance
        """
        return self.create(
            symbol=symbol.upper(),
            position_id=position_id,
            alert_time=datetime.now(),
            alert_type='BREAKOUT',
            alert_subtype='CONFIRMED',
            price=price,
            pivot_at_alert=pivot,
            state_at_alert=0,
            canslim_grade=grade,
            canslim_score=score,
            static_score=static_score,
            dynamic_score=dynamic_score,
            volume_ratio=volume_ratio,
            market_regime=market_regime,
            exec_verdict=exec_verdict,
            adv=adv,
            spread_pct=spread_pct,
            score_details=score_details,
            **kwargs
        )
    
    def create_position_alert(
        self,
        symbol: str,
        alert_type: str,
        alert_subtype: str,
        price: float,
        position_id: int,
        state: int,
        avg_cost: float = None,
        pnl_pct: float = None,
        health_score: int = None,
        health_rating: str = None,
        **kwargs
    ) -> Alert:
        """
        Create a position-related alert (pyramid, stop, health, etc.).
        
        Args:
            symbol: Stock ticker
            alert_type: Type of alert (PYRAMID, STOP, HEALTH, etc.)
            alert_subtype: Subtype (PY1_READY, STOP_WARNING, etc.)
            price: Current price
            position_id: Related position ID
            state: Position state at alert time
            avg_cost: Average cost at alert time
            pnl_pct: P&L percentage at alert time
            health_score: Position health score
            health_rating: Position health rating
            **kwargs: Additional alert attributes
        
        Returns:
            Created Alert instance
        """
        return self.create(
            symbol=symbol.upper(),
            position_id=position_id,
            alert_time=datetime.now(),
            alert_type=alert_type,
            alert_subtype=alert_subtype,
            price=price,
            state_at_alert=state,
            avg_cost_at_alert=avg_cost,
            pnl_pct_at_alert=pnl_pct,
            health_score=health_score,
            health_rating=health_rating,
            **kwargs
        )
    
    # ==================== READ ====================
    
    def get_by_id(self, alert_id: int) -> Optional[Alert]:
        """Get alert by ID."""
        return self.session.query(Alert).filter_by(id=alert_id).first()
    
    def get_recent(
        self,
        limit: int = 50,
        alert_type: str = None,
        symbol: str = None
    ) -> List[Alert]:
        """
        Get recent alerts.
        
        Args:
            limit: Maximum number of alerts
            alert_type: Filter by alert type
            symbol: Filter by symbol
        
        Returns:
            List of Alert instances (newest first)
        """
        query = self.session.query(Alert)
        
        if alert_type:
            query = query.filter(Alert.alert_type == alert_type)
        if symbol:
            query = query.filter(Alert.symbol == symbol.upper())
        
        return query.order_by(desc(Alert.alert_time)).limit(limit).all()
    
    def get_by_symbol(
        self,
        symbol: str,
        limit: int = None,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> List[Alert]:
        """
        Get alerts for a specific symbol.
        
        Args:
            symbol: Stock ticker
            limit: Maximum number of alerts
            start_date: Filter by start date
            end_date: Filter by end date
        
        Returns:
            List of Alert instances (newest first)
        """
        query = self.session.query(Alert).filter(
            Alert.symbol == symbol.upper()
        )
        
        if start_date:
            query = query.filter(Alert.alert_time >= start_date)
        if end_date:
            query = query.filter(Alert.alert_time <= end_date)
        
        query = query.order_by(desc(Alert.alert_time))
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def get_by_position(self, position_id: int) -> List[Alert]:
        """Get all alerts for a position."""
        return self.session.query(Alert).filter(
            Alert.position_id == position_id
        ).order_by(desc(Alert.alert_time)).all()
    
    def get_by_type(
        self,
        alert_type: str,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = None
    ) -> List[Alert]:
        """
        Get alerts by type.
        
        Args:
            alert_type: Alert type (BREAKOUT, PYRAMID, STOP, etc.)
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum number of alerts
        
        Returns:
            List of Alert instances
        """
        query = self.session.query(Alert).filter(Alert.alert_type == alert_type)
        
        if start_date:
            query = query.filter(Alert.alert_time >= start_date)
        if end_date:
            query = query.filter(Alert.alert_time <= end_date)
        
        query = query.order_by(desc(Alert.alert_time))
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def get_unsent(self) -> List[Alert]:
        """Get alerts that haven't been sent to Discord."""
        return self.session.query(Alert).filter(
            Alert.discord_sent == False
        ).order_by(Alert.alert_time).all()
    
    def get_today(self, alert_type: str = None) -> List[Alert]:
        """Get today's alerts."""
        today = date.today()
        start = datetime.combine(today, datetime.min.time())
        end = datetime.combine(today, datetime.max.time())
        
        query = self.session.query(Alert).filter(
            Alert.alert_time >= start,
            Alert.alert_time <= end
        )
        
        if alert_type:
            query = query.filter(Alert.alert_type == alert_type)
        
        return query.order_by(desc(Alert.alert_time)).all()
    
    def get_last_alert(
        self,
        symbol: str,
        alert_type: str = None,
        alert_subtype: str = None
    ) -> Optional[Alert]:
        """
        Get the most recent alert for a symbol.
        
        Args:
            symbol: Stock ticker
            alert_type: Filter by alert type
            alert_subtype: Filter by alert subtype
        
        Returns:
            Most recent Alert or None
        """
        query = self.session.query(Alert).filter(
            Alert.symbol == symbol.upper()
        )
        
        if alert_type:
            query = query.filter(Alert.alert_type == alert_type)
        if alert_subtype:
            query = query.filter(Alert.alert_subtype == alert_subtype)
        
        return query.order_by(desc(Alert.alert_time)).first()
    
    def check_cooldown(
        self,
        symbol: str,
        alert_type: str,
        cooldown_minutes: int = 60
    ) -> bool:
        """
        Check if an alert is within cooldown period.
        
        Args:
            symbol: Stock ticker
            alert_type: Alert type
            cooldown_minutes: Cooldown period in minutes
        
        Returns:
            True if in cooldown (should not alert), False otherwise
        """
        cutoff = datetime.now() - timedelta(minutes=cooldown_minutes)
        
        exists = self.session.query(Alert).filter(
            Alert.symbol == symbol.upper(),
            Alert.alert_type == alert_type,
            Alert.alert_time >= cutoff
        ).first()
        
        return exists is not None
    
    def count(
        self,
        alert_type: str = None,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> int:
        """Count alerts with optional filters."""
        query = self.session.query(func.count(Alert.id))
        
        if alert_type:
            query = query.filter(Alert.alert_type == alert_type)
        if start_date:
            query = query.filter(Alert.alert_time >= start_date)
        if end_date:
            query = query.filter(Alert.alert_time <= end_date)
        
        return query.scalar()
    
    def get_stats_by_date(
        self,
        start_date: date = None,
        end_date: date = None
    ) -> List[Dict[str, Any]]:
        """
        Get alert statistics grouped by date.
        
        Args:
            start_date: Start date (defaults to 30 days ago)
            end_date: End date (defaults to today)
        
        Returns:
            List of dicts with date and counts by type
        """
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()
        
        results = self.session.query(
            func.date(Alert.alert_time).label('date'),
            Alert.alert_type,
            func.count(Alert.id).label('count')
        ).filter(
            func.date(Alert.alert_time) >= start_date,
            func.date(Alert.alert_time) <= end_date
        ).group_by(
            func.date(Alert.alert_time),
            Alert.alert_type
        ).all()
        
        # Restructure into date-keyed dicts
        stats = {}
        for row in results:
            d = str(row.date)
            if d not in stats:
                stats[d] = {'date': d}
            stats[d][row.alert_type] = row.count
        
        return list(stats.values())
    
    # ==================== UPDATE ====================
    
    def update(self, alert: Alert, **kwargs) -> Alert:
        """Update alert attributes."""
        for key, value in kwargs.items():
            if hasattr(alert, key):
                setattr(alert, key, value)
        
        self.session.flush()
        return alert
    
    def mark_sent(
        self,
        alert: Alert,
        channel: str = None,
        message_id: str = None
    ) -> Alert:
        """Mark alert as sent to Discord."""
        alert.discord_sent = True
        alert.discord_sent_at = datetime.now()
        
        if channel:
            alert.discord_channel = channel
        if message_id:
            alert.discord_message_id = message_id
        
        self.session.flush()
        return alert
    
    def log_user_action(
        self,
        alert: Alert,
        action: str
    ) -> Alert:
        """
        Log user response to an alert.
        
        Args:
            alert: Alert instance
            action: User action (TRADED, PASSED, IGNORED)
        
        Returns:
            Updated Alert instance
        """
        alert.user_action = action
        alert.user_action_time = datetime.now()
        self.session.flush()
        return alert
    
    # ==================== DELETE ====================
    
    def delete(self, alert: Alert) -> None:
        """Delete an alert."""
        self.session.delete(alert)
        self.session.flush()
    
    def delete_by_id(self, alert_id: int) -> bool:
        """Delete alert by ID."""
        alert = self.get_by_id(alert_id)
        if alert:
            self.delete(alert)
            return True
        return False
    
    def delete_old(self, days: int = 90) -> int:
        """
        Delete alerts older than specified days.
        
        Args:
            days: Age threshold in days
        
        Returns:
            Number of alerts deleted
        """
        cutoff = datetime.now() - timedelta(days=days)
        
        deleted = self.session.query(Alert).filter(
            Alert.alert_time < cutoff
        ).delete(synchronize_session=False)
        
        self.session.flush()
        return deleted
    
    # ==================== ANALYTICS ====================
    
    def get_breakout_success_rate(
        self,
        start_date: date = None,
        end_date: date = None,
        min_grade: str = None
    ) -> Dict[str, Any]:
        """
        Calculate breakout alert success rate.
        
        Args:
            start_date: Start date for analysis
            end_date: End date for analysis
            min_grade: Minimum grade filter
        
        Returns:
            Dict with success statistics
        """
        query = self.session.query(Alert).filter(
            Alert.alert_type == 'BREAKOUT',
            Alert.user_action.isnot(None)
        )
        
        if start_date:
            query = query.filter(func.date(Alert.alert_time) >= start_date)
        if end_date:
            query = query.filter(func.date(Alert.alert_time) <= end_date)
        
        alerts = query.all()
        
        if not alerts:
            return {'total': 0, 'traded': 0, 'passed': 0, 'trade_rate': 0}
        
        total = len(alerts)
        traded = sum(1 for a in alerts if a.user_action == 'TRADED')
        passed = sum(1 for a in alerts if a.user_action == 'PASSED')
        
        return {
            'total': total,
            'traded': traded,
            'passed': passed,
            'ignored': total - traded - passed,
            'trade_rate': traded / total if total > 0 else 0
        }
    
    def get_grade_distribution(
        self,
        alert_type: str = 'BREAKOUT',
        start_date: date = None,
        end_date: date = None
    ) -> Dict[str, int]:
        """Get distribution of alerts by grade."""
        query = self.session.query(
            Alert.canslim_grade,
            func.count(Alert.id).label('count')
        ).filter(
            Alert.alert_type == alert_type,
            Alert.canslim_grade.isnot(None)
        )
        
        if start_date:
            query = query.filter(func.date(Alert.alert_time) >= start_date)
        if end_date:
            query = query.filter(func.date(Alert.alert_time) <= end_date)
        
        results = query.group_by(Alert.canslim_grade).all()
        
        return {row.canslim_grade: row.count for row in results}
