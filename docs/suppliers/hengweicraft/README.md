# Hengwei Craft

This folder holds the canonical supplier reference for Hengwei Craft alongside the source files used to verify orders and catalogs.

The canonical machine-readable bundle lives in [supplier_bundle.json](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/supplier_bundle.json). Future import or validation tooling should use that file first.

## Supplier

- Supplier ID: `CN-001`
- English name: `Hengwei Craft`
- Chinese name: `衡威工艺`
- Primary geography: `Guangzhou` and `Jiangmen`, China

The structured supplier record lives in [supplier_profile.json](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/supplier_profile.json).

## Canonical Orders

- Order `369`
  - Date: `2026-03-30`
  - Source document total: `34,125 CNY`
  - Source document status: unpaid
  - Item reconciliation: `catalog_matched`
  - Financial reconciliation: `disputed`
  - Reported external reference: `149` totaling `34,123 CNY`
  - Reported settlement: `500 CNY` via Alipay, `15,015 HKD` bank transfer, `23,550 HKD` bank transfer
  - Canonical source scan: [order-149-2025-01-15-source.PNG](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/orders/order-149-2025-01-15-source.PNG)
  - Structured record: [369.json](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/orders/369.json)
  - Status: item reconciliation can continue, but financial reconciliation remains blocked until the external `149` reference is matched to a source document or bank trail
- Order `364-365`
  - Date: `2026-03-26`
  - Total: `11,046 CNY`
  - Payment: cash at `5.34 CNY/SGD`
  - Item reconciliation: `needs_follow_up`
  - Financial reconciliation: `paid`
  - Status: delivered and currently staged at Breeze by the East
  - Planned destination: Jewel for opening on `2026-05-01`
  - Canonical source scan: [order-364-365-2026-03-26-source.PNG](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/orders/order-364-365-2026-03-26-source.PNG)
  - Structured record: [364-365.json](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/orders/364-365.json)

## Source Mapping Notes

- The purchase-order scans now use canonical filenames that match the actual order numbers.
- One source document previously described in chat as order `149` is actually labeled `369` in the scan itself, so the folder now records that as an explicit reconciliation issue instead of flattening the conflict away.
- The earlier raw filenames are retained only in metadata fields such as `original_source_filename`.
- The JSON files are the normalized references the app or future loaders should use.

## Location Notes

- `Breeze by the East` is the business home base and temporary warehouse.
- `Jewel` is the planned retail destination for the staged delivered stock tied to order `364-365`.

## Catalog Sources

- [衡威.爱达荷目录2026(英).xlsx](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/catalog/衡威.爱达荷目录2026(英).xlsx)
- [衡威家居目录2026(英).xlsx](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/catalog/衡威家居目录2026(英).xlsx)
- Structured catalog extraction: [catalog_products.json](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/catalog_products.json)

## Extracted Product Staging

- Product candidates extracted from the visible supplier codes now live in [product_candidates.json](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/product_candidates.json).
- Catalog-derived product records now live in [catalog_products.json](/Users/victoriaenso/Documents/GitHub/retailmanagement/docs/suppliers/hengweicraft/catalog_products.json), which lets the review UI show exact catalog matches for invoice lines.
- These candidates are ready for SKU matching, but purchase-order import is still blocked until each supplier code is matched to a real RetailSG SKU id.
