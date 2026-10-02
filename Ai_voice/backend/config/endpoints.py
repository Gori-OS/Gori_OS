import os
import json
from typing import Optional

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endpoints.json")


def get_utility_backend_url(config_path: Optional[str] = None) -> str:
    """
    Returns the single utility backend URL source of truth.
    UTILITY_BACKEND_URL environment variable is the single override everywhere.
    Falls back to base_url defined in endpoints.json, then to default endpoint host.
    """
    env_override = os.environ.get("UTILITY_BACKEND_URL")
    if env_override and env_override.strip():
        return env_override.strip().rstrip("/")

    target_config = config_path or CONFIG_PATH
    try:
        if os.path.isfile(target_config):
            with open(target_config, "r", encoding="utf-8") as f:
                data = json.load(f)
                base = data.get("base_url")
                if base and isinstance(base, str) and base.strip():
                    return base.strip().rstrip("/")
    except Exception:
        pass

    return "https://goori-os-backend-endpoints.onrender.com"
