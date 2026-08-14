"use client";

import {
  ArrowLeft,
  Bot,
  Boxes,
  CheckCircle2,
  CircleDashed,
  Factory,
  Fingerprint,
  Landmark,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Store,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import type { WebSession } from "../dashboard/contracts";
import styles from "./commerce-os.module.css";

type Stage = {
  id: string;
  label: string;
  sequence: number;
  status: string;
  qualified_record_count: number;
  why: string;
  owner: string;
  sla_hours: number;
  next_action: string;
  workspace_href: string;
  external_write_allowed: false;
};

type Capability = {
  id: string;
  label: string;
  implementation_status: string;
  operating_status: string;
  acceptance_status: string;
  blockers: string[];
};

type NativeModule = {
  module_id: string;
  label: string;
  authority_modules: string[];
  acceptance_status: string;
  verified_capability_count: number;
  capability_count: number;
  native_kjds_owner: true;
  third_party_erp_dependency: false;
};

type Benchmark = {
  benchmark_id: string;
  display_name: string;
  evidence_tier: string;
  native_verified_count: number;
  benchmark_capability_count: number;
  native_gap_capability_ids: string[];
  coverage_status: string;
  baseline_requirement: "must_have_native_parity";
  safe_capability_omission_allowed: false;
  mapping_is_not_implementation: true;
  comparison_only: true;
  runtime_dependency: false;
  integration_required: false;
  workflow_mapping: {
    mapping_status: "mapped_not_implemented";
    source: {
      title: string;
      url: string;
      observed_at: string;
      evidence_tier: string;
    };
    observed_capability_count: number;
    mapped_count: number;
    unmapped_count: number;
    adoption_summary: Record<string, number>;
    implementation_status_summary: Record<string, number>;
    implementation_is_not_claimed: true;
    external_write_allowed: false;
    capabilities: Array<{
      id: string;
      observed: string;
      kjds_target: string;
      adoption: string;
      wave: string;
      implementation_status: string;
      boundary: string;
    }>;
    snapshot_sha256: string;
  } | null;
  why: string;
};

type Agent = {
  agent_id: string;
  name: string;
  status: string;
  current_focus: string;
  why: string;
  owner: string;
  sla_hours: number;
  next_action: string;
  workspace_href: string;
  output_artifact: string;
  queued_work_item_count: number;
  can_approve_own_output: false;
  can_issue_permit: false;
  external_write_allowed: false;
};

type IntelligenceSourceAdapter = {
  adapter_id: string;
  adapter_version: string;
  source_class: string;
  max_source_grade: "A" | "B" | "C" | "D";
  status: "implemented" | "contract_only" | "blocked" | "retired";
  ingestion_surface: string;
  marketplaces: string[];
  observation_profiles: string[];
  semantic_authority: string;
  requires_original_evidence: boolean;
  requires_independent_scope_binding: boolean;
  policy: {
    cookie_or_local_storage: false;
    internal_api: false;
    captcha_bypass: false;
  };
};

type MarketPriceBand = {
  currency: string;
  listing_count: number;
  comparable_listing_count: number;
  price_distribution: {
    minimum: string;
    p25: string;
    median: string;
    p75: string;
    maximum: string;
  };
  sales_is_actual: false;
};

type MarketRadarCohort = {
  candidate_key: string;
  product_identity: Record<string, string>;
  variant_key: string;
  counts: {
    observation_rows: number;
    own_listing_rows: number;
    competitor_listing_rows: number;
    unique_competitor_sellers: number;
    supplier_option_rows: number;
    unique_supplier_identities: number;
    checkout_comparable_at_target: number;
  };
  competitor_price_bands: MarketPriceBand[];
  supplier_price_bands_at_target: MarketPriceBand[];
  supplier_alternative_rows: number;
  target_purchase_quantity: number;
  source_grade_counts: Record<string, number>;
  semantic_authorities: string[];
  evidence_ids: string[];
  sales_is_actual: false;
  supplier_offer_created: false;
  actual_cost_created: false;
};

type CommerceWorkspace = {
  contract_version: string;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    actor_id: string;
    roles: string[];
  };
  status: string;
  outcome: Record<string, number | boolean>;
  current_stage: {
    id: string;
    label: string;
    status: string;
    why: string;
    owner: string;
    next_action: string;
    workspace_href: string;
  } | null;
  stages: Stage[];
  capabilities: Capability[];
  native_architecture: NativeModule[];
  benchmark_baseline_policy: {
    requirement: "must_have_native_parity";
    safe_capability_omission_allowed: false;
    mapping_is_not_implementation: true;
    providers_are_runtime_dependencies: false;
    prohibited_patterns_require_safe_jtbd_replacement: true;
    ai_advantage_is_scored_separately: true;
    external_write_allowed: false;
  };
  benchmark_coverage: Benchmark[];
  ai_content_factory: {
    status: string;
    summary: Record<string, number>;
    templates: Array<{ id: string; kind: string }>;
    truth_inputs: string[];
    outputs: string[];
    competitor_asset_copy_allowed: false;
    listing_reference_requires_all_qa_passed: true;
  };
  intelligence_sources: {
    contract_id: string;
    status: string;
    adapters: IntelligenceSourceAdapter[];
    counts: {
      implemented: number;
      contract_only: number;
      external_write_enabled: 0;
    };
    source_gaps: string[];
    control_envelope: {
      capture_requires_current_entity_scope: true;
      capture_requires_independent_evidence_binding: true;
      supplier_offer_created: false;
      actual_cost_created: false;
      sales_fact_inferred: false;
      external_write_allowed: false;
    };
    snapshot_sha256: string;
  };
  read_only_pilots: {
    contract_id: string;
    status: string;
    scope: {
      tenant_ref: string;
      entity_ref: string | null;
      store_ref: string;
      scope_grant_authority_sha256: string | null;
    };
    counts: {
      pilots: number;
      runs: number;
    };
    source_gaps: string[];
    legacy_rows_inferred: false;
    external_write_allowed: false;
    snapshot_sha256: string;
  };
  read_only_claims: {
    contract_id: string;
    status: string;
    scope: {
      tenant_ref: string;
      entity_ref: string | null;
      store_ref: string;
      scope_grant_authority_sha256: string | null;
    };
    counts: {
      claims: number;
      pending_review: number;
      accepted: number;
      rejected: number;
      authority_blocked: number;
    };
    source_gaps: string[];
    legacy_rows_inferred: false;
    formal_fact_promoted: false;
    external_write_allowed: false;
    snapshot_sha256: string;
  };
  ozon_imports: {
    contract_id: string;
    status: string;
    scope: {
      tenant_ref: string;
      entity_ref: string | null;
      store_ref: string;
      scope_grant_authority_sha256: string | null;
    };
    counts: {
      imports: number;
      rows: number;
      accepted_rows: number;
      rejected_rows: number;
    };
    source_gaps: string[];
    legacy_rows_inferred: false;
    formal_fact_promotion_allowed: false;
    external_write_allowed: false;
    snapshot_sha256: string;
  };
  formal_facts: {
    contract_id: string;
    status: string;
    scope: {
      tenant_ref: string;
      entity_ref: string | null;
      store_ref: string;
      scope_grant_authority_sha256: string | null;
    };
    formal_fact_count: number;
    source_gaps: string[];
    legacy_rows_inferred: false;
    claim_source_allowed: false;
    accounting_posted: false;
    external_write_allowed: false;
    approval_created: false;
    permit_created: false;
    snapshot_sha256: string;
  };
  market_radar: {
    contract_id: string;
    status: string;
    query: {
      timezone: string;
      display_currency: string;
      source_grades: string[];
      max_age_hours: number;
      target_purchase_quantity: number;
      currency_conversion_performed: false;
    };
    counts: {
      observed_listings: number;
      unique_exact_identities: number;
      own_listing_rows: number;
      competitor_listing_rows: number;
      unique_competitor_sellers: number;
      supplier_option_rows: number;
      unique_supplier_identities: number;
      checkout_comparable_at_target: number;
      unresolved_or_filtered_rows: number;
    };
    cohorts: MarketRadarCohort[];
    unresolved: {
      count: number;
      details_disclosed: false;
      by_reason: Record<string, number>;
    };
    source_gaps: string[];
    control_envelope: {
      read_only: true;
      research_only: true;
      client_calculation_allowed: false;
      candidate_scoring_performed: false;
      sales_inferred: false;
      supplier_offer_created: false;
      actual_cost_created: false;
      formal_cm3_created: false;
      approval_created: false;
      permit_created: false;
      external_write_allowed: false;
    };
    snapshot_sha256: string;
  };
  product_content: {
    contract_id: string;
    status: string;
    counts: {
      included_products: number;
      approved_passport_sets: number;
      content_draft_ready: number;
      media_qa_ready: number;
      listing_approval_plan_ready: number;
    };
    source_gaps: string[];
    control_envelope: {
      read_only: true;
      raw_product_content_read: boolean;
      content_draft_allowed: boolean;
      listing_draft_allowed: false;
      approval_created: false;
      permit_created: false;
      external_write_allowed: false;
    };
    snapshot_sha256: string;
  };
  agent_team: Agent[];
  source_gaps: string[];
  control_envelope: {
    external_writes: false;
    ozon_write: false;
    supplier_order: false;
    purchase: false;
    payment: false;
    advertising_write: false;
    agent_self_approval: false;
    agent_permit_issuance: false;
    independent_approval_required: true;
    one_time_permit_required: true;
    readback_required: true;
  };
  completion_claim: {
    benchmark_business_flows_fully_covered: boolean;
    benchmark_products_are_runtime_dependencies: false;
    real_profit_loop_complete: boolean;
    automatic_listing_count_is_success_metric: false;
    success_metric: string;
  };
  snapshot_sha256: string;
};

