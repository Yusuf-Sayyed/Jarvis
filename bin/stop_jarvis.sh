#!/usr/bin/env bash
# JARVIS stop script for Super + Shift + J shortcut and desktop entries

set -e

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
LOCK_FILE="$RUNTIME_DIR/jarvis.lock"
STATUS_FILE="$RUNTIME_DIR/jarvis/status.json"

notify_msg() {
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -u low -i process-stop "JARVIS" "$1"
    fi
}

# Function to verify if a given PID is genuinely the running JARVIS process
is_jarvis_pid() {
    local pid="$1"
    if [ -z "$pid" ] || ! [[ "$pid" =~ ^[0-9]+$ ]] || [ "$pid" -le 1 ]; then
        return 1
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        return 1
    fi
    # Check cmdline to ensure it is the genuine JARVIS assistant process
    if [ -f "/proc/$pid/cmdline" ]; then
        local cmdline
        cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
        if [[ "$cmdline" =~ jarvis\.py ]] || [[ "$cmdline" =~ bin/python.*jarvis ]]; then
            return 0
        fi
    fi
    return 1
}

# 1. Check if running under systemd user service
SERVICE_ACTIVE=0
if systemctl --user is-active --quiet jarvis.service 2>/dev/null; then
    SERVICE_ACTIVE=1
fi

# 2. Extract PID from systemd or lock file or status.json
TARGET_PID=""
if [ "$SERVICE_ACTIVE" -eq 1 ]; then
    TARGET_PID=$(systemctl --user show --property MainPID --value jarvis.service 2>/dev/null || true)
fi

if ! is_jarvis_pid "$TARGET_PID"; then
    TARGET_PID=""
    if [ -f "$LOCK_FILE" ]; then
        CANDIDATE_PID=$(head -n 1 "$LOCK_FILE" 2>/dev/null | tr -d '[:space:]')
        if is_jarvis_pid "$CANDIDATE_PID"; then
            TARGET_PID="$CANDIDATE_PID"
        fi
    fi
fi

if [ -z "$TARGET_PID" ] && [ -f "$STATUS_FILE" ]; then
    CANDIDATE_PID=$(grep -o '"pid":[[:space:]]*[0-9]*' "$STATUS_FILE" 2>/dev/null | grep -o '[0-9]*' || true)
    if is_jarvis_pid "$CANDIDATE_PID"; then
        TARGET_PID="$CANDIDATE_PID"
    fi
fi

# 3. If no verified JARVIS process is active
if [ "$SERVICE_ACTIVE" -eq 0 ] && [ -z "$TARGET_PID" ]; then
    rm -f "$LOCK_FILE" 2>/dev/null || true
    if [ -f "$STATUS_FILE" ]; then
        echo '{"status": "STANDBY", "pid": null, "details": "not_running"}' > "$STATUS_FILE" 2>/dev/null || true
    fi
    notify_msg "JARVIS is not running, Sir."
    exit 0
fi

# 4. Initiate graceful shutdown
notify_msg "Stopping JARVIS voice assistant..."

if [ "$SERVICE_ACTIVE" -eq 1 ]; then
    systemctl --user stop jarvis.service 2>/dev/null || true
fi

if [ -n "$TARGET_PID" ] && kill -0 "$TARGET_PID" 2>/dev/null; then
    # Send SIGTERM to initiate graceful shutdown (closes mic, stops audio, cleans state)
    kill -TERM "$TARGET_PID" 2>/dev/null || true

    # Wait up to 3 seconds for process to exit cleanly
    WAITED=0
    while kill -0 "$TARGET_PID" 2>/dev/null && [ "$WAITED" -lt 30 ]; do
        sleep 0.1
        WAITED=$((WAITED + 1))
    done

    # Fallback to SIGKILL only for this verified process if it hung
    if kill -0 "$TARGET_PID" 2>/dev/null; then
        kill -KILL "$TARGET_PID" 2>/dev/null || true
    fi
fi

# 5. Clean up runtime lock and ensure status is clean
rm -f "$LOCK_FILE" 2>/dev/null || true
if [ -f "$STATUS_FILE" ]; then
    echo '{"status": "STANDBY", "pid": null, "details": "stop_shortcut"}' > "$STATUS_FILE" 2>/dev/null || true
fi

notify_msg "JARVIS stopped, Sir."
exit 0
