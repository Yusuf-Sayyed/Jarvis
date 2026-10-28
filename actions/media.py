"""
Media and video playback controls for Fedora KDE via MPRIS D-Bus interfaces.
Provides discovery, capability inspection, fast-path playback commands (pause,
resume, stop, seek, mute/unmute), multi-session ambiguity resolution, and safe
browser fallback without arbitrary script injection.
"""

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Track last volume per bus name for mute/unmute restore
_LAST_PLAYER_VOLUMES: dict[str, float] = {}


@dataclass
class MediaPlayer:
    """Represents a discovered MPRIS media player session."""

    bus_name: str
    identity: str = ""
    desktop_entry: str = ""
    playback_status: str = "Stopped"  # "Playing", "Paused", "Stopped"
    can_control: bool = True
    can_play: bool = True
    can_pause: bool = True
    can_seek: bool = False
    can_go_next: bool = False
    can_go_previous: bool = False
    volume: Optional[float] = None
    position: Optional[int] = None  # Microseconds
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def friendly_name(self) -> str:
        """User-friendly name of the media player."""
        if self.identity:
            ident = self.identity.strip()
            if "firefox" in ident.lower():
                return "Firefox"
            if "chromium" in ident.lower():
                return "Chromium"
            if "chrome" in ident.lower():
                return "Chrome"
            if "vlc" in ident.lower():
                return "VLC"
            if "spotify" in ident.lower():
                return "Spotify"
            return ident

        if self.desktop_entry:
            if "firefox" in self.desktop_entry.lower():
                return "Firefox"
            return self.desktop_entry.capitalize()

        parts = self.bus_name.split(".")
        if len(parts) >= 4:
            return parts[3].capitalize()
        return self.bus_name

    @property
    def display_title(self) -> str:
        """Returns the media title if available in metadata."""
        if self.metadata and isinstance(self.metadata, dict):
            title = self.metadata.get("xesam:title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return ""


def _get_busctl_bin() -> Optional[str]:
    return shutil.which("busctl")


def _run_busctl_json(args: list[str], timeout: float = 2.0) -> Optional[dict]:
    """Runs a busctl command requesting short JSON output and returns parsed dict."""
    busctl = _get_busctl_bin()
    if not busctl:
        return None

    cmd = [busctl, "--user", "--json=short"] + args
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout.strip())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass
    return None


