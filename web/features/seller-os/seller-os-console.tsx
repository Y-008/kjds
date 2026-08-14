"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  BadgeDollarSign,
  Building2,
  ChartSpline,
  Network,
  Radar,
  Route,
  ShieldCheck,
  Store,
} from "lucide-react";
import { fetchJson } from "../../lib/fetch-json";

type Surface =
  | "seller-os"
  | "strategy-center"
  | "rule-advantage"
  | "portfolio-cockpit"
  | "store-matrix"
  | "growth-command";

type StrategyPack = {
  label: string;
  commercial_plan: string;
  price_cny_month?: string;
  price_cny_year_from?: string;
  shops_max: number | null;
  active_sku_max: number | null;
  users_max: number | null;
  scan_batch_max: number;
  approval_layers: number;
  permit_ttl_minutes: number;
  single_sku_budget_cny: string;
  advertising_daily_cap_cny: string;
  facts_and_profit_kernel?: "shared";
  truth_degraded?: false;
};

type Packs = {
  strategy_packs: Record<string, StrategyPack>;
  portfolio_policy: Record<string, string>;
  facts_and_profit_kernel: string;
  truth_degradation_by_plan: false;
  authorized_scope: { tenant_ref: string; store_refs: string[] };
  strategy_pack_registry: {
    commercial_status: string;
    version: string;
  };
};

type MatrixRow = {
  maturity: string;
  label: string;
  scan_batch_max: number;
  approval_layers: number;
  single_sku_budget_cny: string;
  initial_pilot_units_max: number;
  scaled_inventory_cap: number;
  advertising_daily_cap_cny: string;
  permit_ttl_minutes: number;
  decision: string;
  blockers: string[];
};

type Candidate = {
  fingerprint: string;
  market: {
    title: string;
    variant_key: string;
    revenue_scenario?: {
      kind: string;
      authority: string;
      unit_price: string;
      profit_floor_status: string;
    };
  };
  pilot_selection?: {
    status: string;
    reason: string;
    semantics: string;
  };
  economics: {
    downside: {
      cm3_cny: string | null;
      inventory_cash_cny: string | null;
    };
    actual_profit: null;
  };
  ozon_global_cn: {
    state: string;
    registry: { version: string; registry_hash: string };
    no_data_domains: string[];
    actions: Record<string, ActionReadiness>;
  };
  seller_os?: {
    rows: MatrixRow[];
    same_candidate_facts: true;
    automatic_listing_count_is_success_metric: false;
  };
};

type Batch = {
  run_id?: string;
  counts: {
    observed: number;
    exact_matched: number;
    pilot_ready: number;
    eligible_for_approval?: number;
    approval_allocation_selected?: number;
    approval_waitlist?: number;
  };
  candidates: Candidate[];
  ozon_global_cn_rule_registry?: {
    version: string;
    registry_hash: string;
    effective_rule_count: number;
  };
};

type SellerEvaluation = {
  status: string;
  seller_profile: {
    classification: string | null;
    scale_segment?: string;
    operational_maturity?: string;
    brand_stage?: string;
    risk_posture?: string;
    confidence: string;
    input_completeness?: string;
    evidence_coverage?: string;
    classification_confidence?: string;
    missing_facts: string[];
  };
  strategy?: {
    operating_mode: string;
    confidence: string;
    blockers: string[];
  };
  policy_envelope?: {
    scan_batch_max: number;
    single_sku_budget_cny: string;
    advertising_daily_cap_cny: string;
    approval_layers: number;
    permit_ttl_minutes: number;
  };
  strategy_pack?: StrategyPack;
  portfolio?: {
    status: string;
    snapshot_established: boolean;
    counts: Record<string, number>;
  };
  action_readiness?: Record<string, ActionReadiness>;
  blockers?: string[];
};

type ActionReadiness = {
  status: string;
  blockers: string[];
  why: string;
  missing_evidence: string[];
  owner: string;
  sla_hours: number;
  next_workspace_href: string;
};

type RuleImpact = {
  state: string;
  reason?: string;
  changed_domains: string[];
  affected_sku_count: number;
};

const surfaces: Array<{
  id: Surface;
  path: string;
  label: string;
  icon: typeof Radar;
}> = [
  { id: "seller-os", path: "/seller-os", label: "成熟度诊断", icon: Building2 },
  { id: "strategy-center", path: "/strategy-center", label: "策略中心", icon: Network },
  { id: "rule-advantage", path: "/rule-advantage", label: "规则优势", icon: ShieldCheck },
  { id: "portfolio-cockpit", path: "/portfolio-cockpit", label: "组合驾驶舱", icon: ChartSpline },
  { id: "store-matrix", path: "/store-matrix", label: "店群矩阵", icon: Store },
  { id: "growth-command", path: "/growth-command", label: "增长指挥", icon: Route },
];

