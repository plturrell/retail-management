#!/usr/bin/env python3
"""
Material Infocard OCR Pipeline — extract a structured material glossary.

Processes pre-processed material reference card images through:
  1. GCP Document AI for OCR
  2. Vertex AI Gemini for structured extraction

Extracts: material name, category, properties, sourcing info, care instructions,
and product suitability for each material infocard.

Usage:
  python material_infocard_ocr_pipeline.py \
    --input-dir data/preprocessed_materials \
    --project-id <GCP_PROJECT_ID> \
    --processor-id <DOC_AI_PROCESSOR_ID>
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_INPUT_DIR = "data/preprocessed_materials"
DEFAULT_OUTPUT_JSON = "data/ocr_outputs/material_glossary.json"
DEFAULT_OUTPUT_MANGLE = "data/mangle_facts/material_glossary.mangle"

# ── Gemini structured schema ─────────────────────────────────────────────────

MATERIAL_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "page_number": {"type": "INTEGER"},
        "materials": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "material_name": {
                        "type": "STRING",
                        "description": "Name of the gemstone, crystal, or material (e.g. Amethyst, Jade, Rose Quartz)",
                    },
                    "material_name_raw": {
                        "type": "STRING",
                        "description": "Exact OCR text before cleanup",
                    },
                    "category": {
                        "type": "STRING",
                        "description": "Category: Gemstone, Crystal, Mineral, Metal, Organic, Stone, Glass, or Other",
                    },
                    "colour": {
                        "type": "STRING",
                        "description": "Primary colour or colour range. Null if not mentioned.",
                        "nullable": True,
                    },
                    "hardness": {
                        "type": "STRING",
                        "description": "Mohs hardness scale value or range. Null if not listed.",
                        "nullable": True,
                    },
                    "origin": {
                        "type": "STRING",
                        "description": "Geographic origin or sourcing region. Null if not mentioned.",
                        "nullable": True,
                    },
                    "properties": {
                        "type": "STRING",
                        "description": "Physical properties, metaphysical properties, or healing associations mentioned.",
                        "nullable": True,
                    },
                    "care_instructions": {
                        "type": "STRING",
                        "description": "Care/cleaning/storage instructions. Null if not mentioned.",
                        "nullable": True,
                    },
                    "product_suitability": {
                        "type": "STRING",
                        "description": "What products this material is suited for (e.g. bracelets, necklaces, home decor, bookends).",
                        "nullable": True,
                    },
                    "price_range": {
                        "type": "STRING",
                        "description": "Price tier or range if mentioned (e.g. premium, mid-range). Null if not listed.",
                        "nullable": True,
                    },
                    "notes": {
                        "type": "STRING",
                        "description": "Any other information on the card.",
                        "nullable": True,
                    },
                },
                "required": ["material_name", "material_name_raw", "category"],
            },
        },
    },
    "required": ["page_number", "materials"],
}


# ── Document AI helpers (reused from stockcheck pipeline) ─────────────────────

def layout_text(full_text: str, text_anchor: Any) -> str:
    if not text_anchor or not text_anchor.text_segments:
        return ""
    parts: list[str] = []
    for seg in text_anchor.text_segments:
        start = int(seg.start_index) if seg.start_index else 0
        end = int(seg.end_index)
        parts.append(full_text[start:end])
    return "".join(parts).strip()


def normalized_xy(layout: Any) -> tuple[float, float]:
    verts = layout.bounding_poly.normalized_vertices
    if not verts:
        return 0.0, 0.0
    xs = [v.x for v in verts]
    ys = [v.y for v in verts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _build_ocr_request(client: Any, name: str, raw_document: Any, *, premium: bool = True) -> Any:
    from google.cloud import documentai_v1 as documentai

    if premium:
        ocr_config = documentai.OcrConfig(
            enable_image_quality_scores=True,
            enable_symbol=True,
            premium_features=documentai.OcrConfig.PremiumFeatures(
                compute_style_info=True,
                enable_selection_mark_detection=True,
            ),
        )
    else:
        ocr_config = documentai.OcrConfig()

    return documentai.ProcessRequest(
        name=name,
        raw_document=raw_document,
        process_options=documentai.ProcessOptions(ocr_config=ocr_config),
    )


def _process_with_fallback(client: Any, name: str, raw_document: Any) -> Any:
    from google.api_core import exceptions as gapi_exceptions

    try:
        request = _build_ocr_request(client, name, raw_document, premium=True)
        return client.process_document(request=request)
    except gapi_exceptions.InvalidArgument as exc:
        if "premium" in str(exc).lower():
            print("    (using basic OCR — processor does not support premium features)")
            request = _build_ocr_request(client, name, raw_document, premium=False)
            return client.process_document(request=request)
        raise


def _extract_pages(document: Any) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    full_text = document.text or ""
    for page in document.pages:
        lines = getattr(page, "lines", None) or getattr(page, "paragraphs", None) or []
        page_lines: list[dict[str, Any]] = []
        for line_no, line in enumerate(lines, start=1):
            text = layout_text(full_text, line.layout.text_anchor)
            if not text:
                continue
            x, y = normalized_xy(line.layout)
            page_lines.append({"line_no": line_no, "x": round(x, 4), "y": round(y, 4), "text": text})
        pages.append({
            "page_number": page.page_number,
            "lines": sorted(page_lines, key=lambda row: (row["y"], row["x"])),
        })
    return pages


def ocr_image(
    image_path: Path,
    mime_type: str,
    project_id: str,
    location: str,
    processor_id: str,
    processor_version: str = "",
) -> list[dict[str, Any]]:
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai_v1 as documentai

    endpoint = f"{location}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{endpoint}:443")
    )
    if processor_version:
        name = client.processor_version_path(project_id, location, processor_id, processor_version)
    else:
        name = client.processor_path(project_id, location, processor_id)

    raw_document = documentai.RawDocument(content=image_path.read_bytes(), mime_type=mime_type)
    response = _process_with_fallback(client, name, raw_document)
    return _extract_pages(response.document)


# ── Vertex AI Gemini extraction ───────────────────────────────────────────────

def build_vertex_prompt(document_name: str, pages: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for page in pages:
        rendered.append(f"PAGE {page['page_number']}")
        for line in page["lines"]:
            rendered.append(f"L{line['line_no']:03d} y={line['y']:.4f} x={line['x']:.4f} | {line['text']}")

    return (
        "You are reading printed/handwritten material reference info cards for a luxury "
        "crystal, gemstone and jewellery retail store.\n\n"
        "Each card describes a material used in jewellery or home decor products.\n"
        "Extract every distinct material from the OCR text.\n\n"
        "Rules:\n"
        "- material_name: canonical name (e.g. 'Amethyst', 'Rose Quartz', 'Jade')\n"
        "- material_name_raw: exact OCR text\n"
        "- category: Gemstone, Crystal, Mineral, Metal, Organic, Stone, Glass, or Other\n"
        "- colour: primary colour(s) described\n"
        "- hardness: Mohs scale if mentioned\n"
        "- origin: geographic origin if mentioned\n"
        "- properties: physical/metaphysical properties described\n"
        "- care_instructions: cleaning/storage info\n"
        "- product_suitability: what products the material is good for\n"
        "- price_range: price tier if described\n"
        "- notes: any other info\n\n"
        "Preserve uncertain text — do NOT invent values.\n\n"
        f"DOCUMENT: {document_name}\n\n"
        + "\n".join(rendered)
    )


def extract_materials_with_vertex(
    document_name: str,
    pages: list[dict[str, Any]],
    project_id: str,
    location: str,
    model: str,
    max_retries: int = 2,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project_id, location=location)
    prompt = build_vertex_prompt(document_name, pages)

    for attempt in range(max_retries + 1):
        try:
            def _timeout_handler(signum: int, frame: Any) -> None:
                raise TimeoutError(f"Vertex AI call timed out after {timeout_seconds}s")

            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=MATERIAL_SCHEMA,
                        temperature=0.1,
                        max_output_tokens=16384,
                    ),
                )
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            if response.text:
                try:
                    return json.loads(response.text)
                except json.JSONDecodeError as exc:
                    print(f"    WARNING: JSON decode error on attempt {attempt+1}: {exc}")
                    if attempt < max_retries:
                        time.sleep(3)
                        continue
                    return {"page_number": 0, "materials": []}

        except TimeoutError:
            print(f"    WARNING: Timeout on attempt {attempt+1}")
            if attempt < max_retries:
                time.sleep(5)
                continue
            return {"page_number": 0, "materials": []}
        except Exception as exc:
            err_str = str(exc).lower()
            if "429" in err_str or "resource_exhausted" in err_str:
                wait = 15 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if attempt < max_retries:
                print(f"    WARNING: attempt {attempt+1} failed: {exc}")
                time.sleep(5)
                continue
            print(f"    ERROR: all retries failed: {exc}")
            return {"page_number": 0, "materials": []}

    return {"page_number": 0, "materials": []}


# ── Mangle writer ────────────────────────────────────────────────────────────

def _mangle_str(val: str | None) -> str:
    if val is None:
        return '""'
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def write_mangle(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for page in data.get("pages", []):
        for mat in page.get("materials", []):
            name = _mangle_str(mat.get("material_name"))
            cat = _mangle_str(mat.get("category"))
            colour = _mangle_str(mat.get("colour"))
            hardness = _mangle_str(mat.get("hardness"))
            origin = _mangle_str(mat.get("origin"))
            props = _mangle_str(mat.get("properties"))
            care = _mangle_str(mat.get("care_instructions"))
            suit = _mangle_str(mat.get("product_suitability"))
            lines.append(
                f"material_info({name}, {cat}, {colour}, {hardness}, {origin}, {props}, {care}, {suit})."
            )
    path.write_text("\n".join(lines) + "\n")


# ── Validate env ─────────────────────────────────────────────────────────────

def validate_env(project_id: str, processor_id: str) -> None:
    missing: list[str] = []
    if not project_id:
        missing.append("GOOGLE_CLOUD_PROJECT / --project-id")
    if not processor_id:
        missing.append("DOCUMENT_AI_PROCESSOR_ID / --processor-id")
    if missing:
        print(f"ERROR: Missing required config: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Material Infocard OCR Pipeline")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-mangle", default=DEFAULT_OUTPUT_MANGLE)
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", ""),
    )
    parser.add_argument("--vertex-location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    parser.add_argument("--documentai-location", default=os.environ.get("DOCUMENT_AI_LOCATION", "us"))
    parser.add_argument("--processor-id", default=os.environ.get("DOCUMENT_AI_PROCESSOR_ID", ""))
    parser.add_argument("--processor-version", default=os.environ.get("DOCUMENT_AI_PROCESSOR_VERSION", ""))
    parser.add_argument("--model", default=os.environ.get("VERTEX_GEMINI_MODEL", "gemini-2.5-flash"))
    args = parser.parse_args()

    validate_env(args.project_id, args.processor_id)

    repo_root = Path(__file__).resolve().parents[2]

    def _repo_path(p: str | Path) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()

    input_dir = _repo_path(args.input_dir)
    output_json = _repo_path(args.output_json)
    output_mangle = _repo_path(args.output_mangle)

    image_files = sorted(
        [f for f in input_dir.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".tiff")]
    )
    if not image_files:
        print(f"No images found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(image_files)} images in {input_dir}")
    print("=" * 50)

    all_materials: list[dict[str, Any]] = []
    all_pages: list[dict[str, Any]] = []
    total_count = len(image_files)

    for idx, img in enumerate(image_files, 1):
        mime = "image/png" if img.suffix.lower() == ".png" else "image/jpeg"
        sys.stdout.write(f"  [{idx}/{total_count}] {img.name}...")
        sys.stdout.flush()

        pages = ocr_image(
            image_path=img,
            mime_type=mime,
            project_id=args.project_id,
            location=args.documentai_location,
            processor_id=args.processor_id,
            processor_version=args.processor_version,
        )

        extracted = extract_materials_with_vertex(
            document_name=img.name,
            pages=pages,
            project_id=args.project_id,
            location=args.vertex_location,
            model=args.model,
        )

        materials = extracted.get("materials", [])
        print(f"     materials={len(materials)}")

        page_data = {
            "image": img.name,
            "page_number": extracted.get("page_number", idx),
            "materials": materials,
        }
        all_pages.append(page_data)
        all_materials.extend(materials)

        time.sleep(1)

    # Deduplicate materials by name
    seen_names: dict[str, dict[str, Any]] = {}
    for mat in all_materials:
        name = (mat.get("material_name") or "").strip().lower()
        if not name:
            continue
        if name not in seen_names:
            seen_names[name] = mat
        else:
            # Merge: keep longer/richer values
            existing = seen_names[name]
            for field in ["colour", "hardness", "origin", "properties", "care_instructions",
                          "product_suitability", "price_range", "notes"]:
                new_val = mat.get(field)
                old_val = existing.get(field)
                if new_val and (not old_val or len(str(new_val)) > len(str(old_val))):
                    existing[field] = new_val

    unique_materials = list(seen_names.values())

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_pages": len(all_pages),
        "total_materials_raw": len(all_materials),
        "total_materials_unique": len(unique_materials),
        "glossary": unique_materials,
        "pages": all_pages,
    }

    write_json(output_json, payload)
    write_mangle(output_mangle, payload)

    print()
    print("=" * 50)
    print(f"Total pages:     {len(all_pages)}")
    print(f"Total materials: {len(all_materials)} raw, {len(unique_materials)} unique")
    print(f"JSON   -> {output_json}")
    print(f"Mangle -> {output_mangle}")

    # Summary by category
    from collections import Counter
    cats = Counter(m.get("category", "Other") for m in unique_materials)
    print(f"\nBy category:")
    for cat, count in cats.most_common():
        print(f"  {cat:20s} {count:3d}")

    names = sorted(m.get("material_name", "") for m in unique_materials)
    print(f"\nMaterials: {', '.join(names)}")


if __name__ == "__main__":
    main()
