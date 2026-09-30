import time
import os
import re
import urllib.parse
from typing import Dict, Any, Optional
from backend.services.system_service import SystemService
from backend.services.file_processing_service import file_processing_service, normalize_spoken_filename_patterns
from backend.services.filename_normalizer import normalize_file_command
from backend.services.groq_service import groq_service

# Canonical application alias map and metadata
APP_TARGETS = {
    "nova voice": "nova-voice",
    "novavoice": "nova-voice",
    "nova": "nova-voice",
    "voice": "nova-voice",
    "voice agent": "nova-voice",
    "voice app": "nova-voice",
    "mic": "nova-voice",
    "terminal": "terminal",
    "cmd": "terminal",
    "console": "terminal",
    "command prompt": "terminal",
    "shell": "terminal",
    "files": "files",
    "file": "files",
    "file manager": "files",
    "file explorer": "files",
    "file browser": "files",
    "uploads": "files",
    "text editor": "editor",
    "texteditor": "editor",
    "editor": "editor",
    "notepad": "editor",
    "notes": "editor",
    "settings": "settings",
    "setting": "settings",
    "config": "settings",
    "preferences": "settings",
    "options": "settings",
    "bridge settings": "settings",
    "workspace": "workspace",
    "work space": "workspace",
    # Integrated WebView Browser targets
    "browser": "browser",
    "chrome": "browser",
    "google chrome": "browser",
    "google": "browser",
    "web browser": "browser",
    "web": "browser",
    "internet": "browser",
    "safari": "browser",
    "edge": "browser",
    "preview": "preview",
    "viewer": "preview",
    "image viewer": "preview",
}

VALID_APP_IDS = ["terminal", "files", "editor", "settings", "workspace", "nova-voice", "browser", "preview"]

APP_FRIENDLY_NAMES = {
    "nova-voice": "Nova Voice",
    "files": "Files",
    "terminal": "Terminal",
    "editor": "Text Editor",
    "settings": "Settings",
    "workspace": "Workspace",
    "browser": "Browser",
    "preview": "Preview Viewer",
}

OPEN_VERBS_REGEX = re.compile(r'^(open\s+up|open|launch|start)\b', re.IGNORECASE)
CLOSE_VERBS_REGEX = re.compile(r'^(close\s+down|close|exit|quit|shut\s+down|shutdown|shut|kill|dismiss)\b', re.IGNORECASE)
SHOW_VERBS_REGEX = re.compile(r'^(show\s+me|show|display|view|preview)\b', re.IGNORECASE)
PLAY_VERBS_REGEX = re.compile(r'^(?:play\s+audio|play\s+music|play\s+file|play|listen\s+to)\b', re.IGNORECASE)
PAUSE_VERBS_REGEX = re.compile(r'^(?:pause\s+audio|pause\s+music|pause)\b', re.IGNORECASE)
RESUME_VERBS_REGEX = re.compile(r'^(?:resume\s+audio|resume\s+music|resume|unpause)\b', re.IGNORECASE)
SEARCH_VERBS_REGEX = re.compile(
    r'^(?:search\s+for|search\s+on\s+google\s+for|search\s+google\s+for|search\s+on\s+google|search\s+google|search|google\s+search|google|look\s+up|find\s+on\s+google)\s+(.+)$',
    re.IGNORECASE
)