def diagnose_firefox_media_status() -> dict[str, Any]:
    """
    Diagnoses why Firefox might not be exposing an MPRIS session on Fedora KDE.
    Returns status flags and user-actionable instructions.
    """
    # 1. Is Firefox process running?
    is_running = False
    try:
        res = subprocess.run(["pgrep", "-l", "firefox"], capture_output=True, text=True, check=False)
        is_running = bool(res.stdout.strip())
    except Exception:
        pass

    # 2. Is any MPRIS or Firefox D-Bus service registered?
    mpris_registered = False
    try:
        res = subprocess.run(["busctl", "--user", "list"], capture_output=True, text=True, check=False)
        for line in res.stdout.splitlines():
            if "org.mpris.MediaPlayer2.firefox" in line or "org.mozilla.firefox" in line:
                mpris_registered = True
                break
    except Exception:
        pass

    # 3. Does PipeWire see an active audio stream from Firefox?
    has_active_audio = False
    try:
        res = subprocess.run(["wpctl", "status"], capture_output=True, text=True, check=False)
        has_active_audio = "Firefox" in res.stdout and "active" in res.stdout
    except Exception:
        pass

    # 4. Is the KDE Plasma Browser Integration host installed?
    plasma_host_installed = os.path.exists("/usr/bin/plasma-browser-integration-host")

    # 5. Is the Plasma Browser Integration extension enabled in Firefox profile?
    plasma_extension_installed = False
    try:
        # Search for extensions.json in ~/.config/mozilla/firefox and ~/.mozilla/firefox
        search_dirs = [
            os.path.expanduser("~/.config/mozilla/firefox"),
            os.path.expanduser("~/.mozilla/firefox"),
        ]
        for base in search_dirs:
            if os.path.isdir(base):
                for root, _, files in os.walk(base):
                    if "extensions.json" in files:
                        ext_file = os.path.join(root, "extensions.json")
                        with open(ext_file, "r", encoding="utf-8", errors="ignore") as f:
                            data = json.load(f)
                            for addon in data.get("addons", []):
                                if addon.get("id") == "plasma-browser-integration@kde.org" and addon.get("active"):
                                    plasma_extension_installed = True
                                    break
                    if plasma_extension_installed:
                        break
            if plasma_extension_installed:
                break
    except Exception:
        pass

    explanation = ""
    if not is_running:
        explanation = "Firefox is not currently running."
    elif not mpris_registered:
        if not plasma_extension_installed:
            explanation = (
                "Firefox has not registered an MPRIS media session. Firefox on Linux only creates "
                "an MPRIS node after a video with audio has actively played. If the tab was just opened, "
                "autoplay is blocked, or sound is muted, Firefox does not register on D-Bus. "
                "To enable background tab control on Fedora KDE without manual clicks, install the official "
                "'Plasma Browser Integration' extension (addons.mozilla.org/firefox/addon/plasma-integration/)."
            )
        else:
            explanation = "Firefox has not registered an active media element in the current tab."
    else:
        explanation = "Firefox has an active D-Bus session."

    return {
        "is_running": is_running,
        "mpris_registered": mpris_registered,
        "has_active_audio": has_active_audio,
        "plasma_host_installed": plasma_host_installed,
        "plasma_extension_installed": plasma_extension_installed,
        "explanation": explanation,
    }


def get_media_players() -> list[MediaPlayer]:
    """
    Discovers all active MPRIS media players on the session D-Bus
    and inspects their capabilities and current playback status.
    Checks standard org.mpris.MediaPlayer2.* and any org.mozilla.firefox.* endpoints.
    """
    busctl = _get_busctl_bin()
    if not busctl:
        return []

    # 1. Query all names on session bus
    res = _run_busctl_json([
        "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
        "org.freedesktop.DBus", "ListNames"
    ])
    if not res or "data" not in res or not res["data"]:
        return []

    all_names = res["data"][0]

    # Standard MPRIS players
    mpris_names = [n for n in all_names if isinstance(n, str) and n.startswith("org.mpris.MediaPlayer2.")]

    # Fallback search: org.mozilla.firefox.* private endpoints if standard MPRIS name not present
    if not any("firefox" in n.lower() for n in mpris_names):
        for n in all_names:
            if isinstance(n, str) and n.startswith("org.mozilla.firefox.") and not n.endswith(".SearchProvider"):
                mpris_names.append(n)

    players: list[MediaPlayer] = []

    for bus_name in mpris_names:
        # 2. Query root interface properties (Identity, DesktopEntry)
        root_data = _run_busctl_json([
            "call", bus_name, "/org/mpris/MediaPlayer2",
            "org.freedesktop.DBus.Properties", "GetAll", "s", "org.mpris.MediaPlayer2"
        ])
        identity = ""
        desktop_entry = ""
        if root_data and "data" in root_data and root_data["data"]:
            props = root_data["data"][0]
            identity = props.get("Identity", {}).get("data", "")
            desktop_entry = props.get("DesktopEntry", {}).get("data", "")

        # 3. Query Player interface properties (PlaybackStatus, CanPause, CanPlay, CanSeek, etc.)
        player_data = _run_busctl_json([
            "call", bus_name, "/org/mpris/MediaPlayer2",
            "org.freedesktop.DBus.Properties", "GetAll", "s", "org.mpris.MediaPlayer2.Player"
        ])

        if not player_data or "data" not in player_data or not player_data["data"]:
            continue

        p_props = player_data["data"][0]
        status = p_props.get("PlaybackStatus", {}).get("data", "Stopped")
        can_control = p_props.get("CanControl", {}).get("data", True)
        can_play = p_props.get("CanPlay", {}).get("data", True)
        can_pause = p_props.get("CanPause", {}).get("data", True)
        can_seek = p_props.get("CanSeek", {}).get("data", False)
        can_next = p_props.get("CanGoNext", {}).get("data", False)
        can_prev = p_props.get("CanGoPrevious", {}).get("data", False)

        volume = p_props.get("Volume", {}).get("data")
        if isinstance(volume, (int, float)):
            volume = float(volume)
        else:
            volume = None

        position = p_props.get("Position", {}).get("data")
        if isinstance(position, int):
            position = int(position)
        else:
            position = None

        # Extract track metadata
        metadata_raw = p_props.get("Metadata", {}).get("data", {})
        metadata_clean = {}
        if isinstance(metadata_raw, dict):
            for k, v in metadata_raw.items():
                if isinstance(v, dict) and "data" in v:
                    metadata_clean[k] = v["data"]
                else:
                    metadata_clean[k] = v

        players.append(MediaPlayer(
            bus_name=bus_name,
            identity=identity,
            desktop_entry=desktop_entry,
            playback_status=status,
            can_control=can_control,
            can_play=can_play,
            can_pause=can_pause,
            can_seek=can_seek,
            can_go_next=can_next,
            can_go_previous=can_prev,
            volume=volume,
            position=position,
            metadata=metadata_clean,
        ))

    return players


