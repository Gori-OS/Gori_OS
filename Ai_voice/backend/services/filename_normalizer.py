import os
import re
from typing import Set, Optional, List, Dict, Tuple

# All common file extensions required by specification
CORE_FILE_EXTENSIONS: Set[str] = {
    # Images
    "jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico", "tif", "tiff", "heic",
    # Documents
    "pdf", "txt", "doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx", "rtf", "md",
    # Data & Config
    "json", "xml", "sql", "yml", "yaml", "toml", "ini", "conf", "log",
    # Archives
    "zip", "rar", "7z", "tar", "gz",
    # Audio
    "mp3", "wav", "ogg", "m4a", "flac", "aac",
    # Video
    "mp4", "avi", "mkv", "mov", "webm", "m4v", "3gp",
    # Executable & System
    "exe", "apk", "bat", "sh",
    # Code & Web
    "py", "java", "js", "ts", "html", "css", "cpp", "c", "h",
}

# Words that should NEVER be treated as a filename stem by themselves.
# These include prepositions (e.g. "to pdf"), conjunctions ("and pdf"),
# verbs ("open png", "delete txt"), articles ("the pdf"), pronouns ("me jpg"),
# and common filler words.
NON_STEM_WORDS: Set[str] = {
    # Prepositions & Conjunctions
    "to", "into", "as", "from", "of", "in", "on", "at", "by", "for", "with",
    "about", "between", "through", "over", "under", "above", "below", "and",
    "or", "but", "nor", "yet", "so", "than", "then", "after", "before", "while",
    # Articles & Demonstratives
    "the", "a", "an", "this", "that", "these", "those",
    # Pronouns & Possessives
    "my", "your", "his", "her", "its", "our", "their", "me", "you", "him", "us", "them",
    # Auxiliary & Common Verbs
    "is", "am", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    # Command Verbs & Actions
    "open", "close", "show", "view", "display", "preview", "launch", "start", "exit", "quit",
    "delete", "remove", "erase", "trash", "convert", "change", "turn", "transform", "make",
    "switch", "compress", "shrink", "optimize", "reduce", "extract", "merge", "combine",
    "split", "resize", "watermark", "add", "set", "get", "put", "run", "stop", "send",
    "upload", "download", "copy", "move", "rename", "save", "load", "find", "search",
    # Conversational & Polite Fillers
    "please", "nova", "hey", "hi", "hello", "thanks", "thank", "now", "again", "also",
    "just", "only", "very", "too", "well", "okay", "ok", "right"
}

# Single-letter extensions ('c', 'h') need strict stem validation to prevent
# false positives on common words (e.g. "switch to c", "vitamin c", "grade c", "drive c").
SAFE_SINGLE_LETTER_STEMS: Set[str] = {
    "main", "program", "code", "script", "test", "source", "header", "utils",
    "hello", "math", "sample", "file", "index", "app", "server", "client",
    "helper", "bridge", "module", "kernel", "core", "temp", "output", "input"
}

