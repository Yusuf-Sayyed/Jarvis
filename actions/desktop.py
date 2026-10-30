"""
Desktop application and folder launchers for Fedora KDE.
"""

import os
import shutil
import subprocess


def open_browser() -> bool:
    """Opens the configured default web browser (or Firefox)."""
    from actions.resolver import get_app_registry
    app_registry = get_app_registry()
    app_info = app_registry.get_default_browser() or app_registry.resolve_application("browser")
    exec_path = app_info.exec_path if app_info else (shutil.which("firefox") or "/usr/bin/firefox")
    app_name = app_info.name if app_info else "Firefox"

    if not exec_path or not (os.path.isfile(exec_path) or shutil.which(exec_path)):
        print(f"[JARVIS Error] Web browser was not found on this system.")
        return False

    try:
        print(f"[JARVIS] Opening {app_name}...")
        subprocess.Popen([exec_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[JARVIS] {app_name} launched successfully.")
        return True
    except Exception as e:
        print(f"[JARVIS Error] Failed to launch {app_name}: {e}")
        return False


def open_firefox() -> bool:
    """Opens the Firefox web browser."""
    firefox_bin = shutil.which("firefox") or "/usr/bin/firefox"
    if not (os.path.isfile(firefox_bin) or shutil.which(firefox_bin)):
        print("[JARVIS Error] Firefox was not found on this system.")
        return False

    try:
        print("[JARVIS] Opening Firefox...")
        subprocess.Popen([firefox_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[JARVIS] Firefox launched successfully.")
        return True
    except Exception as e:
        print(f"[JARVIS Error] Failed to launch Firefox: {e}")
        return False


def launch_application(app_name: str) -> tuple[bool, str]:
    """Resolves and launches any registered desktop application."""
    from actions.resolver import get_app_registry
    app_info = get_app_registry().resolve_application(app_name)
    if not app_info or not app_info.exec_path:
        msg = f"Application '{app_name}' was not found on this system."
        print(f"[JARVIS Error] {msg}")
        return False, msg

    try:
        print(f"[JARVIS] Opening {app_info.name}...")
        subprocess.Popen([app_info.exec_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        msg = f"{app_info.name} launched successfully."
        print(f"[JARVIS] {msg}")
        return True, msg
    except Exception as e:
        msg = f"Failed to launch {app_info.name}: {e}"
        print(f"[JARVIS Error] {msg}")
        return False, msg


def open_terminal() -> bool:
    """Opens the Konsole terminal emulator (standard on Fedora KDE)."""
    konsole_bin = shutil.which("konsole")
    if not konsole_bin:
        print("[JARVIS Error] Konsole terminal was not found on this system.")
        return False

    try:
        print("[JARVIS] Opening Konsole terminal...")
        subprocess.Popen([konsole_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[JARVIS] Konsole terminal launched successfully.")
        return True
    except Exception as e:
        print(f"[JARVIS Error] Failed to launch Konsole: {e}")
        return False


_KONSOLE_BIN = shutil.which("konsole")
_SPECTACLE_BIN = shutil.which("spectacle")
_QDBUS_BIN = shutil.which("qdbus-qt6") or shutil.which("qdbus")
_OPENER_BIN = shutil.which("xdg-open") or shutil.which("dolphin") or "xdg-open"


def open_folder(folder_target: str) -> tuple[bool, str]:
    """
    Opens a folder using the system file manager (xdg-open / dolphin).
    Supports common folder names ('downloads', 'documents', 'desktop', 'pictures',
    'music', 'videos', 'home', 'projects') as well as arbitrary resolved project paths.
    """
    import re
    clean = folder_target.lower().strip()
    clean = re.sub(r"^(?:open|launch)\s+", "", clean)
    clean = re.sub(r"(?:\s+(?:folder|directory))+$", "", clean).strip()

    common_map = {
        "downloads": os.path.expanduser("~/Downloads"),
        "download": os.path.expanduser("~/Downloads"),
        "documents": os.path.expanduser("~/Documents"),
        "document": os.path.expanduser("~/Documents"),
        "desktop": os.path.expanduser("~/Desktop"),
        "pictures": os.path.expanduser("~/Pictures"),
        "picture": os.path.expanduser("~/Pictures"),
        "photos": os.path.expanduser("~/Pictures"),
        "music": os.path.expanduser("~/Music"),
        "videos": os.path.expanduser("~/Videos"),
        "video": os.path.expanduser("~/Videos"),
        "home": os.path.expanduser("~"),
        "projects": os.path.expanduser("~/projects"),
    }

    resolved_path = common_map.get(clean)
    if not resolved_path:
        if os.path.isabs(folder_target) and os.path.isdir(folder_target):
            resolved_path = folder_target
        else:
            from actions.resolver import get_directory_resolver
            resolved_path, candidates = get_directory_resolver().resolve_project_directory(clean)

    if not resolved_path or not os.path.isdir(resolved_path):
        msg = f"Folder '{folder_target}' could not be located on this system."
        print(f"[JARVIS Error] {msg}")
        return False, msg

    opener = _OPENER_BIN or shutil.which("xdg-open") or "xdg-open"
    folder_name = os.path.basename(resolved_path) or resolved_path
    try:
        print(f"[JARVIS] Opening {folder_name} folder ({resolved_path})...")
        subprocess.Popen([opener, resolved_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        msg = f"Opening {folder_name} folder, Sir."
        print(f"[JARVIS] {msg}")
        return True, msg
    except Exception as e:
        msg = f"Failed to open folder: {e}"
        print(f"[JARVIS Error] {msg}")
        return False, msg


def open_downloads():
    """Opens the user's Downloads folder using xdg-open."""
    open_folder("downloads")


def open_youtube():
    """Opens YouTube in the system default web browser."""
    print("[JARVIS] Opening YouTube...")
    subprocess.Popen(["xdg-open", "https://www.youtube.com"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def take_screenshot(mode: str = "fullscreen") -> tuple[bool, str]:
    """
    Captures a screenshot using KDE Spectacle.
    Returns (success, message).
    """
    spectacle_bin = shutil.which("spectacle")
    if not spectacle_bin:
        print("[JARVIS Error] KDE Spectacle is not installed on this system.")
        return False, "Screenshot tool 'spectacle' is not available."

    try:
        print("[JARVIS] Capturing screenshot via Spectacle...")
        # -b (background save), -f (fullscreen)
        if mode == "fullscreen":
            subprocess.Popen([spectacle_bin, "-b", "-f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([spectacle_bin, "-r"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[JARVIS] Screenshot captured and saved to your Pictures folder, Sir.")
        return True, "Screenshot captured successfully."
    except Exception as e:
        print(f"[JARVIS Error] Failed to capture screenshot: {e}")
        return False, f"Screenshot capture failed: {e}"


def control_window(action: str) -> tuple[bool, str]:
    """
    Controls desktop windows on KDE Wayland using KWin global shortcuts via D-Bus.
    Supported actions: 'minimize', 'maximize', 'show_desktop', 'switch'.
    """
    qdbus = shutil.which("qdbus-qt6") or shutil.which("qdbus")
    if not qdbus:
        return False, "KDE D-Bus tool (qdbus-qt6) is not available on this system."

    shortcut_map = {
        "minimize": "Window Minimize",
        "maximize": "Window Maximize",
        "show_desktop": "Show Desktop",
        "switch": "Walk Through Windows",
    }
    shortcut = shortcut_map.get(action.lower().strip())
    if not shortcut:
        return False, f"Unsupported window action: '{action}'."

    try:
        res = subprocess.run(
            [qdbus, "org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component.invokeShortcut", shortcut],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Failed to execute window action '{action}': {res.stderr.strip()}"
        return True, f"Window action '{action}' performed successfully."
    except Exception as e:
        return False, f"Error executing window action: {e}"


def minimize_window() -> tuple[bool, str]:
    return control_window("minimize")


def maximize_window() -> tuple[bool, str]:
    return control_window("maximize")


def show_desktop() -> tuple[bool, str]:
    return control_window("show_desktop")


def switch_window() -> tuple[bool, str]:
    return control_window("switch")

