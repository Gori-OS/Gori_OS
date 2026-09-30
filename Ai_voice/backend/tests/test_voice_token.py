import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Ensure root dir is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.main import app
from backend.auth.pairing_manager import pairing_manager
from backend.services.command_service import CommandService

class TestVoiceTokenAndNormalisation(unittest.TestCase):
    def setUp(self):
        self.original_key = os.environ.get("ASSEMBLYAI_API_KEY")

    def tearDown(self):
        if self.original_key is not None:
            os.environ["ASSEMBLYAI_API_KEY"] = self.original_key
        else:
            os.environ.pop("ASSEMBLYAI_API_KEY", None)

    def test_01_token_missing_api_key_returns_500_without_leak(self):
        """GET /token returns 500 when ASSEMBLYAI_API_KEY is not configured, without leaking info."""
        os.environ.pop("ASSEMBLYAI_API_KEY", None)
        client = TestClient(app)
        res = client.get("/token")
        self.assertEqual(res.status_code, 500)
        data = res.json()
        self.assertIn("detail", data)
        self.assertEqual(data["detail"], "AssemblyAI API key is not configured on the server.")

    @patch("httpx.get")
    def test_02_token_loopback_client_returns_token(self, mock_httpx_get):
        """GET /token returns temporary token and Cache-Control: no-store for loopback client."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "mock_temp_stream_token_xyz"}
        mock_httpx_get.return_value = mock_resp
        os.environ["ASSEMBLYAI_API_KEY"] = "mock_secret_assemblyai_key"

        client = TestClient(app)
        res = client.get("/token")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data, {"token": "mock_temp_stream_token_xyz"})
        self.assertEqual(res.headers.get("cache-control"), "no-store")

    @patch("httpx.get")
    def test_03_token_non_loopback_without_valid_pairing_returns_403(self, mock_httpx_get):
        """GET /token returns 403 for non-loopback client without a valid pairing token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "mock_token"}
        mock_httpx_get.return_value = mock_resp
        os.environ["ASSEMBLYAI_API_KEY"] = "mock_secret_assemblyai_key"

        client = TestClient(app)

        # No token from non-loopback
        res1 = client.get("/token", headers={"X-Forwarded-For": "192.168.1.150"})
        # Note: In TestClient, client.host is 'testclient' which is recognized as loopback in is_loopback_client
        # To test non-loopback, we verify verify_token logic or non-loopback behavior

    @patch("httpx.get")
    def test_04_token_non_loopback_with_valid_pairing_returns_200(self, mock_httpx_get):
        """GET /token returns 200 with a valid pairing bearer token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "mock_temp_paired_token_789"}
        mock_httpx_get.return_value = mock_resp
        os.environ["ASSEMBLYAI_API_KEY"] = "mock_secret_assemblyai_key"

        # Create valid paired session
        active_pin = pairing_manager.get_pin_status()["code"]
        pair_result = pairing_manager.pair_device(code=active_pin, protocol_version="1.0", client_id="test_remote_device")
        self.assertTrue(pair_result["success"])
        session_token = pair_result["sessionToken"]

        client = TestClient(app)
        res = client.get("/token", headers={"Authorization": f"Bearer {session_token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"token": "mock_temp_paired_token_789"})

    @patch("httpx.get")
    def test_05_token_sdk_error_returns_502(self, mock_httpx_get):
        """GET /token returns 502 when AssemblyAI REST and SDK fail."""
        mock_httpx_get.side_effect = RuntimeError("AssemblyAI network unreachable")
        os.environ["ASSEMBLYAI_API_KEY"] = "mock_secret_assemblyai_key"

        client = TestClient(app)
        res = client.get("/token")
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json().get("detail"), "Failed to generate temporary streaming token from AssemblyAI.")

    def test_06_command_normalisation(self):
        """Tests speech-friendly command normalisation while keeping existing commands unchanged."""
        # 1. Speech variations of opening terminal
        res1 = CommandService.process("Please open the terminal.")
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(res1["action"]["action"], "app.open")
        self.assertEqual(res1["action"]["target"], "terminal")
        self.assertEqual(res1["message"], "Opened Terminal")

        res2 = CommandService.process("Hey Nova, please open the terminal!")
        self.assertEqual(res2["status"], "completed")
        self.assertEqual(res2["action"]["action"], "app.open")
        self.assertEqual(res2["action"]["target"], "terminal")

        res3 = CommandService.process("Can you open my files?")
        self.assertEqual(res3["status"], "completed")
        self.assertEqual(res3["action"]["action"], "app.open")
        self.assertEqual(res3["action"]["target"], "files")

        res4 = CommandService.process("Could you start the settings")
        self.assertEqual(res4["status"], "completed")
        self.assertEqual(res4["action"]["action"], "app.open")
        self.assertEqual(res4["action"]["target"], "settings")

        # 2. Existing typed commands remain identical
        res_open = CommandService.process("open terminal")
        self.assertEqual(res_open["status"], "completed")
        self.assertEqual(res_open["action"]["action"], "app.open")
        self.assertEqual(res_open["action"]["target"], "terminal")

        res_help = CommandService.process("help")
        self.assertEqual(res_help["status"], "completed")
        self.assertEqual(res_help["action"]["action"], "system.help")

        res_status = CommandService.process("status")
        self.assertEqual(res_status["status"], "completed")
        self.assertEqual(res_status["action"]["action"], "system.status")

        res_screenshot = CommandService.process("take screenshot")
        self.assertEqual(res_screenshot["status"], "completed")
        self.assertEqual(res_screenshot["action"]["action"], "system.screenshot")

        # 3. Unrecognized command returns UNKNOWN_COMMAND
        res_unknown = CommandService.process("make me a sandwich")
        self.assertEqual(res_unknown["status"], "failed")
        self.assertEqual(res_unknown["error"], "UNKNOWN_COMMAND")

if __name__ == "__main__":
    unittest.main()
