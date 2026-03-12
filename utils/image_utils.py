"""
Image utility functions: loading, resizing, and base64 encoding for OpenAI vision API.
"""
import base64
import io
from PIL import Image


def encode_image_to_base64(uploaded_file) -> str:
    """
    Read an uploaded Streamlit file, resize if needed, and return a base64 string.
    """
    image = Image.open(uploaded_file)

    # Resize large images to reduce token usage (max 2048 on longest side)
    max_side = 2048
    if max(image.size) > max_side:
        ratio = max_side / max(image.size)
        new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
        image = image.resize(new_size, Image.LANCZOS)

    # Convert to PNG bytes
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def get_media_type(filename: str) -> str:
    """Return the MIME type based on file extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "png"
    mapping = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }
    return mapping.get(ext, "image/png")


def get_image_thumbnail(base64_data: str, max_width: int = 300) -> str:
    """Return a resized base64 thumbnail for display purposes."""
    img_bytes = base64.b64decode(base64_data)
    image = Image.open(io.BytesIO(img_bytes))

    ratio = max_width / image.size[0]
    if ratio < 1:
        new_size = (max_width, int(image.size[1] * ratio))
        image = image.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")
