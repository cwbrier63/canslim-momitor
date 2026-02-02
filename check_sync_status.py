"""Quick script to check position sync status."""
import sys
import os

# Add to path
sys.path.insert(0, 'c:/trading/canslim_monitor')

from canslim_monitor.data.database import get_database
from canslim_monitor.data.repositories import RepositoryManager
from collections import Counter

db = get_database('c:/trading/canslim_monitor/canslim_positions.db')
with db.get_session() as session:
    repos = RepositoryManager(session)

    # Get all positions
    all_pos = repos.positions.get_all(include_closed=True)
    active = [p for p in all_pos if p.state >= 0]
    needs_sync = [p for p in all_pos if p.needs_sheet_sync and p.state >= 0]

    print(f'Total positions: {len(all_pos)}')
    print(f'Active (state >= 0): {len(active)}')
    print(f'Needs sync (active): {len(needs_sync)}')
    print()

    # Show state breakdown
    states = Counter([p.state for p in all_pos])
    print('State breakdown:')
    for state in sorted(states.keys()):
        count = states[state]
        synced = len([p for p in all_pos if p.state == state and not p.needs_sheet_sync])
        print(f'  State {state}: {count} total, {synced} already synced')

    print()
    print('Sample active positions (first 5):')
    for p in active[:5]:
        print(f'  {p.symbol}: state={p.state}, needs_sync={p.needs_sheet_sync}')
