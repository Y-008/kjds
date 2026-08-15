"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Boxes,
  ChartNoAxesCombined,
  Factory,
  GitBranch,
  MapPinned,
  RefreshCw,
  ScanSearch,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { fetchJson } from "../../lib/fetch-json";

type CountSet = {
  observed: number;
  ozon_observed?: number;
  supplier_observed?: number;
  exact_identity_matched?: number;
  checkout_cost_eligible?: number;
  exact_matched: number;
  downside_positive: number;
  content_ready: number;
  pilot_ready: number;
  own_listings?: number;
  competitor_listings?: number;
  unique_exact_identities?: number;
  supplier_identity_cohort_size?: number;
  checkout_cost_cohort_size?: number;
  supplier_cohort_size?: number;
  fully_costed_candidates?: number;
  eligible_for_approval?: number;
  approval_allocation_selected?: number;
  approval_waitlist?: number;
  official_rule_ready?: number;
  unmatched_ozon?: number;
  unmatched_supplier?: number;
};

type CostCase = {
  revenue_cny: string | null;
  total_cost_cny: string | null;
  cm3_cny: string | null;
  cm3_rate: string | null;
  inventory_cash_cny: string | null;
  conservation_delta_cny: string | null;
  components: Array<{
    name: string;
    amount_cny: string;
    authority: string;
    evidence_id: string | null;
  }>;
};

type BatchCandidate = {
  candidate_id?: string;
  canonical_product_id?: string | null;
  candidate_key: string;
  fingerprint: string;
  rank: number;
  state: string;
  pilot_ready: boolean;
  eligible_for_approval?: boolean;
  pilot_selection?: {
    status: string;
    reason: string;
    semantics: string;
  };
  market: {
    title: string;
    variant_key: string;
    price: string;
    currency: string;
    source_url: string;
    signals: Record<string, unknown>;
    sales_is_actual: false;
    sales_semantics: string;
    revenue_scenario?: {
      kind: string;
      authority: string;
      unit_price: string;
      profit_floor_status: string;
    };
  };
  supply: {
    supplier_ref: string;
    variant_key: string;
    observed_checkout_price: string;
    currency: string;
    observed_quantity: number;
    moq: number | null;
    supplier_density: number;
    signals: Record<string, unknown>;
    counts_as_supplier_offer: false;
    counts_as_actual_cost: false;
  };
  economics: {
    baseline: CostCase;
    downside: CostCase;
    cost_evidence_complete: boolean;
    actual_profit: null;
    formal_cm3: null;
  };
  score: {
    total: string;
    market: string;
    supply: string;
    economics: string;
    evidence_confidence: string;
  };
  strategy: {
    classification: string;
    tactics?: string[];
    reason: string;
    budget: { inventory_units: string; advertising: string };
    promotion_gates: string[];
  };
  content: {
    russian_title: string | null;
    translation_required: boolean;
    selling_points: string[];
    detail_sections: string[];
    passport_ready: boolean;
    media_ready: boolean;
    content_ready: boolean;
  };
  variant_plan: {
    ready: boolean;
    parent_verified: boolean;
    checkpoints: Record<string, unknown>;
    settlement_cycles: number;
    suggestions: Array<{ dimension: string; value: string }>;
    blockers: string[];
  };
  ozon_global_cn: {
    state: "no_data" | "blocked" | "ready" | "ready_with_constraints";
    registry: {
      version: string;
      registry_hash: string;
      country: "CN";
      locale: "zh";
    };
    no_data_domains: string[];
    blockers: string[];
  };
  blockers: string[];
  next_action: string;
  readbacks: Record<string, unknown>;
  automation: {
    current_state: string;
    stages: Array<{
      state: string;
      status: string;
      owner: string;
      sla_hours: number;
      fingerprint: string;
    }>;
    queue_authority: string;
    execution_authority: string;
    external_side_effect: false;
  };
  sale_triggered_procurement?: {
    version: string;
    mode: "sale_triggered_jit";
    state: string;
    recommended_review_quantity: number;
    supplier_order_created: false;
    payment_created: false;
    external_purchase_write: false;
    blockers: string[];
    next_action: string;
  };
};

