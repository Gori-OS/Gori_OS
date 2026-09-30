import os
import time
import ipaddress
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Header, UploadFile, File, Form, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse

from backend.auth.pairing_manager import pairing_manager
from backend.protocol.schemas import PairingRequest, PairingResponse
from backend.services.connection_manager import connection_manager
from backend.services.diagnostics_service import diagnostics_service

logger = logging.getLogger("nova_bridge.http")

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FILES_DIR = os.path.join(UPLOAD_DIR, "files")
MOBILE_DIR = os.path.join(FILES_DIR, "mobile")
PHOTOS_DIR = os.path.join(MOBILE_DIR, "photos")
OUTPUT_DIR = os.path.join(FILES_DIR, "output")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(MOBILE_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def is_loopback_client(host: Optional[str]) -> bool:
    """Checks whether the client host is a local loopback interface."""
    if not host:
        return False
    if host in ("localhost", "testclient"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False

def verify_token(authorization: Optional[str] = None, token: Optional[str] = None) -> Dict[str, Any]:
    """Helper to validate bearer token from header or query param with resilient parsing."""
    extracted_token = None
    if authorization:
        auth_clean = authorization.strip()
        auth_lower = auth_clean.lower()
        if auth_lower.startswith("bearer "):
            extracted_token = auth_clean[7:].strip().strip("'\"")
        elif auth_lower.startswith("token "):
            extracted_token = auth_clean[6:].strip().strip("'\"")
        elif not any(auth_lower.startswith(p) for p in ("basic ", "digest ")):
            extracted_token = auth_clean.strip("'\"")

    if not extracted_token and token:
        extracted_token = token.strip().strip("'\"")

    if not extracted_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "Unauthorized: Missing authorization token.", "error": "UNAUTHORIZED"}
        )

    is_valid, err_code, session = pairing_manager.check_token(extracted_token)
    if not is_valid or not session:
        if err_code == "TOKEN_EXPIRED":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"detail": "Unauthorized: Authorization token has expired. Please re-pair your device with the 6-digit PIN.", "error": "TOKEN_EXPIRED"}
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "Unauthorized: Invalid or expired authorization token.", "error": "UNAUTHORIZED"}
        )
    return session

@router.get("/token")
async def get_streaming_token(
    request: Request,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
):
    """
    CANONICAL WINDOWS BRIDGE PROTOCOL: GET /token
    Mints a short-lived (60s) single-use temporary token for AssemblyAI streaming.
    Only allows loopback clients (127.0.0.1, ::1, localhost) or paired clients
    with a valid bearer token. Returns 403 otherwise.
    """
    client_ip = request.client.host if request.client else None
    if not is_loopback_client(client_ip):
        try:
            verify_token(authorization=authorization, token=token)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Non-loopback client requires a valid pairing token."
            )

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AssemblyAI API key is not configured on the server."
        )

    temp_token = None
    # 1. Primary: Direct REST call to AssemblyAI streaming v3 token endpoint
    try:
        import httpx
        resp = httpx.get(
            "https://streaming.assemblyai.com/v3/token",
            headers={"Authorization": api_key.strip()},
            params={"expires_in_seconds": 60, "max_session_duration_seconds": 300},
            timeout=10.0
        )
        if resp.status_code == 200:
            token_data = resp.json()
            temp_token = token_data.get("token")
        else:
            logger.warning(f"[AssemblyAI] REST token request returned HTTP {resp.status_code}: {resp.text}")
    except Exception as ex:
        logger.warning(f"[AssemblyAI] REST token request exception: {ex}")

    # 2. Fallback: AssemblyAI Python SDK (if installed)
    if not temp_token:
        try:
            from assemblyai.streaming.v3 import RealTimeTranscriber
            transcriber = RealTimeTranscriber(api_key=api_key.strip())
            temp_token = transcriber.create_temporary_token(
                expires_in_seconds=60,
                max_session_duration_seconds=300
            )
        except Exception as e:
            logger.error(f"[AssemblyAI] SDK token generation also failed: {type(e).__name__} {e}")

    if not temp_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate temporary streaming token from AssemblyAI."
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"token": temp_token},
        headers={"Cache-Control": "no-store"}
    )


