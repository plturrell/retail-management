#!/usr/bin/env python3
"""
Supplier Document OCR Pipeline — Chinese supplier invoices, inventory sheets, order docs.

Two processing modes:

  1. DeepSeek Vision (no GCP needed) — Recommended:
     Converts PDF/image pages to base64 and sends directly to DeepSeek-V3's
     vision API. Performs OCR + structured extraction in a single AI pass.

     python supplier_ocr_pipeline.py \
       --input-dir docs/suppliers/china_suppliers \
       --mode deepseek-vision

  2. GCP Document AI + Gemini/DeepSeek (original):
     Uses Google Document AI for OCR then Gemini or DeepSeek for extraction.

     python supplier_ocr_pipeline.py \
       --input-dir docs/suppliers/china_suppliers \
       --project-id <GCP_PROJECT_ID> \
       --processor-id <DOC_AI_PROCESSOR_ID>

Extracts: supplier_item_code, product_name_cn, product_name_en, material,
          product_type, quantity, unit_price_cny, total_price_cny, etc.

Integrates with ocr_lineage.py to track processed documents and prevent duplicates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Defaults ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = "data/ocr_outputs/supplier_docs"
PIPELINE_NAME = "supplier_ocr"

# ── Gemini structured schema for supplier documents ──────────────────────────

SUPPLIER_DOC_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "document_type": {
            "type": "STRING",
            "description": "Type of document: invoice, inventory_list, order_confirmation, packing_list, catalog_page, price_list, unknown",
        },
        "supplier_name": {
            "type": "STRING",
            "description": "Supplier/company name if visible on document",
            "nullable": True,
        },
        "document_number": {
            "type": "STRING",
            "description": "Invoice/order/reference number if visible",
            "nullable": True,
        },
        "document_date": {
            "type": "STRING",
            "description": "Date on document in YYYY-MM-DD format if legible",
            "nullable": True,
        },
        "currency": {
            "type": "STRING",
            "description": "Currency code (CNY, SGD, USD, etc). Default CNY for Chinese suppliers.",
        },
        "document_total": {
            "type": "NUMBER",
            "description": "Total amount on the document if shown",
            "nullable": True,
        },
        "total_quantity": {
            "type": "INTEGER",
            "description": "Total quantity if shown on document",
            "nullable": True,
        },
        "notes": {
            "type": "STRING",
            "description": "Any header/footer notes, payment terms, shipping info visible",
            "nullable": True,
        },
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "line_number": {
                        "type": "INTEGER",
                        "description": "Row/sequence number from the document",
                        "nullable": True,
                    },
                    "supplier_item_code": {
                        "type": "STRING",
                        "description": "Supplier's product/item code (e.g. BFE003702, JE5831-11). Null if absent.",
                        "nullable": True,
                    },
                    "product_name_cn": {
                        "type": "STRING",
                        "description": "Product name in Chinese as written on document",
                        "nullable": True,
                    },
                    "product_name_en": {
                        "type": "STRING",
                        "description": "English translation of product name. Translate Chinese to English if only Chinese present.",
                    },
                    "material": {
                        "type": "STRING",
                        "description": "Primary gemstone/material (e.g. Citrine, Amethyst, Sapphire, Topaz). Translate from Chinese if needed.",
                        "nullable": True,
                    },
                    "product_type": {
                        "type": "STRING",
                        "description": "Product type in English. Must be one of: Bracelet, Necklace, Ring, Pendant, Earring, Charm, Loose Gemstone, Tumbled Stone, Raw Specimen, Crystal Cluster, Gemstone Bead, Cabochon, Bead Strand, Jewellery Component, Figurine, Sculpture, Bookend, Bowl, Vase, Tray, Box, Decorative Object, Healing Crystal, Crystal Point, Gift Set, Accessory",
                    },
                    "colour": {
                        "type": "STRING",
                        "description": "Colour description if noted",
                        "nullable": True,
                    },
                    "size": {
                        "type": "STRING",
                        "description": "Size/dimensions if noted",
                        "nullable": True,
                    },
                    "quantity": {
                        "type": "INTEGER",
                        "description": "Quantity ordered/listed. Parse '5件' as 5.",
                        "nullable": True,
                    },
                    "unit_price": {
                        "type": "NUMBER",
                        "description": "Price per unit in document currency",
                        "nullable": True,
                    },
                    "total_price": {
                        "type": "NUMBER",
                        "description": "Line total (qty × unit_price)",
                        "nullable": True,
                    },
                    "notes": {
                        "type": "STRING",
                        "description": "Any additional notes for this line item",
                        "nullable": True,
                    },
                },
                "required": ["product_name_en", "product_type"],
            },
        },
    },
    "required": ["document_type", "currency", "items"],
}


# ── DeepSeek Local-Extract Mode (no GCP needed) ─────────────────────────────

def _extract_text_from_file(file_path: Path) -> str:
    """Extract raw text from a PDF or image locally.
    - PDF: uses PyMuPDF (fitz) which handles embedded Chinese text well.
    - Image: uses pytesseract with chi_sim+eng language pack if available,
      otherwise returns an empty string with a warning.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(str(file_path))
        pages_text: list[str] = []
        for i, page in enumerate(doc):
            text = page.get_text("text")  # native PDF text layer
            pages_text.append(f"--- PAGE {i+1} ---\n{text}")
        return "\n\n".join(pages_text)
    else:
        # Image file — try pytesseract
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(file_path)
            # chi_sim+eng handles Chinese simplified + English
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            return text
        except ImportError:
            print("    WARNING: pytesseract not installed. Install with: pip install pytesseract")
            print("    WARNING: Also install Tesseract binary: brew install tesseract tesseract-lang")
            return ""
        except Exception as exc:
            print(f"    WARNING: tesseract failed ({exc}). Returning empty text.")
            return ""