# Spelled out extension mappings (grouped by letter count descending)
SPELLED_OUT_PATTERNS = [
    # 4 letters
    (r'\b[jJ]\s+[pP]\s+[eE]\s+[gG]\b', 'jpeg'),
    (r'\b[dD]\s+[oO]\s+[cC]\s+[xX]\b', 'docx'),
    (r'\b[xX]\s+[lL]\s+[sS]\s+[xX]\b', 'xlsx'),
    (r'\b[pP]\s+[pP]\s+[tT]\s+[xX]\b', 'pptx'),
    (r'\b[wW]\s+[eE]\s+[bB]\s+[pP]\b', 'webp'),
    (r'\b[wW]\s+[eE]\s+[bB]\s+[mM]\b', 'webm'),
    (r'\b[jJ]\s+[aA]\s+[vV]\s+[aA]\b', 'java'),
    (r'\b[hH]\s+[tT]\s+[mM]\s+[lL]\b', 'html'),
    (r'\b[jJ]\s+[sS]\s+[oO]\s+[nN]\b', 'json'),
    # 3 letters
    (r'\b[jJ]\s+[pP]\s+[gG]\b', 'jpg'),
    (r'\b[pP]\s+[nN]\s+[gG]\b', 'png'),
    (r'\b[pP]\s+[dD]\s+[fF]\b', 'pdf'),
    (r'\b[gG]\s+[iI]\s+[fF]\b', 'gif'),
    (r'\b[sS]\s+[vV]\s+[gG]\b', 'svg'),
    (r'\b[bB]\s+[mM]\s+[pP]\b', 'bmp'),
    (r'\b[iI]\s+[cC]\s+[oO]\b', 'ico'),
    (r'\b[tT]\s+[xX]\s+[tT]\b', 'txt'),
    (r'\b[dD]\s+[oO]\s+[cC]\b', 'doc'),
    (r'\b[xX]\s+[lL]\s+[sS]\b', 'xls'),
    (r'\b[cCc]\s+[sS]\s+[vV]\b', 'csv'),
    (r'\b[pP]\s+[pP]\s+[tT]\b', 'ppt'),
    (r'\b[xX]\s+[mM]\s+[lL]\b', 'xml'),
    (r'\b[zZ]\s+[iI]\s+[pP]\b', 'zip'),
    (r'\b[rR]\s+[aA]\s+[rR]\b', 'rar'),
    (r'\b[mM]\s+[pP]\s*4\b', 'mp4'),
    (r'\b[mM]\s+[pP]\s*3\b', 'mp3'),
    (r'\b[mM]\s*4\s*[aA]\b', 'm4a'),
    (r'\b[wW]\s+[aA]\s+[vV]\b', 'wav'),
    (r'\b[oO]\s+[gG]\s+[gG]\b', 'ogg'),
    (r'\b[aA]\s+[vV]\s+[iI]\b', 'avi'),
    (r'\b[mM]\s+[kK]\s+[vV]\b', 'mkv'),
    (r'\b[mM]\s+[oO]\s+[vV]\b', 'mov'),
    (r'\b[eE]\s+[xX]\s+[eE]\b', 'exe'),
    (r'\b[aA]\s+[pP]\s+[kK]\b', 'apk'),
    (r'\b[cC]\s+[pP]\s+[pP]\b', 'cpp'),
    (r'\b[sS]\s+[qQ]\s+[lL]\b', 'sql'),
    (r'\b[cC]\s+[sS]\s+[sS]\b', 'css'),
    # 2 letters
    (r'\b[pP]\s+[yY]\b', 'py'),
    (r'\b[jJ]\s+[sS]\b', 'js'),
    (r'\b[tT]\s+[sS]\b', 'ts'),
    (r'\b[mM]\s+[dD]\b', 'md'),
    (r'\b7\s*[zZ]\b', '7z'),
]


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FILES_DIR = os.path.join(UPLOAD_DIR, "files")
MOBILE_DIR = os.path.join(FILES_DIR, "mobile")
PHOTOS_DIR = os.path.join(MOBILE_DIR, "photos")
OUTPUT_DIR = os.path.join(FILES_DIR, "output")


def get_available_disk_extensions(known_files: Optional[List[str]] = None) -> Set[str]:
    """Extracts extensions dynamically from available disk files to support newly encountered extensions."""
    exts = set(CORE_FILE_EXTENSIONS)
    file_list = known_files
    if file_list is None:
        file_list = []
        for d in [MOBILE_DIR, PHOTOS_DIR, OUTPUT_DIR, UPLOAD_DIR]:
            if os.path.exists(d):
                try:
                    for item in os.listdir(d):
                        p = os.path.join(d, item)
                        if os.path.isfile(p) and not item.startswith("."):
                            file_list.append(item)
                except Exception:
                    pass

    for f in file_list:
        if "." in f:
            ext = f.rsplit(".", 1)[-1].lower()
            if ext and len(ext) <= 6 and ext.isalnum():
                exts.add(ext)
    return exts



