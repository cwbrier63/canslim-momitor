"""Test what data is being generated for sync."""
import sys
sys.path.insert(0, 'c:/trading/canslim_monitor')

from canslim_monitor.data.database import get_database
from canslim_monitor.data.repositories import RepositoryManager
from canslim_monitor.integrations.sheets_sync import SheetsSync
from canslim_monitor.utils.config import load_config

# Load config and database
config = load_config('c:/trading/canslim_monitor/user_config.yaml')
db = get_database('c:/trading/canslim_monitor/canslim_positions.db')

# Create sync service
sync = SheetsSync(config, db)

# Get one position and convert to row
with db.get_session() as session:
    repos = RepositoryManager(session)
    positions = repos.positions.get_needing_sync()

    if positions:
        pos = positions[0]
        print(f"Position: {pos.symbol}")
        print(f"State: {pos.state}")
        print(f"Portfolio: {pos.portfolio}")
        print(f"Pivot: {pos.pivot}")
        print(f"Pattern: {pos.pattern}")
        print()

        row_data = sync._position_to_row(pos)
        print(f"Row data (first 10 fields):")
        for i, val in enumerate(row_data[:10]):
            field_names = ['Portfolio', 'Symbol', 'State', 'Pattern', 'Pivot',
                          'E1_Shares', 'E1_Price', 'E2_Shares', 'E2_Price', 'E3_Shares']
            print(f"  {field_names[i]:12} (col {chr(65+i)}): '{val}'")
    else:
        print("No positions need sync")
