"""
product_search.py
-----------------
CLI similarity search over the product catalog built by product_image_pipeline.py.

Usage:
  # Find products visually similar to a query image
  python3 product_search.py --image path/to/query.jpg

  # Find products matching a text description
  python3 product_search.py --text "blue crystal marble vase"

  # Filter by material keyword
  python3 product_search.py --material marble

  # Filter by colour keyword
  python3 product_search.py --colour crystal

  # Combine: text query + material filter
  python3 product_search.py --text "luxury decorative piece" --material copper

  # Show top N results (default 5)
  python3 product_search.py --text "green stone figurine" --top 10
"""

import os
import json
import argparse
import numpy as np
from pathlib import Path

from google import genai
from google.genai import types

# ── Config ────────────────────────────────────────────────────────────────────
EMBED_NPY    = "/Users/user/Documents/retailmanagement/product_embeddings.npy"
EMBED_INDEX  = "/Users/user/Documents/retailmanagement/product_embedding_index.json"
CATALOG_FILE = "/Users/user/Documents/retailmanagement/mangle_facts/product_catalog.mangle"
VISION_MODEL = "gemini-2.5-flash"
EMBED_MODEL  = "gemini-embedding-2-preview"


# ── Helpers ───────────────────────────────────────────────────────────────────

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1D vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

def load_embeddings():
    """Load the embedding matrix and index from disk."""
    if not os.path.exists(EMBED_NPY) or not os.path.exists(EMBED_INDEX):
        print("ERROR: No embeddings found. Run product_image_pipeline.py first.")
        return None, None
    embeddings = np.load(EMBED_NPY)
    with open(EMBED_INDEX) as f:
        index = json.load(f)
    return embeddings, index

def get_text_embedding(api_key: str, text: str) -> np.ndarray:
    """Get a query text embedding from Gemini."""
    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    )
    return np.array(result.embeddings[0].values, dtype=np.float32)

def get_image_embedding(api_key: str, image_path: str) -> np.ndarray:
    """Use Gemini Vision to describe the query image, then embed the description."""
    client = genai.Client(api_key=api_key)

    ext = Path(image_path).suffix.lower().lstrip(".")
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
    mime = mime_map.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        img_bytes = f.read()

    print("  Describing query image with Gemini Vision...")
    response = client.models.generate_content(
        model=VISION_MODEL,
        contents=[
            types.Part.from_bytes(data=img_bytes, mime_type=mime),
            "Describe this product in detail: shape, material, colour, style, and finish. Write 2-3 sentences as if for a luxury product catalogue."
        ]
    )
    description = response.text.strip()
    print(f"  Description: {description[:120]}...")

    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=description,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    )
    return np.array(result.embeddings[0].values, dtype=np.float32)

def rank_results(query_vec: np.ndarray, embeddings: np.ndarray,
                 index: list, top_n: int,
                 material_filter: str = None,
                 colour_filter: str  = None) -> list:
    """Calculate cosine similarity scores and return sorted top results."""
    scores = []
    for i, entry in enumerate(index):
        # Optional keyword filters on stored text
        text_lower = entry.get("text", "").lower()
        if material_filter and material_filter.lower() not in text_lower:
            continue
        if colour_filter and colour_filter.lower() not in text_lower:
            continue

        sim = cosine_similarity(query_vec, embeddings[i])
        scores.append((sim, entry))

    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[:top_n]

def print_results(results: list, title: str):
    """Pretty-print search results."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if not results:
        print("  No matching products found.")
        return
    for rank, (score, entry) in enumerate(results, 1):
        code = entry.get("code", "?")
        fname = entry.get("file", "?")
        text_preview = entry.get("text", "")[:100]
        print(f"\n  #{rank}  Code: {code}  |  File: {fname}")
        print(f"       Similarity: {score:.4f}")
        print(f"       {text_preview}...")
    print(f"\n{'='*60}\n")

def filter_catalog(keyword: str, field: str) -> list:
    """
    Filter the .mangle catalog directly by a keyword in a specific field.
    Returns matching lines as strings.
    """
    results = []
    if not os.path.exists(CATALOG_FILE):
        return results
    with open(CATALOG_FILE) as f:
        for line in f:
            if line.startswith("product_visual") and keyword.lower() in line.lower():
                results.append(line.strip())
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Search the retail product catalog by image or text."
    )
    parser.add_argument("--image",    type=str, help="Path to query image file")
    parser.add_argument("--text",     type=str, help="Text description to search for")
    parser.add_argument("--material", type=str, help="Filter results by material keyword")
    parser.add_argument("--colour",   type=str, help="Filter results by colour keyword")
    parser.add_argument("--top",      type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--list",     action="store_true", help="List all catalog entries")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")

    # ── List mode ───────────────────────────────────────────────────────────
    if args.list:
        print(f"\n{'='*60}")
        print("  Product Catalog")
        print(f"{'='*60}")
        if not os.path.exists(CATALOG_FILE):
            print("  No catalog found. Run product_image_pipeline.py first.")
        else:
            with open(CATALOG_FILE) as f:
                facts = [l.strip() for l in f if l.startswith("product_visual")]
            if not facts:
                print("  Catalog is empty.")
            for fact in facts:
                print(f"  {fact}")
        print()
        return

    # ── Material/colour direct filter (no embedding needed) ─────────────────
    if (args.material or args.colour) and not (args.image or args.text):
        keyword = args.material or args.colour
        field   = "material" if args.material else "colour"
        results = filter_catalog(keyword, field)
        print(f"\n{'='*60}")
        print(f"  Products with {field}: '{keyword}'")
        print(f"{'='*60}")
        if not results:
            print("  No matches found.")
        for r in results:
            print(f"  {r}")
        print()
        return

    # ── Embedding-based search ───────────────────────────────────────────────
    if not (args.image or args.text):
        parser.print_help()
        return

    if not api_key:
        print("ERROR: GEMINI_API_KEY not set. Export it and retry.")
        return

    embeddings, index = load_embeddings()
    if embeddings is None:
        return

    if args.image:
        if not os.path.exists(args.image):
            print(f"ERROR: Image not found: {args.image}")
            return
        print(f"\nSearching by image: {args.image}")
        query_vec = get_image_embedding(api_key, args.image)
        title = f"Top {args.top} visually similar products"
    else:
        print(f"\nSearching by text: \"{args.text}\"")
        query_vec = get_text_embedding(api_key, args.text)
        title = f"Top {args.top} products matching: \"{args.text}\""

    results = rank_results(query_vec, embeddings, index, args.top,
                           material_filter=args.material,
                           colour_filter=args.colour)
    print_results(results, title)


if __name__ == "__main__":
    main()
