#!/usr/bin/env python3
"""
Mock Utility Backend Service on http://127.0.0.1:8000
Provides compatible utility endpoints for file processing according to the
38-endpoint task registry:
- IMAGE: /jpg-to-png, /png-to-jpg, /webp-to-jpg, /jpg-to-webp, /png-to-webp,
         /bmp-to-jpg, /bmp-to-png, /tiff-to-jpg, /tiff-to-png, /heic-to-jpg,
         /heic-to-png, /compress-image, /add-watermark
- PDF:   /extract-images-from-pdf, /merge-pdfs, /split-pdf, /delete-pdf-pages,
         /pdf-to-jpg, /pdf-to-png, /jpg-to-pdf, /png-to-pdf, /images-to-pdf,
         /compress-pdf
- VIDEO: /compress-video, /video-to-gif, /gif-to-mp4, /add-audio-to-video,
         /replace-video-audio
- AUDIO: /mp4-to-mp3, /mp4-to-wav, /wav-to-mp3, /mp3-to-wav, /m4a-to-mp3,
         /compress-audio
- DATA:  /json-to-csv, /csv-to-json, /csv-to-excel, /excel-to-csv
Also preserves legacy /convert, /compress, /resize, /merge for backward compatibility.
"""
import os
import gzip
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, Response, HTTPException, Request
import uvicorn

app = FastAPI(title="Utility Backend Service", version="2.0.0")

