# Maintenance Thread Documentation

## Overview

The **MaintenanceThread** is a background service that handles scheduled nightly maintenance tasks after market close. It ensures data freshness for the next trading day by backing up the database, updating volume averages, earnings dates, and cleaning up old historical data.

**Key Characteristics:**
- **Scope:** All active positions (state >= 0)
- **Frequency:** Once per trading day
- **Schedule:** Default 5:00 PM ET (after market close)
- **Days:** Weekdays only (skips weekends)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     MAINTENANCE THREAD CYCLE                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │                    SCHEDULE CHECK                               │    │
│   │   • Is it a weekday?                                           │    │
│   │   • Has run time passed (17:00 ET)?                            │    │
│   │   • Not already run today?                                      │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                              │                                           │
│                              ▼ (All conditions met)                      │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │                  TASK 1: DATABASE BACKUP                        │    │
│   │   • Copy database file to backup directory                     │    │
│   │   • Add timestamp to backup filename                           │    │
│   │   • Rotate old backups (keep N most recent)                    │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                              │                                           │
│                              ▼                                           │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │                  TASK 2: VOLUME UPDATE                          │    │
│   │   • Query active positions (state >= 0)                        │    │
│   │   • For each symbol:                                           │    │
│   │     - Fetch 50 days of bars from Polygon/Massive               │    │
│   │     - Calculate 50-day average volume                          │    │
│   │     - Store bars in HistoricalBar table                        │    │
│   │     - Update Position.avg_volume_50d                           │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                              │                                           │
│                              ▼                                           │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │                TASK 3: EARNINGS UPDATE                          │    │
│   │   • Query active positions                                     │    │
│   │   • Filter: missing OR past earnings_date                      │    │
│   │   • For each symbol:                                           │    │
│   │     - Fetch next earnings date from Polygon API                │    │
│   │     - Update Position.earnings_date                            │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                              │                                           │
│                              ▼                                           │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │                  TASK 4: DATA CLEANUP                           │    │
│   │   • Delete HistoricalBar records older than configured days   │    │
│   │   • Default: 200 days (for backtesting/ML needs)              │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                              │                                           │
│                              ▼                                           │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │                    MARK COMPLETE                                │    │
│   │   • Record today's date as _last_run_date                      │    │
│   │   • Log summary of results                                     │    │
│   │   • Sleep until next day                                       │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tasks

### Summary Table

| Task | Purpose | Data Updated | Frequency |
|------|---------|--------------|-----------|
| **Database Backup** | Create timestamped backup of database | Backup files | Daily |
| **Volume Update** | Refresh 50-day average volume | `Position.avg_volume_50d`, `HistoricalBar` | Daily |
| **Earnings Update** | Refresh upcoming earnings dates | `Position.earnings_date` | Daily |
| **Data Cleanup** | Remove old historical bars | `HistoricalBar` | Daily |

### Task 1: Database Backup

Creates a timestamped backup of the database file before any modifications. Maintains a rotating set of backups.

**Process:**
1. Copy database file to backup directory
2. Add timestamp to filename (e.g., `canslim_positions_20250203_170000.db`)
3. Rotate old backups - delete oldest beyond `backup_count`

**Backup runs FIRST** to ensure a clean backup before any data modifications.

**Configuration:**
- `backup_dir`: Directory for backups (default: `{db_dir}/backups/`)
- `backup_count`: Number of backups to keep (default: 7)

**Result Fields:**
```python
{
    'backup_path': str,           # Full path to new backup
    'backup_size_mb': float,      # Size in megabytes
    'deleted_old_backups': int    # Number of old backups removed
}
```

**Example Backup Directory:**
```
backups/
├── canslim_positions_20250203_170000.db  (newest)
├── canslim_positions_20250202_170000.db
├── canslim_positions_20250131_170000.db
├── canslim_positions_20250130_170000.db
├── canslim_positions_20250129_170000.db
├── canslim_positions_20250128_170000.db
└── canslim_positions_20250127_170000.db  (oldest, 7th kept)
```

