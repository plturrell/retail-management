export interface QualityIssue {
  field: string;
  severity: "error" | "warning";
  message: string;
}

export interface Product {
  id: string;
  internal_code: string;
  sku_code: string;
  description: string;
  long_description: string;
  material: string;
  product_type: string;
  category: string;
  amazon_sku: string;
  google_product_id: string;
  google_product_category: string;
  nec_plu: string;
  cost_price: number | null;
  retail_price: number | null;
  qty_on_hand: number | null;
  sources: string[];
  raw_names: string[];
  mention_count: number;
  inventory_type: string;
  sourcing_strategy: string;
  inventory_category: string;
  sale_ready: boolean;
  block_sales: boolean;
  stocking_status: string;
  stocking_location: string;
  use_stock: boolean;
  _quality_issues: QualityIssue[];
  _issue_count: number;
}

export interface ReferenceData {
  product_types: string[];
  inventory_categories: string[];
  stocking_statuses: string[];
  stocking_locations: string[];
  inventory_types: string[];
  sourcing_strategies: string[];
}

export interface QualitySummary {
  total_errors: number;
  total_warnings: number;
  products_with_issues: number;
  products_clean: number;
}

export interface DataQualityResponse {
  generated_at: string;
  total_products: number;
  quality_summary: QualitySummary;
  reference: ReferenceData;
  products: Product[];
}

export interface ProductCorrection {
  id: string;
  [field: string]: string | number | boolean | null | undefined;
}

export type FilterMode =
  | "all"
  | "errors"
  | "warnings"
  | "clean"
  | "finished_for_sale"
  | "catalog_to_stock"
  | "material"
  | "store_operations"
  | "sale_ready"
  | "not_stocked"
  | "missing_price"
  | "homeware"
  | "jewellery"
  | "minerals";
