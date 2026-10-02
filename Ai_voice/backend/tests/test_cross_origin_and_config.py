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
from backend.config.endpoints import get_utility_backend_url
from backend.api.http_routes import _token_rate_limits, TOKEN_MAX_PER_MINUTE


class TestCrossOriginAndCloudIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.original_key = os.environ.get("ASSEMBLYAI_API_KEY")
        self.original_utility = os.environ.get("UTILITY_BACKEND_URL")
        # Clear rate limit state
        _token_rate_limits.clear()

    def tearDown(self):
        _token_rate_limits.clear()
        if self.original_key is not None:
            os.environ["ASSEMBLYAI_API_KEY"] = self.original_key
        else:
            os.environ.pop("ASSEMBLYAI_API_KEY", None)

        if self.original_utility is not None:
            os.environ["UTILITY_BACKEND_URL"] = self.original_utility
        else:
            os.environ.pop("UTILITY_BACKEND_URL", None)

    def test_01_cors_preflight_for_vercel_origin(self):
        """OPTIONS preflight from Vercel origin returns 200 with allowed headers."""
        headers = {
            "Origin": "https://gorios-frontend.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type"
        }
        res = self.client.options("/upload/file", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "https://gorios-frontend.vercel.app")
        self.assertIn("authorization", res.headers.get("access-control-allow-headers", "").lower())

    def test_02_health_forwarded_headers(self):
        """GET /health honors X-Forwarded-Proto and X-Forwarded-Host returning wss:// URL."""
        headers = {
            "X-Forwarded-Host": "gori-os.onrender.com",
            "X-Forwarded-Proto": "https"
        }
        res = self.client.get("/health", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("ws_urls", data)
        self.assertEqual(data["ws_urls"], ["wss://gori-os.onrender.com/ws"])

    @patch("httpx.get")
    def test_03_token_authorized_by_vercel_origin(self, mock_httpx_get):
        """GET /token grants AssemblyAI token to Vercel origin without pairing PIN."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "mock_assemblyai_token_vercel"}
        mock_httpx_get.return_value = mock_resp
        os.environ["ASSEMBLYAI_API_KEY"] = "mock_secret_key"

        headers = {
            "Origin": "https://gorios-frontend.vercel.app",
            "X-Forwarded-For": "203.0.113.195"
        }
        res = self.client.get("/token", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"token": "mock_assemblyai_token_vercel"})

    @patch("httpx.get")
    def test_04_token_rate_limiting_exceeded(self, mock_httpx_get):
        """GET /token returns 429 when rate limit is exceeded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "mock_token"}
        mock_httpx_get.return_value = mock_resp
        os.environ["ASSEMBLYAI_API_KEY"] = "mock_secret_key"

        headers = {
            "Origin": "https://gorios-frontend.vercel.app",
            "X-Forwarded-For": "203.0.113.50"
        }
        # Exhaust limit
        for _ in range(TOKEN_MAX_PER_MINUTE):
            res = self.client.get("/token", headers=headers)
            self.assertEqual(res.status_code, 200)

        # 11th request triggers rate limit 429
        res_overflow = self.client.get("/token", headers=headers)
        self.assertEqual(res_overflow.status_code, 429)
        self.assertIn("Rate limit exceeded", res_overflow.json().get("detail", ""))

    def test_05_browser_endpoints_csp_iframe_headers(self):
        """Browser search and proxy endpoints include frame-ancestors for Vercel embedding."""
        res_search = self.client.get("/api/browser/search")
        self.assertEqual(res_search.status_code, 200)
        csp = res_search.headers.get("content-security-policy", "")
        self.assertIn("frame-ancestors", csp)
        self.assertIn("https://gorios-frontend.vercel.app", csp)
        self.assertNotIn("x-frame-options", res_search.headers)

    def test_06_utility_backend_url_helper(self):
        """get_utility_backend_url honors UTILITY_BACKEND_URL override and falls back to config."""
        # Unset env var
        os.environ.pop("UTILITY_BACKEND_URL", None)
        base_fallback = get_utility_backend_url()
        self.assertTrue(base_fallback.startswith("http"))

        # Set env var
        os.environ["UTILITY_BACKEND_URL"] = "https://custom-utility-backend.onrender.com/"
        base_override = get_utility_backend_url()
        self.assertEqual(base_override, "https://custom-utility-backend.onrender.com")


if __name__ == "__main__":
    unittest.main()
