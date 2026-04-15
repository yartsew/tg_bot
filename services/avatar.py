"""
Avatar generation — Кулинарный Синдикат.
Overlays a level-specific PNG frame on a user photo using Pillow.

TODO: Add actual frame PNG files to assets/frames/frame_{level}.png (levels 1–50).
      The fallback frame_1.png must always exist for this service to work.
"""
from __future__ import annotations

import io
import os

from PIL import Image


# Path to the directory that holds frame PNG files.
_FRAMES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "frames",
)


def _get_frame_path(level: int) -> str:
    """
    Return the path to the frame PNG for the given level.
    Falls back to frame_1.png if the level-specific file does not exist.
    """
    specific = os.path.join(_FRAMES_DIR, f"frame_{level}.png")
    if os.path.exists(specific):
        return specific
    fallback = os.path.join(_FRAMES_DIR, "frame_1.png")
    return fallback


def generate_avatar(photo_bytes: bytes, level: int) -> bytes:
    """
    Composite a level frame PNG on top of the user's photo.

    Steps:
    1. Open the photo from raw bytes (JPEG / any Pillow-supported format).
    2. Open the frame PNG (with transparency) for the given level.
    3. Resize the frame to match the photo dimensions.
    4. Paste the frame over the photo using the frame's alpha channel as mask.
    5. Return the result as JPEG bytes.

    TODO: Replace frame_1.png placeholder with real branded frame assets.
    """
    # Open base photo
    photo_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    width, height = photo_img.size

    frame_path = _get_frame_path(level)

    if os.path.exists(frame_path):
        frame_img = Image.open(frame_path).convert("RGBA")
        # Scale frame to match photo size
        frame_img = frame_img.resize((width, height), Image.LANCZOS)
        # Composite: paste frame over photo using frame alpha as mask
        photo_img.paste(frame_img, (0, 0), mask=frame_img)

    # Convert back to RGB for JPEG output (JPEG does not support alpha)
    result_rgb = photo_img.convert("RGB")

    output = io.BytesIO()
    result_rgb.save(output, format="JPEG", quality=92)
    return output.getvalue()
