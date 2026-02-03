"""
CANSLIM Monitor - Position Repository
Phase 1: Database Foundation

Provides CRUD operations and queries for Position entities.
"""

import logging
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from canslim_monitor.data.models import Position, TRACKED_FIELDS, PositionHistory

logger = logging.getLogger('canslim.database')


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
        # Auto-set pivot_set_date when creating with a pivot
        if kwargs.get('pivot') and not kwargs.get('pivot_set_date'):
            kwargs['pivot_set_date'] = date.today()

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
    
    def get_by_state(self, state: float) -> List[Position]:
        """Get positions by specific state (supports float for State -1.5)."""
        return self.session.query(Position).filter(
            Position.state == state
        ).order_by(Position.symbol).all()

    def get_watching_exited(self) -> List[Position]:
        """Get all positions in WATCHING_EXITED state (state = -1.5)."""
        return self.session.query(Position).filter(
            Position.state == -1.5
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
    
    # Fields that trigger recalculation of avg_cost and P&L
    ENTRY_FIELDS = {'e1_shares', 'e1_price', 'e2_shares', 'e2_price',
                    'e3_shares', 'e3_price', 'tp1_sold', 'tp2_sold'}

    def _record_position_changes(
        self,
        position: Position,
        old_values: Dict[str, Any],
        new_values: Dict[str, Any],
        change_source: str = 'manual_edit'
    ) -> int:
        """
        Record changes to position fields in history table.

        Args:
            position: Position that was updated
            old_values: Dict of field names to old values
            new_values: Dict of field names to new values
            change_source: What triggered the changes

        Returns:
            Number of changes recorded
        """
        from datetime import datetime as dt

        count = 0
        changed_at = dt.now()

        for field_name in TRACKED_FIELDS:
            if field_name not in new_values:
                continue

            old_val = old_values.get(field_name)
            new_val = new_values.get(field_name)

            # Skip if values are the same
            if self._values_are_equal(old_val, new_val):
                continue

            # Convert to strings for storage
            old_str = self._value_to_string(old_val)
            new_str = self._value_to_string(new_val)

            history = PositionHistory(
                position_id=position.id,
                field_name=field_name,
                old_value=old_str,
                new_value=new_str,
                change_source=change_source,
                changed_at=changed_at
            )
            self.session.add(history)
            count += 1
            logger.debug(f"  History: {field_name} = {old_str} -> {new_str}")

        if count > 0:
            logger.info(f"Recorded {count} field changes for {position.symbol}")

        return count

    def _value_to_string(self, value: Any) -> Optional[str]:
        """Convert a value to string for storage."""
        if value is None:
            return None
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if hasattr(value, 'isoformat'):  # datetime/date
            return value.isoformat()
        if isinstance(value, float):
            return f"{value:.6f}".rstrip('0').rstrip('.')
        return str(value)

    def _values_are_equal(self, old_val: Any, new_val: Any) -> bool:
        """Check if two values are equal (handles None and float precision)."""
        if old_val is None and new_val is None:
            return True
        if old_val is None or new_val is None:
            return False
        if isinstance(old_val, float) and isinstance(new_val, float):
            return abs(old_val - new_val) < 0.0001
        return str(old_val) == str(new_val)

    def update(
        self,
        position: Position,
        change_source: str = 'manual_edit',
        **kwargs
    ) -> Position:
        """
        Update position attributes and record changes to history.

        Args:
            position: Position instance to update
            change_source: What triggered the update ('manual_edit', 'system_calc', etc.)
            **kwargs: Attributes to update

        Returns:
            Updated Position instance
        """
        # Check if any entry-related fields are being updated
        needs_recalc = bool(set(kwargs.keys()) & self.ENTRY_FIELDS)

        # Track if user explicitly provided certain fields (don't overwrite with calculated values)
        user_provided_stop_price = 'stop_price' in kwargs and kwargs['stop_price'] is not None
        user_provided_tp1_target = 'tp1_target' in kwargs and kwargs['tp1_target'] is not None
        user_provided_tp2_target = 'tp2_target' in kwargs and kwargs['tp2_target'] is not None

        # Auto-update pivot_set_date when pivot changes
        if 'pivot' in kwargs and kwargs['pivot'] is not None:
            old_pivot = position.pivot
            new_pivot = kwargs['pivot']
            if old_pivot != new_pivot:
                kwargs['pivot_set_date'] = date.today()
                logger.info(f"  pivot_set_date auto-set to {date.today()} (pivot changed from {old_pivot} to {new_pivot})")

        logger.info(f"PositionRepo.update: {position.symbol} (id={position.id}) with {len(kwargs)} fields")

        # Capture old values for history tracking
        old_values = {}
        for key in kwargs.keys():
            if hasattr(position, key) and key in TRACKED_FIELDS:
                old_values[key] = getattr(position, key, None)

        # Track key fields for logging
        key_fields = {'stop_price', 'pivot', 'hard_stop_pct', 'pattern', 'base_stage'}

        for key, value in kwargs.items():
            if hasattr(position, key):
                old_value = getattr(position, key, None)
                setattr(position, key, value)
                # Log key fields at INFO level
                if key in key_fields and old_value != value:
                    logger.info(f"  {key}: {old_value} -> {value}")
            else:
                logger.warning(f"  {key}: SKIPPED (attribute not found on Position model)")

        # Recalculate avg_cost and totals if entry data changed
        if needs_recalc:
            self._recalculate_position_totals(
                position,
                skip_stop_price=user_provided_stop_price,
                skip_tp1_target=user_provided_tp1_target,
                skip_tp2_target=user_provided_tp2_target
            )
            # Also recalculate P&L based on new avg_cost
            if position.avg_cost and position.avg_cost > 0 and position.last_price:
                position.current_pnl_pct = ((position.last_price - position.avg_cost) / position.avg_cost) * 100

        # Record changes to history (only for tracked fields)
        if old_values:
            self._record_position_changes(position, old_values, kwargs, change_source)

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
        Transition position to a new state and record to history.

        Args:
            position: Position to transition
            new_state: Target state
            **kwargs: Additional attributes to update

        Returns:
            Updated Position instance
        """
        # Capture old values for history
        old_state = position.state
        old_values = {'state': old_state}
        new_values = {'state': new_state}

        for key in kwargs.keys():
            if hasattr(position, key) and key in TRACKED_FIELDS:
                old_values[key] = getattr(position, key, None)
                new_values[key] = kwargs[key]

        # Apply changes
        position.state = new_state
        position.state_updated_at = datetime.now()
        position.needs_sheet_sync = True

        for key, value in kwargs.items():
            if hasattr(position, key):
                setattr(position, key, value)

        # Record state transition and any additional field changes
        self._record_position_changes(position, old_values, new_values, 'state_transition')

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
    
    def _recalculate_position_totals(
        self,
        position: Position,
        skip_stop_price: bool = False,
        skip_tp1_target: bool = False,
        skip_tp2_target: bool = False
    ) -> None:
        """
        Recalculate total shares and average cost.

        Args:
            position: Position to recalculate
            skip_stop_price: If True, don't overwrite stop_price (user provided)
            skip_tp1_target: If True, don't overwrite tp1_target (user provided)
            skip_tp2_target: If True, don't overwrite tp2_target (user provided)
        """
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
            # Calculate total shares bought (before any sells) for avg_cost
            total_bought = (position.e1_shares or 0) + (position.e2_shares or 0) + (position.e3_shares or 0)
            if total_bought > 0:
                position.avg_cost = total_cost / total_bought

            # Calculate targets (but respect user-provided values)
            if position.avg_cost:
                if not skip_stop_price:
                    position.stop_price = position.avg_cost * (1 - position.hard_stop_pct / 100)
                if not skip_tp1_target:
                    position.tp1_target = position.avg_cost * (1 + position.tp1_pct / 100)
                if not skip_tp2_target:
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

    # ==================== STATE -1.5 (WATCHING_EXITED) OPERATIONS ====================

    def transition_to_watching_exited(
        self,
        position: Position,
        exit_price: float,
        exit_reason: str,
        notes: str = None
    ) -> Position:
        """
        Transition position to State -1.5 (WATCHING_EXITED) for re-entry monitoring.

        Called when position exits via stop loss or technical sell (NOT profit).
        Preserves original pivot for retest detection.

        Args:
            position: The position being exited
            exit_price: The price at exit
            exit_reason: One of STOP_HIT, 50MA_BREAKDOWN, 10WMA_BREAKDOWN, MARKET_CORRECTION

        Returns:
            Updated position in State -1.5
        """
        from datetime import timedelta

        # Preserve original pivot for retest detection
        position.original_pivot = position.pivot

        # Set exit/close data
        position.close_date = date.today()
        position.close_price = exit_price
        position.close_reason = exit_reason
        position.watching_exited_since = datetime.now()

        # Calculate realized P&L
        if position.avg_cost and position.avg_cost > 0:
            position.realized_pnl_pct = ((exit_price - position.avg_cost) / position.avg_cost) * 100
            if position.total_shares:
                position.realized_pnl = (exit_price - position.avg_cost) * position.total_shares

        # Reset MA test count for new monitoring
        position.ma_test_count = 0

        # Clear active position fields
        position.total_shares = 0
        position.e1_shares = 0
        position.e2_shares = 0
        position.e3_shares = 0
        position.entry_date = None
        position.stop_price = None

        # Set state
        position.state = -1.5
        position.state_updated_at = datetime.now()
        position.needs_sheet_sync = True

        # Add note
        exit_note = f"[{datetime.now().strftime('%Y-%m-%d')}] Exited to re-entry watch: {exit_reason} @ ${exit_price:.2f}"
        if notes:
            exit_note += f" - {notes}"
        position.notes = f"{position.notes or ''}\n{exit_note}".strip()

        self.session.flush()

        logger.info(
            f"{position.symbol}: Transitioned to WATCHING_EXITED "
            f"(exit: {exit_reason} @ ${exit_price:.2f})"
        )

        return position

    def remove_from_watching_exited(
        self,
        position: Position,
        target_state: int = -2,
        notes: str = None
    ) -> Position:
        """
        Manually remove position from State -1.5 (WATCHING_EXITED).

        Record is retained in database for historical reference.

        Args:
            position: The position to remove
            target_state: -1 (CLOSED) or -2 (STOPPED_OUT/ARCHIVED)
            notes: Optional notes explaining the removal

        Returns:
            Updated position
        """
        if position.state != -1.5:
            raise ValueError(f"Position {position.symbol} is not in State -1.5")

        if target_state not in [-1, -2]:
            raise ValueError("Target state must be -1 (CLOSED) or -2 (ARCHIVED)")

        # Append removal note
        removal_note = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Removed from re-entry watch"
        if notes:
            removal_note += f": {notes}"

        position.notes = f"{position.notes or ''}\n{removal_note}".strip()
        position.state = target_state
        position.state_updated_at = datetime.now()
        position.needs_sheet_sync = True

        self.session.flush()

        state_name = "CLOSED" if target_state == -1 else "ARCHIVED"
        logger.info(f"{position.symbol}: Removed from WATCHING_EXITED -> {state_name}")

        return position

    def return_to_watchlist(
        self,
        position: Position,
        new_pivot: float,
        notes: str = None
    ) -> Position:
        """
        Return a State -1.5 position to regular watchlist (State 0) with new base.

        Used when a previously exited stock forms a new base pattern.

        Args:
            position: The position to return
            new_pivot: New pivot price for the fresh base
            notes: Optional notes

        Returns:
            Updated position in State 0
        """
        if position.state != -1.5:
            raise ValueError(f"Position {position.symbol} is not in State -1.5")

        # Clear exit data
        position.close_date = None
        position.close_price = None
        position.close_reason = None
        position.watching_exited_since = None
        position.ma_test_count = 0

        # Set new watchlist data
        position.state = 0
        position.state_updated_at = datetime.now()
        position.pivot = new_pivot
        position.pivot_set_date = date.today()
        position.watch_date = date.today()
        position.needs_sheet_sync = True

        # Add note
        return_note = f"[{datetime.now().strftime('%Y-%m-%d')}] Returned to watchlist - new base @ ${new_pivot:.2f}"
        if notes:
            return_note += f" ({notes})"

        position.notes = f"{position.notes or ''}\n{return_note}".strip()

        self.session.flush()

        logger.info(f"{position.symbol}: Returned to WATCHLIST with pivot ${new_pivot:.2f}")

        return position

    def reenter_from_watching_exited(
        self,
        position: Position,
        shares: int,
        entry_price: float,
        stop_price: float,
        entry_date: date = None,
        notes: str = None
    ) -> Position:
        """
        Re-enter a position from State -1.5 (new Entry 1).

        Used when MA bounce or pivot retest provides re-entry opportunity.

        Args:
            position: The position to re-enter
            shares: Number of shares
            entry_price: Re-entry price
            stop_price: Stop loss price
            entry_date: Entry date (defaults to today)
            notes: Optional notes

        Returns:
            Updated position in State 1
        """
        if position.state != -1.5:
            raise ValueError(f"Position {position.symbol} is not in State -1.5")

        entry_date = entry_date or date.today()

        # Set entry data
        position.e1_shares = shares
        position.e1_price = entry_price
        position.e1_date = entry_date
        position.entry_date = entry_date
        position.stop_price = stop_price

        # Clear exit data (keeping original_pivot for reference)
        position.close_date = None
        position.close_price = None
        position.close_reason = None
        position.watching_exited_since = None

        # Recalculate
        self._recalculate_position_totals(position, skip_stop_price=True)

        # Set state
        position.state = 1
        position.state_updated_at = datetime.now()
        position.breakout_date = entry_date
        position.needs_sheet_sync = True

        # Add note
        reentry_note = f"[{entry_date.strftime('%Y-%m-%d')}] RE-ENTRY: {shares} shares @ ${entry_price:.2f}"
        if notes:
            reentry_note += f" ({notes})"

        position.notes = f"{position.notes or ''}\n{reentry_note}".strip()

        self.session.flush()

        logger.info(
            f"{position.symbol}: RE-ENTERED from WATCHING_EXITED "
            f"({shares} shares @ ${entry_price:.2f})"
        )

        return position

    def expire_watching_exited(self, days_threshold: int = 60) -> int:
        """
        Archive positions in State -1.5 that have been there too long.

        Called daily by maintenance task.

        Args:
            days_threshold: Days after which to auto-expire (default 60)

        Returns:
            Number of positions expired
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days_threshold)

        expired = self.session.query(Position).filter(
            Position.state == -1.5,
            Position.watching_exited_since < cutoff
        ).all()

        for pos in expired:
            pos.state = -2  # Archive to STOPPED_OUT
            pos.state_updated_at = datetime.now()
            pos.needs_sheet_sync = True
            pos.notes = f"{pos.notes or ''}\n[{datetime.now().strftime('%Y-%m-%d')}] Auto-expired from re-entry watch after {days_threshold} days".strip()

            logger.info(
                f"{pos.symbol}: Expired from WATCHING_EXITED after {days_threshold} days"
            )

        self.session.flush()
        return len(expired)

    def increment_ma_test_count(self, position: Position) -> int:
        """
        Increment the MA test count for a State -1.5 position.

        Called when an MA bounce is detected. After 3 tests, probability decreases.

        Args:
            position: Position to update

        Returns:
            New MA test count
        """
        if position.state != -1.5:
            return position.ma_test_count or 0

        position.ma_test_count = (position.ma_test_count or 0) + 1
        self.session.flush()

        logger.debug(
            f"{position.symbol}: MA test count incremented to {position.ma_test_count}"
        )

        return position.ma_test_count