type BatchView = {
  run_id?: string;
  state?: "no_data";
  contract_version: string;
  store_ref: string;
  counts: CountSet;
  supply_map?: Array<{
    province: string;
    city: string;
    industry_belt: string;
    supplier_count: number;
    candidate_count?: number;
    status: string;
    longitude: string | null;
    latitude: string | null;
    position_status: string;
  }>;
  market_summary?: {
    observed_items: number;
    price_bands: Array<{
      currency: string;
      minimum: string;
      median: string;
      maximum: string;
      sample: number;
    }>;
    actual_sales_available: false;
    sales_status?: "proxy" | "no_data";
  };
  funnel?: Array<{ stage: string; count: number }>;
  strategy_distribution?: Array<{ strategy: string; count: number }>;
  ozon_global_cn_rule_registry?: {
    version: string;
    registry_hash: string;
    effective_rule_count: number;
    country: "CN";
    locale: "zh";
    ru_local_rules_applied: false;
  };
  candidates: BatchCandidate[];
  procurement_policy?: {
    version: string;
    mode: "sale_triggered_jit";
    pre_order_purchase_quantity: 0;
    supplier_order_created: false;
    payment_created: false;
    external_purchase_write: false;
  };
  bottlenecks?: string[];
  snapshot_sha256?: string;
  evidence_id?: string;
  authority?: {
    permit_created: false;
    ozon_write_performed: false;
    automatic_execution: false;
  };
};

type ErpProfitWorkspace = {
  state: "ready" | "no_data";
  tenant_ref: string;
  store_ref: string;
  counts: {
    evaluated_candidates: number;
    profit_qualified: number;
    sync_records: number;
    succeeded: number;
  };
  connector: { configured: boolean; write_scope: string };
  blockers: string[];
  next: string;
  eligible_items: Array<{
    run_id: string;
    candidate_id: string;
    product_id: string;
    downside_cm3_cny: string;
    candidate_key: string;
  }>;
};

const stageLabels: Record<string, string> = {
  observe: "观察",
  match: "精确匹配",
  evaluate: "评估",
  content_ready: "内容就绪",
  pilot: "小流量 Pilot",
  scale: "扩量",
  reconcile: "结算复盘",
  observed_listings: "观察 listing",
  unique_exact_identities: "唯一精确商品/变体",
  competitor_cohort: "同行 cohort",
  exact_identity_matched: "跨市场精确身份",
  supplier_identity_cohort: "供应身份 cohort",
  checkout_cost_eligible: "结算成本可评估",
  fully_costed: "完整成本",
  eligible_for_approval: "可进入独立审批",
  approval_allocation_selected: "审批预算槽位",
  approval_waitlist: "审批候补",
  published: "已发布",
  ordered: "已下单",
  settled_proven: "结算已证明",
};

const strategyLabels: Record<string, string> = {
  eliminate: "淘汰",
  exploration: "探索",
  controlled_distribution: "受控铺货",
  refined: "精品精细化",
  hero: "Hero SKU",
  brand: "品牌经营",
  store_cluster: "店群复制",
};

const operatingFlow = [
  "Market Radar",
  "Opportunity",
  "Passport",
  "Content QA",
  "Downside CM3",
  "Approval / Permit",
  "FBP / realFBS Pilot",
  "Ads / Price Index",
  "Order / Returns",
  "Settlement / Cash",
  "Scale / Stop",
];

function money(value: string | null) {
  return value === null ? "no_data" : `${value} CNY`;
}

function mapX(longitude: string) {
  return 72 + ((Number(longitude) - 73) / (135 - 73)) * 502;
}

function mapY(latitude: string) {
  return 202 - ((Number(latitude) - 18) / (54 - 18)) * 180;
}