const flow = [
  "机会",
  "Passport",
  "Pilot",
  "广告 / 价格",
  "订单 / 退货",
  "结算 / 现金",
  "扩量 / 停止",
];

const profileLabels: Record<string, string> = {
  novice: "新手",
  solo: "成长个人 / 小微",
  small_team: "中小企业",
  mid_market: "中型企业",
  enterprise: "大卖 / 集团",
};

const diagnosisFields = [
  { key: "shops", label: "授权店铺数", unit: "店", kind: "number", example: "例如 1" },
  { key: "active_skus", label: "在营 SKU", unit: "个", kind: "number", example: "例如 80" },
  { key: "users", label: "运营用户", unit: "人", kind: "number", example: "例如 1" },
  { key: "warehouses", label: "履约仓库", unit: "个", kind: "number", example: "例如 1" },
  { key: "capital_cny", label: "可用经营资金", unit: "CNY", kind: "number", example: "例如 50000" },
] as const;

const scaleOptions = {
  risk_tolerance: [
    ["low", "保守"],
    ["moderate", "适中"],
    ["high", "进取"],
  ],
  brand_maturity: [
    ["unverified", "品牌状态未核验"],
    ["reseller", "经销"],
    ["authorized", "已授权"],
    ["owned", "自有品牌"],
    ["portfolio", "品牌组合"],
  ],
  ops_capability: [
    ["guided", "引导式"],
    ["manual", "人工可重复"],
    ["standardized", "标准化"],
    ["api_scheduled", "API 排程"],
    ["erp_wms", "ERP / WMS 集成"],
  ],
} as const;

