"""
Google Sheets Position Sync Service
===================================
Syncs position data from SQLite to Google Sheets for TrendSpider integration.

Usage:
    from canslim_monitor.integrations.sheets_sync import SheetsSync

    sync = SheetsSync(config, db_manager)
    result = sync.sync_all()
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.data.repositories import RepositoryManager
from canslim_monitor.data.models import Position
from canslim_monitor.utils.logging import get_logger

logger = get_logger('sheets')


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    updated: int = 0
    inserted: int = 0
    deleted: int = 0      # Closed positions removed from sheet
    errors: int = 0
    error_messages: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class SheetsSync:
    """
    Google Sheets sync service for position data.

    Pushes position changes from SQLite to Google Sheets
    to maintain TrendSpider chart overlay functionality.
    """

    # Google Sheets API scopes
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # Column mapping: DB field -> Sheet column letter
    # Matches CANSLIM Position Manager V36 Template structure
    COLUMN_MAP = {
        # Column A-K: Core Position Data
        'portfolio': 'A',
        'symbol': 'B',
        'state': 'C',
        'pattern': 'D',
        'pivot': 'E',
        'e1_shares': 'F',
        'e1_price': 'G',
        'e2_shares': 'H',
        'e2_price': 'I',
        'e3_shares': 'J',
        'e3_price': 'K',

        # Column L-O: Take Profit Tracking
        'tp1_sold': 'L',
        'tp1_price': 'M',
        'tp2_sold': 'N',
        'tp2_price': 'O',

        # Column P-R: Risk Parameters
        'hard_stop_pct': 'P',
        'tp1_pct': 'Q',
        'tp2_pct': 'R',

        # Column S-U: Dates
        'watch_date': 'S',
        'entry_date': 'T',
        'breakout_date': 'U',

        # Column V-X: Base Characteristics
        'base_stage': 'V',
        'base_depth': 'W',
        'base_length': 'X',

        # Column Y-AF: CANSLIM Ratings
        'rs_rating': 'Y',
        'comp_rating': 'Z',
        'eps_rating': 'AA',
        'ad_rating': 'AB',
        'ud_vol_ratio': 'AC',
        'group_rank': 'AD',
        'fund_count': 'AE',
        'prior_uptrend': 'AF',

        # Column AG-AH: Pyramid Flags
        'py1_done': 'AG',
        'py2_done': 'AH',

        # Column AI-AJ: Other
        'earnings_date': 'AI',
        'notes': 'AJ',

        # Column AK-AO: Calculated Fields
        'total_shares': 'AK',
        'avg_cost': 'AL',
        'stop_price': 'AM',
        'tp1_target': 'AN',
        'tp2_target': 'AO',
    }

    # Sheet header row (1-indexed)
    HEADER_ROW = 1
    # First data row
    DATA_START_ROW = 2
    # Last column in sheet (AO = column 41)
    LAST_COLUMN = 'AO'

    def __init__(
        self,
        config: Dict[str, Any],
        db_manager: DatabaseManager = None
    ):
        """
        Initialize Sheets sync service.

        Args:
            config: Configuration dict with google_sheets section
            db_manager: Database manager instance
        """
        self.config = config
        self.db = db_manager

        # Extract sheets config
        sheets_config = config.get('google_sheets', {})
        self.enabled = sheets_config.get('enabled', False)
        self.spreadsheet_id = sheets_config.get('spreadsheet_id', '')
        self.sheet_name = sheets_config.get('sheet_name', 'Positions')
        self.credentials_path = sheets_config.get('credentials_path', '')

        # API service (lazy initialization)
        self._service = None

        # Sync state
        self.last_sync: Optional[datetime] = None
        self.last_error: Optional[str] = None

    @property
    def service(self):
        """Lazy-load Google Sheets API service."""
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self):
        """Authenticate with Google Sheets API."""
        try:
            credentials = Credentials.from_service_account_file(
                self.credentials_path,
                scopes=self.SCOPES
            )
            return build('sheets', 'v4', credentials=credentials)
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets: {e}")
            raise

    def sync_all(self, force: bool = False) -> SyncResult:
        """
        Sync all positions that need syncing.
        - Active positions (state >= 0): Insert or Update in sheet
        - Closed positions (state < 0): Delete from sheet

        Args:
            force: If True, sync all active positions regardless of needs_sheet_sync flag

        Returns:
            SyncResult with sync statistics
        """
        start_time = datetime.now()
        result = SyncResult(success=True)

        if not self.enabled:
            logger.warning("Sheets sync is disabled in config")
            result.success = False
            result.error_messages.append("Sheets sync disabled")
            return result

        try:
            session = self.db.get_new_session()
            repos = RepositoryManager(session)

            # Get positions to sync
            if force:
                # Force sync: get all ACTIVE positions (state >= 0)
                all_positions = repos.positions.get_all(include_closed=False)
                positions_to_sync = [p for p in all_positions if p.state >= 0]
            else:
                # Normal sync: get positions needing sync
                positions_to_sync = repos.positions.get_needing_sync()

            # Separate into active (sync) vs closed (delete)
            active_positions = [p for p in positions_to_sync if p.state >= 0]
            closed_positions = [p for p in positions_to_sync if p.state < 0]

            # Get existing sheet data to determine update vs insert
            existing_rows = self._get_existing_rows()

            # ALWAYS check for orphaned rows (even if no positions need sync)
            # This catches deleted positions that are no longer in the database
            all_db_symbols = set(p.symbol.upper() for p in repos.positions.get_all(include_closed=True))
            orphaned_symbols = set(existing_rows.keys()) - all_db_symbols

            logger.info(f"Sync: {len(active_positions)} active, {len(closed_positions)} to delete, {len(orphaned_symbols)} orphaned")

            # === HANDLE ACTIVE POSITIONS (Insert/Update) ===
            updates = []
            inserts = []

            for position in active_positions:
                row_data = self._position_to_row(position)
                symbol = position.symbol.upper()

                if symbol in existing_rows:
                    # Update existing row
                    row_num = existing_rows[symbol]
                    updates.append((row_num, row_data, position))
                else:
                    # Insert new row
                    inserts.append((row_data, position))

            # Execute batch updates
            if updates:
                update_count = self._batch_update(updates)
                result.updated = update_count

            # Execute inserts
            if inserts:
                insert_count = self._batch_insert(inserts, existing_rows)
                result.inserted = insert_count

            # === HANDLE CLOSED POSITIONS (Delete from sheet) ===
            deleted_count = 0
            for position in closed_positions:
                symbol = position.symbol.upper()
                if symbol in existing_rows:
                    row_num = existing_rows[symbol]
                    if self._delete_row(row_num):
                        deleted_count += 1
                        logger.info(f"Deleted {symbol} (state={position.state}) from row {row_num}")
                        # Update existing_rows since row numbers shift after delete
                        existing_rows = self._get_existing_rows()

            # === HANDLE ORPHANED ROWS (symbols in sheet but not in DB) ===
            # Orphaned symbols were already calculated at the top
            if orphaned_symbols:
                logger.info(f"Deleting {len(orphaned_symbols)} orphaned symbols from sheet: {list(orphaned_symbols)[:5]}")
                for symbol in orphaned_symbols:
                    row_num = existing_rows[symbol]
                    if self._delete_row(row_num):
                        deleted_count += 1
                        logger.info(f"Deleted orphaned {symbol} from row {row_num}")
                        # Update existing_rows since row numbers shift after delete
                        existing_rows = self._get_existing_rows()

            result.deleted = deleted_count

            # Mark all processed positions as synced
            for position in positions_to_sync:
                repos.positions.mark_synced(position)

            session.commit()

            self.last_sync = datetime.now()
            self.last_error = None

        except HttpError as e:
            logger.error(f"Google Sheets API error: {e}")
            result.success = False
            result.errors += 1
            result.error_messages.append(f"API Error: {e.reason}")
            self.last_error = str(e)

        except Exception as e:
            logger.error(f"Sync error: {e}", exc_info=True)
            result.success = False
            result.errors += 1
            result.error_messages.append(str(e))
            self.last_error = str(e)

        finally:
            session.close()

        result.duration_seconds = (datetime.now() - start_time).total_seconds()
        logger.info(f"Sync complete: {result.updated} updated, {result.inserted} inserted, "
                   f"{result.deleted} deleted, {result.errors} errors in {result.duration_seconds:.2f}s")

        return result

    def _delete_row(self, row_num: int) -> bool:
        """
        Delete a row from the sheet.

        Args:
            row_num: Row number to delete (1-indexed)

        Returns:
            True if successful
        """
        try:
            # Get sheet ID (different from spreadsheet ID)
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()

            sheet_id = None
            for sheet in spreadsheet.get('sheets', []):
                if sheet['properties']['title'] == self.sheet_name:
                    sheet_id = sheet['properties']['sheetId']
                    break

            if sheet_id is None:
                logger.error(f"Sheet '{self.sheet_name}' not found")
                return False

            # Delete the row
            request = {
                'deleteDimension': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': row_num - 1,  # 0-indexed
                        'endIndex': row_num          # exclusive
                    }
                }
            }

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': [request]}
            ).execute()

            return True

        except Exception as e:
            logger.error(f"Failed to delete row {row_num}: {e}")
            return False

    def _get_existing_rows(self) -> Dict[str, int]:
        """
        Get mapping of symbol -> row number from existing sheet.
        Symbol is in column B in V36 format.

        Returns:
            Dict mapping symbol to row number
        """
        try:
            # Read column B (Symbol) to find existing rows
            range_name = f"{self.sheet_name}!B:B"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()

            values = result.get('values', [])

            # Build symbol -> row mapping (skip header row)
            mapping = {}
            for i, row in enumerate(values[self.HEADER_ROW:], start=self.DATA_START_ROW):
                if row and row[0]:
                    symbol = row[0].upper().strip()
                    mapping[symbol] = i

            logger.debug(f"Found {len(mapping)} existing rows in sheet")
            if mapping:
                # Log first few symbols found
                first_symbols = list(mapping.keys())[:5]
                logger.debug(f"First symbols in sheet: {first_symbols}")
            return mapping

        except Exception as e:
            logger.error(f"Failed to get existing rows: {e}")
            return {}

    def _position_to_row(self, position: Position) -> List[Any]:
        """
        Convert Position model to row data for sheet.
        Outputs values in V36 column order (A through AO).

        Args:
            position: Position instance

        Returns:
            List of cell values in column order A-AO
        """
        def fmt(value, field_type='str'):
            """Format value for sheet."""
            if value is None:
                return ''
            if field_type == 'date':
                if hasattr(value, 'strftime'):
                    return value.strftime('%Y-%m-%d')
                return str(value) if value else ''
            if field_type == 'bool':
                return 1 if value else 0
            if field_type == 'float':
                return round(float(value), 2) if value else ''
            if field_type == 'int':
                return int(value) if value else ''
            return str(value) if value else ''

        # Build row in exact column order A-AO
        row = [
            # A-K: Core Position Data
            fmt(position.portfolio),                    # A: Portfolio
            fmt(position.symbol),                       # B: Symbol
            fmt(position.state, 'int'),                 # C: State
            fmt(position.pattern),                      # D: Pattern
            fmt(position.pivot, 'float'),               # E: Pivot
            fmt(position.e1_shares, 'int'),             # F: E1_Shares
            fmt(position.e1_price, 'float'),            # G: E1_Price
            fmt(position.e2_shares, 'int'),             # H: E2_Shares
            fmt(position.e2_price, 'float'),            # I: E2_Price
            fmt(position.e3_shares, 'int'),             # J: E3_Shares
            fmt(position.e3_price, 'float'),            # K: E3_Price

            # L-O: Take Profit Tracking
            fmt(getattr(position, 'tp1_sold', 0), 'int'),    # L: TP1_Sold
            fmt(getattr(position, 'tp1_price', None), 'float'),  # M: TP1_Price
            fmt(getattr(position, 'tp2_sold', 0), 'int'),    # N: TP2_Sold
            fmt(getattr(position, 'tp2_price', None), 'float'),  # O: TP2_Price

            # P-R: Risk Parameters
            fmt(position.hard_stop_pct, 'float'),       # P: Hard_Stop_Pct
            fmt(getattr(position, 'tp1_pct', 20), 'float'),  # Q: TP1_Pct (default 20%)
            fmt(getattr(position, 'tp2_pct', 25), 'float'),  # R: TP2_Pct (default 25%)

            # S-U: Dates
            fmt(position.watch_date, 'date'),           # S: Watch_Date
            fmt(position.entry_date, 'date'),           # T: Entry_Date
            fmt(position.breakout_date, 'date'),        # U: Breakout_Date

            # V-X: Base Characteristics
            fmt(position.base_stage),                   # V: Base_Stage
            fmt(position.base_depth, 'float'),          # W: Base_Depth
            fmt(position.base_length, 'int'),           # X: Base_Length

            # Y-AF: CANSLIM Ratings
            fmt(position.rs_rating, 'int'),             # Y: RS_Rating
            fmt(position.comp_rating, 'int'),           # Z: COMP_RATING
            fmt(position.eps_rating, 'int'),            # AA: EPS_Rating
            fmt(position.ad_rating),                    # AB: AD_Rating
            fmt(position.ud_vol_ratio, 'float'),        # AC: UD_Vol_Ratio
            fmt(position.group_rank, 'int'),            # AD: Group_Rank
            fmt(position.fund_count, 'int'),            # AE: Fund_Count
            fmt(position.prior_uptrend, 'float'),       # AF: Prior_Uptrend

            # AG-AH: Pyramid Flags
            fmt(getattr(position, 'py1_done', False), 'bool'),  # AG: PY1_Done
            fmt(getattr(position, 'py2_done', False), 'bool'),  # AH: PY2_Done

            # AI-AJ: Other
            fmt(position.earnings_date, 'date'),        # AI: Earnings_Date
            fmt(position.notes),                        # AJ: Notes

            # AK-AO: Calculated Fields
            fmt(position.total_shares, 'int'),          # AK: Total_Shares
            fmt(position.avg_cost, 'float'),            # AL: Avg_Cost
            fmt(position.stop_price, 'float'),          # AM: Stop_Price
            fmt(getattr(position, 'tp1_target', None), 'float'),  # AN: TP1_Target
            fmt(getattr(position, 'tp2_target', None), 'float'),  # AO: TP2_Target
        ]

        return row

    def _batch_update(self, updates: List[Tuple[int, List, Position]]) -> int:
        """
        Batch update existing rows.

        Args:
            updates: List of (row_number, row_data, position) tuples

        Returns:
            Number of rows updated
        """
        if not updates:
            return 0

        # Prepare batch request
        data = []
        for row_num, row_data, position in updates:
            # Range covers all columns A through AO
            range_name = f"{self.sheet_name}!A{row_num}:{self.LAST_COLUMN}{row_num}"

            data.append({
                'range': range_name,
                'values': [row_data]
            })

        # Execute batch update
        body = {
            'valueInputOption': 'USER_ENTERED',
            'data': data
        }

        # DEBUG: Log first update for debugging
        if data:
            logger.debug(f"First update range: {data[0]['range']}")
            logger.debug(f"First update values (first 5 cols): {data[0]['values'][0][:5]}")

        result = self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body=body
        ).execute()

        logger.debug(f"Batch updated {len(updates)} rows")
        return result.get('totalUpdatedRows', 0)

    def _batch_insert(
        self,
        inserts: List[Tuple[List, Position]],
        existing_rows: Dict[str, int]
    ) -> int:
        """
        Insert new rows at the end of the sheet.

        Args:
            inserts: List of (row_data, position) tuples
            existing_rows: Current symbol -> row mapping

        Returns:
            Number of rows inserted
        """
        if not inserts:
            return 0

        # Find next available row
        next_row = max(existing_rows.values(), default=self.HEADER_ROW) + 1

        # Prepare values
        values = [row_data for row_data, _ in inserts]

        # DEBUG: Log first insert for debugging
        if values:
            logger.debug(f"First insert values (first 5 cols): {values[0][:5]}")

        # Range covers all columns A through AO
        range_name = f"{self.sheet_name}!A{next_row}:{self.LAST_COLUMN}"
        logger.debug(f"Insert range: {range_name}")

        # Execute append
        result = self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': values}
        ).execute()

        # Update sheet_row_id for inserted positions
        for i, (_, position) in enumerate(inserts):
            position.sheet_row_id = position.symbol.upper()

        logger.info(f"Inserted {len(inserts)} new rows starting at row {next_row}")
        return result.get('updates', {}).get('updatedRows', 0)

    def get_status(self) -> Dict[str, Any]:
        """
        Get current sync status for GUI display.

        Returns:
            Status dict with sync info
        """
        return {
            'enabled': self.enabled,
            'spreadsheet_id': self.spreadsheet_id[:20] + '...' if self.spreadsheet_id else None,
            'sheet_name': self.sheet_name,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'last_error': self.last_error,
        }
