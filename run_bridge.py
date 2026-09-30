#!/usr/bin/env python3
"""
Nova OS — Windows AI Bridge Launcher
Single launcher and source of truth for ports, network binding, and truthful diagnostics.
"""
import os
import sys
import time
import socket
import signal
import atexit
import argparse
import threading
from typing import List, Dict, Any

# Ensure stdout flushes immediately
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Ensure project directories are in sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
ai_voice_dir = os.path.join(root_dir, "Ai_voice")
if ai_voice_dir not in sys.path:
    sys.path.insert(0, ai_voice_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Parse optional command line flags for ports
parser = argparse.ArgumentParser(description="Nova OS Windows AI Bridge Server")
parser.add_argument("--http-port", "--port", type=int, default=None, help="HTTP Server port (default: 7890)")
parser.add_argument("--ws-port", type=int, default=None, help="WebSocket Server port (default: 7891)")
args, unknown = parser.parse_known_args()

# One source of truth for ports
HTTP_PORT = args.http_port or int(os.environ.get("PORT_HTTP", os.environ.get("HTTP_PORT", os.environ.get("PORT", "7890"))))
WS_PORT = args.ws_port or int(os.environ.get("PORT_WS", os.environ.get("WS_PORT", "7891")))

os.environ["PORT_HTTP"] = str(HTTP_PORT)
os.environ["PORT_WS"] = str(WS_PORT)

# Import backend services
import uvicorn
from backend.main import app, mdns_service, is_port_in_use
from backend.auth.pairing_manager import pairing_manager
from backend.services.diagnostics_service import diagnostics_service

# Guarantee advertised port always equals the listening port
mdns_service.http_port = HTTP_PORT
mdns_service.ws_port = WS_PORT

# Clean shutdown handler for Ctrl+C, SIGTERM, and console close
def clean_shutdown_handler(signum=None, frame=None):
    print("\n[Shutdown] Stopping Windows AI Bridge cleanly...")
    try:
        mdns_service.stop_sync()
    except Exception:
        pass
    if signum is not None:
        sys.exit(0)

signal.signal(signal.SIGINT, clean_shutdown_handler)
signal.signal(signal.SIGTERM, clean_shutdown_handler)
atexit.register(mdns_service.stop_sync)


def print_startup_diagnostics(adapters: List[Dict[str, Any]], http_port: int, ws_port: int, pin: str):
    """
    TASK 1: Truthful startup checks
    Prints prominent PASS/FAIL lines for:
    - Firewall rules for active profile
    - LAN IPv4s with adapter names and virtual flags
    """
    pin_formatted = f"{pin[:3]} {pin[3:]}" if len(pin) == 6 else pin
    print()
    print("=" * 76)
    print("                 NOVA OS -- WINDOWS AI BRIDGE SERVER")
    print("=" * 76)
    print(f"  Configuration:   HTTP: {http_port} | Dedicated WS: {ws_port}")
    print(f"  Desktop UI:      http://localhost:{http_port}/desktop")
    print(f"  Pairing PIN:     {pin_formatted}  (Enter on phone to pair)")
    print("-" * 76)

    # 1. Firewall Rule Check (Task 1c)
    fw_check = diagnostics_service.check_firewall_rules()
    active_prof = fw_check.get("active_profile", "Unknown")
    if fw_check.get("ok"):
        print(f"  [PASS] Firewall: TCP {http_port}, TCP {ws_port}, UDP 5353 allowed on active profile '{active_prof}'.")
    else:
        missing = fw_check.get("missing", [])
        print(f"  [FAIL] Firewall: BLOCKED on active profile '{active_prof}'! Missing: {', '.join(missing)}")
        print(f"         Phones on your Wi-Fi will NOT be able to connect.")
        print(f"         FIX: Open PowerShell as Administrator and run:")
        print(f"           powershell -ExecutionPolicy Bypass -File scripts/allow_firewall.ps1")
    print("-" * 76)

    # 2. LAN Adapters & Virtual Flags (Task 1d)
    print("  LAN IPv4 Network Interfaces:")
    if adapters:
        for a in adapters:
            ip = a["ip"]
            name = a["adapter"]
            if a.get("recommended"):
                flag = "-> [RECOMMENDED FOR PHONE]"
            elif a.get("is_virtual"):
                flag = "-> [VIRTUAL ADAPTER / VPN - DO NOT USE]"
            else:
                flag = "->"
            print(f"    * {ip:<15} ({name}) {flag}")
            if a.get("recommended"):
                print(f"      Phone Health URL: http://{ip}:{http_port}/health")
    else:
        print("  [FAIL] No private LAN IPv4 detected. Ensure Wi-Fi/Ethernet is connected.")
    print("=" * 76)
    print()


def verify_startup_listeners(http_port: int, ws_port: int, adapters: List[Dict[str, Any]]):
    """
    Runs asynchronous checks after server starts to confirm port listening status.
    TASK 1a: HTTP port is LISTENING on 0.0.0.0.
    TASK 1b: WS port 7891 is LISTENING on 0.0.0.0 (or reports bind failure / fallback).
    Relabels local test as local bind test.
    """
    time.sleep(1.2)  # Allow uvicorn and standalone WS thread to initialize

    # Check 1a: HTTP Port Listening
    http_bound = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            s.connect(("127.0.0.1", http_port))
            http_bound = True
    except Exception:
        http_bound = False

    if http_bound:
        print(f"[STARTUP CHECK] [PASS] HTTP server is LISTENING on 0.0.0.0:{http_port}")
    else:
        print(f"[STARTUP CHECK] [FAIL] HTTP server is NOT listening on 0.0.0.0:{http_port}!")

    # Check 1b: WS Port Listening & Fallback Reporting
    if ws_port != http_port:
        if diagnostics_service.ws_port_bound:
            print(f"[STARTUP CHECK] [PASS] Dedicated WebSocket server is LISTENING on ws://0.0.0.0:{ws_port}/ws")
        else:
            err = diagnostics_service.ws_bind_error or "Bind failed"
            print(f"[STARTUP CHECK] [FAIL] WebSocket port {ws_port} failed to bind ({err}).")
            print(f"                       FALLBACK ACTIVE: Serving WebSocket on ws://0.0.0.0:{http_port}/ws")
    else:
        print(f"[STARTUP CHECK] [PASS] Unified WebSocket server is LISTENING on ws://0.0.0.0:{http_port}/ws")

    # Local bind test (relabeled truthfully - does NOT prove phone reachability)
    if adapters:
        primary_ip = adapters[0]["ip"]
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                s.connect((primary_ip, http_port))
            print(f"[STARTUP CHECK] [PASS] Local bind test verified on http://{primary_ip}:{http_port}")
            print(f"                       (Note: Windows loopback bypasses firewall; verify firewall status above)")
        except Exception as e:
            print(f"[STARTUP CHECK] [FAIL] Local bind test failed on http://{primary_ip}:{http_port}: {e}")
    print()


def main():
    adapters = diagnostics_service.get_detailed_lan_adapters()
    pin = pairing_manager.get_pin_status()["code"]

    # Print truthful startup checks banner (Tasks 1c, 1d)
    print_startup_diagnostics(adapters, HTTP_PORT, WS_PORT, pin)

    # Launch background listener verification (Tasks 1a, 1b)
    checker_thread = threading.Thread(
        target=verify_startup_listeners,
        args=(HTTP_PORT, WS_PORT, adapters),
        daemon=True,
        name="StartupListenersCheckThread"
    )
    checker_thread.start()

    # Check if HTTP port is already bound by an existing instance
    if is_port_in_use(HTTP_PORT):
        print(f"\n[STARTUP ERROR] Port {HTTP_PORT} is already in use by another running process (likely another terminal running 'run_bridge.py').")
        print("Please close the existing bridge instance or stop the conflicting process before starting a new one.\n")
        sys.exit(1)

    # Launch HTTP server on 0.0.0.0
    try:
        uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, reload=False, log_level="info")
    except (KeyboardInterrupt, SystemExit):
        clean_shutdown_handler()
    except Exception as e:
        print(f"[Error] Bridge server crashed: {e}", file=sys.stderr)
        clean_shutdown_handler()
        sys.exit(1)


if __name__ == "__main__":
    main()
