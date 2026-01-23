"""
CANSLIM Monitor - Data Seeder
Phase 1: Database Foundation

Seeds the database with initial data from Google Sheets or CSV exports.
Handles migration of existing watchlist data.
"""

import os
import csv
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from pathlib import Path

from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.data.models import Position
from canslim_monitor.data.repositories import PositionRepository
from canslim_monitor.utils.logging import get_logger

logger = get_logger('database')


class DataSeeder:
    """
    Seeds the database with initial data from various sources.
    """
    
    # Column name mappings (handle various naming conventions)
    COLUMN_MAPPINGS = {
        # Symbol
        'symbol': ['symbol', 'ticker', 'sym', 'stock'],
        
        # State
        'state': ['state', 'status', 'position_state'],
        
        # Pivot
        'pivot': ['pivot', 'pivot_price', 'buy_point', 'entry_point'],
        
        # Pattern
        'pattern': ['pattern', 'base_pattern', 'setup', 'base_type'],
        
        # Portfolio
        'portfolio': ['portfolio', 'account', 'port'],
        
        # Stage
        'base_stage': ['stage', 'base_stage', 'base_count'],
        
        # CANSLIM Factors
        'rs_rating': ['rs', 'rs_rating', 'relative_strength', 'rs rating'],
        'eps_rating': ['eps', 'eps_rating', 'eps rating'],
        'comp_rating': ['comp', 'comp_rating', 'composite', 'composite rating'],
        'ad_rating': ['ad', 'ad_rating', 'a/d', 'acc_dist', 'a/d rating'],
        'ud_vol_ratio': ['ud', 'ud_ratio', 'u/d', 'ud_vol_ratio', 'u/d ratio'],
        'group_rank': ['group_rank', 'group', 'industry_rank', 'grp rank'],
        'fund_count': ['funds', 'fund_count', '# funds', 'fund cnt'],
        
        # Base characteristics
        'base_depth': ['depth', 'base_depth', 'correction', 'base depth'],
        'base_length': ['length', 'base_length', 'weeks', 'base length'],
        'prior_uptrend': ['uptrend', 'prior_uptrend', 'prior_run', 'prior uptrend'],
        
        # Risk parameters
        'hard_stop_pct': ['stop', 'stop_pct', 'hard_stop', 'stop %'],
        'earnings_date': ['earnings', 'earnings_date', 'er date'],
        
        # Entry data
        'e1_shares': ['e1_shares', 'shares', 'entry_shares', 'e1 shares'],
        'e1_price': ['e1_price', 'entry_price', 'entry', 'e1 price'],
        'e1_date': ['e1_date', 'entry_date', 'e1 date'],
        
        # Notes
        'notes': ['notes', 'comments', 'memo'],
    }
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize data seeder.
        
        Args:
            db_manager: Database manager instance
        """
        self.db_manager = db_manager
    
    def seed_from_csv(
        self,
        csv_path: str,
        portfolio: str = 'CWB',
        skip_existing: bool = True,
        update_existing: bool = False
    ) -> Dict[str, Any]:
        """
        Seed positions from a CSV file.
        
        Args:
            csv_path: Path to CSV file
            portfolio: Default portfolio if not in data
            skip_existing: Skip symbols that already exist
            update_existing: Update existing symbols with new data
        
        Returns:
            Dict with seeding results (created, updated, skipped, errors)
        """
        results = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': [],
        }
        
        if not os.path.exists(csv_path):
            results['errors'].append(f"File not found: {csv_path}")
            logger.error(f"CSV file not found: {csv_path}")
            return results
        
        # Read CSV
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        logger.info(f"Read {len(rows)} rows from {csv_path}")
        
        # Build column mapping for this file
        column_map = self._build_column_map(rows[0].keys() if rows else [])
        logger.debug(f"Column mapping: {column_map}")
        
        # Process rows
        with self.db_manager.get_session() as session:
            repo = PositionRepository(session)
            
            for row in rows:
                try:
                    # Extract symbol
                    symbol = self._get_value(row, column_map, 'symbol')
                    if not symbol:
                        continue
                    
                    symbol = symbol.upper().strip()
                    
                    # Check if exists
                    existing = repo.get_by_symbol(symbol, portfolio)
                    
                    if existing:
                        if update_existing:
                            self._update_position(existing, row, column_map)
                            results['updated'] += 1
                            logger.debug(f"Updated {symbol}")
                        else:
                            results['skipped'] += 1
                            logger.debug(f"Skipped existing {symbol}")
                        continue
                    
                    if skip_existing and existing:
                        results['skipped'] += 1
                        continue
                    
                    # Create new position
                    position_data = self._extract_position_data(row, column_map, portfolio)
                    position_data['symbol'] = symbol
                    
                    repo.create(**position_data)
                    results['created'] += 1
                    logger.debug(f"Created {symbol}")
                    
                except Exception as e:
                    error_msg = f"Error processing row: {row.get('symbol', 'unknown')}: {str(e)}"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
        
        logger.info(
            f"Seeding complete: {results['created']} created, "
            f"{results['updated']} updated, {results['skipped']} skipped, "
            f"{len(results['errors'])} errors"
        )
        
        return results
    
    def seed_from_google_sheets(
        self,
        spreadsheet_id: str,
        sheet_name: str = 'Positions',
        credentials_path: str = None,
        portfolio: str = 'CWB',
        skip_existing: bool = True
    ) -> Dict[str, Any]:
        """
        Seed positions directly from Google Sheets.
        
        Args:
            spreadsheet_id: Google Sheets spreadsheet ID
            sheet_name: Name of the sheet to read
            credentials_path: Path to Google API credentials
            portfolio: Default portfolio
            skip_existing: Skip existing symbols
        
        Returns:
            Dict with seeding results
        """
        results = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': [],
        }
        
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            results['errors'].append("Google API libraries not installed")
            logger.error("Google API libraries not installed. Run: pip install google-api-python-client google-auth")
            return results
        
        try:
            # Authenticate
            credentials = Credentials.from_service_account_file(
                credentials_path or os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'),
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            
            service = build('sheets', 'v4', credentials=credentials)
            sheet = service.spreadsheets()
            
            # Read data
            result = sheet.values().get(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A:ZZ'
            ).execute()
            
            values = result.get('values', [])
            
            if not values:
                logger.warning("No data found in sheet")
                return results
            
            # Convert to dict format
            headers = values[0]
            rows = [dict(zip(headers, row + [''] * (len(headers) - len(row)))) 
                    for row in values[1:]]
            
            # Build column mapping
            column_map = self._build_column_map(headers)
            
            # Process rows (similar to CSV)
            with self.db_manager.get_session() as session:
                repo = PositionRepository(session)
                
                for row in rows:
                    try:
                        symbol = self._get_value(row, column_map, 'symbol')
                        if not symbol:
                            continue
                        
                        symbol = symbol.upper().strip()
                        
                        existing = repo.get_by_symbol(symbol, portfolio)
                        
                        if existing and skip_existing:
                            results['skipped'] += 1
                            continue
                        
                        position_data = self._extract_position_data(row, column_map, portfolio)
                        position_data['symbol'] = symbol
                        
                        repo.create(**position_data)
                        results['created'] += 1
                        
                    except Exception as e:
                        results['errors'].append(f"Error: {symbol}: {str(e)}")
            
            logger.info(f"Google Sheets seeding complete: {results['created']} created")
            
        except Exception as e:
            results['errors'].append(f"Google Sheets error: {str(e)}")
            logger.error(f"Google Sheets error: {str(e)}")
        
        return results
    
    def export_to_csv(
        self,
        csv_path: str,
        include_closed: bool = False
    ) -> int:
        """
        Export positions to CSV file.
        
        Args:
            csv_path: Output CSV file path
            include_closed: Include closed positions
        
        Returns:
            Number of positions exported
        """
        with self.db_manager.get_session() as session:
            repo = PositionRepository(session)
            positions = repo.get_all(include_closed=include_closed)
            
            if not positions:
                logger.warning("No positions to export")
                return 0
            
            # Define columns to export
            columns = [
                'symbol', 'portfolio', 'state', 'pivot', 'pattern', 'base_stage',
                'rs_rating', 'eps_rating', 'comp_rating', 'ad_rating', 'ud_vol_ratio',
                'group_rank', 'fund_count', 'base_depth', 'base_length', 'prior_uptrend',
                'hard_stop_pct', 'earnings_date', 'e1_shares', 'e1_price', 'e1_date',
                'entry_grade', 'entry_score', 'watch_date', 'notes'
            ]
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                
                for position in positions:
                    row = {col: getattr(position, col, '') for col in columns}
                    writer.writerow(row)
            
            logger.info(f"Exported {len(positions)} positions to {csv_path}")
            return len(positions)
    
    def _build_column_map(self, columns: List[str]) -> Dict[str, str]:
        """Build mapping from our field names to actual column names."""
        column_map = {}
        columns_lower = {c.lower().strip(): c for c in columns}
        
        for field, aliases in self.COLUMN_MAPPINGS.items():
            for alias in aliases:
                if alias.lower() in columns_lower:
                    column_map[field] = columns_lower[alias.lower()]
                    break
        
        return column_map
    
    def _get_value(
        self,
        row: Dict,
        column_map: Dict[str, str],
        field: str,
        default: Any = None
    ) -> Any:
        """Get value from row using column mapping."""
        column = column_map.get(field)
        if column:
            return row.get(column, default)
        return default
    
    def _extract_position_data(
        self,
        row: Dict,
        column_map: Dict[str, str],
        portfolio: str
    ) -> Dict[str, Any]:
        """Extract position data from row."""
        data = {
            'portfolio': self._get_value(row, column_map, 'portfolio') or portfolio,
            'state': self._parse_int(self._get_value(row, column_map, 'state', '0')),
            'watch_date': date.today(),
        }
        
        # Pivot and pattern
        pivot = self._get_value(row, column_map, 'pivot')
        if pivot:
            data['pivot'] = self._parse_float(pivot)
        
        pattern = self._get_value(row, column_map, 'pattern')
        if pattern:
            data['pattern'] = pattern.strip()
        
        # Stage
        stage = self._get_value(row, column_map, 'base_stage')
        if stage:
            data['base_stage'] = str(stage).strip()
        
        # CANSLIM factors
        for field in ['rs_rating', 'eps_rating', 'comp_rating', 'group_rank', 'fund_count']:
            value = self._get_value(row, column_map, field)
            if value:
                data[field] = self._parse_int(value)
        
        # AD rating (string)
        ad = self._get_value(row, column_map, 'ad_rating')
        if ad:
            data['ad_rating'] = str(ad).strip().upper()[:1]
        
        # Float fields
        for field in ['ud_vol_ratio', 'base_depth', 'base_length', 'prior_uptrend', 'hard_stop_pct']:
            value = self._get_value(row, column_map, field)
            if value:
                data[field] = self._parse_float(value)
        
        # Entry data
        e1_shares = self._get_value(row, column_map, 'e1_shares')
        if e1_shares:
            data['e1_shares'] = self._parse_int(e1_shares)
        
        e1_price = self._get_value(row, column_map, 'e1_price')
        if e1_price:
            data['e1_price'] = self._parse_float(e1_price)
        
        # Notes
        notes = self._get_value(row, column_map, 'notes')
        if notes:
            data['notes'] = str(notes).strip()
        
        return data
    
    def _update_position(
        self,
        position: Position,
        row: Dict,
        column_map: Dict[str, str]
    ) -> None:
        """Update existing position with new data."""
        updates = self._extract_position_data(row, column_map, position.portfolio)
        
        for key, value in updates.items():
            if value is not None and hasattr(position, key):
                setattr(position, key, value)
    
    def _parse_int(self, value: Any) -> Optional[int]:
        """Parse value as integer."""
        if value is None or value == '':
            return None
        try:
            # Handle percentage strings
            if isinstance(value, str):
                value = value.replace('%', '').strip()
            return int(float(value))
        except (ValueError, TypeError):
            return None
    
    def _parse_float(self, value: Any) -> Optional[float]:
        """Parse value as float."""
        if value is None or value == '':
            return None
        try:
            if isinstance(value, str):
                value = value.replace('%', '').replace(',', '').strip()
            return float(value)
        except (ValueError, TypeError):
            return None


def seed_database(
    db_manager: DatabaseManager,
    source: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Convenience function to seed database.
    
    Args:
        db_manager: Database manager
        source: Path to CSV file or 'sheets' for Google Sheets
        **kwargs: Additional arguments for seeder methods
    
    Returns:
        Seeding results
    """
    seeder = DataSeeder(db_manager)
    
    if source.lower() == 'sheets' or source.startswith('http'):
        return seeder.seed_from_google_sheets(**kwargs)
    else:
        return seeder.seed_from_csv(source, **kwargs)
