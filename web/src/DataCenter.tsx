import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { dataApi } from "./api";
import { formatQuantity, formatShanghaiTime } from "./display";
import type {
  DataSummary, InventoryRow, ProductionOrderDetail, ProductionOrderRow,
  PurchaseOrderDetail, PurchaseOrderRow, SalesOrderDetail, SalesOrderRow,
  SupplierPartRow, SupplierRow,
} from "./dataTypes";

type Section = "overview" | "suppliers" | "supplierParts" | "inventory" |
  "purchase" | "production" | "sales";
type Detail = PurchaseOrderDetail | ProductionOrderDetail | SalesOrderDetail;
type Column<T> = { title: string; value: (row: T) => ReactNode };

const sections: { id: Section; label: string; group: string }[] = [
  { id: "overview", label: "数据总览", group: "总览" },
  { id: "suppliers", label: "供应商", group: "供应链" },
  { id: "supplierParts", label: "供应关系", group: "供应链" },
  { id: "inventory", label: "库存", group: "供应链" },
  { id: "purchase", label: "采购订单", group: "供应链" },
  { id: "production", label: "生产订单", group: "生产" },
  { id: "sales", label: "销售订单", group: "销售" },
];

const statusNames: Record<string, string> = {
  ACTIVE: "正常", BLOCKED: "已冻结", PHASE_OUT: "逐步退出",
  LAST_TIME_BUY: "最后采购期", EOL: "已停产", QUALIFIED: "已认证",
  CONDITIONAL: "有条件认证", UNQUALIFIED: "未认证", DRAFT: "草稿",
  OPEN: "进行中", PARTIALLY_RECEIVED: "部分收货", COMPLETED: "已完成",
  CANCELLED: "已取消", PLANNED: "已计划", RELEASED: "已下达",
  IN_PROGRESS: "生产中", CONFIRMED: "已确认", PARTIALLY_DELIVERED: "部分交付",
};
const status = (value: string) => statusNames[value] || value;
const date = (value: string | null) => value ? value.slice(0, 10) : "—";

function DataTable<T>({ rows, columns, onRow }: {
  rows: T[]; columns: Column<T>[]; onRow?: (row: T) => void;
}) {
  if (!rows.length) return <div className="data-empty">没有符合条件的数据。</div>;
  return <div className="table-wrap data-table"><table>
    <thead><tr>{columns.map((column) => <th key={column.title}>{column.title}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={index}
      className={onRow ? "clickable-row" : undefined}
      onClick={() => onRow?.(row)}>
      {columns.map((column) => <td key={column.title}>{column.value(row)}</td>)}
    </tr>)}</tbody>
  </table></div>;
}

