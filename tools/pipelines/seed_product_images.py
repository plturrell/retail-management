"""
seed_product_images.py
-----------------------
Seeds the product_images/ folder by extracting individual product thumbnail
crops from the purchase order form images (images/*.PNG).

Each order form has a "Picture / 图片" column containing small product photos.
This script:
  1. Sends each order form image to Gemini Vision with a bounding-box prompt
  2. Receives JSON with per-item crop coordinates (as % of image dimensions)
  3. Uses Pillow to crop each thumbnail and save it as product_images/{code}.png
  4. Skips a code if a higher-quality image already exists in product_images/

After seeding, you can:
  - Drop your own phone/live-scan photos into product_images/ to replace any crop
  - Run product_image_pipeline.py to build the full visual catalog + embeddings
  - Run product_search.py to search by image, text, or material

Usage:
  export GEMINI_API_KEY="your_key"
  python3 seed_product_images.py
"""

import os
import re
import json
import time
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
from PIL import Image
import io

from google import genai
from google.genai import types

from paths import OCR_OUTPUTS_DIR, PRODUCT_IMAGES_DIR, SOURCE_IMAGES_DIR

# ── Config ────────────────────────────────────────────────────────────────────
IMAGES_DIR = str(SOURCE_IMAGES_DIR)
OCR_DIR = str(OCR_OUTPUTS_DIR)
PRODUCT_DIR = str(PRODUCT_IMAGES_DIR)
VISION_MODEL = "gemini-2.5-flash"

# Padding added around each crop (pixels)
CROP_PADDING = 8

# ── Bounding box prompt ───────────────────────────────────────────────────────
BBOX_PROMPT = """This image is a purchase order form. It has a column titled "Picture" or "图片" containing small product thumbnail photos.

For each product thumbnail you can see, return a JSON array. Each element must have:
  "code": the product code from the same row (e.g. "A031", "H1327B") — look in the adjacent Code/编号 column
  "x_min_pct": left edge of the thumbnail as % of total image width (0-100)
  "y_min_pct": top edge of the thumbnail as % of total image height (0-100)
  "x_max_pct": right edge of the thumbnail as % of total image width (0-100)
  "y_max_pct": bottom edge of the thumbnail as % of total image height (0-100)

Return ONLY the JSON array, no other text. Example:
[
  {"code": "A031", "x_min_pct": 12, "y_min_pct": 37, "x_max_pct": 28, "y_max_pct": 44},
  {"code": "A355", "x_min_pct": 12, "y_min_pct": 44, "x_max_pct": 28, "y_max_pct": 51}
]

Be precise with the coordinates so the crops are tight around the product photo."""

# ── Helpers ───────────────────────────────────────────────────────────────────

def sanitise_code(code: str) -> str:
    """Make the code safe for use as a filename."""
    return re.sub(r'[^\w\-.]', '_', str(code)).strip('_') or "unknown"

def already_seeded(code: str) -> bool:
    """Return True if a manually added image exists (not a seeded crop)."""
    p = Path(PRODUCT_DIR)
    # Check for any file with this code name — if it's there and > 20KB it's
    # probably a real photo rather than a thumbnail crop, so preserve it.
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        f = p / f"{sanitise_code(code)}{ext}"
        if f.exists() and f.stat().st_size > 20_000:
            return True
    return False

def get_bboxes(img_bytes: bytes, mime: str, client) -> list:
    """Ask Gemini to return bounding boxes for all product thumbnails."""
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=VISION_MODEL,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type=mime),
                    BBOX_PROMPT
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            raw = resp.text.strip()
            raw = re.sub(r'^```[a-z]*\n?', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\n?```$', '', raw.strip(), flags=re.MULTILINE)
            return json.loads(raw)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = (attempt + 1) * 30
                print(f"  Rate limited — waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Gemini error: {e}")
                return []

def crop_and_save(img: Image.Image, bbox: dict, out_path: Path):
    """Crop a sub-region from img and save to out_path."""
    w, h = img.size
    x_min = max(0, int(bbox["x_min_pct"] / 100 * w) - CROP_PADDING)
    y_min = max(0, int(bbox["y_min_pct"] / 100 * h) - CROP_PADDING)
    x_max = min(w, int(bbox["x_max_pct"] / 100 * w) + CROP_PADDING)
    y_max = min(h, int(bbox["y_max_pct"] / 100 * h) + CROP_PADDING)

    if x_max <= x_min or y_max <= y_min:
        print(f"    WARNING: degenerate crop box {bbox}, skipping.")
        return False

    cropped = img.crop((x_min, y_min, x_max, y_max))

    # Upscale small thumbnails to at least 256px on the short side for better quality
    min_side = min(cropped.size)
    if min_side < 256:
        scale = 256 / min_side
        new_size = (int(cropped.width * scale), int(cropped.height * scale))
        cropped = cropped.resize(new_size, Image.LANCZOS)

    cropped.save(str(out_path), "PNG")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(PRODUCT_DIR, exist_ok=True)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set. Export it and retry.")
        return

    client = genai.Client(api_key=api_key)

    order_images = sorted(Path(IMAGES_DIR).glob("*.PNG")) + \
                   sorted(Path(IMAGES_DIR).glob("*.png")) + \
                   sorted(Path(IMAGES_DIR).glob("*.jpg")) + \
                   sorted(Path(IMAGES_DIR).glob("*.jpeg"))

    if not order_images:
        print(f"No order form images found in {IMAGES_DIR}/")
        return

    total_saved = 0
    total_skipped = 0

    for img_path in order_images:
        print(f"\n[{img_path.name}] Detecting product thumbnails...")

        with open(img_path, "rb") as f:
            img_bytes = f.read()

        ext  = img_path.suffix.lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/png")

        bboxes = get_bboxes(img_bytes, mime, client)

        if not bboxes:
            print(f"  No bounding boxes returned for {img_path.name}")
            continue

        print(f"  Found {len(bboxes)} product thumbnail(s)")

        # Open image with Pillow for cropping
        pil_img = Image.open(img_path).convert("RGB")

        for bbox in bboxes:
            code = str(bbox.get("code", "unknown")).strip()
            safe_code = sanitise_code(code)
            out_path = Path(PRODUCT_DIR) / f"{safe_code}.png"

            # Don't overwrite real photos the user has added manually
            if already_seeded(code):
                print(f"  [{code}] Skipping — real photo already present")
                total_skipped += 1
                continue

            print(f"  [{code}] Cropping ({bbox['x_min_pct']:.0f}%,{bbox['y_min_pct']:.0f}%) "
                  f"→ ({bbox['x_max_pct']:.0f}%,{bbox['y_max_pct']:.0f}%) ...")

            ok = crop_and_save(pil_img, bbox, out_path)
            if ok:
                size_kb = out_path.stat().st_size // 1024
                print(f"    Saved: {out_path.name} ({size_kb} KB)")
                total_saved += 1
            else:
                total_skipped += 1

        time.sleep(3)  # rate-limit buffer between order forms

    print(f"\n{'='*50}")
    print(f"  Seeding complete!")
    print(f"  Saved  : {total_saved} product image(s)")
    print(f"  Skipped: {total_skipped} (already had real photos)")
    print(f"  Folder : {PRODUCT_DIR}/")
    print(f"\n  Next steps:")
    print(f"  1. Review crops in product_images/ — replace any bad ones with real photos")
    print(f"  2. Run: python3 product_image_pipeline.py   (builds visual catalog + embeddings)")
    print(f"  3. Run: python3 product_search.py --list    (see what was catalogued)")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
