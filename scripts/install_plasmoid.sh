#!/usr/bin/env bash
set -e

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/packaging/plasmoid/org.kde.plasma.jarvisstatus"
TARGET_DIR="$HOME/.local/share/plasma/plasmoids/org.kde.plasma.jarvisstatus"

echo "[JARVIS] Installing KDE Plasma 6 status widget..."
mkdir -p "$TARGET_DIR"
cp -rf "$SOURCE_DIR/"* "$TARGET_DIR/"
echo "[JARVIS] Plasmoid installed successfully to: $TARGET_DIR"
echo "[JARVIS] To add to your KDE panel:"
echo "         1. Right-click your KDE panel (top or bottom)."
echo "         2. Select 'Add Widgets...' or 'Enter Edit Mode' -> 'Add Widgets...'."
echo "         3. Search for 'JARVIS Status' and drag it onto your panel."
