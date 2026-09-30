import os
import sys
import time
import threading
import unittest
import httpx
import uvicorn

# Ensure project root is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.mock_backend_8000 import app as mock_backend_app
from backend.services.command_service import CommandService
from backend.services.file_processing_service import OUTPUT_DIR, MOBILE_DIR, ALLOWED_REGISTRY_ENDPOINTS


class MockServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        config = uvicorn.Config(mock_backend_app, host="127.0.0.1", port=8000, log_level="error")
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


class TestLiveBackendEndToEnd(unittest.TestCase):
    server_thread = None

    @classmethod
    def setUpClass(cls):
        # Ensure test directory and files exist
        os.makedirs(MOBILE_DIR, exist_ok=True)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        test_files = {
            "Intern21.pdf": b"%PDF-1.4\ninternship document",
            "test.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtestpng",
            "image.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRimagepng",
            "image.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01imagejpg",
            "my photo.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01photojpg",
            "report final.pdf": b"%PDF-1.4\nreport final doc",
            "file.pdf": b"%PDF-1.4\ntest pdf content",
            "video.mp4": b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00mp42isom",
            "song.mp4": b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00songmp4",
            "data.csv": b"id,name,value\n1,alpha,100\n",
            "data.json": b'[{"id": 1, "name": "alpha", "value": 100}]',
            "sample.gif": b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        }
        for name, content in test_files.items():
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

        # Start server in thread
        cls.server_thread = MockServerThread()
        cls.server_thread.start()

        # Wait for server to become healthy
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

    def test_live_all_requested_voice_commands(self):
        """
        Tests the complete end-to-end voice-controlled processing flow against
        the live backend on http://127.0.0.1:8000 for all specified commands:
        1. "convert test.png to jpg"
        2. "convert test.png to jpeg"
        3. "convert file.pdf to jpg"
        4. "compress image.png"
        5. "convert video.mp4 to gif"
        6. "convert intern21 dot pdf to png"
        7. "convert song.mp4 to mp3"
        8. "convert data.csv to excel"
        9. "compress this video"
        10. "convert my photo dot jpg to webp"
        11. "convert report final dot pdf to jpg"
        12. "convert test dot P N G to J P G"
        """
        test_cases = [
            {
                "command": "convert test.png to jpg",
                "expected_output_files": ["test.jpg"],
                "expected_endpoint": "/png-to-jpg"
            },
            {
                "command": "convert test.png to jpeg",
                "expected_output_files": ["test.jpg", "test.jpeg"],
                "expected_endpoint": "/png-to-jpg"
            },
            {
                "command": "convert file.pdf to jpg",
                "expected_output_files": ["file.jpg"],
                "expected_endpoint": "/pdf-to-jpg"
            },
            {
                "command": "compress image.png",
                "expected_output_files": ["image_compressed.png"],
                "expected_endpoint": "/compress-image"
            },
            {
                "command": "convert video.mp4 to gif",
                "expected_output_files": ["video.gif"],
                "expected_endpoint": "/video-to-gif"
            },
            {
                "command": "convert intern21 dot pdf to png",
                "expected_output_files": ["Intern21.png", "intern21.png"],
                "expected_endpoint": "/pdf-to-png"
            },
            {
                "command": "convert song.mp4 to mp3",
                "expected_output_files": ["song.mp3"],
                "expected_endpoint": "/mp4-to-mp3"
            },
            {
                "command": "convert data.csv to excel",
                "expected_output_files": ["data.xlsx"],
                "expected_endpoint": "/csv-to-excel"
            },
            {
                "command": "compress this video",
                "expected_output_files": ["video_compressed.mp4", "song_compressed.mp4"],
                "expected_endpoint": "/compress-video"
            },
            {
                "command": "convert my photo dot jpg to webp",
                "expected_output_files": ["my photo.webp"],
                "expected_endpoint": "/jpg-to-webp"
            },
            {
                "command": "convert report final dot pdf to jpg",
                "expected_output_files": ["report final.jpg"],
                "expected_endpoint": "/pdf-to-jpg"
            },
            {
                "command": "convert test dot P N G to J P G",
                "expected_output_files": ["test.jpg"],
                "expected_endpoint": "/png-to-jpg"
            },
            {
                "command": "convert song dot mp4 to mp3",
                "expected_output_files": ["song.mp3"],
                "expected_endpoint": "/mp4-to-mp3"
            },
            {
                "command": "convert image dot png to jpg",
                "expected_output_files": ["image.jpg"],
                "expected_endpoint": "/png-to-jpg"
            },
            {
                "command": "convert image.jpg to webp",
                "expected_output_files": ["image.webp"],
                "expected_endpoint": "/jpg-to-webp"
            },
            {
                "command": "convert data.json to csv",
                "expected_output_files": ["data.csv"],
                "expected_endpoint": "/json-to-csv"
            },
            {
                "command": "convert gif to mp4",
                "expected_output_files": ["sample.mp4"],
                "expected_endpoint": "/gif-to-mp4"
            }
        ]

        for tc in test_cases:
            cmd = tc["command"]
            with self.subTest(command=cmd):
                # Clean any previous output files
                for f in tc["expected_output_files"]:
                    p = os.path.join(OUTPUT_DIR, f)
                    if os.path.exists(p):
                        os.remove(p)

                res = CommandService.process(cmd)

                # 1. Verify status & action
                self.assertEqual(res["status"], "completed", f"Status not completed for '{cmd}': {res}")
                action = res.get("action", {})
                self.assertEqual(action.get("action"), "file.processed")
                self.assertEqual(action.get("target"), "output")
                self.assertEqual(action.get("endpoint"), tc["expected_endpoint"])
                self.assertIn(action.get("output_file"), tc["expected_output_files"])
                self.assertIn(tc["expected_endpoint"], ALLOWED_REGISTRY_ENDPOINTS)

                # 2. Verify file saved in Output directory with preserved filename and extension
                output_path = os.path.join(OUTPUT_DIR, action.get("output_file"))
                self.assertTrue(os.path.exists(output_path), f"Output file not found at {output_path}")
                self.assertGreater(os.path.getsize(output_path), 0, f"Output file is empty: {output_path}")

    def test_live_merge_multi_file_endpoint(self):
        """
        Verify multi-file merge endpoint works against live backend.
        """
        out_merged = os.path.join(OUTPUT_DIR, "merged.pdf")
        if os.path.exists(out_merged):
            os.remove(out_merged)

        res = CommandService.process("merge file.pdf and Intern21.pdf to pdf")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["action"]["output_file"], "merged.pdf")
        self.assertEqual(res["action"]["endpoint"], "/merge-pdfs")
        self.assertTrue(os.path.exists(out_merged))
        self.assertGreater(os.path.getsize(out_merged), 0)


if __name__ == "__main__":
    unittest.main()
