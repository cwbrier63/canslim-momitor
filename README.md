# Position Monitor Service Integration

This update integrates the Position Monitor into the CANSLIM service.

## Installation

### Step 1: Copy files

```cmd
xcopy /s /y canslim_monitor\* C:\trading\canslim_monitor\
```

### Step 2: Add config section

Add the contents of `CONFIG_ADDITIONS.yaml` to your `C:\trading\user_config.yaml` file.

You can copy/paste the `position_monitoring:` section at the end of your config file.

### Step 3: Verify service starts

```cmd
python -m canslim_monitor service
```

You should see:
```
Starting CANSLIM Monitor Service Controller
...
Created 3 threads
Position thread starting...
```

## What's included

| File | Purpose |
|------|---------|
| `service/service_controller.py` | Updated to pass full config to PositionThread |
| `service/threads/position_thread.py` | New implementation using PositionMonitor |
| `core/position_monitor/*` | Core position monitoring module |
| `utils/level_calculator.py` | Stop/target level calculations |
| `CONFIG_ADDITIONS.yaml` | Config section to add to user_config.yaml |

## Service Behavior

When the service runs:

1. **Market hours only** - Position thread only runs during 9:30 AM - 4:00 PM ET
2. **30 second intervals** - Checks positions every 30 seconds (configurable)
3. **IBKR prices** - Uses live prices from TWS/Gateway when connected
4. **Discord alerts** - Sends to position webhook when alerts fire
5. **Cooldowns active** - Won't spam same alert (see config for cooldown times)

## Testing (Market closed)

When market is closed, the position thread will start but won't run cycles:

```
Position thread: Outside market hours, skipping cycle
```

This is expected! The service is working correctly.

## Troubleshooting

### "No module named 'canslim_monitor.core.position_monitor'"

Make sure you copied the `core/position_monitor/` folder:
```cmd
xcopy /s /y canslim_monitor\core\* C:\trading\canslim_monitor\core\
```

### "KeyError: 'position_monitoring'"

Add the config section from `CONFIG_ADDITIONS.yaml` to your `user_config.yaml`.

### Service won't start

Check logs in `C:\Trading\canslim_monitor\logs\` for errors.
