import json
import time
import logging
from fastapi import WebSocket, WebSocketDisconnect
from backend.services.connection_manager import connection_manager
from backend.services.command_service import CommandService
from backend.protocol.schemas import MessageEnvelope

logger = logging.getLogger("ws_routes")

async def handle_websocket_connection(websocket: WebSocket, client_type_hint: str = "unknown"):
    """
    Handles a full-duplex WebSocket connection following the Canonical Windows Bridge Protocol.
    Requires 'authenticate' as the first message before any commands are processed.
    """
    await connection_manager.connect(websocket, client_type=client_type_hint)
    try:
        while True:
            raw_text = await websocket.receive_text()
            
            # Envelope validation
            try:
                msg_dict = json.loads(raw_text)
                if not isinstance(msg_dict, dict):
                    raise ValueError("Envelope must be a JSON object")
            except Exception as e:
                logger.warning(f"Malformed WebSocket envelope received: {e}")
                error_response = {
                    "type": "error",
                    "error": "MALFORMED_ENVELOPE",
                    "message": "Malformed message envelope. Expected a valid JSON object."
                }
                await websocket.send_text(json.dumps(error_response))
                continue

            msg_type = msg_dict.get("type")
            
            # 1. Authentication Handshake
            if msg_type == "authenticate":
                token = msg_dict.get("token") or (msg_dict.get("data") or {}).get("token")
                version = msg_dict.get("protocol_version") or msg_dict.get("version") or "1.0"
                
                auth_result = connection_manager.authenticate_connection(
                    websocket=websocket,
                    token=token,
                    version=version
                )
                await websocket.send_text(json.dumps(auth_result))
                
                # If authentication succeeded, broadcast updated client count to desktop UI
                if auth_result.get("success"):
                    await connection_manager.broadcast({
                        "type": "status_update",
                        "connected_clients": connection_manager.get_authenticated_phone_count(),
                        "devices": connection_manager.get_authenticated_devices()
                    }, exclude=websocket)
                continue

            # 2. Command Processing
            if msg_type == "command":
                request_id = msg_dict.get("request_id") or f"cmd-{int(time.time()*1000)}"
                
                # Strict authentication guard
                if not connection_manager.is_authenticated(websocket):
                    logger.warning(f"[WebSocket] REJECTED command from unauthenticated client: request_id={request_id}")
                    rejection = {
                        "type": "command_result",
                        "request_id": request_id,
                        "protocol_version": "1.0",
                        "timestamp": int(time.time() * 1000),
                        "success": False,
                        "data": {
                            "status": "failed",
                            "action": {"action": "unauthorized"},
                            "message": "UNAUTHORIZED: WebSocket client must authenticate before sending commands.",
                            "execution_time_ms": 0,
                            "error": "UNAUTHORIZED"
                        }
                    }
                    await websocket.send_text(json.dumps(rejection))
                    continue

                # Process authenticated command with client context
                data_dict = msg_dict.get("data") or {}
                cmd_text = data_dict.get("command") or ""
                client_info = connection_manager.connections.get(websocket, {})
                client_type = client_info.get("client_type", "desktop")

                result = CommandService.process(cmd_text, client_context=client_type)

                response = {
                    "type": "command_result",
                    "request_id": request_id,
                    "protocol_version": "1.0",
                    "timestamp": int(time.time() * 1000),
                    "success": result["status"] == "completed",
                    "target_device": result.get("target_device", "computer"),
                    "data": result
                }

                # Respond to sender
                await websocket.send_text(json.dumps(response))

                # Broadcast command execution to other connected clients (e.g. desktop UI)
                # so desktop opens the app window and updates Nova voice transcript in real-time
                await connection_manager.broadcast(response, exclude=websocket)
                continue

            # 3. Ping / Pong
            if msg_type == "ping":
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "timestamp": int(time.time() * 1000)
                }))
                continue

            # 4. Unknown message type fallback
            error_response = {
                "type": "error",
                "error": "UNKNOWN_MESSAGE_TYPE",
                "message": f"Unsupported message type: '{msg_type}'"
            }
            await websocket.send_text(json.dumps(error_response))

    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
        # Notify remaining desktop clients of updated connection count
        try:
            await connection_manager.broadcast({
                "type": "status_update",
                "connected_clients": connection_manager.get_authenticated_phone_count(),
                "devices": connection_manager.get_authenticated_devices()
            })
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket loop: {e}", exc_info=True)
        connection_manager.disconnect(websocket)
