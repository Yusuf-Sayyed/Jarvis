"""
Keyboard automation: Text typing and browser navigation shortcuts on Fedora KDE.
Includes active window verification and tool availability checks.
"""

import shutil
import subprocess
import time

SUPPORTED_BROWSERS = ("firefox", "chrome", "chromium", "brave", "edge", "navigator")


def get_active_window_class() -> str | None:
    """
    Attempts to identify the active window class on Fedora KDE.
    Uses xprop for Xwayland/X11 windows.
    """
    try:
        out = subprocess.check_output(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1,
        )
        win_id = out.strip().split()[-1]
        if win_id and win_id != "0x0":
            prop = subprocess.check_output(
                ["xprop", "-id", win_id, "WM_CLASS"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            if "WM_CLASS" in prop and "=" in prop:
                return prop.split("=", 1)[1].strip().lower()
    except Exception:
        pass
    return None


def verify_browser_active() -> tuple[bool, str]:
    """
    Checks if the active window is a supported web browser to prevent
    accidentally closing or typing into other applications.

    Returns:
        (is_browser: bool, identifier: str)
    """
    # 1. Check active window class if readable
    win_class = get_active_window_class()
    if win_class:
        for browser in SUPPORTED_BROWSERS:
            if browser in win_class:
                return True, browser
        return False, win_class

    # 2. Check if a supported browser process is even running
    try:
        pids = subprocess.check_output(["pgrep", "-l", "firefox"], text=True, stderr=subprocess.DEVNULL)
        if pids.strip():
            return True, "firefox"
    except Exception:
        pass

    return False, "unknown"


def type_text(content: str, press_enter: bool = False):
    """
    Types content into the currently focused window using wtype (Wayland)
    or xdotool/ydotool if available.
    """
    # 1. Native Wayland virtual keyboard (wtype)
    if shutil.which("wtype"):
        print(f"[JARVIS] Typing \"{content}\" via wtype...")
        subprocess.run(["wtype", "--", content], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if press_enter:
            time.sleep(0.05)
            subprocess.run(["wtype", "-k", "Return"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return

    # 2. X11 / Xwayland fallback (xdotool)
    if shutil.which("xdotool"):
        print(f"[JARVIS] Typing \"{content}\" via xdotool...")
        subprocess.run(["xdotool", "type", "--", content], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if press_enter:
            time.sleep(0.05)
            subprocess.run(["xdotool", "key", "Return"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return

    # 3. ydotool fallback
    if shutil.which("ydotool"):
        print(f"[JARVIS] Typing \"{content}\" via ydotool...")
        subprocess.run(["ydotool", "type", "--", content], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if press_enter:
            time.sleep(0.05)
            subprocess.run(["ydotool", "key", "28:1", "28:0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return

    # No typing tool detected
    print("[JARVIS Error] Desktop keystroke typing requires 'wtype' on Fedora KDE Wayland.")
    print("               To enable typing into fields, run: sudo dnf install wtype")


def close_browser_tab() -> bool:
    """
    Closes the current browser tab using Ctrl+W after verifying:
    1. An automation tool (wtype/xdotool) is available.
    2. The active window is not another application (e.g. terminal or IDE).
    """
    # 1. Verify active window is a browser
    is_browser, win_id = verify_browser_active()
    if not is_browser and win_id != "unknown":
        print(f"[JARVIS Warning] Active window appears to be '{win_id}', not a web browser.")
        print("                 Tab closure aborted to prevent closing another application.")
        return False

    # 2. Check for automation tool
    if shutil.which("wtype"):
        print("[JARVIS] Closing current browser tab via Ctrl+W (wtype)...")
        subprocess.run(["wtype", "-M", "ctrl", "-k", "w", "-m", "ctrl"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True

    if shutil.which("xdotool"):
        print("[JARVIS] Closing current browser tab via Ctrl+W (xdotool)...")
        subprocess.run(["xdotool", "key", "ctrl+w"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True

    print("[JARVIS Error] Closing tab via Ctrl+W requires 'wtype' on Fedora KDE Wayland.")
    print("               To enable keyboard shortcuts, please run: sudo dnf install wtype")
    return False


def send_browser_shortcut(action_name: str) -> bool:
    """Sends browser navigation keystrokes via wtype or xdotool."""
    if action_name == "close_tab":
        return close_browser_tab()

    shortcuts = {
        "next_tab": {
            "wtype": [["wtype", "-M", "ctrl", "-k", "Tab", "-m", "ctrl"]],
            "xdotool": [["xdotool", "key", "ctrl+Tab"]],
            "desc": "Switching to next tab",
        },
        "back": {
            "wtype": [["wtype", "-M", "alt", "-k", "Left", "-m", "alt"]],
            "xdotool": [["xdotool", "key", "alt+Left"]],
            "desc": "Navigating back",
        },
        "forward": {
            "wtype": [["wtype", "-M", "alt", "-k", "Right", "-m", "alt"]],
            "xdotool": [["xdotool", "key", "alt+Right"]],
            "desc": "Navigating forward",
        },
        "refresh": {
            "wtype": [["wtype", "-k", "F5"]],
            "xdotool": [["xdotool", "key", "F5"]],
            "desc": "Refreshing page",
        },
    }

    if action_name not in shortcuts:
        return False

    info = shortcuts[action_name]

    if shutil.which("wtype"):
        print(f"[JARVIS] {info['desc']} (via wtype)...")
        for cmd in info["wtype"]:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True

    if shutil.which("xdotool"):
        print(f"[JARVIS] {info['desc']} (via xdotool)...")
        for cmd in info["xdotool"]:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True

    print(f"[JARVIS Error] {info['desc']} requires 'wtype' on Fedora KDE Wayland.")
    print("               To enable browser shortcuts, run: sudo dnf install wtype")
    return False
