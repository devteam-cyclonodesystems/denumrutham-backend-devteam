"""
Secure file upload API endpoints with strict validation.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from uuid import uuid4
import os
import shutil

from app.core.deps import get_current_user
from app.core.response import api_response

router = APIRouter()

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Strict validation constants ---
MAX_IMAGE_SIZE = 5 * 1024 * 1024      # 5 MB
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024   # 10 MB

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_DOC_TYPES = {"application/pdf"}

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".msi",
    ".dll", ".com", ".vbs", ".js", ".jar", ".py",
}


def _validate_extension(filename: str):
    """Reject executable file extensions regardless of MIME type."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' is not allowed.",
        )


async def _read_and_validate_size(file: UploadFile, max_bytes: int) -> bytes:
    """Read file content and enforce size limit."""
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum allowed: {max_bytes // (1024*1024)} MB",
        )
    return content


@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload a temple image (JPEG, PNG, WebP). Max 5 MB."""
    _validate_extension(file.filename or "")

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Only JPEG, PNG, and WebP are allowed.",
        )

    content = await _read_and_validate_size(file, MAX_IMAGE_SIZE)

    ext = os.path.splitext(file.filename or ".jpg")[1]
    filename = f"{uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(content)

    return api_response(
        data={"url": f"/static/uploads/{filename}", "filename": filename},
        message="Image uploaded successfully",
    )


@router.post("/document")
async def upload_document(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload a document (PDF only). Max 10 MB."""
    _validate_extension(file.filename or "")

    if file.content_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Only PDF is allowed.",
        )

    content = await _read_and_validate_size(file, MAX_DOCUMENT_SIZE)

    ext = os.path.splitext(file.filename or ".pdf")[1]
    filename = f"{uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(content)

    return api_response(
        data={"url": f"/static/uploads/{filename}", "filename": filename},
        message="Document uploaded successfully",
    )
