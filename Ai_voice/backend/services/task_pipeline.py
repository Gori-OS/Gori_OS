import os
import re
import json
import logging
import mimetypes
from typing import Dict, Any, Optional, List, Tuple, Set
import httpx
from dotenv import load_dotenv

# Ensure .env is loaded
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv()
from backend.services.filename_normalizer import normalize_file_command

logger = logging.getLogger("nova_bridge.task_pipeline")

# Base directory paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "endpoints.json")
FILES_DIR = os.path.join(BASE_DIR, "uploads", "files")
MOBILE_DIR = os.path.join(FILES_DIR, "mobile")
PHOTOS_DIR = os.path.join(MOBILE_DIR, "photos")
OUTPUT_DIR = os.path.join(FILES_DIR, "output")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MOBILE_DIR, exist_ok=True)
os.makedirs(PHOTOS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. REGISTRY LOADER: Read endpoints.json once as the SINGLE source of truth
# ---------------------------------------------------------------------------
def _load_registry(config_path: str = CONFIG_PATH) -> Tuple[str, float, List[Dict[str, Any]], Dict[str, Dict[str, Any]], Set[str]]:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    base_url = data.get("base_url", "https://goori-os-backend-endpoints.onrender.com").rstrip("/")
    timeout_sec = float(data.get("timeout_seconds", 30))
    endpoints_list = data.get("endpoints", [])
    registry_by_path = {ep["endpoint"]: ep for ep in endpoints_list}
    valid_endpoints = set(registry_by_path.keys())
    return base_url, timeout_sec, endpoints_list, registry_by_path, valid_endpoints


BASE_URL, TIMEOUT_SECONDS, ENDPOINTS_LIST, REGISTRY_BY_PATH, ALLOWED_REGISTRY_ENDPOINTS = _load_registry()

# Extension and format aliases
FORMAT_ALIASES = {
    "jpeg": ["jpg", "jpeg"],
    "jpg": ["jpg", "jpeg"],
    "tif": ["tif", "tiff"],
    "tiff": ["tif", "tiff"],
    "excel": ["excel", "xlsx", "xls"],
    "xlsx": ["excel", "xlsx", "xls"],
    "xls": ["excel", "xlsx", "xls"],
    "video": ["video", "mp4", "mov", "avi", "mkv", "webm"],
}

def get_format_variants(fmt: str) -> List[str]:
    f = fmt.lower().strip().lstrip(".")
    return FORMAT_ALIASES.get(f, [f])

# Derive compatibility table: (src_ext, dst_ext) -> endpoint
def _build_compatibility_table(endpoints: List[Dict[str, Any]]) -> Dict[Tuple[str, str], str]:
    table: Dict[Tuple[str, str], str] = {}
    for ep in endpoints:
        path = ep["endpoint"]
        # Match conversion endpoints matching ^/([a-zA-Z0-9]+)-to-([a-zA-Z0-9]+)$
        m = re.match(r"^/([a-zA-Z0-9]+)-to-([a-zA-Z0-9]+)$", path)
        if m:
            src_token = m.group(1).lower()
            dst_token = m.group(2).lower()
            src_vars = get_format_variants(src_token)
            dst_vars = get_format_variants(dst_token)
            for s in src_vars:
                for d in dst_vars:
                    table[(s, d)] = path
    return table

CONVERSION_REGISTRY_MAP = _build_compatibility_table(ENDPOINTS_LIST)

# Accepted input extensions for operation endpoints
OPERATION_INPUT_EXTS: Dict[str, Set[str]] = {
    "/compress-image": {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"},
    "/add-watermark": {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"},
    "/extract-images-from-pdf": {"pdf"},
    "/merge-pdfs": {"pdf"},
    "/split-pdf": {"pdf"},
    "/delete-pdf-pages": {"pdf"},
    "/compress-pdf": {"pdf"},
    "/images-to-pdf": {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"},
    "/compress-video": {"mp4", "mov", "avi", "mkv", "webm", "flv"},
    "/video-to-gif": {"mp4", "mov", "avi", "mkv", "webm"},
    "/gif-to-mp4": {"gif"},
    "/add-audio-to-video": {"mp4", "mov", "avi", "mkv", "webm"},
    "/replace-video-audio": {"mp4", "mov", "avi", "mkv", "webm"},
    "/compress-audio": {"mp3", "wav", "m4a", "flac", "aac", "ogg"},
}

# Generate Groq registry doc dynamically
def _generate_groq_registry_doc(endpoints: List[Dict[str, Any]]) -> str:
    categories = ["IMAGE", "PDF", "VIDEO", "AUDIO", "DATA"]
    by_cat: Dict[str, List[str]] = {}
    for ep in endpoints:
        cat = ep.get("category", "OTHER").upper()
        by_cat.setdefault(cat, []).append(ep["endpoint"])

    lines = ["FIXED ENDPOINT REGISTRY:"]
    for cat in categories:
        if cat in by_cat:
            lines.append(cat)
            for ep_path in by_cat[cat]:
                lines.append(ep_path)
            lines.append("")
    return "\n".join(lines).strip()

TASK_ENDPOINT_REGISTRY_DOC = _generate_groq_registry_doc(ENDPOINTS_LIST)

# Task verbs for early task detection
TASK_VERBS = {
    "convert", "change", "transform", "turn",
    "compress", "shrink", "reduce", "optimize",
    "merge", "combine", "split", "resize",
    "extract", "add", "remove", "delete", "watermark"
}

# ---------------------------------------------------------------------------
# 2. SPEECH NORMALIZATION
# ---------------------------------------------------------------------------
def normalize_spoken_filename_patterns(text: str) -> str:
    """
    Normalizes speech-to-text spoken filename patterns using global normalization layer.
    """
    return normalize_file_command(text)


def is_task_command(text: str) -> bool:
    """
    Early task detection: strips filler words, normalizes spoken filenames,
    then returns True if the first verb is in TASK_VERBS.
    """
    if not text or not text.strip():
        return False

    normalized = normalize_spoken_filename_patterns(text.strip())

    # Strip leading filler words / greetings
    cleaned = normalized
    while True:
        stripped = re.sub(
            r'^(please|can\s+you\s+please|could\s+you\s+please|can\s+you|could\s+you|would\s+you|will\s+you|hey\s+nova|hi\s+nova|hello\s+nova|nova)\s*[,:\-]?\s*',
            '',
            cleaned,
            flags=re.IGNORECASE
        ).strip()
        if stripped == cleaned:
            break
        cleaned = stripped

    # Extract first verb
    m = re.match(r'^([a-zA-Z]+)\b', cleaned)
    if not m:
        return False

    first_verb = m.group(1).lower()
    return first_verb in TASK_VERBS


# ---------------------------------------------------------------------------
# 3. FILE MATCHING (Section C)
# ---------------------------------------------------------------------------
def list_available_files() -> List[str]:
    """Returns fresh listing of filenames of all existing stored files."""
    found: List[str] = []
    for d in [MOBILE_DIR, PHOTOS_DIR, OUTPUT_DIR, UPLOAD_DIR]:
        if os.path.exists(d):
            try:
                for item in os.listdir(d):
                    p = os.path.join(d, item)
                    if os.path.isfile(p) and not item.startswith("."):
                        if item not in found:
                            found.append(item)
            except Exception:
                pass
    return found


def find_file_path(filename: str) -> Optional[Dict[str, Any]]:
    """Locates an authoritative file on disk and returns its path and metadata."""
    if not filename:
        return None
    for d in [MOBILE_DIR, PHOTOS_DIR, OUTPUT_DIR, UPLOAD_DIR]:
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return {
                "path": p,
                "filename": filename,
                "size": os.path.getsize(p),
                "dir": d
            }
    # Case-insensitive fallback
    for d in [MOBILE_DIR, PHOTOS_DIR, OUTPUT_DIR, UPLOAD_DIR]:
        if os.path.exists(d):
            for item in os.listdir(d):
                p = os.path.join(d, item)
                if os.path.isfile(p) and item.lower() == filename.lower():
                    return {
                        "path": p,
                        "filename": item,
                        "size": os.path.getsize(p),
                        "dir": d
                    }
    return None


def match_authoritative_files(
    normalized_cmd: str,
    groq_files: List[str],
    available_files: List[str],
    target_format: str = ""
) -> Tuple[List[str], Optional[str], Optional[str]]:
    """
    Matches input files authoritatively without guessing.
    Returns: (matched_filenames, error_code, error_detail)
    """
    resolved: List[str] = []
    explicit_missing: Optional[str] = None

    # 1. Check groq_files candidates
    for raw in groq_files:
        cand = normalize_spoken_filename_patterns(str(raw).strip())
        if not cand:
            continue
        # Exact or case-insensitive match against available_files
        matched = None
        for af in available_files:
            if af.lower() == cand.lower():
                matched = af
                break
        if matched:
            if matched not in resolved:
                resolved.append(matched)
        else:
            if "." in cand:
                explicit_missing = cand

    if explicit_missing and not resolved:
        return [], "FILE_NOT_FOUND", explicit_missing

    # 2. Check normalized command text for explicit filenames with extensions
    # e.g., "convert song.mp4 to mp3" -> "song.mp4"
    if not resolved:
        file_tokens = re.findall(r'\b([a-zA-Z0-9_\.\-]+\.[a-zA-Z0-9]+)\b', normalized_cmd)
        for token in file_tokens:
            token_clean = token.strip(" .,;:'\"")
            # Skip if token is just the target format or common word
            matched = None
            for af in available_files:
                if af.lower() == token_clean.lower():
                    matched = af
                    break
            if matched:
                if matched not in resolved:
                    resolved.append(matched)
            else:
                # User gave an explicit filename that does not exist
                return [], "FILE_NOT_FOUND", token_clean

    if resolved:
        return resolved, None, None

    # 3. Format-only matching ("convert gif to mp4", "convert data to excel", etc.)
    # If the user gives only a format and exactly one stored file has that extension -> use it.
    # If several match -> ask them to say the filename. If none -> File not found.
    format_candidates = []
    # Check if there is a source format token before "to", "into", "as"
    m_fmt = re.search(r'\b(?:convert|change|transform|turn)\s+([a-zA-Z0-9]+)\s+(?:to|into|as)\s+([a-zA-Z0-9]+)\b', normalized_cmd, re.IGNORECASE)
    if m_fmt:
        src_fmt = m_fmt.group(1).lower().strip()
        format_candidates = get_format_variants(src_fmt)
    elif groq_files:
        for gf in groq_files:
            if "." not in gf:
                format_candidates = get_format_variants(gf)
                break

    if format_candidates:
        src_fmt_name = format_candidates[0]
        matching_files = [
            af for af in available_files
            if any(af.lower().endswith("." + ext) for ext in format_candidates)
        ]
        if len(matching_files) == 1:
            return [matching_files[0]], None, None
        elif len(matching_files) > 1:
            return matching_files, "AMBIGUOUS_FILE", src_fmt_name
        else:
            return [], "FILE_NOT_FOUND", f"*.{src_fmt_name}"

    # 4. Check for filename without extension matching a single file on disk
    m_single = re.search(r'\b(?:convert|change|transform|turn|compress|split|watermark|optimize)\s+([a-zA-Z0-9_\-]+)\b', normalized_cmd, re.IGNORECASE)
    if m_single:
        cand_base = m_single.group(1).lower().strip()
        if cand_base not in TASK_VERBS and cand_base not in ("this", "the", "my", "a", "an"):
            matches = [af for af in available_files if os.path.splitext(af)[0].lower() == cand_base]
            if len(matches) == 1:
                return [matches[0]], None, None
            elif len(matches) > 1:
                return matches, "AMBIGUOUS_FILE", cand_base

    return [], "FILE_NOT_FOUND", "requested file"


# ---------------------------------------------------------------------------
# 4. GROQ INTENT PARSER
# ---------------------------------------------------------------------------
def call_groq_intent(command_text: str, available_files: List[str]) -> Optional[Dict[str, Any]]:
    """
    Calls Groq API to extract structured JSON intent:
    {
      "intent": "...",
      "endpoint": "...",
      "input_files": [],
      "output_format": "...",
      "parameters": {}
    }
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or not api_key.strip():
        logger.warning("GROQ_API_KEY is not configured")
        return None

    normalized_command = normalize_spoken_filename_patterns(command_text)
    api_url = "https://api.groq.com/openai/v1/chat/completions"
    models = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]

    system_prompt = (
        "You are a voice task intent understanding engine for Nova OS utility tasks.\n"
        "Your ONLY source for endpoint selection is the following fixed 38-endpoint registry:\n\n"
        f"{TASK_ENDPOINT_REGISTRY_DOC}\n\n"
        f"ACTUAL STORAGE FILES IN WEB APP:\n{json.dumps(available_files)}\n\n"
        "CRITICAL RULES:\n"
        "1. Match the user's complete task against this registry considering:\n"
        "   - requested operation\n"
        "   - input file extension/type\n"
        "   - requested output format\n"
        "   - endpoint name and purpose\n"
        "   - required parameters\n"
        "2. For conversion commands, input and output formats MUST match the endpoint.\n"
        "   Examples:\n"
        '   "convert song.mp4 to mp3" -> /mp4-to-mp3\n'
        '   "convert image.png to jpg" -> /png-to-jpg\n'
        '   "convert photo.jpg to webp" -> /jpg-to-webp\n'
        '   "convert intern21.pdf to png" -> /pdf-to-png\n'
        '   "convert data.csv to excel" -> /csv-to-excel\n'
        '   "convert data.json to csv" -> /json-to-csv\n'
        '   "convert gif to mp4" -> /gif-to-mp4\n'
        "3. Do NOT select an endpoint only because its name is textually similar.\n"
        '   For example: "convert image.png to mp3" MUST NOT select /mp4-to-mp3, /mp3-to-wav, or any incompatible endpoint.\n'
        "4. If no endpoint supports the requested input/output combination or operation (e.g. 'convert image.png to mp3'), return:\n"
        "   {\n"
        '     "intent": "unsupported",\n'
        '     "endpoint": null,\n'
        '     "input_files": [],\n'
        '     "output_format": "...",\n'
        '     "parameters": {}\n'
        "   }\n"
        "5. The endpoint returned MUST exactly match one endpoint in the registry or null. Never invent an endpoint. Never create /convert.\n"
        "6. Return JSON ONLY strictly conforming to this schema:\n"
        "{\n"
        '  "intent": "...",\n'
        '  "endpoint": "...",\n'
        '  "input_files": [],\n'
        '  "output_format": "...",\n'
        '  "parameters": {}\n'
        "}"
    )

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json"
    }

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Voice Command: {command_text}\nNormalized: {normalized_command}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(api_url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
            elif resp.status_code == 429:
                logger.warning(f"Groq model {model} rate limited (HTTP 429), trying next model")
                continue
            else:
                logger.warning(f"Groq model {model} returned HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Groq request failed on {model}: {e}")

    return None


# ---------------------------------------------------------------------------
# 5. DETERMINISTIC FALLBACK RESOLVER
# ---------------------------------------------------------------------------
def resolve_operation_endpoint(operation: str, src_ext: str) -> Optional[str]:
    """Resolves non-conversion operation endpoints deterministically from extension and operation."""
    op = operation.lower().strip()
    ext = src_ext.lower().strip().lstrip(".")

    if op in ("compress", "shrink", "reduce", "optimize"):
        if ext in ("jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"):
            return "/compress-image"
        elif ext == "pdf":
            return "/compress-pdf"
        elif ext in ("mp4", "mov", "avi", "mkv", "webm", "flv"):
            return "/compress-video"
        elif ext in ("mp3", "wav", "m4a", "flac", "aac", "ogg"):
            return "/compress-audio"

    if op in ("split", "split_pdf", "split-pdf"):
        if ext == "pdf":
            return "/split-pdf"

    if op in ("merge", "combine"):
        if ext == "pdf":
            return "/merge-pdfs"
        elif ext in ("jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"):
            return "/images-to-pdf"

    if op in ("delete", "remove"):
        if ext == "pdf":
            return "/delete-pdf-pages"

    if op in ("extract", "extract_images"):
        if ext == "pdf":
            return "/extract-images-from-pdf"

    if op in ("watermark", "add_watermark", "add"):
        if ext in ("jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"):
            return "/add-watermark"

    return None


# ---------------------------------------------------------------------------
# 6. UNIFIED TASK RUNNER: run_task(command_text) -> result dict
# ---------------------------------------------------------------------------
def run_task(command_text: str) -> Dict[str, Any]:
    """
    Stateless unified voice task pipeline:
    TRANSCRIPT -> TASK DETECTION -> GROQ INTENT -> REGISTRY MATCH -> FILE MATCH
               -> VALIDATION -> BACKEND REQUEST (https://goori-os-backend-endpoints.onrender.com) -> OUTPUT FOLDER
    """
    raw_cmd = (command_text or "").strip()
    normalized_cmd = normalize_spoken_filename_patterns(raw_cmd)
    available_files = list_available_files()

    # 1. Groq intent call (if available)
    groq_intent = call_groq_intent(raw_cmd, available_files)

    groq_endpoint = None
    input_files_raw: List[str] = []
    output_format = ""
    parameters: Dict[str, Any] = {}
    intent = ""

    if groq_intent:
        intent = (groq_intent.get("intent") or "").lower().strip()
        groq_endpoint = groq_intent.get("endpoint")
        input_files_raw = groq_intent.get("input_files") or []
        output_format = (groq_intent.get("output_format") or "").lower().strip().lstrip(".")
        parameters = groq_intent.get("parameters") or {}

    # Extract target format from command if not provided
    if not output_format:
        fmt_m = re.search(r'\b(?:to|into|as)\s+([a-zA-Z0-9]+)\b', normalized_cmd, re.IGNORECASE)
        if fmt_m:
            output_format = fmt_m.group(1).lower().strip()

    # Extract operation verb from command
    op_m = re.search(r'\b(convert|change|transform|turn|compress|shrink|reduce|optimize|merge|combine|split|resize|extract|add|remove|delete|watermark)\b', normalized_cmd, re.IGNORECASE)
    operation = op_m.group(1).lower() if op_m else (intent or "convert")

    # 2. Match input files authoritatively
    matched_files, file_err, file_err_detail = match_authoritative_files(
        normalized_cmd,
        input_files_raw,
        available_files,
        output_format
    )

    if file_err == "FILE_NOT_FOUND":
        avail_str = ", ".join(available_files[:8]) if available_files else "Storage is empty"
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": file_err_detail},
            "message": f"File not found: '{file_err_detail}'. Available files: {avail_str}",
            "error": "FILE_NOT_FOUND"
        }
    elif file_err == "AMBIGUOUS_FILE":
        files_str = ", ".join(matched_files)
        return {
            "status": "failed",
            "action": {"action": "file.error"},
            "message": f"Multiple {file_err_detail} files found: {files_str}. Please specify the filename.",
            "error": "AMBIGUOUS_FILE"
        }

    primary_filename = matched_files[0]
    _, src_ext_raw = os.path.splitext(primary_filename)
    src_ext = src_ext_raw.lstrip(".").lower()
    dst_ext = output_format.lstrip(".").lower()

    # 3. Validate and resolve endpoint against registry (Never trust Groq)
    resolved_endpoint: Optional[str] = None

    if groq_endpoint and groq_endpoint in ALLOWED_REGISTRY_ENDPOINTS:
        # Check compatibility with primary file and requested output format
        if "-to-" in groq_endpoint:
            m = re.match(r"^/([a-zA-Z0-9]+)-to-([a-zA-Z0-9]+)$", groq_endpoint)
            if m:
                ep_src, ep_dst = m.group(1).lower(), m.group(2).lower()
                src_ok = src_ext in get_format_variants(ep_src)
                dst_ok = (not dst_ext) or (dst_ext in get_format_variants(ep_dst))
                if src_ok and dst_ok:
                    resolved_endpoint = groq_endpoint
        else:
            # Operation endpoint
            allowed_inputs = OPERATION_INPUT_EXTS.get(groq_endpoint, set())
            if src_ext in allowed_inputs:
                resolved_endpoint = groq_endpoint

    # Deterministic fallback lookup if Groq endpoint is not compatible or unavailable
    if not resolved_endpoint:
        if dst_ext:
            resolved_endpoint = CONVERSION_REGISTRY_MAP.get((src_ext, dst_ext))
        else:
            resolved_endpoint = resolve_operation_endpoint(operation, src_ext)

    # If still not found or not in allowed registry: REJECT
    if not resolved_endpoint or resolved_endpoint not in ALLOWED_REGISTRY_ENDPOINTS:
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": primary_filename},
            "message": "No supported endpoint found for this task.",
            "error": "NO_MATCHING_ENDPOINT"
        }

    # 4. Validate parameters for endpoints that require them
    ep_def = REGISTRY_BY_PATH[resolved_endpoint]
    form_params: Dict[str, str] = {}
    required_params = ep_def.get("params", {})

    if resolved_endpoint == "/add-watermark":
        watermark_val = parameters.get("watermark")
        if not watermark_val:
            wm_m = re.search(r'\bwatermark\s+(?:with\s+)?["\']?([^"\']+)["\']?', normalized_cmd, re.IGNORECASE)
            if wm_m:
                watermark_val = wm_m.group(1).strip()
        if not watermark_val:
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_filename},
                "message": "Missing required parameter 'watermark' for /add-watermark.",
                "error": "MISSING_PARAMETER"
            }
        form_params["watermark"] = str(watermark_val)

    elif resolved_endpoint == "/delete-pdf-pages":
        pages_val = parameters.get("pages")
        if not pages_val:
            pg_m = re.search(r'\b(?:pages?|page)\s+([0-9,\-\s]+)', normalized_cmd, re.IGNORECASE)
            if pg_m:
                pages_val = pg_m.group(1).strip()
        if not pages_val:
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_filename},
                "message": "Missing required parameter 'pages' for /delete-pdf-pages.",
                "error": "MISSING_PARAMETER"
            }
        form_params["pages"] = str(pages_val)

    elif resolved_endpoint == "/split-pdf":
        pages_val = parameters.get("pages")
        if not pages_val:
            pg_m = re.search(r'\b(?:pages?|page)\s+([0-9,\-\s]+)', normalized_cmd, re.IGNORECASE)
            if pg_m:
                pages_val = pg_m.group(1).strip()
            else:
                pages_val = "all"
        form_params["pages"] = str(pages_val)

    # 5. STRICT ASSERTIONS: Outgoing URL must be valid and NEVER contain /convert
    assert resolved_endpoint in ALLOWED_REGISTRY_ENDPOINTS, f"Endpoint {resolved_endpoint} is not in registry"
    assert resolved_endpoint != "/convert", "Endpoint /convert must never be called"
    assert "/convert" not in resolved_endpoint, "Endpoint must never contain /convert"

    endpoint_url = f"{BASE_URL}{resolved_endpoint}"
    assert "/convert" not in endpoint_url, "URL must never contain /convert"

    # Multi-file support
    is_multi = ep_def.get("multi_file", False) or resolved_endpoint in ("/merge-pdfs", "/images-to-pdf")
    file_field = ep_def.get("file_field", "files" if is_multi else "file")

    # Locate actual files on disk
    disk_files = []
    for fn in matched_files:
        finfo = find_file_path(fn)
        if finfo:
            disk_files.append(finfo)

    if not disk_files:
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": primary_filename},
            "message": f"File not found on disk: '{primary_filename}'",
            "error": "FILE_NOT_FOUND"
        }

    # 6. Make request to backend https://goori-os-backend-endpoints.onrender.com
    open_handles = []
    try:
        files_payload = []
        for df in disk_files:
            fh = open(df["path"], "rb")
            open_handles.append(fh)
            mime = mimetypes.guess_type(df["path"])[0] or "application/octet-stream"
            files_payload.append((file_field, (df["filename"], fh, mime)))

        upload_kwargs = {"data": form_params}
        if is_multi:
            upload_kwargs["files"] = files_payload
        else:
            upload_kwargs["files"] = {file_field: files_payload[0][1]}

        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.post(endpoint_url, **upload_kwargs)

    except (httpx.ConnectError, httpx.NetworkError):
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": primary_filename},
            "message": f"Could not connect to backend at {endpoint_url}. Ensure the utility service at goori-os-backend-endpoints.onrender.com is reachable.",
            "error": "BACKEND_UNAVAILABLE"
        }
    except httpx.TimeoutException:
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": primary_filename},
            "message": f"Backend request to {resolved_endpoint} timed out.",
            "error": "BACKEND_TIMEOUT"
        }
    except Exception as e:
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": primary_filename},
            "message": f"Backend request to {resolved_endpoint} failed: {str(e)}",
            "error": "BACKEND_ERROR"
        }
    finally:
        for fh in open_handles:
            try:
                fh.close()
            except Exception:
                pass

    # 7. Check backend response status
    if resp.status_code >= 400:
        err_detail = resp.text.strip()
        try:
            err_json = resp.json()
            err_detail = err_json.get("detail") or err_json.get("message") or err_detail
        except Exception:
            pass
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": primary_filename},
            "message": f"Backend error on {resolved_endpoint} (HTTP {resp.status_code}): {err_detail}",
            "error": f"BACKEND_HTTP_{resp.status_code}"
        }

    # 8. Determine output filename and save result
    output_filename = None
    cd = resp.headers.get("content-disposition", "")
    if cd:
        fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?', cd, re.IGNORECASE)
        if fn_match:
            output_filename = os.path.basename(fn_match.group(1).strip())

    if not output_filename:
        # Use template from registry
        template = ep_def.get("output_filename", "{basename}.out")
        basename, _ = os.path.splitext(primary_filename)
        output_filename = template.replace("{basename}", basename).replace("{ext}", src_ext)

    # Sanitize output filename
    output_filename = re.sub(r'[\/\\:\*\?"<>\|]', '_', output_filename)
    out_path = os.path.join(OUTPUT_DIR, output_filename)

    content = resp.content
    try:
        with open(out_path, "wb") as f:
            f.write(content)
    except Exception as e:
        return {
            "status": "failed",
            "action": {"action": "file.error", "source_file": primary_filename},
            "message": f"Failed to save processed file to Output folder: {str(e)}",
            "error": "SAVE_ERROR"
        }

    file_size = len(content)
    size_kb = file_size / 1024
    size_str = f"{size_kb:.1f} KB" if size_kb >= 1 else f"{file_size} B"

    return {
        "status": "completed",
        "action": {
            "action": "file.processed",
            "target": "output",
            "operation": resolved_endpoint.lstrip("/"),
            "endpoint": resolved_endpoint,
            "source_file": primary_filename,
            "output_file": output_filename,
            "path": f"/uploads/files/output/{output_filename}",
            "size": file_size,
            "size_formatted": size_str,
            "groq_intent": groq_intent
        },
        "message": f"Successfully processed '{primary_filename}' -> '{output_filename}' ({size_str}) saved to Output folder",
        "error": None
    }
