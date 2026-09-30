import os
import json
import time
import secrets
import random
import socket
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any, List, Tuple

class PairingManager:
    def __init__(self, pin_ttl_seconds: int = 300, storage_file: Optional[str] = None):
        self.pin_ttl_seconds = pin_ttl_seconds
        self.current_code: Optional[str] = None
        self.code_created_at: float = 0
        self.code_expires_at: float = 0
        self.code_used: bool = False
        
        # In-memory storage for active session tokens (keyed by SHA-256 token hash)
        # token_hash -> {"deviceId": str, "issued_at": float, "expires_at": float, "is_local": bool}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        
        # Latest pairing attempt for UI visibility and diagnostics
        self.latest_attempt: Optional[Dict[str, Any]] = None

        # Resolve persistent sessions storage path (Ai_voice/data/sessions.json)
        if storage_file:
            self.storage_file = storage_file
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.storage_file = os.path.join(base_dir, "data", "sessions.json")
        
        # System device ID
        hostname = socket.gethostname()
        self.device_id = f"win-{hostname.lower()}"
        
        # Local system token for Nova OS browser interface (in-memory only, never persisted)
        self.local_token = f"local-session-{secrets.token_hex(16)}"
        local_hash = self._hash_token(self.local_token)
        self.sessions[local_hash] = {
            "deviceId": f"{self.device_id}-local",
            "issued_at": time.time(),
            "expires_at": time.time() + (86400 * 365),
            "is_local": True
        }
        
        # Load previously paired mobile device sessions from disk
        self._load_sessions()

        # Generate initial PIN
        self.generate_new_pin()

    @staticmethod
    def _hash_token(token: str) -> str:
        """Computes SHA-256 hash of a session token for secure storage and lookup."""
        return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()

    def prune_expired_sessions(self) -> int:
        """Removes all expired sessions from memory."""
        now = time.time()
        expired_keys = [
            th for th, s in self.sessions.items()
            if not s.get("is_local") and s.get("expires_at", 0) <= now
        ]
        for k in expired_keys:
            del self.sessions[k]
        return len(expired_keys)

    def _load_sessions(self):
        """Loads valid non-expired paired sessions from disk, pruning expired ones."""
        if not os.path.exists(self.storage_file):
            return
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            loaded_count = 0
            for item in data:
                token_hash = item.get("token_hash")
                expires_at = item.get("expires_at", 0)
                if token_hash and expires_at > now:
                    self.sessions[token_hash] = {
                        "deviceId": item.get("deviceId", self.device_id),
                        "client_id": item.get("client_id"),
                        "issued_at": item.get("issued_at", now),
                        "expires_at": expires_at,
                        "last_seen": item.get("last_seen", item.get("issued_at", now)),
                        "is_local": False
                    }
                    loaded_count += 1
            if loaded_count > 0:
                print(f"[PairingManager] Loaded {loaded_count} persisted paired session(s) from {self.storage_file}")
        except Exception as e:
            print(f"[PairingManager] Warning: Failed to load sessions from {self.storage_file}: {e}")

    def _save_sessions(self):
        """Persists paired mobile sessions (SHA-256 hash only) to disk after pruning expired sessions."""
        try:
            self.prune_expired_sessions()
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            records = []
            now = time.time()
            for token_hash, sess in self.sessions.items():
                # Never persist local browser tokens
                if sess.get("is_local"):
                    continue
                if sess.get("expires_at", 0) > now:
                    records.append({
                        "token_hash": token_hash,
                        "deviceId": sess.get("deviceId", self.device_id),
                        "client_id": sess.get("client_id"),
                        "issued_at": sess.get("issued_at", now),
                        "expires_at": sess.get("expires_at", now),
                        "last_seen": sess.get("last_seen", now)
                    })
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            print(f"[PairingManager] Warning: Failed to save sessions to {self.storage_file}: {e}")

    def record_attempt(self, client_ip: str, result: str) -> Dict[str, Any]:
        """
        Records the latest pairing attempt without storing sensitive PIN or token.
        result is one of: 'success', 'wrong_pin', 'expired', 'version_mismatch'.
        """
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")

        display_map = {
            "success": "paired successfully",
            "wrong_pin": "wrong PIN",
            "expired": "PIN expired",
            "version_mismatch": "version mismatch"
        }
        display_result = display_map.get(result, result)
        message = f"Phone {client_ip}: {display_result}, {time_str}"

        attempt_data = {
            "client_ip": client_ip,
            "time": time_str,
            "timestamp": now.timestamp(),
            "result": result,
            "message": message
        }
        self.latest_attempt = attempt_data
        return attempt_data

    def generate_new_pin(self) -> str:
        """Generates a fresh 6-digit PIN with a new TTL."""
        code = f"{random.randint(100000, 999999):06d}"
        now = time.time()
        self.current_code = code
        self.code_created_at = now
        self.code_expires_at = now + self.pin_ttl_seconds
        self.code_used = False
        print(f"[PairingManager] Generated new pairing PIN: {code} (expires in {self.pin_ttl_seconds}s)")
        return code

    def get_pin_status(self) -> Dict[str, Any]:
        """Returns the current PIN and expiry status. Auto-refreshes if expired."""
        now = time.time()
        if not self.current_code or self.code_used or now >= self.code_expires_at:
            self.generate_new_pin()
            
        remaining_seconds = max(0, int(self.code_expires_at - time.time()))
        return {
            "code": self.current_code,
            "expires_in": remaining_seconds,
            "created_at": self.code_created_at,
            "expires_at": self.code_expires_at,
            "used": self.code_used,
            "device_id": self.device_id,
            "paired_devices_count": len([s for s in self.sessions.values() if not s.get("is_local")]),
            "local_token": self.local_token,
            "latest_attempt": self.latest_attempt
        }

    def pair_device(self, code: str, protocol_version: str = "1.0", client_id: Optional[str] = None) -> Dict[str, Any]:
        """Validates code and returns canonical PairingResponse dictionary."""
        # 1. Check protocol version
        if protocol_version != "1.0":
            return {
                "success": False,
                "deviceId": "",
                "sessionToken": None,
                "refreshToken": None,
                "expiresAt": None,
                "errorMessage": f"INCOMPATIBLE_PROTOCOL_VERSION: Server protocol version is 1.0 (client sent {protocol_version})",
                "protocolVersion": "1.0"
            }

        # 2. Check PIN
        clean_code = str(code).strip()
        now = time.time()
        
        if not self.current_code or self.code_used or now >= self.code_expires_at:
            # Code expired or already used
            return {
                "success": False,
                "deviceId": "",
                "sessionToken": None,
                "refreshToken": None,
                "expiresAt": None,
                "errorMessage": "INVALID_PAIRING_CODE: The pairing code has expired or was already used. Please use the current code shown on the desktop.",
                "protocolVersion": "1.0"
            }

        if clean_code != self.current_code:
            return {
                "success": False,
                "deviceId": "",
                "sessionToken": None,
                "refreshToken": None,
                "expiresAt": None,
                "errorMessage": "INVALID_PAIRING_CODE: Incorrect 6-digit pairing code.",
                "protocolVersion": "1.0"
            }

        # Successful pairing
        self.code_used = True

        # If client_id is provided, replace any existing session for the same client_id
        if client_id:
            old_hashes = [
                th for th, s in self.sessions.items()
                if not s.get("is_local") and s.get("client_id") == client_id
            ]
            for old_th in old_hashes:
                del self.sessions[old_th]
                print(f"[PairingManager] Replaced previous session for clientId '{client_id}' (token hash: {old_th[:8]}...)")
        
        # Generate opaque session token
        session_token = f"win_sec_{secrets.token_urlsafe(32)}"
        token_hash = self._hash_token(session_token)
        token_lifetime_days = 30
        expiry_dt = datetime.now(timezone.utc) + timedelta(days=token_lifetime_days)
        
        # Store SHA-256 hash of token, keeping raw token only in the response to the phone
        self.sessions[token_hash] = {
            "deviceId": self.device_id,
            "client_id": client_id,
            "issued_at": now,
            "expires_at": now + (token_lifetime_days * 86400),
            "last_seen": now,
            "is_local": False
        }
        self._save_sessions()
        
        print(f"[PairingManager] Device paired successfully. Token issued (hash stored): {token_hash[:10]}...")
        
        # Auto-generate a new PIN for subsequent pairings
        self.generate_new_pin()

        return {
            "success": True,
            "deviceId": self.device_id,
            "sessionToken": session_token,
            "refreshToken": None,
            "expiresAt": expiry_dt.isoformat(),
            "errorMessage": None,
            "protocolVersion": "1.0"
        }

    def validate_token(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        """Validates bearer/session token. Returns session dict if valid, else None."""
        is_valid, _, session = self.check_token(token)
        return session if is_valid else None

    def check_token(self, token: Optional[str]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validates token and returns (is_valid, error_code, session).
        error_code can be None, 'MISSING_TOKEN', 'TOKEN_EXPIRED', or 'INVALID_TOKEN'.
        """
        if not token:
            return False, "MISSING_TOKEN", None

        # Clean quotes and whitespace
        token_str = str(token).strip().strip("'\"")
        if not token_str:
            return False, "MISSING_TOKEN", None

        token_hash = self._hash_token(token_str)

        # Lookup by token hash, or fallback to direct key lookup
        session = self.sessions.get(token_hash) or self.sessions.get(token_str)
        if not session:
            return False, "INVALID_TOKEN", None

        if time.time() > session.get("expires_at", 0):
            # Token expired
            self.sessions.pop(token_hash, None)
            self.sessions.pop(token_str, None)
            self._save_sessions()
            return False, "TOKEN_EXPIRED", None

        # Update last seen timestamp
        session["last_seen"] = time.time()
        return True, None, session

    def get_paired_devices(self) -> List[Dict[str, Any]]:
        """Returns live list of active paired mobile devices for Settings app."""
        self.prune_expired_sessions()
        devices = []
        for token_hash, s in self.sessions.items():
            if s.get("is_local"):
                continue
            issued = s.get("issued_at", time.time())
            last_seen = s.get("last_seen", issued)
            devices.append({
                "device_id": s.get("deviceId", self.device_id),
                "client_id": s.get("client_id") or "Phone Client",
                "issued_at": issued,
                "paired_at_str": datetime.fromtimestamp(issued).strftime("%Y-%m-%d %H:%M:%S"),
                "last_seen_str": datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M:%S"),
                "token_hash": token_hash,
                "token_preview": f"{token_hash[:8]}..."
            })
        devices.sort(key=lambda x: x["issued_at"], reverse=True)
        return devices

    def revoke_token(self, token_or_hash: str) -> bool:
        """Revokes a session token by raw token or token hash."""
        if not token_or_hash:
            return False
        token_str = token_or_hash.strip()
        token_hash = self._hash_token(token_str)

        removed = False
        if token_hash in self.sessions:
            del self.sessions[token_hash]
            removed = True
        if token_str in self.sessions:
            del self.sessions[token_str]
            removed = True

        if removed:
            self._save_sessions()
        return removed

    def revoke_device(self, device_id: str) -> int:
        """Revokes all sessions associated with a given deviceId."""
        to_delete = [
            th for th, s in self.sessions.items()
            if s.get("deviceId") == device_id and not s.get("is_local")
        ]
        for th in to_delete:
            del self.sessions[th]
        if to_delete:
            self._save_sessions()
        return len(to_delete)

# Global instance
pairing_manager = PairingManager()

