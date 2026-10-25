"""
Keyboard automation: Text typing and browser navigation shortcuts on Fedora KDE.
"""

import shutil
import subprocess
import time


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


def send_browser_shortcut(action_name: str):
    """Sends browser navigation keystrokes via wtype or xdotool."""
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
        "close_tab": {
            "wtype": [["wtype", "-M", "ctrl", "-k", "w", "-m", "ctrl"]],
            "xdotool": [["xdotool", "key", "ctrl+w"]],
            "desc": "Closing current tab",
        },
    }

    if action_name not in shortcuts:
        return

    info = shortcuts[action_name]

    if shutil.which("wtype"):
        print(f"[JARVIS] {info['desc']} (via wtype)...")
        for cmd in info["wtype"]:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return

    if shutil.which("xdotool"):
        print(f"[JARVIS] {info['desc']} (via xdotool)...")
        for cmd in info["xdotool"]:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return

    print(f"[JARVIS Error] {info['desc']} requires 'wtype' on Fedora KDE Wayland.")
    print("               To enable browser shortcuts, run: sudo dnf install wtype")