### Task 2: Volume Update

Updates the 50-day average volume for all active positions. This data is critical for:
- **Breakout confirmation:** Volume must be 40%+ above average
- **Position sizing:** Higher volume = more liquid
- **Technical analysis:** Volume trends

**Process:**
1. Query all positions where `state >= 0`
2. For each unique symbol:
   - Fetch 50 days of daily bars from Polygon/Massive
   - Calculate average volume from fetched bars
   - Store/update bars in `HistoricalBar` table
   - Update `Position.avg_volume_50d` and `volume_updated_at`

**Dependencies:**
- `VolumeService` - Handles bar fetching and calculation
- `PolygonClient` - API access for historical data

**Result Fields:**
```python
{
    'symbols': int,    # Total symbols processed
    'success': int,    # Successfully updated
    'failed': int      # Failed updates
}
```

### Task 3: Earnings Update

Updates earnings dates for positions that need it. Critical for:
- **Position risk management:** Avoid holding through earnings
- **Trading decisions:** Plan exits before earnings
- **Alerting:** Warn about upcoming earnings

**Process:**
1. Query all positions where `state >= 0`
2. Filter for positions where:
   - `earnings_date` is NULL, OR
   - `earnings_date` is in the past
3. For each symbol needing update:
   - Fetch next earnings date from Polygon API
   - Update `Position.earnings_date`

**Note:** Skips positions that already have a future earnings date.

**Result Fields:**
```python
{
    'symbols': int,    # Symbols checked
    'updated': int     # Successfully updated
}
```

### Task 4: Data Cleanup

Removes old historical bar data to manage database size while retaining enough for backtesting and ML work.

**Process:**
1. Calculate cutoff date: `today - bars_days_to_keep`
2. Delete all `HistoricalBar` records before cutoff

**Configuration:**
- `bars_days_to_keep`: Days of historical data to retain (default: 200)

**Why 200 days default?**
- 50 days minimum for volume average calculation
- 200 days provides enough history for:
  - Backtesting strategies
  - ML/learning system training
  - Technical indicator calculations (200 MA, etc.)
  - Trend analysis

**Result Fields:**
```python
{
    'deleted_bars': int,   # Number of bars deleted
    'days_kept': int       # Configured retention period
}
```

---

## Configuration

### Config Location

In `user_config.yaml` under the `maintenance` section:

```yaml
maintenance:
  # Schedule (ET timezone)
  run_hour: 17            # Hour to run (0-23), default: 5:00 PM
  run_minute: 0           # Minute to run (0-59)

  # Task toggles
  enable_volume_update: true    # Enable/disable volume updates
  enable_earnings_update: true  # Enable/disable earnings updates
  enable_cleanup: true          # Enable/disable data cleanup
  enable_backup: true           # Enable/disable database backup

  # Data retention (for backtesting/ML)
  bars_days_to_keep: 200        # Days of historical bars to keep (default: 200)

  # Backup settings
  backup_count: 7               # Number of daily backups to keep (default: 7)
  backup_dir: null              # Backup directory (default: {db_dir}/backups/)
  # backup_dir: "C:/Trading/backups"  # Or specify custom path
```

### Service Controller Settings

In the `threads` section:

```yaml
threads:
  maintenance_interval: 300   # Poll interval in seconds (how often to check if time to run)
```

### Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `run_hour` | int | 17 | Hour to run (0-23, ET timezone) |
| `run_minute` | int | 0 | Minute to run (0-59) |
| `enable_volume_update` | bool | true | Enable volume data updates |
| `enable_earnings_update` | bool | true | Enable earnings date updates |
| `enable_cleanup` | bool | true | Enable old data cleanup |
| `enable_backup` | bool | true | Enable database backup |
| `bars_days_to_keep` | int | 200 | Days of historical bars to retain |
| `backup_count` | int | 7 | Number of backup files to keep |
| `backup_dir` | str | null | Backup directory (null = `{db_dir}/backups/`) |
| `maintenance_interval` | int | 300 | Seconds between schedule checks |

