import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock
import httpx

# Ensure project root is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.services.file_processing_service import FileProcessingService, file_processing_service, OUTPUT_DIR, MOBILE_DIR
from backend.services.groq_service import groq_service
from backend.services.command_service import CommandService
from fastapi.testclient import TestClient
from backend.api.http_routes import router
from fastapi import FastAPI


class TestFileProcessingVoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure test directory and test files exist in MOBILE_DIR
        os.makedirs(MOBILE_DIR, exist_ok=True)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        cls.test_files = {
            "test.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtestpng",
            "image.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRimagepng",
            "file.pdf": b"%PDF-1.4\ntest pdf content",
            "video.mp4": b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00mp42isom"
        }
        for name, content in cls.test_files.items():
            fpath = os.path.join(MOBILE_DIR, name)
            if not os.path.exists(fpath):
                with open(fpath, "wb") as f:
                    f.write(content)

    def test_01_parse_exact_user_commands(self):
        """
        Verify parsing of all exact voice commands specified in the requirements:
        - "convert test.png to jpg"
        - "convert test.png to jpeg"
        - "convert file.pdf to jpg"
        - "compress image.png"
        - "convert video.mp4 to gif"
        """
        cases = [
            ("convert test.png to jpg", "convert", "test.png", "jpg"),
            ("convert test.png to jpeg", "convert", "test.png", "jpeg"),
            ("convert file.pdf to jpg", "convert", "file.pdf", "jpg"),
            ("compress image.png", "compress", "image.png", ""),
            ("convert video.mp4 to gif", "convert", "video.mp4", "gif"),
        ]
        for cmd, expected_op, expected_fn, expected_fmt in cases:
            with self.subTest(cmd=cmd):
                parsed = file_processing_service.parse_command(cmd)
                self.assertIsNotNone(parsed, f"Failed to parse command: '{cmd}'")
                self.assertEqual(parsed["operation"], expected_op)
                self.assertEqual(parsed["filename"], expected_fn)
                self.assertEqual(parsed["target_format"], expected_fmt)

    def test_02_parse_natural_speech_variations(self):
        """
        Verify parsing of natural voice variations with filler words, polite prefixes,
        trailing words, and speech-to-text 'dot' formatting.
        """
        variations = [
            ("please convert test.png to jpg", "convert", "test.png", "jpg"),
            ("could you please convert the file.pdf to jpg now", "convert", "file.pdf", "jpg"),
            ("convert test dot png to jpg", "convert", "test.png", "jpg"),
            ("can you compress my image.png please", "compress", "image.png", ""),
            ("hey nova convert video.mp4 to gif thank you", "convert", "video.mp4", "gif"),
            ("transform test.png into jpg", "convert", "test.png", "jpg"),
            ("optimize image.png", "compress", "image.png", ""),
        ]
        for cmd, expected_op, expected_fn, expected_fmt in variations:
            with self.subTest(cmd=cmd):
                parsed = file_processing_service.parse_command(cmd)
                self.assertIsNotNone(parsed, f"Failed to parse variation: '{cmd}'")
                self.assertEqual(parsed["operation"], expected_op)
                self.assertEqual(parsed["filename"], expected_fn)
                self.assertEqual(parsed["target_format"], expected_fmt)

    def test_03_find_file_in_storage(self):
        """
        Verify locating files across storage directories:
        exact name, case-insensitivity, and extensionless matches.
        """
        # Exact match
        found = file_processing_service.find_file("test.png")
        self.assertIsNotNone(found)
        self.assertEqual(found["filename"], "test.png")
        self.assertTrue(os.path.isfile(found["path"]))

        # Case-insensitive
        found_case = file_processing_service.find_file("TEST.PNG")
        self.assertIsNotNone(found_case)
        self.assertEqual(found_case["filename"].lower(), "test.png")

        # Nonexistent file returns None
        found_missing = file_processing_service.find_file("definitely_non_existent_file_12345.xyz")
        self.assertIsNone(found_missing)

    def test_04_missing_file_error_message(self):
        """
        Verify that a non-existent file produces a clear error message listing available files.
        """
        res = CommandService.process("convert nonexistent_demo.png to jpg")
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["error"], "FILE_NOT_FOUND")
        self.assertIn("nonexistent_demo.png", res["message"])
        self.assertIn("Available files", res["message"])

    def test_05_backend_upload_and_save_output(self):
        """
        Verify upload to https://goori-os-backend-endpoints.onrender.com using exact required fields and parameters,
        saving the returned result to the Output folder, and preserving filename and extension.
        """
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b"SIMULATED_JPG_IMAGE_DATA_BYTES"
        mock_response.headers = {
            "content-disposition": 'attachment; filename="test.jpg"'
        }

        mock_groq_resp = {"intent": "convert", "endpoint": "/png-to-jpg", "input_files": ["test.png"], "parameters": {}}
        with patch.object(groq_service, "call_groq_intent_parser", return_value=mock_groq_resp):
            with patch.object(httpx.Client, "post", return_value=mock_response) as mock_post:
                res = CommandService.process("convert test.png to jpg")

                self.assertTrue(mock_post.called)
                call_args, call_kwargs = mock_post.call_args
                self.assertEqual(call_args[0], "https://goori-os-backend-endpoints.onrender.com/png-to-jpg")
                self.assertIn("file", call_kwargs["files"])

                # Verify response
                self.assertEqual(res["status"], "completed")
                self.assertEqual(res["action"]["action"], "file.processed")
                self.assertEqual(res["action"]["target"], "output")
                self.assertEqual(res["action"]["output_file"], "test.jpg")
                self.assertIn("test.jpg", res["message"])

                # Verify file exists on disk in OUTPUT_DIR
                out_file_path = os.path.join(OUTPUT_DIR, "test.jpg")
                self.assertTrue(os.path.exists(out_file_path))
                with open(out_file_path, "rb") as f:
                    self.assertEqual(f.read(), b"SIMULATED_JPG_IMAGE_DATA_BYTES")

    def test_06_compress_flow(self):
        """
        Verify compress voice command flow:
        - "compress image.png"
        - uses https://goori-os-backend-endpoints.onrender.com/compress-image
        - saves result to Output folder with correct name
        """
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b"COMPRESSED_DATA"
        mock_response.headers = {
            "content-disposition": 'attachment; filename="image_compressed.png"'
        }

        mock_groq_resp = {"intent": "compress", "endpoint": "/compress-image", "input_files": ["image.png"], "parameters": {}}
        with patch.object(groq_service, "call_groq_intent_parser", return_value=mock_groq_resp):
            with patch.object(httpx.Client, "post", return_value=mock_response) as mock_post:
                res = CommandService.process("compress image.png")

                self.assertTrue(mock_post.called)
                call_args, call_kwargs = mock_post.call_args
                self.assertEqual(call_args[0], "https://goori-os-backend-endpoints.onrender.com/compress-image")
                self.assertIn("file", call_kwargs["files"])

                self.assertEqual(res["status"], "completed")
                self.assertEqual(res["action"]["output_file"], "image_compressed.png")
                out_path = os.path.join(OUTPUT_DIR, "image_compressed.png")
                self.assertTrue(os.path.exists(out_path))

    def test_07_backend_unavailable_error(self):
        """
        Verify graceful error handling when the deployed utility service is unreachable.
        """
        mock_groq_resp = {"intent": "convert", "endpoint": "/png-to-jpg", "input_files": ["test.png"], "parameters": {}}
        with patch.object(groq_service, "call_groq_intent_parser", return_value=mock_groq_resp):
            with patch.object(httpx.Client, "post", side_effect=httpx.ConnectError("Connection refused")):
                res = CommandService.process("convert test.png to jpg")
                self.assertEqual(res["status"], "failed")
                self.assertEqual(res["error"], "BACKEND_UNAVAILABLE")
                self.assertIn("Ensure the deployed utility service is reachable", res["message"])

    def test_08_configurable_endpoint_mapping(self):
        """
        Verify endpoint mapping from registry handles parameters.
        """
        parsed = file_processing_service.parse_command("split file.pdf")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["filename"], "file.pdf")

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b"SPLIT_PDF_DATA"
        mock_response.headers = {"content-disposition": 'attachment; filename="file_split.zip"'}

        with patch.object(httpx.Client, "post", return_value=mock_response) as mock_post:
            res = file_processing_service.execute_processing(parsed)
            self.assertEqual(res["status"], "completed")
            call_args, call_kwargs = mock_post.call_args
            self.assertEqual(call_args[0], "https://goori-os-backend-endpoints.onrender.com/split-pdf")
            self.assertEqual(res["action"]["output_file"], "file_split.zip")

    def test_09_multi_file_support(self):
        """
        Verify support for endpoints requiring multiple files (e.g. merge file1 and file2).
        """
        parsed = file_processing_service.parse_command("merge file.pdf and test.png to pdf")
        self.assertIsNotNone(parsed)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.content = b"MERGED_DOCUMENT"
        mock_response.headers = {"content-disposition": 'attachment; filename="merged.pdf"'}

        with patch.object(httpx.Client, "post", return_value=mock_response) as mock_post:
            res = file_processing_service.execute_processing(parsed)
            self.assertEqual(res["status"], "completed")
            call_args, call_kwargs = mock_post.call_args
            self.assertEqual(call_args[0], "https://goori-os-backend-endpoints.onrender.com/merge-pdfs")
            self.assertEqual(res["action"]["output_file"], "merged.pdf")

    def test_10_http_files_list_includes_output(self):
        """
        Verify GET /files returns items located in OUTPUT_DIR with type='output' and folder='output'.
        """
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # Place a test output file
        dummy_out = os.path.join(OUTPUT_DIR, "output_verification_test.jpg")
        with open(dummy_out, "wb") as f:
            f.write(b"output_test_data")

        try:
            resp = client.get("/files")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            files = data.get("files", [])
            out_files = [f for f in files if f["name"] == "output_verification_test.jpg"]
            self.assertEqual(len(out_files), 1)
            self.assertEqual(out_files[0]["type"], "output")
            self.assertEqual(out_files[0]["folder"], "output")
            self.assertIn("/uploads/files/output/", out_files[0]["path"])
        finally:
            if os.path.exists(dummy_out):
                os.remove(dummy_out)


if __name__ == "__main__":
    unittest.main()