def normalize_file_command(text: str, available_files: Optional[List[str]] = None) -> str:
    """
    Intelligently normalizes speech-to-text spoken file names and extensions:
    1. Preserves URLs, emails, and decimal numbers.
    2. Normalizes spelled-out extension letters ('P N G' -> 'png', 'J P G' -> 'jpg').
    3. Normalizes spoken separators ('image dot jpg' -> 'image.jpg', 'photo point png' -> 'photo.png').
    4. Reconstructs missing dots in speech-to-text patterns:
       - 'image jpg' -> 'image.jpg'
       - 'photo png' -> 'photo.png'
       - 'document pdf' -> 'document.pdf'
       - 'song mp3' -> 'song.mp3'
       - 'video mp4' -> 'video.mp4'
       - 'file txt' -> 'file.txt'
       - 'convert image jpg to pdf' -> 'convert image.jpg to pdf'
       - 'annual report 2024 pdf' -> 'annual report 2024.pdf'
    5. Preserves existing dots and handles multi-word filenames.
    6. Protects ordinary command keywords and text.
    """
    if not text:
        return ""

    s = text.strip()

    # Step 1: Protect URLs, Emails, and Numbers with decimals using temporary placeholders
    placeholders: Dict[str, str] = {}
    placeholder_idx = 0

    def make_placeholder(val: str) -> str:
        nonlocal placeholder_idx
        token = f"__TOKEN_PH_{placeholder_idx}__"
        placeholder_idx += 1
        placeholders[token] = val
        return token

    # Protect URLs
    s = re.sub(r'https?://[^\s]+', lambda m: make_placeholder(m.group(0)), s)
    # Protect Emails
    s = re.sub(r'\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b', lambda m: make_placeholder(m.group(0)), s)
    # Protect pure decimal numbers (e.g. 3.14, 1.0, 100.50)
    s = re.sub(r'\b\d+\.\d+\b', lambda m: make_placeholder(m.group(0)), s)

    # Step 2: Spelled-out extension letters
    for pattern, repl in SPELLED_OUT_PATTERNS:
        s = re.sub(pattern, repl, s)

    # Step 3: Normalize spoken separator words: "dot", "point", "period"
    # Case a: "image dot jpg" / "photo point png" / "document period pdf"
    s = re.sub(r'(?<=[a-zA-Z0-9_\-])\s*(?:dot|point|period)\s*(?=[a-zA-Z0-9_\-])', '.', s, flags=re.IGNORECASE)
    # Case b: With whitespace around separator followed by word: "photo dot png"
    s = re.sub(r'\s+(?:dot|point|period)\s+([a-zA-Z0-9]+)', r'.\1', s, flags=re.IGNORECASE)
    # Case c: Standalone dot words: "photo dot"
    s = re.sub(r'\s+(?:dot|point|period)\b', '.', s, flags=re.IGNORECASE)
    # Collapse any space around dots: "photo . png" -> "photo.png"
    s = re.sub(r'\s*\.\s*', '.', s)

    # Step 4: Reconstruct missing dots for speech-to-text file extensions
    # Pattern: `<stem_word> <extension_word>`
    # e.g. "image jpg" -> "image.jpg", "photo png" -> "photo.png"
    all_extensions = get_available_disk_extensions(available_files)

    # Regex to find word boundaries where second word is a potential extension
    # Words can be letters, digits, underscores, hyphens
    tokens = s.split(" ")
    reconstructed_tokens = []
    i = 0
    num_tokens = len(tokens)

    while i < num_tokens:
        tok = tokens[i]
        
        # Check if next token is a recognized extension
        if i + 1 < num_tokens:
            next_tok = tokens[i + 1]
            # Strip trailing punctuation from next_tok for check (e.g. "jpg," or "png.")
            next_clean = re.sub(r'[^\w]', '', next_tok)
            next_lower = next_clean.lower()
            
            # Check if tok is not empty and next_tok is a known extension
            if tok and next_lower in all_extensions:
                # Extract the trailing word of tok (in case tok has punctuation or is alphanumeric)
                tok_clean = re.sub(r'^[^\w]+|[^\w]+$', '', tok)
                tok_lower = tok_clean.lower()

                # Conditions under which tok CANNOT be a stem:
                # 1. tok is in NON_STEM_WORDS (e.g. "to pdf", "into png", "open jpg", "the mp3", "and docx")
                # 2. tok already ends with a dot or has this extension (e.g. "image.jpg jpg")
                # 3. tok is empty or just punctuation
                # 4. For single-letter extensions ('c', 'h'), tok must be in SAFE_SINGLE_LETTER_STEMS
                is_non_stem = tok_lower in NON_STEM_WORDS
                already_has_ext = tok_lower.endswith("." + next_lower) or tok.endswith(".")
                
                single_letter_valid = True
                if next_lower in ("c", "h"):
                    single_letter_valid = (tok_lower in SAFE_SINGLE_LETTER_STEMS) or (
                        available_files is not None and any(
                            f.lower() == f"{tok_lower}.{next_lower}" for f in available_files
                        )
                    )

                if (not is_non_stem) and (not already_has_ext) and single_letter_valid and len(tok_clean) > 0:
                    # Check if tok ends with the same extension already (e.g. "photo.png png")
                    if tok_lower.endswith(f".{next_lower}"):
                        # Redundant extension repetition, skip next_tok
                        reconstructed_tokens.append(tok)
                        i += 2
                        continue

                    # Determine punctuation attached to next_tok
                    trailing_punct = next_tok[len(next_clean):] if next_tok.startswith(next_clean) else ""
                    
                    # Reconstruct as <tok>.<next_lower><trailing_punct>
                    combined = f"{tok}.{next_lower}{trailing_punct}"
                    reconstructed_tokens.append(combined)
                    i += 2
                    continue

        reconstructed_tokens.append(tok)
        i += 1

    s = " ".join(reconstructed_tokens)

    # Clean double dots if any occurred: "photo..png" -> "photo.png"
    s = re.sub(r'\.{2,}', '.', s)

    # Step 5: Restore protected numbers, emails, and URLs
    for token, original in placeholders.items():
        s = s.replace(token, original)

    # Collapse redundant whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s
