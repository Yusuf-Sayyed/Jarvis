"""
Runtime status publisher for JARVIS.
Maintains a lightweight, low-resource IPC status state for the desktop panel widget.
Allowed single-word status states:
  - STANDBY
  - LISTENING
  - THINKING
  - SPEAKING
  - ERROR
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

VALID_STATUSES = frozenset({"STANDBY", "LISTENING", "THINKING", "SPEAKING", "ERROR"})
DEFAULT_STATUS = "STANDBY"
STALE_THRESHOLD_SECONDS = 30.0


def get_status_file_path() -> Path:
    """Returns the path to the runtime status JSON file."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        base = Path(runtime_dir) / "jarvis"
    else:
        base = Path(tempfile.gettempdir()) / "jarvis"
    base.mkdir(parents=True, exist_ok=True)
    return base / "status.json"


def set_runtime_status(status: str, details: Optional[str] = None) -> bool:
    """
    Sets the runtime status of JARVIS.
    Validates status against allowed one-word states and writes atomically.
    """
    clean_status = status.strip().upper()
    if clean_status not in VALID_STATUSES:
        clean_status = "ERROR"

    payload = {
        "status": clean_status,
        "pid": os.getpid(),
        "timestamp": time.time(),
        "details": details or "",
    }

    try:
        path = get_status_file_path()
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.write("\n")
        tmp_path.replace(path)
        return True
    except Exception:
        return False


def get_runtime_status() -> dict[str, Any]:
    """
    Reads the runtime status of JARVIS.
    Checks process liveness to avoid stale states after unexpected exits or crashes.
    Returns:
        {"status": "STANDBY"|"LISTENING"|"THINKING"|"SPEAKING"|"ERROR", "pid": int|None, ...}
    """
    path = get_status_file_path()
    if not path.is_file():
        return {"status": DEFAULT_STATUS, "pid": None, "timestamp": 0.0, "details": "no_status_file"}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"status": DEFAULT_STATUS, "pid": None, "timestamp": 0.0, "details": "read_error"}

    pid = data.get("pid")
    status = data.get("status", DEFAULT_STATUS).upper()
    ts = data.get("timestamp", 0.0)

    if status not in VALID_STATUSES:
        status = DEFAULT_STATUS

    # Check if process is still running
    if pid is not None:
        try:
            os.kill(pid, 0)
        except OSError:
            # Process dead or invalid: return STANDBY
            return {
                "status": DEFAULT_STATUS,
                "pid": None,
                "timestamp": ts,
                "details": f"process_{pid}_terminated",
            }

    # Check for stale timestamp if inactive for a long time
    if time.time() - ts > STALE_THRESHOLD_SECONDS and status not in ("STANDBY", "ERROR"):
        return {
            "status": DEFAULT_STATUS,
            "pid": pid,
            "timestamp": ts,
            "details": "stale_timestamp",
        }

    return {
        "status": status,
        "pid": pid,
        "timestamp": ts,
        "details": data.get("details", ""),
    }


def clear_runtime_status():
    """Returns the runtime indicator to STANDBY cleanly."""
    set_runtime_status(DEFAULT_STATUS, details="normal_shutdown")
