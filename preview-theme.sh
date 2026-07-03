#!/bin/bash
# Preview an overlay theme for a few seconds, so you can pick one for config.json.
# Usage:  ./preview-theme.sh sunrise   (midnight | sunrise | forest | grape | mono)
#         ./preview-theme.sh all       (cycles through every theme)
cd "$(dirname "$0")" || exit 1
START=$(./venv/bin/python -c "from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)+timedelta(minutes=2)).astimezone().isoformat())")

show() {
  echo "Previewing theme: $1"
  ./bin/overlay --id "preview-$1" --title "Plato Dev Huddle" --start "$START" \
    --url "https://meet.google.com/abc-defg-hij" --mode meeting --theme "$1" \
    --line "Finish that thought — I'll hold the door for you." \
    --runtime ./runtime &
  local pid=$!
  sleep "${2:-5}"
  kill "$pid" 2>/dev/null
}

if [ "$1" = "all" ]; then
  for t in midnight sunrise forest grape mono glass; do show "$t" 3; done
else
  show "${1:-midnight}" "${2:-6}"
fi
