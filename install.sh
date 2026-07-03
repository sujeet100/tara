#!/bin/bash
# Set up Tara on a fresh Mac. Run from the repo dir (ideally cloned to
# ~/.meeting-assistant). Idempotent — safe to re-run.
set -e
APP="$(cd "$(dirname "$0")" && pwd)"
echo "Installing Tara into $APP"

# 1. python venv + deps
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"

# 2. compile the Swift helpers
mkdir -p "$APP/bin" "$APP/cache" "$APP/logs" "$APP/runtime"
swiftc -O "$APP/overlay.swift"  -o "$APP/bin/overlay"
swiftc -O "$APP/miccheck.swift" -o "$APP/bin/miccheck"
swiftc -O "$APP/camcheck.swift" -o "$APP/bin/camcheck"
swiftc -O "$APP/toast.swift"    -o "$APP/bin/toast"

# 3. config + secret
[ -f "$APP/config.json" ] || cp "$APP/config.example.json" "$APP/config.json"
if [ ! -f "$APP/.env" ]; then
  cp "$APP/.env.example" "$APP/.env"; chmod 600 "$APP/.env"
  echo "→ Edit $APP/.env and put your real Google Calendar secret iCal URL in it."
fi

# 4. launch agents (generated with this machine's paths)
U=$(id -u); PY="$APP/venv/bin/python"; LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA"
make_agent() {  # $1=label suffix  $2=extra plist keys
  local label="com.sujitk.meeting-assistant.$1"
  cat > "$LA/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$APP/$3</string>$4</array>
  $2
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$APP/logs/$1.out.log</string>
  <key>StandardErrorPath</key><string>$APP/logs/$1.err.log</string>
</dict></plist>
PLIST
  launchctl bootout "gui/$U/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$U" "$LA/$label.plist"
}
make_agent brain   "<key>StartInterval</key><integer>60</integer><key>RunAtLoad</key><true/>" "brain.py" "<string>--tick</string>"
make_agent menubar "<key>KeepAlive</key><true/><key>RunAtLoad</key><true/>" "menubar.py" ""

echo "Done. Set your calendar URL in $APP/.env, then it runs every minute."
