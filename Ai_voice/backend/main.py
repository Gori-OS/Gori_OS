import os
import sys
import time
import threading
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, WebSocket, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from dotenv import load_dotenv

# Ensure project root is in sys.path so 'backend' package is resolvable
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
repo_root = os.path.dirname(project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load .env from project root (folder containing run_bridge.py), falling back to real env vars
dotenv_path = os.path.join(repo_root, ".env")
if os.path.isfile(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    load_dotenv()

from backend.api.http_routes import router as http_router, UPLOAD_DIR
from backend.api.ws_routes import handle_websocket_connection
from backend.services.mdns_service import MDNSService
from backend.services.diagnostics_service import diagnostics_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nova_bridge")

# Configurable ports per contract
HTTP_PORT = int(os.environ.get("PORT_HTTP", os.environ.get("PORT", "7890")))
_raw_ws = os.environ.get("PORT_WS")
if _raw_ws:
    WS_PORT = int(_raw_ws)
elif os.environ.get("PORT"):
    WS_PORT = HTTP_PORT
else:
    WS_PORT = 7891

mdns_service = MDNSService(
    service_type="_winbridge._tcp.local.",
    http_port=HTTP_PORT,
    ws_port=WS_PORT
)

import socket

# Dedicated WS App for port 7891
ws_standalone_app = FastAPI(title="Nova OS Bridge WebSocket")

@ws_standalone_app.websocket("/ws")
async def standalone_ws_endpoint(websocket: WebSocket):
    await handle_websocket_connection(websocket, client_type_hint="phone_ws")

_ws_thread_started = False
_ws_thread_lock = threading.Lock()

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a local TCP port is already bound and actively listening without creating TIME_WAIT conflicts."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((host, port))
            return True
        except (OSError, ConnectionRefusedError):
            return False

def run_standalone_ws_server(port: int):
    """Runs the dedicated WebSocket server on port 7891 in a daemon thread with 1 retry on bind failure."""
    attempts = 0
    max_attempts = 2

    while attempts < max_attempts:
        attempts += 1
        if is_port_in_use(port):
            if attempts < max_attempts:
                logger.warning(f"[WebSocket Server] Port {port} appears in use. Retrying in 0.5s (attempt {attempts}/{max_attempts})...")
                time.sleep(0.5)
                continue
            else:
                err_msg = f"[WebSocket Server] ERROR: Port {port} is in use after retry! Dedicated WebSocket server cannot bind. Continuing to serve /ws on main HTTP port {HTTP_PORT}."
                logger.error(err_msg)
                print(err_msg)
                diagnostics_service.ws_port_bound = False
                diagnostics_service.ws_bind_error = f"Port {port} in use"
                return

        try:
            config = uvicorn.Config(
                app=ws_standalone_app,
                host="0.0.0.0",
                port=port,
                log_level="warning",
                access_log=False
            )
            server = uvicorn.Server(config)
            diagnostics_service.ws_port_bound = True
            diagnostics_service.ws_bind_error = None
            print(f"[WebSocket Server] Listening on ws://0.0.0.0:{port}/ws")
            server.run()
            break
        except Exception as e:
            if attempts < max_attempts:
                logger.warning(f"[WebSocket Server] Error starting on port {port}: {e}. Retrying in 0.5s...")
                time.sleep(0.5)
            else:
                err_msg = f"[WebSocket Server] ERROR: Failed starting on port {port} after retry: {e}. Dedicated WebSocket server cannot bind. Continuing to serve /ws on main HTTP port {HTTP_PORT}."
                logger.error(err_msg)
                print(err_msg)
                diagnostics_service.ws_port_bound = False
                diagnostics_service.ws_bind_error = str(e)
                return

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ws_thread_started
    # 1. Start mDNS advertisement asynchronously
    await mdns_service.start()

    # 2. Start dedicated WebSocket server on port 7891 if different from HTTP_PORT
    if WS_PORT != HTTP_PORT:
        with _ws_thread_lock:
            if not _ws_thread_started:
                _ws_thread_started = True
                ws_thread = threading.Thread(
                    target=run_standalone_ws_server,
                    args=(WS_PORT,),
                    daemon=True,
                    name="WebSocketServerThread"
                )
                ws_thread.start()
            else:
                logger.warning("[WebSocket Server] Dedicated WS server thread already started for this process.")
    else:
        diagnostics_service.ws_port_bound = True

    yield

    # Shutdown
    await mdns_service.stop()

# Main FastAPI App (Port 7890)
app = FastAPI(
    title="Nova OS Bridge",
    description="Windows Remote Bridge Server for AI Voice & Desktop Automation",
    version="1.0.0",
    lifespan=lifespan
)

# Parse allowed origins from env or default
allowed_origins_env = os.environ.get("ALLOWED_ORIGINS")
if allowed_origins_env:
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "https://gorios-frontend.vercel.app",
        "https://gori-os.onrender.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:7890",
        "http://localhost:7891",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:7890",
        "http://127.0.0.1:7891",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Middleware: Track non-loopback phone requests into ring buffer (time, client IP, method, path, status)
@app.middleware("http")
async def track_non_loopback_contact_middleware(request: Request, call_next):
    response = await call_next(request)
    try:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else ""

        diagnostics_service.record_client_request(
            client_ip=client_ip,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code
        )
    except Exception:
        pass
    return response

# Mount HTTP routes (/health, /pair, /upload/file, /upload/photo, /files, /api/status, /api/network/diagnostics)
app.include_router(http_router)

# Mount WebSocket on main app as well (dual-port compatibility)
@app.websocket("/ws")
async def main_ws_endpoint(websocket: WebSocket):
    await handle_websocket_connection(websocket, client_type_hint="main_ws")

# Root redirect to /desktop
@app.get("/")
async def root():
    return RedirectResponse(url="/desktop")

# Mount static frontend
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/desktop", StaticFiles(directory=frontend_dir, html=True), name="desktop")

# Mount uploads for direct file viewing
if os.path.exists(UPLOAD_DIR):
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=HTTP_PORT, reload=False)
