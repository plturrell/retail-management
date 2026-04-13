#!/usr/bin/env python3
"""
Parse OCBC bank statements using GCP Document AI Bank Statement Parser.

Extracts structured transaction data from digital PDF bank statements:
  - Account holder, account number, statement period
  - Individual transactions (date, description, amount, type)
  - Opening/closing balances

Outputs:
  - JSON extraction payload in data/ocr_outputs/
  - Mangle facts in data/mangle_facts/

Usage:
  python bank_statement_parser.py
  python bank_statement_parser.py --input-dir docs/ocbc/2025
  python bank_statement_parser.py --input-dir docs/ocbc --recursive
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


DEFAULT_INPUT_DIR = "docs/ocbc"
DEFAULT_OUTPUT_JSON = "data/ocr_outputs/bank_statements.json"
DEFAULT_OUTPUT_MANGLE = "data/mangle_facts/bank_statements.mangle"


def parse_bank_statement(
    pdf_path: Path,
    project_id: str,
    location: str,
    processor_id: str,
    processor_version: str = "",
) -> dict[str, Any]:
    """Send a bank statement PDF to Document AI Bank Statement Parser."""
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai_v1 as documentai
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing google-cloud-documentai. Install backend requirements."
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
    request = documentai.ProcessRequest(
        name=name,
        raw_document=raw_document,
    )
    response = client.process_document(request=request)
    return _extract_bank_data(response.document, pdf_path.name)


def _extract_entity_value(entity: Any) -> Any:
    """Extract the most useful value from a Document AI entity."""
    # Prefer normalized_value when available
    nv = getattr(entity, "normalized_value", None)
    if nv:
        if hasattr(nv, "money_value") and nv.money_value and nv.money_value.units:
            return {
                "amount": float(f"{nv.money_value.units}.{nv.money_value.nanos // 10_000_000:02d}"),
                "currency": nv.money_value.currency_code or "SGD",
            }
        if hasattr(nv, "date_value") and nv.date_value and nv.date_value.year:
            dv = nv.date_value
            return f"{dv.year:04d}-{dv.month:02d}-{dv.day:02d}"
        if hasattr(nv, "text") and nv.text:
            return nv.text

    mention = getattr(entity, "mention_text", "") or ""
    return mention.strip()


def _extract_bank_data(document: Any, file_name: str) -> dict[str, Any]:
    """Extract structured bank statement data from Document AI entities."""
    result: dict[str, Any] = {
        "file_name": file_name,
        "page_count": len(document.pages),
        "full_text_length": len(document.text or ""),
    }

    # Top-level fields
    header: dict[str, Any] = {}
    transactions: list[dict[str, Any]] = []
    line_items: list[dict[str, Any]] = []

    for entity in document.entities:
        etype = entity.type_ or ""
        value = _extract_entity_value(entity)

        # Header-level fields
        if etype in (
            "account_holder_name", "account_number", "bank_name",
            "statement_date", "statement_period_start", "statement_period_end",
            "opening_balance", "closing_balance", "total_deposits",
            "total_withdrawals", "currency",
        ):
            header[etype] = value

        # Transaction line items
        elif etype in ("line_item", "transaction"):
            txn: dict[str, Any] = {"raw_text": getattr(entity, "mention_text", "")}
            for prop in entity.properties:
                ptype = prop.type_ or ""
                pval = _extract_entity_value(prop)
                txn[ptype] = pval
            line_items.append(txn)

        # Nested entities at top level
        elif entity.properties:
            nested: dict[str, Any] = {"type": etype}
            for prop in entity.properties:
                ptype = prop.type_ or ""
                pval = _extract_entity_value(prop)
                nested[ptype] = pval
            transactions.append(nested)

    result["header"] = header
    result["transactions"] = line_items if line_items else transactions

    # Also extract raw text per page for verification
    full_text = document.text or ""
    pages_text: list[dict[str, Any]] = []
    for page in document.pages:
        page_lines: list[str] = []
        for line in getattr(page, "lines", []) or getattr(page, "paragraphs", []) or []:
            anchor = line.layout.text_anchor
            fragments: list[str] = []
            for seg in getattr(anchor, "text_segments", []) or []:
                start = int(seg.start_index or 0)
                end = int(seg.end_index or 0)
                fragments.append(full_text[start:end])
            text = " ".join("".join(fragments).split()).strip()
            if text:
                page_lines.append(text)
        pages_text.append({
            "page_number": page.page_number,
            "line_count": len(page_lines),
            "lines": page_lines,
        })
    result["pages"] = pages_text

    return result


def _month_sort_key(file_name: str) -> tuple[int, int]:
    """Sort bank statement files by year then month."""
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    # Pattern: ...-MonYY.pdf or ...-Mon-YY.pdf
    m = re.search(r"(\w{3})-?(\d{2,4})", file_name, re.IGNORECASE)
    if m:
        month_str = m.group(1).lower()[:3]
        year_str = m.group(2)
        month = months.get(month_str, 0)
        year = int(year_str)
        if year < 100:
            year += 2000
        return (year, month)
    return (0, 0)


def mangle_str(value: Any) -> str:
    if value is None:
        return '"null"'
    return '"' + str(value).replace('"', '\\"').replace("\n", " ").strip() + '"'


def mangle_num(value: Any) -> str:
    if value in (None, "", "null"):
        return "0"
    if isinstance(value, dict):
        value = value.get("amount", 0)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    return str(int(number)) if number == int(number) else str(round(number, 4))


def write_json(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_mangle(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("# Auto-generated from OCBC bank statement parsing via GCP Document AI\n")
        handle.write("# Schema:\n")
        handle.write(
            '#   bank_statement_header(file_name, account_holder, account_number, '
            'statement_date, period_start, period_end, opening_balance, closing_balance).\n'
        )
        handle.write(
            '#   bank_transaction(file_name, txn_index, date, description, '
            'amount, txn_type, balance).\n\n'
        )
        handle.write(
            'DeclDecl(bank_statement_header, [FieldDecl("file_name", "String"), '
            'FieldDecl("account_holder", "String"), FieldDecl("account_number", "String"), '
            'FieldDecl("statement_date", "String"), FieldDecl("period_start", "String"), '
            'FieldDecl("period_end", "String"), FieldDecl("opening_balance", "Float64"), '
            'FieldDecl("closing_balance", "Float64")]).\n'
        )
        handle.write(
            'DeclDecl(bank_transaction, [FieldDecl("file_name", "String"), '
            'FieldDecl("txn_index", "Int64"), FieldDecl("date", "String"), '
            'FieldDecl("description", "String"), FieldDecl("amount", "Float64"), '
            'FieldDecl("txn_type", "String"), FieldDecl("balance", "Float64")]).\n\n'
        )

        for stmt in payload.get("statements", []):
            file_name = stmt.get("file_name", "")
            header = stmt.get("header", {})
            handle.write(
                f"bank_statement_header({mangle_str(file_name)}, "
                f"{mangle_str(header.get('account_holder_name'))}, "
                f"{mangle_str(header.get('account_number'))}, "
                f"{mangle_str(header.get('statement_date'))}, "
                f"{mangle_str(header.get('statement_period_start'))}, "
                f"{mangle_str(header.get('statement_period_end'))}, "
                f"{mangle_num(header.get('opening_balance'))}, "
                f"{mangle_num(header.get('closing_balance'))}).\n\n"
            )
            for txn_idx, txn in enumerate(stmt.get("transactions", []), start=1):
                # Bank Statement Parser uses split withdrawal/deposit fields
                w_date = txn.get("transaction_withdrawal_date", "")
                d_date = txn.get("transaction_deposit_date", "")
                date = d_date or w_date or ""

                w_desc = txn.get("transaction_withdrawal_description", "")
                d_desc = txn.get("transaction_deposit_description", "")
                desc = (d_desc or w_desc or "").replace("\n", " ")

                w_amt = txn.get("transaction_withdrawal")
                d_amt = txn.get("transaction_deposit")
                if d_amt:
                    amount = d_amt if isinstance(d_amt, (int, float)) else d_amt.get("amount", 0)
                    txn_type = "deposit"
                elif w_amt:
                    amount = w_amt if isinstance(w_amt, (int, float)) else w_amt.get("amount", 0)
                    txn_type = "withdrawal"
                else:
                    amount = 0
                    txn_type = "unknown"

                handle.write(
                    f"bank_transaction({mangle_str(file_name)}, {txn_idx}, "
                    f"{mangle_str(date)}, {mangle_str(desc)}, "
                    f"{mangle_num(amount)}, {mangle_str(txn_type)}, "
                    f"0).\n"
                )
            handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse OCBC bank statements with Document AI"
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-mangle", default=DEFAULT_OUTPUT_MANGLE)
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse into year subdirectories (2023/, 2024/, 2025/)",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", ""),
    )
    parser.add_argument("--location", default=os.environ.get("BANK_PARSER_LOCATION", "us"))
    parser.add_argument(
        "--processor-id",
        default=os.environ.get("BANK_STATEMENT_PROCESSOR_ID", ""),
    )
    parser.add_argument("--processor-version", default="")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max statements to process (0 = all)",
    )
    args = parser.parse_args()

    if not args.project_id:
        raise SystemExit("Set GCP project via --project-id, GOOGLE_CLOUD_PROJECT, or GCP_PROJECT_ID.")
    if not args.processor_id:
        raise SystemExit("Set Bank Statement Parser processor via --processor-id or BANK_STATEMENT_PROCESSOR_ID.")

    repo_root = Path(__file__).resolve().parents[2]

    def _repo_path(p: str) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()

    input_dir = _repo_path(args.input_dir)
    output_json = _repo_path(args.output_json)
    output_mangle = _repo_path(args.output_mangle)

    # Collect PDF files
    if args.recursive:
        pdf_files = sorted(input_dir.rglob("*.pdf"), key=lambda p: _month_sort_key(p.name))
    else:
        pdf_files = sorted(input_dir.glob("*.pdf"), key=lambda p: _month_sort_key(p.name))

    # Filter to only bank statement files (skip tax forms, etc.)
    pdf_files = [p for p in pdf_files if "BUSINESS GROWTH ACCOUNT" in p.name]

    if args.limit > 0:
        pdf_files = pdf_files[:args.limit]

    if not pdf_files:
        print(f"No bank statement PDFs found in {input_dir}")
        return

    print(f"Processing {len(pdf_files)} bank statements")
    print(f"  Processor: {args.processor_id} ({args.location})")
    print()

    statements: list[dict[str, Any]] = []
    total_txns = 0

    for pdf_path in pdf_files:
        print(f"  {pdf_path.name}...", end=" ", flush=True)
        try:
            result = parse_bank_statement(
                pdf_path=pdf_path,
                project_id=args.project_id,
                location=args.location,
                processor_id=args.processor_id,
                processor_version=args.processor_version,
            )
            txn_count = len(result.get("transactions", []))
            total_txns += txn_count
            header = result.get("header", {})
            bal = header.get("closing_balance", "?")
            print(f"{result['page_count']} pages, {txn_count} transactions, closing={bal}")
            statements.append(result)
        except Exception as exc:
            print(f"ERROR: {exc}")
            statements.append({"file_name": pdf_path.name, "error": str(exc)})

    payload = {"statements": statements}
    write_json(output_json, payload)
    write_mangle(output_mangle, payload)
    print(f"\nDone: {len(statements)} statements, {total_txns} total transactions")
    print(f"JSON   -> {output_json}")
    print(f"Mangle -> {output_mangle}")


if __name__ == "__main__":
    main()