class CommandService:
    @staticmethod
    def classify_target_device(raw_cmd: str, client_hint: str = "computer") -> str:
        """
        Classifies target device for command execution: 'phone' vs 'computer'.
        Guarantees phone-specific commands execute on phone and computer commands on computer.
        """
        cmd_lower = raw_cmd.lower().strip()
        
        # Explicit device designations
        if any(kw in cmd_lower for kw in ("on my phone", "on the phone", "on phone", "on mobile", "on android")):
            return "phone"
        if any(kw in cmd_lower for kw in ("on computer", "on pc", "on desktop", "on laptop", "in workspace")):
            return "computer"

        # Phone-native features
        phone_keywords = [
            "flashlight", "torch", "turn on flashlight", "turn off flashlight",
            "take a photo", "take photo", "capture photo", "snap photo", "open camera", "front camera", "back camera",
            "vibrate phone", "vibrate", "phone battery", "call ", "dial "
        ]
        if any(kw in cmd_lower for kw in phone_keywords):
            return "phone"

        return "computer"

    @staticmethod
    def process(command_text: str, client_context: Optional[str] = None) -> Dict[str, Any]:
        """
        Single reliable command-routing pipeline:
        Voice/Text Input → Command Understanding → Intent Detection → Target Device Detection
        → Action Resolution → Endpoint/Function Selection → Execution → Result
        """
        start_time = time.perf_counter()
        raw_cmd = (command_text or "").strip()
        disk_files = file_processing_service.list_available_files()
        norm_spoken = normalize_file_command(raw_cmd, available_files=disk_files)
        cmd = norm_spoken.lower()
        
        # Clean punctuation while preserving : and / for URLs
        clean_cmd = re.sub(r'[^\w\s\.\-\:\/]', '', cmd).strip()

        # Speech-friendly command normalisation:
        # Strip leading filler words/phrases
        while True:
            stripped = re.sub(
                r'^(please|can\s+you\s+please|could\s+you\s+please|can\s+you|could\s+you|would\s+you|will\s+you|hey\s+nova|hi\s+nova|hello\s+nova|nova)\s+',
                '',
                clean_cmd,
                flags=re.IGNORECASE
            ).strip()
            if stripped == clean_cmd:
                break
            clean_cmd = stripped

        # Strip trailing filler words/phrases
        while True:
            stripped = re.sub(
                r'\s+(please|now|right\s+now|thank\s+you|thanks|for\s+me)$',
                '',
                clean_cmd,
                flags=re.IGNORECASE
            ).strip()
            if stripped == clean_cmd:
                break
            clean_cmd = stripped

        # Clean punctuation from ends
        clean_cmd = re.sub(r'[\.\!\?\,\;]+$', '', clean_cmd).strip()
        clean_cmd = re.sub(r'^[^\w]+', '', clean_cmd).strip()

        # 1. Target Device Detection
        target_device = CommandService.classify_target_device(raw_cmd, client_hint=client_context or "computer")

        # 2. Phone-Specific Command Execution
        if target_device == "phone":
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            if any(kw in clean_cmd for kw in ("flashlight", "torch")):
                is_on = "off" not in clean_cmd
                return {
                    "status": "completed",
                    "target_device": "phone",
                    "action": {
                        "action": "phone.flashlight",
                        "state": "on" if is_on else "off"
                    },
                    "message": f"Turned {'on' if is_on else 'off'} phone flashlight",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }
            if any(kw in clean_cmd for kw in ("photo", "camera", "picture")):
                return {
                    "status": "completed",
                    "target_device": "phone",
                    "action": {
                        "action": "phone.camera",
                        "mode": "capture"
                    },
                    "message": "Opened phone camera to take photo",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }
            if "vibrate" in clean_cmd:
                return {
                    "status": "completed",
                    "target_device": "phone",
                    "action": {
                        "action": "phone.vibrate"
                    },
                    "message": "Phone vibrated",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }
            if "battery" in clean_cmd:
                return {
                    "status": "completed",
                    "target_device": "phone",
                    "action": {
                        "action": "phone.battery"
                    },
                    "message": "Checking phone battery status",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }

        # Check for conflicting verbs (e.g. "open and close terminal")
        has_open_verb = bool(re.search(r'\b(open|launch|start)\b', clean_cmd))
        has_close_verb = bool(re.search(r'\b(close|exit|quit|shut\s+down|shutdown|shut|kill|dismiss)\b', clean_cmd))
        if has_open_verb and has_close_verb:
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "failed",
                "target_device": "computer",
                "action": {
                    "action": "unknown",
                    "target": None
                },
                "message": "Cannot perform both open and close in a single command. Please specify one action.",
                "execution_time_ms": elapsed_ms,
                "error": "CONFLICTING_COMMANDS"
            }

        # Strip any trailing punctuation that might remain after filler words
        clean_cmd = re.sub(r'[\.\!\?\,\;]+$', '', clean_cmd).strip()

        # 3. Audio Playback Controls (Pause / Resume)
        if PAUSE_VERBS_REGEX.match(clean_cmd):
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "media.pause",
                    "target": "preview"
                },
                "message": "Paused audio playback",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        if RESUME_VERBS_REGEX.match(clean_cmd):
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "media.resume",
                    "target": "preview"
                },
                "message": "Resumed audio playback",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # 4. Audio Playback Command ("play song.mp3", "play song", "play audio", "play music")
        play_match = PLAY_VERBS_REGEX.match(clean_cmd)
        if play_match:
            raw_play_target = clean_cmd[len(play_match.group(0)):].strip()
            # 1. Try raw target directly (e.g. "song.mp3")
            found_file = file_processing_service.find_file(raw_play_target) if raw_play_target else None

            clean_play_target = raw_play_target
            if not found_file and raw_play_target:
                clean_play_target = re.sub(r'^(?:the|my|this|that|a|an)\s+', '', raw_play_target, flags=re.IGNORECASE).strip()
                clean_play_target = re.sub(r'\s+(?:please|now|right\s+now|thank\s+you|thanks|for\s+me)$', '', clean_play_target, flags=re.IGNORECASE).strip()
                found_file = file_processing_service.find_file(clean_play_target)
                if not found_file:
                    clean_play_target2 = re.sub(r'^(?:song|file|audio|music|track)\s+', '', clean_play_target, flags=re.IGNORECASE).strip()
                    if clean_play_target2 and not clean_play_target2.startswith('.'):
                        found_file = file_processing_service.find_file(clean_play_target2)

            if not found_file and not clean_play_target:
                # If user simply said "play" or "play music" or "play song", look for any audio file available or resume
                avail = file_processing_service.list_available_files()
                audio_files = [f for f in avail if f.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac'))]
                if audio_files:
                    chosen = "song.mp3" if "song.mp3" in audio_files else audio_files[0]
                    found_file = file_processing_service.find_file(chosen)

            if found_file:
                # If target was resolved to non-audio but an audio file exists with the same name, prefer the audio file
                fn_stem, fn_ext = os.path.splitext(found_file["filename"])
                if fn_ext.lower() not in ('.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac'):
                    audio_cand = file_processing_service.find_file(f"{fn_stem}.mp3")
                    if audio_cand:
                        found_file = audio_cand

                elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                fn = found_file["filename"]
                full_p = found_file["path"]
                rel_web_path = "/uploads/" + full_p.replace("\\", "/").split("uploads/", 1)[-1] if "uploads" in full_p else f"/uploads/files/mobile/{fn}"
                if not rel_web_path.startswith("/uploads/"):
                    rel_web_path = "/uploads/" + rel_web_path.lstrip("/")

                return {
                    "status": "completed",
                    "target_device": "computer",
                    "action": {
                        "action": "media.play",
                        "target": "preview",
                        "filename": fn,
                        "url": rel_web_path,
                        "path": rel_web_path,
                        "file_type": "audio",
                        "autoplay": True
                    },
                    "message": f"Playing {fn}",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }
            elif clean_play_target:
                elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                return {
                    "status": "failed",
                    "target_device": "computer",
                    "action": {
                        "action": "file.error",
                        "source_file": clean_play_target
                    },
                    "message": f"Audio file '{clean_play_target}' not found in workspace or uploads.",
                    "execution_time_ms": elapsed_ms,
                    "error": "FILE_NOT_FOUND"
                }
            else:
                elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                return {
                    "status": "completed",
                    "target_device": "computer",
                    "action": {
                        "action": "media.resume",
                        "target": "preview"
                    },
                    "message": "Resumed audio playback",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }

        # 5. Web Search Commands ("search capital of India", "search for ...", "google ...")
        search_m = SEARCH_VERBS_REGEX.match(clean_cmd)
        if search_m:
            search_query = search_m.group(1).strip()
            search_query = re.sub(r'^(?:for|about|on)\s+', '', search_query, flags=re.IGNORECASE).strip()
            search_query = re.sub(r'\s+(?:on\s+google|in\s+google|using\s+google|please|now|for\s+me)$', '', search_query, flags=re.IGNORECASE).strip()
            if search_query:
                elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                encoded_q = urllib.parse.quote(search_query)
                encoded_plus = urllib.parse.quote_plus(search_query)
                local_search_url = f"/api/browser/search?q={encoded_q}&redirect=https://www.google.com/search?q={encoded_plus}"
                display_url = f"https://www.google.com/search?q={encoded_plus}"
                return {
                    "status": "completed",
                    "target_device": "computer",
                    "action": {
                        "action": "app.open",
                        "target": "browser",
                        "url": local_search_url,
                        "display_url": display_url,
                        "query": search_query,
                        "is_search": True
                    },
                    "message": f"Searching Google for '{search_query}'",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }

        # 6. Natural-Language File Opening / Viewing (Images, PDFs, Documents, Converted Files)
        # Handles: "Show me image.jpg", "Open image.jpg", "Show image.jpg", "Open the image",
        # "Display image.jpg", "Show me this file", "Open the PDF", "Show me the document",
        # "Show me the converted file", "Open my image"
        file_verb_match = SHOW_VERBS_REGEX.search(clean_cmd) or OPEN_VERBS_REGEX.search(clean_cmd)
        if file_verb_match:
            verb_matched = file_verb_match.group(0).lower()
            raw_target_candidate = clean_cmd[len(file_verb_match.group(0)):].strip()

            # Clean leading possessives/articles: "the", "my", "this", "that", "a", "an"
            clean_file_candidate = re.sub(r'^(?:the|my|this|that|a|an)\s+', '', raw_target_candidate, flags=re.IGNORECASE).strip()

            # Check if this candidate is an application name first (only for OPEN verbs)
            is_app_candidate = (
                OPEN_VERBS_REGEX.search(verb_matched) and
                (clean_file_candidate in APP_TARGETS or clean_file_candidate in VALID_APP_IDS)
            )

            # Check if this candidate is a web URL or domain
            is_url_candidate = (
                OPEN_VERBS_REGEX.search(verb_matched) and
                (clean_file_candidate.startswith(('http://', 'https://')) or
                 any(clean_file_candidate.endswith(f'.{tld}') for tld in ('com', 'org', 'net', 'io', 'ai', 'gov', 'edu', 'co', 'dev', 'app', 'uk', 'in', 'html')))
            )
            if is_url_candidate:
                web_url = clean_file_candidate if clean_file_candidate.startswith(('http://', 'https://')) else f"https://{clean_file_candidate}"
                elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                return {
                    "status": "completed",
                    "target_device": "computer",
                    "action": {
                        "action": "app.open",
                        "target": "browser",
                        "url": web_url,
                        "display_url": web_url
                    },
                    "message": f"Opened {web_url} in browser",
                    "execution_time_ms": elapsed_ms,
                    "error": None
                }

            if not is_app_candidate and raw_target_candidate:
                found_file = file_processing_service.find_file(clean_file_candidate)
                if not found_file:
                    found_file = file_processing_service.find_file(raw_target_candidate)

                if found_file:
                    elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                    fn = found_file["filename"]
                    _, ext = os.path.splitext(fn)
                    ext_clean = ext.lstrip(".").lower()

                    # Classify file type for UI preview component
                    if ext_clean in ("png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff", "heic", "svg", "ico"):
                        f_type = "image"
                    elif ext_clean == "pdf":
                        f_type = "pdf"
                    elif ext_clean in ("mp4", "mov", "avi", "mkv", "webm", "m4v"):
                        f_type = "video"
                    elif ext_clean in ("mp3", "wav", "m4a", "ogg", "flac", "aac"):
                        f_type = "audio"
                    elif ext_clean in ("txt", "md", "log", "py", "js", "ts", "html", "css", "c", "cpp", "h"):
                        f_type = "text"
                    elif ext_clean in ("csv", "json", "xlsx", "xls", "xml", "sql"):
                        f_type = "data"
                    else:
                        f_type = "file"

                    # Calculate relative upload path
                    full_p = found_file["path"]
                    rel_p = os.path.relpath(full_p, os.path.dirname(os.path.dirname(full_p)))
                    rel_web_path = "/" + full_p.replace("\\", "/").split("uploads/", 1)[-1] if "uploads" in full_p else f"/uploads/files/mobile/{fn}"
                    if not rel_web_path.startswith("/uploads/"):
                        rel_web_path = "/uploads/" + rel_web_path.lstrip("/")

                    return {
                        "status": "completed",
                        "target_device": "computer",
                        "action": {
                            "action": "file.open",
                            "target": "preview",
                            "filename": fn,
                            "url": rel_web_path,
                            "path": rel_web_path,
                            "file_type": f_type
                        },
                        "message": f"Opened {fn}",
                        "execution_time_ms": elapsed_ms,
                        "error": None
                    }
                else:
                    has_ext = bool(re.search(r'\.[a-zA-Z0-9]{1,6}$', clean_file_candidate))
                    is_show_verb = bool(SHOW_VERBS_REGEX.search(verb_matched))
                    if has_ext or is_show_verb:
                        elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                        target_disp = clean_file_candidate or raw_target_candidate
                        return {
                            "status": "failed",
                            "target_device": "computer",
                            "action": {
                                "action": "file.error",
                                "source_file": target_disp
                            },
                            "message": f"File '{target_disp}' not found in workspace or uploads.",
                            "execution_time_ms": elapsed_ms,
                            "error": "FILE_NOT_FOUND"
                        }

        # 4. Open or Close Application by Verb
        verb = None
        raw_target = None
        if OPEN_VERBS_REGEX.search(clean_cmd):
            verb = "open"
            raw_target = OPEN_VERBS_REGEX.sub('', clean_cmd).strip()
        elif CLOSE_VERBS_REGEX.search(clean_cmd):
            verb = "close"
            raw_target = CLOSE_VERBS_REGEX.sub('', clean_cmd).strip()

        if verb is not None:
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            if not raw_target:
                action_word = "open" if verb == "open" else "close"
                return {
                    "status": "failed",
                    "target_device": "computer",
                    "action": {
                        "action": "unknown",
                        "target": None
                    },
                    "message": f"Please specify which app to {action_word}. Available apps: terminal, files, editor, settings, workspace, nova-voice.",
                    "execution_time_ms": elapsed_ms,
                    "error": "MISSING_APP_TARGET"
                }

            # Normalise target: drop leading articles and trailing noun indicators/courtesy words
            target = raw_target
            while True:
                prev = target
                target = re.sub(r'^(the|my|a|an)\s+', '', target, flags=re.IGNORECASE).strip()
                target = re.sub(r'\s+(app|window|application|program)$', '', target, flags=re.IGNORECASE).strip()
                target = re.sub(r'\s+(please|now|right\s+now|thank\s+you|thanks|for\s+me)$', '', target, flags=re.IGNORECASE).strip()
                if target == prev:
                    break

            app_id = APP_TARGETS.get(target)
            if not app_id and target in VALID_APP_IDS:
                app_id = target

            # Check if user said "open <file>" but target was not an app
            if not app_id and verb == "open":
                found_file = file_processing_service.find_file(target)
                if found_file:
                    fn = found_file["filename"]
                    _, ext = os.path.splitext(fn)
                    ext_clean = ext.lstrip(".").lower()
                    f_type = "image" if ext_clean in ("png", "jpg", "jpeg", "webp", "bmp", "gif") else ("pdf" if ext_clean == "pdf" else "file")
                    full_p = found_file["path"]
                    rel_web_path = "/uploads/" + full_p.replace("\\", "/").split("uploads/", 1)[-1] if "uploads" in full_p else f"/uploads/files/mobile/{fn}"
                    return {
                        "status": "completed",
                        "target_device": "computer",
                        "action": {
                            "action": "file.open",
                            "target": "preview",
                            "filename": fn,
                            "url": rel_web_path,
                            "path": rel_web_path,
                            "file_type": f_type
                        },
                        "message": f"Opened {fn}",
                        "execution_time_ms": elapsed_ms,
                        "error": None
                    }
                elif "." in target or bool(re.search(r'\.[a-zA-Z0-9]{1,6}$', target)):
                    return {
                        "status": "failed",
                        "target_device": "computer",
                        "action": {
                            "action": "file.error",
                            "source_file": target
                        },
                        "message": f"File '{target}' not found in workspace or uploads.",
                        "execution_time_ms": elapsed_ms,
                        "error": "FILE_NOT_FOUND"
                    }

            # Check if user said "open <url>" (e.g. "open https://github.com", "open google.com")
            if not app_id and verb == "open":
                if target.startswith(('http://', 'https://')) or ('.' in target and any(target.endswith(f'.{tld}') for tld in ('com', 'org', 'net', 'io', 'ai', 'edu', 'gov', 'co', 'dev', 'app', 'uk', 'in', 'html'))):
                    web_url = target if target.startswith(('http://', 'https://')) else f"https://{target}"
                    elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
                    return {
                        "status": "completed",
                        "target_device": "computer",
                        "action": {
                            "action": "app.open",
                            "target": "browser",
                            "url": web_url,
                            "display_url": web_url
                        },
                        "message": f"Opened {web_url} in browser",
                        "execution_time_ms": elapsed_ms,
                        "error": None
                    }

            if not app_id:
                return {
                    "status": "failed",
                    "target_device": "computer",
                    "action": {
                        "action": "unknown",
                        "target": None
                    },
                    "message": f"Unknown app '{target}'. Try: terminal, files, editor, settings, workspace, nova-voice, browser",
                    "execution_time_ms": elapsed_ms,
                    "error": "UNKNOWN_APP"
                }

            friendly_name = APP_FRIENDLY_NAMES.get(app_id, app_id.title())
            if verb == "open":
                if app_id == "browser" and target in ("google", "google.com", "google chrome"):
                    action = {
                        "action": "app.open",
                        "target": "browser",
                        "url": "/api/browser/search?q=&redirect=https://www.google.com",
                        "display_url": "https://www.google.com"
                    }
                    msg = "Opened Google in browser"
                else:
                    action = SystemService.open_application(app_id)
                    msg = f"Opened {friendly_name}"
            else:
                action = SystemService.close_application(app_id)
                msg = f"Closed {friendly_name}"

            return {
                "status": "completed",
                "target_device": "computer",
                "action": action,
                "message": msg,
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # 5. Direct App Name (e.g. "terminal", "browser", "chrome")
        direct_target = re.sub(r'^(the|my)\s+', '', clean_cmd).strip()
        if direct_target in APP_TARGETS or direct_target in VALID_APP_IDS:
            app_id = APP_TARGETS.get(direct_target, direct_target)
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            friendly_name = APP_FRIENDLY_NAMES.get(app_id, app_id.title())
            return {
                "status": "completed",
                "target_device": "computer",
                "action": SystemService.open_application(app_id),
                "message": f"Opened {friendly_name}",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # 6. Workspace Command Suite
        # Planner / Tasks: "add task ...", "complete task ...", "delete task ...", "show tasks"
        add_task_m = re.match(r'^(?:add\s+task|create\s+task|new\s+task)\s+(.+)$', clean_cmd, re.IGNORECASE)
        if add_task_m:
            task_title = add_task_m.group(1).strip()
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.add_task",
                    "target": "workspace",
                    "title": task_title
                },
                "message": f"Added task '{task_title}' to Planner",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        comp_task_m = re.match(r'^(?:complete\s+task|finish\s+task|check\s+task|done\s+task)\s+(.+)$', clean_cmd, re.IGNORECASE)
        if comp_task_m:
            task_title = comp_task_m.group(1).strip()
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.complete_task",
                    "target": "workspace",
                    "title": task_title
                },
                "message": f"Marked task '{task_title}' completed",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        del_task_m = re.match(r'^(?:delete\s+task|remove\s+task)\s+(.+)$', clean_cmd, re.IGNORECASE)
        if del_task_m:
            task_title = del_task_m.group(1).strip()
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.delete_task",
                    "target": "workspace",
                    "title": task_title
                },
                "message": f"Removed task '{task_title}'",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # File Deletion: "delete document.pdf", "remove image.jpg"
        del_file_m = re.match(r'^(?:delete|remove|erase|trash)\s+(.+)$', clean_cmd, re.IGNORECASE)
        if del_file_m:
            raw_del_target = del_file_m.group(1).strip()
            clean_del_target = re.sub(r'^(?:the|my|this|that|a|an|file|document)\s+', '', raw_del_target, flags=re.IGNORECASE).strip()
            clean_del_target = re.sub(r'\s+(?:please|now|right\s+now|thank\s+you|thanks|for\s+me)$', '', clean_del_target, flags=re.IGNORECASE).strip()

            found_file = file_processing_service.find_file(clean_del_target) or file_processing_service.find_file(raw_del_target)
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))

            if found_file:
                fp = found_file["path"]
                fn = found_file["filename"]
                try:
                    if os.path.exists(fp) and os.path.isfile(fp):
                        os.remove(fp)
                    return {
                        "status": "completed",
                        "target_device": "computer",
                        "action": {
                            "action": "file.deleted",
                            "filename": fn,
                            "path": fp
                        },
                        "message": f"Successfully deleted '{fn}'",
                        "execution_time_ms": elapsed_ms,
                        "error": None
                    }
                except Exception as e:
                    return {
                        "status": "failed",
                        "target_device": "computer",
                        "action": {"action": "file.error", "source_file": fn},
                        "message": f"Failed to delete '{fn}': {str(e)}",
                        "execution_time_ms": elapsed_ms,
                        "error": "DELETE_FAILED"
                    }
            else:
                target_name = clean_del_target or raw_del_target
                return {
                    "status": "failed",
                    "target_device": "computer",
                    "action": {
                        "action": "file.error",
                        "source_file": target_name
                    },
                    "message": f"File '{target_name}' not found to delete.",
                    "execution_time_ms": elapsed_ms,
                    "error": "FILE_NOT_FOUND"
                }

        # File Renaming: "rename old.png to new.png"
        rename_file_m = re.match(r'^(?:rename)\s+(.+?)\s+(?:to|into|as)\s+(.+)$', clean_cmd, re.IGNORECASE)
        if rename_file_m:
            src_raw = rename_file_m.group(1).strip()
            dst_raw = rename_file_m.group(2).strip()
            src_clean = re.sub(r'^(?:the|my|this|that|a|an|file)\s+', '', src_raw, flags=re.IGNORECASE).strip()
            dst_clean = re.sub(r'^(?:the|my|this|that|a|an|file)\s+', '', dst_raw, flags=re.IGNORECASE).strip()
            found_file = file_processing_service.find_file(src_clean) or file_processing_service.find_file(src_raw)
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            if found_file:
                old_p = found_file["path"]
                dir_p = os.path.dirname(old_p)
                new_fn = dst_clean
                new_p = os.path.join(dir_p, new_fn)
                try:
                    os.rename(old_p, new_p)
                    return {
                        "status": "completed",
                        "target_device": "computer",
                        "action": {
                            "action": "file.renamed",
                            "old_filename": found_file["filename"],
                            "new_filename": new_fn,
                            "path": new_p
                        },
                        "message": f"Renamed '{found_file['filename']}' to '{new_fn}'",
                        "execution_time_ms": elapsed_ms,
                        "error": None
                    }
                except Exception as e:
                    return {
                        "status": "failed",
                        "target_device": "computer",
                        "action": {"action": "file.error", "source_file": found_file["filename"]},
                        "message": f"Failed to rename '{found_file['filename']}': {str(e)}",
                        "execution_time_ms": elapsed_ms,
                        "error": "RENAME_FAILED"
                    }
            else:
                return {
                    "status": "failed",
                    "target_device": "computer",
                    "action": {"action": "file.error", "source_file": src_clean},
                    "message": f"File '{src_clean}' not found to rename.",
                    "execution_time_ms": elapsed_ms,
                    "error": "FILE_NOT_FOUND"
                }

        if clean_cmd in ("show tasks", "list tasks", "my tasks", "open planner"):
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.switch_tab",
                    "target": "workspace",
                    "tab": "planner"
                },
                "message": "Opened Workspace Planner",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # Documents: "create document ...", "open document ..."
        create_doc_m = re.match(r'^(?:create\s+document|new\s+document|new\s+doc|create\s+doc)\s*(.*)$', clean_cmd, re.IGNORECASE)
        if create_doc_m:
            doc_title = create_doc_m.group(1).strip() or "Untitled Document"
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.create_doc",
                    "target": "workspace",
                    "title": doc_title
                },
                "message": f"Created document '{doc_title}' in Workspace",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # Spreadsheets: "create sheet ...", "set cell A1 to 100"
        create_sheet_m = re.match(r'^(?:create\s+sheet|new\s+sheet|create\s+spreadsheet|new\s+spreadsheet)\s*(.*)$', clean_cmd, re.IGNORECASE)
        if create_sheet_m:
            sheet_title = create_sheet_m.group(1).strip() or "Sheet 1"
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.create_sheet",
                    "target": "workspace",
                    "title": sheet_title
                },
                "message": f"Created sheet '{sheet_title}' in Workspace",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        set_cell_m = re.match(r'^(?:set\s+cell|set)\s+([A-Za-z]+[1-9]\d*)\s+(?:to|=)\s+(.+)$', clean_cmd, re.IGNORECASE)
        if set_cell_m:
            cell_ref = set_cell_m.group(1).upper()
            cell_val = set_cell_m.group(2).strip()
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.set_cell",
                    "target": "workspace",
                    "cell": cell_ref,
                    "value": cell_val
                },
                "message": f"Set cell {cell_ref} to '{cell_val}' in Workspace",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # Tab Switching
        tab_switch_m = re.match(r'^(?:switch\s+to|open)\s+(documents|docs|spreadsheets|sheets|planner|tasks)$', clean_cmd, re.IGNORECASE)
        if tab_switch_m:
            tab_target = tab_switch_m.group(1).lower()
            canonical_tab = "documents" if tab_target in ("documents", "docs") else ("sheets" if tab_target in ("spreadsheets", "sheets") else "planner")
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "workspace.switch_tab",
                    "target": "workspace",
                    "tab": canonical_tab
                },
                "message": f"Switched Workspace to {canonical_tab.title()}",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # 7. Screenshot Stub
        if any(kw in clean_cmd for kw in ["screenshot", "capture screen", "take screenshot", "screen capture", "snapshot"]):
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "system.screenshot",
                    "target": "display"
                },
                "message": "Screenshot captured and saved to desktop.",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # 8. System Status / Telemetry
        if clean_cmd in ["status", "system status", "ping", "info", "system info"]:
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "system.status"
                },
                "message": "Nova OS Bridge is active and listening.",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # 9. Help
        if clean_cmd in ["help", "commands", "what can you do"]:
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "completed",
                "target_device": "computer",
                "action": {
                    "action": "system.help"
                },
                "message": "Available commands: open/close [apps], show [files/images], convert [files], workspace [tasks/docs/sheets], take screenshot, status, help",
                "execution_time_ms": elapsed_ms,
                "error": None
            }

        # 10. File Processing & Conversion Tasks
        # Prioritize deterministic / local matching first for 0ms AI overhead and instant execution
        file_parsed = file_processing_service.parse_command(norm_spoken)
        if file_parsed:
            res = file_processing_service.execute_processing(file_parsed)
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            res["execution_time_ms"] = elapsed_ms
            res["target_device"] = "computer"
            if res.get("status") == "completed" or res.get("error") in (
                "FILE_NOT_FOUND", "NO_MATCHING_ENDPOINT", "BACKEND_UNAVAILABLE", "BACKEND_TIMEOUT", "UPLOAD_FAILED", "SAVE_ERROR"
            ):
                return res

        # Fallback to Groq intent understanding for complex, non-standard natural phrasing
        if groq_service.is_available():
            groq_res = groq_service.process_with_groq(norm_spoken)
            elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            groq_res["execution_time_ms"] = elapsed_ms
            groq_res["target_device"] = "computer"
            if groq_res.get("status") == "completed" or groq_res.get("error") in (
                "FILE_NOT_FOUND", "NO_MATCHING_ENDPOINT", "BACKEND_UNAVAILABLE", "BACKEND_TIMEOUT", "UPLOAD_FAILED", "SAVE_ERROR"
            ):
                return groq_res

        # 11. Graceful fallback for unrecognized commands
        elapsed_ms = max(1, int((time.perf_counter() - start_time) * 1000))
        return {
            "status": "failed",
            "target_device": target_device,
            "action": {
                "action": "unknown",
                "target": None
            },
            "message": f"Command not recognized: '{raw_cmd}'. Try 'help' or 'open terminal'.",
            "execution_time_ms": elapsed_ms,
            "error": "UNKNOWN_COMMAND"
        }
