"""
Migration: Create provider abstraction layer tables

Creates three tables for the data provider abstraction layer:
  - provider_config: Provider instance configuration (one row per provider-domain)
  - provider_credentials: API keys, OAuth tokens per provider
  - provider_health_log: Append-only health/uptime history

Usage:
    python -m migrations.add_provider_tables --db "C:/Trading/canslim_monitor/canslim_positions.db"
"""

import argparse
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path


def table_exists(cursor, table: str) -> bool:
    """Check if a table exists."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def create_provider_tables(db_path: str, backup: bool = True):
    """Create provider abstraction layer tables."""

    db_path = Path(db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        return False

    # Create backup
    if backup:
        backup_path = db_path.with_suffix(
            f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        print(f"Creating backup: {backup_path}")
        shutil.copy(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        created = 0

        # ------------------------------------------------------------------
        # 1. provider_config
        # ------------------------------------------------------------------
        if table_exists(cursor, 'provider_config'):
            print("Table 'provider_config' already exists. Skipping.")
        else:
            print("Creating table 'provider_config'...")
            cursor.execute("""
                CREATE TABLE provider_config (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            VARCHAR(50)  NOT NULL UNIQUE,
                    display_name    VARCHAR(100),
                    provider_type   VARCHAR(20)  NOT NULL,
                    implementation  VARCHAR(50)  NOT NULL,
                    enabled         BOOLEAN      DEFAULT 1,
                    priority        INTEGER      DEFAULT 0,
                    settings        TEXT         NOT NULL DEFAULT '{}',
                    tier_name       VARCHAR(50),
                    calls_per_minute INTEGER,
                    burst_size      INTEGER      DEFAULT 0,
                    min_delay_seconds REAL        DEFAULT 0.0,
                    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(
                "CREATE INDEX idx_provider_config_name ON provider_config (name)"
            )
            cursor.execute(
                "CREATE INDEX idx_provider_config_type ON provider_config (provider_type)"
            )
            cursor.execute(
                "CREATE INDEX idx_provider_type_enabled ON provider_config (provider_type, enabled)"
            )
            created += 1
            print("  -> Created 'provider_config'")

        # ------------------------------------------------------------------
        # 2. provider_credentials
        # ------------------------------------------------------------------
        if table_exists(cursor, 'provider_credentials'):
            print("Table 'provider_credentials' already exists. Skipping.")
        else:
            print("Creating table 'provider_credentials'...")
            cursor.execute("""
                CREATE TABLE provider_credentials (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id       INTEGER      NOT NULL
                        REFERENCES provider_config(id) ON DELETE CASCADE,
                    credential_type   VARCHAR(30)  NOT NULL,
                    credential_value  TEXT         NOT NULL,
                    is_encrypted      BOOLEAN      DEFAULT 0,
                    expires_at        DATETIME,
                    created_at        DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    updated_at        DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(provider_id, credential_type)
                )
            """)
            cursor.execute(
                "CREATE INDEX idx_credential_provider ON provider_credentials (provider_id)"
            )
            created += 1
            print("  -> Created 'provider_credentials'")

        # ------------------------------------------------------------------
        # 3. provider_health_log
        # ------------------------------------------------------------------
        if table_exists(cursor, 'provider_health_log'):
            print("Table 'provider_health_log' already exists. Skipping.")
        else:
            print("Creating table 'provider_health_log'...")
            cursor.execute("""
                CREATE TABLE provider_health_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id     INTEGER      NOT NULL
                        REFERENCES provider_config(id) ON DELETE CASCADE,
                    status          VARCHAR(20)  NOT NULL,
                    latency_ms      REAL,
                    error_message   TEXT,
                    recorded_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(
                "CREATE INDEX idx_health_log_provider_time "
                "ON provider_health_log (provider_id, recorded_at)"
            )
            created += 1
            print("  -> Created 'provider_health_log'")

        conn.commit()

        if created > 0:
            print(f"\nSUCCESS: {created} table(s) created.")
        else:
            print("\nNo tables needed to be created.")

        # Verify
        print("\nVerifying tables...")
        all_exist = True
        for tbl in ('provider_config', 'provider_credentials', 'provider_health_log'):
            exists = table_exists(cursor, tbl)
            status = "OK" if exists else "MISSING"
            print(f"  [{status}] {tbl}")
            if not exists:
                all_exist = False

        return all_exist

    except Exception as e:
        print(f"ERROR: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Create provider abstraction layer tables"
    )
    parser.add_argument('--db', required=True, help="Path to SQLite database")
    parser.add_argument('--no-backup', action='store_true', help="Skip backup creation")

    args = parser.parse_args()

    success = create_provider_tables(args.db, backup=not args.no_backup)

    if success:
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETE")
        print("=" * 60)
        print("""
New tables created:

provider_config
  Stores provider instance configuration (one row per provider-domain).
  Columns: name, display_name, provider_type, implementation, enabled,
           priority, settings (JSON), tier_name, calls_per_minute,
           burst_size, min_delay_seconds

provider_credentials
  API keys and OAuth tokens per provider.
  Columns: provider_id, credential_type, credential_value,
           is_encrypted, expires_at

provider_health_log
  Append-only health/uptime tracking.
  Columns: provider_id, status, latency_ms, error_message, recorded_at
""")

    return 0 if success else 1


if __name__ == '__main__':
    exit(main())
