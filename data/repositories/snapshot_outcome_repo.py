"""
CANSLIM Monitor - Snapshot and Outcome Repositories
Phase 1: Database Foundation

Provides CRUD operations for DailySnapshot and Outcome entities.
"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import and_, or_, func, desc
from sqlalchemy.orm import Session

from canslim_monitor.data.models import DailySnapshot, Outcome


class SnapshotRepository:
    """Repository for DailySnapshot entity operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== CREATE ====================
    
    def create(self, **kwargs) -> DailySnapshot:
        """Create a new daily snapshot."""
        snapshot = DailySnapshot(**kwargs)
        self.session.add(snapshot)
        self.session.flush()
        return snapshot
    
    def create_snapshot(
        self,
        position_id: int,
        symbol: str,
        snapshot_date: date,
        ohlcv: Dict[str, Any],
        position_metrics: Dict[str, Any] = None,
        technicals: Dict[str, Any] = None,
        **kwargs
    ) -> DailySnapshot:
        """
        Create a daily snapshot with structured data.
        
        Args:
            position_id: Related position ID
            symbol: Stock ticker
            snapshot_date: Date of snapshot
            ohlcv: Dict with open, high, low, close, volume
            position_metrics: Dict with avg_cost, total_shares, pnl_pct, etc.
            technicals: Dict with ma50, ma21, ma200, etc.
            **kwargs: Additional attributes
        
        Returns:
            Created DailySnapshot instance
        """
        data = {
            'position_id': position_id,
            'symbol': symbol.upper(),
            'snapshot_date': snapshot_date,
        }
        
        # Add OHLCV
        if ohlcv:
            data.update({
                'open_price': ohlcv.get('open'),
                'high_price': ohlcv.get('high'),
                'low_price': ohlcv.get('low'),
                'close_price': ohlcv.get('close'),
                'volume': ohlcv.get('volume'),
            })
        
        # Add position metrics
        if position_metrics:
            data.update({
                'avg_cost': position_metrics.get('avg_cost'),
                'total_shares': position_metrics.get('total_shares'),
                'pnl_pct': position_metrics.get('pnl_pct'),
                'gain_from_pivot': position_metrics.get('gain_from_pivot'),
                'max_gain_to_date': position_metrics.get('max_gain_to_date'),
                'max_drawdown_to_date': position_metrics.get('max_drawdown_to_date'),
                'days_in_position': position_metrics.get('days_in_position'),
            })
        
        # Add technicals
        if technicals:
            data.update({
                'ma50': technicals.get('ma50'),
                'ma21': technicals.get('ma21'),
                'ma200': technicals.get('ma200'),
                'above_50ma': technicals.get('above_50ma'),
                'above_21ema': technicals.get('above_21ema'),
                'above_200ma': technicals.get('above_200ma'),
                'volume_sma50': technicals.get('volume_sma50'),
                'volume_ratio': technicals.get('volume_ratio'),
            })
        
        data.update(kwargs)
        return self.create(**data)
    
    # ==================== READ ====================
    
    def get_by_id(self, snapshot_id: int) -> Optional[DailySnapshot]:
        """Get snapshot by ID."""
        return self.session.query(DailySnapshot).filter_by(id=snapshot_id).first()
    
    def get_by_position_date(
        self,
        position_id: int,
        snapshot_date: date
    ) -> Optional[DailySnapshot]:
        """Get snapshot for a specific position and date."""
        return self.session.query(DailySnapshot).filter(
            DailySnapshot.position_id == position_id,
            DailySnapshot.snapshot_date == snapshot_date
        ).first()
    
    def get_by_position(
        self,
        position_id: int,
        start_date: date = None,
        end_date: date = None
    ) -> List[DailySnapshot]:
        """Get all snapshots for a position."""
        query = self.session.query(DailySnapshot).filter(
            DailySnapshot.position_id == position_id
        )
        
        if start_date:
            query = query.filter(DailySnapshot.snapshot_date >= start_date)
        if end_date:
            query = query.filter(DailySnapshot.snapshot_date <= end_date)
        
        return query.order_by(DailySnapshot.snapshot_date).all()
    
    def get_by_symbol(
        self,
        symbol: str,
        start_date: date = None,
        end_date: date = None
    ) -> List[DailySnapshot]:
        """Get all snapshots for a symbol."""
        query = self.session.query(DailySnapshot).filter(
            DailySnapshot.symbol == symbol.upper()
        )
        
        if start_date:
            query = query.filter(DailySnapshot.snapshot_date >= start_date)
        if end_date:
            query = query.filter(DailySnapshot.snapshot_date <= end_date)
        
        return query.order_by(DailySnapshot.snapshot_date).all()
    
    def get_latest(self, position_id: int) -> Optional[DailySnapshot]:
        """Get most recent snapshot for a position."""
        return self.session.query(DailySnapshot).filter(
            DailySnapshot.position_id == position_id
        ).order_by(desc(DailySnapshot.snapshot_date)).first()
    
    def get_running_stats(self, position_id: int) -> Dict[str, Any]:
        """
        Get running statistics for a position from snapshots.
        
        Returns:
            Dict with max_gain, max_drawdown, days_held
        """
        snapshots = self.get_by_position(position_id)
        
        if not snapshots:
            return {
                'max_gain_pct': 0,
                'max_drawdown_pct': 0,
                'days_held': 0,
                'current_pnl_pct': 0
            }
        
        max_gain = max((s.pnl_pct or 0) for s in snapshots)
        min_pnl = min((s.pnl_pct or 0) for s in snapshots)
        max_drawdown = abs(min(0, min_pnl))
        
        return {
            'max_gain_pct': max_gain,
            'max_drawdown_pct': max_drawdown,
            'days_held': len(snapshots),
            'current_pnl_pct': snapshots[-1].pnl_pct if snapshots else 0
        }
    
    def exists(self, position_id: int, snapshot_date: date) -> bool:
        """Check if snapshot exists for position and date."""
        return self.get_by_position_date(position_id, snapshot_date) is not None
    
    # ==================== UPDATE ====================
    
    def update(self, snapshot: DailySnapshot, **kwargs) -> DailySnapshot:
        """Update snapshot attributes."""
        for key, value in kwargs.items():
            if hasattr(snapshot, key):
                setattr(snapshot, key, value)
        
        self.session.flush()
        return snapshot
    
    def upsert(
        self,
        position_id: int,
        symbol: str,
        snapshot_date: date,
        **kwargs
    ) -> DailySnapshot:
        """
        Update existing snapshot or create new one.
        
        Returns:
            Created or updated DailySnapshot instance
        """
        existing = self.get_by_position_date(position_id, snapshot_date)
        
        if existing:
            return self.update(existing, **kwargs)
        else:
            return self.create(
                position_id=position_id,
                symbol=symbol,
                snapshot_date=snapshot_date,
                **kwargs
            )
    
    # ==================== DELETE ====================
    
    def delete(self, snapshot: DailySnapshot) -> None:
        """Delete a snapshot."""
        self.session.delete(snapshot)
        self.session.flush()
    
    def delete_by_position(self, position_id: int) -> int:
        """Delete all snapshots for a position."""
        deleted = self.session.query(DailySnapshot).filter(
            DailySnapshot.position_id == position_id
        ).delete(synchronize_session=False)
        
        self.session.flush()
        return deleted
    
    def delete_old(self, days: int = 365) -> int:
        """Delete snapshots older than specified days."""
        cutoff = date.today() - timedelta(days=days)
        
        deleted = self.session.query(DailySnapshot).filter(
            DailySnapshot.snapshot_date < cutoff
        ).delete(synchronize_session=False)
        
        self.session.flush()
        return deleted