# Pre-defined minimal format stubs for binary outputs
STUB_JPEG = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
STUB_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xfe\xae\x00\x00\x00\x00IEND\xaeB`\x82'
STUB_GIF = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
STUB_PDF = b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 300 144]/Parent 2 0 R/Resources<<>>>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000108 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n198\n%%EOF'
STUB_MP4 = b'\x00\x00\x00 ftypmp42\x00\x00\x00\x00mp42isom'
STUB_MP3 = b'ID3\x03\x00\x00\x00\x00\x00\x00\xff\xfb\x90\x44\x00\x00\x00\x00\x00'
STUB_WAV = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'

# Output extension and content mapping per endpoint
ENDPOINT_OUTPUT_MAP = {
    # IMAGE
    "/jpg-to-png": ("png", STUB_PNG, "image/png"),
    "/png-to-jpg": ("jpg", STUB_JPEG, "image/jpeg"),
    "/webp-to-jpg": ("jpg", STUB_JPEG, "image/jpeg"),
    "/jpg-to-webp": ("webp", STUB_PNG, "image/webp"),
    "/png-to-webp": ("webp", STUB_PNG, "image/webp"),
    "/bmp-to-jpg": ("jpg", STUB_JPEG, "image/jpeg"),
    "/bmp-to-png": ("png", STUB_PNG, "image/png"),
    "/tiff-to-jpg": ("jpg", STUB_JPEG, "image/jpeg"),
    "/tiff-to-png": ("png", STUB_PNG, "image/png"),
    "/heic-to-jpg": ("jpg", STUB_JPEG, "image/jpeg"),
    "/heic-to-png": ("png", STUB_PNG, "image/png"),
    "/compress-image": ("compressed", None, "image/png"),
    "/add-watermark": ("watermarked", None, "image/png"),

    # PDF
    "/extract-images-from-pdf": ("images.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip"),
    "/split-pdf": ("split.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip"),
    "/delete-pdf-pages": ("pdf", STUB_PDF, "application/pdf"),
    "/pdf-to-jpg": ("jpg", STUB_JPEG, "image/jpeg"),
    "/pdf-to-png": ("png", STUB_PNG, "image/png"),
    "/jpg-to-pdf": ("pdf", STUB_PDF, "application/pdf"),
    "/png-to-pdf": ("pdf", STUB_PDF, "application/pdf"),
    "/compress-pdf": ("compressed.pdf", STUB_PDF, "application/pdf"),

    # VIDEO
    "/compress-video": ("compressed.mp4", STUB_MP4, "video/mp4"),
    "/video-to-gif": ("gif", STUB_GIF, "image/gif"),
    "/gif-to-mp4": ("mp4", STUB_MP4, "video/mp4"),
    "/add-audio-to-video": ("with_audio.mp4", STUB_MP4, "video/mp4"),
    "/replace-video-audio": ("audio_replaced.mp4", STUB_MP4, "video/mp4"),

    # AUDIO
    "/mp4-to-mp3": ("mp3", STUB_MP3, "audio/mpeg"),
    "/mp4-to-wav": ("wav", STUB_WAV, "audio/wav"),
    "/wav-to-mp3": ("mp3", STUB_MP3, "audio/mpeg"),
    "/mp3-to-wav": ("wav", STUB_WAV, "audio/wav"),
    "/m4a-to-mp3": ("mp3", STUB_MP3, "audio/mpeg"),
    "/compress-audio": ("compressed.mp3", STUB_MP3, "audio/mpeg"),

    # DATA
    "/json-to-csv": ("csv", b"id,name,value\n1,test,100\n", "text/csv"),
    "/csv-to-json": ("json", b'[{"id": 1, "name": "test", "value": 100}]', "application/json"),
    "/csv-to-excel": ("xlsx", b"PK\x03\x04" + b"\x00" * 26, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "/excel-to-csv": ("csv", b"id,name,value\n1,test,100\n", "text/csv"),
}


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "service": "utility-backend-8000"}


# Multi-file endpoints
@app.post("/merge-pdfs")
async def merge_pdfs(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided for merging.")
    combined = bytearray()
    for f in files:
        data = await f.read()
        combined.extend(data)
    out_content = bytes(combined) if len(combined) > 0 else STUB_PDF
    return Response(
        content=out_content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="merged.pdf"'}
    )


@app.post("/images-to-pdf")
async def images_to_pdf(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No images provided.")
    for f in files:
        await f.read()
    return Response(
        content=STUB_PDF,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="images_combined.pdf"'}
    )


# Legacy endpoints for backward compatibility
@app.post("/convert")
async def legacy_convert_file(
    file: UploadFile = File(...),
    format: Optional[str] = Form(None),
    target_format: Optional[str] = Form(None)
):
    fmt = (target_format or format or "jpg").lower().lstrip(".")
    content = await file.read()
    orig_name = file.filename or "file"
    basename, _ = os.path.splitext(orig_name)
    out_filename = f"{basename}.{fmt}"

    if fmt in ("jpg", "jpeg"):
        out_content = STUB_JPEG
        media_type = "image/jpeg"
    elif fmt == "gif":
        out_content = STUB_GIF
        media_type = "image/gif"
    elif fmt == "png":
        out_content = STUB_PNG
        media_type = "image/png"
    elif fmt == "pdf":
        out_content = STUB_PDF
        media_type = "application/pdf"
    else:
        out_content = content
        media_type = "application/octet-stream"

    return Response(
        content=out_content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'}
    )


@app.post("/compress")
async def legacy_compress_file(file: UploadFile = File(...)):
    content = await file.read()
    orig_name = file.filename or "file.bin"
    basename, ext = os.path.splitext(orig_name)
    out_filename = f"{basename}_compressed{ext}"
    compressed = gzip.compress(content) if len(content) > 10 else content
    return Response(
        content=compressed,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'}
    )


@app.post("/resize")
async def legacy_resize_file(
    file: UploadFile = File(...),
    dimensions: Optional[str] = Form(None),
    width: Optional[str] = Form(None),
    height: Optional[str] = Form(None)
):
    content = await file.read()
    orig_name = file.filename or "image.png"
    basename, ext = os.path.splitext(orig_name)
    dim_str = f"_{width}x{height}" if width and height else (f"_{dimensions}" if dimensions else "_resized")
    out_filename = f"{basename}{dim_str}{ext}"
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'}
    )


@app.post("/merge")
async def legacy_merge_files(
    files: List[UploadFile] = File(...),
    format: Optional[str] = Form("pdf")
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided for merging.")
    combined = bytearray()
    for f in files:
        data = await f.read()
        combined.extend(data)
    fmt = (format or "pdf").lower().lstrip(".")
    out_filename = f"merged.{fmt}"
    return Response(
        content=bytes(combined),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'}
    )


# Dynamic handler for all 38 registry endpoints: /{endpoint_path}
@app.post("/{endpoint_name:path}")
async def handle_registry_endpoint(
    endpoint_name: str,
    request: Request,
    file: Optional[UploadFile] = File(None)
):
    clean_ep = "/" + endpoint_name.strip().lstrip("/")
    
    # Check if this endpoint is recognized in the registry
    if clean_ep not in ENDPOINT_OUTPUT_MAP:
        raise HTTPException(status_code=404, detail=f"No backend endpoint configured for '{clean_ep}'")

    out_suffix, default_content, media_type = ENDPOINT_OUTPUT_MAP[clean_ep]

    content = b""
    orig_name = "file"
    if file:
        content = await file.read()
        orig_name = file.filename or "file"

    basename, ext = os.path.splitext(orig_name)
    clean_ext = ext.lstrip(".").lower()

    if out_suffix == "compressed":
        out_filename = f"{basename}_compressed.{clean_ext or 'bin'}"
        out_content = gzip.compress(content) if len(content) > 10 else (default_content or content)
    elif out_suffix == "watermarked":
        out_filename = f"{basename}_watermarked.{clean_ext or 'jpg'}"
        out_content = default_content or content
    elif "." in out_suffix:
        # e.g. "images.zip" or "split.zip" or "compressed.mp4"
        out_filename = f"{basename}_{out_suffix}"
        out_content = default_content or content
    else:
        # Direct extension change, e.g. png -> jpg: basename.jpg
        out_filename = f"{basename}.{out_suffix}"
        out_content = default_content or content

    return Response(
        content=out_content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'}
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