export default function DataCenter() {
  const [section, setSection] = useState<Section>("overview");
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [suppliers, setSuppliers] = useState<SupplierRow[]>([]);
  const [supplierParts, setSupplierParts] = useState<SupplierPartRow[]>([]);
  const [inventory, setInventory] = useState<InventoryRow[]>([]);
  const [purchase, setPurchase] = useState<PurchaseOrderRow[]>([]);
  const [production, setProduction] = useState<ProductionOrderRow[]>([]);
  const [sales, setSales] = useState<SalesOrderRow[]>([]);
  const [supplierSearch, setSupplierSearch] = useState("");
  const [relationSupplier, setRelationSupplier] = useState("");
  const [partSearch, setPartSearch] = useState("");
  const [inventorySearch, setInventorySearch] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (target: Section) => {
    setLoading(true);
    setError(null);
    try {
      switch (target) {
        case "overview": setSummary(await dataApi.summary()); break;
        case "suppliers": setSuppliers(await dataApi.suppliers(supplierSearch)); break;
        case "supplierParts":
          setSupplierParts(await dataApi.supplierParts(relationSupplier, partSearch)); break;
        case "inventory": setInventory(await dataApi.inventory(inventorySearch)); break;
        case "purchase": setPurchase(await dataApi.purchaseOrders()); break;
        case "production": setProduction(await dataApi.productionOrders()); break;
        case "sales": setSales(await dataApi.salesOrders()); break;
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据读取失败");
    } finally {
      setLoading(false);
    }
  }, [supplierSearch, relationSupplier, partSearch, inventorySearch]);

  useEffect(() => { void load(section); }, [section]); // 首次进入或切换栏目时加载

  async function openOrder(kind: "purchase" | "production" | "sales", number: string) {
    setDetail(null);
    setDetailLoading(true);
    setError(null);
    try {
      const item = kind === "purchase" ? await dataApi.purchaseOrder(number) :
        kind === "production" ? await dataApi.productionOrder(number) :
          await dataApi.salesOrder(number);
      setDetail(item);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "订单详情读取失败");
    } finally {
      setDetailLoading(false);
    }
  }

  function choose(target: Section) {
    setDetail(null);
    setSection(target);
  }

  return <div className="data-layout">
    <aside className="data-sidebar" aria-label="数据中心导航">
      <p className="eyebrow">企业数据中心</p>
      {sections.map((item, index) => <div key={item.id}>
        {(index === 0 || sections[index - 1].group !== item.group) &&
          <p className="data-group">{item.group}</p>}
        <button type="button" className={section === item.id ? "data-nav active" : "data-nav"}
          onClick={() => choose(item.id)}>{item.label}</button>
      </div>)}
    </aside>
    <div className="data-main">
      <div className="data-intro">
        <div><p className="eyebrow">只读业务数据</p><h2>{sections.find((item) => item.id === section)?.label}</h2>
          <p>查看当前 PostgreSQL 中的企业业务记录。此页面不提供数据修改操作。</p></div>
        <button type="button" className="button button-secondary" disabled={loading}
          onClick={() => void load(section)}>刷新数据</button>
      </div>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {loading ? <div className="data-loading" role="status">正在读取数据…</div> : <>
        {section === "overview" && summary && <div className="summary-grid">
          {([
            ["供应商", summary.suppliers], ["供应关系", summary.supplier_parts],
            ["库存记录", summary.inventory], ["采购订单", summary.purchase_orders],
            ["生产订单", summary.production_orders], ["销售订单", summary.sales_orders],
            ["采购明细", summary.purchase_order_lines],
            ["生产物料需求", summary.production_material_requirements],
            ["销售明细", summary.sales_order_lines],
          ] as [string, number][]).map(([label, count]) => <div className="summary-card" key={label}>
            <span>{label}</span><strong>{count}</strong><small>条当前记录</small>
          </div>)}
        </div>}
        {section === "suppliers" && <>
          <SearchBar values={[supplierSearch]} labels={["供应商编号或名称"]}
            onChange={[setSupplierSearch]} onSearch={() => void load(section)} />
          <DataTable rows={suppliers} columns={[
            { title: "供应商编号", value: (row) => row.supplier_code },
            { title: "供应商名称", value: (row) => row.supplier_name },
            { title: "状态", value: (row) => status(row.status) },
            { title: "质量评分", value: (row) => formatQuantity(row.quality_rating) },
            { title: "交付评分", value: (row) => formatQuantity(row.delivery_rating) },
          ]} />
        </>}
        {section === "supplierParts" && <>
          <SearchBar values={[relationSupplier, partSearch]}
            labels={["供应商编号或名称", "零件号"]}
            onChange={[setRelationSupplier, setPartSearch]}
            onSearch={() => void load(section)} />
          <DataTable rows={supplierParts} columns={[
            { title: "供应商", value: (row) => `${row.supplier_name} (${row.supplier_code})` },
            { title: "零件号", value: (row) => row.part_number },
            { title: "Revision", value: (row) => row.revision_code || "—" },
            { title: "制造商料号", value: (row) => row.manufacturer_part_number },
            { title: "供应状态", value: (row) => status(row.status) },
            { title: "认证状态", value: (row) => status(row.qualification_status) },
            { title: "单价", value: (row) => `${formatQuantity(row.unit_price)} ${row.currency}` },
            { title: "停产日期", value: (row) => date(row.eol_date) },
          ]} />
        </>}
        {section === "inventory" && <>
          <SearchBar values={[inventorySearch]} labels={["零件号"]}
            onChange={[setInventorySearch]} onSearch={() => void load(section)} />
          <DataTable rows={inventory} columns={[
            { title: "零件号", value: (row) => row.part_number },
            { title: "Revision", value: (row) => row.revision_code },
            { title: "工厂", value: (row) => row.plant_code },
            { title: "仓库", value: (row) => row.warehouse_code },
            { title: "现有数量", value: (row) => formatQuantity(row.qty_on_hand) },
            { title: "预留数量", value: (row) => formatQuantity(row.qty_reserved) },
            { title: "单位成本", value: (row) => `${formatQuantity(row.unit_cost)} ${row.currency}` },
          ]} />
        </>}
        {section === "purchase" && <DataTable rows={purchase} onRow={(row) => void openOrder("purchase", row.order_number)} columns={[
          { title: "采购订单号", value: (row) => <strong>{row.order_number}</strong> },
          { title: "供应商", value: (row) => row.supplier_name },
          { title: "状态", value: (row) => status(row.status) },
          { title: "订单日期", value: (row) => date(row.order_date) },
          { title: "预计到货日期", value: (row) => date(row.expected_date) },
          { title: "查看", value: () => "查看明细 →" },
        ]} />}
        {section === "production" && <DataTable rows={production} onRow={(row) => void openOrder("production", row.order_number)} columns={[
          { title: "生产订单号", value: (row) => <strong>{row.order_number}</strong> },
          { title: "产品", value: (row) => `${row.product_part_number} / ${row.product_revision}` },
          { title: "状态", value: (row) => status(row.status) },
          { title: "计划数量", value: (row) => formatQuantity(row.planned_qty) },
          { title: "已完成数量", value: (row) => formatQuantity(row.completed_qty) },
          { title: "计划开始", value: (row) => formatShanghaiTime(row.planned_start) },
          { title: "查看", value: () => "查看物料 →" },
        ]} />}
        {section === "sales" && <DataTable rows={sales} onRow={(row) => void openOrder("sales", row.order_number)} columns={[
          { title: "销售订单号", value: (row) => <strong>{row.order_number}</strong> },
          { title: "客户编号", value: (row) => row.customer_code },
          { title: "状态", value: (row) => status(row.status) },
          { title: "订单日期", value: (row) => date(row.order_date) },
          { title: "要求交付日期", value: (row) => date(row.requested_delivery_date) },
          { title: "查看", value: () => "查看明细 →" },
        ]} />}
      </>}
      {detailLoading && <div className="data-loading" role="status">正在读取订单详情…</div>}
      {detail && !detailLoading && <OrderDetail detail={detail} onClose={() => setDetail(null)} />}
    </div>
  </div>;
}

