"""GCP-backed document OCR and sales-ledger extraction."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.ai_gateway import AIRequest, ASYNC_TIMEOUT_SECONDS, invoke
from app.services.gcs import download_bytes


REPO_ROOT = Path(__file__).resolve().parents[3]
MATERIALS_JSON_PATH = (
    REPO_ROOT / "data" / "ocr_outputs" / "material_reference_adobe_scan_12_apr_2026.json"
)
POS_ITEMS_MANGLE_PATH = REPO_ROOT / "data" / "mangle_facts" / "pos_orders.mangle"

GENERIC_MATERIAL_WORDS = {
    "stone",
    "crystal",
    "natural",
    "mineral",
    "marble",
    "copper",
    "glass",
}

SALES_LEDGER_SCHEMA: dict[str, Any] = {
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


def _guess_mime_type(file_name: str, content_type: str | None = None) -> str:
    if content_type:
        return content_type
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    raise ValueError(f"Unsupported OCR input type: {suffix or file_name}")


def _layout_text(full_text: str, anchor: Any) -> str:
    fragments: list[str] = []
    for segment in getattr(anchor, "text_segments", []) or []:
        start = int(segment.start_index or 0)
        end = int(segment.end_index or 0)
        fragments.append(full_text[start:end])
    return normalize_space("".join(fragments))


def _normalized_xy(layout: Any) -> tuple[float, float]:
    vertices = getattr(getattr(layout, "bounding_poly", None), "normalized_vertices", None) or []
    if not vertices:
        return 0.0, 0.0
    xs = [float(v.x) for v in vertices if v.x is not None]
    ys = [float(v.y) for v in vertices if v.y is not None]
    return (min(xs) if xs else 0.0, min(ys) if ys else 0.0)


def _sync_process_document_bytes(data: bytes, mime_type: str) -> list[dict[str, Any]]:
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai_v1 as documentai
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-documentai is not installed; install backend requirements."
        ) from exc

    if not settings.DOCUMENT_AI_PROCESSOR_ID:
        raise RuntimeError("DOCUMENT_AI_PROCESSOR_ID is not configured")

    location = settings.DOCUMENT_AI_LOCATION
    endpoint = f"{location}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{endpoint}:443")
    )
    if settings.DOCUMENT_AI_PROCESSOR_VERSION:
        name = client.processor_version_path(
            settings.GCP_PROJECT_ID,
            location,
            settings.DOCUMENT_AI_PROCESSOR_ID,
            settings.DOCUMENT_AI_PROCESSOR_VERSION,
        )
    else:
        name = client.processor_path(
            settings.GCP_PROJECT_ID,
            location,
            settings.DOCUMENT_AI_PROCESSOR_ID,
        )

    raw_document = documentai.RawDocument(content=data, mime_type=mime_type)
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
    full_text = document.text or ""
    pages: list[dict[str, Any]] = []

    for page in document.pages:
        rows = getattr(page, "lines", None) or getattr(page, "paragraphs", None) or []
        lines: list[dict[str, Any]] = []
        for line_no, row in enumerate(rows, start=1):
            text = _layout_text(full_text, row.layout.text_anchor)
            if not text:
                continue
            x, y = _normalized_xy(row.layout)
            lines.append(
                {
                    "line_no": line_no,
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "text": text,
                }
            )
        page_text = normalize_space(" ".join(line["text"] for line in lines))
        pages.append(
            {
                "page_number": page.page_number,
                "text": page_text,
                "lines": sorted(lines, key=lambda item: (item["y"], item["x"])),
            }
        )
    return pages


def _build_sales_ledger_prompt(document_name: str, pages: list[dict[str, Any]]) -> str:
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
        "- Normalize dates to YYYY-MM-DD only when reasonably clear.\n"
        "- salesperson is the cleaned name; salesperson_raw is the raw OCR text.\n"
        "- items must contain the handwritten product description and amount when present.\n"
        "- qty is nullable and should only be set when explicit.\n"
        "- entry_total is the section total when visible; otherwise null.\n"
        "- notes can capture unresolved ambiguity.\n\n"
        f"DOCUMENT: {document_name}\n\n"
        + "\n".join(rendered_pages)
    )


@lru_cache(maxsize=1)
def _load_material_aliases() -> tuple[MaterialAlias, ...]:
    if not MATERIALS_JSON_PATH.exists():
        return ()

    payload = json.loads(MATERIALS_JSON_PATH.read_text(encoding="utf-8"))
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
    return tuple(aliases)


@lru_cache(maxsize=1)
def _load_product_hints() -> tuple[ProductHint, ...]:
    if not POS_ITEMS_MANGLE_PATH.exists():
        return ()

    hints: list[ProductHint] = []
    for line in POS_ITEMS_MANGLE_PATH.read_text(encoding="utf-8").splitlines():
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
    return tuple(hints)


def _match_material(description: str) -> dict[str, Any] | None:
    desc_norm = normalize_lookup(description)
    if not desc_norm:
        return None

    best: dict[str, Any] | None = None
    for alias in _load_material_aliases():
        if alias.alias_norm in desc_norm:
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


def _match_product_hint(description: str) -> dict[str, Any] | None:
    desc_norm = normalize_lookup(description)
    if not desc_norm:
        return None

    best: dict[str, Any] | None = None
    for hint in _load_product_hints():
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


def _enrich_sales_ledger(extracted: dict[str, Any], document_name: str) -> dict[str, Any]:
    for page in extracted.get("pages", []):
        for entry_index, entry in enumerate(page.get("entries", []), start=1):
            entry["document_name"] = document_name
            entry["entry_no"] = entry_index
            for item_index, item in enumerate(entry.get("items", []), start=1):
                item["item_no"] = item_index
                desc = item.get("description_raw", "")
                item["material_match"] = _match_material(desc)
                item["product_hint"] = _match_product_hint(desc)
    return extracted


async def _extract_sales_ledger(document_name: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    resp = await invoke(
        AIRequest(
            prompt=_build_sales_ledger_prompt(document_name, pages),
            purpose="sales_ledger_extraction",
            timeout_seconds=ASYNC_TIMEOUT_SECONDS,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_schema=SALES_LEDGER_SCHEMA,
        ),
        fallback_text='{"pages": []}',
    )
    try:
        extracted = json.loads(resp.text or '{"pages": []}')
    except json.JSONDecodeError:
        extracted = {"pages": [], "notes": "Vertex returned invalid JSON"}

    enriched = _enrich_sales_ledger(extracted, document_name)
    return {
        "result": enriched,
        "ai_request_id": resp.request_id,
        "ai_model": resp.model,
        "ai_fallback": resp.is_fallback,
        "ai_error": resp.error,
    }


async def process_document_from_gcs(
    *,
    job_type: str,
    gcs_uri: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not gcs_uri:
        raise ValueError("gcs_input_uri is required for OCR jobs")

    file_name = payload.get("file_name") or Path(gcs_uri).name
    mime_type = _guess_mime_type(file_name, payload.get("content_type"))
    data = await download_bytes(gcs_uri)
    pages = await asyncio.to_thread(_sync_process_document_bytes, data, mime_type)

    result: dict[str, Any] = {
        "status": "completed",
        "job_type": job_type,
        "gcs_input_uri": gcs_uri,
        "document_name": file_name,
        "mime_type": mime_type,
        "page_count": len(pages),
        "pages": pages,
    }

    document_kind = payload.get("document_kind")
    if job_type == "ocr_sales_ledger" or document_kind == "sales_ledger":
        result["structured"] = await _extract_sales_ledger(file_name, pages)

    return result