### Retention Recommendations

| Use Case | bars_days_to_keep | Reason |
|----------|-------------------|--------|
| **Minimal** | 100 | 50 for avg + 50 buffer |
| **Standard** | 200 | Default, good for basic backtesting |
| **Backtesting** | 500 | ~2 years of data |
| **ML/Learning** | 750+ | 3+ years for robust training |

---

## Dependencies

### Required Services

| Service | File | Purpose |
|---------|------|---------|
| `VolumeService` | `services/volume_service.py` | Fetches bars, calculates averages |
| `EarningsService` | `services/earnings_service.py` | Fetches earnings dates |
| `PolygonClient` | `integrations/polygon_client.py` | API access to Polygon/Massive |

### Database Tables

| Table | Operations | Purpose |
|-------|-----------|---------|
| `Position` | Read/Update | Source of symbols, stores avg_volume and earnings |
| `HistoricalBar` | Create/Delete | Stores daily price/volume bars |

### API Requirements

- **Polygon.io or Massive API key** required
- Used for:
  - Daily bar data (OHLCV)
  - Earnings dates lookup

---

## Scheduling Logic

### Run Conditions

The maintenance thread checks these conditions every `maintenance_interval` seconds:

```python
def _should_run(self) -> bool:
    # 1. Skip weekends
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # 2. Skip if already ran today
    if self._last_run_date == now_et.date():
        return False

    # 3. Run if past scheduled time
    scheduled_time = today.replace(hour=run_hour, minute=run_minute)
    return now_et >= scheduled_time
```

### Timing Flow

```
Market Close (4:00 PM ET)
        │
        ▼
5:00 PM ET ─── Maintenance runs (default)
        │
        │     • Database backup (~seconds)
        │     • Volume update (~5-10 min for 50 symbols)
        │     • Earnings update (~2-5 min for 50 symbols)
        │     • Cleanup (~seconds)
        │
        ▼
5:15 PM ET ─── Complete, sleep until tomorrow
```

### Why 5:00 PM ET?

- After market close (4:00 PM) ensures final bar data is available
- Before overnight session gives time for any issues to be fixed
- API rate limits are less constrained after hours

---

## Error Handling

### Task-Level Isolation

Each task runs independently - if one fails, others still execute:

```python
# Backup runs first
if self.enable_backup:
    try:
        results['backup'] = self._backup_database()
    except Exception as e:
        results['backup'] = {'error': str(e)}
        # Continues to volume update...

# Volume update runs even if backup failed
if self.enable_volume_update:
    try:
        results['volume_update'] = self._update_volume_data()
    except Exception as e:
        results['volume_update'] = {'error': str(e)}
```

### Symbol-Level Errors

Within each task, individual symbol failures don't stop the batch:

```python
for symbol in symbols:
    try:
        result = volume_service.update_symbol(symbol)
        if result.success:
            success += 1
        else:
            failed += 1
    except Exception as e:
        failed += 1
        self.logger.error(f"{symbol}: {e}")
```

### Missing Dependencies

Tasks gracefully skip if dependencies are unavailable:

```python
if not self.db_session_factory or not self.polygon_client:
    self.logger.warning("Volume update skipped - missing dependencies")
    return {'skipped': 'missing dependencies'}
```

---

## Logging

### Logger Name

```python
logging.getLogger('canslim.maintenance')
```

### Log Output

Logs are written to:
- Console (when running in foreground)
- `logs/maintenance/maintenance_YYYY-MM-DD.log` (when configured)

### Log Examples

**Startup:**
```
Maintenance thread initialized. Run time: 17:00 ET, volume_update=True, earnings_update=True, backup=True, bars_keep=200 days
```

