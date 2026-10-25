"""
Unit tests for command routing and confirmation state transitions.
"""

import unittest
from core.router import route_command


class TestRouter(unittest.TestCase):

    def test_exit_command(self):
        should_continue, pending = route_command("exit jarvis")
        self.assertFalse(should_continue)
        self.assertIsNone(pending)

    def test_close_tab_confirmation_flow(self):
        # 1. User says "close the current tab" -> asks for confirmation
        should_continue, pending = route_command("close the current tab")
        self.assertTrue(should_continue)
        self.assertEqual(pending, "close_tab")

        # 2. User says "no" -> cancels action
        should_continue, pending = route_command("no", pending_action="close_tab")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)

        # 3. User says "close the current tab" again
        should_continue, pending = route_command("close the current tab")
        self.assertEqual(pending, "close_tab")

        # 4. User says "yes" -> confirms and clears pending action
        should_continue, pending = route_command("yes", pending_action="close_tab")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)


if __name__ == "__main__":
    unittest.main()
