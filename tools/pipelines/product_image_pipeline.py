"""
product_image_pipeline.py
--------------------------
Gemini Vision pipeline for retail product image recognition.

For each image in product_images/:
  1. Sends image to Gemini Vision with a structured extraction prompt
  2. Extracts: dominant_colour, material_type, object_shape, style_tags, description
  3. Computes a text embedding using Gemini text-embedding-004
  4. Stores embeddings as product_embeddings.npy (numpy) for similarity search
  5. Writes structured Mangle facts to mangle_facts/product_catalog.mangle

Naming convention (optional):
  product_images/A031.jpg  -> code "A031" auto-detected from filename
  product_images/photo1.jpg -> code derived from filename, no auto-link

Usage:
  export GEMINI_API_KEY="your_key"
  python3 product_image_pipeline.py

Output:
  mangle_facts/product_catalog.mangle  — visual descriptor facts
  product_embeddings.npy               — numpy array of embeddings
  product_embedding_index.json         — maps embedding row -> product code/file
"""

import os
import json
import time
import re
import numpy as np
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from paths import EMBED_INDEX_PATH, EMBED_NPY_PATH, MANGLE_FACTS_DIR, PRODUCT_IMAGES_DIR

# ── Config ────────────────────────────────────────────────────────────────────
IMAGES_DIR = str(PRODUCT_IMAGES_DIR)
OUT_DIR = str(MANGLE_FACTS_DIR)
CATALOG_FILE = os.path.join(OUT_DIR, "product_catalog.mangle")
EMBED_NPY = str(EMBED_NPY_PATH)
EMBED_INDEX = str(EMBED_INDEX_PATH)

VISION_MODEL    = "gemini-2.5-flash"
EMBED_MODEL     = "gemini-embedding-2-preview"

CNY_SGD_RATE    = 5.34   # must match ocr_to_mangle.py

# ── Prompt ────────────────────────────────────────────────────────────────────
VISION_PROMPT = """You are a luxury retail product cataloguing AI.
Analyse this product image and return ONLY a JSON object with these exact fields:

{
  "dominant_colour": "<primary colour of the object, e.g. gold, amber, green>",
  "secondary_colour": "<secondary colour if present, else null>",
  "material_type": "<main material, e.g. copper, crystal, marble, glass, stone>",
  "secondary_material": "<secondary material if present, else null>",
  "object_shape": "<shape/form, e.g. bookend, vase, figurine, candleholder, bowl, tower>",
  "style_tags": ["<tag1>", "<tag2>", "<tag3>"],
  "estimated_height_cm": <number or null>,
  "surface_finish": "<e.g. polished, matte, textured, rough>",
  "visual_description": "<2-3 sentence vivid English description of the product for a luxury catalogue>"
}

Be precise. Do not add commentary outside the JSON object."""

# ── Helpers ───────────────────────────────────────────────────────────────────

def mangle_str(v):
    if v is None: return '"null"'
    return '"' + str(v).replace('"', '\\"').replace('\n', ' ').strip() + '"'

def mangle_list(lst):
    """Render a Python list as a Mangle list literal."""
    if not lst: return '[]'
    items = ", ".join(mangle_str(x) for x in lst)
    return f'[{items}]'

def get_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif"}.get(ext.lstrip("."), "image/jpeg")

def code_from_filename(path: Path) -> str:
    """
    Derive a product code from the filename.
    'A031.jpg' -> 'A031', 'product_H489A.png' -> 'H489A'
    Falls back to the stem if no recognisable code found.
    """
    stem = path.stem
    # Look for pattern like A031, H1327B, H489A etc.
    m = re.search(r'([A-H]\d{3,4}[A-Z]?)', stem, re.IGNORECASE)
    return m.group(1).upper() if m else stem

