#!/usr/bin/env python3
"""
Process handwritten sales ledgers in docs/sales_taka with GCP services.

Pipeline:
  1. Document AI Enterprise OCR extracts page text + line layout
  2. Vertex AI Gemini converts OCR lines into structured sales entries
  3. Local matching enriches extracted items against:
     - material_reference JSON
     - historical pos_item material text from pos_orders.mangle

Outputs:
  - JSON extraction payload in data/ocr_outputs/
  - Mangle facts in data/mangle_facts/

This script is intentionally GCP-first:
  - Vertex AI / ADC authentication
  - Document AI OCR processor
  - no local OCR fallback
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = "docs/sales_taka"
DEFAULT_OUTPUT_JSON = "data/ocr_outputs/sales_taka_gcp_vertex.json"
DEFAULT_OUTPUT_MANGLE = "data/mangle_facts/sales_taka_sales.mangle"
DEFAULT_MATERIALS_JSON = "data/ocr_outputs/material_reference_adobe_scan_12_apr_2026.json"
DEFAULT_POS_ITEMS = "data/mangle_facts/pos_orders.mangle"


DATE_PATTERNS = [
    re.compile(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b", re.IGNORECASE),
]

GENERIC_MATERIAL_WORDS = {
    "stone",
    "crystal",
    "natural",
    "mineral",
    "marble",
    "copper",
    "glass",
}


ENTRY_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "pages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page_number": {"type": "INTEGER"},
                    "entries": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "date_raw": {"type": "STRING", "nullable": True},
                                "date_iso": {"type": "STRING", "nullable": True},
                                "salesperson_raw": {"type": "STRING", "nullable": True},
                                "salesperson": {"type": "STRING", "nullable": True},
                                "entry_total": {"type": "NUMBER", "nullable": True},
                                "entry_total_raw": {"type": "STRING", "nullable": True},
                                "notes": {"type": "STRING", "nullable": True},
                                "items": {
                                    "type": "ARRAY",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "line_no": {"type": "INTEGER", "nullable": True},
                                            "description_raw": {"type": "STRING"},
                                            "qty": {"type": "NUMBER", "nullable": True},
                                            "qty_raw": {"type": "STRING", "nullable": True},
                                            "amount": {"type": "NUMBER", "nullable": True},
                                            "amount_raw": {"type": "STRING", "nullable": True},
                                        },
                                        "required": ["description_raw"],
                                    },
                                },
                            },
                            "required": ["items"],
                        },
                    },
                },
                "required": ["page_number", "entries"],
            },
        }
    },
    "required": ["pages"],
}


@dataclass(frozen=True)
class MaterialAlias:
    material_key: str
    display_name: str
    alias: str
    alias_norm: str


@dataclass(frozen=True)
class ProductHint:
    code: str
    material_text: str
    material_norm: str


def normalize_space(text: str) -> str:
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_lookup(text: str) -> str:
    text = normalize_space(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


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


def load_material_aliases(path: Path) -> list[MaterialAlias]:
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    aliases: list[MaterialAlias] = []
    for material in payload.get("materials", []):
        display_name = material.get("display_name", "")
        material_key = material.get("material_key", "")
        for alias in material.get("aliases", []) or [display_name]:
            alias = normalize_space(alias)
            alias_norm = normalize_lookup(alias)
            if not alias_norm or alias_norm in GENERIC_MATERIAL_WORDS:
                continue
            aliases.append(
                MaterialAlias(
                    material_key=material_key,
                    display_name=display_name,
                    alias=alias,
                    alias_norm=alias_norm,
                )
            )
    return aliases


def load_product_hints(path: Path) -> list[ProductHint]:
    if not path.exists():
        return []

    hints: list[ProductHint] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("pos_item("):
            continue
        values = re.findall(r'"((?:\\"|[^"])*)"', line)
        if len(values) < 4:
            continue
        code = values[2].replace('\\"', '"')
        material_text = normalize_space(values[3].replace('\\"', '"'))
        material_norm = normalize_lookup(material_text)
        if not material_norm or material_norm in GENERIC_MATERIAL_WORDS:
            continue
        hints.append(ProductHint(code=code, material_text=material_text, material_norm=material_norm))
    return hints


def match_material(description: str, aliases: list[MaterialAlias]) -> dict[str, Any] | None:
    desc_norm = normalize_lookup(description)
    if not desc_norm:
        return None

    best: dict[str, Any] | None = None
    for alias in aliases:
        score = 0.0
        basis = ""
        if alias.alias_norm and alias.alias_norm in desc_norm:
            score = min(1.0, 0.78 + min(0.2, len(alias.alias_norm) / 40))
            basis = "substring"
        else:
            score = SequenceMatcher(None, desc_norm, alias.alias_norm).ratio()
            if score < 0.68:
                continue
            basis = "fuzzy"

        candidate = {
            "material_key": alias.material_key,
            "display_name": alias.display_name,
            "matched_alias": alias.alias,
            "score": round(score, 4),
            "basis": basis,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def match_product_hint(description: str, hints: list[ProductHint]) -> dict[str, Any] | None:
    desc_norm = normalize_lookup(description)
    if not desc_norm:
        return None

    best: dict[str, Any] | None = None
    for hint in hints:
        score = 0.0
        basis = ""
        if hint.material_norm in desc_norm or desc_norm in hint.material_norm:
            score = 0.75
            basis = "substring"
        else:
            score = SequenceMatcher(None, desc_norm, hint.material_norm).ratio()
            if score < 0.72:
                continue
            basis = "fuzzy"

        candidate = {
            "code": hint.code,
            "material_text": hint.material_text,
            "score": round(score, 4),
            "basis": basis,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def layout_text(full_text: str, anchor: Any) -> str:
    fragments: list[str] = []
    for segment in getattr(anchor, "text_segments", []) or []:
        start = int(segment.start_index or 0)
        end = int(segment.end_index or 0)
        fragments.append(full_text[start:end])
    return normalize_space("".join(fragments))


def normalized_xy(layout: Any) -> tuple[float, float]:
    vertices = getattr(getattr(layout, "bounding_poly", None), "normalized_vertices", None) or []
    if not vertices:
        return 0.0, 0.0
    xs = [float(v.x) for v in vertices if v.x is not None]
    ys = [float(v.y) for v in vertices if v.y is not None]
    return (min(xs) if xs else 0.0, min(ys) if ys else 0.0)


def ocr_pdf_with_document_ai(
    pdf_path: Path,
    project_id: str,
    location: str,
    processor_id: str,
    processor_version: str = "",
) -> list[dict[str, Any]]:
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai_v1 as documentai
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency google-cloud-documentai. Install backend requirements first."
        ) from exc

    endpoint = f"{location}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{endpoint}:443")
    )
    if processor_version:
        name = client.processor_version_path(project_id, location, processor_id, processor_version)
    else:
        name = client.processor_path(project_id, location, processor_id)

    raw_document = documentai.RawDocument(
        content=pdf_path.read_bytes(),
        mime_type="application/pdf",
    )
    process_options = documentai.ProcessOptions(
        ocr_config=documentai.OcrConfig(
            enable_native_pdf_parsing=True,
            enable_image_quality_scores=True,
            enable_symbol=True,
            premium_features=documentai.OcrConfig.PremiumFeatures(
                compute_style_info=True,
                enable_selection_mark_detection=True,
            ),
        )
    )
    request = documentai.ProcessRequest(
        name=name,
        raw_document=raw_document,
        process_options=process_options,
    )
    response = client.process_document(request=request)
    document = response.document
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
            page_lines.append(
                {
                    "line_no": line_no,
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "text": text,
                }
            )
        pages.append(
            {
                "page_number": page.page_number,
                "lines": sorted(page_lines, key=lambda row: (row["y"], row["x"])),
            }
        )
    return pages


def _build_ocr_request(
    client: Any,
    name: str,
    raw_document: Any,
    *,
    is_pdf: bool = False,
    premium: bool = True,
) -> Any:
    """Build a Document AI ProcessRequest, with or without premium features."""
    from google.cloud import documentai_v1 as documentai

    if premium:
        ocr_config = documentai.OcrConfig(
            enable_native_pdf_parsing=is_pdf,
            enable_image_quality_scores=True,
            enable_symbol=True,
            premium_features=documentai.OcrConfig.PremiumFeatures(
                compute_style_info=True,
                enable_selection_mark_detection=True,
            ),
        )
    else:
        ocr_config = documentai.OcrConfig(
            enable_native_pdf_parsing=is_pdf,
        )

    return documentai.ProcessRequest(
        name=name,
        raw_document=raw_document,
        process_options=documentai.ProcessOptions(ocr_config=ocr_config),
    )


def _process_with_fallback(
    client: Any,
    name: str,
    raw_document: Any,
    *,
    is_pdf: bool = False,
) -> Any:
    """Try premium OCR features first, fall back to basic if processor doesn't support them."""
    from google.api_core import exceptions as gapi_exceptions

    try:
        request = _build_ocr_request(client, name, raw_document, is_pdf=is_pdf, premium=True)
        return client.process_document(request=request)
    except gapi_exceptions.InvalidArgument as exc:
        if "Premium OCR" in str(exc) or "premium" in str(exc).lower():
            print("    (processor does not support premium features, using basic OCR)")
            request = _build_ocr_request(client, name, raw_document, is_pdf=is_pdf, premium=False)
            return client.process_document(request=request)
        raise


