#!/usr/bin/env python3
"""
Stock Check OCR Pipeline — Takashimaya inventory sheets.

Processes handwritten stock check PDFs/images through:
  1. GCP Document AI for OCR
  2. Vertex AI Gemini for structured extraction

Extracts: product_code, product_name, quantity, location, condition, notes.

Usage:
  python stockcheck_ocr_pipeline.py \
    --input-dir data/preprocessed_stockcheck \
    --project-id <GCP_PROJECT_ID> \
    --processor-id <DOC_AI_PROCESSOR_ID> \
    --documentai-location asia-south1 \
    --vertex-location us-central1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_INPUT_DIR = "data/preprocessed_stockcheck"
DEFAULT_OUTPUT_JSON = "data/ocr_outputs/stockcheck.json"
DEFAULT_OUTPUT_MANGLE = "data/mangle_facts/stockcheck.mangle"

# ── Gemini structured schema ─────────────────────────────────────────────────

STOCKCHECK_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "page_number": {"type": "INTEGER"},
        "store_location": {
            "type": "STRING",
            "description": "Store or shelf area if mentioned at top of page",
        },
        "check_date": {
            "type": "STRING",
            "description": "Date of stock check in YYYY-MM-DD if legible, else raw text",
        },
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "product_code": {
                        "type": "STRING",
                        "description": "Internal product/item code (e.g. A008, H1063). Null if not visible.",
                    },
                    "product_name": {
                        "type": "STRING",
                        "description": "Product description as written (material, type, colour etc)",
                    },
                    "product_name_raw": {
                        "type": "STRING",
                        "description": "Exact OCR text before cleanup",
                    },
                    "quantity": {
                        "type": "INTEGER",
                        "description": "Stock count quantity. Null if illegible.",
                        "nullable": True,
                    },
                    "unit_price": {
                        "type": "NUMBER",
                        "description": "Price per unit if written. Null if not visible.",
                        "nullable": True,
                    },
                    "total_price": {
                        "type": "NUMBER",
                        "description": "Total price (qty x unit) if written. Null if not visible.",
                        "nullable": True,
                    },
                    "location": {
                        "type": "STRING",
                        "description": "Shelf/display/cabinet location if noted. Null if not visible.",
                        "nullable": True,
                    },
                    "condition": {
                        "type": "STRING",
                        "description": "Condition notes (damaged, display, etc). Null if none.",
                        "nullable": True,
                    },
                    "notes": {
                        "type": "STRING",
                        "description": "Any other handwritten annotations.",
                        "nullable": True,
                    },
                },
                "required": ["product_name", "product_name_raw"],
            },
        },
    },
    "required": ["page_number", "items"],
}


# ── Document AI helpers (shared pattern with sales_taka pipeline) ─────────────

def layout_text(full_text: str, text_anchor: Any) -> str:
    """Extract text span from Document AI text_anchor."""
    if not text_anchor or not text_anchor.text_segments:
        return ""
    parts: list[str] = []
    for seg in text_anchor.text_segments:
        start = int(seg.start_index) if seg.start_index else 0
        end = int(seg.end_index)
        parts.append(full_text[start:end])
    return "".join(parts).strip()


def normalized_xy(layout: Any) -> tuple[float, float]:
    """Return average normalized (x, y) of bounding polygon vertices."""
    verts = layout.bounding_poly.normalized_vertices
    if not verts:
        return 0.0, 0.0
    xs = [v.x for v in verts]
    ys = [v.y for v in verts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _build_ocr_request(
    client: Any,
    name: str,
    raw_document: Any,
    *,
    premium: bool = True,
) -> Any:
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
        "You are reading handwritten retail stock check / inventory sheets.\n"
        "Extract every product line item from the OCR text.\n\n"
        "Rules:\n"
        "- product_code: item codes like A008, H1063, H1327B, A446 etc. Null if absent.\n"
        "- product_name: cleaned description (material, type, colour, size).\n"
        "- product_name_raw: exact OCR text before you cleaned it.\n"
        "- quantity: integer count. Null if illegible or missing.\n"
        "- unit_price / total_price: numeric if written. Null if absent.\n"
        "- location: shelf/cabinet/display area if noted.\n"
        "- condition: any damage/display notes.\n"
        "- notes: any other annotations.\n"
        "- check_date: date at top of page if visible, YYYY-MM-DD format.\n"
        "- store_location: store name/area if visible at top.\n\n"
        "Preserve uncertain text — do NOT invent values.\n\n"
        f"DOCUMENT: {document_name}\n\n"
        + "\n".join(rendered)
    )


def extract_stockcheck_with_vertex(
    document_name: str,
    pages: list[dict[str, Any]],
    project_id: str,
    location: str,
    model: str,
    max_retries: int = 2,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    import signal

    prompt = build_vertex_prompt(document_name, pages)

    for attempt in range(max_retries + 1):
        try:
            def _timeout_handler(signum: int, frame: Any) -> None:
                raise TimeoutError(f"API call timed out after {timeout_seconds}s")

            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)
            response_text = ""
            try:
                if model.startswith("deepseek"):
                    import os
                    from openai import OpenAI
                    deepseek_prompt = prompt + "\n\nYou MUST return ONLY valid JSON adhering exactly to this schema:\n" + json.dumps(STOCKCHECK_SCHEMA, indent=2)
                    client = OpenAI(
                        api_key=os.environ.get("DEEPSEEK_API_KEY"),
                        base_url="https://api.deepseek.com",
                    )
                    response = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": deepseek_prompt}],
                        temperature=0.1,
                        max_tokens=8192,
                        response_format={"type": "json_object"},
                    )
                    response_text = response.choices[0].message.content or ""
                else:
                    from google import genai
                    from google.genai import types
                    client = genai.Client(vertexai=True, project=project_id, location=location)
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=STOCKCHECK_SCHEMA,
                            temperature=0.1,
                            max_output_tokens=8192,
                        ),
                    )
                    response_text = response.text or ""
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            if not response_text:
                return {"page_number": 0, "items": []}
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            print(f"    WARNING: invalid JSON ({exc}), skipping extraction")
            return {"page_number": 0, "items": [], "notes": f"JSON error: {exc}"}
        except (TimeoutError, Exception) as exc:
            if attempt < max_retries:
                wait = 5 * (attempt + 1)
                print(f"    RETRY {attempt+1}/{max_retries}: {exc} — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"    ERROR: {exc} after {max_retries} retries, skipping")
                return {"page_number": 0, "items": [], "notes": f"Failed: {exc}"}


# ── Output writers ────────────────────────────────────────────────────────────

def mangle_str(value: Any) -> str:
    if value is None:
        return '"null"'
    return '"' + str(value).replace('"', '\\"').replace("\n", " ").strip() + '"'


def mangle_num(value: Any) -> str:
    if value in (None, "", "null"):
        return "0"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    return str(int(number)) if number == int(number) else str(round(number, 4))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def write_mangle(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for page_data in payload.get("pages", []):
        doc_name = page_data.get("document_name", "")
        page_num = page_data.get("page_number", 0)
        for item in page_data.get("items", []):
            lines.append(
                f"stockcheck_item("
                f"{mangle_str(doc_name)}, "
                f"{mangle_num(page_num)}, "
                f"{mangle_str(item.get('product_code'))}, "
                f"{mangle_str(item.get('product_name'))}, "
                f"{mangle_num(item.get('quantity'))}, "
                f"{mangle_num(item.get('unit_price'))}, "
                f"{mangle_num(item.get('total_price'))}, "
                f"{mangle_str(item.get('location'))}, "
                f"{mangle_str(item.get('condition'))}, "
                f"{mangle_str(item.get('notes'))}"
                f")."
            )
    path.write_text("\n".join(lines) + "\n" if lines else "")


# ── CLI ───────────────────────────────────────────────────────────────────────

def validate_env(project_id: str, processor_id: str) -> None:
    errors: list[str] = []
    if not project_id:
        errors.append("GCP project ID is required (--project-id or GOOGLE_CLOUD_PROJECT)")
    if not processor_id:
        errors.append("Document AI processor ID is required (--processor-id or DOCUMENT_AI_PROCESSOR_ID)")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stock Check OCR Pipeline")
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

    # Collect images
    image_files = sorted(
        p for ext in ("*.png", "*.jpg", "*.jpeg") for p in input_dir.glob(ext)
    )
    if not image_files:
        print(f"No images found in {input_dir}")
        sys.exit(1)

    print(f"Found {len(image_files)} stock check images")

    all_pages: list[dict[str, Any]] = []
    total_items = 0

    for idx, img_path in enumerate(image_files, start=1):
        print(f"  [{idx}/{len(image_files)}] {img_path.name}...", end=" ", flush=True)
        mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"

        pages = ocr_image(
            image_path=img_path,
            mime_type=mime,
            project_id=args.project_id,
            location=args.documentai_location,
            processor_id=args.processor_id,
            processor_version=args.processor_version,
        )

        extracted = extract_stockcheck_with_vertex(
            document_name=img_path.name,
            pages=pages,
            project_id=args.project_id,
            location=args.vertex_location,
            model=args.model,
        )

        n_items = len(extracted.get("items", []))
        total_items += n_items
        extracted["document_name"] = img_path.name
        all_pages.append(extracted)
        print(f"items={n_items}", flush=True)
        sys.stdout.flush()

    payload = {"pages": all_pages, "total_items": total_items}
    write_json(output_json, payload)
    write_mangle(output_mangle, payload)

    print(f"\n{'='*50}")
    print(f"Total pages:  {len(all_pages)}")
    print(f"Total items:  {total_items}")
    print(f"JSON   -> {output_json}")
    print(f"Mangle -> {output_mangle}")
    
    try:
        sys.path.append(str(repo_root / "tools" / "scripts"))
        from vault_utils import upload_to_vault
        doc_id = "stockcheck" # Or a dynamically generated logic based on filename
        print(f"\nUploading to OCR Vault Staging as {doc_id}...")
        upload_to_vault(args.project_id, doc_id, "Stockcheck Batch", payload)
        print("Vault upload successful.")
    except Exception as e:
        print(f"Error executing vault upload: {e}")


if __name__ == "__main__":
    main()