class OutcomeRepository:
    """Repository for Outcome entity operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== CREATE ====================
    
    def create(self, **kwargs) -> Outcome:
        """Create a new outcome record."""
        outcome = Outcome(**kwargs)
        self.session.add(outcome)
        self.session.flush()
        return outcome
    
    def create_from_position(
        self,
        position,
        exit_price: float,
        exit_date: date = None,
        exit_reason: str = None,
        running_stats: Dict[str, Any] = None,
        spy_exit_price: float = None
    ) -> Outcome:
        """
        Create outcome record from a closed position.
        
        Args:
            position: Position instance being closed
            exit_price: Exit price
            exit_date: Exit date (defaults to today)
            exit_reason: Reason for exit (STOP_HIT, TP1, TP2, MANUAL, etc.)
            running_stats: Dict with max_gain_pct, max_drawdown_pct
            spy_exit_price: SPY price at exit
        
        Returns:
            Created Outcome instance
        """
        exit_date = exit_date or date.today()
        
        # Calculate results
        entry_price = position.avg_cost or position.e1_price
        gross_pnl = (exit_price - entry_price) * (position.total_shares or 0)
        gross_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
        
        # Calculate holding days
        entry_dt = position.entry_date or position.e1_date
        holding_days = (exit_date - entry_dt).days if entry_dt else 0
        
        # Determine outcome classification
        if gross_pct >= 20:
            outcome_class = 'SUCCESS'
            outcome_score = 3
        elif gross_pct >= 5:
            outcome_class = 'PARTIAL'
            outcome_score = 2
        elif gross_pct > -7:
            outcome_class = 'STOPPED'
            outcome_score = 1
        else:
            outcome_class = 'FAILED'
            outcome_score = 0
        
        # Calculate relative return
        spy_return = None
        relative_return = None
        if spy_exit_price and position.pivot:  # Use pivot as proxy for SPY entry
            # This should be improved with actual SPY tracking
            pass
        
        return self.create(
            position_id=position.id,
            symbol=position.symbol,
            portfolio=position.portfolio,
            
            # Entry context
            entry_date=entry_dt,
            entry_price=entry_price,
            entry_shares=position.total_shares,
            entry_grade=position.entry_grade,
            entry_score=position.entry_score,
            
            # CANSLIM factors at entry
            rs_at_entry=position.rs_rating,
            eps_at_entry=position.eps_rating,
            comp_at_entry=position.comp_rating,
            ad_at_entry=position.ad_rating,
            stage_at_entry=position.base_stage,
            pattern=position.pattern,
            base_depth_at_entry=position.base_depth,
            base_length_at_entry=position.base_length,
            
            # Exit data
            exit_date=exit_date,
            exit_price=exit_price,
            exit_shares=position.total_shares,
            exit_reason=exit_reason,
            
            # Results
            holding_days=holding_days,
            gross_pnl=gross_pnl,
            gross_pct=gross_pct,
            
            # Risk metrics
            max_gain_pct=running_stats.get('max_gain_pct') if running_stats else None,
            max_drawdown_pct=running_stats.get('max_drawdown_pct') if running_stats else None,
            hit_stop=exit_reason == 'STOP_HIT',
            
            # Classification
            outcome=outcome_class,
            outcome_score=outcome_score,
        )
    
    # ==================== READ ====================
    
    def get_by_id(self, outcome_id: int) -> Optional[Outcome]:
        """Get outcome by ID."""
        return self.session.query(Outcome).filter_by(id=outcome_id).first()
    
    def get_by_position(self, position_id: int) -> Optional[Outcome]:
        """Get outcome for a position."""
        return self.session.query(Outcome).filter_by(position_id=position_id).first()
    
    def get_by_symbol(self, symbol: str) -> List[Outcome]:
        """Get all outcomes for a symbol."""
        return self.session.query(Outcome).filter(
            Outcome.symbol == symbol.upper()
        ).order_by(desc(Outcome.exit_date)).all()
    
    def get_all(
        self,
        start_date: date = None,
        end_date: date = None,
        outcome_type: str = None,
        grade: str = None
    ) -> List[Outcome]:
        """
        Get outcomes with optional filters.
        
        Args:
            start_date: Filter by entry date start
            end_date: Filter by entry date end
            outcome_type: Filter by outcome classification
            grade: Filter by entry grade
        
        Returns:
            List of Outcome instances
        """
        query = self.session.query(Outcome)
        
        if start_date:
            query = query.filter(Outcome.entry_date >= start_date)
        if end_date:
            query = query.filter(Outcome.entry_date <= end_date)
        if outcome_type:
            query = query.filter(Outcome.outcome == outcome_type)
        if grade:
            query = query.filter(Outcome.entry_grade == grade)
        
        return query.order_by(desc(Outcome.exit_date)).all()
    
    def get_for_learning(
        self,
        min_sample_size: int = 20,
        start_date: date = None,
        end_date: date = None,
        validated_only: bool = False
    ) -> List[Outcome]:
        """
        Get outcomes suitable for learning engine analysis.
        
        Args:
            min_sample_size: Not used directly, but caller should check
            start_date: Filter by entry date start
            end_date: Filter by entry date end
            validated_only: Only return validated outcomes
        
        Returns:
            List of Outcome instances with complete data
        """
        query = self.session.query(Outcome).filter(
            Outcome.entry_grade.isnot(None),
            Outcome.outcome.isnot(None),
            Outcome.rs_at_entry.isnot(None)
        )
        
        if start_date:
            query = query.filter(Outcome.entry_date >= start_date)
        if end_date:
            query = query.filter(Outcome.entry_date <= end_date)
        if validated_only:
            query = query.filter(Outcome.validated == True)
        
        return query.order_by(Outcome.entry_date).all()
    
    def count(self, outcome_type: str = None, grade: str = None) -> int:
        """Count outcomes with optional filters."""
        query = self.session.query(func.count(Outcome.id))
        
        if outcome_type:
            query = query.filter(Outcome.outcome == outcome_type)
        if grade:
            query = query.filter(Outcome.entry_grade == grade)
        
        return query.scalar()
    
    # ==================== UPDATE ====================
    
    def update(self, outcome: Outcome, **kwargs) -> Outcome:
        """Update outcome attributes."""
        for key, value in kwargs.items():
            if hasattr(outcome, key):
                setattr(outcome, key, value)
        
        self.session.flush()
        return outcome
    
    def validate(
        self,
        outcome: Outcome,
        tradesviz_matched: bool = False,
        tradesviz_trade_id: str = None,
        notes: str = None
    ) -> Outcome:
        """Mark outcome as validated."""
        outcome.validated = True
        outcome.tradesviz_matched = tradesviz_matched
        
        if tradesviz_trade_id:
            outcome.tradesviz_trade_id = tradesviz_trade_id
        if notes:
            outcome.validation_notes = notes
        
        self.session.flush()
        return outcome
    
    # ==================== DELETE ====================
    
    def delete(self, outcome: Outcome) -> None:
        """Delete an outcome."""
        self.session.delete(outcome)
        self.session.flush()
    
    # ==================== ANALYTICS ====================
    
    def get_summary_stats(
        self,
        start_date: date = None,
        end_date: date = None,
        grade: str = None
    ) -> Dict[str, Any]:
        """
        Calculate summary statistics for outcomes.
        
        Returns:
            Dict with win rate, avg gain, avg loss, etc.
        """
        outcomes = self.get_all(
            start_date=start_date,
            end_date=end_date,
            grade=grade
        )
        
        if not outcomes:
            return {
                'total': 0,
                'win_rate': 0,
                'avg_gain': 0,
                'avg_loss': 0,
                'avg_holding_days': 0
            }
        
        total = len(outcomes)
        winners = [o for o in outcomes if o.gross_pct and o.gross_pct > 0]
        losers = [o for o in outcomes if o.gross_pct and o.gross_pct <= 0]
        
        return {
            'total': total,
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': len(winners) / total if total > 0 else 0,
            'avg_gain': sum(o.gross_pct for o in winners) / len(winners) if winners else 0,
            'avg_loss': sum(o.gross_pct for o in losers) / len(losers) if losers else 0,
            'avg_holding_days': sum(o.holding_days or 0 for o in outcomes) / total if total > 0 else 0,
            'by_outcome': {
                'SUCCESS': sum(1 for o in outcomes if o.outcome == 'SUCCESS'),
                'PARTIAL': sum(1 for o in outcomes if o.outcome == 'PARTIAL'),
                'STOPPED': sum(1 for o in outcomes if o.outcome == 'STOPPED'),
                'FAILED': sum(1 for o in outcomes if o.outcome == 'FAILED'),
            }
        }
    
    def get_grade_performance(self) -> Dict[str, Dict[str, Any]]:
        """
        Get performance breakdown by entry grade.
        
        Returns:
            Dict with grade -> stats mapping
        """
        grades = ['A+', 'A', 'B', 'C']
        result = {}
        
        for grade in grades:
            stats = self.get_summary_stats(grade=grade)
            result[grade] = stats
        
        return result
    
    def get_factor_correlation(self, factor: str) -> Dict[str, float]:
        """
        Calculate correlation between a factor and outcome success.
        
        Args:
            factor: Factor column name (rs_at_entry, eps_at_entry, etc.)
        
        Returns:
            Dict with correlation statistics
        """
        outcomes = self.get_for_learning()
        
        if not outcomes:
            return {'correlation': 0, 'sample_size': 0}
        
        # Get factor values and outcome scores
        data = [(getattr(o, factor), o.outcome_score) 
                for o in outcomes 
                if getattr(o, factor) is not None]
        
        if len(data) < 10:
            return {'correlation': 0, 'sample_size': len(data)}
        
        # Simple correlation calculation
        x_vals = [d[0] for d in data]
        y_vals = [d[1] for d in data]
        
        x_mean = sum(x_vals) / len(x_vals)
        y_mean = sum(y_vals) / len(y_vals)
        
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in data)
        x_std = (sum((x - x_mean) ** 2 for x in x_vals)) ** 0.5
        y_std = (sum((y - y_mean) ** 2 for y in y_vals)) ** 0.5
        
        correlation = numerator / (x_std * y_std) if x_std and y_std else 0
        
        return {
            'correlation': correlation,
            'sample_size': len(data),
            'factor_mean': x_mean,
            'success_rate_high': sum(1 for x, y in data if x > x_mean and y >= 2) / 
                                max(1, sum(1 for x, y in data if x > x_mean)),
            'success_rate_low': sum(1 for x, y in data if x <= x_mean and y >= 2) / 
                               max(1, sum(1 for x, y in data if x <= x_mean)),
        }
