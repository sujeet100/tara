#!/bin/bash
# Remove the meeting assistant's launchd agents. Leaves your files in
# ~/.meeting-assistant intact (delete the folder manually if you want them gone).
U=$(id -u)
for prefix in com.tara-assistant com.sujitk.meeting-assistant; do  # incl. legacy label
  for label in brain menubar; do
    launchctl bootout "gui/$U/$prefix.$label" 2>/dev/null && echo "stopped $prefix.$label"
    rm -f "$HOME/Library/LaunchAgents/$prefix.$label.plist"
  done
done
echo "Agents removed. Files kept in ~/.meeting-assistant (delete manually to fully remove)."