export function SellerOsConsole({ surface }: { surface: Surface }) {
  const [packs, setPacks] = useState<Packs | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [evaluation, setEvaluation] = useState<SellerEvaluation | null>(null);
  const [ruleImpact, setRuleImpact] = useState<RuleImpact | null>(null);
  const [selectedStore, setSelectedStore] = useState("");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("正在读取统一事实与治理内核…");
  const [sellerFacts, setSellerFacts] = useState({
    shops: "",
    active_skus: "",
    users: "",
    warehouses: "",
    capital_cny: "",
    risk_tolerance: "",
    brand_maturity: "",
    ops_capability: "",
  });

  const load = useCallback(async (requestedStore?: string) => {
    setLoading(true);
    setNotice("正在读取授权作用域、统一事实与治理内核…");
    try {
      const packsResponse = await fetchJson<Packs>(
        "/backend/v1/seller-os/strategy-packs",
      );
      const packsPayload = await packsResponse.json();
      if (!packsResponse.ok) {
        setNotice(`策略包读取失败（HTTP ${packsResponse.status || "offline"}），可重试。`);
        setLoading(false);
        return;
      }
      setPacks(packsPayload);
      const store = requestedStore
        || selectedStore
        || packsPayload.authorized_scope.store_refs[0]
        || "";
      setSelectedStore(store);
      if (!store) {
        setBatch(null);
        setNotice("当前身份没有授权店铺；工作区保持 forbidden/no_data。");
        setLoading(false);
        return;
      }
      const [batchResponse, impactResponse] = await Promise.all([
        fetchJson<Batch>(
          `/backend/v1/batch-opportunities/latest?store_ref=${encodeURIComponent(store)}`,
        ),
        fetchJson<RuleImpact>("/backend/v1/ozon-global-rules/impact", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            previous_registry: null,
            previous_registry_hash: null,
            sku_bindings: [],
          }),
        }),
      ]);
      const batchPayload = await batchResponse.json();
      const impactPayload = await impactResponse.json();
      setBatch(batchResponse.ok ? batchPayload : null);
      setRuleImpact(impactResponse.ok ? impactPayload : null);
      setNotice(
        batchResponse.ok
          ? `已读取 ${store} 的最近真实批量 run。`
          : `店铺 ${store} 尚无 run 或读取失败；保持 no_data，可重试。`,
      );
    } catch {
      setNotice("网络或服务异常；未缓存伪数据，请重试。");
    } finally {
      setLoading(false);
    }
  }, [selectedStore]);

  useEffect(() => {
    void load();
  }, [load]);

  const diagnose = async (event: FormEvent) => {
    event.preventDefault();
    setNotice("服务端正在按事实分类，不采信自选标签…");
    if (!packs || !selectedStore) {
      setNotice("请先读取授权租户与店铺。");
      return;
    }
    const response = await fetchJson<SellerEvaluation>(
      "/backend/v1/seller-os/evaluate",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          tenant_ref: packs.authorized_scope.tenant_ref,
          store_ref: selectedStore,
          seller_facts: {
            values: {
              ...sellerFacts,
              shops: sellerFacts.shops ? Number(sellerFacts.shops) : "no_data",
              active_skus: sellerFacts.active_skus
                ? Number(sellerFacts.active_skus)
                : "no_data",
              users: sellerFacts.users ? Number(sellerFacts.users) : "no_data",
              warehouses: sellerFacts.warehouses
                ? Number(sellerFacts.warehouses)
                : "no_data",
            },
            provenance: {
              source: "user_self_report",
              observed_at: new Date().toISOString(),
              evidence_ids: [],
            },
          },
          operating_facts: {},
          portfolio_items: [],
          advantage_facts: {},
        }),
      },
    );
    const payload = await response.json();
    if (!response.ok) {
      setNotice(`诊断失败（HTTP ${response.status || "offline"}）`);
      return;
    }
    setEvaluation(payload);
    setNotice(
      payload.status === "no_data"
        ? "信息不完整：服务端未猜测成熟度。"
        : `事实分类完成：${profileLabels[payload.seller_profile.classification ?? ""] ?? payload.seller_profile.classification}`,
    );
  };

  const candidate = batch?.candidates?.[0];
  const actions = evaluation?.action_readiness
    ?? candidate?.ozon_global_cn.actions
    ?? null;

  return (
    <main className="seller-os-page">
      <header className="seller-os-topbar">
        <Link href="/" className="seller-os-brand">KJDS <span>SELLER OS</span></Link>
        <nav>
          {surfaces.map((item) => {
            const Icon = item.icon;
            return (
              <Link key={item.id} href={item.path} data-active={item.id === surface}>
                <Icon size={14} /> {item.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <section className="seller-os-hero">
        <div>
          <span>RULES-AS-CODE · PROFIT-FIRST · NO BYPASS</span>
          <h1>比平台最低线更早一步，而不是绕过平台规则。</h1>
          <p>
            同一事实、利润与治理内核服务个人到集团；规模、协作和预算可以不同，
            真实性与独立 Permit / Readback 不打折。
          </p>
        </div>
        <aside>
          <strong>{surface.replaceAll("-", " ").toUpperCase()}</strong>
          <p>{notice}</p>
          <label>
            <span>授权店铺</span>
            <select
              aria-label="授权店铺"
              value={selectedStore}
              onChange={(event) => void load(event.target.value)}
              disabled={loading}
            >
              {(packs?.authorized_scope.store_refs ?? []).map((store) => (
                <option key={store} value={store}>{store}</option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => void load()} disabled={loading}>
            {loading ? "读取中…" : "重试读取"}
          </button>
          <small>自动上品数量不是成功指标</small>
        </aside>
      </section>

      {actions ? (
        <section className="seller-os-rule-card" aria-label="动作级就绪度">
          <header>
            <ShieldCheck size={20} />
            <div><span>ACTION-SCOPED READINESS</span><h2>当前动作为什么可做 / 不可做</h2></div>
          </header>
          <div className="seller-os-rule-metrics">
            {Object.entries(actions).map(([name, action]) => (
              <article key={name}>
                <span>{name}</span>
                <strong>{action.status}</strong>
                <p>{action.why} · Owner {action.owner} · SLA {action.sla_hours}h</p>
                <small>
                  {action.blockers.length
                    ? action.blockers.join(" / ")
                    : "当前动作所需门禁已满足"}
                  {" · "}
                  <Link href={action.next_workspace_href}>下一工作区</Link>
                </small>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {surface === "seller-os" ? (
        <section className="seller-os-diagnosis">
          <header>
            <Building2 size={20} />
            <div><span>FACT CLASSIFIER</span><h2>经营成熟度诊断</h2></div>
          </header>
          <form onSubmit={(event) => void diagnose(event)}>
            {diagnosisFields.map((field) => (
              <label key={field.key}>
                <span>{field.label}（{field.unit}）</span>
                <input
                  type="number"
                  min="0"
                  value={sellerFacts[field.key]}
                  onChange={(event) => setSellerFacts((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))}
                  placeholder={`${field.example}；留空即 no_data`}
                />
              </label>
            ))}
            {(Object.keys(scaleOptions) as Array<keyof typeof scaleOptions>).map((key) => (
              <label key={key}>
                <span>
                  {key === "risk_tolerance"
                    ? "风险姿态（自报）"
                    : key === "brand_maturity"
                      ? "品牌阶段（需后续证据核验）"
                      : "运营能力（自报）"}
                </span>
                <select
                  value={sellerFacts[key]}
                  onChange={(event) => setSellerFacts((current) => ({
                    ...current,
                    [key]: event.target.value,
                  }))}
                >
                  <option value="">请选择；留空即 no_data</option>
                  {scaleOptions[key].map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
            ))}
            <button type="submit">按事实诊断</button>
          </form>
          <p>
            隐私说明：仅提交经营规模与能力量表，不采集密码、Cookie 或个人敏感信息。
            自报数据不会自动升级为平台事实或商业 entitlement。
          </p>
          <div className="seller-os-result">
            <strong>
              {evaluation?.seller_profile.scale_segment
                ? profileLabels[evaluation.seller_profile.scale_segment]
                : "no_data"}
            </strong>
            <span>
              规模 confidence {evaluation?.seller_profile.classification_confidence ?? "no_data"} ·
              Evidence coverage {evaluation?.seller_profile.evidence_coverage ?? "no_data"}
            </span>
            <p>
              运营 {evaluation?.seller_profile.operational_maturity ?? "no_data"} ·
              品牌 {evaluation?.seller_profile.brand_stage ?? "no_data"} ·
              风险 {evaluation?.seller_profile.risk_posture ?? "no_data"} ·
              建议模式 {evaluation?.strategy?.operating_mode ?? "no_data"} ·
              单 SKU 预算 {evaluation?.policy_envelope?.single_sku_budget_cny ?? "no_data"} ·
              审批 {evaluation?.policy_envelope?.approval_layers ?? "no_data"} 层
            </p>
          </div>
        </section>
      ) : null}

      {surface === "strategy-center" ? (
        <section className="seller-os-pack-grid">
          {Object.entries(packs?.strategy_packs ?? {}).map(([key, pack]) => (
            <article key={key}>
              <span>{profileLabels[key] ?? key}</span>
              <h2>{pack.commercial_plan}</h2>
              <strong>
                {pack.price_cny_month
                  ? `¥${pack.price_cny_month}/月`
                  : `¥${pack.price_cny_year_from}/年起`}
              </strong>
              <small>定价假设 · internal preview · 当前不可交易</small>
              <p>{pack.shops_max ?? "50+"} 店 · {pack.active_sku_max ?? "百万+"} SKU · {pack.users_max ?? "自定义"} 用户</p>
              <dl>
                <div><dt>扫描批次</dt><dd>{pack.scan_batch_max}</dd></div>
                <div><dt>单 SKU 预算</dt><dd>¥{pack.single_sku_budget_cny}</dd></div>
                <div><dt>审批层级</dt><dd>{pack.approval_layers}</dd></div>
                <div><dt>Permit TTL</dt><dd>{pack.permit_ttl_minutes}m</dd></div>
              </dl>
              <small>
                仅改变配额、协作、SLA 与可申请包络，不降低真实性；Ozon 授权、KJDS 订阅、
                单次 Approval / Permit 是三个独立 Gate。
              </small>
            </article>
          ))}
        </section>
      ) : null}

      {surface === "rule-advantage" ? (
        <section className="seller-os-rule-card">
          <header><ShieldCheck size={20} /><div><span>RULE CHANGE SIMULATION</span><h2>规则变化与受影响 SKU</h2></div></header>
          <div className="seller-os-rule-metrics">
            <article><span>Registry</span><strong>{batch?.ozon_global_cn_rule_registry?.version ?? "no_data"}</strong></article>
            <article><span>规则数</span><strong>{batch?.ozon_global_cn_rule_registry?.effective_rule_count ?? "no_data"}</strong></article>
            <article><span>候选池（非受影响数）</span><strong>{batch?.counts.exact_matched ?? 0}</strong></article>
            <article>
              <span>需重评</span>
              <strong>
                {ruleImpact?.state === "change_detected"
                  ? ruleImpact.affected_sku_count
                  : "no_data"}
              </strong>
            </article>
          </div>
          <p>
            哈希 {batch?.ozon_global_cn_rule_registry?.registry_hash ?? "no_data"}。
            {ruleImpact?.state === "change_detected"
              ? ` 变更域：${ruleImpact.changed_domains.join(" / ")}。`
              : " 尚无 previous hash→current hash 的规则变更事件，不能把所有候选伪装成受影响 SKU。"}
          </p>
        </section>
      ) : null}

      {surface === "portfolio-cockpit" ? (
        <section className="seller-os-portfolio">
          <header><ChartSpline size={20} /><div><span>CAPITAL BUCKETS</span><h2>proven / growth / experiment / exit</h2></div></header>
          <div>
            {["proven", "growth", "experiment", "exit"].map((bucket) => (
              <article key={bucket}>
                <span>{bucket}</span>
                <strong>
                  {evaluation?.portfolio?.snapshot_established
                    ? evaluation.portfolio.counts[bucket] ?? 0
                    : "no_data"}
                </strong>
                <p>政策资金 {packs?.portfolio_policy?.[bucket] ? `${Number(packs.portfolio_policy[bucket]) * 100}%` : "no_data"}</p>
              </article>
            ))}
          </div>
          <p>
            {evaluation?.portfolio?.snapshot_established
              ? "组合来自服务端 Actual Cash CM3 / 履约 / 退货 / 结算快照。"
              : `尚未建立真实 Portfolio snapshot；候选池 ${batch?.counts.exact_matched ?? 0} 与资金组合严格分开。`}
          </p>
        </section>
      ) : null}

      {surface === "store-matrix" ? (
        <section className="seller-os-empty">
          <Store size={26} />
          <h2>店群按品牌 / 类目 / 区域 / 主体分工</h2>
          <strong>no_data</strong>
          <p>当前真实 run 没有多店、多主体、品牌授权和两个结算周期证据；系统不会生成重复垃圾铺货矩阵。</p>
        </section>
      ) : null}

      {surface === "growth-command" ? (
        <section className="seller-os-command">
          <header><Route size={20} /><div><span>CONTROLLED GROWTH FLOW</span><h2>机会到结算现金的真实流转</h2></div></header>
          <div className="seller-os-flow">
            {flow.map((step, index) => <span key={step}>{index + 1}. {step}</span>)}
          </div>
          {(batch?.candidates ?? []).slice(0, 20).map((row) => (
            <article key={row.fingerprint}>
              <div>
                <strong>{row.market.title}</strong>
                <span>{row.market.variant_key}</span>
              </div>
              <dl>
                <div><dt>downside CM3</dt><dd>{row.economics.downside.cm3_cny ?? "no_data"}</dd></div>
                <div><dt>现金占用</dt><dd>{row.economics.downside.inventory_cash_cny ?? "no_data"}</dd></div>
                <div><dt>规则门</dt><dd>{row.ozon_global_cn.state}</dd></div>
                <div>
                  <dt>审批分配</dt>
                  <dd>{row.pilot_selection?.status ?? "ineligible"}</dd>
                </div>
              </dl>
              <small>
                {row.pilot_selection?.semantics
                  ?? "预算槽位不是 Approval、Permit 或已启动 Pilot"}
              </small>
            </article>
          ))}
          {(batch?.candidates.length ?? 0) === 0 ? (
            <article><strong>no_data · 尚无精确匹配候选</strong></article>
          ) : null}
        </section>
      ) : null}

      {candidate?.seller_os ? (
        <section className="seller-os-matrix">
          <header>
            <BadgeDollarSign size={20} />
            <div>
              <span>SAME SKU · DIFFERENT POLICY ENVELOPES</span>
              <h2>同一真实候选的 5 档经营决策</h2>
            </div>
          </header>
          <div className="seller-os-matrix-scroll">
            <table>
              <thead>
                <tr><th>成熟度</th><th>决策</th><th>批次</th><th>单 SKU 预算</th><th>审批</th><th>广告/日</th><th>Permit TTL</th></tr>
              </thead>
              <tbody>
                {candidate.seller_os.rows.map((row) => (
                  <tr key={row.maturity}>
                    <td>{row.label}</td>
                    <td data-state={row.decision}>{row.decision}</td>
                    <td>{row.scan_batch_max}</td>
                    <td>¥{row.single_sku_budget_cny}</td>
                    <td>{row.approval_layers} 层</td>
                    <td>¥{row.advertising_daily_cap_cny}</td>
                    <td>{row.permit_ttl_minutes}m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>候选事实与利润完全相同；只有规模、预算、协作和自动化包络改变。Permit 均未创建。</p>
        </section>
      ) : (
        <section className="seller-os-empty">
          <Radar size={26} /><h2>成熟度策略矩阵</h2><strong>no_data</strong>
          <p>最近 run 尚无精确匹配候选，系统不会展示演示 SKU。</p>
        </section>
      )}
    </main>
  );
}
