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


def _run_shortcut(desc: str, wtype_args: list[str], ydotool_args: list[str], xdotool_args: list[str]) -> bool:
    """
    Attempts to simulate a shortcut using available tools with return code verification.
    Tries ydotool first, then wtype, then xdotool.
    """
    # 1. Try ydotool (Kernel uinput-level; works on all Wayland compositors including KDE)
    if shutil.which("ydotool"):
        try:
            res = subprocess.run(
                ["ydotool"] + ydotool_args,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                print(f"[JARVIS] {desc} (via ydotool)...")
                return True
        except Exception:
            pass

    # 2. Try wtype (only works on compositors supporting zwp_virtual_keyboard_v1)
    if shutil.which("wtype"):
        try:
            res = subprocess.run(
                ["wtype"] + wtype_args,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                print(f"[JARVIS] {desc} (via wtype)...")
                return True
        except Exception:
            pass

    # 3. Try xdotool (works on X11 / Xwayland)
    if shutil.which("xdotool"):
        try:
            res = subprocess.run(
                ["xdotool"] + xdotool_args,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                print(f"[JARVIS] {desc} (via xdotool)...")
                return True
        except Exception:
            pass

    # If all failed or none available, provide an honest, actionable error message
    print(f"[JARVIS Error] Could not perform '{desc}'.")
    print("               On Fedora KDE Plasma (Wayland), 'wtype' is not supported by KWin.")
    print("               To enable tab closing and keyboard automation, please install ydotool:")
    print("                 sudo dnf install ydotool")
    print("                 sudo ydotoold &")
    return False


def type_text(content: str, press_enter: bool = False):
    """
    Types content into the currently focused window using ydotool, wtype, or xdotool.
    """
    # 1. Try ydotool
    if shutil.which("ydotool"):
        try:
            res = subprocess.run(
                ["ydotool", "type", "--", content],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                print(f"[JARVIS] Typing \"{content}\" via ydotool...")
                if press_enter:
                    time.sleep(0.05)
                    subprocess.run(["ydotool", "key", "28:1", "28:0"], capture_output=True, check=False)
                return
        except Exception:
            pass

    # 2. Try wtype
    if shutil.which("wtype"):
        try:
            res = subprocess.run(
                ["wtype", "--", content],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                print(f"[JARVIS] Typing \"{content}\" via wtype...")
                if press_enter:
                    time.sleep(0.05)
                    subprocess.run(["wtype", "-k", "Return"], capture_output=True, check=False)
                return
        except Exception:
            pass

    # 3. Try xdotool
    if shutil.which("xdotool"):
        try:
            res = subprocess.run(
                ["xdotool", "type", "--", content],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                print(f"[JARVIS] Typing \"{content}\" via xdotool...")
                if press_enter:
                    time.sleep(0.05)
                    subprocess.run(["xdotool", "key", "Return"], capture_output=True, check=False)
                return
        except Exception:
            pass

    print("[JARVIS Error] Could not simulate typing: No working keyboard automation tool found.")
    print("               On Fedora KDE Plasma (Wayland), 'wtype' is not supported by KWin.")
    print("               To enable typing into fields, please install ydotool:")
    print("                 sudo dnf install ydotool")
    print("                 sudo ydotoold &")


def close_browser_tab() -> bool:
    """
    Closes the current browser tab using Ctrl+W after verifying:
    1. The active window is a web browser.
    2. A working keyboard automation tool (ydotool/wtype/xdotool) is available.
    """
    # 1. Verify active window is a browser
    is_browser, win_id = verify_browser_active()
    if not is_browser and win_id != "unknown":
        print(f"[JARVIS Warning] Active window appears to be '{win_id}', not a web browser.")
        print("                 Tab closure aborted to prevent closing another application.")
        return False

    return _run_shortcut(
        desc="Closing current browser tab via Ctrl+W",
        wtype_args=["-M", "ctrl", "-k", "w", "-m", "ctrl"],
        ydotool_args=["key", "29:1", "17:1", "17:0", "29:0"],
        xdotool_args=["key", "ctrl+w"],
    )


def send_browser_shortcut(action_name: str) -> bool:
    """Sends browser navigation keystrokes via ydotool, wtype, or xdotool."""
    if action_name == "close_tab":
        return close_browser_tab()

    shortcuts = {
        "next_tab": {
            "wtype": ["-M", "ctrl", "-k", "Tab", "-m", "ctrl"],
            "ydotool": ["key", "29:1", "15:1", "15:0", "29:0"],
            "xdotool": ["key", "ctrl+Tab"],
            "desc": "Switching to next tab",
        },
        "back": {
            "wtype": ["-M", "alt", "-k", "Left", "-m", "alt"],
            "ydotool": ["key", "56:1", "105:1", "105:0", "56:0"],
            "xdotool": ["key", "alt+Left"],
            "desc": "Navigating back",
        },
        "forward": {
            "wtype": ["-M", "alt", "-k", "Right", "-m", "alt"],
            "ydotool": ["key", "56:1", "106:1", "106:0", "56:0"],
            "xdotool": ["key", "alt+Right"],
            "desc": "Navigating forward",
        },
        "refresh": {
            "wtype": ["-k", "F5"],
            "ydotool": ["key", "63:1", "63:0"],
            "xdotool": ["key", "F5"],
            "desc": "Refreshing page",
        },
    }

    if action_name not in shortcuts:
        return False

    info = shortcuts[action_name]
    return _run_shortcut(
        desc=info["desc"],
        wtype_args=info["wtype"],
        ydotool_args=info["ydotool"],
        xdotool_args=info["xdotool"],
    )

