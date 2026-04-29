from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from app.auth.dependencies import RoleEnum, require_any_store_role

router = APIRouter(prefix="/api/pos-labelling", tags=["pos-labelling"])

@router.get("/print", response_class=HTMLResponse)
def print_labels(
    skus: List[str] = Query(...),
    prices: Optional[List[str]] = Query(None),
    names: Optional[List[str]] = Query(None),
    _: dict = Depends(require_any_store_role(RoleEnum.owner)),
):
    """
    Generates an HTML page suitable for printing POS labels.
    Uses JsBarcode to render barcodes for the provided SKUs.
    """
    items_html = ""
    for i, sku in enumerate(skus):
        price = prices[i] if prices and i < len(prices) else ""
        name = names[i] if names and i < len(names) else ""
        
        items_html += f"""
        <div class="label">
            <div class="header">
                <span class="name">{name}</span>
                <span class="price">{price}</span>
            </div>
            <svg class="barcode"
                 jsbarcode-format="CODE128"
                 jsbarcode-value="{sku}"
                 jsbarcode-textmargin="0"
                 jsbarcode-fontoptions="bold">
            </svg>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>POS Labels</title>
        <script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>
        <style>
            body {{
                font-family: sans-serif;
                margin: 0;
                padding: 20px;
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
            }}
            .label {{
                border: 1px dashed #ccc;
                padding: 10px;
                width: 250px;
                text-align: center;
                page-break-inside: avoid;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                margin-bottom: 5px;
                font-size: 14px;
                font-weight: bold;
            }}
            .price {{
                color: #333;
            }}
            .barcode {{
                width: 100%;
                height: 60px;
            }}
            @media print {{
                body {{
                    padding: 0;
                }}
                .label {{
                    border: none;
                    margin-bottom: 20px;
                }}
            }}
        </style>
    </head>
    <body>
        {items_html}
        <script>
            JsBarcode(".barcode").init();
            window.onload = function() {{
                // Auto-trigger print dialog when loaded in a WebView/Browser
                setTimeout(function() {{ window.print(); }}, 500);
            }};
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
