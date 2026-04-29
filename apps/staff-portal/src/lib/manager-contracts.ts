export type RecommendationType = "reorder" | "price_change" | "stock_anomaly";

export type RecommendationStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "applied"
  | "expired"
  | "queued"
  | "unavailable";

export type InventoryType = "purchased" | "material" | "finished";

export type SourcingStrategy =
  | "supplier_premade"
  | "manufactured_standard"
  | "manufactured_custom";

export interface RecommendationOutcome {
  recommendation_id: string;
  sku_id: string | null;
  title: string;
  type: RecommendationType;
  status: RecommendationStatus;
  updated_at: string | null;
}

export interface ManagerSummary {
  store_id: string;
  analysis_status: string;
  last_generated_at: string | null;
  low_stock_count: number;
  anomaly_count: number;
  pending_price_recommendations: number;
  pending_reorder_recommendations: number;
  pending_stock_anomalies: number;
  open_purchase_orders: number;
  active_work_orders: number;
  in_transit_transfers: number;
  purchased_units: number;
  material_units: number;
  finished_units: number;
  recent_outcomes: RecommendationOutcome[];
}

export interface InventoryInsight {
  inventory_id: string | null;
  sku_id: string;
  store_id: string;
  sku_code: string;
  description: string;
  long_description: string | null;
  inventory_type: InventoryType;
  sourcing_strategy: SourcingStrategy;
  supplier_name: string | null;
  cost_price: number | null;
  current_price: number | null;
  current_price_valid_until: string | null;
  purchased_qty: number;
  purchased_incoming_qty: number;
  material_qty: number;
  material_incoming_qty: number;
  material_allocated_qty: number;
  finished_qty: number;
  finished_allocated_qty: number;
  in_transit_qty: number;
  active_work_order_count: number;
  qty_on_hand: number;
  reorder_level: number;
  reorder_qty: number;
  low_stock: boolean;
  anomaly_flag: boolean;
  anomaly_reason: string | null;
  recent_sales_qty: number;
  recent_sales_revenue: number;
  avg_daily_sales: number;
  days_of_cover: number | null;
  pending_recommendation_count: number;
  pending_price_recommendation_count: number;
  last_updated: string | null;
}

export interface ManagerRecommendation {
  id: string;
  store_id: string;
  sku_id: string | null;
  inventory_id: string | null;
  inventory_type: InventoryType;
  sourcing_strategy: SourcingStrategy;
  supplier_name: string | null;
  type: RecommendationType;
  status: RecommendationStatus;
  title: string;
  rationale: string;
  confidence: number;
  supporting_metrics: Record<string, unknown>;
  source: string;
  expected_impact: string | null;
  current_price: number | null;
  suggested_price: number | null;
  suggested_order_qty: number | null;
  workflow_action: string | null;
  analysis_status: string;
  generated_at: string;
  decided_at: string | null;
  applied_at: string | null;
  note: string | null;
}

export interface InventoryAdjustmentHistory {
  id: string;
  inventory_id: string;
  sku_id: string;
  store_id: string;
  quantity_delta: number;
  resulting_qty: number;
  reason: string;
  source: string;
  note: string | null;
  created_at: string;
}

export interface SupplyChainSummary {
  store_id: string;
  supplier_count: number;
  open_purchase_orders: number;
  active_work_orders: number;
  in_transit_transfers: number;
  purchased_units: number;
  material_units: number;
  finished_units: number;
  open_recommendation_linked_orders: number;
}

export interface Supplier {
  id: string;
  name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  lead_time_days: number;
  currency: string;
  notes: string | null;
  is_active: boolean;
}

export interface StageInventoryPosition {
  id: string;
  store_id: string;
  sku_id: string;
  sku_code: string;
  description: string;
  inventory_type: InventoryType;
  sourcing_strategy: SourcingStrategy;
  supplier_name: string | null;
  quantity_on_hand: number;
  incoming_quantity: number;
  allocated_quantity: number;
  available_quantity: number;
}

export interface PurchaseOrderLine {
  line_id: string;
  sku_id: string;
  sku_code: string;
  description: string;
  stage_inventory_type: InventoryType;
  quantity: number;
  unit_cost: number;
  received_quantity: number;
  open_quantity: number;
  note: string | null;
}

export interface PurchaseOrder {
  id: string;
  supplier_id: string;
  supplier_name: string | null;
  status: "draft" | "ordered" | "partially_received" | "received" | "cancelled";
  lines: PurchaseOrderLine[];
  total_quantity: number;
  total_cost: number;
  expected_delivery_date: string | null;
  note: string | null;
  recommendation_id: string | null;
}

export interface WorkOrderComponent {
  sku_id: string;
  sku_code: string;
  description: string;
  quantity_required: number;
  note: string | null;
}

export interface WorkOrder {
  id: string;
  finished_sku_id: string;
  finished_sku_code: string;
  finished_description: string;
  work_order_type: "standard" | "custom";
  status: "draft" | "scheduled" | "in_progress" | "completed" | "cancelled";
  target_quantity: number;
  completed_quantity: number;
  components: WorkOrderComponent[];
  due_date: string | null;
  note: string | null;
  recommendation_id: string | null;
}

export interface BOMRecipeComponent {
  sku_id: string;
  sku_code: string;
  description: string;
  quantity_required: number;
  note: string | null;
}

export interface BOMRecipe {
  id: string;
  store_id: string;
  finished_sku_id: string;
  finished_sku_code: string;
  finished_description: string;
  name: string;
  yield_quantity: number;
  components: BOMRecipeComponent[];
  notes: string | null;
}

export interface StockTransfer {
  id: string;
  sku_id: string;
  sku_code: string;
  description: string;
  quantity: number;
  from_inventory_type: InventoryType;
  to_inventory_type: InventoryType;
  status: "draft" | "in_transit" | "received" | "cancelled";
  note: string | null;
  recommendation_id: string | null;
  dispatched_at: string | null;
  received_at: string | null;
}

export type DataEnvelope<T> = {
  data: T;
};
