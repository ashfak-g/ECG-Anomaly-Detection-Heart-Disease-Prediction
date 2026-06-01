"""
utils.py — Secure file upload, role decorators, and helper utilities.
Production-hardened: MIME validation, PIL verify, EXIF strip, UUID rename.
"""

import os
import uuid
import logging
from functools import wraps

from flask import current_app, abort, redirect, url_for, request
from flask_login import current_user
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
MAX_IMAGE_PIXELS = 50_000_000  # prevent decompression-bomb attacks
MODEL_INPUT_SIZE = (224, 224)  # resize target for AI model

# We detect MIME from file header bytes rather than trusting the extension.
# Map of magic-byte prefixes → MIME type.
_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
}


def _detect_mime(stream) -> str:
    """Read first 16 bytes of a file stream to detect MIME type."""
    header = stream.read(16)
    stream.seek(0)
    for magic, mime in _MAGIC_BYTES.items():
        if header[:len(magic)] == magic:
            return mime
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# Secure Picture Upload
# ---------------------------------------------------------------------------

def save_picture(form_picture):
    """
    Securely process and save an uploaded ECG image.

    Steps:
      1. Detect real MIME type from file bytes (not extension)
      2. Open with PIL and call verify() to detect corrupt/malicious files
      3. Check pixel count to prevent decompression bombs
      4. Strip all EXIF metadata (patient privacy)
      5. Resize to model input dimensions
      6. Save with a UUID filename (never trust user-controlled names)

    Args:
        form_picture: FileStorage object from the upload form.

    Returns:
        str: The generated UUID filename (relative to UPLOAD_FOLDER).

    Raises:
        ValueError: If file is invalid, corrupt, or an unsafe type.
    """

    # 1. Real MIME type check (magic bytes, not extension)
    mime = _detect_mime(form_picture.stream)
    if mime not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"File type '{mime}' is not allowed. Only JPEG and PNG are accepted."
        )

    # 2. PIL verify — detects corrupt, truncated, or crafted images
    try:
        img = Image.open(form_picture.stream)
        img.verify()  # Raises on corrupt/fake images
    except Exception as exc:
        logger.warning("PIL verify failed for upload: %s", exc)
        raise ValueError("Corrupt or invalid image file.") from exc

    # Re-open after verify() (verify invalidates the image object)
    form_picture.stream.seek(0)
    img = Image.open(form_picture.stream)

    # 3. Decompression bomb guard
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    pixel_count = img.width * img.height
    if pixel_count > MAX_IMAGE_PIXELS:
        raise ValueError(
            f"Image is too large ({pixel_count:,} pixels). "
            f"Maximum allowed: {MAX_IMAGE_PIXELS:,}."
        )

    # 4. Strip EXIF / metadata (patient privacy)
    # Re-create image data without metadata
    data = list(img.getdata())
    clean_img = Image.new(img.mode, img.size)
    clean_img.putdata(data)

    # 5. Resize to model input size
    clean_img = clean_img.resize(MODEL_INPUT_SIZE, Image.LANCZOS)

    # 6. Save with UUID filename — never use user-supplied filenames
    filename = f"{uuid.uuid4().hex}.png"
    upload_folder = current_app.config['UPLOAD_FOLDER']
    save_path = os.path.join(upload_folder, filename)
    clean_img.save(save_path, format="PNG")

    logger.info("Saved upload as %s (%dx%d → %dx%d)",
                filename, img.width, img.height,
                MODEL_INPUT_SIZE[0], MODEL_INPUT_SIZE[1])

    return filename


# ---------------------------------------------------------------------------
# Role-Based Access Decorators
# ---------------------------------------------------------------------------

def roles_required(*roles):
    """
    Decorator that restricts route access to authenticated users with one
    of the specified roles.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))
            if (current_user.role or '') not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(f):
    """Shortcut decorator: admin-only access."""
    return roles_required('admin')(f)