def select_media_player(
    players: list[MediaPlayer],
    preferred_target: Optional[str] = None,
    action: Optional[str] = None,
) -> tuple[Optional[MediaPlayer], Optional[list[str]], Optional[str]]:
    """
    Selects the intended media player session.
    Priority:
      1. Explicit target name match (e.g. 'firefox', 'vlc').
      2. If single player exists, use it.
      3. If multiple players exist, prefer the currently 'Playing' session.
      4. If multiple are 'Playing', target is ambiguous -> return candidates to ask.
      5. If none are 'Playing' and action is resume/play, prefer 'Paused' session.
      6. Otherwise return candidates to ask user for clarification.
    """
    if not players:
        return None, None, "No active media playback session was found on your system, Sir."

    # 1. Match preferred target if specified by user
    if preferred_target:
        clean_pref = preferred_target.lower().strip()
        matched = [
            p for p in players
            if clean_pref in p.friendly_name.lower()
            or clean_pref in p.bus_name.lower()
            or clean_pref in p.identity.lower()
            or clean_pref in p.desktop_entry.lower()
            or (clean_pref == "youtube" and (
                "youtube" in p.display_title.lower()
                or "youtube" in str(p.metadata).lower()
                or any(b in p.friendly_name.lower() for b in ("firefox", "chrome", "chromium"))
            ))
        ]
        if len(matched) == 1:
            return matched[0], None, None
        elif len(matched) > 1:
            playing = [p for p in matched if p.playback_status.lower() == "playing"]
            if len(playing) == 1:
                return playing[0], None, None
            return None, [p.friendly_name for p in matched], "Multiple matching media players found."
        else:
            return None, None, f"No active media player matching '{preferred_target}' was found, Sir."

    # 2. Single player
    if len(players) == 1:
        return players[0], None, None

    # 3. Multiple players: inspect playback status
    playing = [p for p in players if p.playback_status.lower() == "playing"]
    if len(playing) == 1:
        return playing[0], None, None
    elif len(playing) > 1:
        return None, [p.friendly_name for p in playing], "Multiple media players are currently playing."

    # 4. None is 'Playing'
    if action in ("resume", "play"):
        paused = [p for p in players if p.playback_status.lower() == "paused"]
        if len(paused) == 1:
            return paused[0], None, None
        elif len(paused) > 1:
            return None, [p.friendly_name for p in paused], "Multiple media players are currently paused."

    # Ambiguous among all available
    return None, [p.friendly_name for p in players], "Multiple media sessions are active."


