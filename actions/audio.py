"""
Audio and volume control for Fedora KDE using PipeWire / WirePlumber (wpctl).
Supports absolute/relative volume adjustments up to 150% (software amplification)
and hardware mute/unmute toggling with actual state verification.
"""

import re
import shutil
import subprocess
from typing import Optional


def _get_wpctl_bin() -> Optional[str]:
    return shutil.which("wpctl")


def get_volume_status() -> tuple[Optional[float], bool, str]:
    """
    Queries current volume level and mute status from wpctl.
    Returns:
        (volume_float, is_muted, human_status_str)
        e.g. (0.95, False, "95%") or (0.50, True, "50% [MUTED]")
    """
    wpctl = _get_wpctl_bin()
    if not wpctl:
        return None, False, "wpctl unavailable"

    try:
        res = subprocess.run(
            [wpctl, "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return None, False, "error querying volume"

        # Output format: "Volume: 0.95" or "Volume: 0.50 [MUTED]"
        out = res.stdout.strip()
        is_muted = "[MUTED]" in out

        m = re.search(r"Volume:\s+([0-9.]+)", out)
        if m:
            vol = float(m.group(1))
            status_str = f"{int(vol * 100)}%"
            if is_muted:
                status_str += " [MUTED]"
            return vol, is_muted, status_str
    except Exception as e:
        return None, False, f"query error: {e}"

    return None, False, "unknown"


def set_volume(percentage: int) -> tuple[bool, str]:
    """
    Sets volume to a target percentage (0% to 150%).
    Supports software amplification up to 150% with -l 1.5.
    Rejects values above 150% so higher-level logic can prompt confirmation.
    Returns:
        (success: bool, message: str)
    """
    wpctl = _get_wpctl_bin()
    if not wpctl:
        return False, "Audio control utility 'wpctl' is not available on this system."

    try:
        pct = int(percentage)
    except (ValueError, TypeError):
        return False, f"Invalid volume percentage: {percentage}"

    if pct < 0:
        return False, "Volume percentage cannot be negative."

    if pct > 150:
        return False, f"Requested volume {pct}% exceeds maximum supported volume of 150% (software amplification)."

    try:
        # Use -l 1.5 to allow software boost up to 150%
        res = subprocess.run(
            [wpctl, "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", f"{pct}%"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Failed to set volume: {res.stderr.strip()}"

        # If muted, unmute so user hears the new volume level
        _, is_muted, _ = get_volume_status()
        if is_muted:
            subprocess.run([wpctl, "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], timeout=1.0, check=False)

        # Verify actual state after setting
        actual_vol, _, _ = get_volume_status()
        actual_pct = int(round(actual_vol * 100)) if actual_vol is not None else pct

        msg = f"Volume set to {actual_pct}%."
        if pct > 100:
            msg += " Note: Software amplification above 100% may cause audio distortion."

        return True, msg
    except Exception as e:
        return False, f"Error adjusting volume: {e}"


def change_volume(delta_pct: int) -> tuple[bool, str]:
    """
    Increases or decreases volume by delta_pct (e.g. +10% or -20%).
    Clamps the adjusted target between 0% and 150%.
    """
    current_vol, is_muted, _ = get_volume_status()
    if current_vol is None:
        return False, "Could not determine current volume level to adjust."

    current_pct = int(round(current_vol * 100))
    target_pct = max(0, min(150, current_pct + delta_pct))
    return set_volume(target_pct)


def set_mute(mute_state: Optional[bool] = None) -> tuple[bool, str]:
    """
    Mutes (True), unmutes (False), or toggles (None) audio mute state.
    """
    wpctl = _get_wpctl_bin()
    if not wpctl:
        return False, "Audio control utility 'wpctl' is not available on this system."

    try:
        if mute_state is True:
            arg = "1"
            action_desc = "muted"
        elif mute_state is False:
            arg = "0"
            action_desc = "unmuted"
        else:
            arg = "toggle"
            action_desc = "toggled"

        res = subprocess.run(
            [wpctl, "set-mute", "@DEFAULT_AUDIO_SINK@", arg],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Failed to set mute: {res.stderr.strip()}"

        # Verify new state
        _, now_muted, status_str = get_volume_status()
        if now_muted:
            return True, "Audio muted."
        else:
            return True, f"Audio unmuted ({status_str})."
    except Exception as e:
        return False, f"Error changing mute state: {e}"