@router.get("/health")
async def health_endpoint(request: Request):
    """
    CANONICAL WINDOWS BRIDGE PROTOCOL: GET /health
    Unauthenticated health check for reachability testing and network diagnostics.
    """
    from backend.services.mdns_service import get_lan_ipv4_addresses
    http_port = int(os.environ.get("PORT_HTTP", os.environ.get("HTTP_PORT", os.environ.get("PORT", "7890"))))
    ws_port = int(os.environ.get("PORT_WS", os.environ.get("WS_PORT", "7891")))
    lan_ips = get_lan_ipv4_addresses()

    # Determine host for ws_urls fallback
    host = request.url.hostname if (request and request.url and request.url.hostname) else None
    if not host or host in ("0.0.0.0", "127.0.0.1", "localhost"):
        host = lan_ips[0] if lan_ips else "127.0.0.1"

    ws_urls = [
        f"ws://{host}:{ws_port}/ws",
        f"ws://{host}:{http_port}/ws"
    ]

    return {
        "status": "ok",
        "protocol_version": "1.0",
        "device_id": pairing_manager.device_id,
        "http_port": http_port,
        "ws_port": ws_port,
        "ws_port_bound": diagnostics_service.ws_port_bound,
        "ws_urls": ws_urls,
        "lan_ips": lan_ips
    }

@router.post("/pair", response_model=PairingResponse)
async def pair_endpoint(request: Request):
    """
    CANONICAL WINDOWS BRIDGE PROTOCOL: POST /pair
    Accepts 6-digit PIN and validates against current active PIN.
    Returns opaque sessionToken, deviceId, and expiry.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    code = str(body.get("code") or "").strip()
    protocol_version = str(body.get("protocolVersion") or body.get("protocol_version") or "1.0").strip()
    client_id = body.get("clientId") or body.get("client_id")
    if client_id is not None:
        client_id = str(client_id).strip()

    client_ip = request.client.host if (request.client and request.client.host) else "unknown"

    # Validate pairing (PIN validation logic in pairing_manager.pair_device is preserved)
    result = pairing_manager.pair_device(code=code, protocol_version=protocol_version, client_id=client_id)

    # Classify outcome for audit log and pairing visibility
    if result.get("success"):
        outcome = "success"
    else:
        err = result.get("errorMessage") or ""
        if "INCOMPATIBLE_PROTOCOL_VERSION" in err:
            outcome = "version_mismatch"
        elif "expired" in err or "already used" in err:
            outcome = "expired"
        else:
            outcome = "wrong_pin"

    # Log attempt (client IP, time, result). NEVER log raw tokens or PIN!
    attempt_record = pairing_manager.record_attempt(client_ip=client_ip, result=outcome)
    print(f"[Pairing] {attempt_record['message']}")

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)

@router.get("/pair/status")
async def get_pair_status():
    """Returns current active PIN, expiry countdown, latest attempt, and local session info for Nova OS desktop UI."""
    return pairing_manager.get_pin_status()

@router.post("/pair/regenerate")
async def regenerate_pair_code():
    """Forces regeneration of the 6-digit pairing code."""
    new_code = pairing_manager.generate_new_pin()
    return {"success": True, "code": new_code, "status": pairing_manager.get_pin_status()}

@router.post("/pair/revoke")
async def revoke_pair_session(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Revokes a paired session token. Accepts token in Authorization header or JSON body.
    """
    token_to_revoke = None
    if authorization and authorization.startswith("Bearer "):
        token_to_revoke = authorization.split("Bearer ", 1)[1].strip()
    else:
        try:
            body = await request.json()
            token_to_revoke = body.get("token") or body.get("token_hash")
        except Exception:
            pass

    if not token_to_revoke:
        raise HTTPException(status_code=400, detail="Token required to revoke")

    revoked = pairing_manager.revoke_token(token_to_revoke)
    return {"success": revoked, "message": "Session revoked" if revoked else "Token not found"}

