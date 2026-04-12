#!/bin/bash
# ============================================================
# run_pipeline.sh
# Retail Data Mangle Pipeline
# ============================================================
# Usage:
#   ./run_pipeline.sh                          # uses GEMINI_API_KEY from env
#   ./run_pipeline.sh YOUR_API_KEY_HERE        # pass key as argument
# ============================================================

set -e  # exit immediately on any error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── API Key ─────────────────────────────────────────────────
if [ -n "$1" ]; then
    export GEMINI_API_KEY="$1"
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo ""
    echo "  ERROR: GEMINI_API_KEY is not set."
    echo ""
    echo "  Set it in your shell:"
    echo "    export GEMINI_API_KEY='your_key_here'"
    echo "  Or pass it as an argument:"
    echo "    ./run_pipeline.sh your_key_here"
    echo ""
    exit 1
fi

# ── Dependencies ─────────────────────────────────────────────
echo "▶  Checking Python dependencies..."
python3 -c "from google import genai" 2>/dev/null || {
    echo "   Installing google-genai..."
    pip3 install -q google-genai
}
python3 -c "import pandas, openpyxl" 2>/dev/null || {
    echo "   Installing pandas + openpyxl..."
    pip3 install -q pandas openpyxl
}
python3 -c "import numpy" 2>/dev/null || {
    echo "   Installing numpy..."
    pip3 install -q numpy
}
python3 -c "from PIL import Image" 2>/dev/null || {
    echo "   Installing Pillow..."
    pip3 install -q Pillow
}
echo "   [OK] Dependencies ready."
echo ""

# ── Banner ───────────────────────────────────────────────────
echo ""
echo "  ===========================================  "
echo "  |   Retail Data Mangle Pipeline           |  "
echo "  |=========================================|  "
echo "  |  Step 0 -> Seed product images (once)   |  "
echo "  |  Step 1 -> OCR  (PNG -> JSON)           |  "
echo "  |  Step 2 -> ETL  (JSON -> Mangle, SGD)   |  "
echo "  |  Step 3 -> Excel ETL (xlsx -> Mangle)   |  "
echo "  |  Step 4 -> Image Recognition (if imgs)  |  "
echo "  ===========================================  "
echo ""

# -- Step 0: Seed product images from order forms (runs once when folder is empty)
SEED_COUNT=$(find "$SCRIPT_DIR/product_images" -type f \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) 2>/dev/null | wc -l | tr -d ' ')
if [ "$SEED_COUNT" -eq 0 ]; then
    echo ">> Step 0 -- Seeding product_images/ from order form thumbnails..."
    echo "   (This only runs once. Add your own photos to product_images/ to override)"
    echo ""
    python3 "$SCRIPT_DIR/seed_product_images.py"
    echo ""
else
    echo ">> Step 0 -- Skipped (product_images/ already has $SEED_COUNT file(s))"
fi
echo ""

# -- Step 1: OCR pipeline─
echo "▶  Step 1 — Running OCR pipeline..."
echo "   Model  : gemini-2.5-flash"
echo "   Input  : $SCRIPT_DIR/images/"
echo "   Output : $SCRIPT_DIR/ocr_outputs/"
echo ""
python3 "$SCRIPT_DIR/gemini_ocr_pipeline.py"
echo ""
echo "   ✔ OCR complete."
echo ""

# ── Step 2: OCR JSON → Mangle facts ─────────────────────────
echo "▶  Step 2 — Converting OCR JSON → Mangle facts..."
echo "   Input  : $SCRIPT_DIR/ocr_outputs/"
echo "   Output : $SCRIPT_DIR/mangle_facts/pos_orders.mangle"
echo ""
python3 "$SCRIPT_DIR/ocr_to_mangle.py"
echo ""
echo "   ✔ OCR → Mangle conversion complete."
echo ""

# ── Step 3: Excel master data → Mangle facts ─────────────────
echo "▶  Step 3 — Converting Excel master data → Mangle facts..."
echo "   Input  : $SCRIPT_DIR/docs/"
echo "   Output : $SCRIPT_DIR/mangle_facts/"
echo ""
python3 "$SCRIPT_DIR/excel_to_mangle.py"
echo ""
echo "   ✔ Excel → Mangle conversion complete."
echo ""

# ── Step 4: Product image recognition (optional) ────────────
PRODUCT_IMGS=$(find "$SCRIPT_DIR/product_images" -type f \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) 2>/dev/null | wc -l | tr -d ' ')
if [ "$PRODUCT_IMGS" -gt 0 ]; then
    echo ">>  Step 4 -- Running product image recognition..."
    echo "   Images : $PRODUCT_IMGS file(s) in $SCRIPT_DIR/product_images/"
    echo "   Output : $SCRIPT_DIR/mangle_facts/product_catalog.mangle"
    echo ""
    python3 "$SCRIPT_DIR/product_image_pipeline.py"
    echo ""
    echo "   [OK] Product image recognition complete."
else
    echo ">>  Step 4 -- Skipped (no files in product_images/ -- add product photos to enable)"
fi
echo ""

# ── Summary ──────────────────────────────────────────────────
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   Pipeline finished successfully!        ║"
echo "  ╠══════════════════════════════════════════╣"
FACT_COUNT=$(grep -c '\.' "$SCRIPT_DIR/mangle_facts/pos_orders.mangle" 2>/dev/null || echo "?")
MANGLE_FILES=$(ls "$SCRIPT_DIR/mangle_facts/"*.mangle 2>/dev/null | wc -l | tr -d ' ')
CATALOG_COUNT=$(grep -c 'product_visual' "$SCRIPT_DIR/mangle_facts/product_catalog.mangle" 2>/dev/null || echo "0")
echo "  ║  Mangle files produced : $MANGLE_FILES"
echo "  ║  pos_orders.mangle facts: $FACT_COUNT"
echo "  ║  Product catalog entries: $CATALOG_COUNT"
echo "  ║  Currency rate (SGD): 1 SGD = 5.34 CNY  "
echo "  ╚══════════════════════════════════════════╝"
echo ""
