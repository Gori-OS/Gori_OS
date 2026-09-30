import os
import sys
import unittest
from unittest.mock import patch, MagicMock

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.services.filename_normalizer import (
    normalize_file_command,
    CORE_FILE_EXTENSIONS,
    get_available_disk_extensions
)
from backend.services.command_service import CommandService
from backend.services.file_processing_service import file_processing_service, UPLOAD_DIR


class TestFileNameAndExtensionNormalization(unittest.TestCase):
    """
    Comprehensive test suite for the global file name and file extension normalization layer.
    Verifies speech-to-text pattern reconstruction, preservation of existing files,
    casing consistency, space preservation, and execution through CommandService.
    """

    def test_01_required_speech_to_text_pairs(self):
        """
        Verifies core required patterns from specification:
        * image jpg -> image.jpg
        * photo png -> photo.png
        * document pdf -> document.pdf
        * song mp3 -> song.mp3
        * video mp4 -> video.mp4
        * file txt -> file.txt
        """
        test_cases = [
            ("image jpg", "image.jpg"),
            ("photo png", "photo.png"),
            ("document pdf", "document.pdf"),
            ("song mp3", "song.mp3"),
            ("video mp4", "video.mp4"),
            ("file txt", "file.txt"),
        ]
        for spoken, expected in test_cases:
            with self.subTest(spoken=spoken):
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_02_required_phrases_and_commands(self):
        """
        Verifies required command phrases from specification:
        * show me image jpg -> show me image.jpg
        * open photo png -> open photo.png
        * delete document pdf -> delete document.pdf
        * convert image jpg to pdf -> convert image.jpg to pdf
        """
        phrases = [
            ("show me image jpg", "show me image.jpg"),
            ("open photo png", "open photo.png"),
            ("delete document pdf", "delete document.pdf"),
            ("convert image jpg to pdf", "convert image.jpg to pdf"),
            ("convert image jpg into pdf", "convert image.jpg into pdf"),
            ("turn vacation photo png into jpg", "turn vacation photo.png into jpg"),
            ("merge report 1 pdf and report 2 pdf to pdf", "merge report 1.pdf and report 2.pdf to pdf"),
            ("extract images from document pdf", "extract images from document.pdf"),
            ("compress video mp4", "compress video.mp4"),
        ]
        for spoken, expected in phrases:
            with self.subTest(spoken=spoken):
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_03_all_42_supported_extensions(self):
        """
        Verifies all 42 required file extensions:
        jpg, jpeg, png, gif, webp, svg, bmp, ico, pdf, txt, doc, docx, xls, xlsx,
        csv, ppt, pptx, json, xml, zip, rar, 7z, mp3, wav, ogg, m4a, mp4, avi,
        mkv, mov, webm, exe, apk, py, java, js, ts, html, css, cpp, c, h, sql, md
        """
        extensions = [
            "jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico", "pdf", "txt",
            "doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx", "json", "xml", "zip",
            "rar", "7z", "mp3", "wav", "ogg", "m4a", "mp4", "avi", "mkv", "mov",
            "webm", "exe", "apk", "py", "java", "js", "ts", "html", "css", "cpp",
            "c", "h", "sql", "md"
        ]
        for ext in extensions:
            with self.subTest(extension=ext):
                # For single-letter 'c' and 'h', use safe code stem 'main'
                stem = "main" if ext in ("c", "h") else "sample"
                spoken = f"{stem} {ext}"
                expected = f"{stem}.{ext}"
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_04_filenames_containing_spaces(self):
        """
        Verifies multi-word filenames containing spaces:
        - annual report 2024 pdf -> annual report 2024.pdf
        - quarterly financial report docx -> quarterly financial report.docx
        - my test photo png -> my test photo.png
        - old backup file zip -> old backup file.zip
        """
        cases = [
            ("annual report 2024 pdf", "annual report 2024.pdf"),
            ("quarterly financial report docx", "quarterly financial report.docx"),
            ("my test photo png", "my test photo.png"),
            ("old backup file zip", "old backup file.zip"),
            ("show me my vacation photo png", "show me my vacation photo.png"),
            ("delete quarterly financial report docx", "delete quarterly financial report.docx"),
        ]
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_05_preserve_existing_dots_and_no_double_dots(self):
        """
        Preserves filenames that already contain dots:
        - photo.png -> photo.png (not photo..png)
        - image.jpg -> image.jpg
        - my.file.txt -> my.file.txt
        - version 1.0 notes.txt -> version 1.0 notes.txt
        - photo . png -> photo.png
        """
        cases = [
            ("open photo.png", "open photo.png"),
            ("show me image.jpg", "show me image.jpg"),
            ("delete my.file.txt", "delete my.file.txt"),
            ("version 1.0 notes.txt", "version 1.0 notes.txt"),
            ("photo . png", "photo.png"),
            ("document . pdf", "document.pdf"),
            ("convert test.png to jpg", "convert test.png to jpg"),
        ]
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_06_case_handling(self):
        """
        Consistent uppercase / lowercase handling:
        - IMAGE JPG -> IMAGE.jpg
        - Photo PNG -> Photo.png
        - DOCUMENT PDF -> DOCUMENT.pdf
        """
        cases = [
            ("IMAGE JPG", "IMAGE.jpg"),
            ("Photo PNG", "Photo.png"),
            ("DOCUMENT PDF", "DOCUMENT.pdf"),
            ("open PHOTO PNG", "open PHOTO.png"),
        ]
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_07_do_not_modify_urls_emails_numbers_or_ordinary_words(self):
        """
        Ordinary words, URLs, emails, and normal text must not be modified:
        - URLs: https://example.com/api
        - Emails: user@example.com
        - Decimals: 3.14, 1.0
        - System commands: open terminal, switch to sheets, set cell A1 to 100, turn on flashlight
        """
        cases = [
            ("https://example.com/api", "https://example.com/api"),
            ("http://localhost:7890/test", "http://localhost:7890/test"),
            ("user@example.com", "user@example.com"),
            ("open terminal", "open terminal"),
            ("switch to sheets", "switch to sheets"),
            ("set cell A1 to 100", "set cell A1 to 100"),
            ("turn on flashlight", "turn on flashlight"),
            ("what can you do", "what can you do"),
            ("status", "status"),
            ("help", "help"),
        ]
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_08_spoken_separators_and_spelled_out_letters(self):
        """
        Normalizes spoken separator words (dot, point, period) and spelled-out extensions:
        - image dot jpg -> image.jpg
        - photo point png -> photo.png
        - document period pdf -> document.pdf
        - image j p g -> image.jpg
        - song m p 3 -> song.mp3
        - video m p 4 -> video.mp4
        - data c s v -> data.csv
        - notes t x t -> notes.txt
        """
        cases = [
            ("image dot jpg", "image.jpg"),
            ("photo point png", "photo.png"),
            ("document period pdf", "document.pdf"),
            ("image j p g", "image.jpg"),
            ("photo p n g", "photo.png"),
            ("document p d f", "document.pdf"),
            ("song m p 3", "song.mp3"),
            ("video m p 4", "video.mp4"),
            ("data c s v", "data.csv"),
            ("notes t x t", "notes.txt"),
            ("code p y", "code.py"),
            ("styles c s s", "styles.css"),
        ]
        for spoken, expected in cases:
            with self.subTest(spoken=spoken):
                result = normalize_file_command(spoken)
                self.assertEqual(result, expected)

    def test_09_command_service_integration_open_and_show(self):
        """
        Tests CommandService.process integration with open and show commands:
        - "show me image jpg" -> resolves to existing image.jpg and returns file.open
        - "open photo png" -> reconstructs photo.png
        """
        # "image.jpg" exists in mobile uploads directory
        res_show = CommandService.process("show me image jpg")
        self.assertEqual(res_show["status"], "completed")
        self.assertEqual(res_show["action"]["action"], "file.open")
        self.assertEqual(res_show["action"]["filename"], "image.jpg")
        self.assertEqual(res_show["action"]["file_type"], "image")

        # Nonexistent file should report clear file not found
        res_open = CommandService.process("open nonexistent_photo_xyz png")
        self.assertEqual(res_open["status"], "failed")
        self.assertEqual(res_open["error"], "FILE_NOT_FOUND")
        self.assertIn("nonexistent_photo_xyz.png", res_open["message"])

    def test_10_command_service_integration_delete_file(self):
        """
        Tests CommandService.process integration with delete command:
        - Creates a temporary file in uploads
        - "delete temp_test_doc pdf" -> reconstructs "temp_test_doc.pdf" and deletes it
        """
        temp_path = os.path.join(UPLOAD_DIR, "temp_test_doc.pdf")
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4 test document content")
        self.assertTrue(os.path.exists(temp_path))

        try:
            res_del = CommandService.process("delete temp_test_doc pdf")
            self.assertEqual(res_del["status"], "completed")
            self.assertEqual(res_del["action"]["action"], "file.deleted")
            self.assertEqual(res_del["action"]["filename"], "temp_test_doc.pdf")
            self.assertFalse(os.path.exists(temp_path))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
