"""
Migration: Create learning engine tables for A/B testing and factor analysis.

Creates:
- ab_tests: Tracks A/B test configurations
- ab_test_assignments: Tracks which positions use which weight set
- factor_correlations: Stores factor correlation analysis results

Run: python migrations/add_learning_tables.py
"""

import sqlite3
from pathlib import Path
import sys


def get_db_path() -> Path:
    """Get database path from config or use default."""
    default_path = Path("c:/trading/canslim_monitor/canslim_positions.db")
    return default_path


def run_migration():
    """Create learning engine tables."""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Running migration on: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # =========================================
    # Table: ab_tests
    # =========================================
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='ab_tests'
    """)

    if cursor.fetchone():
        print("  Table 'ab_tests' already exists - skipping creation")
    else:
        print("  Creating table: ab_tests")
        cursor.execute("""
            CREATE TABLE ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                description TEXT,

                -- Test configuration
                control_weights_id INTEGER,
                treatment_weights_id INTEGER,
                split_ratio REAL DEFAULT 0.5,

                -- Status
                status VARCHAR(20) DEFAULT 'draft',
                started_at DATETIME,
                ended_at DATETIME,

                -- Sample tracking
                min_sample_size INTEGER DEFAULT 30,
                control_count INTEGER DEFAULT 0,
                treatment_count INTEGER DEFAULT 0,

                -- Results (updated during test)
                control_win_rate REAL,
                treatment_win_rate REAL,
                control_avg_return REAL,
                treatment_avg_return REAL,
                p_value REAL,
                is_significant INTEGER DEFAULT 0,

                -- Winner selection
                winner VARCHAR(20),
                winner_selected_at DATETIME,

                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (control_weights_id) REFERENCES learned_weights(id),
                FOREIGN KEY (treatment_weights_id) REFERENCES learned_weights(id)
            )
        """)

        print("  Creating index: idx_ab_tests_status")
        cursor.execute("""
            CREATE INDEX idx_ab_tests_status
            ON ab_tests(status)
        """)

    # =========================================
    # Table: ab_test_assignments
    # =========================================
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='ab_test_assignments'
    """)

    if cursor.fetchone():
        print("  Table 'ab_test_assignments' already exists - skipping creation")
    else:
        print("  Creating table: ab_test_assignments")
        cursor.execute("""
            CREATE TABLE ab_test_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ab_test_id INTEGER NOT NULL,
                position_id INTEGER NOT NULL,

                -- Assignment
                group_name VARCHAR(20) NOT NULL,
                weights_id INTEGER NOT NULL,
                assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,

                -- Score at assignment
                score_at_assignment INTEGER,
                grade_at_assignment VARCHAR(2),

                -- Outcome (updated when position closes)
                outcome VARCHAR(20),
                return_pct REAL,
                holding_days INTEGER,
                outcome_recorded_at DATETIME,

                FOREIGN KEY (ab_test_id) REFERENCES ab_tests(id) ON DELETE CASCADE,
                FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE,
                FOREIGN KEY (weights_id) REFERENCES learned_weights(id)
            )
        """)

        print("  Creating index: idx_ab_assignments_test")
        cursor.execute("""
            CREATE INDEX idx_ab_assignments_test
            ON ab_test_assignments(ab_test_id, group_name)
        """)

        print("  Creating index: idx_ab_assignments_position")
        cursor.execute("""
            CREATE INDEX idx_ab_assignments_position
            ON ab_test_assignments(position_id)
        """)

    # =========================================
    # Table: factor_correlations
    # =========================================
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='factor_correlations'
    """)

    if cursor.fetchone():
        print("  Table 'factor_correlations' already exists - skipping creation")
    else:
        print("  Creating table: factor_correlations")
        cursor.execute("""
            CREATE TABLE factor_correlations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_date DATE NOT NULL,

                -- Analysis period
                sample_start_date DATE,
                sample_end_date DATE,
                sample_size INTEGER,

                -- Factor being analyzed
                factor_name VARCHAR(50) NOT NULL,
                factor_type VARCHAR(20),

                -- Correlation metrics
                correlation_return REAL,
                correlation_win_rate REAL,
                p_value_return REAL,
                p_value_win_rate REAL,

                -- Success rate by bucket
                low_bucket_win_rate REAL,
                mid_bucket_win_rate REAL,
                high_bucket_win_rate REAL,

                -- Averages
                low_bucket_avg_return REAL,
                mid_bucket_avg_return REAL,
                high_bucket_avg_return REAL,

                -- Statistical significance
                is_significant INTEGER DEFAULT 0,
                recommended_direction VARCHAR(10),

                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        print("  Creating index: idx_factor_correlations_date")
        cursor.execute("""
            CREATE INDEX idx_factor_correlations_date
            ON factor_correlations(analysis_date, factor_name)
        """)

    # =========================================
    # Add ab_test_id column to learned_weights
    # =========================================
    cursor.execute("PRAGMA table_info(learned_weights)")
    columns = {row[1] for row in cursor.fetchall()}

    if 'ab_test_id' in columns:
        print("  Column 'ab_test_id' already exists in learned_weights - skipping")
    else:
        print("  Adding column: learned_weights.ab_test_id")
        cursor.execute("""
            ALTER TABLE learned_weights
            ADD COLUMN ab_test_id INTEGER REFERENCES ab_tests(id)
        """)

    if 'version' not in columns:
        print("  Adding column: learned_weights.version")
        cursor.execute("""
            ALTER TABLE learned_weights
            ADD COLUMN version INTEGER DEFAULT 1
        """)

    if 'parent_weights_id' not in columns:
        print("  Adding column: learned_weights.parent_weights_id")
        cursor.execute("""
            ALTER TABLE learned_weights
            ADD COLUMN parent_weights_id INTEGER REFERENCES learned_weights(id)
        """)

    conn.commit()
    conn.close()

    print("\nMigration complete.")


def verify_migration():
    """Verify the migration was successful."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables_to_check = ['ab_tests', 'ab_test_assignments', 'factor_correlations']
    all_exist = True

    for table in tables_to_check:
        cursor.execute(f"""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='{table}'
        """)
        exists = cursor.fetchone() is not None
        status = "[OK]" if exists else "[FAIL]"
        print(f"  {status} Table '{table}': {'exists' if exists else 'MISSING'}")
        all_exist = all_exist and exists

    # Check learned_weights columns
    cursor.execute("PRAGMA table_info(learned_weights)")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = ['ab_test_id', 'version', 'parent_weights_id']
    for col in required_columns:
        exists = col in columns
        status = "[OK]" if exists else "[FAIL]"
        print(f"  {status} Column 'learned_weights.{col}': {'exists' if exists else 'MISSING'}")
        all_exist = all_exist and exists

    conn.close()

    if all_exist:
        print("\nVERIFICATION PASSED - All learning engine tables created")
        return True
    else:
        print("\nVERIFICATION FAILED - Some tables or columns are missing")
        return False


def show_table_info():
    """Show table information."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables = ['ab_tests', 'ab_test_assignments', 'factor_correlations']

    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()

        if columns:
            print(f"\nTable: {table}")
            print("-" * 60)
            for col in columns:
                print(f"  {col[1]:25} {col[2]:15} {'NOT NULL' if col[3] else ''}")

            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  Records: {count}")

    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("CANSLIM Monitor - Learning Engine Tables Migration")
    print("=" * 60)

    run_migration()
    print()
    verify_migration()
    show_table_info()
