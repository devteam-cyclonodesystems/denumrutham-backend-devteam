"""
Secure file upload API endpoints with strict validation.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from uuid import uuid4
import os
import shutil
import logging

from app.core.deps import get_current_user
from app.core.response import api_response

logger = logging.getLogger("tms.security")

router = APIRouter()

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Strict validation constants ---
MAX_IMAGE_SIZE = 5 * 1024 * 1024      # 5 MB
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_AUDIO_SIZE = 15 * 1024 * 1024       # 15 MB

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_DOC_EXTENSIONS = {".pdf"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a"}


def _verify_content_length(request: Request, max_bytes: int):
    """Check Content-Length header prior to reading bytes to prevent memory attacks."""
    cl_header = request.headers.get("content-length")
    if cl_header:
        try:
            cl = int(cl_header)
            if cl > max_bytes:
                logger.error(
                    "Upload validation failure: Content-Length exceeds maximum limit.",
                    extra={"operation": "UPLOAD_CONTENT_LENGTH_CHECK", "status": "FAILURE", "content_length": cl}
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"File too large. Maximum allowed: {max_bytes // (1024*1024)} MB",
                )
        except ValueError:
            logger.error(
                "Upload validation failure: Invalid Content-Length header format.",
                extra={"operation": "UPLOAD_CONTENT_LENGTH_CHECK", "status": "FAILURE", "content_length_header": cl_header}
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header."
            )


def _validate_image_signature(content: bytes, ext: str):
    """Verify image magic bytes match JPEG, PNG, or WebP formatting."""
    if content.startswith(b"\xFF\xD8\xFF"):
        detected_mime = "image/jpeg"
        allowed_exts = {".jpg", ".jpeg"}
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_mime = "image/png"
        allowed_exts = {".png"}
    elif content.startswith(b"RIFF") and len(content) > 12 and content[8:12] == b"WEBP":
        detected_mime = "image/webp"
        allowed_exts = {".webp"}
    else:
        logger.error(
            "Upload magic byte failure: File content does not match allowed image signatures.",
            extra={"operation": "UPLOAD_IMAGE_MAGIC_BYTES", "status": "FAILURE"}
        )
        raise HTTPException(
            status_code=400,
            detail="File content does not match allowed image formats (JPEG, PNG, WebP)."
        )
        
    if ext not in allowed_exts:
        logger.error(
            f"Upload validation failure: Extension '{ext}' mismatch for detected format '{detected_mime}'.",
            extra={"operation": "UPLOAD_IMAGE_SIGNATURE_MATCH", "status": "FAILURE", "extension": ext, "detected_mime": detected_mime}
        )
        raise HTTPException(
            status_code=400,
            detail="File extension does not match the image content signature."
        )


def _validate_doc_signature(content: bytes, ext: str):
    """Verify document magic bytes match PDF formatting."""
    if content.startswith(b"%PDF"):
        detected_mime = "application/pdf"
        allowed_exts = {".pdf"}
    else:
        logger.error(
            "Upload magic byte failure: File content does not match allowed document signatures (PDF).",
            extra={"operation": "UPLOAD_DOC_MAGIC_BYTES", "status": "FAILURE"}
        )
        raise HTTPException(
            status_code=400,
            detail="File content does not match allowed document formats (PDF)."
        )
        
    if ext not in allowed_exts:
        logger.error(
            f"Upload validation failure: Extension '{ext}' mismatch for PDF.",
            extra={"operation": "UPLOAD_DOC_SIGNATURE_MATCH", "status": "FAILURE", "extension": ext}
        )
        raise HTTPException(
            status_code=400,
            detail="File extension does not match the document content signature."
        )


async def _read_and_validate_size(file: UploadFile, max_bytes: int) -> bytes:
    """Read file content and enforce size limit."""
    content = await file.read()
    if len(content) > max_bytes:
        logger.error(
            "Upload validation failure: File size exceeds maximum limit.",
            extra={"operation": "UPLOAD_SIZE_CHECK", "status": "FAILURE"}
        )
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum allowed: {max_bytes // (1024*1024)} MB",
        )
    return content


@router.post("/image")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload a temple image (JPEG, PNG, WebP). Max 5 MB, compressed and returned as Base64."""
    # 1. Immediate Content-Length Header check
    _verify_content_length(request, MAX_IMAGE_SIZE)

    # 2. Extension check against allowlist
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        logger.error(
            f"Upload validation failure: Extension '{ext}' is not allowed for images.",
            extra={"operation": "UPLOAD_IMAGE_EXTENSION_CHECK", "status": "FAILURE", "extension": ext}
        )
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' is not allowed. Supported: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}",
        )

    # 3. Read content bytes and enforce actual size check
    content = await _read_and_validate_size(file, MAX_IMAGE_SIZE)

    # 4. Perform magic byte signature validation
    _validate_image_signature(content, ext)

    # 5. PIL Compress to WebP and convert to Base64 data URL
    import base64
    from io import BytesIO
    from PIL import Image

    try:
        image = Image.open(BytesIO(content))
        # Keep transparency if any (WebP supports it)
        max_width = 1920
        if image.width > max_width:
            new_height = int(image.height * (max_width / image.width))
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

        buffer = BytesIO()
        image.save(buffer, format="WEBP", quality=75)
        webp_bytes = buffer.getvalue()

        encoded = base64.b64encode(webp_bytes).decode('utf-8')
        data_url = f"data:image/webp;base64,{encoded}"

        # Write to local static folder as a fallback reference
        filename = f"{uuid4().hex}.webp"
        file_path = os.path.join(UPLOAD_DIR, filename)
        with open(file_path, "wb") as buffer_file:
            buffer_file.write(webp_bytes)

        return api_response(
            data={"url": data_url, "filename": filename},
            message="Image uploaded and compressed successfully",
        )
    except Exception as e:
        logger.error(
            f"Image processing and compression failure: {e}",
            extra={"operation": "UPLOAD_IMAGE_COMPRESSION", "status": "FAILURE", "error": str(e)}
        )
        raise HTTPException(
            status_code=400,
            detail="Failed to process and compress the uploaded image."
        )


