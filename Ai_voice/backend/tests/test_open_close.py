import os
import sys
import unittest

# Ensure root dir is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.services.command_service import CommandService
from backend.services.system_service import SystemService

class TestOpenCloseCommands(unittest.TestCase):
    def test_01_open_terminal_unchanged(self):
        """'open terminal' gives app.open / terminal, unchanged."""
        res = CommandService.process("open terminal")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["action"]["action"], "app.open")
        self.assertEqual(res["action"]["target"], "terminal")
        self.assertEqual(res["message"], "Opened Terminal")
        self.assertIsNone(res["error"])

    def test_02_close_terminal_variations(self):
        """'close terminal', 'close the terminal', 'Please close terminal.', 'shut down terminal', 'exit terminal', 'quit terminal', and 'kill terminal' all give app.close / terminal."""
        variations = [
            "close terminal",
            "close the terminal",
            "Please close terminal.",
            "shut down terminal",
            "exit terminal",
            "quit terminal",
            "kill terminal",
            "dismiss terminal",
            "shutdown terminal",
            "shut terminal"
        ]
        for cmd in variations:
            with self.subTest(cmd=cmd):
                res = CommandService.process(cmd)
                self.assertEqual(res["status"], "completed", f"Failed for cmd: {cmd}")
                self.assertEqual(res["action"]["action"], "app.close", f"Failed for cmd: {cmd}")
                self.assertEqual(res["action"]["target"], "terminal", f"Failed for cmd: {cmd}")
                self.assertEqual(res["message"], "Closed Terminal", f"Failed for cmd: {cmd}")
                self.assertIsNone(res["error"])

    def test_03_close_aliases(self):
        """'close notepad' gives editor, 'close cmd' gives terminal, and 'close file manager' gives files."""
        res_notepad = CommandService.process("close notepad")
        self.assertEqual(res_notepad["status"], "completed")
        self.assertEqual(res_notepad["action"]["action"], "app.close")
        self.assertEqual(res_notepad["action"]["target"], "editor")
        self.assertEqual(res_notepad["message"], "Closed Text Editor")

        res_cmd = CommandService.process("close cmd")
        self.assertEqual(res_cmd["status"], "completed")
        self.assertEqual(res_cmd["action"]["action"], "app.close")
        self.assertEqual(res_cmd["action"]["target"], "terminal")
        self.assertEqual(res_cmd["message"], "Closed Terminal")

        res_files = CommandService.process("close file manager")
        self.assertEqual(res_files["status"], "completed")
        self.assertEqual(res_files["action"]["action"], "app.close")
        self.assertEqual(res_files["action"]["target"], "files")
        self.assertEqual(res_files["message"], "Closed Files")

    def test_04_unknown_app_and_bare_close(self):
        """'close banana' gives UNKNOWN_APP, and bare 'close' gives a failed result with a helpful message."""
        # 'close banana'
        res_banana = CommandService.process("close banana")
        self.assertEqual(res_banana["status"], "failed")
        self.assertEqual(res_banana["error"], "UNKNOWN_APP")
        self.assertIn("banana", res_banana["message"])
        self.assertIn("Try: terminal, files, editor, settings, workspace, nova-voice", res_banana["message"])

        # bare 'close'
        res_bare_close = CommandService.process("close")
        self.assertEqual(res_bare_close["status"], "failed")
        self.assertEqual(res_bare_close["error"], "MISSING_APP_TARGET")
        self.assertIn("Please specify which app to close", res_bare_close["message"])

        # bare 'open'
        res_bare_open = CommandService.process("open")
        self.assertEqual(res_bare_open["status"], "failed")
        self.assertEqual(res_bare_open["error"], "MISSING_APP_TARGET")
        self.assertIn("Please specify which app to open", res_bare_open["message"])

    def test_05_conflicting_verbs(self):
        """'open and close terminal' returns CONFLICTING_COMMANDS error."""
        res = CommandService.process("open and close terminal")
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["error"], "CONFLICTING_COMMANDS")

    def test_06_help_mentions_open_and_close(self):
        """'help' mentions both open and close."""
        res = CommandService.process("help")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["action"]["action"], "system.help")
        self.assertIn("open", res["message"].lower())
        self.assertIn("close", res["message"].lower())

    def test_07_speech_spoken_forms_and_nouns(self):
        """Spoken forms with filler and noun suffixes: 'close the terminal window', 'shut down the files app'."""
        res1 = CommandService.process("close the terminal window")
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(res1["action"]["action"], "app.close")
        self.assertEqual(res1["action"]["target"], "terminal")

        res2 = CommandService.process("shut down the files app")
        self.assertEqual(res2["status"], "completed")
        self.assertEqual(res2["action"]["action"], "app.close")
        self.assertEqual(res2["action"]["target"], "files")

        res3 = CommandService.process("Hey Nova, please close my editor application.")
        self.assertEqual(res3["status"], "completed")
        self.assertEqual(res3["action"]["action"], "app.close")
        self.assertEqual(res3["action"]["target"], "editor")

    def test_08_system_service_close_application(self):
        """SystemService.close_application returns app.close action."""
        act = SystemService.close_application("terminal")
        self.assertEqual(act, {"action": "app.close", "target": "terminal"})

    def test_09_all_six_apps_and_variations(self):
        """Verify close commands for all 6 apps and their natural variations."""
        expected_apps = [
            ("close terminal", "terminal"),
            ("close files", "files"),
            ("close editor", "editor"),
            ("close settings", "settings"),
            ("close workspace", "workspace"),
            ("close nova voice", "nova-voice"),
            ("close the terminal", "terminal"),
            ("please close terminal", "terminal"),
            ("close terminal window", "terminal"),
            ("close the terminal please", "terminal"),
            ("close terminal, please", "terminal"),
            ("close terminal now", "terminal"),
            ("Hey Nova, please close terminal window", "terminal"),
            ("close files window", "files"),
            ("close editor window", "editor"),
            ("close settings window", "settings"),
            ("close workspace window", "workspace"),
            ("close nova voice window", "nova-voice"),
            ("please close nova voice", "nova-voice"),
            ("please close workspace", "workspace"),
            ("close the workspace", "workspace"),
            ("close the settings", "settings"),
            ("close the editor", "editor"),
            ("close the files", "files"),
        ]
        for cmd, expected_target in expected_apps:
            with self.subTest(cmd=cmd, target=expected_target):
                res = CommandService.process(cmd)
                self.assertEqual(res["status"], "completed", f"Failed status for '{cmd}'")
                self.assertEqual(res["action"]["action"], "app.close", f"Failed action for '{cmd}'")
                self.assertEqual(res["action"]["target"], expected_target, f"Failed target for '{cmd}'")
                self.assertIsNone(res["error"], f"Error not None for '{cmd}'")

if __name__ == "__main__":
    unittest.main()

