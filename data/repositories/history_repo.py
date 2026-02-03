"""
CANSLIM Monitor - Position History Repository

Provides operations for tracking and querying position field changes.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Set
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from canslim_monitor.data.models import PositionHistory, TRACKED_FIELDS

logger = logging.getLogger('canslim.database')


class HistoryRepository:
    """Repository for PositionHistory entity operations."""

    def __init__(self, session: Session):
        self.session = session

    def record_change(
        self,
        position_id: int,
        field_name: str,
        old_value: Any,
        new_value: Any,
        change_source: str = 'manual_edit'
    ) -> PositionHistory:
        """
        Record a single field change.

        Args:
            position_id: ID of the position
            field_name: Name of the field that changed
            old_value: Previous value (will be converted to string)
            new_value: New value (will be converted to string)
            change_source: What triggered the change
                           ('manual_edit', 'state_transition', 'system_calc', 'price_update')

        Returns:
            Created PositionHistory record
        """
        # Convert values to strings for storage
        old_str = self._value_to_string(old_value)
        new_str = self._value_to_string(new_value)

        history = PositionHistory(
            position_id=position_id,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            change_source=change_source,
            changed_at=datetime.now()
        )
        self.session.add(history)
        self.session.flush()

        logger.debug(f"Recorded change for position {position_id}: {field_name} = {old_str} -> {new_str}")
        return history

    def record_changes(
        self,
        position_id: int,
        old_values: Dict[str, Any],
        new_values: Dict[str, Any],
        change_source: str = 'manual_edit',
        fields_to_track: Set[str] = None
    ) -> List[PositionHistory]:
        """
        Record multiple field changes by comparing old and new values.

        Args:
            position_id: ID of the position
            old_values: Dict of field names to old values
            new_values: Dict of field names to new values
            change_source: What triggered the changes
            fields_to_track: Optional set of fields to track (defaults to TRACKED_FIELDS)

        Returns:
            List of created PositionHistory records
        """
        if fields_to_track is None:
            fields_to_track = TRACKED_FIELDS

        records = []
        changed_at = datetime.now()

        for field_name in fields_to_track:
            old_val = old_values.get(field_name)
            new_val = new_values.get(field_name)

            # Only record if values are different
            if self._values_different(old_val, new_val):
                old_str = self._value_to_string(old_val)
                new_str = self._value_to_string(new_val)

                history = PositionHistory(
                    position_id=position_id,
                    field_name=field_name,
                    old_value=old_str,
                    new_value=new_str,
                    change_source=change_source,
                    changed_at=changed_at
                )
                self.session.add(history)
                records.append(history)

                logger.debug(f"Recorded change: {field_name} = {old_str} -> {new_str}")

        if records:
            self.session.flush()
            logger.info(f"Recorded {len(records)} field changes for position {position_id}")

        return records

    def get_prior_value(
        self,
        position_id: int,
        field_name: str
    ) -> Optional[str]:
        """
        Get the most recent prior value for a field.

        Args:
            position_id: ID of the position
            field_name: Name of the field

        Returns:
            The old_value from the most recent change, or None if no history
        """
        history = self.session.query(PositionHistory).filter(
            and_(
                PositionHistory.position_id == position_id,
                PositionHistory.field_name == field_name
            )
        ).order_by(desc(PositionHistory.changed_at)).first()

        return history.old_value if history else None

    def get_field_history(
        self,
        position_id: int,
        field_name: str,
        limit: int = 10
    ) -> List[PositionHistory]:
        """
        Get the change history for a specific field.

        Args:
            position_id: ID of the position
            field_name: Name of the field
            limit: Maximum number of records to return

        Returns:
            List of PositionHistory records, most recent first
        """
        return self.session.query(PositionHistory).filter(
            and_(
                PositionHistory.position_id == position_id,
                PositionHistory.field_name == field_name
            )
        ).order_by(desc(PositionHistory.changed_at)).limit(limit).all()

    def get_position_history(
        self,
        position_id: int,
        limit: int = 50
    ) -> List[PositionHistory]:
        """
        Get all change history for a position.

        Args:
            position_id: ID of the position
            limit: Maximum number of records to return

        Returns:
            List of PositionHistory records, most recent first
        """
        return self.session.query(PositionHistory).filter(
            PositionHistory.position_id == position_id
        ).order_by(desc(PositionHistory.changed_at)).limit(limit).all()

    def get_changed_fields(
        self,
        position_id: int,
        since: datetime = None
    ) -> Set[str]:
        """
        Get the set of fields that have changed (for showing indicators).

        Args:
            position_id: ID of the position
            since: Optional datetime to limit to recent changes

        Returns:
            Set of field names that have history records
        """
        query = self.session.query(PositionHistory.field_name).filter(
            PositionHistory.position_id == position_id
        )

        if since:
            query = query.filter(PositionHistory.changed_at >= since)

        # Get distinct field names
        results = query.distinct().all()
        return {r[0] for r in results}

    def get_recently_changed_fields(
        self,
        position_id: int,
        days: int = 7
    ) -> Set[str]:
        """
        Get fields that changed in the last N days.

        Args:
            position_id: ID of the position
            days: Number of days to look back

        Returns:
            Set of field names that have recent changes
        """
        since = datetime.now() - timedelta(days=days)
        return self.get_changed_fields(position_id, since)

    def get_latest_change_time(
        self,
        position_id: int,
        field_name: str
    ) -> Optional[datetime]:
        """
        Get the time of the most recent change for a field.

        Args:
            position_id: ID of the position
            field_name: Name of the field

        Returns:
            Datetime of the most recent change, or None
        """
        history = self.session.query(PositionHistory.changed_at).filter(
            and_(
                PositionHistory.position_id == position_id,
                PositionHistory.field_name == field_name
            )
        ).order_by(desc(PositionHistory.changed_at)).first()

        return history[0] if history else None

    def delete_position_history(self, position_id: int) -> int:
        """
        Delete all history for a position.

        Args:
            position_id: ID of the position

        Returns:
            Number of records deleted
        """
        count = self.session.query(PositionHistory).filter(
            PositionHistory.position_id == position_id
        ).delete()
        self.session.flush()
        return count

    def _value_to_string(self, value: Any) -> Optional[str]:
        """Convert a value to string for storage."""
        if value is None:
            return None
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, (datetime,)):
            return value.isoformat()
        if isinstance(value, float):
            # Format floats nicely, removing trailing zeros
            return f"{value:.6f}".rstrip('0').rstrip('.')
        return str(value)

    def _values_different(self, old_val: Any, new_val: Any) -> bool:
        """
        Check if two values are meaningfully different.

        Handles None comparisons and float precision.
        """
        # Both None - not different
        if old_val is None and new_val is None:
            return False

        # One is None, other isn't - different
        if old_val is None or new_val is None:
            return True

        # For floats, use small epsilon for comparison
        if isinstance(old_val, float) and isinstance(new_val, float):
            return abs(old_val - new_val) > 0.0001

        # For other types, use string comparison
        return str(old_val) != str(new_val)
