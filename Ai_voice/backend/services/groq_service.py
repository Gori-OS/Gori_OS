import os
import re
import json
import logging
import mimetypes
from typing import Dict, Any, Optional, List, Tuple
import httpx
from dotenv import load_dotenv

# Ensure .env is loaded from project root
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv()

from backend.services.file_processing_service import (
    file_processing_service,
    normalize_spoken_filename_patterns,
    is_endpoint_compatible,
    ALLOWED_REGISTRY_ENDPOINTS,
    ENDPOINT_REGISTRY_SPECS,
    CONVERSION_REGISTRY_MAP,
    OUTPUT_DIR,
    MOBILE_DIR,
    PHOTOS_DIR,
    UPLOAD_DIR
)
from backend.config.endpoints import get_utility_backend_url

logger = logging.getLogger("nova_bridge.groq_service")

# Fixed 38-endpoint registry as the ONLY source for endpoint selection
TASK_ENDPOINT_REGISTRY_DOC = """FIXED ENDPOINT REGISTRY:
IMAGE
/jpg-to-png
/png-to-jpg
/webp-to-jpg
/jpg-to-webp
/png-to-webp
/bmp-to-jpg
/bmp-to-png
/tiff-to-jpg
/tiff-to-png
/heic-to-jpg
/heic-to-png
/compress-image
/add-watermark

PDF
/extract-images-from-pdf
/merge-pdfs
/split-pdf
/delete-pdf-pages
/pdf-to-jpg
/pdf-to-png
/jpg-to-pdf
/png-to-pdf
/images-to-pdf
/compress-pdf

VIDEO
/compress-video
/video-to-gif
/gif-to-mp4
/add-audio-to-video
/replace-video-audio

AUDIO
/mp4-to-mp3
/mp4-to-wav
/wav-to-mp3
/mp3-to-wav
/m4a-to-mp3
/compress-audio

DATA
/json-to-csv
/csv-to-json
/csv-to-excel
/excel-to-csv"""


