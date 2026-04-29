import json
from google.cloud import firestore

COLLECTION_NAME = "ocr_staging_vault"

def convert_to_markdown(doc_name: str, payload: dict) -> str:
    """Converts structured JSON OCR output to Obsidian-style Markdown"""
    lines = []
    lines.append(f"# {doc_name}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("```json")
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

def upload_to_vault(project_id: str, doc_id: str, source_filename: str, payload: dict) -> None:
    """Upload structured JSON payload to Firestore as Markdown"""
    try:
        db = firestore.Client(project=project_id)
        doc_ref = db.collection(COLLECTION_NAME).document(doc_id)
        markdown_str = convert_to_markdown(doc_id, payload)
        doc_ref.set({
            "document_id": doc_id,
            "source_filename": source_filename,
            "status": "Needs Review",
            "markdown_content": markdown_str,
            "metadata": payload,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"Failed to upload {doc_id} to vault: {e}")
