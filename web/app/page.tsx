"use client";

import {
  Activity,
  BarChart3,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Database,
  FileUp,
  FlaskConical,
  Image as ImageIcon,
  LayoutDashboard,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

type Health = { name: string; status: string; detail?: string | null };
type Recommendation = {
  id: string;
  agent: string;
  action: string;
  expected_cm3_delta?: string | null;
  risk: string;
  status: string;
  shadow_mode: boolean;
};
type SourceConnector = {
  platform: string;
  ingestion: string;
  authentication: string;
  status: string;
  notes: string;
};
type PassportReadiness = {
  kind: "product" | "compliance" | "quality";
  status: "missing" | "draft" | "awaiting_approval" | "approved" | "blocked";
  missing_fields: string[];
  evidence_count: number;
};
type ProductReadiness = {
  product: { id: string; sku: string; name: string; status: string };
  passports: PassportReadiness[];
  ready_for_validation: boolean;
};
type PassportReview = {
  product: { id: string; sku: string; name: string };
  passport: {
    id: string;
    kind: "product" | "compliance" | "quality";
    version: number;
    facts: Record<string, unknown>;
    evidence: string[];
    missing_fields: string[];
    created_at: string;
  };
};
type ProductIdentity = { id: string; sku: string; name: string };
type SourcingComparison = {
  product: ProductIdentity;
  supplier_count: number;
  offer_count: number;
  scenario_count: number;
  ready_for_procurement_review: boolean;
  rows: Array<{
    offer: { id: string; supplier_ref: string; platform: string; title: string; unit_price: string; currency: string; min_order_quantity: number; evidence_ref: string };
    scenario: null | { id: string; cm3_cny: string; cm3_rate: string; break_even_price_rub: string; evidence: string[] };
    has_positive_cm3: boolean;
  }>;
};
type ApprovalRecord = { id: string; action: string; resource_id: string; status: string; requested_by: string; payload: Record<string, unknown> };
type SampleEvent = { id: string; sequence: number; event_type: string; effective_at: string; evidence_id: string; facts: Record<string, unknown> };
type SampleOrder = {
  id: string; approval_id: string; product_id: string; product: { sku: string; name: string };
  offer_id: string; scenario_id: string; supplier_ref: string; quantity: number; currency: string;
  unit_price: string; status: string; next_events: string[]; events: SampleEvent[];
};
type SupplierPerformance = {
  supplier_ref: string; sample_order_count: number; completed_sample_count: number; rejected_sample_count: number;
  quality_yield: string | null; delivery_completeness: string | null; on_time_rate: string | null;
  score: string | null; evidence_count: number;
};
type BackupOption = {
  offer: { id: string; supplier_ref: string; platform: string; unit_price: string; currency: string; min_order_quantity: number };
  scenario: { id: string; cm3_cny: string; cm3_rate: string; break_even_price_rub: string };
  supplier_performance: SupplierPerformance | null;
  advisory_only: boolean;
};
type GateRequirement = {
  id: string;
  title: string;
  ready: boolean;
  status: "ready_for_review" | "needs_input";
  current: number;
  target: number;
  next_action: string;
};
type GateReadiness = {
  status: "ready_for_review" | "needs_input";
  g0: "ready_for_review" | "blocked";
  g1: "ready_for_review" | "blocked";
  requirements: GateRequirement[];
  next_actions: string[];
};

const passportLabels = { product: "商品资料", compliance: "俄罗斯合规", quality: "样品质量" } as const;
const procurementStatusLabels: Record<string, string> = {
  approved_to_order: "已批准，待确认样品单", order_confirmed: "供应商已确认", shipped: "样品运输中",
  received: "样品已签收", inspected: "验货完成，待决定", rework_required: "需要返工复验",
  golden_sample_approved: "黄金样已批准", sample_rejected: "样品已淘汰", cancelled: "样品单已取消",
};
const procurementEventLabels: Record<string, string> = {
  order_confirmed: "确认样品订单", shipped: "记录发货", received: "记录签收", inspection_completed: "完成验货",
  golden_sample_approved: "批准黄金样", sample_rejected: "淘汰样品", rework_required: "要求返工", cancelled: "取消",
};

const nav = [
  [LayoutDashboard, "经营总览", true],
  [FileUp, "数据中心", false],
  [Waypoints, "全球货源", false],
  [Boxes, "商品中心", false],
  [BrainCircuit, "AI 工作台", false],
  [ImageIcon, "内容工厂", false],
  [FlaskConical, "增长实验", false],
  [CircleDollarSign, "利润中心", false],
  [ShieldCheck, "审批中心", false],
] as const;

export default function Home() {
  const [health, setHealth] = useState<Record<string, Health>>({});
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [sourceConnectors, setSourceConnectors] = useState<SourceConnector[]>([]);
  const [offers, setOffers] = useState<unknown[]>([]);
  const [products, setProducts] = useState<ProductIdentity[]>([]);
  const [comparisons, setComparisons] = useState<SourcingComparison[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([]);
  const [sampleOrders, setSampleOrders] = useState<SampleOrder[]>([]);
  const [supplierPerformance, setSupplierPerformance] = useState<SupplierPerformance[]>([]);
  const [backupOptions, setBackupOptions] = useState<Record<string, BackupOption[]>>({});
  const [backupRationales, setBackupRationales] = useState<Record<string, string>>({});
  const [skuReadiness, setSkuReadiness] = useState<ProductReadiness[]>([]);
  const [passportReviews, setPassportReviews] = useState<PassportReview[]>([]);
  const [gateReadiness, setGateReadiness] = useState<GateReadiness | null>(null);
  const [uploading, setUploading] = useState(false);
  const [gateUploading, setGateUploading] = useState(false);
  const [skuUploading, setSkuUploading] = useState(false);
  const [reviewingKey, setReviewingKey] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [sourcingUploading, setSourcingUploading] = useState(false);
  const [procurementDrafts, setProcurementDrafts] = useState<Record<string, { quantity: string; rationale: string }>>({});
  const [procurementBusy, setProcurementBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("等待第一份 Ozon 数据");

  const load = useCallback(async () => {
    const [healthResponse, recommendationResponse, connectorResponse, offersResponse, productsResponse, gateResponse, reviewResponse, approvalsResponse, sampleOrdersResponse, supplierPerformanceResponse] = await Promise.all([
      fetch("/backend/v1/integrations/health", { cache: "no-store" }),
      fetch("/backend/v1/recommendations", { cache: "no-store" }),
      fetch("/backend/v1/sourcing/connectors", { cache: "no-store" }),
      fetch("/backend/v1/sourcing/offers", { cache: "no-store" }),
      fetch("/backend/v1/products", { cache: "no-store" }),
      fetch("/backend/v1/operations/readiness", { cache: "no-store" }),
      fetch("/backend/v1/passport-reviews", { cache: "no-store" }),
      fetch("/backend/v1/approvals", { cache: "no-store" }),
      fetch("/backend/v1/procurement/sample-orders", { cache: "no-store" }),
      fetch("/backend/v1/procurement/suppliers/performance", { cache: "no-store" }),
    ]);
    if (healthResponse.ok) setHealth(await healthResponse.json());
    if (recommendationResponse.ok) setRecommendations(await recommendationResponse.json());
    if (connectorResponse.ok) setSourceConnectors(await connectorResponse.json());
    if (offersResponse.ok) setOffers(await offersResponse.json());
    if (gateResponse.ok) setGateReadiness(await gateResponse.json());
    if (reviewResponse.ok) setPassportReviews(await reviewResponse.json());
    if (approvalsResponse.ok) setApprovals(await approvalsResponse.json());
    if (sampleOrdersResponse.ok) setSampleOrders(await sampleOrdersResponse.json());
    if (supplierPerformanceResponse.ok) setSupplierPerformance(await supplierPerformanceResponse.json());
    if (productsResponse.ok) {
      const products: ProductIdentity[] = await productsResponse.json();
      setProducts(products);
      const readiness = await Promise.all(
        products.slice(0, 3).map(async (product) => {
          const response = await fetch(`/backend/v1/products/${product.id}/readiness`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ProductReadiness> : null;
        }),
      );
      setSkuReadiness(readiness.filter((item): item is ProductReadiness => item !== null));
      const comparisonRows = await Promise.all(products.slice(0, 3).map(async (product) => {
        const response = await fetch(`/backend/v1/sourcing/comparisons/${product.id}`, { cache: "no-store" });
        return response.ok ? response.json() as Promise<SourcingComparison> : null;
      }));
      setComparisons(comparisonRows.filter((item): item is SourcingComparison => item !== null && item.offer_count > 0));
    }
  }, []);

  useEffect(() => {
    load().catch(() => setNotice("后端尚未启动，请先启动 KJDS 服务"));
  }, [load]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement;
    if (!input.files?.[0]) return;
    setUploading(true);
    setNotice("正在校验并导入 Ozon 文件…");
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      const response = await fetch("/backend/v1/imports/ozon", { method: "POST", body });
      const result = await response.json();
      setNotice(
        response.ok
          ? `导入完成：${result.accepted_count} 行可用，${result.rejected_count} 行需检查`
          : result.detail ?? "导入失败",
      );
      if (response.ok) form.reset();
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setUploading(false);
    }
  }

  async function uploadGateEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (form.elements.namedItem("gate_file") as HTMLInputElement).files?.[0];
    const requirement = (form.elements.namedItem("requirement_id") as HTMLSelectElement).value;
    if (!file || !requirement) return;
    setGateUploading(true);
    setNotice("正在固化并校验阶段门证据…");
    const body = new FormData();
    body.append("file", file);
    body.append("requirement_id", requirement);
    body.append("effective_at", new Date().toISOString());
    try {
      const response = await fetch("/backend/v1/operations/gate-evidence", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${requirement} 证据已固化并进入阶段门` : result.detail ?? "证据提交失败");
      if (response.ok) {
        form.reset();
        await load();
      }
    } catch {
      setNotice("无法提交阶段门证据，请检查服务状态");
    } finally {
      setGateUploading(false);
    }
  }

  async function uploadSkuEpisode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement).value.trim();
    const lines = (name: string) => value(name).split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    const file = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).files?.[0];
    const productEvidence = file("product_evidence");
    const complianceEvidence = file("compliance_evidence");
    const qualityEvidence = file("quality_evidence");
    if (!productEvidence || !complianceEvidence || !qualityEvidence) return;
    const productFacts = {
      decision: "draft",
      material: value("material"), intended_use: value("intended_use"), country_of_origin: value("country_of_origin"),
      weight_kg: value("weight_kg"),
      dimensions_cm: { length: value("length_cm"), width: value("width_cm"), height: value("height_cm") },
    };
    const complianceFacts = {
      decision: "draft", hs_code: value("hs_code"), eaeu_rules: lines("eaeu_rules"),
      eac_requirement: value("eac_requirement"), chestny_znak_requirement: value("chestny_znak_requirement"),
      russian_labeling: value("russian_labeling"), ip_status: value("ip_status"),
      transport_restrictions: value("transport_restrictions"), sellability: value("sellability"),
    };
    const qualityFacts = {
      decision: "draft", golden_sample_ref: value("golden_sample_ref"),
      inspection_plan: lines("inspection_plan"), packaging_test: value("packaging_test"),
    };
    const body = new FormData();
    body.append("sku", value("sku")); body.append("name", value("product_name"));
    body.append("effective_at", new Date().toISOString());
    body.append("product_facts_json", JSON.stringify(productFacts));
    body.append("compliance_facts_json", JSON.stringify(complianceFacts));
    body.append("quality_facts_json", JSON.stringify(qualityFacts));
    body.append("product_evidence", productEvidence); body.append("compliance_evidence", complianceEvidence);
    body.append("quality_evidence", qualityEvidence);
    setSkuUploading(true);
    setNotice("正在建立 SKU、三类 Passport 与证据血缘…");
    try {
      const response = await fetch("/backend/v1/intake/sku-episodes", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${result.product.sku} 已建立，等待三类 Passport 人工复核` : result.detail ?? "SKU 录入失败");
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法提交 SKU Episode，请检查服务状态");
    } finally {
      setSkuUploading(false);
    }
  }

  async function reviewPassport(item: PassportReview, decision: "approved" | "blocked") {
    const key = item.passport.id;
    const notes = (reviewNotes[key] ?? "").trim();
    if (decision === "blocked" && !notes) {
      setNotice("阻断 Passport 必须填写明确原因");
      return;
    }
    setReviewingKey(key);
    setNotice(`正在记录 ${item.product.sku} 的人工审核结论…`);
    try {
      const response = await fetch(
        `/backend/v1/products/${item.product.id}/passports/${item.passport.kind}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_version: item.passport.version, decision, review_notes: notes }),
        },
      );
      const result = await response.json();
      setNotice(response.ok ? `${item.product.sku} · ${passportLabels[item.passport.kind]} 已${decision === "approved" ? "批准" : "阻断"}` : result.detail ?? "审核提交失败");
      if (response.ok) await load();
    } catch {
      setNotice("无法提交审核结论，请检查服务状态");
    } finally {
      setReviewingKey(null);
    }
  }

  async function uploadSupplierComparison(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement).value.trim();
    const file = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).files?.[0];
    const evidenceFiles = [1, 2, 3].map((index) => file(`supplier_evidence_${index}`));
    const assumptions = file("assumption_evidence");
    if (evidenceFiles.some((item) => !item) || !assumptions) return;
    const offerRows = [1, 2, 3].map((index) => ({
      supplier_ref: value(`supplier_ref_${index}`), platform: value(`platform_${index}`), external_id: value(`external_id_${index}`),
      source_url: value(`source_url_${index}`), title: value(`offer_title_${index}`), currency: value(`currency_${index}`),
      unit_price: value(`unit_price_${index}`), source_to_cny_rate: value(`source_to_cny_rate_${index}`),
      min_order_quantity: Number(value(`moq_${index}`)), weight_kg: value(`supplier_weight_${index}`),
      length_cm: value(`supplier_length_${index}`), width_cm: value(`supplier_width_${index}`), height_cm: value(`supplier_height_${index}`),
      domestic_logistics_per_unit: value(`domestic_logistics_${index}`), attributes: {}, media: [],
    }));
    const profitInputs = {
      sale_price_rub: value("sale_price_rub"), rub_per_cny: value("rub_per_cny"),
      international_freight_cny_per_kg: value("international_freight"), packaging_cny: value("packaging_cny"),
      last_mile_cny: value("last_mile_cny"), customs_rate: value("customs_rate"), platform_fee_rate: value("platform_fee_rate"),
      advertising_rate: value("advertising_rate"), return_reserve_rate: value("return_reserve_rate"), other_cost_cny: value("other_cost_cny"),
    };
    const body = new FormData();
    body.append("product_id", value("sourcing_product_id")); body.append("effective_at", new Date().toISOString());
    body.append("offers_json", JSON.stringify(offerRows)); body.append("profit_inputs_json", JSON.stringify(profitInputs));
    evidenceFiles.forEach((item, index) => body.append(`offer_evidence_${index + 1}`, item as File));
    body.append("assumption_evidence", assumptions);
    setSourcingUploading(true); setNotice("正在固化三家报价并计算可比 CM3…");
    try {
      const response = await fetch("/backend/v1/sourcing/comparison-intake", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${result.comparison.product.sku} 已完成三家证据化报价比较` : result.detail ?? "报价比较录入失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法提交供应商比较，请检查服务状态"); }
    finally { setSourcingUploading(false); }
  }

  async function requestProcurement(comparison: SourcingComparison, row: SourcingComparison["rows"][number]) {
    if (!row.scenario) return;
    const draft = procurementDrafts[row.offer.id] ?? { quantity: String(row.offer.min_order_quantity), rationale: "" };
    if (!draft.rationale.trim()) { setNotice("提交采购审批前必须填写选择理由"); return; }
    try {
      const response = await fetch("/backend/v1/sourcing/procurement-candidates", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: comparison.product.id, offer_id: row.offer.id, scenario_id: row.scenario.id, quantity: Number(draft.quantity), rationale: draft.rationale }),
      });
      const result = await response.json();
      setNotice(response.ok ? `采购候选已进入双人审批：${result.id}` : result.detail ?? "采购审批申请失败");
      if (response.ok) await load();
    } catch { setNotice("无法提交采购审批，请检查服务状态"); }
  }

  async function createSampleOrder(approvalId: string) {
    setProcurementBusy(approvalId);
    setNotice("正在把已批准的采购候选转为受控样品单…");
    try {
      const response = await fetch("/backend/v1/procurement/sample-orders", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approval_id: approvalId }),
      });
      const result = await response.json();
      setNotice(response.ok ? `${result.product.sku} 样品单已建立，等待供应商确认` : result.detail ?? "样品单建立失败");
      if (response.ok) await load();
    } catch { setNotice("无法建立样品单，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function recordSampleEvent(event: FormEvent<HTMLFormElement>, order: SampleOrder) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const file = (form.elements.namedItem("event_evidence") as HTMLInputElement).files?.[0];
    if (!file) return;
    let eventType = order.next_events.find((item) => item !== "cancelled") ?? "";
    const facts: Record<string, string | number> = {};
    if (order.status === "approved_to_order") {
      facts.supplier_order_ref = value("supplier_order_ref"); facts.promised_delivery_at = value("promised_delivery_at");
    } else if (order.status === "order_confirmed") {
      facts.tracking_ref = value("tracking_ref"); facts.carrier = value("carrier");
    } else if (order.status === "shipped") {
      facts.received_quantity = Number(value("received_quantity")); facts.damaged_quantity = Number(value("damaged_quantity"));
    } else if (order.status === "received" || order.status === "rework_required") {
      facts.inspected_quantity = Number(value("inspected_quantity")); facts.passed_quantity = Number(value("passed_quantity"));
      facts.defect_count = Number(value("defect_count")); facts.result = value("inspection_result");
    } else if (order.status === "inspected") {
      eventType = value("sample_decision");
      if (eventType === "golden_sample_approved") facts.golden_sample_ref = value("decision_detail");
      else facts.reason = value("decision_detail");
    }
    if (!eventType) { setNotice("当前样品单没有可执行的下一步"); return; }
    const body = new FormData();
    body.append("event_type", eventType); body.append("effective_at", new Date().toISOString());
    body.append("facts_json", JSON.stringify(facts)); body.append("file", file);
    setProcurementBusy(order.id);
    setNotice(`正在固化“${procurementEventLabels[eventType] ?? eventType}”证据…`);
    try {
      const response = await fetch(`/backend/v1/procurement/sample-orders/${order.id}/events`, { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${order.product.sku} 已更新：${procurementStatusLabels[result.status] ?? result.status}` : result.detail ?? "样品进度提交失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录样品进度，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function loadBackupOptions(orderId: string) {
    setProcurementBusy(orderId);
    try {
      const response = await fetch(`/backend/v1/procurement/sample-orders/${orderId}/backup-options`, { cache: "no-store" });
      const result = await response.json();
      if (response.ok) {
        setBackupOptions((current) => ({ ...current, [orderId]: result.options }));
        setNotice(result.options.length ? `已找到 ${result.options.length} 个正 CM3 备用方案，切换仍需重新审批` : "没有满足正 CM3 条件的备用供应商");
      } else setNotice(result.detail ?? "备用方案读取失败");
    } catch { setNotice("无法读取备用供应商，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function requestBackupProcurement(order: SampleOrder, option: BackupOption) {
    const key = `${order.id}:${option.offer.id}`;
    const rationale = (backupRationales[key] ?? "").trim();
    if (!rationale) { setNotice("备用供应商切换必须填写明确理由"); return; }
    setProcurementBusy(order.id);
    try {
      const response = await fetch("/backend/v1/sourcing/procurement-candidates", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: order.product_id, offer_id: option.offer.id, scenario_id: option.scenario.id, quantity: Math.max(order.quantity, option.offer.min_order_quantity), rationale: `备用切换：${rationale}` }),
      });
      const result = await response.json();
      setNotice(response.ok ? `备用方案已进入全新双人审批：${result.id}` : result.detail ?? "备用方案提交失败");
      if (response.ok) await load();
    } catch { setNotice("无法提交备用方案审批，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  const toolCount = Object.values(health).filter((item) => item.status === "ok").length;
  const readySkuCount = skuReadiness.filter((item) => item.ready_for_validation).length;
  const pendingProcurementApprovals = approvals.filter((item) => item.action === "procurement.place_order" && item.status === "pending").length;
  const approvedWithoutSample = approvals.filter((item) => item.action === "procurement.place_order" && item.status === "approved" && !sampleOrders.some((order) => order.approval_id === item.id));

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">K</div>
          <div><strong>KJDS</strong><span>俄罗斯经营系统</span></div>
        </div>
        <nav>
          {nav.map(([Icon, label, active]) => (
            <button className={active ? "active" : ""} key={label}><Icon size={19} /><span>{label}</span>{active && <ChevronRight size={16} />}</button>
          ))}
        </nav>
        <div className="sidebar-status">
          <span className="pulse" />
          <div><strong>14天影子运行</strong><span>只建议，不执行高风险动作</span></div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><p className="eyebrow">OZON · RUSSIA</p><h1>经营指挥中心</h1></div>
          <button className="refresh" onClick={() => load()}><RefreshCw size={17} />刷新状态</button>
        </header>

        <section className="hero">
          <div>
            <span className="hero-tag"><Sparkles size={15} />核心目标：单品净利润 CM3</span>
            <h2>先用真实数据跑通 3 个 SKU，<br />再把成功打法复制成规模。</h2>
            <p>系统会追踪证据、利润、内容和实验结果；缺失数据会明确提示，不允许 AI 编造。</p>
          </div>
          <form className="upload" onSubmit={upload}>
            <FileUp size={23} />
            <label htmlFor="ozon-file">导入 Ozon 经营数据</label>
            <span>支持 CSV / XLSX，重复文件不会重复入库</span>
            <input id="ozon-file" name="file" type="file" accept=".csv,.xlsx" />
            <button disabled={uploading}>{uploading ? "正在导入…" : "选择文件并导入"}</button>
          </form>
        </section>

        <div className="notice"><Activity size={17} /><span>{notice}</span></div>

        <section className="gate-overview">
          <div className="gate-overview-head">
            <div><p className="eyebrow">REALITY GATE</p><h3>G0–G1 真实准入状态</h3></div>
            <span className={gateReadiness?.status === "ready_for_review" ? "gate ready" : "gate blocked"}>
              {gateReadiness?.status === "ready_for_review" ? "等待人工放行" : "等待真实输入"}
            </span>
          </div>
          {gateReadiness ? <div className="requirement-grid">
            {gateReadiness.requirements.map((item) => <article className={item.ready ? "requirement ready" : "requirement"} key={item.id}>
              <div><span>{item.id}</span><b>{item.current}/{item.target}</b></div>
              <strong>{item.title}</strong>
              <small>{item.ready ? "证据条件已满足，仍需阶段门人工复核" : item.next_action}</small>
            </article>)}
          </div> : <div className="gate-loading">正在读取阶段门事实…</div>}
          <form className="gate-evidence-upload" onSubmit={uploadGateEvidence}>
            <div><strong>补充阶段门证据</strong><small>原文件将哈希固化并自动链接，不覆盖历史。</small></div>
            <select name="requirement_id" aria-label="阶段门证据类型" defaultValue="" required>
              <option value="" disabled>选择证据类型</option>
              <option value="GOV-001">负责人、审批人与风险预算</option>
              <option value="OZN-001">Ozon 账户、权限与收款路径</option>
            </select>
            <input name="gate_file" aria-label="阶段门证据文件" type="file" required />
            <button disabled={gateUploading}>{gateUploading ? "正在固化…" : "提交证据"}</button>
          </form>
        </section>

        <section className="sku-intake-panel">
          <div className="panel-title"><div><p className="eyebrow">SKU EPISODE INTAKE</p><h3>候选 SKU 一站式录入</h3></div><span className="badge">草稿 · 需人工审核</span></div>
          <form className="sku-intake" onSubmit={uploadSkuEpisode}>
            <div className="intake-basic">
              <label>SKU<input name="sku" placeholder="例如 RU-001" required /></label>
              <label>商品名称<input name="product_name" placeholder="使用可稳定识别的商品名称" required /></label>
            </div>
            <div className="intake-passports">
              <details open>
                <summary><span>1</span><strong>商品 Passport</strong><small>材料、用途、产地、重量与尺寸</small></summary>
                <div className="intake-fields">
                  <label>材料<input name="material" required /></label><label>用途<input name="intended_use" required /></label>
                  <label>原产国<input name="country_of_origin" defaultValue="CN" required /></label><label>重量 kg<input name="weight_kg" type="number" min="0.001" step="0.001" required /></label>
                  <label>长 cm<input name="length_cm" type="number" min="0" step="0.1" required /></label><label>宽 cm<input name="width_cm" type="number" min="0" step="0.1" required /></label>
                  <label>高 cm<input name="height_cm" type="number" min="0" step="0.1" required /></label><label>商品证据<input name="product_evidence" type="file" required /></label>
                </div>
              </details>
              <details open>
                <summary><span>2</span><strong>俄罗斯合规 Passport</strong><small>先记录事实与未知项，审核人再作结论</small></summary>
                <div className="intake-fields">
                  <label>HS Code<input name="hs_code" required /></label><label>EAC 要求<input name="eac_requirement" defaultValue="unknown" required /></label>
                  <label>诚实标要求<input name="chestny_znak_requirement" defaultValue="unknown" required /></label><label>俄文标签<input name="russian_labeling" defaultValue="unknown" required /></label>
                  <label>知识产权状态<input name="ip_status" defaultValue="review_required" required /></label><label>运输限制<input name="transport_restrictions" defaultValue="unknown" required /></label>
                  <label>可售状态<input name="sellability" defaultValue="pending_review" required /></label><label>合规证据<input name="compliance_evidence" type="file" required /></label>
                  <label className="wide">EAEU 规则依据（每行一条）<textarea name="eaeu_rules" required /></label>
                </div>
              </details>
              <details open>
                <summary><span>3</span><strong>样品质量 Passport</strong><small>黄金样、验货计划与包装测试</small></summary>
                <div className="intake-fields">
                  <label>黄金样编号<input name="golden_sample_ref" required /></label><label>包装测试<input name="packaging_test" defaultValue="pending" required /></label>
                  <label>质量证据<input name="quality_evidence" type="file" required /></label><label className="wide">验货项目（每行一条）<textarea name="inspection_plan" required /></label>
                </div>
              </details>
            </div>
            <div className="intake-submit"><p>提交只建立可追溯草稿，不代表合规批准、采购授权或上架放行。</p><button disabled={skuUploading}>{skuUploading ? "正在建立…" : "建立 SKU Episode"}</button></div>
          </form>
        </section>

        <section className="passport-review-panel">
          <div className="panel-title">
            <div><p className="eyebrow">HUMAN REVIEW</p><h3>Passport 人工审核</h3></div>
            <span className={passportReviews.length ? "badge" : "gate ready"}>{passportReviews.length ? `${passportReviews.length} 项待审` : "队列已清空"}</span>
          </div>
          {passportReviews.length ? <div className="review-grid">{passportReviews.map((item) => {
            const key = item.passport.id;
            const busy = reviewingKey === key;
            return <article className="review-card" key={key}>
              <div className="review-head">
                <div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div>
                <span>{passportLabels[item.passport.kind]} · V{item.passport.version}</span>
              </div>
              <div className="fact-list">{Object.entries(item.passport.facts).filter(([name]) => name !== "decision").map(([name, value]) => <div key={name}><span>{name}</span><b>{typeof value === "object" ? JSON.stringify(value) : String(value)}</b></div>)}</div>
              <div className="review-evidence"><ShieldCheck size={14} /><span>{item.passport.evidence.length} 份不可变证据</span>{item.passport.missing_fields.length ? <b>缺少 {item.passport.missing_fields.join("、")}</b> : <b>必填事实完整</b>}</div>
              <label>审核说明<textarea value={reviewNotes[key] ?? ""} onChange={(event) => setReviewNotes((current) => ({ ...current, [key]: event.target.value }))} placeholder="记录核查依据；阻断时必须填写原因" /></label>
              <div className="review-actions">
                <button className="reject" disabled={busy} onClick={() => reviewPassport(item, "blocked")}>阻断并退回</button>
                <button className="approve" disabled={busy || item.passport.missing_fields.length > 0} onClick={() => reviewPassport(item, "approved")}>{busy ? "提交中…" : "批准 Passport"}</button>
              </div>
            </article>;
          })}</div> : <div className="empty"><CheckCircle2 size={25} /><strong>没有待审核 Passport</strong><p>新的 SKU Episode 提交后会自动进入这里。</p></div>}
        </section>

        <section className="sourcing-intake-panel">
          <div className="panel-title"><div><p className="eyebrow">THREE-QUOTE GATE</p><h3>三家供应商证据化比价</h3></div><span className="badge">{pendingProcurementApprovals} 项采购待审批</span></div>
          <form className="sourcing-intake" onSubmit={uploadSupplierComparison}>
            <div className="sourcing-common">
              <label>候选 SKU<select name="sourcing_product_id" required><option value="">选择 SKU</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
              <label>目标售价 RUB<input name="sale_price_rub" type="number" min="0.01" step="0.01" required /></label><label>RUB/CNY<input name="rub_per_cny" type="number" min="0.0001" step="0.0001" required /></label>
              <label>国际运费 CNY/kg<input name="international_freight" type="number" min="0" step="0.01" required /></label><label>包装 CNY<input name="packaging_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>尾程 CNY<input name="last_mile_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>关税率<input name="customs_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>平台费率<input name="platform_fee_rate" type="number" min="0" max="0.9999" step="0.0001" required /></label><label>广告率<input name="advertising_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>退货准备率<input name="return_reserve_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label><label>其他成本 CNY<input name="other_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>利润假设证据<input name="assumption_evidence" type="file" required /></label>
            </div>
            <div className="supplier-entry-grid">{[1, 2, 3].map((index) => <details open key={index}><summary><span>{index}</span><strong>供应商 {index}</strong><small>原始报价与实测条件</small></summary><div className="supplier-fields">
              <label>供应商标识<input name={`supplier_ref_${index}`} required /></label><label>来源平台<select name={`platform_${index}`} defaultValue="1688"><option value="1688">1688</option><option value="alibaba">Alibaba</option><option value="manual">线下/人工</option></select></label>
              <label>报价快照编号<input name={`external_id_${index}`} required /></label><label>商品标题<input name={`offer_title_${index}`} required /></label>
              <label className="wide">原始链接<input name={`source_url_${index}`} type="url" required /></label><label>币种<input name={`currency_${index}`} defaultValue="CNY" maxLength={3} required /></label>
              <label>单价<input name={`unit_price_${index}`} type="number" min="0.01" step="0.01" required /></label><label>兑 CNY 汇率<input name={`source_to_cny_rate_${index}`} type="number" min="0.0001" step="0.0001" defaultValue="1" required /></label>
              <label>MOQ<input name={`moq_${index}`} type="number" min="1" required /></label><label>重量 kg<input name={`supplier_weight_${index}`} type="number" min="0.001" step="0.001" required /></label>
              <label>长 cm<input name={`supplier_length_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label><label>宽 cm<input name={`supplier_width_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label>
              <label>高 cm<input name={`supplier_height_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label><label>国内物流/件<input name={`domestic_logistics_${index}`} type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label className="wide">报价证据<input name={`supplier_evidence_${index}`} type="file" required /></label>
            </div></details>)}</div>
            <div className="intake-submit"><p>三份报价和共同利润假设都会哈希固化；系统只生成比较与审批申请，不会自动采购。</p><button disabled={sourcingUploading}>{sourcingUploading ? "正在比较…" : "建立三家报价比较"}</button></div>
          </form>
        </section>

        {comparisons.length > 0 && <section className="comparison-panel">
          <div className="panel-title"><div><p className="eyebrow">SOURCING DECISION</p><h3>报价与 CM3 比较</h3></div><span className="gate ready">仅人工提交采购</span></div>
          {comparisons.map((comparison) => <div className="comparison-group" key={comparison.product.id}><div className="comparison-title"><strong>{comparison.product.sku} · {comparison.product.name}</strong><span>{comparison.supplier_count}/3 家供应商</span></div><div className="comparison-grid">{comparison.rows.map((row, index) => {
            const draft = procurementDrafts[row.offer.id] ?? { quantity: String(row.offer.min_order_quantity), rationale: "" };
            const passportReady = skuReadiness.find((item) => item.product.id === comparison.product.id)?.ready_for_validation;
            return <article className="comparison-card" key={row.offer.id}><div className="rank">#{index + 1}</div><strong>{row.offer.supplier_ref}</strong><small>{row.offer.platform} · {row.offer.unit_price} {row.offer.currency} · MOQ {row.offer.min_order_quantity}</small><div className="cm3"><span>预计 CM3</span><b>{row.scenario ? `${row.scenario.cm3_cny} CNY` : "缺少场景"}</b><small>{row.scenario ? `${(Number(row.scenario.cm3_rate) * 100).toFixed(1)}% · 保本价 ${row.scenario.break_even_price_rub} RUB` : ""}</small></div>
              <label>采购数量<input type="number" min={row.offer.min_order_quantity} value={draft.quantity} onChange={(event) => setProcurementDrafts((current) => ({ ...current, [row.offer.id]: { ...draft, quantity: event.target.value } }))} /></label>
              <label>选择理由<textarea value={draft.rationale} onChange={(event) => setProcurementDrafts((current) => ({ ...current, [row.offer.id]: { ...draft, rationale: event.target.value } }))} placeholder="为什么选择它，而不是另外两家？" /></label>
              <button disabled={!comparison.ready_for_procurement_review || !passportReady || !row.has_positive_cm3} onClick={() => requestProcurement(comparison, row)}>提交双人采购审批</button>{!passportReady && <em>需先批准三本 Passport</em>}
            </article>;
          })}</div></div>)}
        </section>}

        <section className="procurement-panel">
          <div className="panel-title">
            <div><p className="eyebrow">SAMPLE PROCUREMENT</p><h3>样品采购与供应商验证</h3></div>
            <span className="gate ready">每一步必须有证据</span>
          </div>
          <div className="procurement-guardrail"><ShieldCheck size={17} /><p><strong>真实付款不会自动执行。</strong><span>已批准候选只能建立样品跟踪；供应商切换会生成一项新的双人审批。</span></p></div>
          {approvedWithoutSample.length > 0 && <div className="approved-order-queue">
            <strong>已通过双人审批，等待建立样品单</strong>
            {approvedWithoutSample.map((approval) => <button key={approval.id} disabled={procurementBusy === approval.id} onClick={() => createSampleOrder(approval.id)}>
              {procurementBusy === approval.id ? "正在建立…" : `建立样品单 · ${String(approval.payload.quantity ?? "-")} 件`}
            </button>)}
          </div>}
          {sampleOrders.length ? <div className="sample-order-grid">{sampleOrders.map((order) => {
            const performance = supplierPerformance.find((item) => item.supplier_ref === order.supplier_ref);
            const terminal = order.next_events.length === 0;
            return <article className="sample-order-card" key={order.id}>
              <div className="sample-order-head"><div><strong>{order.product.sku} · {order.product.name}</strong><small>{order.supplier_ref} · {order.quantity} 件 · {order.unit_price} {order.currency}/件</small></div><span className={`sample-state ${terminal ? "terminal" : ""}`}>{procurementStatusLabels[order.status] ?? order.status}</span></div>
              <div className="sample-progress">{["确认", "发货", "签收", "验货", "定样"].map((label, index) => <span className={order.events.length > index ? "done" : ""} key={label}>{label}</span>)}</div>
              <div className="sample-facts">
                <div><span>证据事件</span><b>{order.events.length}</b></div><div><span>供应商评分</span><b>{performance?.score ? `${performance.score} 分` : "待形成"}</b></div><div><span>样品成功</span><b>{performance ? `${performance.completed_sample_count}/${performance.sample_order_count}` : "-"}</b></div>
              </div>
              {order.events.length > 0 && <details className="sample-timeline"><summary>查看不可变进度记录</summary><ol>{order.events.map((item) => <li key={item.id}><span>{item.sequence}</span><div><strong>{procurementEventLabels[item.event_type] ?? item.event_type}</strong><small>{new Date(item.effective_at).toLocaleString("zh-CN")} · 证据 {item.evidence_id.slice(-8)}</small></div></li>)}</ol></details>}
              {!terminal && <form className="sample-event-form" onSubmit={(event) => recordSampleEvent(event, order)}>
                <strong>下一步：{order.status === "inspected" ? "形成样品决定" : procurementEventLabels[order.next_events.find((item) => item !== "cancelled") ?? ""]}</strong>
                {order.status === "approved_to_order" && <div className="sample-event-fields"><label>供应商订单号<input name="supplier_order_ref" required /></label><label>承诺交付时间<input name="promised_delivery_at" type="datetime-local" required /></label></div>}
                {order.status === "order_confirmed" && <div className="sample-event-fields"><label>物流单号<input name="tracking_ref" required /></label><label>承运商<input name="carrier" required /></label></div>}
                {order.status === "shipped" && <div className="sample-event-fields"><label>签收数量<input name="received_quantity" type="number" min="0" max={order.quantity} defaultValue={order.quantity} required /></label><label>破损数量<input name="damaged_quantity" type="number" min="0" defaultValue="0" required /></label></div>}
                {(order.status === "received" || order.status === "rework_required") && <div className="sample-event-fields"><label>验货数量<input name="inspected_quantity" type="number" min="1" max={order.quantity} defaultValue={order.quantity} required /></label><label>通过数量<input name="passed_quantity" type="number" min="0" max={order.quantity} defaultValue={order.quantity} required /></label><label>缺陷数<input name="defect_count" type="number" min="0" defaultValue="0" required /></label><label>验货结论<select name="inspection_result" defaultValue="passed"><option value="passed">通过</option><option value="failed">不通过</option><option value="rework">需返工</option></select></label></div>}
                {order.status === "inspected" && <div className="sample-event-fields"><label>样品决定<select name="sample_decision" defaultValue="golden_sample_approved"><option value="golden_sample_approved">批准为黄金样</option><option value="rework_required">要求返工</option><option value="sample_rejected">淘汰供应商样品</option></select></label><label>黄金样编号 / 决定原因<input name="decision_detail" required /></label></div>}
                <label className="sample-evidence">本步原始证据<input name="event_evidence" type="file" required /></label>
                <button disabled={procurementBusy === order.id}>{procurementBusy === order.id ? "正在固化…" : "提交进度与证据"}</button>
              </form>}
              <div className="backup-control">
                <button className="secondary" disabled={procurementBusy === order.id} onClick={() => loadBackupOptions(order.id)}>查看备用供应商</button>
                <small>只提供建议，不自动切换</small>
              </div>
              {backupOptions[order.id] && <div className="backup-list">{backupOptions[order.id].length ? backupOptions[order.id].map((option) => {
                const rationaleKey = `${order.id}:${option.offer.id}`;
                return <div key={option.offer.id}><div><strong>{option.offer.supplier_ref}</strong><small>{option.offer.unit_price} {option.offer.currency} · MOQ {option.offer.min_order_quantity} · CM3 {option.scenario.cm3_cny} CNY</small><input value={backupRationales[rationaleKey] ?? ""} onChange={(event) => setBackupRationales((current) => ({ ...current, [rationaleKey]: event.target.value }))} placeholder="填写切换理由" /></div><button disabled={procurementBusy === order.id} onClick={() => requestBackupProcurement(order, option)}>重新提交审批</button></div>;
              }) : <p>暂无正 CM3 备用方案。</p>}</div>}
            </article>;
          })}</div> : <div className="empty"><Boxes size={25} /><strong>还没有受控样品单</strong><p>三家比价通过、Passport 批准并完成双人采购审批后，才会进入这里。</p></div>}
          {supplierPerformance.length > 0 && <div className="supplier-scoreboard"><strong>供应商实绩榜</strong><div>{supplierPerformance.map((item) => <article key={item.supplier_ref}><span>{item.supplier_ref}</span><b>{item.score ? `${item.score} 分` : "数据不足"}</b><small>质量 {item.quality_yield ? `${(Number(item.quality_yield) * 100).toFixed(0)}%` : "-"} · 准时 {item.on_time_rate ? `${(Number(item.on_time_rate) * 100).toFixed(0)}%` : "-"} · {item.evidence_count} 份证据</small></article>)}</div></div>}
        </section>

        <section className="metrics">
          <article><span className="metric-icon green"><CircleDollarSign /></span><div><p>CM3 净利润</p><strong>待导入</strong><small>真实费用齐全后计算</small></div></article>
          <article><span className="metric-icon blue"><ShieldCheck /></span><div><p>SKU 准入门</p><strong>{readySkuCount} / 3</strong><small>{skuReadiness.length ? "三类护照全部批准才可上线" : "先录入 3 个真实候选 SKU"}</small></div></article>
          <article><span className="metric-icon violet"><Waypoints /></span><div><p>全球货源平台</p><strong>{sourceConnectors.length}</strong><small>{offers.length} 个商品报价已入库</small></div></article>
          <article><span className="metric-icon amber"><CheckCircle2 /></span><div><p>工具连接</p><strong>{toolCount} / 4</strong><small>Ollama · ComfyUI · n8n · Firecrawl</small></div></article>
        </section>

        <section className="grid">
          <article className="panel agents">
            <div className="panel-title"><div><p className="eyebrow">AI SQUAD</p><h3>Agent 团队</h3></div><span className="badge">影子模式</span></div>
            <div className="agent-list">
              {["市场分析", "商品策略", "俄语 Listing", "内容生产", "运营建议", "利润审计", "质量检查"].map((name, index) => (
                <div className="agent" key={name}><span>{index + 1}</span><div><strong>{name}</strong><small>{index < 2 ? "等待数据" : "等待上游任务"}</small></div><Clock3 size={16} /></div>
              ))}
            </div>
          </article>

          <article className="panel">
            <div className="panel-title"><div><p className="eyebrow">INFRASTRUCTURE</p><h3>现有工具状态</h3></div><Database size={20} /></div>
            <div className="health-list">
              {(["ollama", "comfyui", "n8n", "firecrawl"] as const).map((key) => {
                const item = health[key];
                const ok = item?.status === "ok";
                return <div key={key}><span className={ok ? "health-dot ok" : "health-dot"} /><div><strong>{key === "ollama" ? "Ollama 本地模型" : key === "comfyui" ? "ComfyUI 内容引擎" : key === "n8n" ? "n8n 内部自动化" : "Firecrawl 数据采集"}</strong><small>{item?.detail || (ok ? "连接正常" : "等待连接")}</small></div><span className={ok ? "state ok" : "state"}>{ok ? "在线" : "离线"}</span></div>;
              })}
            </div>
            <div className="license-note"><ShieldCheck size={18} /><p><strong>商业授权保护已开启</strong><span>授权不明的模型默认不能参与生产。</span></p></div>
          </article>

          <article className="panel recommendations">
            <div className="panel-title"><div><p className="eyebrow">DECISIONS</p><h3>最新经营建议</h3></div><BarChart3 size={20} /></div>
            {recommendations.length ? recommendations.slice(0, 4).map((item) => (
              <div className="recommendation" key={item.id}><span className="risk">{item.risk}</span><div><strong>{item.action}</strong><small>{item.agent} · {item.status}</small></div><b>{item.expected_cm3_delta ? `¥${item.expected_cm3_delta}` : "待评估"}</b></div>
            )) : <div className="empty"><TriangleAlert size={25} /><strong>还没有可验证的建议</strong><p>导入经营数据后，Agent 才会生成有证据的建议。</p></div>}
          </article>

          <article className="panel sku-gates">
            <div className="panel-title"><div><p className="eyebrow">GATE 0–1</p><h3>三 SKU 准入门</h3></div><ShieldCheck size={20} /></div>
            {skuReadiness.length ? <div className="sku-list">{skuReadiness.map((item) => {
              const approved = item.passports.filter((passport) => passport.status === "approved").length;
              const blocked = item.passports.some((passport) => passport.status === "blocked");
              const next = item.passports.find((passport) => passport.status !== "approved");
              return <div className="sku-card" key={item.product.id}>
                <div className="sku-card-head"><div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div><span className={blocked ? "gate blocked" : item.ready_for_validation ? "gate ready" : "gate"}>{blocked ? "已阻断" : item.ready_for_validation ? "可验证" : `${approved}/3`}</span></div>
                <div className="passport-row">{item.passports.map((passport) => <span className={passport.status} key={passport.kind}>{passportLabels[passport.kind]}</span>)}</div>
                <p>{item.ready_for_validation ? "资料、合规和样品质量均已通过人工批准。" : blocked ? "存在否决结论，停止采购和上架。" : next ? `下一步：补齐${passportLabels[next.kind]}（缺 ${next.missing_fields.length} 项）` : "等待审核。"}</p>
              </div>;
            })}</div> : <div className="empty"><Boxes size={25} /><strong>尚未录入真实候选 SKU</strong><p>下一步先确定 3 个 SKU，再逐个补齐商品、合规和质量护照。</p></div>}
          </article>

          <article className="panel source-platforms">
            <div className="panel-title"><div><p className="eyebrow">GLOBAL SOURCING</p><h3>货源连接器</h3></div><Waypoints size={20} /></div>
            <div className="platform-chips">
              {sourceConnectors.map((item) => <span key={item.platform}>{item.platform}<small>{item.ingestion}</small></span>)}
            </div>
            <div className="license-note"><Database size={18} /><p><strong>Supabase 数据底座</strong><span>报价、证据、利润方案和上架草稿统一留痕。</span></p></div>
          </article>
        </section>
      </section>
    </main>
  );
}