@router.post("/document")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload a document (PDF only). Max 10 MB."""
    # 1. Immediate Content-Length Header check
    _verify_content_length(request, MAX_DOCUMENT_SIZE)

    # 2. Extension check against allowlist
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_DOC_EXTENSIONS:
        logger.error(
            f"Upload validation failure: Extension '{ext}' is not allowed for documents.",
            extra={"operation": "UPLOAD_DOC_EXTENSION_CHECK", "status": "FAILURE", "extension": ext}
        )
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' is not allowed. Supported: {', '.join(ALLOWED_DOC_EXTENSIONS)}",
        )

    # 3. Read content bytes and enforce actual size check
    content = await _read_and_validate_size(file, MAX_DOCUMENT_SIZE)

    # 4. Perform magic byte signature validation
    _validate_doc_signature(content, ext)

    # 5. Sanitize filename completely using uuid4() + extension
    filename = f"{uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(content)

    return api_response(
        data={"url": f"/static/uploads/{filename}", "filename": filename},
        message="Document uploaded successfully",
    )


@router.post("/audio")
async def upload_audio(
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload a temple chanting audio file (MP3, WAV, OGG, M4A). Max 15 MB."""
    # 1. Immediate Content-Length Header check
    _verify_content_length(request, MAX_AUDIO_SIZE)

    # 2. Extension check against allowlist
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        logger.error(
            f"Upload validation failure: Extension '{ext}' is not allowed for audio.",
            extra={"operation": "UPLOAD_AUDIO_EXTENSION_CHECK", "status": "FAILURE", "extension": ext}
        )
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' is not allowed. Supported: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}",
        )

    # 3. Read content bytes and enforce actual size check
    content = await _read_and_validate_size(file, MAX_AUDIO_SIZE)

    # 4. Save to local static folder
    filename = f"{uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    try:
        with open(file_path, "wb") as buffer_file:
            buffer_file.write(content)

        return api_response(
            data={"url": f"/static/uploads/{filename}", "filename": filename},
            message="Audio file uploaded successfully",
        )
    except Exception as e:
        logger.error(
            f"Audio file write failure: {e}",
            extra={"operation": "UPLOAD_AUDIO_WRITE", "status": "FAILURE", "error": str(e)}
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to store the uploaded audio file."
        )