export function BatchOpportunityPanel() {
  const [view, setView] = useState<BatchView | null>(null);
  const [busy, setBusy] = useState(true);
  const [storeRef, setStoreRef] = useState("");
  const [authorizedStores, setAuthorizedStores] = useState<string[]>([]);
  const [erp, setErp] = useState<ErpProfitWorkspace | null>(null);
  const [tenantRef, setTenantRef] = useState("");
  const [notice, setNotice] = useState("正在读取最近一次批量扫描…");

  const load = useCallback(async (requestedStore?: string) => {
    const store = requestedStore || storeRef;
    if (!store) return;
    setBusy(true);
    const response = await fetchJson<BatchView>(
      `/backend/v1/batch-opportunities/latest?store_ref=${encodeURIComponent(store)}`,
    );
    const payload = await response.json();
    if (!response.ok || !payload || typeof payload !== "object") {
      setNotice(`批量工作区读取失败（HTTP ${response.status || "offline"}）`);
      setBusy(false);
      return;
    }
    setView(payload);
    const erpResponse = await fetchJson<ErpProfitWorkspace>(
      `/backend/v1/erp/profit-items?store_ref=${encodeURIComponent(store)}`,
    );
    if (erpResponse.ok) setErp(await erpResponse.json());
    setNotice(
      payload.state === "no_data"
        ? "暂无批量扫描 run；页面不会用演示候选填充。"
        : `真实 run 已读取：${payload.counts.observed} 条观察、${payload.counts.exact_identity_matched ?? payload.counts.exact_matched} 个精确身份、${payload.counts.checkout_cost_eligible ?? 0} 个结算成本可评估。`,
    );
    setBusy(false);
  }, [storeRef]);

  useEffect(() => {
    void fetchJson<{
      authorized_scope: { store_refs: string[] };
    }>("/backend/v1/seller-os/strategy-packs").then(async (response) => {
      const payload = await response.json();
      if (!response.ok || !payload.authorized_scope?.store_refs?.length) {
        setNotice("当前身份没有授权店铺，批量工作区保持 forbidden/no_data。");
        setBusy(false);
        return;
      }
      setAuthorizedStores(payload.authorized_scope.store_refs);
      setTenantRef((payload.authorized_scope as { tenant_ref?: string }).tenant_ref ?? "");
      const store = payload.authorized_scope.store_refs[0];
      setStoreRef(store);
      await load(store);
    });
  }, [load]);

  const scan = async () => {
    setBusy(true);
    setNotice("服务端正在重放最新 Observation、FX、十五项成本与治理门…");
    const hour = new Date().toISOString().slice(0, 13).replaceAll(/[-T:]/g, "");
    const response = await fetchJson<BatchView>("/backend/v1/batch-market-scans", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        store_ref: storeRef,
        policy_id: "cn-ozon-observed-cost-v1",
        idempotency_key: `batch-opportunity-${hour}`,
        candidate_limit: 500,
        pilot_limit: 3,
        target_purchase_quantity: 1,
        max_age_hours: 72,
        max_inventory_cash_cny: "3000.00",
        cm3_floor_cny: "0.00",
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload || typeof payload !== "object" || !("counts" in payload)) {
      setNotice(`扫描失败（HTTP ${response.status || "offline"}）`);
      setBusy(false);
      return;
    }
    setView(payload);
    setNotice(
      `扫描完成：观察 ${payload.counts.observed}，跨市场精确身份 ${payload.counts.exact_identity_matched ?? payload.counts.exact_matched}，结算成本可评估 ${payload.counts.checkout_cost_eligible ?? 0}，可进审批 ${payload.counts.eligible_for_approval ?? 0}，审批预算槽位 ${payload.counts.approval_allocation_selected ?? 0}，Pilot ready ${payload.counts.pilot_ready}。`,
    );
    setBusy(false);
  };

  const counts = view?.counts ?? {
    observed: 0,
    exact_matched: 0,
    downside_positive: 0,
    content_ready: 0,
    pilot_ready: 0,
  };

  const prepareErpSync = async (item: ErpProfitWorkspace["eligible_items"][number]) => {
    setBusy(true);
    const response = await fetchJson("/backend/v1/erp/profit-items/syncs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        tenant_ref: tenantRef,
        store_ref: storeRef,
        run_id: item.run_id,
        candidate_id: item.candidate_id,
        idempotency_key: `erp-profit-item-${item.candidate_id}`,
      }),
    });
    const payload = await response.json();
    setNotice(response.ok
      ? `ERP Item 同步记录已建立：${payload.status}。库存仍为 0，未创建采购单。`
      : `ERP Item 同步被阻断（HTTP ${response.status || "offline"}）。`);
    await load(storeRef);
  };
  const supplyRegions = view?.supply_map ?? [];
  const positionedSupply = supplyRegions.filter(
    (item) => item.longitude !== null && item.latitude !== null,
  );

  return (
    <div className="workspace-page batch-opportunity-page">
      <section className="batch-hero">
        <div>
          <span><ScanSearch size={15} /> SCAN · SCORE · CLASSIFY · PILOT</span>
          <h2>全国供应与 Ozon 市场机会，由服务端统一算清。</h2>
          <p>
            标准品可以使用精确变体和下单页复核的 observed checkout price，
            但它仍不是供应商 Offer 或实际成本。销量未知就显示 no_data，不用评价或差价伪造销量。
            采用 sale-triggered JIT：Ozon 真实订单前采购数量恒为 0，出单后也只进入采购评审。
          </p>
        </div>
        <div className="batch-policy-card">
          <ShieldAlert size={22} />
          <strong>数据与发布硬门禁</strong>
          <p>downside CM3 &gt; 0 · Passport · 媒体权利/QA · 独立批准 · 单次 Permit · Readback · 止损</p>
          <small>资源政策目标：70% 已验证精品 / 20% 受控铺货 / 10% 探索；不是当前事实。</small>
        </div>
      </section>

      <section className="batch-toolbar">
        <div>
          <span>REAL BATCH SNAPSHOT</span>
          <h3>实际数量，不为达到 100–500 目标补造数据</h3>
          <p>{notice}</p>
        </div>
        <div>
          <label>
            <span className="sr-only">授权店铺</span>
            <select
              aria-label="授权店铺"
              value={storeRef}
              onChange={(event) => {
                setStoreRef(event.target.value);
                void load(event.target.value);
              }}
              disabled={busy}
            >
              {authorizedStores.map((store) => (
                <option key={store} value={store}>{store}</option>
              ))}
            </select>
          </label>
          <button type="button" className="secondary" onClick={() => void load()} disabled={busy}>
            <RefreshCw size={14} /> 刷新
          </button>
          <button type="button" onClick={() => void scan()} disabled={busy}>
            <ScanSearch size={14} /> {busy ? "处理中…" : "重跑服务端扫描"}
          </button>
        </div>
      </section>

      <section className="batch-kpis" aria-label="批量机会真实计数">
        <article><Boxes size={18} /><span>实际观察</span><strong>{counts.observed}</strong></article>
        <article><GitBranch size={18} /><span>跨市场精确身份</span><strong>{counts.exact_identity_matched ?? counts.exact_matched}</strong></article>
        <article><Factory size={18} /><span>结算成本可评估</span><strong>{counts.checkout_cost_eligible ?? 0}</strong></article>
        <article><ChartNoAxesCombined size={18} /><span>downside 正</span><strong>{counts.downside_positive}</strong></article>
        <article><Sparkles size={18} /><span>审批预算槽位</span><strong>{counts.approval_allocation_selected ?? 0}</strong></article>
        <article className={counts.pilot_ready ? "ready" : "blocked"}>
          <ShieldAlert size={18} /><span>Pilot 就绪</span><strong>{counts.pilot_ready}</strong>
        </article>
      </section>

      <section className="batch-official-flow" aria-label="利润款 ERP 同步">
        <header>
          <div>
            <span>PROFIT-QUALIFIED → ERP ITEM DRAFT</span>
            <h3>利润款写入 ERP，同步状态由服务端权威判定</h3>
          </div>
          <strong>{erp?.counts.profit_qualified ?? 0} 可同步</strong>
        </header>
        <p>
          已评估 {erp?.counts.evaluated_candidates ?? 0} · 同步记录 {erp?.counts.sync_records ?? 0} ·
          成功 {erp?.counts.succeeded ?? 0} · 连接器 {erp?.connector.configured ? "已配置" : "未配置"}
        </p>
        {(erp?.eligible_items ?? []).map((item) => (
          <button key={item.candidate_id} type="button" disabled={busy} onClick={() => void prepareErpSync(item)}>
            建立 ERP Item 草稿 · CM3 {item.downside_cm3_cny} CNY
          </button>
        ))}
        {(erp?.eligible_items.length ?? 0) === 0 ? (
          <p className="batch-no-data">no_data · {erp?.next ?? "尚无服务端证实的利润款"}；不会把观察价写成 ERP 利润商品。</p>
        ) : null}
        <small>固定 opening_stock=0；不创建采购单、付款、广告或 Ozon 写入。</small>
      </section>

      <section className="batch-official-flow" aria-label="Ozon Global CN 官方经营闭环">
        <header>
          <div>
            <span>OZON GLOBAL CN · RULE REGISTRY</span>
            <h3>官方规则执行链，不与 RU 本土规则混用</h3>
          </div>
          <strong>
            {view?.ozon_global_cn_rule_registry
              ? `v${view.ozon_global_cn_rule_registry.version} · ${view.ozon_global_cn_rule_registry.effective_rule_count} rules`
              : "no_data"}
          </strong>
        </header>
        <div>
          {operatingFlow.map((step, index) => (
            <span key={step}>{index + 1}. {step}</span>
          ))}
        </div>
        <p>
          规则哈希 {view?.ozon_global_cn_rule_registry?.registry_hash?.slice(0, 16) ?? "no_data"} ·
          官方门就绪候选 {counts.official_rule_ready ?? 0} ·
          RU 本土默认 {view?.ozon_global_cn_rule_registry?.ru_local_rules_applied ? "错误" : "未应用"}
        </p>
      </section>

      <section className="batch-visual-grid">
        <article className="batch-map-card">
          <header><MapPinned size={18} /><div><span>SUPPLY MAP</span><h3>全国供应方位与产业带</h3></div></header>
          {supplyRegions.length > 0 ? (
            <>
              {positionedSupply.length > 0 ? (
                <svg viewBox="0 0 640 240" role="img" aria-label="按观察经纬度投影的真实供应产业带分布">
                  <path d="M72 42 L180 22 L275 45 L390 28 L532 76 L574 138 L498 202 L360 216 L224 198 L114 150 Z" />
                  {positionedSupply.slice(0, 40).map((item) => (
                    <g
                      key={`${item.province}-${item.city}-${item.industry_belt}`}
                      transform={`translate(${mapX(item.longitude!)} ${mapY(item.latitude!)})`}
                    >
                      <circle r={8 + Math.min(item.supplier_count, 8)} />
                      <text y="-17">{item.province}</text>
                      <text y="25">{item.city} · {item.supplier_count}</text>
                    </g>
                  ))}
                </svg>
              ) : (
                <p className="batch-no-data">no_data · 已观察供应方，但原件未提供可复核经纬度；不绘制猜测点位</p>
              )}
              <div className="batch-map-legend">
                {supplyRegions.map((item) => (
                  <span key={`${item.province}-${item.city}`}>
                    {item.industry_belt} · {item.status} · 定位 {item.position_status}
                  </span>
                ))}
              </div>
            </>
          ) : <p className="batch-no-data">no_data · 尚无带省市/产业带的可复核供应观察</p>}
        </article>

        <article className="batch-market-card">
          <header><ChartNoAxesCombined size={18} /><div><span>MARKET RANGE</span><h3>Ozon 行情与价格带</h3></div></header>
          {(view?.market_summary?.price_bands.length ?? 0) > 0 ? (
            <div className="batch-price-bands">
              {view?.market_summary?.price_bands.map((band) => (
                <div key={band.currency}>
                  <span>{band.currency} · 样本 {band.sample}</span>
                  <div><i /><i /><i /></div>
                  <strong>{band.minimum}</strong><strong>{band.median}</strong><strong>{band.maximum}</strong>
                </div>
              ))}
              <small>销量：{view?.market_summary?.actual_sales_available ? "actual" : (view?.market_summary?.sales_status ?? "no_data")}</small>
            </div>
          ) : <p className="batch-no-data">no_data · 尚无 Ozon 市场价格观察</p>}
        </article>
      </section>

      <section className="batch-funnel-card">
        <header><Factory size={18} /><div><span>OPERATING STATE MACHINE</span><h3>候选漏斗与策略分布</h3></div></header>
        <div className="batch-funnel">
          {(view?.funnel ?? []).map((item) => (
            <div key={item.stage}><strong>{item.count}</strong><span>{stageLabels[item.stage] ?? item.stage}</span></div>
          ))}
        </div>
        <div className="batch-strategies">
          {(view?.strategy_distribution ?? []).map((item) => (
            <span key={item.strategy}>{strategyLabels[item.strategy] ?? item.strategy} <strong>{item.count}</strong></span>
          ))}
          {(view?.strategy_distribution?.length ?? 0) === 0 ? <span>no_data · 尚无策略分类</span> : null}
        </div>
      </section>

      <section className="batch-candidate-list">
        {(view?.candidates ?? []).map((candidate) => (
          <article key={candidate.fingerprint} className={`batch-candidate ${candidate.state}`}>
            <header>
              <span className="batch-rank">{String(candidate.rank).padStart(2, "0")}</span>
              <div>
                <span>{strategyLabels[candidate.strategy.classification] ?? candidate.strategy.classification}</span>
                <h3>{candidate.market.title}</h3>
                <p>{candidate.market.variant_key} ↔ {candidate.supply.variant_key}</p>
              </div>
              <strong>{candidate.score.total}</strong>
            </header>
            <div className="batch-candidate-grid">
              <div>
                <span>市场 / 供应</span>
                <strong>{candidate.market.price} {candidate.market.currency}</strong>
                <p>
                  收入场景 {candidate.market.revenue_scenario?.kind ?? "no_data"} ·
                  {candidate.market.revenue_scenario?.authority ?? "no_data"}
                </p>
                <p>{candidate.supply.observed_checkout_price} {candidate.supply.currency} · MOQ {candidate.supply.moq ?? "no_data"} · 数量 {candidate.supply.observed_quantity}</p>
                <small>供应商密度 {candidate.supply.supplier_density} · 销量 {candidate.market.sales_semantics}</small>
              </div>
              <div>
                <span>baseline / downside CM3</span>
                <strong>{money(candidate.economics.baseline.cm3_cny)}</strong>
                <p>{money(candidate.economics.downside.cm3_cny)}</p>
                <small>现金占用 {money(candidate.economics.downside.inventory_cash_cny)} · 守恒 {candidate.economics.downside.conservation_delta_cny ?? "no_data"}</small>
              </div>
              <div>
                <span>内容与变体</span>
                <strong>{candidate.content.content_ready ? "content_ready" : "blocked"}</strong>
                <p>Passport {candidate.content.passport_ready ? "ready" : "blocked"} · 媒体 {candidate.content.media_ready ? "ready" : "blocked"}</p>
                <small>变体计划 {candidate.variant_plan.ready ? "ready" : "等待 24h/72h/7d + 两结算周期"}</small>
              </div>
              <div>
                <span>Global CN 官方规则</span>
                <strong>{candidate.ozon_global_cn.state}</strong>
                <p>
                  CN/zh · {candidate.ozon_global_cn.no_data_domains.length
                    ? `no_data: ${candidate.ozon_global_cn.no_data_domains.join(" / ")}`
                    : "全部域已验证"}
                </p>
                <small>规则变化会改变指纹并触发 SKU 重评估</small>
              </div>
            </div>
            <div className="batch-candidate-bottom">
              <p>
                <strong>{candidate.strategy.reason}</strong><br />
                {candidate.next_action}
                {candidate.strategy.tactics?.length ? ` · 战术：${candidate.strategy.tactics.join(" / ")}` : ""}
              </p>
              <div>{candidate.blockers.slice(0, 5).map((item) => <span key={item}>{item}</span>)}</div>
            </div>
            <div className="batch-state-row" aria-label="出单后采购状态">
              <span data-status={candidate.sale_triggered_procurement?.state === "eligible_for_procurement_review" ? "current" : "blocked"}>
                采购模式 {candidate.sale_triggered_procurement?.mode ?? "sale_triggered_jit"} · {candidate.sale_triggered_procurement?.state ?? "no_data"}
              </span>
              <span>
                建议评审数量 {candidate.sale_triggered_procurement?.recommended_review_quantity ?? 0} · 下单/付款均未创建
              </span>
            </div>
            <div className="batch-state-row" aria-label="候选自动化状态机">
              {candidate.automation.stages.map((stage) => (
                <span key={stage.state} data-status={stage.status}>
                  {stageLabels[stage.state] ?? stage.state} · {stage.owner} · {stage.sla_hours}h
                </span>
              ))}
            </div>
            <footer>
              <span>observed checkout · 非 Offer · 非 actual</span>
              <span>
                {candidate.pilot_selection?.status ?? "ineligible"} ·
                仅审批预算分配，非 Approval / Permit / Pilot
              </span>
            </footer>
          </article>
        ))}
        {(view?.candidates.length ?? 0) === 0 ? (
          <div className="batch-empty">
            <ShieldAlert size={24} />
            {(counts.exact_identity_matched ?? counts.exact_matched) > 0 ? (
              <>
                <h3>同款已找到，待结算成本 Evidence</h3>
                <p>不向供应商下单；仅在确认仍有货时，补齐目标数量 1、MOQ、税与目标仓运费绑定的 1688 checkout 观察。</p>
              </>
            ) : (
              <>
                <h3>暂无精确跨市场匹配</h3>
                <p>继续补充 Ozon 市场观察与绑定同一真实身份/变体的 1688 供应观察。</p>
              </>
            )}
          </div>
        ) : null}
      </section>

      <section className="batch-run-boundary">
        <ShieldAlert size={18} />
        <div>
          <strong>当前运行不采购；发布仍按利润与治理门禁</strong>
          <p>
            Run {view?.run_id ?? "no_data"} · Evidence {view?.evidence_id ?? "no_data"} ·
            Permit {view?.authority?.permit_created ? "已创建" : "未创建"} ·
            Ozon 写入 {view?.authority?.ozon_write_performed ? "已执行" : "未执行"} ·
            出单前采购 {view?.procurement_policy?.pre_order_purchase_quantity ?? 0} 件
          </p>
        </div>
      </section>
    </div>
  );
}
