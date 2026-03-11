# Scheduler Setup (Daily Auto-Refresh)

This app includes a background job that can run daily:

- fetch latest prices for traded tickers
- update `data/prices.csv`
- recompute `data/positions.csv`
- recompute `data/daily_snapshot.csv`

Command used:

```bash
cd "/Users/jxie/Simple Portfolio Manager"
./scripts/run_daily_refresh.sh
```

## Option 1: Cron (quickest)

1. Open crontab:

```bash
crontab -e
```

2. Add this line to run weekdays at **4:30 PM local time**:

```bash
30 16 * * 1-5 cd "/Users/jxie/Simple Portfolio Manager" && ./scripts/run_daily_refresh.sh >> "/Users/jxie/Simple Portfolio Manager/daily_refresh.log" 2>&1
```

3. Save and exit. Verify:

```bash
crontab -l
```

## Option 2: macOS launchd (recommended on Mac)

Create file:

`~/Library/LaunchAgents/com.jingerzz.simple-portfolio-refresh.plist`

Use this content:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.jingerzz.simple-portfolio-refresh</string>

    <key>ProgramArguments</key>
    <array>
      <string>/Users/jxie/Simple Portfolio Manager/.venv/bin/python</string>
      <string>/Users/jxie/Simple Portfolio Manager/scripts/daily_refresh.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/jxie/Simple Portfolio Manager</string>

    <key>StartCalendarInterval</key>
    <array>
      <dict>
        <key>Weekday</key><integer>1</integer>
        <key>Hour</key><integer>16</integer>
        <key>Minute</key><integer>30</integer>
      </dict>
      <dict>
        <key>Weekday</key><integer>2</integer>
        <key>Hour</key><integer>16</integer>
        <key>Minute</key><integer>30</integer>
      </dict>
      <dict>
        <key>Weekday</key><integer>3</integer>
        <key>Hour</key><integer>16</integer>
        <key>Minute</key><integer>30</integer>
      </dict>
      <dict>
        <key>Weekday</key><integer>4</integer>
        <key>Hour</key><integer>16</integer>
        <key>Minute</key><integer>30</integer>
      </dict>
      <dict>
        <key>Weekday</key><integer>5</integer>
        <key>Hour</key><integer>16</integer>
        <key>Minute</key><integer>30</integer>
      </dict>
    </array>

    <key>StandardOutPath</key>
    <string>/Users/jxie/Simple Portfolio Manager/daily_refresh.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/jxie/Simple Portfolio Manager/daily_refresh.log</string>
  </dict>
</plist>
```

Load it:

```bash
launchctl unload ~/Library/LaunchAgents/com.jingerzz.simple-portfolio-refresh.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.jingerzz.simple-portfolio-refresh.plist
launchctl list | grep simple-portfolio-refresh
```

## Manual test run

Run once before scheduling:

```bash
cd "/Users/jxie/Simple Portfolio Manager"
./scripts/run_daily_refresh.sh --force-refresh
```

## Log check

```bash
tail -n 100 "/Users/jxie/Simple Portfolio Manager/daily_refresh.log"
```