class GroqService:
    def __init__(self):
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.models = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
        self.timeout = 15.0

    @property
    def api_key(self) -> Optional[str]:
        return os.environ.get("GROQ_API_KEY")

    def is_available(self) -> bool:
        key = self.api_key
        return bool(key and key.strip())

    def call_groq_intent_parser(self, command_text: str, available_files: List[str]) -> Optional[Dict[str, Any]]:
        """
        Sends the transcribed voice command and endpoint registry to Groq.
        Groq returns structured JSON:
        {
          "intent": "...",
          "endpoint": "...",
          "input_files": [],
          "parameters": {}
        }
        The endpoint MUST exactly match one endpoint from the registry.
        """
        if not self.is_available():
            logger.warning("GROQ_API_KEY is not configured in .env")
            return None

        # Normalize spoken patterns before sending to Groq as well
        normalized_command = normalize_spoken_filename_patterns(command_text)

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
            "   - endpoint name\n"
            "   - endpoint purpose\n"
            "   - required parameters\n"
            "2. Use high-confidence matching.\n"
            "3. For conversion commands, input and output formats MUST match the endpoint.\n"
            "   Examples:\n"
            '   "convert song.mp4 to mp3" -> /mp4-to-mp3\n'
            '   "convert song dot mp4 to mp3" -> /mp4-to-mp3\n'
            '   "convert image.png to jpg" -> /png-to-jpg\n'
            '   "convert image dot png to jpg" -> /png-to-jpg\n'
            '   "convert image.jpg to webp" -> /jpg-to-webp\n'
            '   "convert intern21.pdf to png" -> /pdf-to-png\n'
            '   "convert data.csv to excel" -> /csv-to-excel\n'
            '   "convert data.json to csv" -> /json-to-csv\n'
            '   "convert gif to mp4" -> /gif-to-mp4\n'
            "4. Do NOT select an endpoint only because its name is textually similar.\n"
            '   For example: "convert image.png to mp3" MUST NOT select /mp4-to-mp3, /mp3-to-wav, or any other incompatible endpoint.\n'
            "5. If a file task or conversion is requested but no endpoint supports the requested input/output combination or operation (e.g. 'convert image.png to mp3'), return:\n"
            "   {\n"
            '     "intent": "unsupported",\n'
            '     "endpoint": null,\n'
            '     "input_files": [],\n'
            '     "parameters": {}\n'
            "   }\n"
            "6. If the command is NOT a file utility or conversion task at all (e.g. conversational or unrecognized like 'make me a sandwich'), set 'intent' to 'unknown' and 'endpoint' to null.\n"
            "7. The endpoint returned by Groq MUST exactly match one endpoint in the registry.\n"
            "   Never invent an endpoint.\n"
            "   Never create /convert.\n"
            "   Never fall back to /convert.\n"
            "   Never modify an endpoint name.\n"
            "   Never guess an endpoint.\n"
            "8. Return JSON ONLY strictly conforming to this schema:\n"
            "{\n"
            '  "intent": "...",\n'
            '  "endpoint": "...",\n'
            '  "input_files": [],\n'
            '  "parameters": {}\n'
            "}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json"
        }

        # Try models in order of priority
        last_error = None
        for model in self.models:
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
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(self.api_url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    return parsed
                elif resp.status_code == 429:
                    logger.warning(f"Groq model {model} rate limited (HTTP 429), trying next model if available")
                    last_error = f"HTTP 429: {resp.text}"
                    continue
                else:
                    logger.warning(f"Groq model {model} returned HTTP {resp.status_code}: {resp.text}")
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
            except Exception as e:
                logger.warning(f"Groq request failed on {model}: {e}")
                last_error = str(e)

        logger.error(f"All Groq models failed or rate limited. Last error: {last_error}")
        return None

    def resolve_authoritative_files(
        self,
        raw_input_files: List[str],
        normalized_cmd: str,
        available_files: List[str],
        intent: str
    ) -> List[Dict[str, Any]]:
        """
        Resolves spoken filename patterns against actual files available in the web app.
        The actual filename in the web app is authoritative.
        Case-insensitive matching supporting spaces, numbers, underscores, hyphens, and multiple dots.
        """
        resolved = []
        explicit_missing = False

        # 1. First try matching filenames provided by Groq
        for raw_fn in raw_input_files:
            clean_fn = normalize_spoken_filename_patterns(str(raw_fn).strip())
            if not clean_fn:
                continue

            found = file_processing_service.find_file(clean_fn)
            if found:
                resolved.append(found)
                continue

            # If user explicitly requested a file with an extension that does not exist in storage
            if "." in clean_fn:
                explicit_missing = True

            # Check contextual terms
            lower_fn = clean_fn.lower()
            if any(term in lower_fn for term in ["this video", "the video", "video"]):
                for cand in available_files:
                    if cand.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break
            elif any(term in lower_fn for term in ["this pdf", "the pdf", "pdf", "document"]):
                for cand in available_files:
                    if cand.lower().endswith(".pdf"):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break
            elif any(term in lower_fn for term in ["this gif", "the gif", "gif"]):
                for cand in available_files:
                    if cand.lower().endswith(".gif"):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break
            elif any(term in lower_fn for term in ["this image", "the image", "image", "photo"]):
                for cand in available_files:
                    if cand.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break

        # If an explicit file with extension was requested and not found in storage, return empty immediately
        if explicit_missing and not resolved:
            return []

        # 2. If no files resolved from input_files and no explicit missing file, scan the normalized command text directly
        if not resolved and normalized_cmd:
            # Check if command has an explicit missing filename with extension
            explicit_fn_match = re.search(r'\b([a-zA-Z0-9_\.\-]+\.[a-zA-Z0-9]+)\b', normalized_cmd)
            if explicit_fn_match:
                candidate_token = explicit_fn_match.group(1)
                found = file_processing_service.find_file(candidate_token)
                if found:
                    resolved.append(found)
                    return resolved
                else:
                    # Token with extension was explicitly in command and not found
                    return []

            found_in_cmd = file_processing_service.find_in_command(normalized_cmd)
            if found_in_cmd:
                resolved.append(found_in_cmd)

        # 3. If still empty, check if contextual reference in normalized command matches available files
        if not resolved and available_files:
            cmd_lower = normalized_cmd.lower()
            if "video" in cmd_lower:
                for cand in available_files:
                    if cand.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break
            elif "pdf" in cmd_lower or "document" in cmd_lower:
                for cand in available_files:
                    if cand.lower().endswith(".pdf"):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break
            elif "gif" in cmd_lower:
                for cand in available_files:
                    if cand.lower().endswith(".gif"):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break
            elif "image" in cmd_lower or "photo" in cmd_lower:
                for cand in available_files:
                    if cand.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break
            elif "csv" in cmd_lower or "excel" in cmd_lower or "data" in cmd_lower:
                for cand in available_files:
                    if cand.lower().endswith((".csv", ".xlsx", ".json")):
                        f = file_processing_service.find_file(cand)
                        if f:
                            resolved.append(f)
                            break

        return resolved

    def validate_and_resolve_endpoint(
        self,
        groq_endpoint: Optional[str],
        intent: str,
        primary_file: Optional[Dict[str, Any]],
        normalized_cmd: str,
        output_format: str = ""
    ) -> Optional[str]:
        """
        Validates that the selected endpoint exactly matches one from the 38-endpoint registry
        AND strictly satisfies input and output format compatibility.
        NEVER invents an endpoint.
        """
        source_name = primary_file.get("filename", "") if primary_file else ""
        _, src_ext = os.path.splitext(source_name)
        src_clean = src_ext.lstrip(".").lower()

        # Deduce target format if not provided
        tgt_fmt = output_format.strip().lower().lstrip(".")
        if not tgt_fmt:
            fmt_m = re.search(r'\b(?:to|into|as)\s+([a-zA-Z0-9]+)\b', normalized_cmd, re.IGNORECASE)
            if fmt_m:
                tgt_fmt = fmt_m.group(1).lower()

        # 1. Check if Groq returned a valid registry endpoint and verify compatibility
        if groq_endpoint:
            clean_ep = "/" + groq_endpoint.strip().lstrip("/")
            if is_endpoint_compatible(clean_ep, source_ext=src_clean, target_format=tgt_fmt, operation=intent):
                return clean_ep
            else:
                logger.warning(
                    f"Groq endpoint '{clean_ep}' rejected: incompatible with source='{source_name}' "
                    f"(ext='{src_clean}'), target='{tgt_fmt}', operation='{intent}'"
                )

        # 2. If Groq endpoint is not compatible or null, verify against registry conversion rules
        resolved_rule = file_processing_service.resolve_endpoint_from_task(
            intent=intent,
            source_filename=source_name,
            target_format=tgt_fmt,
            explicit_endpoint=None
        )

        if resolved_rule and resolved_rule.get("endpoint") in ALLOWED_REGISTRY_ENDPOINTS:
            ep = resolved_rule["endpoint"]
            if is_endpoint_compatible(ep, source_ext=src_clean, target_format=tgt_fmt, operation=intent):
                return ep

        return None

    def process_with_groq(self, command_text: str) -> Dict[str, Any]:
        """
        Complete Groq-powered task resolution workflow:
        1. Receive transcribed voice command.
        2. Normalize spoken filenames and extensions ('dot' -> '.', 'P N G' -> 'png').
        3. Send the task command to Groq with the 38-endpoint registry.
        4. Identify operation, input file(s), target format, and parameters.
        5. Match filenames authoritatively against actual files in the web app.
        6. Select and validate the correct endpoint strictly from the endpoint registry.
        7. Send file to https://goori-os-backend-endpoints.onrender.com using exact method, field names, parameters.
        8. Save returned result in Output folder.
        9. Refresh Output folder and return file.processed action.
        """
        available_files = file_processing_service.list_available_files()
        normalized_cmd = normalize_spoken_filename_patterns(command_text)

        groq_result = self.call_groq_intent_parser(command_text, available_files)

        if not groq_result:
            # Fallback to deterministic parser
            parsed = file_processing_service.parse_command(command_text)
            if parsed:
                return file_processing_service.execute_processing(parsed)

            return {
                "status": "failed",
                "action": {"action": "file.error"},
                "message": "Groq intent understanding is currently unavailable or failed to respond.",
                "error": "GROQ_UNAVAILABLE"
            }

        intent = (groq_result.get("intent") or "").strip().lower()
        groq_endpoint = groq_result.get("endpoint")
        input_files_raw = groq_result.get("input_files") or []
        parameters = groq_result.get("parameters") or {}
        output_format = (groq_result.get("output_format") or "").strip().lower().lstrip(".")

        if intent == "unsupported":
            is_task_related = bool(
                re.search(r'\b(convert|transform|turn|compress|shrink|optimize|reduce|split|merge|combine|extract|watermark|delete)\b', normalized_cmd, re.IGNORECASE)
                or input_files_raw
                or output_format
                or "." in normalized_cmd
            )
            if is_task_related:
                return {
                    "status": "failed",
                    "action": {"action": "file.error"},
                    "message": "No supported endpoint is available for this task.",
                    "error": "NO_MATCHING_ENDPOINT",
                    "groq_intent": groq_result
                }
            else:
                return {
                    "status": "failed",
                    "action": {"action": "file.error"},
                    "message": f"Could not identify a file utility task from command: '{command_text}'.",
                    "error": "UNKNOWN_TASK"
                }

        if intent in ("none", "unknown") and not groq_endpoint:
            return {
                "status": "failed",
                "action": {"action": "file.error"},
                "message": f"Could not identify a file utility task from command: '{command_text}'.",
                "error": "UNKNOWN_TASK"
            }

        # Match input files authoritatively against actual files in storage
        resolved_files = self.resolve_authoritative_files(
            input_files_raw,
            normalized_cmd,
            available_files,
            intent
        )

        if not resolved_files:
            # Determine best display name for the missing file
            if input_files_raw and str(input_files_raw[0]).strip():
                target_name = normalize_spoken_filename_patterns(str(input_files_raw[0]).strip())
            else:
                fn_match = re.search(r'[a-zA-Z0-9_\.\-\s]+\.[a-zA-Z0-9]+', normalized_cmd)
                target_name = fn_match.group(0).strip() if fn_match else "requested file"

            avail_str = ", ".join(available_files[:8]) if available_files else "Storage is empty"
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": target_name},
                "message": f"File not found: '{target_name}'. Available files: {avail_str}",
                "error": "FILE_NOT_FOUND"
            }

        primary_file = resolved_files[0]
        basename, ext = os.path.splitext(primary_file["filename"])
        clean_ext = ext.lstrip(".").lower()

        # Validate endpoint against the 38-endpoint registry
        endpoint = self.validate_and_resolve_endpoint(
            groq_endpoint=groq_endpoint,
            intent=intent,
            primary_file=primary_file,
            normalized_cmd=normalized_cmd,
            output_format=output_format
        )

        if not endpoint or endpoint not in ALLOWED_REGISTRY_ENDPOINTS:
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": "No supported endpoint is available for this task.",
                "error": "NO_MATCHING_ENDPOINT"
            }

        # Execute upload to utility backend
        base_url = get_utility_backend_url()
        endpoint_url = f"{base_url}{endpoint}"
        multi_file = endpoint in ("/merge-pdfs", "/images-to-pdf")
        file_field = "files" if multi_file else "file"
        timeout = 30.0

        # Build form parameters
        form_params = {}
        for pk, pv in parameters.items():
            if pv is not None:
                form_params[pk] = str(pv)

        open_file_handles = []
        try:
            files_payload = []
            for finfo in resolved_files:
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
                resp = client.post(endpoint_url, **upload_kwargs)

        except (httpx.ConnectError, httpx.NetworkError):
            local_res = file_processing_service._try_local_fallback(endpoint, primary_file)
            if local_res:
                return local_res
            return {
                "status": "failed",
                "action": {"action": "file.error", "source_file": primary_file["filename"]},
                "message": f"Could not connect to backend at {endpoint_url}. Ensure the deployed utility service is reachable.",
                "error": "BACKEND_UNAVAILABLE"
            }
        except httpx.TimeoutException:
            local_res = file_processing_service._try_local_fallback(endpoint, primary_file)
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

        # Check response status
        if resp.status_code >= 400:
            local_res = file_processing_service._try_local_fallback(endpoint, primary_file)
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

        # Determine output filename
        output_filename = None
        cd = resp.headers.get("content-disposition", "")
        if cd:
            fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?', cd, re.IGNORECASE)
            if fn_match:
                output_filename = os.path.basename(fn_match.group(1).strip())

        if not output_filename:
            # Fallback to endpoint pattern output
            ep_clean = endpoint.lstrip("/")
            if "-to-" in ep_clean:
                target_ext = ep_clean.split("-to-")[-1]
                if target_ext == "excel":
                    target_ext = "xlsx"
                output_filename = f"{basename}.{target_ext}"
            elif "compress" in ep_clean:
                output_filename = f"{basename}_compressed.{clean_ext}"
            elif "split" in ep_clean:
                output_filename = f"{basename}_split.zip"
            elif "watermark" in ep_clean:
                output_filename = f"{basename}_watermarked.{clean_ext}"
            elif "merge" in ep_clean:
                output_filename = "merged.pdf"
            else:
                output_filename = f"{basename}_{ep_clean}.{clean_ext}"

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
                "operation": endpoint.lstrip("/"),
                "endpoint": endpoint,
                "source_file": primary_file["filename"],
                "output_file": output_filename,
                "path": f"/uploads/files/output/{output_filename}",
                "size": file_size,
                "size_formatted": size_str,
                "groq_intent": groq_result
            },
            "message": f"Successfully processed '{primary_file['filename']}' -> '{output_filename}' ({size_str}) saved to Output folder",
            "error": None
        }


# Singleton Groq service instance
groq_service = GroqService()