def _extract_pages(document: Any) -> list[dict[str, Any]]:
    """Extract page lines from a Document AI response document."""
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
            page_lines.append(
                {
                    "line_no": line_no,
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "text": text,
                }
            )
        pages.append(
            {
                "page_number": page.page_number,
                "lines": sorted(page_lines, key=lambda row: (row["y"], row["x"])),
            }
        )
    return pages


def ocr_image_with_document_ai(
    image_path: Path,
    mime_type: str,
    project_id: str,
    location: str,
    processor_id: str,
    processor_version: str = "",
) -> list[dict[str, Any]]:
    """OCR a single pre-processed image (PNG/JPEG) via Document AI.

    Used when images have been pre-processed for better handwriting
    recognition (deskewed, contrast-enhanced, binarized).
    Tries premium features first, falls back to basic OCR.
    """
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai_v1 as documentai
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency google-cloud-documentai. Install backend requirements first."
        ) from exc

    endpoint = f"{location}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{endpoint}:443")
    )
    if processor_version:
        name = client.processor_version_path(project_id, location, processor_id, processor_version)
    else:
        name = client.processor_path(project_id, location, processor_id)

    raw_document = documentai.RawDocument(
        content=image_path.read_bytes(),
        mime_type=mime_type,
    )
    response = _process_with_fallback(client, name, raw_document, is_pdf=False)
    return _extract_pages(response.document)