**Task Execution:**
```
==================================================
Starting nightly maintenance tasks
==================================================
Creating database backup: C:/Trading/canslim_monitor/backups/canslim_positions_20250203_170000.db
Backup created: canslim_positions_20250203_170000.db (45.2 MB)
Rotated 1 old backup(s), keeping 7

Updating 50-day volume data for active positions...
Updating volume data for 45 symbols
NVDA: avg_vol=52,345,678
AAPL: avg_vol=78,234,567
...
Volume update complete: 43/45 successful

Updating earnings dates for active positions...
Updating earnings for 12 symbols
GOOGL: earnings=2025-02-15
...
Earnings update complete: 10/12 updated

Cleaning up old historical data (keeping 200 days)...
Cleanup complete: 2,345 old bars deleted
==================================================
Maintenance complete: {'backup': {...}, 'volume_update': {...}, ...}
==================================================
```

---

## Troubleshooting

### Maintenance Not Running

**Symptoms:** No maintenance logs after 5 PM ET

**Check:**
1. **Service running?** - Check if main service is active
2. **Thread enabled?** - Verify maintenance thread is created
3. **API client available?** - Thread requires `polygon_client`

```bash
# Check service status
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'GET_STATUS'})
print(f'Service: {result.get(\"service_running\")}')
print(f'IBKR: {result.get(\"ibkr_connected\")}')
"
```

### Backup Failures

**Symptoms:** `{'error': '...'}` in backup results

**Common Causes:**
- **Disk full:** No space for backup
- **Permission denied:** Cannot write to backup directory
- **Database locked:** Another process has exclusive lock

**Solution:**
```bash
# Check backup directory
ls -la C:/Trading/canslim_monitor/backups/

# Manual backup
cp canslim_positions.db canslim_positions_backup.db
```

### Volume Update Failures

**Symptoms:** `failed > 0` in volume update results

**Common Causes:**
- **API rate limiting:** Too many requests too fast
- **Invalid symbols:** Delisted or invalid ticker
- **Network issues:** API timeouts

**Solution:**
```bash
# Test single symbol manually
python -m canslim_monitor.services.volume_service update --symbol NVDA
```

### Earnings Not Updating

**Symptoms:** Positions still show old/missing earnings dates

**Common Causes:**
- **Future date exists:** Skipped because earnings_date is already in future
- **No earnings data:** Company may not have scheduled earnings
- **API issues:** Polygon earnings endpoint errors

**Solution:**
```bash
# Force update all
python -m canslim_monitor earnings --force

# Check single symbol
python -m canslim_monitor earnings --symbol NVDA
```

### Database Growing Large

**Symptoms:** Database file size keeps increasing

**Check:**
- `enable_cleanup` is true
- `bars_days_to_keep` is set appropriately
- Cleanup task is running successfully

**Manual cleanup:**
```bash
python -m canslim_monitor.services.volume_service cleanup
```

---

## CLI Commands

### Service Control

**Start the service (includes MaintenanceThread):**
```bash
# Run in foreground (for debugging)
python -m canslim_monitor service start

# Check service status
python -m canslim_monitor service status
```

### Volume Service Commands

```bash
# Update volume for all watchlist positions
python -m canslim_monitor.services.volume_service update

# Update single symbol
python -m canslim_monitor.services.volume_service update --symbol NVDA

# Test API connection
python -m canslim_monitor.services.volume_service test

# Manual cleanup of old bars
python -m canslim_monitor.services.volume_service cleanup
```

### Earnings Service Commands

```bash
# Update earnings for all positions
python -m canslim_monitor earnings

# Force update (even if date exists)
python -m canslim_monitor earnings --force

# Update single symbol
python -m canslim_monitor earnings --symbol NVDA

# Check upcoming earnings (read-only)
python -m canslim_monitor earnings --check

# Check next 30 days
python -m canslim_monitor earnings --check --days 30
```

### Check Thread Status

