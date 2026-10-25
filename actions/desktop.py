"""
Desktop application and folder launchers for Fedora KDE.
"""

import os
import subprocess


def open_firefox():
    """Opens the Firefox web browser."""
    print("[JARVIS] Opening Firefox...")
    subprocess.Popen(["firefox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_terminal():
    """Opens the Konsole terminal emulator (standard on Fedora KDE)."""
    print("[JARVIS] Opening Konsole terminal...")
    subprocess.Popen(["konsole"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_downloads():
    """Opens the user's Downloads folder using xdg-open."""
    downloads_path = os.path.expanduser("~/Downloads")
    print(f"[JARVIS] Opening Downloads folder ({downloads_path})...")
    subprocess.Popen(["xdg-open", downloads_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_youtube():
    """Opens YouTube in the system default web browser."""
    print("[JARVIS] Opening YouTube...")
    subprocess.Popen(["xdg-open", "https://www.youtube.com"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
