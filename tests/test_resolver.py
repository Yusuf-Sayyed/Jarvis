"""
Unit tests for actions/resolver.py application and directory resolver.
"""

import tempfile
import unittest
from pathlib import Path

from actions.resolver import AppRegistry, DirectoryResolver
from core.memory import MemoryStore


class TestResolver(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_resolver_mem.sqlite"
        self.memory = MemoryStore(db_path=self.db_path)
        self.app_registry = AppRegistry()
        self.dir_resolver = DirectoryResolver()
        self.dir_resolver.memory = self.memory

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_application_resolution(self):
        # 1. Antigravity IDE
        app = self.app_registry.resolve_application("antigravity")
        if app:
            self.assertIn("antigravity", app.name.lower())
            self.assertTrue(Path(app.exec_path).exists())

        # 2. Konsole / Terminal
        konsole = self.app_registry.resolve_application("terminal")
        self.assertIsNotNone(konsole)
        self.assertIn("konsole", konsole.exec_path.lower())

        # 3. Firefox / Browser
        browser = self.app_registry.resolve_application("browser")
        self.assertIsNotNone(browser)
        self.assertIn("firefox", browser.exec_path.lower())

        # 4. Unknown application
        unknown = self.app_registry.resolve_application("non_existent_fake_app_xyz")
        self.assertIsNone(unknown)

    def test_project_directory_resolution(self):
        # Create a mock project directory inside temp directory
        mock_project = Path(self.temp_dir.name) / "MockProject"
        mock_project.mkdir()

        # Seed memory
        self.memory.save_project("mockproject", str(mock_project))

        resolved, candidates = self.dir_resolver.resolve_project_directory("MockProject")
        self.assertEqual(resolved, str(mock_project))
        self.assertEqual(len(candidates), 1)

        # Clean project phrase variations ("my mockproject folder")
        resolved_phrase, _ = self.dir_resolver.resolve_project_directory("my MockProject folder")
        self.assertEqual(resolved_phrase, str(mock_project))

        # Real system Lensify folder if it exists on Desktop
        desktop_lensify = Path.home() / "Desktop" / "Lensify"
        if desktop_lensify.is_dir():
            real_resolved, _ = self.dir_resolver.resolve_project_directory("Lensify")
            self.assertEqual(real_resolved, str(desktop_lensify))


if __name__ == "__main__":
    unittest.main()
