import os
import re
import json
import logging
import mimetypes
from typing import Dict, Any, Optional, List, Tuple
import httpx
from backend.services.filename_normalizer import normalize_file_command, CORE_FILE_EXTENSIONS

from backend.config.endpoints import get_utility_backend_url

logger = logging.getLogger("nova_bridge.file_processing")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FILES_DIR = os.path.join(UPLOAD_DIR, "files")
MOBILE_DIR = os.path.join(FILES_DIR, "mobile")
PHOTOS_DIR = os.path.join(MOBILE_DIR, "photos")
OUTPUT_DIR = os.path.join(FILES_DIR, "output")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "endpoints.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MOBILE_DIR, exist_ok=True)

# 38 Endpoints strictly defined in the registry
ALLOWED_REGISTRY_ENDPOINTS = {
    # IMAGE
    "/jpg-to-png",
    "/png-to-jpg",
    "/webp-to-jpg",
    "/jpg-to-webp",
    "/png-to-webp",
    "/bmp-to-jpg",
    "/bmp-to-png",
    "/tiff-to-jpg",
    "/tiff-to-png",
    "/heic-to-jpg",
    "/heic-to-png",
    "/compress-image",
    "/add-watermark",

    # PDF
    "/extract-images-from-pdf",
    "/merge-pdfs",
    "/split-pdf",
    "/delete-pdf-pages",
    "/pdf-to-jpg",
    "/pdf-to-png",
    "/jpg-to-pdf",
    "/png-to-pdf",
    "/images-to-pdf",
    "/compress-pdf",

    # VIDEO
    "/compress-video",
    "/video-to-gif",
    "/gif-to-mp4",
    "/add-audio-to-video",
    "/replace-video-audio",

    # AUDIO
    "/mp4-to-mp3",
    "/mp4-to-wav",
    "/wav-to-mp3",
    "/mp3-to-wav",
    "/m4a-to-mp3",
    "/compress-audio",

    # DATA
    "/json-to-csv",
    "/csv-to-json",
    "/csv-to-excel",
    "/excel-to-csv",
}

# Explicit source format -> target format mapping to registry endpoints
CONVERSION_REGISTRY_MAP = {
    # IMAGE
    ("jpg", "png"): "/jpg-to-png",
    ("jpeg", "png"): "/jpg-to-png",
    ("png", "jpg"): "/png-to-jpg",
    ("png", "jpeg"): "/png-to-jpg",
    ("webp", "jpg"): "/webp-to-jpg",
    ("webp", "jpeg"): "/webp-to-jpg",
    ("jpg", "webp"): "/jpg-to-webp",
    ("jpeg", "webp"): "/jpg-to-webp",
    ("png", "webp"): "/png-to-webp",
    ("bmp", "jpg"): "/bmp-to-jpg",
    ("bmp", "jpeg"): "/bmp-to-jpg",
    ("bmp", "png"): "/bmp-to-png",
    ("tiff", "jpg"): "/tiff-to-jpg",
    ("tiff", "jpeg"): "/tiff-to-jpg",
    ("tiff", "png"): "/tiff-to-png",
    ("heic", "jpg"): "/heic-to-jpg",
    ("heic", "jpeg"): "/heic-to-jpg",
    ("heic", "png"): "/heic-to-png",

    # PDF
    ("pdf", "jpg"): "/pdf-to-jpg",
    ("pdf", "jpeg"): "/pdf-to-jpg",
    ("pdf", "png"): "/pdf-to-png",
    ("jpg", "pdf"): "/jpg-to-pdf",
    ("jpeg", "pdf"): "/jpg-to-pdf",
    ("png", "pdf"): "/png-to-pdf",

    # VIDEO
    ("mp4", "gif"): "/video-to-gif",
    ("gif", "mp4"): "/gif-to-mp4",

    # AUDIO
    ("mp4", "mp3"): "/mp4-to-mp3",
    ("mp4", "wav"): "/mp4-to-wav",
    ("wav", "mp3"): "/wav-to-mp3",
    ("mp3", "wav"): "/mp3-to-wav",
    ("m4a", "mp3"): "/m4a-to-mp3",

    # DATA
    ("json", "csv"): "/json-to-csv",
    ("csv", "json"): "/csv-to-json",
    ("csv", "excel"): "/csv-to-excel",
    ("csv", "xlsx"): "/csv-to-excel",
    ("csv", "xls"): "/csv-to-excel",
    ("excel", "csv"): "/excel-to-csv",
    ("xlsx", "csv"): "/excel-to-csv",
    ("xls", "csv"): "/excel-to-csv",

    # EXTRACTION / MULTI
    ("pdf", "images"): "/extract-images-from-pdf",
    ("pdf", "image"): "/extract-images-from-pdf",
    ("image", "pdf"): "/jpg-to-pdf",
    ("images", "pdf"): "/images-to-pdf",
    ("photos", "pdf"): "/images-to-pdf",
}

