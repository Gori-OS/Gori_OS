import unittest
import os
import sys
import urllib.parse

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.services.command_service import CommandService
from backend.services.browser_service import BrowserService

class TestMp3PlaybackAndBrowserSearch(unittest.TestCase):

    def test_01_play_song_mp3_triggers_media_play(self):
        """When user says 'play song.mp3', it must return media.play with autoplay: True."""
        res = CommandService.process("play song.mp3")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["target_device"], "computer")
        self.assertEqual(res["action"]["action"], "media.play")
        self.assertEqual(res["action"]["target"], "preview")
        self.assertEqual(res["action"]["filename"], "song.mp3")
        self.assertTrue(res["action"]["autoplay"])
        self.assertIn("song.mp3", res["action"]["url"])

    def test_02_play_song_mp3_spoken_without_dot(self):
        """Speech without dot 'play song mp3' must normalize and play song.mp3."""
        res = CommandService.process("play song mp3")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["action"]["action"], "media.play")
        self.assertEqual(res["action"]["filename"], "song.mp3")

    def test_03_play_song_prioritizes_audio(self):
        """'play song' must prioritize audio file song.mp3 over video song.mp4."""
        res = CommandService.process("play song")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["action"]["action"], "media.play")
        self.assertTrue(res["action"]["filename"].endswith((".mp3", ".wav", ".m4a")))

    def test_04_pause_and_resume_controls(self):
        """'pause song' and 'resume' control audio playback state."""
        pause_res = CommandService.process("pause song")
        self.assertEqual(pause_res["status"], "completed")
        self.assertEqual(pause_res["action"]["action"], "media.pause")

        resume_res = CommandService.process("resume")
        self.assertEqual(resume_res["status"], "completed")
        self.assertEqual(resume_res["action"]["action"], "media.resume")

    def test_05_search_capital_of_india(self):
        """'search capital of India' opens browser with Google results page."""
        res = CommandService.process("search capital of India")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["action"]["action"], "app.open")
        self.assertEqual(res["action"]["target"], "browser")
        self.assertTrue(res["action"].get("is_search"))
        self.assertIn("/api/browser/search", res["action"]["url"])
        self.assertIn("capital%20of%20india", res["action"]["url"].lower())
        self.assertIn("google.com/search?q=", res["action"]["display_url"].lower())

    def test_06_browser_service_search_capital_of_india(self):
        """BrowserService returns instant knowledge card for Capital of India (New Delhi)."""
        data = BrowserService.perform_search("capital of India")
        self.assertIsNotNone(data.get("direct_answer"))
        self.assertEqual(data["direct_answer"]["heading"], "New Delhi")
        self.assertIn("Capital of India", data["direct_answer"]["subheading"])

        html = BrowserService.render_google_results_page("capital of India", data)
        self.assertIn("New Delhi", html)
        self.assertIn("Google Search", html)

    def test_07_open_web_url_and_google(self):
        """'open https://github.com' and 'open google' route cleanly to browser."""
        res_url = CommandService.process("open https://github.com")
        self.assertEqual(res_url["status"], "completed")
        self.assertEqual(res_url["action"]["action"], "app.open")
        self.assertEqual(res_url["action"]["target"], "browser")
        self.assertEqual(res_url["action"]["url"], "https://github.com")

        res_google = CommandService.process("open google")
        self.assertEqual(res_google["status"], "completed")
        self.assertEqual(res_google["action"]["action"], "app.open")
        self.assertEqual(res_google["action"]["target"], "browser")
        self.assertIn("google.com", res_google["action"]["display_url"])

if __name__ == "__main__":
    unittest.main()
