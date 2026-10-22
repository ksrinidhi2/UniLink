"""
uploads.py
==========
Image Upload & Asset Management Router for UniLink:
- Supports authenticating student requests via JWT Bearer tokens.
- Validates file sizes (max 5 MB) and MIME types.
- Validates magic bytes / image signatures (JPEG, PNG, WebP, GIF) to prevent file extension spoofing.
- Generates unguessable, secure server-side filenames (UUID4 + valid extension).
- Saves images to `backend/uploads/` persistent local storage.
- Returns relative accessible image URLs (e.g. `/uploads/<filename>`).
- Supports both standard Multipart form-data (`UploadFile`) and JSON Base64 data uploads.
- Provides resource-level image attach & delete endpoints for:
    - Marketplace Listings: POST/DELETE /listings/{listing_id}/image
    - Borrow Listings: POST/DELETE /borrow/{listing_id}/image
    - Lost & Found Reports: POST/DELETE /lost-found/{report_id}/image
  strictly verifying authenticated ownership (403 if not owner).
"""

import os
import uuid
import base64
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

try:
    from backend.database import get_db
    from backend.models import Student, Listing, LostFoundReport
    from backend.dependencies import get_current_student
except ImportError:
    from database import get_db
    from models import Student, Listing, LostFoundReport
    from dependencies import get_current_student

router = APIRouter(tags=["Image Uploads"])

# Persistent directory for storing uploaded images
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB maximum

# Allowed MIME types and corresponding allowed extensions
MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def validate_image_bytes(content: bytes, declared_content_type: Optional[str] = None) -> Tuple[bool, str, str]:
    """
    Validates image file content against size limits, MIME types, and binary magic bytes.
    Returns (is_valid, error_message, determined_extension).
    """
    if not content:
        return False, "Uploaded file is empty.", ""

    if len(content) > MAX_FILE_SIZE:
        return False, f"File size ({len(content) / (1024 * 1024):.2f} MB) exceeds maximum allowed limit of 5 MB.", ""

    # Check magic byte signatures
    ext = None
    if content.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    elif content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        ext = ".gif"
    elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        ext = ".webp"
    else:
        return False, "Invalid image format. Allowed formats are JPEG, PNG, WebP, and GIF.", ""

    # If a content type was declared, verify it doesn't conflict
    if declared_content_type:
        clean_ct = declared_content_type.lower().split(";")[0].strip()
        expected_ext = MIME_TO_EXT.get(clean_ct)
        # Allow jpg/jpeg interchangeability
        if expected_ext and ext:
            if clean_ct not in MIME_TO_EXT:
                return False, f"Unsupported MIME type: {clean_ct}", ""

    return True, "", ext


def save_image_bytes(content: bytes, ext: str) -> str:
    """
    Saves image content with a unique UUID filename to the persistent uploads folder.
    Returns the relative URL path for the saved image.
    """
    filename = f"{uuid.uuid4().hex}{ext}"
    target_path = os.path.join(UPLOAD_DIR, filename)
    with open(target_path, "wb") as f:
        f.write(content)
    return f"/uploads/{filename}"


def delete_local_image_if_exists(image_url: Optional[str]) -> None:
    """
    Safely deletes a local file in UPLOAD_DIR if the image_url refers to /uploads/<filename>.
    Prevents path traversal vulnerabilities.
    """
    if not image_url or not image_url.startswith("/uploads/"):
        return
    filename = os.path.basename(image_url)
    # Ensure no subpath navigation
    if filename and not filename.startswith("."):
        file_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


# ==============================================================================
# SCHEMAS
# ==============================================================================
class ImageUploadResponse(BaseModel):
    image_url: str
    message: str = "Image uploaded successfully"


class Base64ImageUploadPayload(BaseModel):
    file_base64: str = Field(..., description="Base64 encoded image data (can include data URI prefix)")
    filename: Optional[str] = Field(None, description="Optional original filename")
    content_type: Optional[str] = Field(None, description="Optional declared MIME type (e.g. image/png)")


class ResourceImageActionResponse(BaseModel):
    message: str
    image_url: Optional[str] = None
    resource_id: int


# ==============================================================================
# 1. STANDALONE IMAGE UPLOAD ENDPOINTS
# ==============================================================================
@router.post(
    "/uploads/image",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image (Multipart Form)",
    description="Upload an image file (JPEG, PNG, WebP, GIF up to 5MB). Returns a persistent image URL."
)
async def upload_image_multipart(
    file: UploadFile = File(..., description="Image file to upload"),
    current_student: Student = Depends(get_current_student),
):
    """
    Receives an image via multipart/form-data.
    Validates magic bytes, enforces maximum file size, and stores on disk.
    """
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {str(exc)}"
        )

    is_valid, err_msg, ext = validate_image_bytes(content, file.content_type)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg
        )

    image_url = save_image_bytes(content, ext)
    return ImageUploadResponse(image_url=image_url, message="Image uploaded successfully")


@router.post(
    "/uploads/image/base64",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image (Base64 JSON)",
    description="Upload an image encoded as base64 string. Useful when client sends base64 directly."
)
def upload_image_base64(
    payload: Base64ImageUploadPayload,
    current_student: Student = Depends(get_current_student),
):
    """
    Receives an image encoded in base64 string.
    Decodes and validates binary content.
    """
    raw_b64 = payload.file_base64.strip()
    declared_ct = payload.content_type

    # Handle data:image/png;base64,... header if present
    if "," in raw_b64 and "base64" in raw_b64[:30]:
        header, raw_b64 = raw_b64.split(",", 1)
        if not declared_ct and ":" in header and ";" in header:
            try:
                declared_ct = header.split(":")[1].split(";")[0]
            except Exception:
                pass

    try:
        content = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 encoding."
        )

    is_valid, err_msg, ext = validate_image_bytes(content, declared_ct)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg
        )

    image_url = save_image_bytes(content, ext)
    return ImageUploadResponse(image_url=image_url, message="Image uploaded successfully")


