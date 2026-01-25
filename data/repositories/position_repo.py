"""
CANSLIM Monitor - Position Repository
Phase 1: Database Foundation

Provides CRUD operations and queries for Position entities.
"""

from datetime import datetime, date
from typing import List, Optional, Dict, Any
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from canslim_monitor.data.models import Position


class PositionRepository:
    """Repository for Position entity operations."""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== CREATE ====================
    
    def create(self, **kwargs) -> Position:
        """
        Create a new position.
        
        Args:
            **kwargs: Position attributes
        
        Returns:
            Created Position instance
        """
        position = Position(**kwargs)
        self.session.add(position)
        self.session.flush()
        return position
    
    def create_watchlist_item(
        self,
        symbol: str,
        pivot: float,
        pattern: str,
        portfolio: str = 'CWB',
        **kwargs
    ) -> Position:
        """
        Create a new watchlist item (state = 0).
        
        Args:
            symbol: Stock ticker
            pivot: Breakout pivot price
            pattern: Base pattern (Cup w/Handle, etc.)
            portfolio: Portfolio code
            **kwargs: Additional position attributes
        
        Returns:
            Created Position instance
        """
        return self.create(
            symbol=symbol.upper(),
            pivot=pivot,
            pattern=pattern,
            portfolio=portfolio,
            state=0,
            watch_date=date.today(),
            **kwargs
        )
    
    # ==================== READ ====================
    
    def get_by_id(self, position_id: int) -> Optional[Position]:
        """Get position by ID."""
        return self.session.query(Position).filter_by(id=position_id).first()
    
    def get_by_symbol(self, symbol: str, portfolio: str = None) -> Optional[Position]:
        """
        Get position by symbol (and optionally portfolio).
        
        Args:
            symbol: Stock ticker
            portfolio: Optional portfolio filter
        
        Returns:
            Position or None
        """
        query = self.session.query(Position).filter(
            Position.symbol == symbol.upper()
        )
        if portfolio:
            query = query.filter(Position.portfolio == portfolio)
        
        return query.first()
    
    def get_all(self, include_closed: bool = False) -> List[Position]:
        """
        Get all positions.
        
        Args:
            include_closed: If True, include closed positions (state < 0)
        
        Returns:
            List of Position instances
        """
        query = self.session.query(Position)
        if not include_closed:
            query = query.filter(Position.state >= 0)
        return query.order_by(Position.symbol).all()
    
    def get_watching(self) -> List[Position]:
        """Get all positions in WATCHING state (state = 0)."""
        return self.session.query(Position).filter(
            Position.state == 0
        ).order_by(Position.symbol).all()
    
    def get_in_position(self) -> List[Position]:
        """Get all active positions (state >= 1)."""
        return self.session.query(Position).filter(
            Position.state >= 1
        ).order_by(Position.symbol).all()
    
    def get_by_state(self, state: int) -> List[Position]:
        """Get positions by specific state."""
        return self.session.query(Position).filter(
            Position.state == state
        ).order_by(Position.symbol).all()
    
    def get_by_portfolio(self, portfolio: str, include_closed: bool = False) -> List[Position]:
        """Get positions by portfolio."""
        query = self.session.query(Position).filter(
            Position.portfolio == portfolio
        )
        if not include_closed:
            query = query.filter(Position.state >= 0)
        return query.order_by(Position.symbol).all()
    
    def get_needing_sync(self) -> List[Position]:
        """Get positions that need to be synced to Google Sheets.

        Returns ALL positions with needs_sheet_sync=True, including closed ones.
        Closed positions (state < 0) will be deleted from the sheet.
        """
        return self.session.query(Position).filter(
            Position.needs_sheet_sync == True
        ).all()
    
    def get_by_sheet_row_id(self, sheet_row_id: str) -> Optional[Position]:
        """Get position by Google Sheets row ID."""
        return self.session.query(Position).filter_by(
            sheet_row_id=sheet_row_id
        ).first()
    
    def search(
        self,
        symbol: str = None,
        portfolio: str = None,
        state: int = None,
        min_rs: int = None,
        max_rs: int = None,
        pattern: str = None,
        grade: str = None,
        limit: int = None
    ) -> List[Position]:
        """
        Search positions with multiple filters.
        
        Args:
            symbol: Symbol contains (case-insensitive)
            portfolio: Exact portfolio match
            state: Exact state match
            min_rs: Minimum RS rating
            max_rs: Maximum RS rating
            pattern: Pattern contains (case-insensitive)
            grade: Exact grade match
            limit: Maximum results
        
        Returns:
            List of matching Position instances
        """
        query = self.session.query(Position)
        
        if symbol:
            query = query.filter(Position.symbol.ilike(f'%{symbol}%'))
        if portfolio:
            query = query.filter(Position.portfolio == portfolio)
        if state is not None:
            query = query.filter(Position.state == state)
        if min_rs:
            query = query.filter(Position.rs_rating >= min_rs)
        if max_rs:
            query = query.filter(Position.rs_rating <= max_rs)
        if pattern:
            query = query.filter(Position.pattern.ilike(f'%{pattern}%'))
        if grade:
            query = query.filter(Position.entry_grade == grade)
        
        query = query.order_by(Position.symbol)
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def count(self, state: int = None, portfolio: str = None) -> int:
        """Count positions with optional filters."""
        query = self.session.query(func.count(Position.id))
        
        if state is not None:
            query = query.filter(Position.state == state)
        if portfolio:
            query = query.filter(Position.portfolio == portfolio)
        
        return query.scalar()
    
    # ==================== UPDATE ====================
    
    def update(self, position: Position, **kwargs) -> Position:
        """
        Update position attributes.
        
        Args:
            position: Position instance to update
            **kwargs: Attributes to update
        
        Returns:
            Updated Position instance
        """
        for key, value in kwargs.items():
            if hasattr(position, key):
                setattr(position, key, value)
        
        position.needs_sheet_sync = True
        self.session.flush()
        return position
    
    def update_by_id(self, position_id: int, **kwargs) -> Optional[Position]:
        """Update position by ID."""
        position = self.get_by_id(position_id)
        if position:
            return self.update(position, **kwargs)
        return None
    
    def update_price(
        self,
        position: Position,
        price: float,
        timestamp: datetime = None
    ) -> Position:
        """
        Update position's last price and calculate PnL.
        
        Args:
            position: Position to update
            price: Current price
            timestamp: Price timestamp (defaults to now)
        
        Returns:
            Updated Position instance
        """
        position.last_price = price
        position.last_price_time = timestamp or datetime.now()
        
        # Calculate PnL if in position
        if position.avg_cost and position.avg_cost > 0:
            position.current_pnl_pct = ((price - position.avg_cost) / position.avg_cost) * 100
        
        self.session.flush()
        return position
    
    def transition_state(
        self,
        position: Position,
        new_state: int,
        **kwargs
    ) -> Position:
        """
        Transition position to a new state.
        
        Args:
            position: Position to transition
            new_state: Target state
            **kwargs: Additional attributes to update
        
        Returns:
            Updated Position instance
        """
        position.state = new_state
        position.state_updated_at = datetime.now()
        position.needs_sheet_sync = True
        
        for key, value in kwargs.items():
            if hasattr(position, key):
                setattr(position, key, value)
        
        self.session.flush()
        return position
    
    def log_entry(
        self,
        position: Position,
        entry_num: int,
        shares: int,
        price: float,
        entry_date: date = None
    ) -> Position:
        """
        Log a trade entry (E1, E2, or E3).
        
        Args:
            position: Position to update
            entry_num: Entry number (1, 2, or 3)
            shares: Number of shares
            price: Entry price
            entry_date: Entry date (defaults to today)
        
        Returns:
            Updated Position instance
        """
        entry_date = entry_date or date.today()
        
        if entry_num == 1:
            position.e1_shares = shares
            position.e1_price = price
            position.e1_date = entry_date
            position.entry_date = entry_date
        elif entry_num == 2:
            position.e2_shares = shares
            position.e2_price = price
            position.e2_date = entry_date
        elif entry_num == 3:
            position.e3_shares = shares
            position.e3_price = price
            position.e3_date = entry_date
        
        # Recalculate totals
        self._recalculate_position_totals(position)
        
        # Transition to appropriate state
        if entry_num == 1 and position.state == 0:
            position.state = 1
            position.state_updated_at = datetime.now()
            position.breakout_date = entry_date
        elif entry_num == 2 and position.state == 1:
            position.state = 2
            position.state_updated_at = datetime.now()
        elif entry_num == 3 and position.state == 2:
            position.state = 3
            position.state_updated_at = datetime.now()
        
        position.needs_sheet_sync = True
        self.session.flush()
        return position
    
    def mark_synced(self, position: Position) -> Position:
        """Mark position as synced with Google Sheets."""
        position.needs_sheet_sync = False
        position.last_sheet_sync = datetime.now()
        self.session.flush()
        return position
    
    def _recalculate_position_totals(self, position: Position) -> None:
        """Recalculate total shares and average cost."""
        total_shares = 0
        total_cost = 0.0
        
        if position.e1_shares and position.e1_price:
            total_shares += position.e1_shares
            total_cost += position.e1_shares * position.e1_price
        
        if position.e2_shares and position.e2_price:
            total_shares += position.e2_shares
            total_cost += position.e2_shares * position.e2_price
        
        if position.e3_shares and position.e3_price:
            total_shares += position.e3_shares
            total_cost += position.e3_shares * position.e3_price
        
        # Subtract sold shares
        if position.tp1_sold and position.tp1_price:
            total_shares -= position.tp1_sold
        
        if position.tp2_sold and position.tp2_price:
            total_shares -= position.tp2_sold
        
        position.total_shares = total_shares
        
        if total_shares > 0 and total_cost > 0:
            position.avg_cost = total_cost / (position.e1_shares or 0 + position.e2_shares or 0 + position.e3_shares or 0)
            
            # Calculate targets
            if position.avg_cost:
                position.stop_price = position.avg_cost * (1 - position.hard_stop_pct / 100)
                position.tp1_target = position.avg_cost * (1 + position.tp1_pct / 100)
                position.tp2_target = position.avg_cost * (1 + position.tp2_pct / 100)
    
    # ==================== DELETE ====================
    
    def delete(self, position: Position) -> None:
        """Delete a position (cascades to alerts and snapshots)."""
        self.session.delete(position)
        self.session.flush()
    
    def delete_by_id(self, position_id: int) -> bool:
        """
        Delete position by ID.
        
        Returns:
            True if deleted, False if not found
        """
        position = self.get_by_id(position_id)
        if position:
            self.delete(position)
            return True
        return False
    
    def delete_by_symbol(self, symbol: str, portfolio: str = None) -> bool:
        """Delete position by symbol."""
        position = self.get_by_symbol(symbol, portfolio)
        if position:
            self.delete(position)
            return True
        return False
    
    # ==================== BULK OPERATIONS ====================
    
    def bulk_update_prices(self, prices: Dict[str, float], timestamp: datetime = None) -> int:
        """
        Bulk update prices for multiple symbols.
        
        Args:
            prices: Dict of symbol -> price
            timestamp: Price timestamp
        
        Returns:
            Number of positions updated
        """
        timestamp = timestamp or datetime.now()
        updated = 0
        
        for symbol, price in prices.items():
            positions = self.session.query(Position).filter(
                Position.symbol == symbol.upper(),
                Position.state >= 0
            ).all()
            
            for position in positions:
                self.update_price(position, price, timestamp)
                updated += 1
        
        return updated
    
    def bulk_create(self, positions_data: List[Dict[str, Any]]) -> List[Position]:
        """
        Bulk create positions.
        
        Args:
            positions_data: List of position attribute dicts
        
        Returns:
            List of created Position instances
        """
        positions = []
        for data in positions_data:
            position = Position(**data)
            self.session.add(position)
            positions.append(position)
        
        self.session.flush()
        return positions
