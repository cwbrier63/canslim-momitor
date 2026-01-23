# GUI Fix Deployment Instructions

## Summary of Fixes

### 1. UTF-8 Encoding Corruption (FIXED)
All Unicode characters have been restored throughout `kanban_window.py`:
- ▶ Start button
- ■ Stop button  
- ✏️ Edit Position menu
- 📊 View Score Details menu
- 🔔 View Alerts menu
- 📦 Move to... menu
- 🛑 Stop Out menu
- ✅ Close Position menu
- 🗑️ Delete menu
- All box-drawing characters (═ ─ █ ░)
- All status emojis (🟢 🟡 🔴)
- All checkmarks and arrows (✓ ✗ → ←)

### 2. IBD Exposure Double-Click (NEW)
Double-click on "RECOMMENDED EXPOSURE" in the top banner now opens the IBD Exposure editor dialog where you can:
- Set market status (Confirmed Uptrend, Under Pressure, Rally Attempt, Correction)
- Set exposure range
- Add notes
- View history

### 3. Alert Enhancements (PRESERVED)
All improvements from yesterday are kept:
- **DateRangeFilterWidget**: Preset buttons (15 min, 1 hour, 4 hours, Today, 7 Days, 30 Days, Custom)
- **Custom date range picker**: From/To datetime selectors
- **Quick time filter**: "Last X minutes/hours/days"
- **Extended columns**: Right-click table header to show/hide columns (severity, health rating, grade, score, market regime, volume ratio, pivot, avg cost, MA21, MA50)

### 4. alerts.py Removed
The redundant `alerts.py` file has been removed. All functionality is properly in:
- `global_alert_window.py` - Main alert window with date filtering
- `alert_table_widget.py` - Reusable table with column visibility

---

## Deployment Steps

### Option A: Replace Entire GUI Folder
```bash
# Backup your current gui folder
cd C:\Trading\canslim_monitor
rename gui gui_backup_20260122

# Extract the fixed gui folder
# Unzip fixed_gui.zip and rename the "fixed_gui" folder to "gui"
```

### Option B: Replace Individual Files
Copy these files from the zip to `C:\Trading\canslim_monitor\gui\`:

**Main file (REQUIRED):**
- `kanban_window.py` - UTF-8 fixes + IBD editor integration

**Alert files (keep enhancements):**
- `alerts/global_alert_window.py` - Date filtering
- `alerts/alert_table_widget.py` - Column visibility

**Delete this file if it exists:**
- `alerts/alerts.py` - Redundant, causes conflicts

---

## Verification Steps

After deployment, verify these work:

1. **Start/Stop Buttons**: Should show ▶ and ■ symbols
2. **Context Menu**: Right-click a position card - icons should display correctly
3. **IBD Exposure Editor**: Double-click "RECOMMENDED EXPOSURE" in top banner
4. **Alert Monitor**: Open View menu → Alert Monitor
   - Date filter presets should work
   - Right-click table header to show/hide columns

---

## Files Included

```
fixed_gui/
├── __init__.py
├── kanban_window.py          # FIXED: UTF-8 + IBD editor
├── kanban_column.py
├── position_card.py
├── position_table_view.py
├── ibd_exposure_dialog.py
├── regime_management_dialog.py
├── service_control.py
├── service_status_bar.py
├── state_config.py
├── transition_dialogs.py
└── alerts/
    ├── __init__.py
    ├── alert_descriptions.py
    ├── alert_detail_dialog.py
    ├── alert_table_widget.py  # ENHANCED: Column visibility
    ├── global_alert_window.py # ENHANCED: Date filtering
    └── position_alert_dialog.py
```

Note: `alerts.py` is intentionally NOT included (redundant)

---

## Rollback

If issues occur, restore from your backup:
```bash
cd C:\Trading\canslim_monitor
rmdir /s gui
rename gui_backup_20260122 gui
```
