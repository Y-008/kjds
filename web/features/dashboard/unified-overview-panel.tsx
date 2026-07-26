import {
  ArrowUpRight,
  BarChart3,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Database,
  FileCheck2,
  Gauge,
  ImageIcon,
  PackageSearch,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Store,
  TrendingUp,
  Waypoints,
  Workflow,
} from "lucide-react";
import type { OperatingAnalyticsSnapshot } from "./contracts";
import type { DashboardModel } from "./use-dashboard-controller";
import type { WorkspaceId } from "./dashboard-workspaces";

type Props = {
  model: DashboardModel;
  onNavigate: (workspace: WorkspaceId) => void;
};

const workspaceIds = new Set<WorkspaceId>([
  "overview",
  "data",
  "research",
  "products",
  "sourcing",
  "growth",
  "finance",
  "science",
  "governance",
  "system",
]);

const stageStatus = {
  verified: { label: "已有真源", tone: "verified" },
  in_progress: { label: "进行中", tone: "progress" },
  blocked: { label: "被门禁阻断", tone: "blocked" },
  no_data: { label: "缺真实数据", tone: "empty" },
} as const;

const operatingModes = [
  {
    id: "guided_foundation",
    label: "新手引导",
    eyebrow: "GUIDED",
    description: "一次只给一个可验证动作，先连接账户、原件和成本。",
    control: "不跳过证据与审批",
  },
  {
    id: "distribution",
    label: "铺货模式",
    eyebrow: "DISTRIBUTION",
    description: "批量采集、去重、完整度检查和淘汰队列，先预览差异。",
    control: "批量不等于批量直发",
  },
  {
    id: "existing_listing_refinement",
    label: "精品 / 精细化",
    eyebrow: "REFINEMENT",
    description: "围绕真实 CM3、价格带、内容、转化和有上限广告实验。",
    control: "当前建议",
  },
  {
    id: "store_group",
    label: "店群模式",
    eyebrow: "STORE GROUP",
    description: "店铺身份、预算与风险隔离后，再做商品和资金组合汇总。",
    control: "禁止共享平台凭证",
  },
  {
    id: "brand",
    label: "品牌运营",
    eyebrow: "BRAND",
    description: "统一权利、素材、俄语表达和长期资产，追踪复购与声誉。",
    control: "生成素材必须核权",
  },
] as const;

const capabilityCards: Array<{
  id: WorkspaceId;
  title: string;
  description: string;
  icon: typeof Store;
}> = [
  { id: "data", title: "原件与数据", description: "Ozon 导出、API 原响应、Evidence 与复核", icon: Database },
  { id: "research", title: "市场与候选", description: "需求、同行、行业、关键词与三候选", icon: PackageSearch },
  { id: "sourcing", title: "1688 与物流", description: "RFQ、三报价、计费重和十五项成本", icon: Waypoints },
  { id: "products", title: "内容与 Listing", description: "有权原图、视频、俄语内容和 QA", icon: Sparkles },
  { id: "growth", title: "增长实验", description: "价格、内容、转化、广告上限与止损", icon: TrendingUp },
  { id: "finance", title: "利润与到账", description: "CM3、费用、FX、结算、银行和对账", icon: CircleDollarSign },
  { id: "science", title: "AI 决策", description: "假设、反方、因果实验和结果记忆", icon: Bot },
  { id: "governance", title: "审批与执行", description: "双人审批、一次许可、回读与回滚", icon: ShieldCheck },
];

function stageWorkspace(value: string): WorkspaceId {
  return workspaceIds.has(value as WorkspaceId) ? value as WorkspaceId : "overview";
}

function money(value: string | null, currency: string | null) {
  if (value === null) return "暂无";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return `${value} ${currency ?? ""}`.trim();
  return `${numeric.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${currency ?? ""}`.trim();
}

function observedAt(value: string | null) {
  if (!value) return "尚无真源时间";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString("zh-CN");
}

function shortId(value: string | null | undefined) {
  if (!value) return "—";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function pricePosition(value: string | null, ceiling: number) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || ceiling <= 0) return 0;
  return Math.max(0, Math.min(100, numeric / ceiling * 100));
}

function EmptyAnalytics() {
  return (
    <div className="workspace-page overview-page">
      <section className="analytics-empty-state">
        <Workflow size={30} />
        <strong>经营分析快照正在加载</strong>
        <p>页面不会用演示数据代替 readiness、目录、供应链、订单或财务真源。</p>
      </section>
    </div>
  );
}