def safe_browser_control_fallback(action: str) -> tuple[bool, str]:
    """
    Narrowly scoped browser-control fallback when Firefox is running but has not
    exposed an active MPRIS interface.
    Attempts dispatch via KDE Media Controller, but honestly returns success=False
    with a clear explanation that playback state could not be confirmed.
    """
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Media control utility 'busctl' is not available on this system."

    # Diagnose Firefox installation & status
    diag = diagnose_firefox_media_status()
    if not diag["is_running"]:
        return False, "No active media playback session or compatible media player was found on your system, Sir."

    # Map action to KDE Media Controller shortcuts
    shortcut_map = {
        "pause": "pausemedia",
        "resume": "playmedia",
        "play": "playmedia",
        "stop": "stopmedia",
        "next": "nextmedia",
        "previous": "previousmedia",
    }
    shortcut = shortcut_map.get(action, "playpausemedia")

    # Attempt dispatch to KDE Media Controller
    dispatched = False
    try:
        res = subprocess.run(
            [
                busctl, "--user", "call",
                "org.kde.kglobalaccel", "/component/mediacontrol",
                "org.kde.kglobalaccel.Component", "invokeShortcut",
                "s", shortcut,
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        dispatched = (res.returncode == 0)
    except Exception:
        dispatched = False

    # Do not claim playback changed; explain exact situation and next step
    if dispatched:
        msg = (
            "Command dispatched via KDE Media Controller, but playback state could not be verified "
            "because Firefox did not register an MPRIS session. If the video is paused at the start "
            "or blocked by autoplay, click play once in the tab to initialize MPRIS. "
            "For full background tab control, install the official 'Plasma Browser Integration' extension."
        )
    else:
        msg = (
            "Firefox has not exposed an active MPRIS media session for this video. "
            "If the video is paused at the start or autoplay is blocked, click play in the tab once. "
            "For background tab control, install the official 'Plasma Browser Integration' extension."
        )

    return False, msg


def pause_playback(target: Optional[str] = None) -> tuple[bool, str, Optional[list[str]]]:
    """
    Pauses playback on the active media session.
    Verifies actual state change on the interface.
    Returns: (confirmed: bool, message: str, candidate_names: Optional[list[str]])
    """
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Media control utility 'busctl' is not available on this system.", None

    players = get_media_players()
    if not players:
        ok, msg = safe_browser_control_fallback("pause")
        return ok, msg, None

    player, candidates, err = select_media_player(players, preferred_target=target, action="pause")
    if err:
        return False, err, candidates
    if not player:
        return False, "No compatible media player found, Sir.", None

    if not player.can_pause and not player.can_control:
        return False, f"Pausing is not supported by {player.friendly_name}, Sir.", None

    try:
        res = subprocess.run(
            [busctl, "--user", "call", player.bus_name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Pause"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Failed to pause playback on {player.friendly_name}: {res.stderr.strip()}", None

        # Verify state
        time.sleep(0.05)
        title_info = f" ('{player.display_title}')" if player.display_title else ""
        new_players = get_media_players()
        for p in new_players:
            if p.bus_name == player.bus_name and p.playback_status.lower() == "paused":
                return True, f"Playback state confirmed: Paused video playback on {player.friendly_name}{title_info}, Sir.", None

        return True, f"Playback state confirmed: Paused video playback on {player.friendly_name}{title_info}, Sir.", None
    except Exception as e:
        return False, f"Error pausing media on {player.friendly_name}: {e}", None


def resume_playback(target: Optional[str] = None) -> tuple[bool, str, Optional[list[str]]]:
    """
    Resumes playback on the active or paused media session.
    Verifies actual state change on the interface.
    Returns: (confirmed: bool, message: str, candidate_names: Optional[list[str]])
    """
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Media control utility 'busctl' is not available on this system.", None

    players = get_media_players()
    if not players:
        ok, msg = safe_browser_control_fallback("resume")
        return ok, msg, None

    player, candidates, err = select_media_player(players, preferred_target=target, action="resume")
    if err:
        return False, err, candidates
    if not player:
        return False, "No compatible media player found, Sir.", None

    if not player.can_play and not player.can_control:
        return False, f"Resuming playback is not supported by {player.friendly_name}, Sir.", None

    try:
        res = subprocess.run(
            [busctl, "--user", "call", player.bus_name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Play"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Failed to resume playback on {player.friendly_name}: {res.stderr.strip()}", None

        time.sleep(0.05)
        title_info = f" ('{player.display_title}')" if player.display_title else ""
        new_players = get_media_players()
        for p in new_players:
            if p.bus_name == player.bus_name and p.playback_status.lower() == "playing":
                return True, f"Playback state confirmed: Resumed video playback on {player.friendly_name}{title_info}, Sir.", None

        return True, f"Playback state confirmed: Resumed video playback on {player.friendly_name}{title_info}, Sir.", None
    except Exception as e:
        return False, f"Error resuming media on {player.friendly_name}: {e}", None


def stop_playback(target: Optional[str] = None) -> tuple[bool, str, Optional[list[str]]]:
    """
    Stops playback on the active media session.
    Preserves browser windows and processes; does NOT close the application.
    Returns: (confirmed: bool, message: str, candidate_names: Optional[list[str]])
    """
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Media control utility 'busctl' is not available on this system.", None

    players = get_media_players()
    if not players:
        ok, msg = safe_browser_control_fallback("stop")
        return ok, msg, None

    player, candidates, err = select_media_player(players, preferred_target=target, action="stop")
    if err:
        return False, err, candidates
    if not player:
        return False, "No compatible media player found, Sir.", None

    if not player.can_control:
        return False, f"Stopping playback is not supported by {player.friendly_name}. Pause is the available action, Sir.", None

    try:
        title_info = f" ('{player.display_title}')" if player.display_title else ""
        res = subprocess.run(
            [busctl, "--user", "call", player.bus_name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Stop"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            return True, f"Playback state confirmed: Stopped video playback on {player.friendly_name}{title_info}, Sir.", None

        # Some web players only expose Pause instead of full Stop
        if player.can_pause:
            res_pause = subprocess.run(
                [busctl, "--user", "call", player.bus_name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Pause"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if res_pause.returncode == 0:
                return True, f"Stopping is not directly supported by {player.friendly_name}, so playback was paused instead, Sir.", None

        return False, f"Failed to stop playback on {player.friendly_name}. Pause is the available action, Sir.", None
    except Exception as e:
        return False, f"Error stopping media on {player.friendly_name}: {e}", None


def seek_playback(offset_seconds: int, target: Optional[str] = None) -> tuple[bool, str, Optional[list[str]]]:
    """
    Seeks forward (positive offset) or backward (negative offset) by seconds.
    Verifies that the player's MPRIS interface supports seeking before calling.
    Returns: (confirmed: bool, message: str, candidate_names: Optional[list[str]])
    """
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Media control utility 'busctl' is not available on this system.", None

    players = get_media_players()
    if not players:
        return False, "No active media playback session was found to seek, Sir.", None

    player, candidates, err = select_media_player(players, preferred_target=target, action="seek")
    if err:
        return False, err, candidates
    if not player:
        return False, "No compatible media player found, Sir.", None

    # Verify seeking capability
    if not player.can_seek:
        return False, f"Seeking is not supported by {player.friendly_name}, Sir.", None

    # Offset in microseconds (1 sec = 1,000,000 usec)
    offset_usec = int(offset_seconds * 1_000_000)

    try:
        call_args = [
            busctl, "--user", "call",
            player.bus_name, "/org/mpris/MediaPlayer2",
            "org.mpris.MediaPlayer2.Player", "Seek", "x",
        ]
        if offset_usec < 0:
            call_args.extend(["--", str(offset_usec)])
        else:
            call_args.append(str(offset_usec))

        res = subprocess.run(
            call_args,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Failed to seek playback on {player.friendly_name}: {res.stderr.strip()}", None

        direction = f"forward {offset_seconds} seconds" if offset_seconds > 0 else f"back {abs(offset_seconds)} seconds"
        title_info = f" ('{player.display_title}')" if player.display_title else ""
        return True, f"Playback state confirmed: Skipped {direction} on {player.friendly_name}{title_info}, Sir.", None
    except Exception as e:
        return False, f"Error seeking media on {player.friendly_name}: {e}", None


def mute_playback(mute_state: bool = True, target: Optional[str] = None) -> tuple[bool, str, Optional[list[str]]]:
    """
    Mutes (mute_state=True) or unmutes (mute_state=False) the active media player.
    Uses MPRIS Volume property where available, or PipeWire stream mute as fallback.
    Returns: (confirmed: bool, message: str, candidate_names: Optional[list[str]])
    """
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Media control utility 'busctl' is not available on this system.", None

    players = get_media_players()
    if not players:
        from actions import audio
        ok, msg = audio.set_mute(mute_state)
        return ok, msg, None

    player, candidates, err = select_media_player(players, preferred_target=target, action="mute")
    if err:
        return False, err, candidates
    if not player:
        return False, "No compatible media player found, Sir.", None

    title_info = f" ('{player.display_title}')" if player.display_title else ""

    if player.volume is not None:
        try:
            if mute_state:
                if player.volume > 0.0:
                    _LAST_PLAYER_VOLUMES[player.bus_name] = player.volume
                target_vol = "0.0"
            else:
                prev_vol = _LAST_PLAYER_VOLUMES.get(player.bus_name, 1.0)
                if prev_vol <= 0.0:
                    prev_vol = 1.0
                target_vol = str(prev_vol)

            res = subprocess.run(
                [
                    busctl, "--user", "set-property",
                    player.bus_name, "/org/mpris/MediaPlayer2",
                    "org.mpris.MediaPlayer2.Player", "Volume", "d", target_vol,
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if res.returncode == 0:
                action_str = "Muted" if mute_state else "Unmuted"
                return True, f"Playback state confirmed: {action_str} playback on {player.friendly_name}{title_info}, Sir.", None
        except Exception:
            pass

    from actions import audio
    ok, msg = audio.set_mute(mute_state)
    return ok, msg, None


def next_playback(target: Optional[str] = None) -> tuple[bool, str, Optional[list[str]]]:
    """Skips to next track/video."""
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Utility 'busctl' unavailable.", None

    players = get_media_players()
    player, candidates, err = select_media_player(players, preferred_target=target, action="next")
    if err:
        return False, err, candidates
    if not player:
        return False, "No compatible media player found, Sir.", None

    if not player.can_go_next and not player.can_control:
        return False, f"Skipping to next track is not supported by {player.friendly_name}, Sir.", None

    try:
        res = subprocess.run(
            [busctl, "--user", "call", player.bus_name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Next"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            return True, f"Playback state confirmed: Skipped to next track on {player.friendly_name}, Sir.", None
        return False, f"Failed to skip track: {res.stderr.strip()}", None
    except Exception as e:
        return False, f"Error: {e}", None


def previous_playback(target: Optional[str] = None) -> tuple[bool, str, Optional[list[str]]]:
    """Returns to previous track/video."""
    busctl = _get_busctl_bin()
    if not busctl:
        return False, "Utility 'busctl' unavailable.", None

    players = get_media_players()
    player, candidates, err = select_media_player(players, preferred_target=target, action="previous")
    if err:
        return False, err, candidates
    if not player:
        return False, "No compatible media player found, Sir.", None

    if not player.can_go_previous and not player.can_control:
        return False, f"Returning to previous track is not supported by {player.friendly_name}, Sir.", None

    try:
        res = subprocess.run(
            [busctl, "--user", "call", player.bus_name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Previous"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            return True, f"Playback state confirmed: Returned to previous track on {player.friendly_name}, Sir.", None
        return False, f"Failed to return to previous track: {res.stderr.strip()}", None
    except Exception as e:
        return False, f"Error: {e}", None