```bash
python -c "
from canslim_monitor.service.ipc_client import IPCClient
client = IPCClient()
result = client.send_command({'type': 'GET_THREAD_STATUS', 'thread': 'maintenance'})
print(f'State: {result.get(\"state\")}')
print(f'Last run: {result.get(\"last_check\")}')
print(f'Errors: {result.get(\"error_count\")}')
"
```

### Force Maintenance Run

```bash
# Currently no IPC command to force maintenance
# Workaround: Restart service after run_hour passes
python -m canslim_monitor service stop
python -m canslim_monitor service start
```

### View Backups

```bash
python -c "
from pathlib import Path

backup_dir = Path('C:/Trading/canslim_monitor/backups')
if backup_dir.exists():
    backups = sorted(backup_dir.glob('*.db'), key=lambda p: p.stat().st_mtime, reverse=True)
    print('Database Backups:')
    print('-' * 60)
    for b in backups:
        size_mb = b.stat().st_size / 1024 / 1024
        mtime = b.stat().st_mtime
        from datetime import datetime
        date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
        print(f'{b.name:45} {size_mb:>6.1f} MB  {date_str}')
else:
    print('No backup directory found')
"
```

### View Historical Bars

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.data.models import HistoricalBar
from datetime import datetime, timedelta

db = Database('canslim_positions.db')
session = db.get_new_session()

# Count bars per symbol
from sqlalchemy import func
counts = session.query(
    HistoricalBar.symbol,
    func.count(HistoricalBar.id)
).group_by(HistoricalBar.symbol).all()

print('Historical Bars by Symbol:')
print('-' * 30)
for symbol, count in sorted(counts, key=lambda x: -x[1])[:10]:
    print(f'{symbol}: {count} bars')

session.close()
"
```

### View Average Volumes

```bash
python -c "
from canslim_monitor.data.database import Database
from canslim_monitor.data.models import Position

db = Database('canslim_positions.db')
session = db.get_new_session()

positions = session.query(Position).filter(
    Position.state >= 0,
    Position.avg_volume_50d != None
).order_by(Position.avg_volume_50d.desc()).limit(10).all()

print('Top 10 Positions by Average Volume:')
print('-' * 40)
for p in positions:
    vol = p.avg_volume_50d or 0
    updated = p.volume_updated_at.strftime('%Y-%m-%d') if p.volume_updated_at else 'Never'
    print(f'{p.symbol:6} {vol:>12,} (updated: {updated})')

session.close()
"
```

---

## Related Files

| File | Purpose |
|------|---------|
| `service/threads/maintenance_thread.py` | Main maintenance thread logic |
| `services/volume_service.py` | Volume data fetching and calculation |
| `services/earnings_service.py` | Earnings date fetching and updates |
| `integrations/polygon_client.py` | API client for Polygon/Massive |
| `data/models.py` | Database models (Position, HistoricalBar) |

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA FLOW                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│  │   Database   │         │   Backup     │         │   Backup     │        │
│  │     File     │────────▶│   Task       │────────▶│   Directory  │        │
│  │              │  copy   │              │         │              │        │
│  └──────────────┘         └──────────────┘         └──────────────┘        │
│                                                                              │
│  ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│  │   Polygon    │         │   Volume     │         │   Position   │        │
│  │     API      │────────▶│   Service    │────────▶│    Table     │        │
│  │              │  bars   │              │  avg    │ avg_volume   │        │
│  └──────────────┘         └──────────────┘         └──────────────┘        │
│                                  │                                          │
│                                  │ store                                    │
│                                  ▼                                          │
│                           ┌──────────────┐                                  │
│                           │ HistoricalBar│                                  │
│                           │    Table     │                                  │
│                           └──────────────┘                                  │
│                                                                              │
│  ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│  │   Polygon    │         │  Earnings    │         │   Position   │        │
│  │     API      │────────▶│   Service    │────────▶│    Table     │        │
│  │  (earnings)  │  date   │              │         │ earnings_date│        │
│  └──────────────┘         └──────────────┘         └──────────────┘        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```