function ListingCard({ analytics }: { analytics: OperatingAnalyticsSnapshot }) {
  const listing = analytics.focal_listing;
  if (!listing) {
    return (
      <article className="live-listing-card no-listing">
        <PackageSearch size={34} />
        <strong>还没有可复验 Ozon Listing</strong>
        <p>先完成只读商品响应和目录导入，驾驶舱才会显示商品图、价格、库存与内容。</p>
      </article>
    );
  }
  const heroImage = listing.image_references[0];
  return (
    <article className="live-listing-card">
      <div className="listing-image-stage">
        {heroImage ? <img src={heroImage} alt={listing.name} /> : <ImageIcon size={46} />}
        <span className="listing-live-status"><span /> {listing.status_name ?? listing.status ?? "状态未知"}</span>
        <span className="listing-rights">Ozon 外部引用 · 未核权</span>
      </div>
      <div className="listing-card-body">
        <div className="listing-identifiers">
          <span>OFFER {listing.offer_id}</span>
          <span>SKU {listing.marketplace_sku ?? "—"}</span>
        </div>
        <h3>{listing.name}</h3>
        <div className="listing-commerce">
          <div><small>目录售价</small><strong>{money(listing.price, listing.currency_code)}</strong></div>
          <div><small>可售库存</small><strong>{listing.available_stock ?? "—"} <em>件</em></strong></div>
          <div><small>媒体</small><strong>{listing.image_reference_count} <em>图</em> · {listing.video_reference_count} <em>视频</em></strong></div>
        </div>
        <footer>
          <span>真源 {shortId(listing.source_evidence_id)}</span>
          <span>{observedAt(listing.observed_at)}</span>
        </footer>
      </div>
    </article>
  );
}

