#!/bin/bash
# Remove the meeting assistant's launchd agents. Leaves your files in
# ~/.meeting-assistant intact (delete the folder manually if you want them gone).
U=$(id -u)
for label in brain menubar; do
  launchctl bootout "gui/$U/com.sujitk.meeting-assistant.$label" 2>/dev/null \
    && echo "stopped $label" || echo "$label was not running"
  rm -f "$HOME/Library/LaunchAgents/com.sujitk.meeting-assistant.$label.plist"
done
echo "Agents removed. Files kept in ~/.meeting-assistant (delete manually to fully remove)."