def get_text_embedding(client, text: str) -> list:
    """Get a text embedding vector from Gemini."""
    for attempt in range(3):
        try:
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
            )
            return result.embeddings[0].values
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = (attempt + 1) * 20
                print(f"    Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                raise

# ── Core processing ───────────────────────────────────────────────────────────

def process_image(path: Path, client) -> Optional[dict]:
    """Send image to Gemini Vision, return parsed descriptor dict."""
    print(f"  Analysing {path.name}...")
    try:
        with open(path, "rb") as f:
            img_bytes = f.read()

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=VISION_MODEL,
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type=get_mime(path)),
                        VISION_PROMPT
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    wait = (attempt + 1) * 30
                    print(f"    Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        raw = response.text.strip()
        # Strip markdown fences if present
        raw = re.sub(r'^```[a-z]*\n?', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\n?```$', '', raw, flags=re.MULTILINE)
        data = json.loads(raw)
        print(f"    -> {data.get('object_shape','?')} | {data.get('material_type','?')} | {data.get('dominant_colour','?')}")
        return data

    except Exception as e:
        print(f"    ERROR: {e}")
        return None


def write_mangle_fact(f, code: str, filename: str, descriptor: dict):
    """Write a product_visual fact to the mangle file."""
    colour    = descriptor.get("dominant_colour") or "unknown"
    colour2   = descriptor.get("secondary_colour")
    material  = descriptor.get("material_type") or "unknown"
    material2 = descriptor.get("secondary_material")
    shape     = descriptor.get("object_shape") or "unknown"
    tags      = descriptor.get("style_tags") or []
    finish    = descriptor.get("surface_finish") or "unknown"
    desc      = descriptor.get("visual_description") or ""

    # Combined material string
    mat_full = material if not material2 else f"{material}, {material2}"
    col_full = colour   if not colour2   else f"{colour}, {colour2}"

    f.write(
        f'product_visual({mangle_str(code)}, {mangle_str(filename)}, '
        f'{mangle_str(col_full)}, {mangle_str(mat_full)}, '
        f'{mangle_str(shape)}, {mangle_str(finish)}, '
        f'{mangle_list(tags)}, {mangle_str(desc)}).\n'
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set.")
        return

    client = genai.Client(api_key=api_key)

    images_path = Path(IMAGES_DIR)
    image_files = sorted([
        p for p in images_path.iterdir()
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ])

    if not image_files:
        print(f"No product images found in {IMAGES_DIR}/")
        print("Add product photos (e.g. A031.jpg, H1327B.png) and re-run.")
        return

    print(f"\nFound {len(image_files)} product image(s) in {IMAGES_DIR}/\n")

    embeddings   = []
    embed_index  = []
    processed    = 0

    with open(CATALOG_FILE, "w", encoding="utf-8") as mangle_f:
        mangle_f.write("# Product visual catalog — auto-generated by product_image_pipeline.py\n")
        mangle_f.write("# Schema:\n")
        mangle_f.write("#   product_visual(code, filename, colour, material, shape, finish, style_tags, description).\n\n")

        for img_path in image_files:
            code = code_from_filename(img_path)
            print(f"[{img_path.name}] -> code: {code}")

            descriptor = process_image(img_path, client)
            if not descriptor:
                continue

            write_mangle_fact(mangle_f, code, img_path.name, descriptor)

            # Build embedding text from descriptor
            embed_text = (
                f"{descriptor.get('object_shape','')} made of "
                f"{descriptor.get('material_type','')} "
                f"{'and ' + descriptor.get('secondary_material','') if descriptor.get('secondary_material') else ''}. "
                f"Colour: {descriptor.get('dominant_colour','')}. "
                f"Style: {', '.join(descriptor.get('style_tags') or [])}. "
                f"{descriptor.get('visual_description','')}"
            ).strip()

            print(f"    Computing embedding...")
            try:
                vec = get_text_embedding(client, embed_text)
                embeddings.append(vec)
                embed_index.append({"code": code, "file": img_path.name, "text": embed_text})
                processed += 1
            except Exception as e:
                print(f"    Embedding failed: {e}")

            time.sleep(2)  # rate-limit buffer between images

    # Save embeddings
    if embeddings:
        np.save(EMBED_NPY, np.array(embeddings, dtype=np.float32))
        with open(EMBED_INDEX, "w") as idx_f:
            json.dump(embed_index, idx_f, indent=2)
        print(f"\nSaved {len(embeddings)} embedding(s) to {EMBED_NPY}")

    print(f"\nCatalog written to {CATALOG_FILE}")
    print(f"Processed {processed}/{len(image_files)} image(s) successfully.")


if __name__ == "__main__":
    main()
