#!/usr/bin/env python3
"""
Uploads OCR JSON outputs into Firestore as Markdown 'Vault Notes'
This implements the Firebase Obsidian Vault staging layer.
"""

import json
import os
import argparse
from pathlib import Path
from google.cloud import firestore

DEFAULT_INPUT_DIR = "data/ocr_outputs"
COLLECTION_NAME = "ocr_staging_vault"

def convert_to_markdown(doc_name: str, payload: dict) -> str:
    """Converts structured JSON OCR output to Obsidian-style Markdown"""
    lines = []
    lines.append(f"# {doc_name}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("```json")
    # Simplify metadata so it's not overwhelmingly large, but keep it for reference
    lines.append("{JSON Metadata is stored in the Firestore Document directly}")
    lines.append("```")
    lines.append("")
    lines.append("## Staged Data")
    
    if "documents" in payload:
        # Sales Ledger structure
        for doc in payload["documents"]:
            lines.append(f"### Document: {doc.get('document_name')}")
            for page in doc.get("pages", []):
                lines.append(f"**Page {page.get('page_number')}**")
                for entry_idx, entry in enumerate(page.get("entries", []), start=1):
                    lines.append(f"\n#### Entry {entry_idx}")
                    lines.append(f"- **Date**: {entry.get('date_iso') or entry.get('date_raw')}")
                    lines.append(f"- **Salesperson**: {entry.get('salesperson')}")
                    lines.append(f"- **Total**: {entry.get('entry_total')}")
                    lines.append("")
                    lines.append("| Item No | Qty | Description | Amount | Material Code |")
                    lines.append("|---|---|---|---|---|")
                    for item_idx, item in enumerate(entry.get("items", []), start=1):
                        qty = item.get("qty") or ""
                        desc = item.get("description_raw", "").replace('\n', ' ')
                        amt = item.get("amount") or ""
                        mat = item.get("material_match", {})
                        mat_code = mat.get("material_key", "") if mat else ""
                        lines.append(f"| {item_idx} | {qty} | {desc} | {amt} | {mat_code} |")
                lines.append("")
                
    elif "pages" in payload and "total_items" in payload:
        # Stock Check structure
        for page in payload["pages"]:
            lines.append(f"### Page {page.get('page_number')}")
            lines.append(f"**Location**: {page.get('store_location')}")
            lines.append(f"**Date**: {page.get('check_date')}")
            lines.append("")
            lines.append("| Code | Name | Qty | Unit Price | Total Price | Location | Condition |")
            lines.append("|---|---|---|---|---|---|---|")
            for item in page.get("items", []):
                code = item.get("product_code") or ""
                name = item.get("product_name") or "".replace('\n', ' ')
                qty = item.get("quantity") or ""
                unit = item.get("unit_price") or ""
                total = item.get("total_price") or ""
                loc = item.get("location") or ""
                cond = item.get("condition") or ""
                lines.append(f"| {code} | {name} | {qty} | {unit} | {total} | {loc} | {cond} |")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Upload OCR outputs to Firestore Vault")
    parser.add_argument("--project-id", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "victoriaensoapp"))
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    input_path = (repo_root / args.input_dir).resolve()
    
    print(f"Connecting to Firestore for project: {args.project_id}")
    try:
        db = firestore.Client(project=args.project_id)
    except Exception as e:
        print(f"Error connecting to Firestore. Are you authenticated? {e}")
        return

    json_files = list(input_path.glob("*.json"))
    if not json_files:
        print(f"No json files found in {input_path}")
        return
        
    for json_file in json_files:
        if json_file.name.startswith("material_reference"):
            continue # ignore reference schemas
            
        print(f"Processing {json_file.name}...")
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except json.JSONDecodeError:
            print(f"  Skipping {json_file.name} - invalid JSON")
            continue
            
        markdown_str = convert_to_markdown(json_file.stem, payload)
        
        doc_ref = db.collection(COLLECTION_NAME).document(json_file.stem)
        doc_ref.set({
            "document_id": json_file.stem,
            "source_filename": json_file.name,
            "status": "Needs Review",
            "markdown_content": markdown_str,
            "metadata": payload,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        print(f"  -> Uploaded as '{json_file.stem}'")
        
    print("Upload complete!")

if __name__ == "__main__":
    main()
