"""File storage helpers: save uploads, organize per report.

Uploads are auto-shrunk so massive originals (8-50 MB phone shots) don't
slow down later inference, OCR and PDF generation. The clamp keeps the
long edge at most :data:`UPLOAD_MAX_LONG_EDGE` and re-encodes JPEG at a
quality that keeps the file under ~1 MB while still looking great.
"""
from __future__ import annotations
from pathlib import Path
import io
import logging
import uuid

from PIL import Image, ImageOps

from .. import config

log = logging.getLogger("nauticai.storage")

UPLOAD_MAX_LONG_EDGE = 2400   # ≥ enough detail for OCR + species classifier
UPLOAD_JPEG_QUALITY  = 85


def safe_suffix(name: str) -> str:
    s = Path(name).suffix.lower()
    return s if s in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


def _shrink_if_huge(content: bytes, suffix: str) -> tuple[bytes, str]:
    """Decode → downscale → re-encode if the image is too big.

    Returns the (possibly new) bytes + suffix.  We always write JPEG when
    we re-encode because it's much smaller than PNG for photos and every
    downstream consumer (Pillow, EasyOCR, ReportLab) handles JPEG fine.
    """
    try:
        with Image.open(io.BytesIO(content)) as im:
            im = ImageOps.exif_transpose(im)        # respect camera rotation
            W, H = im.size
            longest = max(W, H)
            if longest <= UPLOAD_MAX_LONG_EDGE and suffix in {".jpg", ".jpeg"}:
                return content, suffix              # already a sensible size
            if longest > UPLOAD_MAX_LONG_EDGE:
                scale = UPLOAD_MAX_LONG_EDGE / float(longest)
                im = im.resize((max(1, int(W * scale)), max(1, int(H * scale))),
                                Image.LANCZOS)
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG",
                                    quality=UPLOAD_JPEG_QUALITY, optimize=True)
            return buf.getvalue(), ".jpg"
    except Exception:
        # If decoding fails, just keep the bytes as-is — the analyse step
        # will surface a clearer error.
        log.exception("upload shrink failed; persisting original bytes")
        return content, suffix


def save_upload(content: bytes, original_filename: str) -> tuple[str, Path]:
    """Persist an uploaded image to /storage/uploads/<uuid>.<ext>. Returns (id, path)."""
    image_id = uuid.uuid4().hex
    suffix = safe_suffix(original_filename)
    content, suffix = _shrink_if_huge(content, suffix)
    dest = config.UPLOADS_DIR / f"{image_id}{suffix}"
    dest.write_bytes(content)
    return image_id, dest


def report_pdf_path(report_id: str) -> Path:
    return config.REPORTS_DIR / f"{report_id}.pdf"
