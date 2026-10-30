#!/usr/bin/env bash
# JARVIS launcher script for Super + J shortcut and desktop entries

set -e

# Send brief visual notification if notify-send is available
if command -v notify-send >/dev/null 2>&1; then
    if systemctl --user is-active --quiet jarvis.service 2>/dev/null; then
        notify-send -u low -i audio-input-microphone "JARVIS" "JARVIS is already running, Sir."
        exit 0
    else
        notify-send -u low -i audio-input-microphone "JARVIS" "Initializing JARVIS voice assistant..."
    fi
fi

# If systemd user service is installed, start or restart it
if systemctl --user list-unit-files 2>/dev/null | grep -q "^jarvis\.service"; then
    systemctl --user start jarvis.service
else
    cd /home/yusuf/jarvis
    nohup /home/yusuf/jarvis/.venv/bin/python /home/yusuf/jarvis/jarvis.py > /dev/null 2>&1 &
fi