# Complete metadata specifications for all 38 endpoints in the registry
ENDPOINT_REGISTRY_SPECS = {
    # IMAGE (13 endpoints)
    "/jpg-to-png": {"category": "IMAGE", "inputs": {"jpg", "jpeg"}, "outputs": {"png"}, "ops": {"convert"}},
    "/png-to-jpg": {"category": "IMAGE", "inputs": {"png"}, "outputs": {"jpg", "jpeg"}, "ops": {"convert"}},
    "/webp-to-jpg": {"category": "IMAGE", "inputs": {"webp"}, "outputs": {"jpg", "jpeg"}, "ops": {"convert"}},
    "/jpg-to-webp": {"category": "IMAGE", "inputs": {"jpg", "jpeg"}, "outputs": {"webp"}, "ops": {"convert"}},
    "/png-to-webp": {"category": "IMAGE", "inputs": {"png"}, "outputs": {"webp"}, "ops": {"convert"}},
    "/bmp-to-jpg": {"category": "IMAGE", "inputs": {"bmp"}, "outputs": {"jpg", "jpeg"}, "ops": {"convert"}},
    "/bmp-to-png": {"category": "IMAGE", "inputs": {"bmp"}, "outputs": {"png"}, "ops": {"convert"}},
    "/tiff-to-jpg": {"category": "IMAGE", "inputs": {"tiff", "tif"}, "outputs": {"jpg", "jpeg"}, "ops": {"convert"}},
    "/tiff-to-png": {"category": "IMAGE", "inputs": {"tiff", "tif"}, "outputs": {"png"}, "ops": {"convert"}},
    "/heic-to-jpg": {"category": "IMAGE", "inputs": {"heic"}, "outputs": {"jpg", "jpeg"}, "ops": {"convert"}},
    "/heic-to-png": {"category": "IMAGE", "inputs": {"heic"}, "outputs": {"png"}, "ops": {"convert"}},
    "/compress-image": {"category": "IMAGE", "inputs": {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"}, "outputs": set(), "ops": {"compress", "shrink", "optimize", "reduce"}},
    "/add-watermark": {"category": "IMAGE", "inputs": {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"}, "outputs": set(), "ops": {"watermark", "add_watermark", "add-watermark"}},

    # PDF (10 endpoints)
    "/extract-images-from-pdf": {"category": "PDF", "inputs": {"pdf"}, "outputs": {"zip", "images", "png", "jpg"}, "ops": {"extract", "extract_images", "extract-images-from-pdf"}},
    "/merge-pdfs": {"category": "PDF", "inputs": {"pdf"}, "outputs": {"pdf"}, "ops": {"merge", "combine", "merge-pdfs", "merge_pdfs"}},
    "/split-pdf": {"category": "PDF", "inputs": {"pdf"}, "outputs": {"zip", "pdf"}, "ops": {"split", "split-pdf", "split_pdf"}},
    "/delete-pdf-pages": {"category": "PDF", "inputs": {"pdf"}, "outputs": {"pdf"}, "ops": {"delete_pages", "delete-pdf-pages", "delete_pdf_pages"}},
    "/pdf-to-jpg": {"category": "PDF", "inputs": {"pdf"}, "outputs": {"jpg", "jpeg"}, "ops": {"convert"}},
    "/pdf-to-png": {"category": "PDF", "inputs": {"pdf"}, "outputs": {"png"}, "ops": {"convert"}},
    "/jpg-to-pdf": {"category": "PDF", "inputs": {"jpg", "jpeg"}, "outputs": {"pdf"}, "ops": {"convert"}},
    "/png-to-pdf": {"category": "PDF", "inputs": {"png"}, "outputs": {"pdf"}, "ops": {"convert"}},
    "/images-to-pdf": {"category": "PDF", "inputs": {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "heic"}, "outputs": {"pdf"}, "ops": {"convert", "merge", "combine", "images-to-pdf"}},
    "/compress-pdf": {"category": "PDF", "inputs": {"pdf"}, "outputs": set(), "ops": {"compress", "shrink", "optimize", "reduce"}},

    # VIDEO (5 endpoints)
    "/compress-video": {"category": "VIDEO", "inputs": {"mp4", "mov", "avi", "mkv", "webm", "flv"}, "outputs": set(), "ops": {"compress", "shrink", "optimize", "reduce"}},
    "/video-to-gif": {"category": "VIDEO", "inputs": {"mp4", "mov", "avi", "mkv", "webm"}, "outputs": {"gif"}, "ops": {"convert"}},
    "/gif-to-mp4": {"category": "VIDEO", "inputs": {"gif"}, "outputs": {"mp4"}, "ops": {"convert"}},
    "/add-audio-to-video": {"category": "VIDEO", "inputs": {"mp4", "mov", "avi", "mkv", "webm"}, "outputs": set(), "ops": {"add_audio", "add-audio", "add-audio-to-video"}},
    "/replace-video-audio": {"category": "VIDEO", "inputs": {"mp4", "mov", "avi", "mkv", "webm"}, "outputs": set(), "ops": {"replace_audio", "replace-audio", "replace-video-audio"}},

    # AUDIO (6 endpoints)
    "/mp4-to-mp3": {"category": "AUDIO", "inputs": {"mp4"}, "outputs": {"mp3"}, "ops": {"convert"}},
    "/mp4-to-wav": {"category": "AUDIO", "inputs": {"mp4"}, "outputs": {"wav"}, "ops": {"convert"}},
    "/wav-to-mp3": {"category": "AUDIO", "inputs": {"wav"}, "outputs": {"mp3"}, "ops": {"convert"}},
    "/mp3-to-wav": {"category": "AUDIO", "inputs": {"mp3"}, "outputs": {"wav"}, "ops": {"convert"}},
    "/m4a-to-mp3": {"category": "AUDIO", "inputs": {"m4a"}, "outputs": {"mp3"}, "ops": {"convert"}},
    "/compress-audio": {"category": "AUDIO", "inputs": {"mp3", "wav", "m4a", "aac", "flac", "ogg"}, "outputs": set(), "ops": {"compress", "shrink", "optimize", "reduce"}},

    # DATA (4 endpoints)
    "/json-to-csv": {"category": "DATA", "inputs": {"json"}, "outputs": {"csv"}, "ops": {"convert"}},
    "/csv-to-json": {"category": "DATA", "inputs": {"csv"}, "outputs": {"json"}, "ops": {"convert"}},
    "/csv-to-excel": {"category": "DATA", "inputs": {"csv"}, "outputs": {"excel", "xlsx", "xls"}, "ops": {"convert"}},
    "/excel-to-csv": {"category": "DATA", "inputs": {"xlsx", "xls", "excel"}, "outputs": {"csv"}, "ops": {"convert"}},
}


def is_endpoint_compatible(
    endpoint: str,
    source_ext: str = "",
    target_format: str = "",
    operation: str = ""
) -> bool:
    """
    Validates that the given registry endpoint strictly supports:
    1. The input file extension/type.
    2. The requested output format (for conversions).
    3. The requested operation.
    """
    clean_ep = "/" + endpoint.strip().lstrip("/")
    if clean_ep not in ALLOWED_REGISTRY_ENDPOINTS:
        return False

    spec = ENDPOINT_REGISTRY_SPECS.get(clean_ep)
    if not spec:
        return False

    src = source_ext.lstrip(".").lower()
    tgt = target_format.lstrip(".").lower()

    # Normalize format aliases
    if src == "jpeg":
        src = "jpg"
    elif src in ("xls", "excel"):
        src = "xlsx"
    elif src == "tif":
        src = "tiff"

    if tgt == "jpeg":
        tgt = "jpg"
    elif tgt in ("xls", "xlsx"):
        tgt = "excel"
    elif tgt == "tif":
        tgt = "tiff"

    # 1. Input format check
    if src:
        allowed_inputs = set(spec["inputs"])
        if "jpg" in allowed_inputs or "jpeg" in allowed_inputs:
            allowed_inputs.update(["jpg", "jpeg"])
        if "xlsx" in allowed_inputs or "excel" in allowed_inputs:
            allowed_inputs.update(["xlsx", "xls", "excel"])
        if "tiff" in allowed_inputs or "tif" in allowed_inputs:
            allowed_inputs.update(["tiff", "tif"])

        if src not in allowed_inputs:
            return False

    # 2. Output format check (for conversion endpoints)
    if tgt and spec["outputs"]:
        allowed_outputs = set(spec["outputs"])
        if "jpg" in allowed_outputs or "jpeg" in allowed_outputs:
            allowed_outputs.update(["jpg", "jpeg"])
        if "excel" in allowed_outputs or "xlsx" in allowed_outputs:
            allowed_outputs.update(["excel", "xlsx", "xls"])
        if "tiff" in allowed_outputs or "tif" in allowed_outputs:
            allowed_outputs.update(["tiff", "tif"])

        if tgt not in allowed_outputs:
            return False

    return True


def normalize_spoken_filename_patterns(text: str, available_files: Optional[List[str]] = None) -> str:
    """
    Normalizes speech-to-text spoken filename patterns using the global normalization layer.
    Reconstructs missing dots (e.g. 'image jpg' -> 'image.jpg'), expands spelled out letters,
    and normalizes spoken separators.
    """
    return normalize_file_command(text, available_files=available_files)


class FileProcessingService:
    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Loads configurable endpoint definitions from JSON or returns defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "endpoints" in data:
                        return data
            except Exception as e:
                logger.warning(f"Failed to load {self.config_path}, using defaults: {e}")

        return {
            "base_url": get_utility_backend_url(self.config_path),
            "timeout_seconds": 30,
            "endpoints": []
        }

    def list_available_files(self) -> List[str]:
        """Returns filenames of all existing stored files across storage directories."""
        found = []
        for d in [MOBILE_DIR, PHOTOS_DIR, OUTPUT_DIR, UPLOAD_DIR]:
            if os.path.exists(d):
                for item in os.listdir(d):
                    p = os.path.join(d, item)
                    if os.path.isfile(p) and not item.startswith("."):
                        if item not in found:
                            found.append(item)
        return found

    def find_file(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Locates a file in storage directories authoritatively:
        1. Exact case-insensitive match against actual filenames on disk.
        2. Match without extension if filename has no extension.
        3. Match stripping leading articles ("the", "my", "a", "an") if not found.
        4. Normalized space/hyphen/underscore match.
        
        The actual filename in the web app is AUTHORITATIVE.
        Returns dict with actual 'filename' as present on disk.
        """
        if not filename:
            return None

        # Clean quotes and normalize spoken patterns
        raw_clean = filename.strip().strip("'\"")
        normalized_name = normalize_spoken_filename_patterns(raw_clean)
        # Strip polite trailing and leading words
        normalized_name = re.sub(r'\s+(?:please|now|right\s+now|thank\s+you|thanks|for\s+me)$', '', normalized_name, flags=re.IGNORECASE).strip()

        search_dirs = [MOBILE_DIR, PHOTOS_DIR, OUTPUT_DIR, UPLOAD_DIR]

        # 1. Exact case-insensitive match
        for d in search_dirs:
            if os.path.exists(d):
                for item in os.listdir(d):
                    p = os.path.join(d, item)
                    if os.path.isfile(p) and item.lower() == normalized_name.lower():
                        return {
                            "path": p,
                            "filename": item,  # Authoritative disk filename
                            "size": os.path.getsize(p),
                            "dir": d
                        }

        # 2. Match without extension if normalized_name has no extension
        if "." not in normalized_name:
            for d in search_dirs:
                if os.path.exists(d):
                    for item in os.listdir(d):
                        p = os.path.join(d, item)
                        name_no_ext, _ = os.path.splitext(item)
                        if os.path.isfile(p) and name_no_ext.lower() == normalized_name.lower():
                            return {
                                "path": p,
                                "filename": item,
                                "size": os.path.getsize(p),
                                "dir": d
                            }

        # 3. Strip leading articles/possessives: "the", "my", "a", "an"
        # e.g. user said "my test.png" and disk file is "test.png"
        stripped_name = re.sub(r'^(?:the|my|a|an)\s+', '', normalized_name, flags=re.IGNORECASE).strip()
        if stripped_name != normalized_name:
            for d in search_dirs:
                if os.path.exists(d):
                    for item in os.listdir(d):
                        p = os.path.join(d, item)
                        if os.path.isfile(p) and item.lower() == stripped_name.lower():
                            return {
                                "path": p,
                                "filename": item,
                                "size": os.path.getsize(p),
                                "dir": d
                            }

        # 4. Normalized whitespace / punctuation tolerance (e.g. "report-final.pdf" -> "report final.pdf")
        def simplify_for_match(s: str) -> str:
            return re.sub(r'[\s_\-]+', ' ', s).strip().lower()

        simplified_query = simplify_for_match(normalized_name)
        for d in search_dirs:
            if os.path.exists(d):
                for item in os.listdir(d):
                    p = os.path.join(d, item)
                    if os.path.isfile(p) and simplify_for_match(item) == simplified_query:
                        return {
                            "path": p,
                            "filename": item,
                            "size": os.path.getsize(p),
                            "dir": d
                        }

        # 5. Generic format or type indicator / relative reference:
        # e.g. "this png", "the image", "my photo", "this video", "the converted file", "converted file", "the output", "this file"
        lower_raw = normalized_name.lower().strip()
        type_clean = re.sub(r'^(?:the|my|this|that|a|an)\s+', '', lower_raw).strip()
        type_clean = re.sub(r'\s+(?:file|document|image|photo|video|audio)$', '', type_clean).strip() or type_clean

        # Check if asking for converted / output / result file
        if any(w in lower_raw for w in ("converted", "output", "result")):
            if os.path.exists(OUTPUT_DIR):
                out_files = [
                    os.path.join(OUTPUT_DIR, f) for f in os.listdir(OUTPUT_DIR)
                    if os.path.isfile(os.path.join(OUTPUT_DIR, f)) and not f.startswith(".")
                ]
                if out_files:
                    out_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                    latest_p = out_files[0]
                    return {
                        "path": latest_p,
                        "filename": os.path.basename(latest_p),
                        "size": os.path.getsize(latest_p),
                        "dir": OUTPUT_DIR
                    }

        type_ext_map = {
            "png": [".png"],
            "jpg": [".jpg", ".jpeg"],
            "jpeg": [".jpeg", ".jpg"],
            "webp": [".webp"],
            "gif": [".gif"],
            "bmp": [".bmp"],
            "tiff": [".tiff", ".tif"],
            "heic": [".heic"],
            "pdf": [".pdf"],
            "doc": [".pdf", ".txt", ".md"],
            "document": [".pdf", ".txt", ".md"],
            "video": [".mp4", ".mov", ".avi", ".mkv", ".webm"],
            "mp4": [".mp4"],
            "image": [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"],
            "photo": [".png", ".jpg", ".jpeg", ".webp", ".bmp"],
            "pic": [".png", ".jpg", ".jpeg", ".webp", ".bmp"],
            "picture": [".png", ".jpg", ".jpeg", ".webp", ".bmp"],
            "csv": [".csv"],
            "json": [".json"],
            "excel": [".xlsx", ".xls"],
            "data": [".csv", ".json", ".xlsx"],
            "audio": [".mp3", ".wav", ".m4a"],
            "song": [".mp3", ".mp4", ".wav", ".m4a"],
            "mp3": [".mp3"],
            "wav": [".wav"],
            "m4a": [".m4a"],
            "notes": [".txt", ".md"],
            "text": [".txt", ".md"]
        }

        # If asking for "this file" / "the file" / "file", pick the most recent file
        is_generic_file = lower_raw in ("this file", "the file", "my file", "file")
        exts_to_match = type_ext_map.get(type_clean) if not is_generic_file else None

        if exts_to_match is not None or is_generic_file:
            candidates = []
            for d in search_dirs:
                if os.path.exists(d):
                    for item in os.listdir(d):
                        p = os.path.join(d, item)
                        if os.path.isfile(p) and not item.startswith("."):
                            if is_generic_file or any(item.lower().endswith(ext) for ext in exts_to_match):
                                candidates.append((os.path.getmtime(p), p, item, d))
            if candidates:
                # Prioritize source input directories (MOBILE_DIR, PHOTOS_DIR) over OUTPUT_DIR for processing
                if not any(w in lower_raw for w in ("converted", "output", "result")):
                    pref_candidates = [c for c in candidates if c[3] in (MOBILE_DIR, PHOTOS_DIR)]
                    if pref_candidates:
                        candidates = pref_candidates
                # Prefer exact stem match if present (e.g. video.mp4 for 'video')
                exact_stem = [c for c in candidates if os.path.splitext(c[2])[0].lower() == type_clean]
                if exact_stem:
                    candidates = exact_stem
                candidates.sort(key=lambda c: c[0], reverse=True)
                _, best_path, best_name, best_dir = candidates[0]
                return {
                    "path": best_path,
                    "filename": best_name,
                    "size": os.path.getsize(best_path),
                    "dir": best_dir
                }

        return None

    def find_in_command(self, command_text: str) -> Optional[Dict[str, Any]]:
        """
        Scans normalized command text against all available files in storage.
        Uses whole-word boundary matching to prevent substrings (e.g. 'file' in 'ghost_file_999')
        from matching.
        """
        norm_cmd = normalize_spoken_filename_patterns(command_text)
        available = self.list_available_files()

        # Sort available files by length descending
        available_sorted = sorted(available, key=lambda x: len(x), reverse=True)

        for candidate in available_sorted:
            cand_lower = candidate.lower()
            cand_base, cand_ext = os.path.splitext(cand_lower)

            # Match full filename with boundary: e.g. "report final.pdf" or "Intern21.pdf"
            escaped_cand = re.escape(cand_lower)
            if re.search(r'(?<![a-zA-Z0-9_\-])' + escaped_cand + r'(?![a-zA-Z0-9_\-])', norm_cmd.lower()):
                found = self.find_file(candidate)
                if found:
                    return found

            # Match base name only if distinctive (>= 4 chars) and not generic
            if len(cand_base) >= 4 and cand_base not in ("file", "image", "photo", "video", "audio", "data", "test"):
                escaped_base = re.escape(cand_base)
                if re.search(r'(?<![a-zA-Z0-9_\-])' + escaped_base + r'(?![a-zA-Z0-9_\-])', norm_cmd.lower()):
                    found = self.find_file(candidate)
                    if found:
                        return found

        return None

    def resolve_endpoint_from_task(
        self,
        intent: str,
        source_filename: str,
        target_format: str = "",
        explicit_endpoint: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves a task to an exact endpoint from the 38-endpoint registry.
        Validates against ALLOWED_REGISTRY_ENDPOINTS.
        NEVER invents an endpoint.
        """
        endpoints_config = self.config.get("endpoints", [])
        
        # 1. If explicit endpoint was provided (e.g. from Groq)
        _, src_ext = os.path.splitext(source_filename or "")
        src_clean = src_ext.lstrip(".").lower()
        tgt_clean = target_format.lstrip(".").lower()

        if explicit_endpoint:
            clean_ep = "/" + explicit_endpoint.strip().lstrip("/")
            if clean_ep in ALLOWED_REGISTRY_ENDPOINTS:
                if is_endpoint_compatible(clean_ep, source_ext=src_clean, target_format=tgt_clean, operation=intent):
                    # Find matching config rule
                    for rule in endpoints_config:
                        if rule.get("endpoint") == clean_ep:
                            return rule
                    # Generate standard rule if not in config
                    return {
                        "id": clean_ep.lstrip("/").replace("-", "_"),
                        "endpoint": clean_ep,
                        "method": "POST",
                        "file_field": "files" if clean_ep in ("/merge-pdfs", "/images-to-pdf") else "file",
                        "multi_file": clean_ep in ("/merge-pdfs", "/images-to-pdf")
                    }
                else:
                    logger.warning(
                        f"Explicit endpoint '{clean_ep}' rejected: incompatible with source='{source_filename}', target='{target_format}'"
                    )
                    return None

        # 2. Resolve from (source_ext, target_format) mapping

        # Check conversion table
        if (src_clean, tgt_clean) in CONVERSION_REGISTRY_MAP:
            mapped_ep = CONVERSION_REGISTRY_MAP[(src_clean, tgt_clean)]
            for rule in endpoints_config:
                if rule.get("endpoint") == mapped_ep:
                    return rule
            return {
                "id": mapped_ep.lstrip("/").replace("-", "_"),
                "endpoint": mapped_ep,
                "method": "POST",
                "file_field": "file",
                "multi_file": False
            }

        # Check operations
        intent_clean = (intent or "").strip().lower()

        if intent_clean in ("compress", "shrink", "optimize", "reduce"):
            if src_clean in ("jpg", "jpeg", "png", "webp", "bmp", "tiff", "heic"):
                mapped_ep = "/compress-image"
            elif src_clean == "pdf":
                mapped_ep = "/compress-pdf"
            elif src_clean in ("mp4", "mov", "avi", "mkv", "webm"):
                mapped_ep = "/compress-video"
            elif src_clean in ("mp3", "wav", "m4a", "aac", "flac"):
                mapped_ep = "/compress-audio"
            else:
                mapped_ep = None

            if mapped_ep:
                for rule in endpoints_config:
                    if rule.get("endpoint") == mapped_ep:
                        return rule
                return {"endpoint": mapped_ep, "method": "POST", "file_field": "file", "multi_file": False}

        if intent_clean in ("split", "split-pdf", "split_pdf"):
            mapped_ep = "/split-pdf"
            for rule in endpoints_config:
                if rule.get("endpoint") == mapped_ep:
                    return rule
            return {"endpoint": mapped_ep, "method": "POST", "file_field": "file", "multi_file": False}

        if intent_clean in ("merge", "merge-pdfs", "merge_pdfs"):
            mapped_ep = "/merge-pdfs"
            for rule in endpoints_config:
                if rule.get("endpoint") == mapped_ep:
                    return rule
            return {"endpoint": mapped_ep, "method": "POST", "file_field": "files", "multi_file": True}

        if intent_clean in ("extract", "extract_images", "extract-images-from-pdf"):
            mapped_ep = "/extract-images-from-pdf"
            for rule in endpoints_config:
                if rule.get("endpoint") == mapped_ep:
                    return rule
            return {"endpoint": mapped_ep, "method": "POST", "file_field": "file", "multi_file": False}

        if intent_clean in ("watermark", "add_watermark", "add-watermark"):
            mapped_ep = "/add-watermark"
            for rule in endpoints_config:
                if rule.get("endpoint") == mapped_ep:
                    return rule
            return {"endpoint": mapped_ep, "method": "POST", "file_field": "file", "multi_file": False}

        return None

    def parse_command(self, command_text: str) -> Optional[Dict[str, Any]]:
        """
        Deterministic parser for voice task commands matching the endpoint registry.
        """
        if not command_text:
            return None

        normalized = normalize_spoken_filename_patterns(command_text)

        # Strip polite prefixes
        while True:
            stripped = re.sub(
                r'^(?:please|can\s+you\s+please|could\s+you\s+please|can\s+you|could\s+you|would\s+you|will\s+you|hey\s+nova|hi\s+nova|hello\s+nova|nova)\s+',
                '',
                normalized,
                flags=re.IGNORECASE
            ).strip()
            if stripped == normalized:
                break
            normalized = stripped

        # Strip polite trailing words
        while True:
            stripped = re.sub(
                r'\s+(?:please|now|right\s+now|thank\s+you|thanks|for\s+me)$',
                '',
                normalized,
                flags=re.IGNORECASE
            ).strip()
            if stripped == normalized:
                break
            normalized = stripped

        # 1. Convert: convert <filename> to <format> | turn <filename> into <format> | make <filename> a <format> | change <filename> to <format>
        KNOWN_CONV_FORMATS = {
            "jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "tif", "heic",
            "pdf", "mp4", "mov", "avi", "mkv", "webm", "mp3", "wav", "m4a",
            "flac", "aac", "ogg", "csv", "json", "excel", "xlsx", "xls",
            "images", "photos", "pics"
        }
        conv_m = re.search(
            r'\b(?:convert|transform|turn|change|make|switch)\s+(?P<filename>[a-zA-Z0-9_\.\-\s]+?)\s+(?:to|into|as|a|an)\s+(?P<target_format>[a-zA-Z0-9]+)\b',
            normalized,
            re.IGNORECASE
        )
        if conv_m:
            target_fmt = conv_m.group("target_format").strip().lower()
            if target_fmt in ("images", "photos", "pics"):
                target_fmt = "images"

            if target_fmt in KNOWN_CONV_FORMATS:
                fn = conv_m.group("filename").strip()
                disk_files = [f.lower() for f in self.list_available_files()]
                if fn.lower() not in disk_files:
                    fn = re.sub(r'^(?:the|my|this|that|a|an)\s+', '', fn, flags=re.IGNORECASE).strip()
                return {
                    "operation": "convert",
                    "filename": fn,
                    "target_format": target_fmt,
                    "normalized_cmd": normalized
                }

        # 1b. Extract: extract images from <filename>
        extract_m = re.search(
            r'\b(?:extract\s+images\s+from|extract\s+photos\s+from|extract\s+images|extract\s+pictures\s+from)\s+(?P<filename>[a-zA-Z0-9_\.\-\s]+)',
            normalized,
            re.IGNORECASE
        )
        if extract_m:
            fn = extract_m.group("filename").strip()
            fn = re.sub(r'^(?:the|my|this|that|a|an)\s+', '', fn, flags=re.IGNORECASE).strip()
            fn = re.sub(r'\s+(?:please|now|right\s+now|thank\s+you|thanks|for\s+me)$', '', fn, flags=re.IGNORECASE).strip()
            return {
                "operation": "extract",
                "filename": fn,
                "target_format": "images",
                "normalized_cmd": normalized
            }

        # 2. Compress: compress <filename> | compress this <type>
        comp_m = re.search(
            r'\b(?:compress|shrink|optimize|reduce)\s+(?P<filename>[a-zA-Z0-9_\.\-\s]+)',
            normalized,
            re.IGNORECASE
        )
        if comp_m:
            fn = comp_m.group("filename").strip()
            fn = re.sub(r'^(?:the|my|a|an)\s+', '', fn, flags=re.IGNORECASE).strip()
            fn = re.sub(r'\s+(?:please|now|right\s+now|thank\s+you|thanks|for\s+me)$', '', fn, flags=re.IGNORECASE).strip()
            return {
                "operation": "compress",
                "filename": fn,
                "target_format": "",
                "normalized_cmd": normalized
            }

        # 3. Split: split <filename> | split this pdf
        split_m = re.search(
            r'\b(?:split)\s+(?P<filename>[a-zA-Z0-9_\.\-\s]+)',
            normalized,
            re.IGNORECASE
        )
        if split_m:
            fn = split_m.group("filename").strip()
            fn = re.sub(r'^(?:the|my|a|an)\s+', '', fn, flags=re.IGNORECASE).strip()
            fn = re.sub(r'\s+(?:please|now|right\s+now|thank\s+you|thanks|for\s+me)$', '', fn, flags=re.IGNORECASE).strip()
            return {
                "operation": "split",
                "filename": fn,
                "target_format": "",
                "normalized_cmd": normalized
            }

        # 4. Merge: merge <filenames> to <format>
        merge_m = re.search(
            r'\b(?:merge|combine)\s+(?P<filenames>[a-zA-Z0-9_\.\-\s]+?)(?:\s+(?:to|into|as)\s+(?P<target_format>[a-zA-Z0-9]+))?$',
            normalized,
            re.IGNORECASE
        )
        if merge_m:
            fns = merge_m.group("filenames").strip()
            tgt = merge_m.group("target_format") or "pdf"
            return {
                "operation": "merge",
                "filename": fns,
                "target_format": tgt.lower(),
                "normalized_cmd": normalized
            }

        return None

    def execute_processing(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a file processing request:
        1. Resolves authoritative disk filename(s).
        2. Resolves and validates endpoint from the 38-endpoint registry.
        3. Uploads file to https://goori-os-backend-endpoints.onrender.com.
        4. Saves output into Output folder and returns result.
        """
        raw_fn = (parsed.get("filename") or "").strip()
        target_fmt = parsed.get("target_format") or ""
        operation = parsed.get("operation") or "convert"
        explicit_ep = parsed.get("endpoint")

        # 1. Authoritative file resolution (support single and multiple files)
        filenames_to_find = []
        if " and " in raw_fn or "," in raw_fn:
            split_fns = re.split(r'\s+(?:and|,)\s+|\s*,\s*', raw_fn)
            filenames_to_find = [f.strip() for f in split_fns if f.strip()]
        elif raw_fn:
            filenames_to_find = [raw_fn.strip()]

        found_files = []
        for fn in filenames_to_find:
            f = self.find_file(fn)
            if f:
                found_files.append(f)

        # Only scan command text if raw_fn was empty or not an explicit filename with extension
        if not found_files and (not raw_fn or "." not in raw_fn) and parsed.get("normalized_cmd"):
            finfo = self.find_in_command(parsed["normalized_cmd"])
            if finfo:
                found_files.append(finfo)

        if not found_files:
            available = self.list_available_files()
            avail_str = ", ".join(available[:8]) if available else "No files in storage"
            target_display = raw_fn or "requested file"
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": target_display},
                "message": f"File not found: '{target_display}'. Available files: {avail_str}",
                "error": "FILE_NOT_FOUND"
            }

        primary_file = found_files[0]
        basename, ext = os.path.splitext(primary_file["filename"])
        clean_ext = ext.lstrip(".").lower()

        # 2. Resolve endpoint against registry
        endpoint_rule = self.resolve_endpoint_from_task(
            intent=operation,
            source_filename=primary_file["filename"],
            target_format=target_fmt,
            explicit_endpoint=explicit_ep
        )

        if not endpoint_rule and len(found_files) > 1:
            endpoint_rule = {"endpoint": "/merge-pdfs", "method": "POST", "file_field": "files", "multi_file": True}

        if not endpoint_rule:
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": "No supported endpoint is available for this task.",
                "error": "NO_MATCHING_ENDPOINT"
            }

        endpoint_path = endpoint_rule.get("endpoint")
        if endpoint_path not in ALLOWED_REGISTRY_ENDPOINTS:
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": "No supported endpoint is available for this task.",
                "error": "NO_MATCHING_ENDPOINT"
            }

        base_url = get_utility_backend_url(self.config_path)
        endpoint_url = f"{base_url}{endpoint_path}"
        method = endpoint_rule.get("method", "POST").upper()
        multi_file = endpoint_rule.get("multi_file", False) or len(found_files) > 1 or endpoint_path in ("/merge-pdfs", "/images-to-pdf")
        file_field = "files" if multi_file else endpoint_rule.get("file_field", "file")
        timeout = float(self.config.get("timeout_seconds", 30))

        # 3. Form parameters & multipart files
        form_params = {}
        for k, v in endpoint_rule.get("params", {}).items():
            if isinstance(v, str):
                val = v.replace("{target_format}", target_fmt)
                val = val.replace("{filename}", primary_file["filename"])
                val = val.replace("{basename}", basename)
                val = val.replace("{ext}", clean_ext)
                form_params[k] = val
            else:
                form_params[k] = str(v)

        open_file_handles = []
        try:
            files_payload = []
            for finfo in found_files:
                fh = open(finfo["path"], "rb")
                open_file_handles.append(fh)
                mime = mimetypes.guess_type(finfo["path"])[0] or "application/octet-stream"
                files_payload.append((file_field, (finfo["filename"], fh, mime)))

            upload_kwargs = {"data": form_params}
            if multi_file:
                upload_kwargs["files"] = files_payload
            else:
                upload_kwargs["files"] = {file_field: files_payload[0][1]}

            with httpx.Client(timeout=timeout) as client:
                if method == "POST":
                    resp = client.post(endpoint_url, **upload_kwargs)
                elif method == "PUT":
                    resp = client.put(endpoint_url, **upload_kwargs)
                else:
                    resp = client.request(method, endpoint_url, **upload_kwargs)

        except (httpx.ConnectError, httpx.NetworkError):
            local_res = self._try_local_fallback(endpoint_path, primary_file, target_fmt)
            if local_res:
                return local_res
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": f"Could not connect to backend at {endpoint_url}. Ensure the deployed utility service is reachable.",
                "error": "BACKEND_UNAVAILABLE"
            }
        except httpx.TimeoutException:
            local_res = self._try_local_fallback(endpoint_path, primary_file, target_fmt)
            if local_res:
                return local_res
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": f"Backend at {endpoint_url} timed out while processing '{primary_file['filename']}'.",
                "error": "BACKEND_TIMEOUT"
            }
        except Exception as e:
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": f"Upload failed: {str(e)}",
                "error": "UPLOAD_FAILED"
            }
        finally:
            for fh in open_file_handles:
                try:
                    fh.close()
                except Exception:
                    pass

        # 4. Check backend response
        if resp.status_code >= 400:
            local_res = self._try_local_fallback(endpoint_path, primary_file, target_fmt)
            if local_res:
                return local_res
            err_detail = resp.text.strip()
            try:
                err_json = resp.json()
                err_detail = err_json.get("detail") or err_json.get("message") or err_detail
            except Exception:
                pass
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": f"Backend returned error (HTTP {resp.status_code}): {err_detail}",
                "error": f"BACKEND_HTTP_{resp.status_code}"
            }

        # 5. Determine output filename and extension
        output_filename = None
        cd = resp.headers.get("content-disposition", "")
        if cd:
            fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?', cd, re.IGNORECASE)
            if fn_match:
                output_filename = os.path.basename(fn_match.group(1).strip())

        if not output_filename:
            tmpl = endpoint_rule.get("output_filename")
            if tmpl:
                out_name = tmpl.replace("{basename}", basename)
                out_name = out_name.replace("{target_format}", target_fmt)
                out_name = out_name.replace("{ext}", clean_ext)
                output_filename = out_name

        if not output_filename:
            if endpoint_path == "/merge-pdfs":
                output_filename = "merged.pdf"
            else:
                output_filename = f"{basename}_processed.{target_fmt or clean_ext or 'bin'}"

        output_filename = re.sub(r'[\/\\:\*\?"<>\|]', '_', output_filename)
        out_path = os.path.join(OUTPUT_DIR, output_filename)

        content = resp.content
        try:
            with open(out_path, "wb") as f:
                f.write(content)
        except Exception as e:
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
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
                "operation": (
                    "convert" if "-to-" in endpoint_path
                    else ("compress" if "compress" in endpoint_path
                    else ("merge" if "merge" in endpoint_path
                    else ("split" if "split" in endpoint_path
                    else endpoint_path.lstrip("/"))))
                ),
                "endpoint": endpoint_path,
                "source_file": primary_file["filename"],
                "output_file": output_filename,
                "path": f"/uploads/files/output/{output_filename}",
                "size": file_size,
                "size_formatted": size_str
            },
            "message": f"Successfully processed '{primary_file['filename']}' -> '{output_filename}' ({size_str}) saved to Output folder",
            "error": None
        }


    def _try_local_fallback(self, endpoint_path: str, primary_file: Dict[str, Any], target_fmt: str = "") -> Optional[Dict[str, Any]]:
        """Performs fast built-in local conversions for supported operations (e.g. data formats)."""
        try:
            import csv
            src_path = primary_file["path"]
            base = os.path.splitext(primary_file["filename"])[0]

            if endpoint_path == "/json-to-csv":
                out_name = f"{base}.csv"
                out_path = os.path.join(OUTPUT_DIR, out_name)
                with open(src_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data = [data]
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    fieldnames = list(data[0].keys())
                    with open(out_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(data)
                else:
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(str(data))
                f_size = os.path.getsize(out_path)
                s_str = f"{f_size/1024:.1f} KB" if f_size >= 1024 else f"{f_size} B"
                return {
                    "status": "completed",
                    "action": {
                        "action": "file.processed",
                        "target": "output",
                        "operation": "convert",
                        "endpoint": endpoint_path,
                        "source_file": primary_file["filename"],
                        "output_file": out_name,
                        "path": f"/uploads/files/output/{out_name}",
                        "size": f_size,
                        "size_formatted": s_str
                    },
                    "message": f"Successfully processed '{primary_file['filename']}' -> '{out_name}' ({s_str}) saved to Output folder",
                    "error": None
                }

            elif endpoint_path == "/csv-to-json":
                out_name = f"{base}.json"
                out_path = os.path.join(OUTPUT_DIR, out_name)
                with open(src_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(rows, f, indent=2)
                f_size = os.path.getsize(out_path)
                s_str = f"{f_size/1024:.1f} KB" if f_size >= 1024 else f"{f_size} B"
                return {
                    "status": "completed",
                    "action": {
                        "action": "file.processed",
                        "target": "output",
                        "operation": "convert",
                        "endpoint": endpoint_path,
                        "source_file": primary_file["filename"],
                        "output_file": out_name,
                        "path": f"/uploads/files/output/{out_name}",
                        "size": f_size,
                        "size_formatted": s_str
                    },
                    "message": f"Successfully processed '{primary_file['filename']}' -> '{out_name}' ({s_str}) saved to Output folder",
                    "error": None
                }

        except Exception as ex:
            logger.warning(f"Local conversion fallback error: {ex}")
        return None

# Singleton service instance
file_processing_service = FileProcessingService()