function SearchBar({ values, labels, onChange, onSearch }: {
  values: string[]; labels: string[];
  onChange: ((value: string) => void)[]; onSearch: () => void;
}) {
  return <form className="data-search" onSubmit={(event) => { event.preventDefault(); onSearch(); }}>
    {values.map((value, index) => <label key={labels[index]}>
      <span>{labels[index]}</span>
      <input value={value} onChange={(event) => onChange[index](event.target.value)}
        placeholder={`搜索${labels[index]}`} />
    </label>)}
    <button className="button button-primary" type="submit">搜索</button>
  </form>;
}

function OrderDetail({ detail, onClose }: { detail: Detail; onClose: () => void }) {
  const kind = "requirements" in detail ? "生产订单" : "customer_code" in detail ? "销售订单" : "采购订单";
  return <section className="panel order-detail" aria-label={`${kind}详情`}>
    <div className="panel-heading compact"><div><span className="section-number">详情</span>
      <h3>{kind} {detail.order_number}</h3></div>
      <button type="button" className="button button-secondary" onClick={onClose}>关闭详情</button>
    </div>
    <p className="detail-meta">状态：{status(detail.status)} · 订单号：{detail.order_number}</p>
    {"requirements" in detail ? <DataTable rows={detail.requirements} columns={[
      { title: "行号", value: (row) => row.line_number },
      { title: "零件号", value: (row) => row.part_number },
      { title: "Revision", value: (row) => row.revision_code },
      { title: "冻结需求数量", value: (row) => formatQuantity(row.required_qty) },
      { title: "预留数量", value: (row) => formatQuantity(row.reserved_qty) },
      { title: "已发料数量", value: (row) => formatQuantity(row.issued_qty) },
    ]} /> : "customer_code" in detail ? <DataTable rows={detail.lines} columns={[
      { title: "行号", value: (row) => row.line_number },
      { title: "产品", value: (row) => row.product_part_number },
      { title: "Revision", value: (row) => row.product_revision },
      { title: "订单数量", value: (row) => formatQuantity(row.ordered_qty) },
      { title: "已交付数量", value: (row) => formatQuantity(row.delivered_qty) },
      { title: "要求交付日期", value: (row) => date(row.requested_delivery_date) },
    ]} /> : <DataTable rows={detail.lines} columns={[
      { title: "行号", value: (row) => row.line_number },
      { title: "零件号", value: (row) => row.part_number },
      { title: "Revision", value: (row) => row.revision_code },
      { title: "订购数量", value: (row) => formatQuantity(row.ordered_qty) },
      { title: "已收货数量", value: (row) => formatQuantity(row.received_qty) },
      { title: "预计到货日期", value: (row) => date(row.expected_date) },
    ]} />}
  </section>;
}
