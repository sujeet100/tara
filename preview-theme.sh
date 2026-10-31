#!/bin/bash
# Preview an overlay theme for a few seconds, so you can pick one for config.json.
# Usage:  ./preview-theme.sh sunrise   (midnight | sunrise | forest | grape | mono)
#         ./preview-theme.sh all       (cycles through every theme)
#         ./preview-theme.sh chore     (the blocking chore screen — timesheet)
# Every preview self-terminates, so nothing can leave you staring at a locked
# screen; the chore preview in particular has no snooze and swallows esc.
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

chore() {
  echo "Previewing the blocking chore screen for ${1:-6}s"
  ./bin/overlay --id "preview-chore" --title "Submit your timesheet" \
    --start "$START" --url "https://sadhak.sahaj.ai/timetracker/timesheet" \
    --mode chore --cta "Open Sadhak" --runtime ./runtime \
    --line "I did warn you. Open Sadhak and I'll give you room." &
  local pid=$!
  sleep "${1:-6}"
  kill "$pid" 2>/dev/null
}

if [ "$1" = "chore" ]; then
  chore "${2:-6}"
elif [ "$1" = "all" ]; then
  for t in midnight sunrise forest grape mono glass; do show "$t" 3; done
else
  show "${1:-midnight}" "${2:-6}"
fi
