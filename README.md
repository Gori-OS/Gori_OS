# Nova OS — Windows AI Bridge

Production Windows-side bridge server (FastAPI) and browser-based desktop environment (**Nova OS**) for remote AI automation, voice/text command execution, and streaming media uploads from the companion **Windows Remote** Flutter client.

---

## Architecture Overview

```
                      +---------------------------------------+
                      |   Flutter Android ("Windows Remote")  |
                      +-------------------+-------------------+
                                          |
                   mDNS (_winbridge._tcp) | Host IP (7890 HTTP / 7891 WS)
                                          v
+----------------------------------------------------------------------------------+
| Windows Machine ("Ai_voice")                                                     |
|                                                                                  |
|   +------------------------------------+   +---------------------------------+   |
|   | HTTP Server (Port 7890)            |   | Dedicated WebSocket (Port 7891) |   |
|   | - POST /pair                       |   | - /ws                           |   |
|   | - POST /upload/file (Bearer auth)  |   |   * Authenticate handshake      |   |
|   | - POST /upload/photo (Bearer auth) |   |   * Real-time command router    |   |
|   | - GET  /files (Live folder tree)   |   |   * Action dispatch             |   |
|   | - GET  /desktop (Nova OS UI)       |   | - (Port 7890 /ws dual-fallback) |   |
|   +-----------------+------------------+   +----------------+----------------+   |
|                     |                                       |                    |
|                     |              +------------------------+                    |
|                     v              v                                             |
|   +--------------------------------------------------------------------------+   |
|   | Nova OS Web Desktop (/desktop)                                           |   |
|   | - Nova Voice Orb Agent (Live Phone Command Transcript)                   |   |
|   | - Interactive Terminal                                                   |   |
|   | - Files Manager (Real Folder Tree: Mobile / Photos)                      |   |
|   | - Text Editor & System Settings                                          |   |
|   | - Persistent 6-Digit Pairing PIN Widget                                  |   |
|   +--------------------------------------------------------------------------+   |
|                                                                                  |
|   Uploads Directory Structure:                                                   |
|     Ai_voice/uploads/files/                                                      |
|     ├── mobile/                                                                  |
|     │   ├── <uploaded-documents-and-files>                                       |
|     │   └── photos/                                                              |
|     │       └── <uploaded-photos>                                                |
|     └── output/                                                                  |
|         └── <voice-processed-results-and-conversions>                            |
+----------------------------------------------------------------------------------+
```

---

## Ports & Protocols (Agreed Canonical Truth)

| Service | Port | Path | Description |
| :--- | :--- | :--- | :--- |
| **HTTP API & Desktop** | **`7890`** | `/pair`, `/upload/*`, `/files`, `/desktop` | Primary HTTP server and Web UI |
| **Dedicated WebSocket**| **`7891`** | `/ws` | Dedicated full-duplex WebSocket for Flutter phone app |
| **WebSocket Fallback** | **`7890`** | `/ws` | Dual-port fallback if phone connects WS on port 7890 |
| **mDNS / Zeroconf**   | **`7890`** | Service: `_winbridge._tcp.local.` | Auto-discovery for Flutter app |

---

## Quickstart: Running the Bridge Server

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Required packages: `fastapi`, `uvicorn`, `websockets`, `pydantic`, `python-multipart`, `zeroconf`, `httpx`, `assemblyai`, `python-dotenv`.

### 2. Configure AssemblyAI Voice Streaming (Optional but Recommended)

Copy the `.env.example` file to `.env` in the repository root and add your AssemblyAI API key:

```bash
cp .env.example .env
```

Edit `.env`:
```env
ASSEMBLYAI_API_KEY=your_assemblyai_api_key_here
```

### 3. Start the Server

From the project root:

```bash
python run_bridge.py
```

*(Or on Windows, simply double-click `start_bridge.bat` to automatically verify firewall rules and launch the bridge.)*

The bridge server will automatically:
1. Bind HTTP endpoints (including `/pair`, `/upload/*`, `/files`, `/token`, and `/desktop`) to **port 7890**.
2. Launch the dedicated WebSocket server on **port 7891** at path `/ws`.
3. Register mDNS / Zeroconf service `_winbridge._tcp.local.` on port 7890 broadcasting machine hostname and ports.
4. Generate an active 6-digit pairing PIN with a 5-minute rolling TTL.

