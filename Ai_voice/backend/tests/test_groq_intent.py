import os
import sys
import json
import time
import threading
import unittest
from unittest.mock import patch, MagicMock
import httpx
import uvicorn

# Ensure project root is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.mock_backend_8000 import app as mock_backend_app
from backend.services.command_service import CommandService
from backend.services.groq_service import groq_service, GroqService
from backend.services.file_processing_service import (
    file_processing_service,
    normalize_spoken_filename_patterns,
    ALLOWED_REGISTRY_ENDPOINTS,
    OUTPUT_DIR,
    MOBILE_DIR
)


class MockServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        config = uvicorn.Config(mock_backend_app, host="127.0.0.1", port=8000, log_level="error")
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


class TestGroqIntentUnderstanding(unittest.TestCase):
    server_thread = None

    @classmethod
    def setUpClass(cls):
        os.makedirs(MOBILE_DIR, exist_ok=True)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        cls.test_files = {
            "Intern21.pdf": b"%PDF-1.4\ninternship document",
            "test.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtestpng",
            "image.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRimagepng",
            "image.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01imagejpg",
            "my photo.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01photojpg",
            "report final.pdf": b"%PDF-1.4\nreport final doc",
            "file.pdf": b"%PDF-1.4\ntest pdf content",
            "video.mp4": b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00mp42isom",
            "song.mp4": b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00songmp4",
            "audio.m4a": b"\x00\x00\x00 ftypm4a \x00\x00\x00\x00m4a audio",
            "data.csv": b"id,name,value\n1,alpha,100\n"
        }
        for name, content in cls.test_files.items():
            fpath = os.path.join(MOBILE_DIR, name)
            if not os.path.exists(fpath):
                with open(fpath, "wb") as f:
                    f.write(content)

        # Check if mock backend is already running on port 8000
        try:
            resp = httpx.get("http://127.0.0.1:8000/health", timeout=0.5)
            if resp.status_code == 200:
                cls.server_thread = None
                os.environ["UTILITY_BACKEND_URL"] = "http://127.0.0.1:8000"
                return
        except Exception:
            pass

        # Start mock backend on 8000
        cls.server_thread = MockServerThread()
        cls.server_thread.start()

        healthy = False
        for _ in range(30):
            try:
                resp = httpx.get("http://127.0.0.1:8000/health", timeout=1.0)
                if resp.status_code == 200:
                    healthy = True
                    break
            except Exception:
                time.sleep(0.1)

        if not healthy:
            raise RuntimeError("Failed to connect to mock backend on http://127.0.0.1:8000")

        os.environ["UTILITY_BACKEND_URL"] = "http://127.0.0.1:8000"

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("UTILITY_BACKEND_URL", None)
        if cls.server_thread:
            cls.server_thread.stop()
            time.sleep(0.2)

    def test_01_groq_never_called_for_open_and_close_commands(self):
        """
        CRITICAL REQUIREMENT: Groq must ONLY handle task/endpoint commands.
        Do NOT use Groq for open or close commands.
        """
        open_close_commands = [
            "open terminal",
            "close terminal",
            "open files",
            "close files",
            "open editor",
            "close editor",
            "open settings",
            "close settings",
            "open workspace",
            "close workspace",
            "open nova voice",
            "close nova voice",
            "close the terminal",
            "please close terminal",
            "close terminal window",
            "take screenshot",
            "status",
            "help"
        ]

        with patch.object(groq_service, "call_groq_intent_parser") as mock_groq_call:
            for cmd in open_close_commands:
                with self.subTest(cmd=cmd):
                    res = CommandService.process(cmd)
                    self.assertEqual(res["status"], "completed", f"Failed for {cmd}")
                    # Groq must NEVER be called
                    self.assertFalse(mock_groq_call.called, f"Groq was unexpectedly called for: '{cmd}'")

    def test_02_spoken_filename_pattern_normalization(self):
        """
        Test normalization of spoken filename patterns:
        - 'dot', 'point', 'period' -> '.'
        - Spelled out: P N G -> png, P D F -> pdf, J P G -> jpg, J P E G -> jpeg,
          W E B P -> webp, M P 4 -> mp4, M P 3 -> mp3, W A V -> wav, C S V -> csv,
          J S O N -> json, X L S X -> xlsx
        - Do not treat 'dot' as part of the filename
        - Support filenames containing spaces, numbers, underscores, hyphens, and multiple dots
        """
        cases = [
            ("image dot png", "image.png"),
            ("image dot jpg", "image.jpg"),
            ("intern21 dot pdf", "intern21.pdf"),
            ("photo dot J P G", "photo.jpg"),
            ("test dot p n g", "test.png"),
            ("my document dot pdf", "my document.pdf"),
            ("report final dot pdf", "report final.pdf"),
            ("my photo point jpg", "my photo.jpg"),
            ("data period csv", "data.csv"),
            ("test dot P N G", "test.png"),
            ("track dot M P 3", "track.mp3"),
            ("clip dot M P 4", "clip.mp4"),
            ("audio dot W A V", "audio.wav"),
            ("archive.tar dot gz", "archive.tar.gz"),
            ("file_v2-final dot J P E G", "file_v2-final.jpeg"),
            ("spreadsheet dot X L S X", "spreadsheet.xlsx"),
            ("config dot J S O N", "config.json"),
            ("photo dot W E B P", "photo.webp"),
        ]
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                result = normalize_spoken_filename_patterns(spoken)
                self.assertEqual(result, expected)

    def test_03_authoritative_filename_resolution(self):
        """
        Filename matching must be case-insensitive and match against actual files
        available in the web app. The actual filename on disk is authoritative.
        """
        # Spoken "intern21 dot pdf" must resolve to actual "Intern21.pdf" (capital I)
        finfo = file_processing_service.find_file("intern21 dot pdf")
        self.assertIsNotNone(finfo)
        self.assertEqual(finfo["filename"], "Intern21.pdf")

        # Spoken "image dot png" -> "image.png"
        finfo = file_processing_service.find_file("image dot png")
        self.assertIsNotNone(finfo)
        self.assertEqual(finfo["filename"], "image.png")

        # Spoken "my photo dot jpg" -> "my photo.jpg"
        finfo = file_processing_service.find_file("my photo dot jpg")
        self.assertIsNotNone(finfo)
        self.assertEqual(finfo["filename"], "my photo.jpg")

        # Spoken "report final dot pdf" -> "report final.pdf"
        finfo = file_processing_service.find_file("report final dot pdf")
        self.assertIsNotNone(finfo)
        self.assertEqual(finfo["filename"], "report final.pdf")

        # Spoken "test dot P N G" -> "test.png"
        finfo = file_processing_service.find_file("test dot P N G")
        self.assertIsNotNone(finfo)
        self.assertEqual(finfo["filename"], "test.png")

    def test_04_groq_structured_json_schema(self):
        """
        Groq must return structured JSON:
        {
          "intent": "...",
          "endpoint": "...",
          "input_files": [],
          "parameters": {}
        }
        The endpoint MUST exactly match one endpoint from the registry.
        """
        if not groq_service.is_available():
            self.skipTest("GROQ_API_KEY is not configured in .env")

        available_files = file_processing_service.list_available_files()
        res = groq_service.call_groq_intent_parser("convert intern21 dot pdf to png", available_files)

        if res is None:
            self.skipTest("Groq rate limited or temporarily unavailable")

        self.assertIn("intent", res)
        self.assertIn("endpoint", res)
        self.assertIn("input_files", res)
        self.assertIn("parameters", res)

        # The endpoint MUST exactly match one endpoint from the registry
        self.assertIn(res["endpoint"], ALLOWED_REGISTRY_ENDPOINTS)
        self.assertEqual(res["endpoint"], "/pdf-to-png")

    def test_05_all_prompt_examples_match_registry_endpoints(self):
        """
        Verifies task resolution and registry endpoints for all prompt examples:
        - 'convert intern21.pdf to png' -> '/pdf-to-png'
        - 'convert intern21 dot pdf to png' -> '/pdf-to-png'
        - 'convert test.png to jpg' -> '/png-to-jpg'
        - 'turn image.jpg into pdf' -> '/jpg-to-pdf'
        - 'convert video.mp4 to gif' -> '/video-to-gif'
        - 'convert song.mp4 to mp3' -> '/mp4-to-mp3'
        - 'convert data.csv to excel' -> '/csv-to-excel'
        - 'compress this video' -> '/compress-video'
        - 'split this pdf' -> '/split-pdf'
        - 'convert my photo dot jpg to webp' -> '/jpg-to-webp'
        - 'convert report final dot pdf to jpg' -> '/pdf-to-jpg'
        - 'convert test dot P N G to J P G' -> '/png-to-jpg'
        """
        test_cases = [
            ("convert intern21.pdf to png", "/pdf-to-png", ["Intern21.pdf"]),
            ("convert intern21 dot pdf to png", "/pdf-to-png", ["Intern21.pdf"]),
            ("convert test.png to jpg", "/png-to-jpg", ["test.png"]),
            ("turn image.jpg into pdf", "/jpg-to-pdf", ["image.jpg"]),
            ("convert video.mp4 to gif", "/video-to-gif", ["video.mp4"]),
            ("convert song.mp4 to mp3", "/mp4-to-mp3", ["song.mp4"]),
            ("convert data.csv to excel", "/csv-to-excel", ["data.csv"]),
            ("compress this video", "/compress-video", ["video.mp4"]),
            ("split this pdf", "/split-pdf", ["Intern21.pdf", "file.pdf", "report final.pdf"]),
            ("convert my photo dot jpg to webp", "/jpg-to-webp", ["my photo.jpg"]),
            ("convert report final dot pdf to jpg", "/pdf-to-jpg", ["report final.pdf"]),
            ("convert test dot P N G to J P G", "/png-to-jpg", ["test.png"]),
        ]

        for cmd, expected_endpoint, allowed_files in test_cases:
            with self.subTest(cmd=cmd):
                res = CommandService.process(cmd)
                self.assertEqual(res["status"], "completed", f"Failed for '{cmd}': {res}")
                action = res.get("action", {})
                self.assertEqual(action.get("action"), "file.processed")
                self.assertEqual(action.get("endpoint"), expected_endpoint)
                self.assertIn(action.get("source_file"), allowed_files)
                self.assertIn(expected_endpoint, ALLOWED_REGISTRY_ENDPOINTS)

    def test_06_missing_file_error_handling(self):
        """
        If the filename cannot be matched to an existing web-app file,
        ask/show a clear 'File not found' error and do not call the backend.
        """
        original_post = httpx.Client.post
        backend_calls = []

        def spy_post(client_self, url, *args, **kwargs):
            if "goori-os-backend-endpoints.onrender.com" in str(url):
                backend_calls.append(url)
            return original_post(client_self, url, *args, **kwargs)

        with patch.object(httpx.Client, "post", new=spy_post):
            res = CommandService.process("convert ghost_file_999.png to jpg")
            self.assertEqual(res["status"], "failed")
            self.assertEqual(res["error"], "FILE_NOT_FOUND")
            self.assertIn("File not found", res["message"])
            self.assertIn("ghost_file_999.png", res["message"])
            # Backend MUST NOT be called
            self.assertEqual(len(backend_calls), 0)

    def test_07_no_matching_endpoint_error_handling(self):
        """
        If no matching endpoint exists, show a clear 'No supported endpoint is available for this task.'
        error and do not make the request. Never invent an endpoint.
        """
        original_post = httpx.Client.post
        backend_calls = []

        def spy_post(client_self, url, *args, **kwargs):
            if "goori-os-backend-endpoints.onrender.com" in str(url):
                backend_calls.append(url)
            return original_post(client_self, url, *args, **kwargs)

        # Task outside registry: converting CSV to FLAC
        mock_groq_resp = {
            "intent": "convert",
            "endpoint": "/wav-to-flac",  # Not in 38-endpoint registry
            "input_files": ["data.csv"],
            "parameters": {}
        }
        with patch.object(httpx.Client, "post", new=spy_post):
            with patch.object(groq_service, "call_groq_intent_parser", return_value=mock_groq_resp):
                res = CommandService.process("convert data.csv to flac")
                self.assertEqual(res["status"], "failed")
                self.assertEqual(res["error"], "NO_MATCHING_ENDPOINT")
                self.assertEqual(res["message"], "No supported endpoint is available for this task.")
                # Backend MUST NOT be called
                self.assertEqual(len(backend_calls), 0)

    def test_08_incompatible_endpoint_rejected_strictly(self):
        """
        CRITICAL REQUIREMENT:
        Do NOT select an endpoint only because its name is textually similar.
        For example: 'convert image.png to mp3' MUST NOT select:
        /mp4-to-mp3, /mp3-to-wav or any other incompatible endpoint.
        Must return 'No supported endpoint is available for this task.' and NOT call backend.
        """
        original_post = httpx.Client.post
        backend_calls = []

        def spy_post(client_self, url, *args, **kwargs):
            if "goori-os-backend-endpoints.onrender.com" in str(url):
                backend_calls.append(url)
            return original_post(client_self, url, *args, **kwargs)

        # Case A: Even if Groq returns /mp4-to-mp3 due to similarity with "mp3"
        mock_groq_hallucination = {
            "intent": "convert",
            "endpoint": "/mp4-to-mp3",
            "input_files": ["image.png"],
            "parameters": {}
        }
        with patch.object(httpx.Client, "post", new=spy_post):
            with patch.object(groq_service, "call_groq_intent_parser", return_value=mock_groq_hallucination):
                res = CommandService.process("convert image.png to mp3")
                self.assertEqual(res["status"], "failed")
                self.assertEqual(res["error"], "NO_MATCHING_ENDPOINT")
                self.assertEqual(res["message"], "No supported endpoint is available for this task.")
                self.assertEqual(len(backend_calls), 0)

        # Case B: Even if Groq returns /mp3-to-wav
        mock_groq_hallucination_wav = {
            "intent": "convert",
            "endpoint": "/mp3-to-wav",
            "input_files": ["image.png"],
            "parameters": {}
        }
        with patch.object(httpx.Client, "post", new=spy_post):
            with patch.object(groq_service, "call_groq_intent_parser", return_value=mock_groq_hallucination_wav):
                res = CommandService.process("convert image.png to mp3")
                self.assertEqual(res["status"], "failed")
                self.assertEqual(res["error"], "NO_MATCHING_ENDPOINT")
                self.assertEqual(res["message"], "No supported endpoint is available for this task.")
                self.assertEqual(len(backend_calls), 0)

    def test_09_unsupported_groq_intent_response(self):
        """
        If no endpoint supports the requested input/output combination, return:
        {
          "intent": "unsupported",
          "endpoint": null,
          "input_files": [],
          "parameters": {}
        }
        and show: 'No supported endpoint is available for this task.'
        """
        unsupported_resp = {
            "intent": "unsupported",
            "endpoint": None,
            "input_files": [],
            "parameters": {}
        }
        with patch.object(groq_service, "call_groq_intent_parser", return_value=unsupported_resp):
            res = CommandService.process("convert image.png to mp3")
            self.assertEqual(res["status"], "failed")
            self.assertEqual(res["error"], "NO_MATCHING_ENDPOINT")
            self.assertEqual(res["message"], "No supported endpoint is available for this task.")

    def test_10_m4a_spoken_normalization_and_conversion(self):
        """
        Normalize spoken 'M 4 A' / 'm 4 a' -> 'm4a' and execute /m4a-to-mp3 endpoint.
        """
        cmd = "convert audio dot M 4 A to mp3"
        res = CommandService.process(cmd)
        self.assertEqual(res["status"], "completed", f"Failed for {cmd}: {res}")
        self.assertEqual(res["action"]["endpoint"], "/m4a-to-mp3")
        self.assertEqual(res["action"]["source_file"], "audio.m4a")

    def test_11_independent_voice_command_processing(self):
        """
        Do not reuse a filename from a previous command.
        Do not reuse an endpoint from a previous command.
        Each voice command must be processed independently.
        """
        # Command 1: PNG to JPG
        res1 = CommandService.process("convert image.png to jpg")
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(res1["action"]["endpoint"], "/png-to-jpg")
        self.assertEqual(res1["action"]["source_file"], "image.png")

        # Command 2: MP4 to MP3 (MUST NOT reuse image.png or /png-to-jpg)
        res2 = CommandService.process("convert song.mp4 to mp3")
        self.assertEqual(res2["status"], "completed")
        self.assertEqual(res2["action"]["endpoint"], "/mp4-to-mp3")
        self.assertEqual(res2["action"]["source_file"], "song.mp4")

        # Command 3: CSV to Excel (MUST NOT reuse song.mp4 or /mp4-to-mp3)
        res3 = CommandService.process("convert data.csv to excel")
        self.assertEqual(res3["status"], "completed")
        self.assertEqual(res3["action"]["endpoint"], "/csv-to-excel")
        self.assertEqual(res3["action"]["source_file"], "data.csv")


if __name__ == "__main__":
    unittest.main()
