"""
Display and brightness control for Fedora KDE using native Solid PowerManagement D-Bus.
Does not require root privileges or external brightnessctl utilities.
"""

import shutil
import subprocess
from typing import Optional

DBUS_SERVICE = "org.kde.Solid.PowerManagement"
DBUS_PATH = "/org/kde/Solid/PowerManagement/Actions/BrightnessControl"
DBUS_INTERFACE = "org.kde.Solid.PowerManagement.Actions.BrightnessControl"


def _get_qdbus_bin() -> Optional[str]:
    return shutil.which("qdbus-qt6") or shutil.which("qdbus")


def get_brightness_status() -> tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Queries current and maximum brightness from KDE Solid PowerManagement.
    Returns:
        (current_raw, max_raw, percentage)
        e.g. (2500, 10000, 25)
    """
    qdbus = _get_qdbus_bin()
    if not qdbus:
        return None, None, None

    try:
        # Get max brightness
        res_max = subprocess.run(
            [qdbus, DBUS_SERVICE, DBUS_PATH, f"{DBUS_INTERFACE}.brightnessMax"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res_max.returncode != 0:
            return None, None, None
        max_val = int(res_max.stdout.strip())

        # Get current brightness
        res_cur = subprocess.run(
            [qdbus, DBUS_SERVICE, DBUS_PATH, f"{DBUS_INTERFACE}.brightness"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res_cur.returncode != 0:
            return None, None, None
        cur_val = int(res_cur.stdout.strip())

        pct = int(round((cur_val / max_val) * 100))
        return cur_val, max_val, pct
    except Exception:
        return None, None, None


def set_brightness(percentage: int) -> tuple[bool, str]:
    """
    Sets screen brightness to a percentage (safe minimum 5% to 100%).
    Returns:
        (success: bool, message: str)
    """
    qdbus = _get_qdbus_bin()
    if not qdbus:
        return False, "KDE D-Bus utility 'qdbus-qt6' is not available."

    cur_val, max_val, _ = get_brightness_status()
    if max_val is None:
        return False, "Could not interface with KDE Brightness Control via D-Bus."

    # Clamp percentage: enforce a safe minimum of 5% so screen is never completely dark
    clamped_pct = max(5, min(100, int(percentage)))
    target_raw = int(round((clamped_pct / 100.0) * max_val))

    try:
        res = subprocess.run(
            [qdbus, DBUS_SERVICE, DBUS_PATH, f"{DBUS_INTERFACE}.setBrightness", str(target_raw)],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Failed to set brightness: {res.stderr.strip()}"

        # Verify state
        _, _, actual_pct = get_brightness_status()
        reported_pct = actual_pct if actual_pct is not None else clamped_pct
        return True, f"Brightness set to {reported_pct}%."
    except Exception as e:
        return False, f"Error adjusting brightness: {e}"


def change_brightness(delta_pct: int) -> tuple[bool, str]:
    """
    Increases or decreases brightness by delta_pct (e.g. +10% or -15%).
    """
    _, _, current_pct = get_brightness_status()
    if current_pct is None:
        return False, "Could not determine current brightness level."

    target_pct = current_pct + delta_pct
    return set_brightness(target_pct)