def build_vertex_prompt(document_name: str, pages: list[dict[str, Any]]) -> str:
    rendered_pages: list[str] = []
    for page in pages:
        rendered_pages.append(f"PAGE {page['page_number']}")
        for line in page["lines"]:
            rendered_pages.append(
                f"L{line['line_no']:03d} y={line['y']:.4f} x={line['x']:.4f} | {line['text']}"
            )

    return (
        "You are reading handwritten retail sales ledger pages.\n"
        "Extract dated sales entries from the OCR lines.\n"
        "Rules:\n"
        "- A page can contain multiple sales entries.\n"
        "- Preserve uncertain text in raw fields instead of inventing values.\n"
        "- Normalize dates to YYYY-MM-DD only when the date is reasonably clear.\n"
        "- salesperson is the cleaned name; salesperson_raw is the raw OCR text.\n"
        "- items must contain the handwritten product description and amount when present.\n"
        "- qty is nullable and should only be set when explicit.\n"
        "- entry_total is the section total when visible; otherwise null.\n"
        "- notes can capture unresolved ambiguity.\n\n"
        f"DOCUMENT: {document_name}\n\n"
        + "\n".join(rendered_pages)
    )


def extract_sales_entries_with_vertex(
    document_name: str,
    pages: list[dict[str, Any]],
    project_id: str,
    location: str,
    model: str,
    max_retries: int = 2,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    import signal
    import time

    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project_id, location=location)
    prompt = build_vertex_prompt(document_name, pages)

    for attempt in range(max_retries + 1):
        try:
            # Use alarm-based timeout on Unix
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
                        response_schema=ENTRY_SCHEMA,
                        temperature=0.1,
                        max_output_tokens=8192,
                    ),
                )
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            if not response.text:
                return {"pages": []}
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            print(f"    WARNING: Gemini returned invalid JSON ({exc}), skipping extraction")
            return {"pages": [], "notes": f"Vertex JSON error: {exc}"}
        except (TimeoutError, Exception) as exc:
            if attempt < max_retries:
                wait = 5 * (attempt + 1)
                print(f"    RETRY {attempt+1}/{max_retries}: {exc} — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"    ERROR: {exc} after {max_retries} retries, skipping")
                return {"pages": [], "notes": f"Extraction failed: {exc}"}


def enrich_result(
    document_name: str,
    extracted: dict[str, Any],
    aliases: list[MaterialAlias],
    product_hints: list[ProductHint],
) -> dict[str, Any]:
    for page in extracted.get("pages", []):
        for entry_index, entry in enumerate(page.get("entries", []), start=1):
            entry["document_name"] = document_name
            entry["entry_no"] = entry_index
            for item_index, item in enumerate(entry.get("items", []), start=1):
                item["item_no"] = item_index
                desc = item.get("description_raw", "")
                item["material_match"] = match_material(desc, aliases)
                item["product_hint"] = match_product_hint(desc, product_hints)
    return extracted


def write_json(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_mangle(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("# Auto-generated from sales_taka GCP OCR + Vertex extraction\n")
        handle.write("# Schema:\n")
        handle.write(
            "#   sales_note_entry(document_name, page_no, entry_no, date_raw, date_iso, salesperson_raw, salesperson, entry_total, entry_total_raw).\n"
        )
        handle.write(
            "#   sales_note_item(document_name, page_no, entry_no, item_no, description_raw, qty, qty_raw, amount, amount_raw).\n"
        )
        handle.write(
            "#   sales_note_material_match(document_name, page_no, entry_no, item_no, material_key, display_name, score, basis).\n"
        )
        handle.write(
            "#   sales_note_product_hint(document_name, page_no, entry_no, item_no, code, material_text, score, basis).\n\n"
        )
        handle.write(
            'DeclDecl(sales_note_entry, [FieldDecl("document_name", "String"), FieldDecl("page_no", "Int64"), '
            'FieldDecl("entry_no", "Int64"), FieldDecl("date_raw", "String"), FieldDecl("date_iso", "String"), '
            'FieldDecl("salesperson_raw", "String"), FieldDecl("salesperson", "String"), FieldDecl("entry_total", "Float64"), '
            'FieldDecl("entry_total_raw", "String")]).\n'
        )
        handle.write(
            'DeclDecl(sales_note_item, [FieldDecl("document_name", "String"), FieldDecl("page_no", "Int64"), '
            'FieldDecl("entry_no", "Int64"), FieldDecl("item_no", "Int64"), FieldDecl("description_raw", "String"), '
            'FieldDecl("qty", "Float64"), FieldDecl("qty_raw", "String"), FieldDecl("amount", "Float64"), FieldDecl("amount_raw", "String")]).\n'
        )
        handle.write(
            'DeclDecl(sales_note_material_match, [FieldDecl("document_name", "String"), FieldDecl("page_no", "Int64"), '
            'FieldDecl("entry_no", "Int64"), FieldDecl("item_no", "Int64"), FieldDecl("material_key", "String"), '
            'FieldDecl("display_name", "String"), FieldDecl("score", "Float64"), FieldDecl("basis", "String")]).\n'
        )
        handle.write(
            'DeclDecl(sales_note_product_hint, [FieldDecl("document_name", "String"), FieldDecl("page_no", "Int64"), '
            'FieldDecl("entry_no", "Int64"), FieldDecl("item_no", "Int64"), FieldDecl("code", "String"), '
            'FieldDecl("material_text", "String"), FieldDecl("score", "Float64"), FieldDecl("basis", "String")]).\n\n'
        )

        for document in payload.get("documents", []):
            document_name = document.get("document_name", "")
            for page in document.get("pages", []):
                page_no = int(page.get("page_number") or 0)
                for entry in page.get("entries", []):
                    entry_no = int(entry.get("entry_no") or 0)
                    handle.write(
                        f"sales_note_entry({mangle_str(document_name)}, {page_no}, {entry_no}, "
                        f"{mangle_str(entry.get('date_raw'))}, {mangle_str(entry.get('date_iso'))}, "
                        f"{mangle_str(entry.get('salesperson_raw'))}, {mangle_str(entry.get('salesperson'))}, "
                        f"{mangle_num(entry.get('entry_total'))}, {mangle_str(entry.get('entry_total_raw'))}).\n"
                    )
                    for item in entry.get("items", []):
                        item_no = int(item.get("item_no") or 0)
                        handle.write(
                            f"sales_note_item({mangle_str(document_name)}, {page_no}, {entry_no}, {item_no}, "
                            f"{mangle_str(item.get('description_raw'))}, {mangle_num(item.get('qty'))}, "
                            f"{mangle_str(item.get('qty_raw'))}, {mangle_num(item.get('amount'))}, "
                            f"{mangle_str(item.get('amount_raw'))}).\n"
                        )
                        material_match = item.get("material_match")
                        if material_match:
                            handle.write(
                                f"sales_note_material_match({mangle_str(document_name)}, {page_no}, {entry_no}, {item_no}, "
                                f"{mangle_str(material_match.get('material_key'))}, {mangle_str(material_match.get('display_name'))}, "
                                f"{mangle_num(material_match.get('score'))}, {mangle_str(material_match.get('basis'))}).\n"
                            )
                        product_hint = item.get("product_hint")
                        if product_hint:
                            handle.write(
                                f"sales_note_product_hint({mangle_str(document_name)}, {page_no}, {entry_no}, {item_no}, "
                                f"{mangle_str(product_hint.get('code'))}, {mangle_str(product_hint.get('material_text'))}, "
                                f"{mangle_num(product_hint.get('score'))}, {mangle_str(product_hint.get('basis'))}).\n"
                            )
                    handle.write("\n")


def validate_env(project_id: str, processor_id: str) -> None:
    if not project_id:
        raise SystemExit("Set GCP project via --project-id, GOOGLE_CLOUD_PROJECT, or GCP_PROJECT_ID.")
    if not processor_id:
        raise SystemExit(
            "Set Document AI processor via --processor-id or DOCUMENT_AI_PROCESSOR_ID."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-mangle", default=DEFAULT_OUTPUT_MANGLE)
    parser.add_argument("--materials-json", default=DEFAULT_MATERIALS_JSON)
    parser.add_argument("--pos-items", default=DEFAULT_POS_ITEMS)
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", ""),
    )
    parser.add_argument("--vertex-location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))
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
    materials_json = _repo_path(args.materials_json)
    pos_items = _repo_path(args.pos_items)
    output_json = _repo_path(args.output_json)
    output_mangle = _repo_path(args.output_mangle)

    aliases = load_material_aliases(materials_json)
    product_hints = load_product_hints(pos_items)

    documents: list[dict[str, Any]] = []

    # Collect input files: PDFs and pre-processed images (PNG/JPG)
    pdf_files = sorted(input_dir.glob("*.pdf"))
    image_files = sorted(
        p for ext in ("*.png", "*.jpg", "*.jpeg")
        for p in input_dir.glob(ext)
    )

    if image_files and not pdf_files:
        print(f"Found {len(image_files)} pre-processed images (no PDFs)")
    elif image_files and pdf_files:
        print(f"Found {len(pdf_files)} PDFs and {len(image_files)} images — using images (pre-processed preferred)")
        pdf_files = []  # prefer pre-processed images when both exist
    else:
        print(f"Found {len(pdf_files)} PDFs")

    for pdf_path in pdf_files:
        pages = ocr_pdf_with_document_ai(
            pdf_path=pdf_path,
            project_id=args.project_id,
            location=args.documentai_location,
            processor_id=args.processor_id,
            processor_version=args.processor_version,
        )
        extracted = extract_sales_entries_with_vertex(
            document_name=pdf_path.name,
            pages=pages,
            project_id=args.project_id,
            location=args.vertex_location,
            model=args.model,
        )
        enriched = enrich_result(pdf_path.name, extracted, aliases, product_hints)
        documents.append({"document_name": pdf_path.name, **enriched})
        print(
            f"Processed {pdf_path.name}: pages={len(enriched.get('pages', []))}"
        )

    import sys
    total_images = len(image_files)
    for idx, img_path in enumerate(image_files, start=1):
        print(f"  [{idx}/{total_images}] {img_path.name}...", end=" ", flush=True)
        mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
        pages = ocr_image_with_document_ai(
            image_path=img_path,
            mime_type=mime,
            project_id=args.project_id,
            location=args.documentai_location,
            processor_id=args.processor_id,
            processor_version=args.processor_version,
        )
        extracted = extract_sales_entries_with_vertex(
            document_name=img_path.name,
            pages=pages,
            project_id=args.project_id,
            location=args.vertex_location,
            model=args.model,
        )
        enriched = enrich_result(img_path.name, extracted, aliases, product_hints)
        documents.append({"document_name": img_path.name, **enriched})
        n_entries = sum(len(p.get("entries", [])) for p in enriched.get("pages", []))
        print(f"pages={len(enriched.get('pages', []))} entries={n_entries}", flush=True)
        sys.stdout.flush()

    payload = {"documents": documents}
    write_json(output_json, payload)
    write_mangle(output_mangle, payload)
    print(f"JSON   -> {output_json}")
    print(f"Mangle -> {output_mangle}")
    
    try:
        sys.path.append(str(repo_root / "tools" / "scripts"))
        from vault_utils import upload_to_vault
        doc_id = "sales_taka_gcp_vertex"
        print(f"\nUploading to OCR Vault Staging as {doc_id}...")
        upload_to_vault(args.project_id, doc_id, "Sales Taka Batch", payload)
        print("Vault upload successful.")
    except Exception as e:
        print(f"Error executing vault upload: {e}")


if __name__ == "__main__":
    main()
