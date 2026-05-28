# =============================================================================
# Snapshot Annotator — Pillow-based blur / rect / text / arrow rendering
# =============================================================================

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _resolve_coords(op: Dict[str, Any], w: int, h: int):
    """Convert normalised 0..1 coords to pixel ints."""
    x = int(op.get("x", 0) * w)
    y = int(op.get("y", 0) * h)
    return x, y


def apply_operations(image_bytes: bytes, operations: List[Dict[str, Any]]) -> bytes:
    """
    Apply a list of annotation operations to a JPEG image.

    Supported operation types:
      blur  — {"type":"blur",  "x":0..1, "y":0..1, "w":0..1, "h":0..1, "radius":25}
      rect  — {"type":"rect",  "x":0..1, "y":0..1, "w":0..1, "h":0..1, "color":"red", "width":3}
      text  — {"type":"text",  "x":0..1, "y":0..1, "text":"...", "color":"white", "size":20}
      arrow — {"type":"arrow", "x1":0..1,"y1":0..1,"x2":0..1,"y2":0..1,"color":"red","width":3}

    Returns JPEG bytes of the annotated image.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow is required for snapshot annotation") from exc

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    W, H = img.size

    for op in operations:
        op_type = op.get("type", "").lower()

        try:
            if op_type == "blur":
                px = int(op.get("x", 0) * W)
                py = int(op.get("y", 0) * H)
                pw = max(1, int(op.get("w", 0.1) * W))
                ph = max(1, int(op.get("h", 0.1) * H))
                radius = int(op.get("radius", 25))
                box = (px, py, px + pw, py + ph)
                region = img.crop(box)
                blurred = region.filter(ImageFilter.GaussianBlur(radius=radius))
                img.paste(blurred, box)
                # Re-draw on updated image
                draw = ImageDraw.Draw(img)

            elif op_type == "rect":
                px = int(op.get("x", 0) * W)
                py = int(op.get("y", 0) * H)
                pw = max(1, int(op.get("w", 0.1) * W))
                ph = max(1, int(op.get("h", 0.1) * H))
                color = op.get("color", "red")
                line_width = int(op.get("width", 3))
                draw.rectangle(
                    [(px, py), (px + pw, py + ph)],
                    outline=color,
                    width=line_width,
                )

            elif op_type == "text":
                px, py = _resolve_coords(op, W, H)
                text = str(op.get("text", ""))
                color = op.get("color", "white")
                size = int(op.get("size", 20))
                # Try to load a decent font; fall back gracefully
                font = None
                font_candidates = [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                    "/System/Library/Fonts/Helvetica.ttc",
                ]
                for path in font_candidates:
                    try:
                        font = ImageFont.truetype(path, size)
                        break
                    except Exception:
                        continue
                if font is None:
                    font = ImageFont.load_default()

                # Shadow for legibility
                draw.text((px + 1, py + 1), text, fill="black", font=font)
                draw.text((px, py), text, fill=color, font=font)

            elif op_type == "arrow":
                x1 = int(op.get("x1", 0) * W)
                y1 = int(op.get("y1", 0) * H)
                x2 = int(op.get("x2", 0.1) * W)
                y2 = int(op.get("y2", 0.1) * H)
                color = op.get("color", "red")
                line_width = int(op.get("width", 3))

                # Line
                draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)

                # Arrowhead (simple triangle approximation)
                import math
                angle = math.atan2(y2 - y1, x2 - x1)
                arrow_size = max(10, line_width * 4)
                left_angle = angle + math.radians(150)
                right_angle = angle - math.radians(150)
                lx = int(x2 + arrow_size * math.cos(left_angle))
                ly = int(y2 + arrow_size * math.sin(left_angle))
                rx = int(x2 + arrow_size * math.cos(right_angle))
                ry = int(y2 + arrow_size * math.sin(right_angle))
                draw.polygon([(x2, y2), (lx, ly), (rx, ry)], fill=color)

            else:
                logger.warning("Unknown annotation op type: %s", op_type)

        except Exception as op_exc:
            logger.warning("Annotation op %s failed: %s", op_type, op_exc)
            continue

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
