export interface DataSummary {
  suppliers: number;
  supplier_parts: number;
  inventory: number;
  purchase_orders: number;
  purchase_order_lines: number;
  production_orders: number;
  production_material_requirements: number;
  sales_orders: number;
  sales_order_lines: number;
}

export interface SupplierRow {
  supplier_code: string;
  supplier_name: string;
  status: string;
  quality_rating: string;
  delivery_rating: string;
}

export interface SupplierPartRow {
  supplier_code: string;
  supplier_name: string;
  part_number: string;
  revision_code: string | null;
  manufacturer_part_number: string;
  status: string;
  qualification_status: string;
  unit_price: string;
  currency: string;
  lead_time_days: number;
  minimum_order_qty: string;
  last_time_buy_date: string | null;
  eol_date: string | null;
}

export interface InventoryRow {
  plant_code: string;
  warehouse_code: string;
  part_number: string;
  revision_code: string;
  qty_on_hand: string;
  qty_reserved: string;
  unit_cost: string;
  currency: string;
}

export interface PurchaseOrderRow {
  order_number: string;
  supplier_code: string;
  supplier_name: string;
  status: string;
  order_date: string;
  expected_date: string | null;
  currency: string;
}

export interface PurchaseOrderLineRow {
  line_number: number;
  part_number: string;
  revision_code: string;
  ordered_qty: string;
  received_qty: string;
  unit_price: string;
  expected_date: string | null;
  status: string;
}

export interface PurchaseOrderDetail extends PurchaseOrderRow {
  lines: PurchaseOrderLineRow[];
}

export interface ProductionOrderRow {
  order_number: string;
  product_part_number: string;
  product_revision: string;
  status: string;
  planned_qty: string;
  completed_qty: string;
  planned_start: string;
  planned_end: string;
}

export interface ProductionRequirementRow {
  line_number: number;
  part_number: string;
  revision_code: string;
  required_qty: string;
  reserved_qty: string;
  issued_qty: string;
}

export interface ProductionOrderDetail extends ProductionOrderRow {
  requirements: ProductionRequirementRow[];
}

export interface SalesOrderRow {
  order_number: string;
  customer_code: string;
  status: string;
  order_date: string;
  requested_delivery_date: string | null;
}

export interface SalesOrderLineRow {
  line_number: number;
  product_part_number: string;
  product_revision: string;
  ordered_qty: string;
  delivered_qty: string;
  requested_delivery_date: string | null;
}

export interface SalesOrderDetail extends SalesOrderRow {
  lines: SalesOrderLineRow[];
}