export function UnifiedOverviewPanel({ model, onNavigate }: Props) {
  const analytics = model.operatingAnalytics;
  if (!analytics) return <EmptyAnalytics />;

  const listing = analytics.focal_listing;
  const pipelineMax = Math.max(1, ...analytics.pipeline.map((item) => item.value));
  const priceCeiling = Math.max(
    1,
    Number(listing?.old_price ?? 0),
    Number(listing?.price ?? 0),
    Number(listing?.min_price ?? 0),
  );

  return (
    <div className="workspace-page overview-page">
      <section className="overview-command-hero">
        <div className="command-hero-copy">
          <span className="hero-kicker"><Store size={15} /> OZON RU · 真实经营指挥舱</span>
          <h2>把一个真实商品，推进到<br />可验证利润与可控增长。</h2>
          <p>这不是“AI 自动出单”的演示。系统把店铺、1688、内容、价格、广告、订单和结算放进同一条证据链，明确告诉你现在走到哪一步、缺什么、谁来处理。</p>
          <div className="playbook-banner">
            <span><Gauge size={18} /></span>
            <div>
              <small>当前建议运营方式 · 仅建议</small>
              <strong>{analytics.recommended_playbook.label}</strong>
              <p>{analytics.recommended_playbook.reasons.join("；")}</p>
            </div>
          </div>
          <div className="hero-actions">
            <button type="button" onClick={() => onNavigate("growth")}>进入现有商品诊断 <ArrowUpRight size={16} /></button>
            <button className="secondary" type="button" onClick={() => onNavigate("sourcing")}>推进 1688 三报价</button>
          </div>
          <div className="snapshot-trace">
            <ShieldCheck size={14} />
            <span>快照 {shortId(analytics.snapshot_sha256)} · 真源截至 {observedAt(analytics.source_as_of)}</span>
          </div>
        </div>
        <ListingCard analytics={analytics} />
      </section>

      <section className="command-kpis" aria-label="真实经营关键数据">
        <article><span className="kpi-icon blue"><Store size={19} /></span><div><small>店铺目录 / 已绑定</small><strong>{analytics.summary.catalog_items}<em> / {analytics.summary.bound_listings}</em></strong><p>来自逐字节复验的 Ozon 目录</p></div></article>
        <article><span className="kpi-icon green"><PackageSearch size={19} /></span><div><small>当前可售库存</small><strong>{analytics.summary.available_stock}<em> 件</em></strong><p>不等于已销售或可盈利</p></div></article>
        <article><span className="kpi-icon violet"><ImageIcon size={19} /></span><div><small>目录媒体引用</small><strong>{analytics.summary.external_image_references}<em> 图</em> · {analytics.summary.external_video_references}<em> 视频</em></strong><p>均为未核权外部引用</p></div></article>
        <article><span className="kpi-icon amber"><ShieldAlert size={19} /></span><div><small>当前经营阻断</small><strong>{analytics.summary.gate_blockers}</strong><p>来自服务端 readiness</p></div></article>
        <article><span className="kpi-icon rose"><Waypoints size={19} /></span><div><small>RFQ / 已核验发送</small><strong>{analytics.summary.rfq_packages}<em> / {analytics.summary.verified_dispatch_proofs}</em></strong><p>复制、发送、回复、报价严格分离</p></div></article>
        <article><span className="kpi-icon slate"><FileCheck2 size={19} /></span><div><small>正式财务分录</small><strong>{analytics.summary.formal_finance_entries}</strong><p>没有就保持 0，不用估算冒充</p></div></article>
      </section>

      <section className="operating-flow-board">
        <div className="section-heading flow-heading">
          <div>
            <span>REAL OPERATING FLOW · 10 STEPS</span>
            <h3>从店铺同步到利润到账的完整流转</h3>
            <p>每一格可下钻到实际工作区；进度来自对象计数或稳定 requirement，不是页面自评。</p>
          </div>
          <div className="flow-legend"><span className="verified" />已有真源 <span className="blocked" />门禁阻断 <span className="empty" />缺真实数据</div>
        </div>
        <div className="operating-flow-track">
          {analytics.stages.map((stage) => {
            const status = stageStatus[stage.status];
            return (
              <button
                className={`flow-stage ${status.tone}`}
                type="button"
                key={stage.id}
                onClick={() => onNavigate(stageWorkspace(stage.workspace))}
              >
                <header>
                  <span>{stage.step}</span>
                  <b>{status.label}</b>
                </header>
                <strong>{stage.label}</strong>
                <div className="flow-progress">
                  <span style={{ width: `${stage.progress_percent}%` }} />
                </div>
                <div className="flow-count"><b>{stage.current}</b><span> / {stage.target}</span></div>
                {stage.facts.length ? <small>{stage.facts.join(" · ")}</small> : <small>来源 {stage.source_ids.map(shortId).join(" · ") || "待建立"}</small>}
                <p>{stage.next_action}</p>
                <ArrowUpRight size={15} />
              </button>
            );
          })}
        </div>
      </section>

      <section className="analytics-board-grid">
        <article className="analytics-card coverage-chart-card">
          <div className="section-heading">
            <div><span>FACT COVERAGE</span><h3>经营事实覆盖图</h3><p>条形只表示对应 requirement 的 current / target。</p></div>
            <BarChart3 size={20} />
          </div>
          <div className="coverage-chart">
            {analytics.coverage.map((item) => (
              <div className="coverage-row" key={item.id}>
                <div><strong>{item.label}</strong><span>{item.current}/{item.target} · {item.unit}</span></div>
                <div className="coverage-bar"><span style={{ width: `${item.percent}%` }} /></div>
                <b>{item.percent}%</b>
              </div>
            ))}
          </div>
          <footer><ShieldCheck size={14} /> 0% 是明确缺口，不是系统故障；100% 也不自动授予平台写入。</footer>
        </article>

        <article className="analytics-card pipeline-chart-card">
          <div className="section-heading">
            <div><span>OBJECT PIPELINE</span><h3>经营对象流转链</h3><p>各行单位不同，因此不计算伪转化率。</p></div>
            <Workflow size={20} />
          </div>
          <div className="pipeline-chart">
            {analytics.pipeline.map((item) => (
              <div className="pipeline-row" key={item.id}>
                <span>{item.label}</span>
                <div><i style={{ width: `${item.value === 0 ? 2 : Math.max(10, item.value / pipelineMax * 100)}%` }} /></div>
                <strong>{item.value}<small> {item.unit}</small></strong>
              </div>
            ))}
          </div>
          <div className="pipeline-no-history"><BarChart3 size={15} /><span>暂无可复验历史序列：不绘制虚假 GMV、订单或利润趋势。</span></div>
        </article>
      </section>

      <section className="listing-intelligence-grid">
        <article className="analytics-card listing-analysis-card">
          <div className="section-heading">
            <div><span>FOCAL LISTING · TRUE DATA</span><h3>真实商品数据诊断</h3><p>价格、库存与媒体来自当前 Ozon 目录快照；竞品与 CM3 缺失会直接暴露。</p></div>
            <button type="button" onClick={() => onNavigate("growth")}>完整诊断 <ArrowUpRight size={14} /></button>
          </div>
          {listing ? (
            <>
              <div className="listing-analysis-body">
                <div className="listing-gallery">
                  {listing.image_references.slice(0, 4).map((src, index) => <img src={src} alt={`${listing.name} 图 ${index + 1}`} key={src} />)}
                  {!listing.image_references.length && <div><ImageIcon size={28} />没有图片引用</div>}
                </div>
                <div className="listing-fact-table">
                  <div><span>商品档案</span><strong>{listing.canonical_product_id ? "已绑定" : "未绑定"}</strong></div>
                  <div><span>三类 Passport</span><strong className={listing.passports_ready ? "positive" : "negative"}>{listing.passports_ready ? "已通过" : "缺失"}</strong></div>
                  <div><span>真实供应商报价</span><strong>{listing.supplier_count} / 3</strong></div>
                  <div><span>完整正 CM3 场景</span><strong>{listing.complete_profit_scenario_count}</strong></div>
                  <div><span>有权图片角色</span><strong>{listing.approved_media_roles} / {listing.required_media_roles || 7}</strong></div>
                  <div><span>增长快照</span><strong className={listing.growth_observation ? "positive" : "negative"}>{listing.growth_observation ? "已有真源" : "尚未建立"}</strong></div>
                </div>
              </div>
              <div className="price-band">
                <div className="price-band-head">
                  <strong>目录价格带</strong>
                  <span>币种 {listing.currency_code ?? "未知"} · 不等于同行市场价</span>
                </div>
                <div className="price-axis">
                  <span className="price-line" />
                  <i className="price-dot minimum" style={{ left: `${pricePosition(listing.min_price, priceCeiling)}%` }}><b>最低价</b><small>{money(listing.min_price, listing.currency_code)}</small></i>
                  <i className="price-dot current" style={{ left: `${pricePosition(listing.price, priceCeiling)}%` }}><b>当前价</b><small>{money(listing.price, listing.currency_code)}</small></i>
                  <i className="price-dot old" style={{ left: `${pricePosition(listing.old_price, priceCeiling)}%` }}><b>原价</b><small>{money(listing.old_price, listing.currency_code)}</small></i>
                </div>
              </div>
            </>
          ) : <div className="overview-empty"><PackageSearch size={25} /><strong>尚无真实 Listing</strong></div>}
        </article>

        <article className="analytics-card next-action-card">
          <div className="section-heading">
            <div><span>AI NEXT BEST ACTION</span><h3>下一动作，不替你越权</h3><p>优先级和责任 Agent 来自统一只读经营简报。</p></div>
            <Bot size={20} />
          </div>
          <div className="next-action-list">
            {analytics.priority_items.slice(0, 4).map((item, index) => (
              <div key={item.id}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><small>{item.agent_name} · {item.source_id}</small><strong>{item.title}</strong><p>{item.next_action}</p></div>
              </div>
            ))}
          </div>
          <footer><ShieldAlert size={14} /><span>AI 不能自动选品、联系供应商、采购、改价、发布或投放。</span></footer>
        </article>
      </section>

      <section className="operating-mode-board">
        <div className="section-heading">
          <div><span>ONE CORE · FIVE OPERATING MODES</span><h3>同一事实与治理内核，适配不同卖家阶段</h3><p>模式改变关注点，不降低 Evidence、权限、审批、回读和止损要求。</p></div>
        </div>
        <div className="operating-mode-grid">
          {operatingModes.map((mode) => {
            const selected = mode.id === analytics.recommended_playbook.id;
            return (
              <article className={selected ? "selected" : ""} key={mode.id}>
                <span>{mode.eyebrow}</span>
                <div><strong>{mode.label}</strong>{selected && <b><CheckCircle2 size={12} /> 当前建议</b>}</div>
                <p>{mode.description}</p>
                <small><ShieldCheck size={12} /> {mode.control}</small>
              </article>
            );
          })}
        </div>
      </section>

      <section className="capability-map">
        <div className="section-heading">
          <div><span>OPERATING WORKSPACES</span><h3>所有前台功能都能从经营流下钻</h3><p>表单负责提交受控事实和申请；分析负责解释现状，不混在一起。</p></div>
        </div>
        <div className="capability-grid">
          {capabilityCards.map((item) => {
            const Icon = item.icon;
            return (
              <button type="button" onClick={() => onNavigate(item.id)} key={item.id}>
                <span className="capability-icon"><Icon size={20} /></span>
                <strong>{item.title}</strong>
                <p>{item.description}</p>
                <ArrowUpRight size={16} />
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