@router.post("/upload/file")
async def upload_file(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
):
    """
    CANONICAL WINDOWS BRIDGE PROTOCOL: POST /upload/file
    Authenticated streaming file upload to uploads/ directory.
    """
    verify_token(authorization=authorization, token=token)

    safe_filename = os.path.basename(file.filename or f"file_{int(time.time())}.bin")
    file_path = os.path.join(MOBILE_DIR, safe_filename)

    # Stream to disk without buffering entire file in memory
    total_bytes = 0
    chunk_size = 64 * 1024
    with open(file_path, "wb") as buffer:
        while chunk := await file.read(chunk_size):
            buffer.write(chunk)
            total_bytes += len(chunk)

    print(f"[Upload] Streamed file: {safe_filename} ({total_bytes} bytes) to {file_path}")

    return {
        "success": True,
        "filename": safe_filename,
        "size": total_bytes,
        "path": f"/uploads/files/mobile/{safe_filename}",
        "uploaded_at": datetime.now().isoformat()
    }

@router.post("/upload/photo")
async def upload_photo(
    photo: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
):
    """
    CANONICAL WINDOWS BRIDGE PROTOCOL: POST /upload/photo
    Authenticated streaming photo upload to uploads/files/mobile/photos/ directory.
    """
    verify_token(authorization=authorization, token=token)

    safe_filename = os.path.basename(photo.filename or f"photo_{int(time.time())}.jpg")
    photo_path = os.path.join(PHOTOS_DIR, safe_filename)

    # Stream to disk without buffering entire photo in memory
    total_bytes = 0
    chunk_size = 64 * 1024
    with open(photo_path, "wb") as buffer:
        while chunk := await photo.read(chunk_size):
            buffer.write(chunk)
            total_bytes += len(chunk)

    print(f"[Upload] Streamed photo: {safe_filename} ({total_bytes} bytes) to {photo_path}")

    return {
        "success": True,
        "filename": safe_filename,
        "size": total_bytes,
        "path": f"/uploads/files/mobile/photos/{safe_filename}",
        "uploaded_at": datetime.now().isoformat()
    }

def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

@router.get("/files")
async def list_files():
    """
    Returns live list of all files and photos stored in uploads/files/mobile/ directory.
    Used by Nova OS Files desktop app.
    """
    file_list = []
    
    # 1. Check general files in uploads/files/mobile/
    if os.path.exists(MOBILE_DIR):
        for item in os.listdir(MOBILE_DIR):
            if item.startswith("."):
                continue
            item_path = os.path.join(MOBILE_DIR, item)
            if os.path.isfile(item_path):
                stat = os.stat(item_path)
                file_list.append({
                    "name": item,
                    "size": stat.st_size,
                    "size_formatted": format_file_size(stat.st_size),
                    "type": "file",
                    "path": f"/uploads/files/mobile/{item}",
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })

    # 2. Check photos in uploads/files/mobile/photos/
    if os.path.exists(PHOTOS_DIR):
        for item in os.listdir(PHOTOS_DIR):
            if item.startswith("."):
                continue
            item_path = os.path.join(PHOTOS_DIR, item)
            if os.path.isfile(item_path):
                stat = os.stat(item_path)
                file_list.append({
                    "name": item,
                    "size": stat.st_size,
                    "size_formatted": format_file_size(stat.st_size),
                    "type": "photo",
                    "path": f"/uploads/files/mobile/photos/{item}",
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })

    # 3. Check processed output files in uploads/files/output/
    if os.path.exists(OUTPUT_DIR):
        for item in os.listdir(OUTPUT_DIR):
            if item.startswith("."):
                continue
            item_path = os.path.join(OUTPUT_DIR, item)
            if os.path.isfile(item_path):
                stat = os.stat(item_path)
                file_list.append({
                    "name": item,
                    "size": stat.st_size,
                    "size_formatted": format_file_size(stat.st_size),
                    "type": "output",
                    "folder": "output",
                    "path": f"/uploads/files/output/{item}",
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })

    # Sort newest first
    file_list.sort(key=lambda x: x["modified"], reverse=True)
    return {"files": file_list, "total": len(file_list)}

