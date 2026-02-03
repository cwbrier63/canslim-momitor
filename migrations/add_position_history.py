"""
Migration: Create position_history table for tracking position field changes.

The position_history table stores historical values of position fields,
allowing users to see how values changed throughout the position lifecycle.

Run: python migrations/add_position_history.py
"""

import sqlite3
from pathlib import Path
import sys


def get_db_path() -> Path:
    """Get database path from config or use default."""
    default_path = Path("c:/trading/canslim_monitor/canslim_positions.db")
    return default_path


def run_migration():
    """Create the position_history table."""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Running migration on: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if table already exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='position_history'
    """)

    if cursor.fetchone():
        print("  Table 'position_history' already exists - skipping creation")
    else:
        print("  Creating table: position_history")
        cursor.execute("""
            CREATE TABLE position_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL,
                changed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                change_source VARCHAR(30),
                field_name VARCHAR(50) NOT NULL,
                old_value VARCHAR(500),
                new_value VARCHAR(500),
                FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE
            )
        """)

        # Create indexes for efficient lookups
        print("  Creating index: idx_position_history_lookup")
        cursor.execute("""
            CREATE INDEX idx_position_history_lookup
            ON position_history(position_id, field_name)
        """)

        print("  Creating index: idx_position_history_recent")
        cursor.execute("""
            CREATE INDEX idx_position_history_recent
            ON position_history(position_id, changed_at)
        """)

        print("  Creating index: idx_position_history_changed_at")
        cursor.execute("""
            CREATE INDEX idx_position_history_changed_at
            ON position_history(changed_at)
        """)

    conn.commit()
    conn.close()

    print("\nMigration complete.")


def verify_migration():
    """Verify the migration was successful."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='position_history'
    """)
    table_exists = cursor.fetchone() is not None

    # Check columns
    if table_exists:
        cursor.execute("PRAGMA table_info(position_history)")
        columns = {row[1] for row in cursor.fetchall()}
        required = {'id', 'position_id', 'changed_at', 'change_source', 'field_name', 'old_value', 'new_value'}
        missing = required - columns
    else:
        missing = {'table'}

    # Check indexes
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND tbl_name='position_history'
    """)
    indexes = {row[0] for row in cursor.fetchall()}

    conn.close()

    if not table_exists:
        print("VERIFICATION FAILED - Table 'position_history' does not exist")
        return False
    elif missing:
        print(f"VERIFICATION FAILED - Missing columns: {missing}")
        return False
    else:
        print("VERIFICATION PASSED - position_history table created successfully")
        print(f"  Indexes: {indexes}")
        return True


def show_table_info():
    """Show current table information."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(position_history)")
    columns = cursor.fetchall()

    print("\nTable: position_history")
    print("-" * 50)
    for col in columns:
        print(f"  {col[1]:20} {col[2]:15} {'NOT NULL' if col[3] else ''}")

    cursor.execute("SELECT COUNT(*) FROM position_history")
    count = cursor.fetchone()[0]
    print(f"\nTotal records: {count}")

    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("CANSLIM Monitor - Position History Table Migration")
    print("=" * 60)

    run_migration()
    print()
    verify_migration()
    show_table_info()