# ==============================================================================
# 2. MARKETPLACE RESOURCE IMAGE ENDPOINTS
# ==============================================================================
@router.post(
    "/listings/{listing_id}/image",
    response_model=ResourceImageActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Attach or replace image for Marketplace Listing",
    description="Uploads and updates the image for an existing marketplace listing. Only the owner can upload."
)
async def attach_marketplace_image(
    listing_id: int,
    file: UploadFile = File(..., description="New image file"),
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_student),
):
    listing = db.query(Listing).filter(Listing.id == listing_id, Listing.listing_type == "marketplace").first()
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace listing not found")

    if listing.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You can only update images on your own listings"
        )

    content = await file.read()
    is_valid, err_msg, ext = validate_image_bytes(content, file.content_type)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)

    # Delete previous local image if applicable
    if listing.image_url:
        delete_local_image_if_exists(listing.image_url)

    new_url = save_image_bytes(content, ext)
    listing.image_url = new_url
    db.commit()
    db.refresh(listing)

    return ResourceImageActionResponse(
        message="Marketplace listing image updated successfully",
        image_url=new_url,
        resource_id=listing.id
    )


@router.delete(
    "/listings/{listing_id}/image",
    response_model=ResourceImageActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove image from Marketplace Listing",
    description="Removes the image from an owned marketplace listing. Only the owner can remove."
)
def remove_marketplace_image(
    listing_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_student),
):
    listing = db.query(Listing).filter(Listing.id == listing_id, Listing.listing_type == "marketplace").first()
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace listing not found")

    if listing.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You can only remove images on your own listings"
        )

    if listing.image_url:
        delete_local_image_if_exists(listing.image_url)
        listing.image_url = None
        db.commit()
        db.refresh(listing)

    return ResourceImageActionResponse(
        message="Listing image removed successfully",
        image_url=None,
        resource_id=listing.id
    )


# ==============================================================================
# 3. BORROW RESOURCE IMAGE ENDPOINTS
# ==============================================================================
@router.post(
    "/borrow/{listing_id}/image",
    response_model=ResourceImageActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Attach or replace image for Peer Borrow Listing",
    description="Uploads and updates the image for an existing borrow listing. Only the owner can upload."
)
async def attach_borrow_image(
    listing_id: int,
    file: UploadFile = File(..., description="New image file"),
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_student),
):
    listing = db.query(Listing).filter(Listing.id == listing_id, Listing.listing_type == "borrow").first()
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Borrow listing not found")

    if listing.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You can only update images on your own borrow listings"
        )

    content = await file.read()
    is_valid, err_msg, ext = validate_image_bytes(content, file.content_type)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)

    if listing.image_url:
        delete_local_image_if_exists(listing.image_url)

    new_url = save_image_bytes(content, ext)
    listing.image_url = new_url
    db.commit()
    db.refresh(listing)

    return ResourceImageActionResponse(
        message="Borrow listing image updated successfully",
        image_url=new_url,
        resource_id=listing.id
    )


@router.delete(
    "/borrow/{listing_id}/image",
    response_model=ResourceImageActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove image from Peer Borrow Listing",
    description="Removes the image from an owned borrow listing. Only the owner can remove."
)
def remove_borrow_image(
    listing_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_student),
):
    listing = db.query(Listing).filter(Listing.id == listing_id, Listing.listing_type == "borrow").first()
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Borrow listing not found")

    if listing.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You can only remove images on your own borrow listings"
        )

    if listing.image_url:
        delete_local_image_if_exists(listing.image_url)
        listing.image_url = None
        db.commit()
        db.refresh(listing)

    return ResourceImageActionResponse(
        message="Borrow listing image removed successfully",
        image_url=None,
        resource_id=listing.id
    )


# ==============================================================================
# 4. LOST & FOUND RESOURCE IMAGE ENDPOINTS
# ==============================================================================
@router.post(
    "/lost-found/{report_id}/image",
    response_model=ResourceImageActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Attach or replace image for Lost & Found Report",
    description="Uploads and updates the image for an existing lost & found report. Only the reporter can upload."
)
async def attach_lost_found_image(
    report_id: int,
    file: UploadFile = File(..., description="New image file"),
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_student),
):
    report = db.query(LostFoundReport).filter(LostFoundReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lost & Found report not found")

    if report.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You can only update images on your own reports"
        )

    content = await file.read()
    is_valid, err_msg, ext = validate_image_bytes(content, file.content_type)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)

    if report.image_url:
        delete_local_image_if_exists(report.image_url)

    new_url = save_image_bytes(content, ext)
    report.image_url = new_url
    db.commit()
    db.refresh(report)

    return ResourceImageActionResponse(
        message="Report image updated successfully",
        image_url=new_url,
        resource_id=report.id
    )


@router.delete(
    "/lost-found/{report_id}/image",
    response_model=ResourceImageActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove image from Lost & Found Report",
    description="Removes the image from an owned lost & found report. Only the reporter can remove."
)
def remove_lost_found_image(
    report_id: int,
    db: Session = Depends(get_db),
    current_student: Student = Depends(get_current_student),
):
    report = db.query(LostFoundReport).filter(LostFoundReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lost & Found report not found")

    if report.student_id != current_student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You can only remove images on your own reports"
        )

    if report.image_url:
        delete_local_image_if_exists(report.image_url)
        report.image_url = None
        db.commit()
        db.refresh(report)

    return ResourceImageActionResponse(
        message="Report image removed successfully",
        image_url=None,
        resource_id=report.id
    )