@router.delete("/files")
@router.post("/files/delete")
async def delete_file_endpoint(
    request: Request,
    path: Optional[str] = Query(None),
    filename: Optional[str] = Query(None),
    folder: Optional[str] = Query(None)
):
    """
    Deletes a specific uploaded or output file securely.
    Guarantees only the targeted file is removed and prevents directory traversal.
    """
    target_path_str = path
    if not target_path_str:
        try:
            body = await request.json()
            if isinstance(body, dict):
                target_path_str = body.get("path") or body.get("filename")
                if not folder and "folder" in body:
                    folder = body.get("folder")
        except Exception:
            pass

    # Resolve filename & folder if full path not given directly
    if not target_path_str and filename:
        clean_fn = os.path.basename(filename.strip())
        if folder == "output":
            target_path_str = os.path.join(OUTPUT_DIR, clean_fn)
        elif folder == "photos":
            target_path_str = os.path.join(PHOTOS_DIR, clean_fn)
        else:
            target_path_str = os.path.join(MOBILE_DIR, clean_fn)

    if not target_path_str:
        raise HTTPException(status_code=400, detail="Missing file 'path' or 'filename' parameter.")

    # Normalize relative web path (e.g. /uploads/files/mobile/sample.png -> absolute path)
    clean_p = target_path_str.replace("\\", "/").strip()
    if clean_p.startswith("/uploads/"):
        rel = clean_p.split("/uploads/", 1)[-1]
        abs_target = os.path.abspath(os.path.join(UPLOAD_DIR, rel))
    elif clean_p.startswith("uploads/"):
        rel = clean_p.split("uploads/", 1)[-1]
        abs_target = os.path.abspath(os.path.join(UPLOAD_DIR, rel))
    elif os.path.isabs(clean_p):
        abs_target = os.path.abspath(clean_p)
    else:
        # Search candidate in known upload folders
        found = False
        for d in [OUTPUT_DIR, PHOTOS_DIR, MOBILE_DIR, UPLOAD_DIR]:
            candidate = os.path.join(d, os.path.basename(clean_p))
            if os.path.isfile(candidate):
                abs_target = os.path.abspath(candidate)
                found = True
                break
        if not found:
            abs_target = os.path.abspath(os.path.join(MOBILE_DIR, os.path.basename(clean_p)))

    # Path traversal security guard: must reside strictly inside UPLOAD_DIR
    upload_root = os.path.abspath(UPLOAD_DIR)
    try:
        common = os.path.commonpath([abs_target, upload_root])
        if common != upload_root:
            raise HTTPException(status_code=403, detail="Forbidden: Path traversal outside upload directory.")
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid file path.")

    # Guard: do not delete directories
    protected_dirs = [
        os.path.abspath(UPLOAD_DIR),
        os.path.abspath(FILES_DIR),
        os.path.abspath(MOBILE_DIR),
        os.path.abspath(PHOTOS_DIR),
        os.path.abspath(OUTPUT_DIR)
    ]
    if abs_target in protected_dirs or os.path.isdir(abs_target):
        raise HTTPException(status_code=400, detail="Cannot delete system directories.")

    if not os.path.exists(abs_target):
        raise HTTPException(status_code=404, detail=f"File not found: '{os.path.basename(abs_target)}'")

    try:
        os.remove(abs_target)
        fn = os.path.basename(abs_target)
        logger.info(f"[Files] Deleted file: {abs_target}")
        return {
            "success": True,
            "message": f"Successfully deleted '{fn}'",
            "filename": fn,
            "path": target_path_str
        }
    except Exception as e:
        logger.error(f"[Files] Failed to delete file {abs_target}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


@router.get("/api/file-processor/config")
async def get_file_processor_config():
    """Returns current configurable endpoint mappings for file processing."""
    from backend.services.file_processing_service import file_processing_service
    return file_processing_service.config

@router.post("/api/file-processor/config")
async def update_file_processor_config(payload: Dict[str, Any]):
    """Updates and persists configurable endpoint mappings for file processing."""
    from backend.services.file_processing_service import file_processing_service
    file_processing_service.update_config(payload)
    return {"status": "ok", "message": "File processor configuration updated."}

@router.post("/api/file-processor/process")
async def process_file_endpoint(payload: Dict[str, Any]):
    """Processes a file processing command via REST API."""
    cmd = payload.get("command") or ""
    if not cmd:
        raise HTTPException(status_code=400, detail="Missing 'command' field in request.")
    from backend.services.command_service import CommandService
    res = CommandService.process(cmd)
    return res

@router.get("/pair/devices")
async def get_paired_devices():
    """Returns list of active paired mobile devices with last_seen and paired timestamps for Settings."""
    return {"devices": pairing_manager.get_paired_devices()}

@router.get("/api/network/diagnostics")
async def get_network_diagnostics():
    """
    CANONICAL WINDOWS BRIDGE PROTOCOL: GET /api/network/diagnostics
    Returns detailed LAN adapters, ports, bind statuses, firewall rules check,
    mDNS registration, last phone contact, and recent phone contacts ring buffer.
    """
    http_port = int(os.environ.get("PORT_HTTP", os.environ.get("HTTP_PORT", os.environ.get("PORT", "7890"))))
    ws_port = int(os.environ.get("PORT_WS", os.environ.get("WS_PORT", "7891")))
    adapters = diagnostics_service.get_detailed_lan_adapters()
    fw_check = diagnostics_service.check_firewall_rules()

    return {
        "lan_ips": adapters,
        "http_port": http_port,
        "ws_port": ws_port,
        "ws_bound": diagnostics_service.ws_port_bound,
        "firewall_rules_ok": fw_check["ok"],
        "firewall_info": fw_check,
        "mdns_registered": diagnostics_service.mdns_registered,
        "last_phone_contact": diagnostics_service.get_last_phone_contact(),
        "recent_contacts": diagnostics_service.get_recent_contacts(),
        "last_pairing_attempt": pairing_manager.latest_attempt
    }

@router.get("/api/status")
async def get_bridge_status():
    """Returns bridge server telemetry and live client stats for Settings app."""
    pin_status = pairing_manager.get_pin_status()
    return {
        "status": "online",
        "protocol_version": "1.0",
        "device_id": pairing_manager.device_id,
        "connected_phones": connection_manager.get_authenticated_phone_count(),
        "total_connections": len(connection_manager.connections),
        "active_devices": connection_manager.get_authenticated_devices(),
        "pairing_code": pin_status["code"],
        "pin_expires_in": pin_status["expires_in"],
        "latest_attempt": pin_status.get("latest_attempt"),
        "ws_port_bound": diagnostics_service.ws_port_bound,
        "last_phone_contact": diagnostics_service.get_last_phone_contact(),
        "paired_devices": pairing_manager.get_paired_devices()
    }

@router.get("/api/browser/search", response_class=HTMLResponse)
async def browser_search_endpoint(q: Optional[str] = Query(None)):
    """
    Renders Google Search results page or Google homepage inside the WebView.
    """
    from backend.services.browser_service import browser_service
    if not q or not q.strip():
        return HTMLResponse(content=browser_service.render_google_homepage())
    search_data = browser_service.perform_search(q)
    html_content = browser_service.render_google_results_page(q, search_data)
    return HTMLResponse(content=html_content)

@router.get("/api/browser/proxy", response_class=HTMLResponse)
async def browser_proxy_endpoint(url: str = Query(...)):
    """
    Proxies web pages inside the in-OS WebView, stripping X-Frame-Options/CSP restrictions.
    """
    from backend.services.browser_service import browser_service
    html_content = await browser_service.proxy_web_page(url)
    return HTMLResponse(content=html_content)