### 4. Open the Nova OS Desktop

Open your browser to:
```
http://localhost:7890/desktop
```

---

## Voice (AssemblyAI Streaming)

Nova Voice features real-time speech-to-text using AssemblyAI's streaming WebSocket v3 (`universal-3-6-pro`). Users can click the Nova Orb or microphone button, speak natural language commands, watch real-time transcription appear, and have finalized text dispatched directly through the Nova OS Command Service.

### 1. Setup & API Key Configuration

1. Get an API key from [AssemblyAI](https://www.assemblyai.com/).
2. Copy `.env.example` to `.env` in the project root:
   ```bash
   cp .env.example .env
   ```
3. Set your key:
   ```env
   ASSEMBLYAI_API_KEY=your_api_key_here
   ```
4. **Security**: `.env` is listed in `.gitignore`. The master API key remains solely on the server and is never exposed to browser clients, JavaScript, HTML, network logs, or error responses.

### 2. Architecture & Streaming Flow

```
[Browser: http://localhost:7890/desktop]
       |
       |  1. Click Nova Orb / Mic 🎙
       |  2. GET /token (Bridge Server validates loopback or pairing bearer token)
       v
[FastAPI Bridge Server]
       |
       |  3. Calls RealTimeTranscriber(api_key=...).create_temporary_token(60s)
       |  4. Returns single-use temp token with Cache-Control: no-store
       v
[Browser SpeechService]
       |
       |  5. Requests getUserMedia (16 kHz mono audio)
       |  6. Opens wss://streaming.assemblyai.com/v3/ws?token=...&speech_model=universal-3-6-pro
       |  7. Streams PCM 16-bit binary audio frames
       v
[AssemblyAI Streaming v3]
       |
       |  8. Emits 'Turn' messages (end_of_turn: false -> onPartial live updates)
       |  9. Emits 'Turn' message  (end_of_turn: true  -> onFinal completed transcript)
       v
[Nova Voice UI]
       |
       | 10. Sends { type: "Terminate" }, awaits 'Termination' message, stops mic
       | 11. Hands final text to window.BridgeClient.sendCommand(text)
       v
[CommandService]
       |
       | 12. Normalizes text (strips filler words/articles) & dispatches action
       v
[Nova OS Window Manager] (e.g. opens Terminal, Files, Settings, takes screenshot)
```

### 3. Speech-Friendly Command Normalisation

Voice commands are handled gracefully by `CommandService.process`:
- Strips leading filler words (`please`, `can you`, `could you`, `hey nova`).
- Strips leading articles (`the`, `my`).
- Examples:
  - `"Please open the terminal."` -> Opens Terminal (`app.open / terminal`)
  - `"Hey Nova, can you open my files?"` -> Opens Files (`app.open / files`)
  - Existing typed commands (`open terminal`, `help`, `status`, `take screenshot`) remain 100% backwards compatible.

### 4. Troubleshooting

- **HTTP 500 on `/token`**:
  `ASSEMBLYAI_API_KEY` is missing. Create `.env` in the root folder containing `run_bridge.py` and populate `ASSEMBLYAI_API_KEY`.
- **HTTP 502 on `/token`**:
  Server failed to contact AssemblyAI to create a streaming token. Verify internet connectivity and ensure your AssemblyAI account is active.
- **HTTP 403 on `/token`**:
  The request came from a non-loopback network IP without a valid mobile pairing session token. Only `localhost` / `127.0.0.1` or paired devices with a valid Bearer token can mint tokens.
- **"Microphone access blocked: Browsers require a secure context"**:
  Modern browsers enforce that `getUserMedia` is only available on `http://localhost` or HTTPS. Accessing the desktop from another LAN machine via raw HTTP (`http://192.168.x.x:7890/desktop`) will block microphone access. Access via `http://localhost:7890/desktop` on the host machine.
- **Mic Permission Denied**:
  If prompted, grant microphone permission in your browser for `http://localhost:7890`.


## Where the Pairing PIN is Displayed

1. **Persistent Desktop Pairing Widget (Top-Right)**:
   A dedicated glassmorphic card prominently displays the current 6-digit PIN (e.g. `842 109`), the countdown timer (`Expires in: 04:32`), a `↻ REFRESH PIN` button, and live phone connection status.
2. **System Tray Pill (Taskbar Right)**:
   Displays `PIN: 842109`. Clicking it opens the **Settings** window.
3. **Settings Application (`settings`)**:
   Shows pairing security details, full bridge telemetry, and the live list of authenticated devices.

---

## Canonical Protocol Specification

### 1. Device Pairing (`POST /pair`)
- **Port**: `7890` (HTTP)
- **Path**: `/pair`
- **Headers**:
  ```http
  Content-Type: application/json
  X-Protocol-Version: 1.0
  ```
- **Request Body**:
  ```json
  {
    "code": "842109",
    "protocolVersion": "1.0"
  }
  ```
- **Success Response (200 OK)**:
  ```json
  {
    "success": true,
    "deviceId": "win-hostname",
    "sessionToken": "win_sec_d83e29f...",
    "refreshToken": null,
    "expiresAt": "2026-10-28T00:00:00Z",
    "errorMessage": null,
    "protocolVersion": "1.0"
  }
  ```
- **Failure Response (200 OK with error)**:
  ```json
  {
    "success": false,
    "deviceId": "",
    "sessionToken": null,
    "refreshToken": null,
    "expiresAt": null,
    "errorMessage": "INVALID_PAIRING_CODE: Incorrect 6-digit pairing code.",
    "protocolVersion": "1.0"
  }
  ```

---

### 2. Full-Duplex WebSocket (`/ws`)
- **Port**: `7891` (or `7890` dual-fallback)
- **Path**: `/ws`

#### Step A: Authentication Handshake (Mandatory 1st Message)
- **Client Frame**:
  ```json
  {
    "type": "authenticate",
    "token": "win_sec_d83e29f...",
    "protocol_version": "1.0"
  }
  ```
- **Server Response**:
  ```json
  {
    "type": "auth_result",
    "success": true,
    "device_id": "win-hostname",
    "version": "1.0",
    "error": null
  }
  ```
*Unauthenticated connections sending `command` frames are immediately rejected with `UNAUTHORIZED`.*

#### Step B: Command Execution
- **Client Frame**:
  ```json
  {
    "type": "command",
    "request_id": "cmd-1790535-a1b2",
    "timestamp": 1790535000000,
    "data": {
      "command": "open terminal",
      "type": "text"
    }
  }
  ```
- **Server Response**:
  ```json
  {
    "type": "command_result",
    "request_id": "cmd-1790535-a1b2",
    "protocol_version": "1.0",
    "timestamp": 1790535000015,
    "success": true,
    "data": {
      "status": "completed",
      "action": {
        "action": "app.open",
        "target": "terminal"
      },
      "message": "Opened Terminal",
      "execution_time_ms": 2,
      "error": null
    }
  }
  ```
*When a phone sends an app-opening command, the bridge broadcasts the command result to the Nova OS desktop browser so the window opens live on screen!*

#### Step C: Supported Commands
| Command | Resulting Action | Behavior |
| :--- | :--- | :--- |
| `open nova voice` / `voice` | `{"action": "app.open", "target": "nova-voice"}` | Opens Nova Voice agent |
| `open files` / `files` | `{"action": "app.open", "target": "files"}` | Opens File Manager |
| `open terminal` / `terminal` | `{"action": "app.open", "target": "terminal"}` | Opens Terminal |
| `open editor` / `editor` | `{"action": "app.open", "target": "editor"}` | Opens Text Editor |
| `open settings` / `settings` | `{"action": "app.open", "target": "settings"}` | Opens Settings |
| `open workspace` / `workspace` | `{"action": "app.open", "target": "workspace"}` | Opens Workspace |
| `close nova voice` | `{"action": "app.close", "target": "nova-voice"}` | Closes Nova Voice agent |
| `close files` | `{"action": "app.close", "target": "files"}` | Closes File Manager |
| `close terminal` | `{"action": "app.close", "target": "terminal"}` | Closes Terminal |
| `close editor` | `{"action": "app.close", "target": "editor"}` | Closes Text Editor |
| `close settings` | `{"action": "app.close", "target": "settings"}` | Closes Settings |
| `close workspace` | `{"action": "app.close", "target": "workspace"}` | Closes Workspace |
| `take screenshot` / `screenshot` | `{"action": "system.screenshot"}` | Triggers screenshot flash & stub |
| `status` / `ping` | `{"action": "system.status"}` | Returns bridge system health |
| `help` | `{"action": "system.help"}` | Lists supported commands |
| *unrecognized* | `{"action": "unknown", "status": "failed"}` | Graceful fallback (never crashes) |

---

### 3. Voice-Controlled File Processing with Groq Intent Understanding & 38-Endpoint Registry

Nova OS integrates **Groq-powered intent understanding** with a strict 38-endpoint task registry and robust speech-to-text filename normalization for utility file processing.

> [!IMPORTANT]
> **Strict Command Routing Boundary:** Groq is **ONLY** invoked for task/endpoint commands. Existing `open`, `close`, and system commands (`screenshot`, `status`, `help`) are parsed deterministically and are **NEVER** routed through Groq.
> **No Invented Endpoints:** Every task is resolved strictly to one of the 38 endpoints in the registry. If no matching endpoint exists, a clear `"No endpoint available for this task"` error is returned without making an HTTP request.
> **Authoritative Filenames:** Spoken filenames are normalized and matched case-insensitively against actual web app storage. If matched, the actual disk filename is authoritative and used for upload. If not found, a clear `"File not found"` error is returned without making an HTTP request.

#### Available Task Endpoints Registry (38 Endpoints on `http://127.0.0.1:8000`)
- **IMAGE**:
  - `POST /jpg-to-png`, `POST /png-to-jpg`, `POST /webp-to-jpg`, `POST /jpg-to-webp`, `POST /png-to-webp`
  - `POST /bmp-to-jpg`, `POST /bmp-to-png`, `POST /tiff-to-jpg`, `POST /tiff-to-png`, `POST /heic-to-jpg`, `POST /heic-to-png`
  - `POST /compress-image`, `POST /add-watermark`
- **PDF**:
  - `POST /extract-images-from-pdf`, `POST /merge-pdfs`, `POST /split-pdf`, `POST /delete-pdf-pages`
  - `POST /pdf-to-jpg`, `POST /pdf-to-png`, `POST /jpg-to-pdf`, `POST /png-to-pdf`, `POST /images-to-pdf`, `POST /compress-pdf`
- **VIDEO**:
  - `POST /compress-video`, `POST /video-to-gif`, `POST /gif-to-mp4`, `POST /add-audio-to-video`, `POST /replace-video-audio`
- **AUDIO**:
  - `POST /mp4-to-mp3`, `POST /mp4-to-wav`, `POST /wav-to-mp3`, `POST /mp3-to-wav`, `POST /m4a-to-mp3`, `POST /compress-audio`
- **DATA**:
  - `POST /json-to-csv`, `POST /csv-to-json`, `POST /csv-to-excel`, `POST /excel-to-csv`

#### Speech-to-Text Normalization Rules
Speech-to-text engines may transcribe filenames with "dot" or spelled-out letters. Nova OS normalizes these before matching:
- `"dot"`, `"point"`, `"period"` $\rightarrow$ `"."`
- `"P N G"` $\rightarrow$ `"png"`, `"P D F"` $\rightarrow$ `"pdf"`, `"J P G"` $\rightarrow$ `"jpg"`, `"J P E G"` $\rightarrow$ `"jpeg"`
- `"W E B P"` $\rightarrow$ `"webp"`, `"M P 4"` $\rightarrow$ `"mp4"`, `"M P 3"` $\rightarrow$ `"mp3"`, `"W A V"` $\rightarrow$ `"wav"`
- `"C S V"` $\rightarrow$ `"csv"`, `"J S O N"` $\rightarrow$ `"json"`, `"X L S X"` $\rightarrow$ `"xlsx"`
- Full support for spaces, numbers, hyphens, underscores, and multiple dots (`my photo.jpg`, `report final.pdf`, `archive.tar.gz`).

#### Examples & Endpoints
| Spoken Natural Command | Normalized File & Authoritative Match | Resolved Endpoint | Result Saved in Output |
| :--- | :--- | :--- | :--- |
| `"convert intern21 dot pdf to png"` | `Intern21.pdf` (authoritative) | `POST /pdf-to-png` | `uploads/files/output/Intern21.png` |
| `"convert image dot png to jpg"` | `image.png` | `POST /png-to-jpg` | `uploads/files/output/image.jpg` |
| `"convert my photo dot jpg to webp"` | `my photo.jpg` | `POST /jpg-to-webp` | `uploads/files/output/my photo.webp` |
| `"convert report final dot pdf to jpg"` | `report final.pdf` | `POST /pdf-to-jpg` | `uploads/files/output/report final.jpg` |
| `"convert test dot P N G to J P G"` | `test.png` | `POST /png-to-jpg` | `uploads/files/output/test.jpg` |
| `"turn image.jpg into pdf"` | `image.jpg` | `POST /jpg-to-pdf` | `uploads/files/output/image.pdf` |
| `"convert video.mp4 to gif"` | `video.mp4` | `POST /video-to-gif` | `uploads/files/output/video.gif` |
| `"convert song.mp4 to mp3"` | `song.mp4` | `POST /mp4-to-mp3` | `uploads/files/output/song.mp3` |
| `"convert data.csv to excel"` | `data.csv` | `POST /csv-to-excel` | `uploads/files/output/data.xlsx` |
| `"compress this video"` | `video.mp4` (contextual) | `POST /compress-video` | `uploads/files/output/video_compressed.mp4` |
| `"split this pdf"` | `Intern21.pdf` / `file.pdf` | `POST /split-pdf` | `uploads/files/output/Intern21_split.zip` |
| `"merge file.pdf and Intern21.pdf to pdf"` | `file.pdf`, `Intern21.pdf` | `POST /merge-pdfs` | `uploads/files/output/merged.pdf` |

#### Groq Structured JSON Schema
Groq returns structured JSON strictly adhering to the schema:
```json
{
  "intent": "convert",
  "endpoint": "/pdf-to-png",
  "input_files": ["Intern21.pdf"],
  "parameters": {}
}
```

#### Task Resolution Lifecycle (11-Step Pipeline)
1. **Receive Voice Command**: Transcribed speech received from voice companion.
2. **Normalize Spoken Patterns**: Normalizes `"dot"`, `"point"`, `"P N G"`, `"J P G"`, etc.
3. **Send Registry to Groq**: Sends the 38-endpoint registry with available files to Groq.
4. **Identify Operation & Files**: Groq identifies intent, input files, target format, and parameters.
5. **Authoritative Storage Resolution**: Matches normalized filenames case-insensitively against actual web app files.
6. **Validate Endpoint**: Validates the selected endpoint strictly against the 38-endpoint registry (never invents endpoints).
7. **Pre-flight Error Checks**: If file is not found $\rightarrow$ returns `"File not found"` without backend call. If no endpoint exists $\rightarrow$ returns `"No endpoint available for this task"` without backend call.
8. **Multipart Upload**: Sends file(s) to `http://127.0.0.1:8000` using exact method, field names, and parameters.
9. **Stream & Receive**: Receives the processed file from the backend service.
10. **Save to Output**: Saves result into `uploads/files/output/` preserving correct filename and extension.
11. **UI Auto-Refresh & Feedback**: Dispatches `file.processed` WebSocket event to Nova OS desktop; Files app instantly refreshes and navigates to the Output folder.

---

### 3. Authenticated Streamed Uploads (`files/mobile/`)

#### File Upload (`POST /upload/file`)
- **Headers**: `Authorization: Bearer <sessionToken>`, `X-Protocol-Version: 1.0`
- **Body**: `multipart/form-data` with field `file`
- **Destination**: `Ai_voice/uploads/files/mobile/<filename>` (streamed chunk-by-chunk to disk without RAM buffering)
- **Response**: `{"success": true, "filename": "doc.pdf", "size": 128420, "path": "/uploads/files/mobile/doc.pdf"}`

#### Photo Upload (`POST /upload/photo`)
- **Headers**: `Authorization: Bearer <sessionToken>`, `X-Protocol-Version: 1.0`
- **Body**: `multipart/form-data` with field `photo`
- **Destination**: `Ai_voice/uploads/files/mobile/photos/<filename>`
- **Response**: `{"success": true, "filename": "photo.jpg", "size": 512000, "path": "/uploads/files/mobile/photos/photo.jpg"}`

*Unauthenticated requests without a valid Bearer token return `HTTP 401 Unauthorized`.*

---

### 4. Files List API (`GET /files`)
- **URL**: `http://<host>:7890/files`
- **Response**:
  ```json
  {
    "files": [
      {
        "name": "hello_bridge.txt",
        "size": 19,
        "size_formatted": "19 B",
        "type": "file",
        "path": "/uploads/files/mobile/hello_bridge.txt",
        "modified": "2026-09-28 01:49:22"
      },
      {
        "name": "camera_snap.jpg",
        "size": 12,
        "size_formatted": "12 B",
        "type": "photo",
        "path": "/uploads/files/mobile/photos/camera_snap.jpg",
        "modified": "2026-09-28 01:49:22"
      }
    ],
    "total": 2
  }
  ```

---

## Nova OS "Files" Desktop Application

The built-in **Files** app (`frontend/js/window_manager.js`, `helpers.js`) renders a live, interactive folder tree:
- **Top-level `Mobile` folder** (`/files/mobile`): Displays documents received from the phone alongside a nested **`photos/`** folder.
- **Nested `Photos` folder** (`/files/mobile/photos`): Opening the `photos/` folder drills into the photos directory with full parent directory navigation (`.. (Parent Folder)`).
- **Interactive Breadcrumb Navigation**: Click any breadcrumb segment (`files / mobile / photos`) to instantly jump up or down the directory hierarchy.
- **Live Sync**: Counts and file entries update dynamically from `GET /files`.

---

## End-to-End Manual Verification Procedure

Follow this test procedure to verify the entire system with a real mobile device:

1. **Boot the Bridge Server**:
   ```bash
   cd Ai_voice
   python run_bridge.py
   ```
2. **Open Nova OS Desktop**:
   Open a browser to `http://localhost:7890/desktop`.
3. **Confirm Pairing PIN**:
   - Check the top-right widget: verify a live 6-digit code (e.g. `458 129`) is shown with a rolling countdown timer.
4. **Connect from Phone**:
   - Ensure the phone and PC are on the same Wi-Fi network.
   - Open the **Windows Remote** Flutter app.
   - The app will automatically discover the PC via mDNS (`_winbridge._tcp`). Alternatively, tap **Connect manually** and enter the PC's LAN IP with HTTP port `7890` / WS port `7891`.
   - When prompted, enter the 6-digit PIN shown on the Nova OS desktop.
   - Tap **Pair**. Confirm pairing succeeds and issues a secure session token.
5. **Test Remote Command Execution**:
   - On the phone, speak or type `open terminal` or `open files`.
   - In Nova OS, observe the corresponding window pop up on screen immediately, and watch the Nova Voice transcript record the event in real-time.
6. **Test Remote Uploads**:
   - Upload a document from the phone: confirm it lands in `Ai_voice/uploads/files/mobile/`.
   - Upload a photo from the phone: confirm it lands in `Ai_voice/uploads/files/mobile/photos/`.
   - Open the **Files** app in Nova OS: open the `Mobile` folder to see the file and double-click `photos` to view the uploaded photo.

---

## Automated Test Suites

```bash
# Run unit tests (health, diagnostics, clientId re-pair, expired session pruning, PIN auth, uploads, WebSocket)
venv\Scripts\python -m unittest Ai_voice/backend/tests/test_bridge.py
```

---

## Troubleshooting: "Can't reach your PC" & Reachability Diagnostics

If the companion phone app fails with **"Can't reach your PC"** or `POST http://<pc-ip>:7890/pair` times out (errno 110):

### 1. How to Read the New Diagnostics Panel (Desktop & Settings)
The bridge provides real-time visibility into whether phone packets are reaching your computer:

* **Desktop PIN Panel Widget** (top-right of Nova OS desktop):
  - **Green banner (`Last phone contact: 192.168.0.42 GET /health 200 (3s ago)`)**: Packets from the phone are successfully reaching your PC over Wi-Fi.
  - **Yellow warning (`No phone has reached this PC yet. Check Wi-Fi, firewall and router isolation`)**: Zero network packets from any non-loopback device have reached the bridge. Inbound traffic is blocked at the network, router, or firewall layer.
  - **Port status badge**: Shows whether HTTP 7890 is listening, whether dedicated WS 7891 is bound or using fallback, and whether active profile firewall rules pass.

* **Settings App (`⚙ Settings` on desktop or taskbar)**:
  - **Network Reachability & Phone Contact**: Shows the exact last phone contact timestamp, method, path, and status code.
  - **Active Profile Firewall Status**: Shows `PASS` if Windows Defender Firewall has inbound rules enabled for your **active** network profile (`Public` or `Private`). If `BLOCKED`, it prints the exact command to run.
  - **LAN IP Addresses & Adapters**: Lists all detected network interfaces with adapter names. Identifies `[RECOMMENDED FOR PHONE]` (physical Wi-Fi/Ethernet) vs `[VIRTUAL ADAPTER / VPN]` (VirtualBox, Hyper-V, VMware, WSL, Tailscale) so you know which IP to enter on the phone.
  - **Paired Devices Management**: Lists all actively paired mobile devices (Device ID / Client ID, paired timestamp, last seen timestamp) with a **Revoke** button to instantly invalidate unauthorized or stale sessions.

---

### 2. Phone Browser Test of `/health` (Key Test)
Before troubleshooting complex pairing issues, verify basic HTTP reachability:
1. On your mobile phone, open **Safari** (iOS) or **Chrome** (Android).
2. Navigate to:
   ```
   http://<pc-lan-ip>:7890/health
   ```
   *(Replace `<pc-lan-ip>` with the recommended IP displayed on the bridge startup banner, e.g. `http://192.168.0.200:7890/health`)*.
3. **Expected result**: The browser immediately returns a JSON response:
   ```json
   {
     "status": "ok",
     "protocol_version": "1.0",
     "http_port": 7890,
     "ws_port": 7891,
     "ws_port_bound": true,
     "ws_urls": ["ws://192.168.0.200:7891/ws", "ws://192.168.0.200:7890/ws"],
     "lan_ips": ["192.168.0.200"]
   }
   ```
   *Within 4 seconds of opening this URL, the Nova OS desktop widget will turn green and display: `Last phone contact: <phone-ip> GET /health 200 (1s ago)`.*
4. **If the phone browser spins and times out**: The phone cannot reach your PC's IP. Follow steps 3–6 below.

---

### 3. Verify Listening Ports with Netstat
Confirm that both HTTP and WebSocket servers are listening on `0.0.0.0` (all network adapters), not just `127.0.0.1`:
Open Command Prompt or PowerShell on the PC and run:
```cmd
netstat -ano | findstr "7890 7891"
```
You should see:
```text
  TCP    0.0.0.0:7890           0.0.0.0:0              LISTENING        <PID>
  TCP    0.0.0.0:7891           0.0.0.0:0              LISTENING        <PID>
```
If port 7891 is in use by another application, the bridge automatically retries once and falls back to serving `/ws` on port 7890, ensuring the phone client can still connect via the fallback URL in `/health`.

---

### 4. Windows Defender Firewall (Active Profile)
Windows Firewall often classifies home Wi-Fi networks as `Public`, which silently blocks all inbound connections by default. The local bind test cannot detect this because Windows bypasses firewall filtering for connections originating on the local machine.

To allow inbound connections on all profiles (Public, Private, Domain):
1. Right-click PowerShell and select **Run as Administrator**.
2. Run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/allow_firewall.ps1
   ```
   *(Or simply run `start_bridge.bat`, which requests elevation and applies this automatically before launch).*

---

### 5. Third-Party Antivirus & Security Suites
If you have third-party antivirus software installed (e.g. Norton 360, McAfee LiveSafe, Bitdefender, ESET Smart Security, Kaspersky, Avast, AVG):
- Third-party suites install their own proprietary network packet filters that completely override Windows Defender Firewall rules.
- Even if Windows Defender allows port 7890, the third-party firewall will drop inbound packets from the phone.
- **Fix**: Open your antivirus control center -> **Firewall** / **Network Protection** -> add inbound rules allowing TCP `7890`, TCP `7891`, and UDP `5353`, or set your local Wi-Fi connection profile to **"Home / Trusted Network"**.

---

### 6. Router Client Isolation (AP Isolation)
- Many modern Wi-Fi routers (especially guest networks, mesh repeaters, or ISP-provided routers) have **"AP Isolation"**, **"Client Isolation"**, or **"Guest Network Isolation"** enabled by default.
- This security feature deliberately blocks Wi-Fi devices from sending packets to each other, preventing phones from reaching PCs on the same Wi-Fi.
- **Fix**:
  1. Ensure both PC and phone are connected to your primary home Wi-Fi, NOT a Guest SSID.
  2. If using separate 2.4GHz and 5GHz SSIDs, connect both devices to the same frequency band or ensure SSID bridging is enabled.
  3. Log into your router's web admin (usually `http://192.168.1.1` or `http://192.168.0.1`), go to Wireless Settings / Advanced, and verify **"AP Isolation" / "Station Isolation"** is **Disabled**.

