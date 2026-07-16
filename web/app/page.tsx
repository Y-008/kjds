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
  const [skuReadiness, setSkuReadiness] = useState<ProductReadiness[]>([]);
  const [gateReadiness, setGateReadiness] = useState<GateReadiness | null>(null);
  const [uploading, setUploading] = useState(false);
  const [gateUploading, setGateUploading] = useState(false);
  const [skuUploading, setSkuUploading] = useState(false);
  const [notice, setNotice] = useState("等待第一份 Ozon 数据");

  const load = useCallback(async () => {
    const [healthResponse, recommendationResponse, connectorResponse, offersResponse, productsResponse, gateResponse] = await Promise.all([
      fetch("/backend/v1/integrations/health", { cache: "no-store" }),
      fetch("/backend/v1/recommendations", { cache: "no-store" }),
      fetch("/backend/v1/sourcing/connectors", { cache: "no-store" }),
      fetch("/backend/v1/sourcing/offers", { cache: "no-store" }),
      fetch("/backend/v1/products", { cache: "no-store" }),
      fetch("/backend/v1/operations/readiness", { cache: "no-store" }),
    ]);
    if (healthResponse.ok) setHealth(await healthResponse.json());
    if (recommendationResponse.ok) setRecommendations(await recommendationResponse.json());
    if (connectorResponse.ok) setSourceConnectors(await connectorResponse.json());
    if (offersResponse.ok) setOffers(await offersResponse.json());
    if (gateResponse.ok) setGateReadiness(await gateResponse.json());
    if (productsResponse.ok) {
      const products: { id: string }[] = await productsResponse.json();
      const readiness = await Promise.all(
        products.slice(0, 3).map(async (product) => {
          const response = await fetch(`/backend/v1/products/${product.id}/readiness`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ProductReadiness> : null;
        }),
      );
      setSkuReadiness(readiness.filter((item): item is ProductReadiness => item !== null));
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

  const toolCount = Object.values(health).filter((item) => item.status === "ok").length;
  const readySkuCount = skuReadiness.filter((item) => item.ready_for_validation).length;

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
