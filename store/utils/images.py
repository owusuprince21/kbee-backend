# realestate/utils/images.py
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile

def shrink_image_if_needed(uploaded_file, limit_bytes=10 * 1024 * 1024,
                           max_width=2400, quality=82, force_rgb=True):
    """
    If uploaded_file.size > limit_bytes, re-encode as JPEG (or WebP if you prefer)
    with downscale + quality to bring it under the limit.
    Returns the original file if already small enough.
    """
    try:
        if not uploaded_file or getattr(uploaded_file, "size", 0) <= limit_bytes:
            return uploaded_file

        # Open and normalize
        img = Image.open(uploaded_file)
        if force_rgb and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Downscale if needed
        w, h = img.size
        if w > max_width:
            ratio = max_width / float(w)
            img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)

        # Re-encode to JPEG (swap to "WEBP" if you prefer)
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        out.seek(0)

        # Build a new Django file
        base = uploaded_file.name.rsplit(".", 1)[0]
        new_name = f"{base}.jpg"
        return ContentFile(out.read(), name=new_name)
    except Exception:
        # If anything goes wrong, just return the original
        return uploaded_file
