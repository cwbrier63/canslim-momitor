"""
Reset sync flags for all active positions.
Run this if positions exist but won't sync.
"""
import sqlite3

db_path = "c:/trading/canslim_monitor/canslim_positions.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check current status
cursor.execute("""
    SELECT
        state,
        COUNT(*) as total,
        SUM(CASE WHEN needs_sheet_sync = 1 THEN 1 ELSE 0 END) as needs_sync
    FROM positions
    GROUP BY state
    ORDER BY state
""")

print("Current position status:")
print("State | Total | Needs Sync")
print("------|-------|------------")
for row in cursor.fetchall():
    print(f"{row[0]:5} | {row[1]:5} | {row[2]:10}")

# Count active positions
cursor.execute("SELECT COUNT(*) FROM positions WHERE state >= 0")
active_count = cursor.fetchone()[0]
print(f"\nTotal ACTIVE positions (state >= 0): {active_count}")

if active_count > 0:
    print("\nResetting needs_sheet_sync=TRUE for all active positions...")
    cursor.execute("""
        UPDATE positions
        SET needs_sheet_sync = 1
        WHERE state >= 0
    """)
    conn.commit()
    print(f"✓ Reset {cursor.rowcount} positions")
    print("\nNow try 'Sync to Google Sheets' (regular sync will work now)")
else:
    print("\n⚠ No active positions found. All positions are closed (state < 0).")
    print("  There's nothing to sync to Google Sheets.")

conn.close()
