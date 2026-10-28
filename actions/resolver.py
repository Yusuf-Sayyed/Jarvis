"""
Application and project filesystem resolver for Fedora KDE.
Discovers installed desktop applications from .desktop launchers and resolves
project directories, aliases, and likely speech-recognition variants safely.
"""

import glob
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.memory import get_memory_store


@dataclass
class AppInfo:
    name: str
    exec_path: str
    desktop_file: Optional[str] = None
    aliases: list[str] = None


class AppRegistry:
    """Discovers and caches installed desktop applications and their aliases."""

    def __init__(self):
        self._apps: dict[str, AppInfo] = {}
        self._scanned = False
        self._init_curated_aliases()

    def _init_curated_aliases(self):
        """Hardcoded base aliases for key Fedora KDE desktop tools."""
        self._curated_aliases = {
            "antigravity": [
                "antigravity", "antigravity ide", "anti-gravity", "anti gravity",
                "anti-gravity ide", "anti gravity ide", "anti-gravity editor",
                "anti gravity editor", "antigravity editor",
                "ide", "editor", "code", "vs code", "vscode"
            ],
            "konsole": ["konsole", "terminal", "console"],
            "firefox": ["firefox", "browser", "web browser"],
            "dolphin": ["dolphin", "files", "file manager"],
            "spectacle": ["spectacle", "screenshot", "capture"],
            "kwrite": ["kwrite", "text editor", "notepad"],
            "plasma-systemmonitor": ["system monitor", "task manager", "plasma system monitor", "activity monitor"],
        }

    def scan_applications(self, force_rescan: bool = False):
        """Scans /usr/share/applications and user local desktop directories."""
        if self._scanned and not force_rescan:
            return

        self._apps.clear()
        search_dirs = [
            Path("/usr/share/applications"),
            Path.home() / ".local" / "share" / "applications",
        ]

        # 1. Check for custom user AppImage / standalone installations
        antigravity_bin = Path.home() / "Applications" / "Antigravity IDE" / "antigravity"
        if antigravity_bin.is_file():
            self._register_app(
                AppInfo(
                    name="Antigravity IDE",
                    exec_path=str(antigravity_bin),
                    aliases=self._curated_aliases.get("antigravity", []),
                )
            )

        # 2. Scan standard .desktop files
        for s_dir in search_dirs:
            if not s_dir.is_dir():
                continue
            for desktop_path in s_dir.glob("*.desktop"):
                self._parse_desktop_file(desktop_path)

        self._scanned = True

    def _parse_desktop_file(self, desktop_file: Path):
        try:
            name, exec_cmd, no_display = "", "", False
            with open(desktop_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("Name=") and not name:
                        name = line.split("=", 1)[1].strip()
                    elif line.startswith("Exec=") and not exec_cmd:
                        raw_exec = line.split("=", 1)[1].strip()
                        # Remove field codes like %u, %F, %U
                        exec_cmd = re.sub(r"%[a-zA-Z]", "", raw_exec).strip()
                    elif line == "NoDisplay=true":
                        no_display = True

            if no_display or not name or not exec_cmd:
                return

            tokens = shlex.split(exec_cmd)
            if not tokens:
                return

            binary_name = os.path.basename(tokens[0])
            resolved_bin = shutil.which(tokens[0]) or (tokens[0] if os.path.isabs(tokens[0]) and os.path.isfile(tokens[0]) else None)

            if resolved_bin:
                app_info = AppInfo(
                    name=name,
                    exec_path=resolved_bin,
                    desktop_file=str(desktop_file),
                    aliases=[name.lower(), binary_name.lower()],
                )
                self._register_app(app_info)

        except Exception:
            pass

    def _register_app(self, app_info: AppInfo):
        key = app_info.name.lower()
        if key not in self._apps:
            self._apps[key] = app_info

        # Also index by aliases
        for a in app_info.aliases:
            a_clean = a.lower().strip()
            if a_clean not in self._apps:
                self._apps[a_clean] = app_info

        # Apply curated aliases
        for canon, aliases in self._curated_aliases.items():
            if canon in key or (app_info.exec_path and canon in os.path.basename(app_info.exec_path).lower()):
                for a in aliases:
                    self._apps[a.lower().strip()] = app_info

    def get_default_browser(self) -> Optional[AppInfo]:
        """Resolves the system configured default web browser or falls back to Firefox."""
        self.scan_applications()
        # 1. Try xdg-settings
        try:
            cmd = shutil.which("xdg-settings")
            if cmd:
                res = subprocess.run([cmd, "get", "default-web-browser"], capture_output=True, text=True, timeout=1.0)
                if res.returncode == 0 and res.stdout.strip():
                    desktop_id = res.stdout.strip().lower()
                    clean_id = re.sub(r"\.desktop$", "", desktop_id)
                    for app in self._apps.values():
                        if app.desktop_file and desktop_id in os.path.basename(app.desktop_file).lower():
                            return app
                        if clean_id in os.path.basename(app.exec_path).lower():
                            return app
        except Exception:
            pass

        # 2. Check BROWSER environment variable
        env_browser = os.environ.get("BROWSER")
        if env_browser:
            resolved = self.resolve_application(env_browser)
            if resolved:
                return resolved

        # 3. Fall back to curated alias 'browser' or 'firefox'
        return self._apps.get("browser") or self._apps.get("firefox")

    def resolve_application(self, spoken_name: str) -> Optional[AppInfo]:
        """Resolves a spoken application query to an installed AppInfo."""
        self.scan_applications()
        clean = spoken_name.lower().strip()

        # Check default browser explicitly
        if clean in ("browser", "web browser", "default browser", "the browser"):
            default_browser = self.get_default_browser()
            if default_browser:
                return default_browser

        # Check direct alias/name match
        if clean in self._apps:
            return self._apps[clean]

        # Check binary in system PATH directly
        bin_path = shutil.which(clean)
        if bin_path:
            return AppInfo(name=clean.capitalize(), exec_path=bin_path, aliases=[clean])

        # Substring / fuzzy match
        for key, app in self._apps.items():
            if clean in key or key in clean:
                return app

        return None


class DirectoryResolver:
    """Discovers project directories and known filesystem paths safely."""

    def __init__(self):
        self.memory = get_memory_store()

    def resolve_project_directory(self, project_name: str) -> tuple[Optional[str], list[str]]:
        """
        Resolves a project directory name to an absolute path.
        Returns:
            (best_match_path, all_candidate_paths)
            If multiple candidates exist, best_match_path is None, and all_candidate_paths
            contains the matches to allow JARVIS to ask a clarification question.
        """
        clean_name = project_name.lower().strip()
        # Clean phrases like "my lensify project", "lensify project folder"
        clean_name = re.sub(r"^(?:my\s+|the\s+)", "", clean_name)
        clean_name = re.sub(r"(?:\s+(?:project|folder|directory|repo))+$", "", clean_name).strip()
        # Repair common speech phonetic variants (e.g. "lens 5" -> "lensify")
        clean_name = re.sub(r"\b(?:lens\s*(?:5|five|fy|ify|i\s*fy|if\s*i)|lensi+fy)\b", "lensify", clean_name, flags=re.IGNORECASE).strip()

        # 1. Check memory store first (< 1ms fast-path)
        cached = self.memory.get_project(clean_name)
        if cached and os.path.isdir(cached["resolved_path"]):
            return cached["resolved_path"], [cached["resolved_path"]]

        # 2. Search common project root locations
        search_roots = [
            Path.home() / "Desktop",
            Path.home() / "projects",
            Path.home() / "Documents",
            Path.home(),
        ]

        clean_compact = clean_name.replace(" ", "").replace("-", "").replace("_", "")

        candidates = []
        for root in search_roots:
            if not root.is_dir():
                continue
            try:
                # Direct check
                direct_candidate = root / clean_name
                if direct_candidate.is_dir() and str(direct_candidate) not in candidates:
                    candidates.append(str(direct_candidate))

                # Shallow scan of immediate subdirectories
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    child_compact = child.name.lower().replace(" ", "").replace("-", "").replace("_", "")
                    if child.name.lower() == clean_name or (clean_compact and child_compact == clean_compact):
                        c_str = str(child.resolve())
                        if c_str not in candidates:
                            candidates.append(c_str)
            except Exception:
                pass

        if len(candidates) == 1:
            # Save to memory store for instant future recall
            self.memory.save_project(clean_name, candidates[0])
            return candidates[0], candidates

        if len(candidates) > 1:
            # Ambiguity: return all matches so caller can ask for clarification
            return None, candidates

        return None, []


# Global instances
_REGISTRY: Optional[AppRegistry] = None
_DIR_RESOLVER: Optional[DirectoryResolver] = None


def get_app_registry() -> AppRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = AppRegistry()
    return _REGISTRY


def get_directory_resolver() -> DirectoryResolver:
    global _DIR_RESOLVER
    if _DIR_RESOLVER is None:
        _DIR_RESOLVER = DirectoryResolver()
    return _DIR_RESOLVER