def extract_with_deepseek_local(
    document_name: str,
    file_path: Path,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Extract text locally then send to DeepSeek two-step pipeline.

    Step 1 — PyMuPDF/Tesseract: Extract raw text from PDF/image locally.
    Step 2 — deepseek-reasoner: Clean up Chinese handwriting, resolve ambiguities.
    Step 3 — deepseek-chat:     Format into strict JSON schema.

    No GCP credentials needed.
    """
    import os
    from openai import OpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPSEEK_API_KEY not set in environment.")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # Step 1: Local text extraction
    print(f"    Local text extraction...", end=" ", flush=True)
    raw_text = _extract_text_from_file(file_path)
    if not raw_text.strip():
        print("no text found")
        return {"document_type": "unknown", "currency": "CNY", "items": [], "notes": "No text extracted locally"}
    n_chars = len(raw_text)
    print(f"{n_chars} chars extracted")

    base_context = (
        f"DOCUMENT: {document_name}\n"
        "This is a Chinese gemstone/jewellery supplier invoice or inventory sheet.\n"
        "Header columns: 货号=item code, 货名=item name, 数量=qty, 单价=unit price, 金额=amount\n"
        "Footer: 合计=total, 应收=amount due\n"
        "Common materials: 黄晶=Citrine, 蓝宝=Sapphire, 紫晶=Amethyst, 托帕石=Topaz,\n"
        "  翡翠=Jade, 碧玺=Tourmaline, 海蓝宝=Aquamarine, 红宝=Ruby, 石榴石=Garnet\n\n"
        f"RAW TEXT:\n{raw_text}"
    )

    for attempt in range(max_retries + 1):
        try:
            # Step 2: Reasoner — clean and resolve ambiguities
            print(f"    DeepSeek Reasoner cleaning...", end=" ", flush=True)
            reasoner_prompt = (
                base_context
                + "\n\nAnalyze the raw text above. Correct OCR errors, resolve obscure Chinese gemstone "
                "names, fix garbled characters, and organize all product lines into a clean markdown table. "
                "Do NOT generate JSON yet. Focus on accuracy of Chinese translation."
            )
            reason_resp = client.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": reasoner_prompt}],
                temperature=0.1,
                max_tokens=8192,
            )
            reasoned_text = reason_resp.choices[0].message.content or ""
            # Strip any <think> block from reasoner output
            if "</think>" in reasoned_text:
                reasoned_text = reasoned_text.split("</think>", 1)[-1].strip()
            print(f"done ({len(reasoned_text)} chars)")

            # Step 3: Chat — strict JSON formatting
            print(f"    DeepSeek Chat formatting...", end=" ", flush=True)
            extractor_prompt = (
                f"Here is cleaned, reasoned data about a supplier document:\n\n{reasoned_text}\n\n"
                f"Return ONLY valid JSON matching this schema exactly:\n{json.dumps(SUPPLIER_DOC_SCHEMA, indent=2)}"
            )
            format_resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": extractor_prompt}],
                temperature=0.1,
                max_tokens=8192,
                response_format={"type": "json_object"},
            )
            response_text = format_resp.choices[0].message.content or ""
            if not response_text:
                return {"document_type": "unknown", "currency": "CNY", "items": []}
            return json.loads(response_text)

        except json.JSONDecodeError as exc:
            print(f"    WARNING: invalid JSON ({exc})")
            return {"document_type": "unknown", "currency": "CNY", "items": [], "notes": str(exc)}
        except Exception as exc:
            if attempt < max_retries:
                wait = 5 * (attempt + 1)
                print(f"\n    RETRY {attempt+1}/{max_retries}: {exc} — waiting {wait}s")
                time.sleep(wait)
            else:
                raise

    return {"document_type": "unknown", "currency": "CNY", "items": []}


# ── Document AI OCR (reuses pattern from stockcheck pipeline) ────────────────

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


def ocr_file(
    file_path: Path,
    project_id: str,
    location: str,
    processor_id: str,
    processor_version: str = "",
) -> list[dict[str, Any]]:
    """OCR a PDF or image file and return list of page dicts with lines."""
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai_v1 as documentai

    suffix = file_path.suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    mime_type = mime_map.get(suffix)
    if not mime_type:
        print(f"    WARNING: unsupported file type {suffix}, skipping")
        return []

    endpoint = f"{location}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{endpoint}:443")
    )
    if processor_version:
        name = client.processor_version_path(project_id, location, processor_id, processor_version)
    else:
        name = client.processor_path(project_id, location, processor_id)

    raw_document = documentai.RawDocument(content=file_path.read_bytes(), mime_type=mime_type)
    response = _process_with_fallback(client, name, raw_document)
    return _extract_pages(response.document)


# ── Vertex AI Gemini extraction ──────────────────────────────────────────────

def build_supplier_prompt(document_name: str, pages: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for page in pages:
        rendered.append(f"PAGE {page['page_number']}")
        for line in page["lines"]:
            rendered.append(f"L{line['line_no']:03d} y={line['y']:.4f} x={line['x']:.4f} | {line['text']}")

    return (
        "You are reading a Chinese gemstone/jewellery supplier document.\n"
        "This could be an invoice, inventory list, order confirmation, or packing list.\n"
        "The text contains both Chinese (中文) and English.\n\n"
        "Extract every product line item from the OCR text.\n\n"
        "Rules:\n"
        "- supplier_item_code: the supplier's product code (alphanumeric codes like BFE003702, JE5831-11, 126802LB). Null if absent.\n"
        "- product_name_cn: the Chinese product name exactly as written (e.g. 黄晶耳钉, 蓝宝吊坠).\n"
        "- product_name_en: translate the Chinese name to English (e.g. 黄晶耳钉 → Citrine Earring Studs).\n"
        "- material: identify the primary gemstone/material. Common translations:\n"
        "  黄晶=Citrine, 蓝宝=Sapphire, 紫晶=Amethyst, 托帕石=Topaz, 紫锂辉=Kunzite,\n"
        "  翡翠=Jade, 碧玺=Tourmaline, 玫瑰石英=Rose Quartz, 月光石=Moonstone,\n"
        "  海蓝宝=Aquamarine, 橄榄石=Peridot, 石榴石=Garnet, 红宝=Ruby\n"
        "- product_type: classify as one of the allowed types listed in the schema.\n"
        "  Common translations: 耳钉/耳环=Earring, 戒指=Ring, 手链=Bracelet, 项链=Necklace,\n"
        "  吊坠=Pendant, 万能链=Necklace (universal chain)\n"
        "- quantity: parse Chinese quantity notation (e.g. '5件' = 5, '2件' = 2).\n"
        "- unit_price / total_price: numeric values in document currency.\n"
        "- Also extract document-level info: document_type, supplier_name, document_number, date, totals.\n"
        "- Look at the header row '货号' (item code), '货名' (item name), '数量' (qty), '单价' (unit price), '金额' (amount).\n"
        "- Check footer for 合计 (total), 应收 (amount due).\n\n"
        "Preserve uncertain text — do NOT invent values.\n\n"
        f"DOCUMENT: {document_name}\n\n"
        + "\n".join(rendered)
    )


def extract_with_gemini(
    document_name: str,
    pages: list[dict[str, Any]],
    project_id: str,
    location: str,
    model: str,
    max_retries: int = 2,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    import signal

    prompt = build_supplier_prompt(document_name, pages)

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
                    client = OpenAI(
                        api_key=os.environ.get("DEEPSEEK_API_KEY"),
                        base_url="https://api.deepseek.com",
                    )
                    
                    # Step 1: Reasoning
                    print(f" (Step 1: Reasoning with deepseek-reasoner)...", end=" ", flush=True)
                    reasoner_prompt = prompt + "\n\nAnalyze the raw OCR text above. Correct typos, resolve obscure Chinese handwriting for gemstones, and organize the data cleanly into markdown tables. Focus heavily on translating and resolving ambiguities. Do not generate JSON yet."
                    reason_response = client.chat.completions.create(
                        model="deepseek-reasoner",
                        messages=[{"role": "user", "content": reasoner_prompt}],
                        temperature=0.1,
                        max_tokens=8192,
                    )
                    reasoned_text = reason_response.choices[0].message.content or ""
                    
                    # Step 2: Extraction
                    print(f" (Step 2: Formatting with deepseek-chat)...", end=" ", flush=True)
                    extractor_prompt = f"Here is cleanly reasoned text about a supplier document:\n\n{reasoned_text}\n\nYou MUST return ONLY valid JSON adhering exactly to this schema:\n{json.dumps(SUPPLIER_DOC_SCHEMA, indent=2)}"
                    
                    response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": extractor_prompt}],
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
                            response_schema=SUPPLIER_DOC_SCHEMA,
                            temperature=0.1,
                            max_output_tokens=8192,
                        ),
                    )
                    response_text = response.text or ""
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            if not response_text:
                return {"document_type": "unknown", "currency": "CNY", "items": []}
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            print(f"    WARNING: invalid JSON ({exc}), skipping extraction")
            return {"document_type": "unknown", "currency": "CNY", "items": [], "notes": f"JSON error: {exc}"}
        except (TimeoutError, Exception) as exc:
            if attempt < max_retries:
                wait = 5 * (attempt + 1)
                print(f"    RETRY {attempt+1}/{max_retries}: {exc} — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"    ERROR: {exc} after {max_retries} retries, skipping")
                return {"document_type": "unknown", "currency": "CNY", "items": [], "notes": f"Failed: {exc}"}

    return {"document_type": "unknown", "currency": "CNY", "items": []}


# ── Output writers ────────────────────────────────────────────────────────────

def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Supplier Document OCR Pipeline")
    parser.add_argument("--input-dir", required=True, help="Directory containing supplier PDFs/images")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--supplier-name", default="", help="Supplier name for lineage tracking")
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", ""),
    )
    parser.add_argument("--vertex-location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    parser.add_argument("--documentai-location", default=os.environ.get("DOCUMENT_AI_LOCATION", "us"))
    parser.add_argument("--processor-id", default=os.environ.get("DOCUMENT_AI_PROCESSOR_ID", ""))
    parser.add_argument("--processor-version", default=os.environ.get("DOCUMENT_AI_PROCESSOR_VERSION", ""))
    parser.add_argument("--model", default=os.environ.get("VERTEX_GEMINI_MODEL", "gemini-2.5-flash"))
    parser.add_argument(
        "--mode",
        default="gcp",
        choices=["gcp", "deepseek-vision"],
        help="'gcp' uses Document AI + Gemini/DeepSeek. 'deepseek-vision' sends images directly to DeepSeek-V3 vision (no GCP needed).",
    )
    parser.add_argument("--force", action="store_true", help="Re-process even if already in lineage")
    args = parser.parse_args()

    # Validate GCP args only when NOT using DeepSeek Vision mode
    if args.mode != "deepseek-vision":
        if not args.project_id:
            print("ERROR: GCP project ID required (--project-id or GOOGLE_CLOUD_PROJECT)", file=sys.stderr)
            print("TIP: Use --mode deepseek-vision to skip GCP entirely.", file=sys.stderr)
            sys.exit(1)
        if not args.processor_id:
            print("ERROR: Document AI processor ID required (--processor-id or DOCUMENT_AI_PROCESSOR_ID)", file=sys.stderr)
            print("TIP: Use --mode deepseek-vision to skip GCP entirely.", file=sys.stderr)
            sys.exit(1)

    def _repo_path(p: str | Path) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()

    input_dir = _repo_path(args.input_dir)
    output_dir = _repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load lineage tracker
    sys.path.insert(0, str(Path(__file__).parent))
    from ocr_lineage import LineageTracker

    tracker = LineageTracker()

    # Collect documents (PDFs + images) — case-insensitive
    extensions = ("*.pdf", "*.jpg", "*.jpeg", "*.png", "*.tiff",
                  "*.PDF", "*.JPG", "*.JPEG", "*.PNG", "*.TIFF")
    doc_files = sorted(set(p for ext in extensions for p in input_dir.glob(ext)))
    if not doc_files:
        print(f"No documents found in {input_dir}")
        sys.exit(1)

    print(f"Found {len(doc_files)} documents in {input_dir.name}/")
    print(f"Supplier: {args.supplier_name or '(auto-detect)'}")
    print(f"Output:   {output_dir}")
    print()

    all_results: list[dict[str, Any]] = []
    total_items = 0
    skipped = 0

    for idx, doc_path in enumerate(doc_files, start=1):
        print(f"  [{idx}/{len(doc_files)}] {doc_path.name}")

        # Check lineage
        if not args.force and tracker.already_processed(doc_path, PIPELINE_NAME):
            record = tracker.find_by_path(doc_path, PIPELINE_NAME)
            items = record.get("items_extracted", 0) if record else "?"
            print(f"    SKIP — already processed (items={items})")
            skipped += 1
            continue

        # Register in lineage
        lineage_record = tracker.start(
            doc_path,
            pipeline=PIPELINE_NAME,
            supplier=args.supplier_name,
            document_type="supplier_document",
        )

        try:
            if args.mode == "deepseek-vision":
                # ── DeepSeek Local Mode: PyMuPDF text extraction + DeepSeek Reasoner/Chat ──
                extracted = extract_with_deepseek_local(
                    document_name=doc_path.name,
                    file_path=doc_path,
                )
                n_pages = 1
                total_lines = len(extracted.get("items", []))
            else:
                # ── GCP Document AI Mode ──────────────────────────────────────
                # Step 1: Document AI OCR
                print(f"    OCR...", end=" ", flush=True)
                pages = ocr_file(
                    file_path=doc_path,
                    project_id=args.project_id,
                    location=args.documentai_location,
                    processor_id=args.processor_id,
                    processor_version=args.processor_version,
                )
                n_pages = len(pages)
                total_lines = sum(len(p.get("lines", [])) for p in pages)
                print(f"{n_pages} pages, {total_lines} lines")

                if total_lines == 0:
                    print(f"    WARNING: no text extracted, skipping extraction")
                    tracker.fail(lineage_record["id"], "No text extracted from OCR")
                    continue

                # Step 2: Gemini / DeepSeek structured extraction
                print(f"    AI extraction...", end=" ", flush=True)
                extracted = extract_with_gemini(
                    document_name=doc_path.name,
                    pages=pages,
                    project_id=args.project_id,
                    location=args.vertex_location,
                    model=args.model,
                )

            n_items = len(extracted.get("items", []))
            doc_type = extracted.get("document_type", "unknown")
            currency = extracted.get("currency", "CNY")
            doc_total = extracted.get("document_total")
            supplier = extracted.get("supplier_name", args.supplier_name)
            total_items += n_items

            print(f"{n_items} items extracted (type={doc_type}, currency={currency})")
            if doc_total:
                print(f"    Document total: {currency} {doc_total:,.0f}")

            # Enrich result with metadata
            result = {
                "source_file": doc_path.name,
                "source_path": str(doc_path.relative_to(REPO_ROOT)),
                "lineage_id": lineage_record["id"],
                "supplier_name": supplier,
                "ocr_pages": n_pages,
                "ocr_lines": total_lines,
                "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                **extracted,
            }
            all_results.append(result)

            # Write individual file output
            safe_name = doc_path.stem.replace(" ", "_").replace("(", "").replace(")", "")
            out_file = output_dir / f"{safe_name}.json"
            write_json(out_file, result)
            print(f"    Output: {out_file.name}")

            # Update lineage
            tracker.finish(
                lineage_record["id"],
                pages_processed=n_pages,
                items_extracted=n_items,
                output_paths=[str(out_file.relative_to(REPO_ROOT))],
                notes=f"type={doc_type}, total={doc_total}, supplier={supplier}",
            )

        except Exception as exc:
            print(f"    ERROR: {exc}")
            tracker.fail(lineage_record["id"], str(exc))
            continue

        # Rate limit between documents
        if idx < len(doc_files):
            time.sleep(2)

    # Write combined output
    combined_path = output_dir / "_combined_supplier_extract.json"
    combined = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "supplier_name": args.supplier_name,
        "source_directory": str(input_dir.relative_to(REPO_ROOT)),
        "total_documents": len(all_results),
        "total_items": total_items,
        "documents": all_results,
    }
    write_json(combined_path, combined)

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUPPLIER OCR PIPELINE — COMPLETE")
    print(f"{'='*60}")
    print(f"  Documents processed: {len(all_results)}")
    print(f"  Documents skipped:   {skipped}")
    print(f"  Total items:         {total_items}")
    print(f"  Combined output:     {combined_path}")
    print()

    # Print item breakdown
    if all_results:
        from collections import Counter
        types = Counter(
            item.get("product_type") or "?"
            for doc in all_results
            for item in doc.get("items", [])
        )
        materials = Counter(
            item.get("material") or "?"
            for doc in all_results
            for item in doc.get("items", [])
        )
        print("  Product types extracted:")
        for t, n in types.most_common():
            print(f"    {t:25s} {n:4d}")
        print("  Materials extracted:")
        for m, n in materials.most_common(10):
            print(f"    {m:25s} {n:4d}")

    tracker.print_summary()


if __name__ == "__main__":
    main()