type StrategyPacks = {
  authorized_scope: {
    tenant_ref: string;
    store_refs: string[];
  };
};

const outcomeLabels: Array<[string, string]> = [
  ["observed_listings", "观察 listings"],
  ["unique_exact_identities", "精确商品身份"],
  ["fully_costed_candidates", "完整成本候选"],
  ["downside_positive", "下行情景为正"],
  ["erp_item_sync_succeeded", "ERP 草稿回读"],
  ["published", "已受控发布"],
  ["ordered", "真实订单"],
  ["settled_proven", "结算后已证明"],
];

const statusLabel: Record<string, string> = {
  completed: "已验证",
  ready_for_internal_action: "可做内部动作",
  blocked: "阻断",
  no_data: "无数据",
  verified: "已验证",
  partial: "部分可用",
  not_proven: "未证明",
  waiting_for_evidence: "等待 Evidence",
  ready_for_internal_work: "可做内部工作",
  monitoring: "监控中",
  ready: "可用",
  implemented: "已准入",
  contract_only: "仅合同",
};

function shortHash(value: string) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—";
}

function label(value: string) {
  return statusLabel[value] ?? value;
}

export function CommerceOsConsole() {
  const [session, setSession] = useState<WebSession | null>(null);
  const [stores, setStores] = useState<string[]>([]);
  const [storeRef, setStoreRef] = useState("");
  const [workspace, setWorkspace] = useState<CommerceWorkspace | null>(null);
  const [scopeBusy, setScopeBusy] = useState(true);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [error, setError] = useState("");

  const redirectForAuth = useCallback((status: number) => {
    if (status === 401) {
      window.location.assign("/login");
      return true;
    }
    if (status === 428) {
      window.location.assign("/mfa");
      return true;
    }
    return false;
  }, []);

  const loadScope = useCallback(async (signal?: AbortSignal) => {
    setScopeBusy(true);
    setError("");
    const [sessionResponse, packsResponse] = await Promise.all([
      fetchJson<WebSession | { detail?: string }>("/auth/session", {
        cache: "no-store",
        signal,
      }),
      fetchJson<StrategyPacks | { detail?: string }>(
        "/backend/v1/seller-os/strategy-packs",
        { cache: "no-store", signal },
      ),
    ]);
    if (
      redirectForAuth(sessionResponse.status) ||
      redirectForAuth(packsResponse.status)
    ) {
      return;
    }
    const [sessionBody, packsBody] = await Promise.all([
      sessionResponse.json(),
      packsResponse.json(),
    ]);
    if (!sessionResponse.ok || !packsResponse.ok) {
      const detail =
        ("detail" in packsBody && packsBody.detail) ||
        ("detail" in sessionBody && sessionBody.detail) ||
        "授权店铺作用域暂不可用";
      setError(String(detail));
      setScopeBusy(false);
      return;
    }
    const authorized = (packsBody as StrategyPacks).authorized_scope.store_refs;
    setSession(sessionBody as WebSession);
    setStores(authorized);
    setStoreRef((current) =>
      current && authorized.includes(current) ? current : authorized[0] ?? "",
    );
    setScopeBusy(false);
  }, [redirectForAuth]);

  const loadWorkspace = useCallback(async (store: string, signal?: AbortSignal) => {
    if (!store) return;
    setWorkspaceBusy(true);
    setError("");
    const response = await fetchJson<CommerceWorkspace | { detail?: string }>(
      `/backend/v1/commerce-os/workspace?store_ref=${encodeURIComponent(store)}`,
      { cache: "no-store", signal },
    );
    if (redirectForAuth(response.status)) return;
    const body = await response.json();
    if (!response.ok) {
      const detail = "detail" in body ? body.detail : "Commerce OS 暂不可用";
      setError(String(detail));
      setWorkspaceBusy(false);
      return;
    }
    setWorkspace(body as CommerceWorkspace);
    setWorkspaceBusy(false);
  }, [redirectForAuth]);

  useEffect(() => {
    const controller = new AbortController();
    void loadScope(controller.signal);
    return () => controller.abort("commerce scope unmounted");
  }, [loadScope]);

  useEffect(() => {
    if (!storeRef) return;
    const controller = new AbortController();
    void loadWorkspace(storeRef, controller.signal);
    return () => controller.abort("commerce workspace changed");
  }, [loadWorkspace, storeRef]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/" className={styles.backLink}>
          <ArrowLeft size={16} />
          返回经营平台
        </Link>
        <div className={styles.productMark}>
          <span><Boxes size={19} /></span>
          <div>
            <strong>Commerce OS</strong>
            <small>KJDS NATIVE ERP · AGENT TEAM</small>
          </div>
        </div>
        <label className={styles.storePicker}>
          <Store size={15} />
          <span>授权店铺</span>
          <select
            value={storeRef}
            onChange={(event) => setStoreRef(event.target.value)}
            disabled={scopeBusy || stores.length === 0}
            aria-label="选择授权店铺"
          >
            {stores.map((store) => <option key={store}>{store}</option>)}
          </select>
        </label>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>
            <ShieldCheck size={14} />
            ONE TRUTH KERNEL · NO SECOND ERP TRUTH
          </span>
          <h1>原生跨境 ERP，<em>Agent 负责推进，权威模块负责判定</em></h1>
          <p>
            毛子、荔枝、芒果店长、店小秘、妙手、无忧易售、Seerfar 与 LinkFox
            是 Must-have 能力基准。商品、订单、采购、库存、履约、利润、
            Evidence 和审批由 KJDS 一套经营内核贯通；页面不把“功能已编码”冒充真实闭环。
          </p>
        </div>
        <aside>
          <LockKeyhole size={24} />
          <strong>外部写保持关闭</strong>
          <p>Ozon、供应商、采购、付款和广告都未授权自动执行。</p>
          <small>
            {workspace
              ? `快照 ${shortHash(workspace.snapshot_sha256)}`
              : "正在读取服务端快照"}
          </small>
        </aside>
      </section>

      {error ? (
        <section className={styles.errorState} role="alert">
          <CircleDashed size={22} />
          <div><strong>经营真源暂不可用</strong><p>{error}</p></div>
          <button
            type="button"
            onClick={() =>
              storeRef ? void loadWorkspace(storeRef) : void loadScope()
            }
          >
            重试
          </button>
        </section>
      ) : null}

      {(scopeBusy || workspaceBusy) && !workspace ? (
        <section className={styles.loadingState} role="status">
          <RefreshCw size={22} />
          <div>
            <strong>正在读取授权作用域与经营权威</strong>
            <p>数据返回前不会填充演示 SKU、利润或完成状态。</p>
          </div>
        </section>
      ) : null}

      {workspace ? (
        <>
          <section className={styles.scopeBar}>
            <div><span>Tenant</span><strong>{workspace.scope.tenant_ref}</strong></div>
            <div>
              <span>Entity</span>
              <strong>{workspace.scope.entity_ref ?? "no_data"}</strong>
            </div>
            <div><span>Store</span><strong>{workspace.scope.store_ref}</strong></div>
            <div><span>As of</span><strong>{workspace.as_of}</strong></div>
          </section>

          <section className={styles.metricGrid} aria-label="真实经营漏斗">
            {outcomeLabels.map(([key, text]) => (
              <article key={key}>
                <span>{text}</span>
                <strong>{String(workspace.outcome[key] ?? 0)}</strong>
              </article>
            ))}
          </section>

          <section className={styles.currentStage}>
            <Workflow size={23} />
            <div>
              <span>CURRENT CONTROL POINT</span>
              <h2>{workspace.current_stage?.label ?? "全部阶段已完成"}</h2>
              <p>{workspace.current_stage?.why ?? workspace.completion_claim.success_metric}</p>
            </div>
            {workspace.current_stage ? (
              <Link href={workspace.current_stage.workspace_href}>
                {workspace.current_stage.owner} · {workspace.current_stage.next_action}
              </Link>
            ) : null}
          </section>

          <section className={styles.section}>
            <header>
              <span>SCOPED MARKET RADAR · EXACT IDENTITY</span>
              <h2>同一商品先聚合 cohort，再进入候选</h2>
              <p>
                服务端按 exact product identity + exact variant 分离自有 Listing、同行与
                供应商；价格带按币种隔离，listing 数不冒充 SKU，公开信号不冒充销量。
              </p>
            </header>
            <div
              className={styles.radarAuthority}
              data-state={workspace.market_radar.status}
            >
              <div className={styles.radarSummary}>
                <Fingerprint size={25} />
                <div>
                  <span>MARKET RADAR AUTHORITY</span>
                  <h3>{label(workspace.market_radar.status)}</h3>
                  <small>
                    {workspace.market_radar.contract_id} ·{" "}
                    {shortHash(workspace.market_radar.snapshot_sha256)}
                  </small>
                </div>
                <div className={styles.radarQuery}>
                  <span>来源 {workspace.market_radar.query.source_grades.join("/")}</span>
                  <span>新鲜度 ≤ {workspace.market_radar.query.max_age_hours}h</span>
                  <span>目标采购 {workspace.market_radar.query.target_purchase_quantity} 件</span>
                  <span>展示币种 {workspace.market_radar.query.display_currency}</span>
                </div>
              </div>
              <div className={styles.radarMetrics}>
                <article>
                  <span>观察 listings</span>
                  <strong>{workspace.market_radar.counts.observed_listings}</strong>
                </article>
                <article>
                  <span>唯一精确身份</span>
                  <strong>{workspace.market_radar.counts.unique_exact_identities}</strong>
                </article>
                <article>
                  <span>自有 Listing</span>
                  <strong>{workspace.market_radar.counts.own_listing_rows}</strong>
                </article>
                <article>
                  <span>同行 listings</span>
                  <strong>{workspace.market_radar.counts.competitor_listing_rows}</strong>
                </article>
                <article>
                  <span>唯一同行卖家</span>
                  <strong>{workspace.market_radar.counts.unique_competitor_sellers}</strong>
                </article>
                <article>
                  <span>唯一供应商</span>
                  <strong>{workspace.market_radar.counts.unique_supplier_identities}</strong>
                </article>
                <article>
                  <span>目标数量可比</span>
                  <strong>{workspace.market_radar.counts.checkout_comparable_at_target}</strong>
                </article>
                <article>
                  <span>未解析/被过滤</span>
                  <strong>{workspace.market_radar.counts.unresolved_or_filtered_rows}</strong>
                </article>
              </div>
              {workspace.market_radar.cohorts.length ? (
                <div className={styles.radarCohorts}>
                  {workspace.market_radar.cohorts.slice(0, 12).map((cohort) => (
                    <article key={cohort.candidate_key}>
                      <header>
                        <div>
                          <span>EXACT VARIANT</span>
                          <strong>{cohort.variant_key}</strong>
                        </div>
                        <small>{shortHash(cohort.candidate_key)}</small>
                      </header>
                      <dl>
                        <div>
                          <dt>同行 / 卖家</dt>
                          <dd>
                            {cohort.counts.competitor_listing_rows} /{" "}
                            {cohort.counts.unique_competitor_sellers}
                          </dd>
                        </div>
                        <div>
                          <dt>供应行 / 供应商</dt>
                          <dd>
                            {cohort.counts.supplier_option_rows} /{" "}
                            {cohort.counts.unique_supplier_identities}
                          </dd>
                        </div>
                        <div>
                          <dt>目标数量可比</dt>
                          <dd>{cohort.counts.checkout_comparable_at_target}</dd>
                        </div>
                      </dl>
                      <div className={styles.radarBands}>
                        {cohort.competitor_price_bands.map((band) => (
                          <span key={`market-${band.currency}`}>
                            同行 {band.currency} p50 {band.price_distribution.median}
                          </span>
                        ))}
                        {cohort.supplier_price_bands_at_target.map((band) => (
                          <span key={`supply-${band.currency}`}>
                            供应 {band.currency} p50 {band.price_distribution.median}
                          </span>
                        ))}
                      </div>
                      <footer>
                        Evidence {cohort.evidence_ids.length} ·
                        source grade {Object.keys(cohort.source_grade_counts).join("/")}
                      </footer>
                    </article>
                  ))}
                </div>
              ) : (
                <div className={styles.radarEmpty}>
                  <strong>当前没有可聚合的 exact identity/variant cohort</strong>
                  <p>
                    {workspace.market_radar.source_gaps.join(" · ") ||
                      "等待带作用域、Evidence、来源等级与新鲜度的 Observation。"}
                  </p>
                </div>
              )}
              <div className={styles.radarLocks}>
                <strong>研究语义锁</strong>
                <span>不跨币种换算</span>
                <span>100 件价不能筛 3 件 Pilot</span>
                <span>Observation ≠ Offer / actual cost</span>
                <span>销量推断：关闭</span>
                <span>外部写入：关闭</span>
              </div>
            </div>
          </section>

          <section className={styles.section}>
            <header>
              <span>NATIVE INTELLIGENCE INGESTION</span>
              <h2>来源适配器权威，不靠浏览器状态拼 ERP</h2>
              <p>
                Seller API、官方导出、授权连接器和允许的公开页按独立合同进入同一
                Observation/Catalog 内核；Cookie、localStorage、内部 API 与验证码绕过均被禁止。
              </p>
            </header>
            <div className={styles.sourceAuthority}>
              <div className={styles.sourceAuthoritySummary}>
                <Fingerprint size={24} />
                <div>
                  <span>SOURCE REGISTRY</span>
                  <h3>{label(workspace.intelligence_sources.status)}</h3>
                  <small>
                    {workspace.intelligence_sources.contract_id} ·{" "}
                    {shortHash(workspace.intelligence_sources.snapshot_sha256)}
                  </small>
                </div>
                <dl>
                  <div>
                    <dt>已准入</dt>
                    <dd>{workspace.intelligence_sources.counts.implemented}</dd>
                  </div>
                  <div>
                    <dt>仅合同</dt>
                    <dd>{workspace.intelligence_sources.counts.contract_only}</dd>
                  </div>
                  <div>
                    <dt>外部写</dt>
                    <dd>{workspace.intelligence_sources.counts.external_write_enabled}</dd>
                  </div>
                </dl>
              </div>
              <div className={styles.sourceAdapterGrid}>
                <article data-state={workspace.read_only_pilots.status}>
                  <div>
                    <strong>Ozon 只读 Pilot / Run</strong>
                    <span>
                      {label(workspace.read_only_pilots.status)} · Pilot{" "}
                      {workspace.read_only_pilots.counts.pilots} · Run{" "}
                      {workspace.read_only_pilots.counts.runs}
                    </span>
                  </div>
                  <p>
                    tenant / entity / store 原生授权；Run 通过 Pilot FK 在 SQL
                    作用域内读取
                  </p>
                  <small>
                    {workspace.read_only_pilots.scope.entity_ref
                      ? `entity ${workspace.read_only_pilots.scope.entity_ref}`
                      : "entity authority no_data"}
                  </small>
                  <footer>
                    legacy 不推断 · external write false ·{" "}
                    {shortHash(workspace.read_only_pilots.snapshot_sha256)}
                  </footer>
                </article>
                <article data-state={workspace.read_only_claims.status}>
                  <div>
                    <strong>Ozon 只读 Claim 复核账</strong>
                    <span>
                      {label(workspace.read_only_claims.status)} · Claim{" "}
                      {workspace.read_only_claims.counts.claims} · 待复核{" "}
                      {workspace.read_only_claims.counts.pending_review}
                    </span>
                  </div>
                  <p>
                    Claim → Run → Pilot 同作用域复核；accepted 仍不是正式库存或价格事实
                  </p>
                  <small>
                    {workspace.read_only_claims.scope.entity_ref
                      ? `entity ${workspace.read_only_claims.scope.entity_ref}`
                      : "entity authority no_data"}
                  </small>
                  <footer>
                    legacy 不推断 · formal fact false · external write false ·{" "}
                    {shortHash(workspace.read_only_claims.snapshot_sha256)}
                  </footer>
                </article>
                <article data-state={workspace.ozon_imports.status}>
                  <div>
                    <strong>Ozon 官方导入 staging</strong>
                    <span>
                      {label(workspace.ozon_imports.status)} · 文件{" "}
                      {workspace.ozon_imports.counts.imports} · 行{" "}
                      {workspace.ozon_imports.counts.rows}
                    </span>
                  </div>
                  <p>
                    原始 CSV/XLSX 仅进入作用域 staging；独立复核前不晋升正式 Fact
                  </p>
                  <small>
                    {workspace.ozon_imports.scope.entity_ref
                      ? `entity ${workspace.ozon_imports.scope.entity_ref}`
                      : "entity authority no_data"}
                  </small>
                  <footer>
                    legacy 不推断 · formal promotion false · external write false ·{" "}
                    {shortHash(workspace.ozon_imports.snapshot_sha256)}
                  </footer>
                </article>
                <article data-state={workspace.formal_facts.status}>
                  <div>
                    <strong>Formal Fact 原生权威</strong>
                    <span>
                      {label(workspace.formal_facts.status)} · 正式 Fact{" "}
                      {workspace.formal_facts.formal_fact_count}
                    </span>
                  </div>
                  <p>
                    仅从 scoped Import 经独立 Evidence 复核和 exact Product/SKU
                    映射晋升
                  </p>
                  <small>
                    {workspace.formal_facts.scope.entity_ref
                      ? `entity ${workspace.formal_facts.scope.entity_ref}`
                      : "entity authority no_data"}
                  </small>
                  <footer>
                    legacy 不推断 · Claim 不直升 · accounting false · external write false ·{" "}
                    {shortHash(workspace.formal_facts.snapshot_sha256)}
                  </footer>
                </article>
                {workspace.intelligence_sources.adapters.length ? (
                  workspace.intelligence_sources.adapters.map((adapter) => (
                    <article key={adapter.adapter_id} data-state={adapter.status}>
                      <div>
                        <strong>{adapter.adapter_id}</strong>
                        <span>{label(adapter.status)} · {adapter.max_source_grade} 级上限</span>
                      </div>
                      <p>
                        {adapter.ingestion_surface} · {adapter.marketplaces.join(" / ")}
                      </p>
                      <small>{adapter.semantic_authority}</small>
                      <footer>
                        {adapter.requires_original_evidence ? "需原始 Evidence" : "允许公开观察 Evidence"}
                        {" · "}
                        {adapter.requires_independent_scope_binding ? "需独立作用域绑定" : "无需作用域绑定"}
                      </footer>
                    </article>
                  ))
                ) : (
                  <article data-state="no_data">
                    <strong>no_data</strong>
                    <p>当前作用域尚无可读取的来源适配器权威。</p>
                  </article>
                )}
              </div>
              <div className={styles.sourceAuthorityLocks}>
                <strong>语义隔离</strong>
                <span>公开价格 ≠ Supplier Offer</span>
                <span>评论/页面信号 ≠ 销量</span>
                <span>来源等级 ≠ 业务事实升级</span>
                <span>外部写入：关闭</span>
              </div>
            </div>
          </section>

          <section className={styles.section}>
            <header>
              <span>OPERATING FLOW</span>
              <h2>13 段经营状态机</h2>
              <p>只有候选级权威记录才能推进；通用媒体、观察或执行计数不能跨阶段代替。</p>
            </header>
            <div className={styles.stageGrid}>
              {workspace.stages.map((stage) => (
                <article key={stage.id} data-state={stage.status}>
                  <div>
                    <span>{String(stage.sequence).padStart(2, "0")}</span>
                    {stage.status === "completed"
                      ? <CheckCircle2 size={17} />
                      : <CircleDashed size={17} />}
                  </div>
                  <h3>{stage.label}</h3>
                  <strong>{label(stage.status)} · {stage.qualified_record_count}</strong>
                  <p>{stage.why}</p>
                  <footer>{stage.owner} · SLA {stage.sla_hours}h</footer>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <header>
              <span>NATIVE ARCHITECTURE</span>
              <h2>KJDS 自有经营模块</h2>
              <p>开源侧车通过 Adapter 复用；Canonical Facts、CM3、Evidence 和治理不外包。</p>
              <Link className={styles.workspaceLink} href="/oms">
                打开原生 OMS
                <Workflow size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/inventory">
                打开库存与履约
                <Boxes size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/procurement">
                打开采购与收货控制
                <Boxes size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/accounts-payable">
                打开应付与供应商付款控制
                <Landmark size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/returns">
                打开退货与售后财务控制
                <Workflow size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/customer-service">
                打开客服 Case 与消息权威
                <Workflow size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/delivery-exceptions">
                打开物流交付与异常权威
                <Workflow size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/warehouse-fulfillment">
                打开仓库执行与包裹交接权威
                <Workflow size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/channel-accounts">
                打开渠道账户与运行身份权威
                <Workflow size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/native-parity">
                打开原生同等能力验收权威
                <Workflow size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/finance-control">
                打开结算与现金控制
                <Landmark size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/profit-ledger">
                打开十五项实际利润账
                <Landmark size={15} />
              </Link>
            </header>
            <div className={styles.moduleGrid}>
              {workspace.native_architecture.map((module) => (
                <article key={module.module_id}>
                  <Boxes size={19} />
                  <div>
                    <h3>{module.label}</h3>
                    <p>{module.authority_modules.join(" · ")}</p>
                    <small>
                      {module.verified_capability_count}/{module.capability_count} 真实验收 ·
                      {module.third_party_erp_dependency ? " 外部真相" : " KJDS 真相"}
                    </small>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <header>
              <span>SCOPED PIM · PASSPORT · CONTENT</span>
              <h2>商品真源到 Listing 审批计划</h2>
              <p>
                数量与状态直接来自 tenant / entity / store / as-of 服务端权威；
                页面不从市场标题推导内容就绪，也不把审批计划当作 Approval 或 Permit。
              </p>
              <Link className={styles.workspaceLink} href="/pim">
                打开商品主数据 PIM
                <Boxes size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/listings">
                打开 Listing 生命周期
                <Boxes size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/media-factory">
                打开内容媒体工厂
                <Boxes size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/sourcing-intelligence">
                打开原生供应智能
                <Boxes size={15} />
              </Link>
              <Link className={styles.workspaceLink} href="/seller-erp-bridge">
                打开授权 Seller ERP Bridge
                <Boxes size={15} />
              </Link>
            </header>
            <div
              className={styles.productAuthority}
              data-state={workspace.product_content.status}
            >
              <div className={styles.productAuthorityLead}>
                <Boxes size={25} />
                <div>
                  <span>PRODUCT CONTENT AUTHORITY</span>
                  <h3>{label(workspace.product_content.status)}</h3>
                  <small>
                    {workspace.product_content.contract_id} ·{" "}
                    {shortHash(workspace.product_content.snapshot_sha256)}
                  </small>
                </div>
              </div>
              <div className={styles.productAuthorityCounts}>
                <article>
                  <span>作用域内 Product</span>
                  <strong>{workspace.product_content.counts.included_products}</strong>
                </article>
                <article>
                  <span>三类 Passport 已批准</span>
                  <strong>{workspace.product_content.counts.approved_passport_sets}</strong>
                </article>
                <article>
                  <span>可生成内容草稿</span>
                  <strong>{workspace.product_content.counts.content_draft_ready}</strong>
                </article>
                <article>
                  <span>媒体 QA 已通过</span>
                  <strong>{workspace.product_content.counts.media_qa_ready}</strong>
                </article>
                <article>
                  <span>Listing 审批计划就绪</span>
                  <strong>{workspace.product_content.counts.listing_approval_plan_ready}</strong>
                </article>
              </div>
              <div className={styles.productAuthorityLocks}>
                <strong>执行锁</strong>
                <span>审批计划 ≠ 独立 Approval</span>
                <span>Approval ≠ 一次性 Permit</span>
                <span>Ozon 外部写入：关闭</span>
              </div>
              <div className={styles.productAuthorityGaps}>
                <strong>当前 Evidence / 真源缺口</strong>
                {workspace.product_content.source_gaps.length ? (
                  <ul>
                    {workspace.product_content.source_gaps.map((gap) => (
                      <li key={gap}>{gap}</li>
                    ))}
                  </ul>
                ) : (
                  <p>该作用域未报告 Product/content 来源缺口。</p>
                )}
              </div>
            </div>
          </section>

          <section className={styles.twoColumn}>
            <section className={styles.section}>
              <header>
                <span>CAPABILITY BENCHMARKS</span>
                <h2>市场已验证的基础功能，逐项原生覆盖</h2>
              </header>
              <p>
                Must-have 基线；安全能力不可省略，映射不等于实现，AI 优势单独验收。
                第三方产品不是运行依赖，外部写仍关闭。
              </p>
              <div className={styles.benchmarkList}>
                {workspace.benchmark_coverage.map((item) => (
                  <article key={item.benchmark_id}>
                    <div>
                      <strong>{item.display_name}</strong>
                      <small>
                        {item.evidence_tier} 级观察 · must_have_native_parity
                      </small>
                    </div>
                    <span>{item.native_verified_count}/{item.benchmark_capability_count}</span>
                    <p>{item.why}</p>
                    <small>
                      原生待验 {item.native_gap_capability_ids.length} 项 ·
                      安全能力允许遗漏：否 · 映射即实现：否
                    </small>
                    {item.workflow_mapping ? (
                      <details className={styles.workflowMapping}>
                        <summary>
                          <strong>
                            {item.workflow_mapping.mapped_count}/
                            {item.workflow_mapping.observed_capability_count} 项工作流已映射
                          </strong>
                          <span>映射 ≠ 实现 · 外部写关闭</span>
                        </summary>
                        <div className={styles.mappingSummary}>
                          {Object.entries(item.workflow_mapping.adoption_summary).map(
                            ([decision, count]) => (
                              <span key={decision}>
                                {decision} {count}
                              </span>
                            ),
                          )}
                          <a
                            href={item.workflow_mapping.source.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            C 级来源
                          </a>
                        </div>
                        <div className={styles.workflowCapabilityList}>
                          {item.workflow_mapping.capabilities.map((capability) => (
                            <article key={capability.id}>
                              <header>
                                <strong>{capability.observed}</strong>
                                <span>
                                  {capability.wave} · {capability.adoption} ·{" "}
                                  {capability.implementation_status}
                                </span>
                              </header>
                              <p>原生目标：{capability.kjds_target}</p>
                              <small>边界：{capability.boundary}</small>
                            </article>
                          ))}
                        </div>
                      </details>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>

            <section className={styles.section}>
              <header>
                <span>AI CONTENT FACTORY</span>
                <h2>图片、视频与 Listing 草稿</h2>
              </header>
              <div className={styles.factoryCard}>
                <Factory size={28} />
                <strong>{label(workspace.ai_content_factory.status)}</strong>
                <p>
                  只从三类 Passport、类目 schema 与有权素材生成；竞品标题和图片不可复制。
                </p>
                <div>
                  {workspace.ai_content_factory.outputs.map((item) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
                <footer>
                  QA 全过后才可引用 · Manifest{" "}
                  {workspace.ai_content_factory.summary.manifest_count ?? 0}
                </footer>
              </div>
            </section>
          </section>

          <section className={styles.section}>
            <header>
              <span>AGENT TEAM</span>
              <h2>12 个责任 Agent 的真实 handoff</h2>
              <p>Agent 可归一、复算、生成草稿与内部任务；不可自批、自发 Permit 或外部写。</p>
            </header>
            <div className={styles.agentGrid}>
              {workspace.agent_team.map((agent) => (
                <article key={agent.agent_id}>
                  <Bot size={19} />
                  <div>
                    <span>{label(agent.status)}</span>
                    <h3>{agent.name}</h3>
                    <p>{agent.current_focus} · {agent.why}</p>
                    <small>{agent.output_artifact} · 队列 {agent.queued_work_item_count}</small>
                  </div>
                  <Link href={agent.workspace_href}>下一步</Link>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.gaps}>
            <Fingerprint size={20} />
            <div>
              <h2>当前 source gaps</h2>
              {workspace.source_gaps.length ? (
                <ul>
                  {workspace.source_gaps.map((gap) => <li key={gap}>{gap}</li>)}
                </ul>
              ) : <p>服务端快照未报告来源缺口。</p>}
            </div>
            <aside>
              <strong>
                {workspace.completion_claim.real_profit_loop_complete ? "闭环已证明" : "真实盈利闭环未完成"}
              </strong>
              <span>自动上品数量不是成功指标</span>
            </aside>
          </section>
        </>
      ) : null}
    </main>
  );
}
