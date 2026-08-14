"use client";

import {
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchJson } from "../../lib/fetch-json";
import type {
  CandidateCollection,
  CategoryPath,
  GrowthChannelCapabilities,
  MoneyProjection,
  OperatingPlan,
  ProfitAnalytics,
  ProfitCandidate,
  ProfitLineage,
  ProfitPortfolio,
  ProfitRemediation,
  ProfitTruthReadiness,
  ProfitWorkspace,
  StoreCategoryRoute,
  StoreProfileProposal,
  StoreRoutingMatrix,
} from "./contracts";
import styles from "./profit-command.module.css";

export type ProfitSurface =
  | "overview"
  | "products"
  | "product-detail"
  | "routing"
  | "truth"
  | "remediation"
  | "lineage";

type StrategyPacks = {
  authorized_scope: { tenant_ref: string; store_refs: string[] };
};

type CandidateDetail = {
  status: string;
  candidate: ProfitCandidate;
  snapshot_sha256: string;
};

const surfaces: Array<{ id: ProfitSurface; href: string; label: string }> = [
  { id: "overview", href: "/profit-command", label: "利润总览" },
  { id: "products", href: "/profit-command/products", label: "商品利润" },
  { id: "routing", href: "/profit-command/routing", label: "店铺类目路由" },
  { id: "truth", href: "/profit-command/truth", label: "利润真相门禁" },
  { id: "remediation", href: "/profit-command/remediation", label: "利润修复" },
  { id: "lineage", href: "/profit-command/lineage", label: "数据血缘" },
];

const profitBases: Array<{ key: keyof ProfitCandidate["profit"]; label: string; note: string }> = [
  { key: "scenario_profit", label: "情景利润", note: "模型场景，不等于实际利润" },
  { key: "risk_adjusted_profit", label: "风险利润", note: "downside / CVaR 决策口径" },
  { key: "accrual_profit", label: "权责利润", note: "订单与费用归属后的利润" },
  { key: "settlement_profit", label: "结算利润", note: "平台结算核销后的利润" },
  { key: "cash_profit", label: "现金利润", note: "银行到账后的最终口径" },
];

const analyticsMetricKeys = [
  ["scenario_expected_cm3", "情景期望 CM3"],
  ["risk_downside_cm3", "风险 downside CM3"],
  ["accrual_profit", "权责利润"],
  ["settlement_profit", "结算利润"],
  ["cash_profit", "现金利润"],
] as const;

const stageLabels: Record<string, string> = {
  raw_evidence: "原始证据",
  normalized_observation: "标准观察",
  reviewed_observation: "复核观察",
  formal_fact: "正式事实",
  decision_snapshot: "决策快照",
};

function money(value: MoneyProjection | undefined | null): string {
  if (!value || value.amount === null) return value?.status ?? "no_data";
  return `${value.currency ?? ""} ${value.amount}`.trim();
}

function scenarioValue(candidate: ProfitCandidate, basis: keyof ProfitCandidate["profit"]): string {
  const value = candidate.profit[basis];
  if (basis === "scenario_profit") {
    return value.expected_cm3 === null || value.expected_cm3 === undefined
      ? value.status ?? "no_data"
      : `${value.currency ?? ""} ${value.expected_cm3}`;
  }
  if (basis === "risk_adjusted_profit") {
    return value.downside_cm3 === null || value.downside_cm3 === undefined
      ? value.status ?? "no_data"
      : `${value.currency ?? ""} ${value.downside_cm3}`;
  }
  return money(value);
}

function categoryText(path: CategoryPath | null | undefined): string {
  if (!path) return "no_data";
  return [path.level_1?.name, path.level_2?.name, path.level_3?.name]
    .filter(Boolean)
    .join(" / ") || path.leaf_category_id || "no_data";
}

function backendHref(value: string): string {
  return value.startsWith("/v1/") ? `/backend${value}` : value;
}

function statusTone(value: string | undefined): string {
  return value === "available" || value === "ready" || value === "primary_store"
    ? styles.good
    : value === "blocked" || value === "stop_loss" || value === "exit"
      ? styles.danger
      : "";
}

export function ProfitCommandConsole({
  surface,
  candidateId,
}: {
  surface: ProfitSurface;
  candidateId?: string;
}) {
  const [storeRefs, setStoreRefs] = useState<string[]>([]);
  const [selectedStore, setSelectedStore] = useState("");
  const [workspace, setWorkspace] = useState<ProfitWorkspace | null>(null);
  const [analytics, setAnalytics] = useState<ProfitAnalytics | null>(null);
  const [collection, setCollection] = useState<CandidateCollection | null>(null);
  const [portfolio, setPortfolio] = useState<ProfitPortfolio | null>(null);
  const [operatingPlan, setOperatingPlan] = useState<OperatingPlan | null>(null);
  const [storeRouting, setStoreRouting] = useState<StoreRoutingMatrix | null>(null);
  const [profileProposal, setProfileProposal] = useState<StoreProfileProposal | null>(null);
  const [growthChannels, setGrowthChannels] = useState<GrowthChannelCapabilities | null>(null);
  const [truthReadiness, setTruthReadiness] = useState<ProfitTruthReadiness | null>(null);
  const [remediation, setRemediation] = useState<ProfitRemediation | null>(null);
  const [lineage, setLineage] = useState<ProfitLineage | null>(null);
  const [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [decisionClass, setDecisionClass] = useState("");
  const [remediationOffset, setRemediationOffset] = useState(0);
  const [refreshToken, setRefreshToken] = useState(0);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("正在读取授权经营作用域…");

  useEffect(() => {
    let active = true;
    const loadScope = async () => {
      const response = await fetchJson<StrategyPacks>("/backend/v1/seller-os/strategy-packs");
      const payload = await response.json();
      if (!active) return;
      if (!response.ok) {
        setNotice(`授权作用域读取失败（HTTP ${response.status || "offline"}）`);
        setLoading(false);
        return;
      }
      const refs = payload.authorized_scope.store_refs;
      setStoreRefs(refs);
      setSelectedStore((current) => current || refs[0] || "");
      if (!refs.length) {
        setNotice("当前身份没有授权店铺；大屏保持 forbidden/no_data。");
        setLoading(false);
      }
    };
    void loadScope();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedStore) return;
    let active = true;
    const load = async () => {
      setLoading(true);
      setNotice(`正在读取 ${selectedStore} 的利润、类目路由与证据快照…`);
      const store = encodeURIComponent(selectedStore);
      const decision = decisionClass
        ? `&decision_class=${encodeURIComponent(decisionClass)}`
        : "";
      const search = query ? `&query=${encodeURIComponent(query)}` : "";
      const detailPath = candidateId
        ? `/backend/v1/profit-command/candidates/${encodeURIComponent(candidateId)}?store_ref=${store}`
        : null;
      const [
        workspaceResponse,
        analyticsResponse,
        candidatesResponse,
        portfolioResponse,
        planResponse,
        routingResponse,
        profileProposalResponse,
        growthChannelsResponse,
        truthReadinessResponse,
        remediationResponse,
        lineageResponse,
        detailResponse,
      ] = await Promise.all([
        fetchJson<ProfitWorkspace>(`/backend/v1/profit-command/workspace?store_ref=${store}`),
        fetchJson<ProfitAnalytics>(`/backend/v1/profit-command/analytics?store_ref=${store}`),
        fetchJson<CandidateCollection>(
          `/backend/v1/profit-command/candidates?store_ref=${store}&page_size=100${decision}${search}`,
        ),
        fetchJson<ProfitPortfolio>("/backend/v1/profit-command/portfolio"),
        fetchJson<OperatingPlan>(`/backend/v1/seller-os/operating-plan?store_ref=${store}`),
        fetchJson<StoreRoutingMatrix>("/backend/v1/seller-os/store-routing"),
        fetchJson<StoreProfileProposal>(`/backend/v1/seller-os/store-profile-proposal?store_ref=${store}&seller_tier=beginner`),
        fetchJson<GrowthChannelCapabilities>("/backend/v1/growth-channels/capabilities"),
        fetchJson<ProfitTruthReadiness>(`/backend/v1/profit-command/truth-readiness?store_ref=${store}`),
        fetchJson<ProfitRemediation>(`/backend/v1/profit-command/remediation?store_ref=${store}&queue_page_size=50&queue_offset=${remediationOffset}`),
        fetchJson<ProfitLineage>(
          `/backend/v1/profit-command/lineage?store_ref=${store}${candidateId ? `&candidate_id=${encodeURIComponent(candidateId)}` : ""}`,
        ),
        detailPath ? fetchJson<CandidateDetail>(detailPath) : Promise.resolve(null),
      ]);
      if (!active) return;
      const workspacePayload = await workspaceResponse.json();
      const analyticsPayload = await analyticsResponse.json();
      const candidatesPayload = await candidatesResponse.json();
      const portfolioPayload = await portfolioResponse.json();
      const planPayload = await planResponse.json();
      const routingPayload = await routingResponse.json();
      const profileProposalPayload = await profileProposalResponse.json();
      const growthChannelsPayload = await growthChannelsResponse.json();
      const truthReadinessPayload = await truthReadinessResponse.json();
      const remediationPayload = await remediationResponse.json();
      const lineagePayload = await lineageResponse.json();
      const detailPayload = detailResponse ? await detailResponse.json() : null;
      if (!active) return;
      setWorkspace(workspaceResponse.ok ? workspacePayload : null);
      setAnalytics(analyticsResponse.ok ? analyticsPayload : null);
      setCollection(candidatesResponse.ok ? candidatesPayload : null);
      setPortfolio(portfolioResponse.ok ? portfolioPayload : null);
      setOperatingPlan(planResponse.ok ? planPayload : null);
      setStoreRouting(routingResponse.ok ? routingPayload : null);
      setProfileProposal(profileProposalResponse.ok ? profileProposalPayload : null);
      setGrowthChannels(growthChannelsResponse.ok ? growthChannelsPayload : null);
      setTruthReadiness(truthReadinessResponse.ok ? truthReadinessPayload : null);
      setRemediation(remediationResponse.ok ? remediationPayload : null);
      setLineage(lineageResponse.ok ? lineagePayload : null);
      setDetail(detailResponse?.ok && detailPayload ? detailPayload : null);
      const failed = [
        workspaceResponse,
        analyticsResponse,
        candidatesResponse,
        portfolioResponse,
        planResponse,
        routingResponse,
        profileProposalResponse,
        growthChannelsResponse,
        truthReadinessResponse,
        remediationResponse,
        lineageResponse,
      ].filter((response) => !response.ok).length;
      setNotice(
        failed
          ? `${failed} 个只读投影暂不可用；其余区域保持真实数据，未补演示值。`
          : `已读取 ${selectedStore} 的同一时点经营快照；页面不执行利润重算。`,
      );
      setLoading(false);
    };
    void load();
    return () => { active = false; };
  }, [candidateId, decisionClass, query, refreshToken, remediationOffset, selectedStore]);

  const submitFilter = (event: FormEvent) => {
    event.preventDefault();
    setQuery(queryDraft.trim());
  };

  const currentCandidate = detail?.candidate
    ?? collection?.candidates.find((candidate) => candidate.candidate_id === candidateId)
    ?? null;

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/" className={styles.brand}>KJDS <span>PROFIT COMMAND</span></Link>
        <nav className={styles.nav} aria-label="利润指挥中心">
          {surfaces.map((item) => (
            <Link
              key={item.id}
              href={item.href}
              data-active={surface === item.id || (surface === "product-detail" && item.id === "products")}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className={styles.topActions}>
          <select
            className={styles.storeSelect}
            aria-label="授权店铺"
            value={selectedStore}
            onChange={(event) => {
              setRemediationOffset(0);
              setSelectedStore(event.target.value);
            }}
          >
            {storeRefs.map((store) => <option value={store} key={store}>{store}</option>)}
          </select>
          <button
            className={styles.refresh}
            type="button"
            onClick={() => {
              setRemediationOffset(0);
              setRefreshToken((value) => value + 1);
            }}
            disabled={loading}
          >
            <RefreshCw size={14} /><span>{loading ? "读取中" : "刷新快照"}</span>
          </button>
        </div>
      </header>

      <div className={styles.content}>
        <section className={styles.hero}>
          <div className={styles.heroMain}>
            <span className={styles.kicker}>FULL LINEAGE · FIVE PROFIT BASES · STORE FIT</span>
            <h1>{surfaceTitle(surface)}</h1>
            <p>{surfaceDescription(surface)}</p>
            <div className={styles.scopeLine}>
              <span>STORE {selectedStore || "no_data"}</span>
              <span>
                STATUS {surface === "truth"
                  ? truthReadiness?.status ?? "no_data"
                  : workspace?.status ?? "no_data"}
              </span>
              <span>
                AS OF {surface === "truth"
                  ? truthReadiness?.as_of ?? "no_data"
                  : workspace?.as_of ?? "no_data"}
              </span>
              <span>
                SNAPSHOT {(surface === "truth"
                  ? truthReadiness?.snapshot_sha256
                  : workspace?.snapshot_sha256)?.slice(0, 12) ?? "no_data"}
              </span>
            </div>
          </div>
          <aside className={styles.heroSignal}>
            <span>ACTUAL CASH PROFIT</span>
            <strong className={statusTone(workspace?.summary.actual_cash_profit.status)}>
              {money(workspace?.summary.actual_cash_profit)}
            </strong>
            <p>
              现金利润未完成订单、结算、银行到账三账核销时，系统只显示 no_data，
              不用情景利润替代。
            </p>
          </aside>
        </section>

        <div className={styles.notice}>
          <ShieldCheck size={15} />
          <span>{notice} 所有店铺与类目建议均为 proposal-only，不创建上架、广告、采购或 Permit。</span>
        </div>

        {surface === "overview" ? (
          <Overview
            workspace={workspace}
            analytics={analytics}
            portfolio={portfolio}
            operatingPlan={operatingPlan}
          />
        ) : null}
        {surface === "products" ? (
          <Products
            collection={collection}
            queryDraft={queryDraft}
            decisionClass={decisionClass}
            onQueryDraft={setQueryDraft}
            onDecisionClass={setDecisionClass}
            onSubmit={submitFilter}
          />
        ) : null}
        {surface === "product-detail" ? <ProductDetail candidate={currentCandidate} /> : null}
        {surface === "routing" ? (
          <Routing plan={operatingPlan} matrix={storeRouting} proposal={profileProposal} growthChannels={growthChannels} />
        ) : null}
        {surface === "truth" ? <TruthReadiness truth={truthReadiness} /> : null}
        {surface === "remediation" ? (
          <Remediation
            remediation={remediation}
            onPage={setRemediationOffset}
          />
        ) : null}
        {surface === "lineage" ? <Lineage lineage={lineage} /> : null}
      </div>
    </main>
  );
}

function Overview({
  workspace,
  analytics,
  portfolio,
  operatingPlan,
}: {
  workspace: ProfitWorkspace | null;
  analytics: ProfitAnalytics | null;
  portfolio: ProfitPortfolio | null;
  operatingPlan: OperatingPlan | null;
}) {
  const metrics = [
    ["风险利润机会", String(workspace?.summary.risk_profit_opportunities ?? "no_data"), "downside CM3 为正且门禁完整", "good"],
    ["当前亏损暴露", money(workspace?.summary.loss_exposure), workspace?.summary.loss_exposure.reason ?? "no_data", "risk"],
    ["库存占资", money(workspace?.summary.inventory_cash), workspace?.summary.inventory_cash.reason ?? "no_data", ""],
    ["候选 SKU", String(workspace?.counts.candidates ?? "no_data"), "数据库中的当前候选", ""],
    ["覆盖店铺", String(portfolio?.summary.store_count ?? "no_data"), "只统计授权且有作用域的店铺", ""],
  ];
  return (
    <>
      <section className={styles.metrics}>
        {metrics.map(([label, value, note, tone]) => (
          <article className={styles.metric} data-tone={tone} key={label}>
            <span>{label}</span><strong>{value}</strong><p>{note}</p>
          </article>
        ))}
      </section>

      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>DECISION MIX</span><h2>SKU 经营决策分布</h2></div>
            <p>由服务端 Profit Command 分类；前端不重算。</p>
          </header>
          {analytics?.decision_distribution.length ? (
            <div className={styles.chart}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analytics.decision_distribution} margin={{ left: -22, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="rgba(234,226,202,.08)" />
                  <XAxis dataKey="key" stroke="#8d897d" tick={{ fontSize: 10 }} />
                  <YAxis allowDecimals={false} stroke="#8d897d" tick={{ fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: "#171914", border: "1px solid rgba(234,226,202,.18)", fontSize: 11 }} />
                  <Bar dataKey="count" fill="#b8ef61" radius={[5, 5, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <Empty label="暂无可审计决策分布" />}
        </article>

        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>HIGHEST VALUE ACTION</span><h2>当前最高价值动作</h2></div>
          </header>
          {workspace?.summary.highest_value_action ? (
            <div>
              <span className={styles.status}>{workspace.summary.highest_value_action.decision_class}</span>
              <h3>{workspace.summary.highest_value_action.candidate_id}</h3>
              <p className={styles.mono}>{workspace.summary.highest_value_action.next_action}</p>
              <p className={styles.mono}>OWNER {workspace.summary.highest_value_action.owner}</p>
            </div>
          ) : <Empty label="尚无可执行动作" />}
        </article>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>PROFIT BASIS SEPARATION</span><h2>五套利润口径</h2></div>
          <p>同币种、同口径、证据完整才聚合；禁止预测冒充现金。</p>
        </header>
        <div className={styles.basisGrid}>
          {analyticsMetricKeys.map(([key, label]) => {
            const value = analytics?.profit_metrics[key];
            return (
              <article className={styles.basisCard} key={key}>
                <span>{label}</span>
                <strong className={statusTone(value?.status)}>{money(value)}</strong>
                <p>{value?.reason ?? `${value?.included_candidate_count ?? 0} SKU evidenced`}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>CATEGORY PROFIT MATRIX</span><h2>一级至叶子类目经营矩阵</h2></div>
            <p>当前源数据只提供叶子类目和商品类型时，上级类目保持 no_data。</p>
          </header>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>叶子类目</th><th>商品类型</th><th>SKU</th><th>决策</th><th>店铺路由</th></tr></thead>
              <tbody>
                {(analytics?.category_matrix ?? []).slice(0, 20).map((row) => (
                  <tr key={`${row.source_category_id}:${row.product_type_id}`}>
                    <td>{row.source_category_id}</td><td>{row.product_type_id}</td>
                    <td>{row.candidate_count}</td>
                    <td className={styles.mono}>{JSON.stringify(row.decision_counts)}</td>
                    <td className={styles.mono}>{JSON.stringify(row.route_counts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>DATA COMPLETENESS</span><h2>全量留存与数据质量</h2></div>
          </header>
          <div className={styles.metrics} style={{ gridTemplateColumns: "1fr 1fr" }}>
            <article className={styles.metric}><span>SOURCE</span><strong>{workspace?.bundle?.counts.source_total ?? "no_data"}</strong><p>源记录总数</p></article>
            <article className={styles.metric}><span>ACCEPTED</span><strong>{workspace?.bundle?.counts.accepted ?? "no_data"}</strong><p>进入标准观察</p></article>
            <article className={styles.metric} data-tone="risk"><span>QUARANTINE</span><strong>{workspace?.bundle?.counts.quarantined ?? "no_data"}</strong><p>原始数据保留，等待修复</p></article>
            <article className={styles.metric}><span>ROUTED</span><strong>{operatingPlan?.summary.candidate_count ?? "no_data"}</strong><p>经过店铺类目判断</p></article>
          </div>
          <p className={styles.mono}>历史序列：{analytics?.time_series.status ?? "no_data"} · {analytics?.time_series.reason ?? "no_data"} · synthetic=false</p>
        </article>
      </section>
    </>
  );
}

function Products({
  collection,
  queryDraft,
  decisionClass,
  onQueryDraft,
  onDecisionClass,
  onSubmit,
}: {
  collection: CandidateCollection | null;
  queryDraft: string;
  decisionClass: string;
  onQueryDraft: (value: string) => void;
  onDecisionClass: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <section className={styles.panel}>
      <header className={styles.panelTitle}>
        <div><span>SKU PROFIT WORKBENCH</span><h2>商品利润与下一动作</h2></div>
        <p>{collection?.count ?? 0} 条当前页 · 服务端过滤与游标分页</p>
      </header>
      <form className={styles.filters} onSubmit={onSubmit}>
        <Search size={16} />
        <input className={styles.filterInput} value={queryDraft} onChange={(event) => onQueryDraft(event.target.value)} placeholder="搜索 offer_id 或商品名称" />
        <select className={styles.filterSelect} value={decisionClass} onChange={(event) => onDecisionClass(event.target.value)}>
          <option value="">全部决策</option>
          {['stop_loss', 'reprice', 'pilot', 'hold', 'exit', 'needs_data'].map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <button className={styles.filterButton} type="submit">查询</button>
      </form>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th>商品</th><th>官方类目身份</th><th>售价 / 市场价</th><th>风险利润</th><th>实际现金利润</th><th>店铺路由</th><th>决策</th></tr></thead>
          <tbody>
            {(collection?.candidates ?? []).map((candidate) => (
              <tr key={candidate.candidate_id}>
                <td><strong><Link href={`/profit-command/products/${encodeURIComponent(candidate.candidate_id)}`}>{candidate.name || candidate.offer_id}</Link></strong><span className={styles.mono}>{candidate.offer_id}</span></td>
                <td><strong>{candidate.category_identity.source_category_id ?? "no_data"}</strong><span className={styles.mono}>TYPE {candidate.category_identity.product_type_id ?? "no_data"}</span></td>
                <td><strong>{money(candidate.raw_money.own_price)}</strong><span className={styles.mono}>MARKET {money(candidate.raw_money.market_reference_price)}</span></td>
                <td>{scenarioValue(candidate, "risk_adjusted_profit")}</td>
                <td>{scenarioValue(candidate, "cash_profit")}</td>
                <td><span className={styles.status}>{candidate.store_category_route?.decision ?? "unbound"}</span></td>
                <td><strong className={statusTone(candidate.decision_class)}>{candidate.decision_class}</strong><span className={styles.mono}>{candidate.reason_codes[0] ?? "ready"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!collection?.candidates.length ? <Empty label="当前筛选条件下没有真实候选" /> : null}
    </section>
  );
}

function ProductDetail({ candidate }: { candidate: ProfitCandidate | null }) {
  if (!candidate) return <Empty label="当前作用域找不到该 SKU，或详情投影尚未建立" />;
  const route = candidate.store_category_route;
  return (
    <div className={styles.detailGrid}>
      <article className={`${styles.panel} ${styles.detailWide}`}>
        <header className={styles.panelTitle}>
          <div><span>SKU ECONOMICS</span><h2>{candidate.name || candidate.offer_id}</h2></div>
          <span className={styles.status}>{candidate.decision_class}</span>
        </header>
        <div className={styles.basisGrid}>
          {profitBases.map((basis) => (
            <article className={styles.basisCard} key={basis.key}>
              <span>{basis.label}</span><strong>{scenarioValue(candidate, basis.key)}</strong><p>{basis.note}</p>
            </article>
          ))}
        </div>
      </article>

      <article className={`${styles.panel} ${styles.detailNarrow}`}>
        <header className={styles.panelTitle}><div><span>RAW MONEY</span><h2>原币金额与 FX</h2></div></header>
        <p>本店售价 <strong>{money(candidate.raw_money.own_price)}</strong></p>
        <p>市场参考 <strong>{money(candidate.raw_money.market_reference_price)}</strong></p>
        <p className={styles.mono}>FX BASIS {candidate.raw_money.fx_basis ? "available" : "no_data"}</p>
        <p className={styles.danger}>币种不一致且无汇率证据时，不生成利润或调价结论。</p>
      </article>

      <article className={`${styles.panel} ${styles.detailWide}`}>
        <header className={styles.panelTitle}>
          <div><span>15-COMPONENT COST COVERAGE</span><h2>十五项成本证据</h2></div>
          <p>{candidate.cost_coverage.evidenced}/{candidate.cost_coverage.required} evidenced</p>
        </header>
        <div className={styles.costGrid}>
          {candidate.cost_coverage.components.map((component) => (
            <div className={styles.costItem} key={component.name}><span>{component.name}</span><strong className={statusTone(component.status)}>{component.status}</strong></div>
          ))}
        </div>
      </article>

      <article className={`${styles.panel} ${styles.detailNarrow}`}>
        <header className={styles.panelTitle}><div><span>CATEGORY ROUTE</span><h2>店铺与官方类目</h2></div></header>
        <RouteSummary route={route} />
      </article>

      <article className={`${styles.panel} ${styles.detailFull}`}>
        <header className={styles.panelTitle}><div><span>BLOCKERS & NEXT ACTION</span><h2>阻断原因与责任动作</h2></div><p>OWNER {candidate.owner}</p></header>
        <ul className={styles.reasonList}>{candidate.reason_codes.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        <p>{candidate.next_action}</p>
      </article>

      <article className={`${styles.panel} ${styles.detailFull}`}>
        <header className={styles.panelTitle}><div><span>DRILLTHROUGH</span><h2>订单、库存、结算、供应与证据</h2></div><p>{candidate.evidence_ids.length} evidence ids</p></header>
        <div className={styles.drillGrid}>
          {Object.entries(candidate.drillthrough).filter(([, value]) => value).map(([label, href]) => (
            <a href={backendHref(href as string)} key={label}>{label}<br /><span className={styles.mono}>{href}</span></a>
          ))}
        </div>
      </article>
    </div>
  );
}

function Routing({
  plan,
  matrix,
  proposal,
  growthChannels,
}: {
  plan: OperatingPlan | null;
  matrix: StoreRoutingMatrix | null;
  proposal: StoreProfileProposal | null;
  growthChannels: GrowthChannelCapabilities | null;
}) {
  return (
    <>
      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}><div><span>STORE OPERATING PROFILE</span><h2>店铺经营属性</h2></div><p>{plan?.status ?? "no_data"}</p></header>
          {plan?.profile ? (
            <div className={styles.routeCards}>
              <article className={styles.routeCard}><span className={styles.kicker}>POSITIONING</span><h3>{plan.profile.store_positioning}</h3><p>{plan.profile.assortment_mode} · {plan.profile.price_band}</p></article>
              <article className={styles.routeCard}><span className={styles.kicker}>MARKET</span><h3>{plan.profile.target_regions.join(" / ") || "no_data"}</h3><p>{plan.profile.fulfillment_models.join(" / ") || "no_data"}</p></article>
              <article className={styles.routeCard}><span className={styles.kicker}>GROWTH</span><h3>{plan.profile.planned_growth_channels.join(" / ") || "no_data"}</h3><p>渠道只按 incremental cash CM3 扩量</p></article>
            </div>
          ) : <Empty label="尚未建立证据化店铺经营属性，系统不猜测店铺定位" />}
        </article>
        <article className={styles.panel}>
          <header className={styles.panelTitle}><div><span>ROUTE COUNTS</span><h2>类目路由决策</h2></div></header>
          <div className={styles.routeCards}>
            {Object.entries(plan?.summary.route_counts ?? {}).map(([key, value]) => (
              <article className={styles.routeCard} key={key}><span className={styles.kicker}>{key}</span><h3>{value}</h3><p>proposal-only</p></article>
            ))}
          </div>
        </article>
      </section>

      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>VK + TELEGRAM PORTS</span><h2>俄罗斯私域与内容增长入口</h2></div>
            <p>{growthChannels?.optimization_objective ?? "no_data"}</p>
          </header>
          <div className={styles.routeCards}>
            {(growthChannels?.channels ?? []).map((channel) => (
              <article className={styles.routeCard} key={channel.channel}>
                <header><span className={styles.status}>{channel.channel}</span><strong>{channel.dry_run_adapter ? "DRY-RUN" : "NO DATA"}</strong></header>
                <h3>{channel.operations.join(" / ")}</h3>
                <p>DEEP LINK {String(channel.supports_deep_links)} · DM {String(channel.supports_direct_messages)}</p>
                <p>{channel.requires_initiated_or_subscribed_message ? "仅已发起会话或已订阅用户" : "仍需渠道同意与精确 Permit"}</p>
              </article>
            ))}
          </div>
        </article>
        <article className={styles.panel}>
          <header className={styles.panelTitle}><div><span>ATTRIBUTION FUNNEL</span><h2>从曝光到现金 CM3</h2></div></header>
          <div className={styles.lineage}>
            {(growthChannels?.attribution_funnel ?? []).map((stage, index) => (
              <div key={stage} style={{ display: "contents" }}>
                <article className={styles.lineageNode}><span className={styles.kicker}>{stage}</span></article>
                {index < (growthChannels?.attribution_funnel.length ?? 0) - 1 ? <ArrowRight className={styles.lineageArrow} size={16} /> : null}
              </div>
            ))}
          </div>
          <p className={styles.mono}>奖励在退款窗口关闭且结算完成前只计提；广告、渠道、奖励和退款成本全部进入 incremental_cash_cm3。</p>
        </article>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>EVIDENCE-BACKED PROFILE PROPOSAL</span><h2>官方类目证据形成的店铺画像草案</h2></div>
          <p>{proposal?.status ?? "no_data"} · {proposal?.quality.data_grade ?? "E"} · {proposal?.quality.confidence ?? "0"}</p>
        </header>
        <div className={styles.notice}>
          <ShieldCheck size={15} />
          <span>当前仅观察到 {proposal?.quality.evidence_type_coverage.join(" / ") || "no_data"}；缺订单、实际利润或精确变体时只供人工复核，不写入正式店铺属性。</span>
        </div>
        <div className={styles.routeCards}>
          {(proposal?.category_role_assignments ?? []).map((assignment) => (
            <article className={styles.routeCard} key={assignment.category_id}>
              <header><span className={styles.status}>{assignment.role}</span><strong>{assignment.data_grade}</strong></header>
              <h3>{assignment.category_name}</h3>
              <p>CATEGORY {assignment.category_id}</p>
              <p>IDENTITY {assignment.identity_quality} · VARIANT {assignment.variant_quality}</p>
              <p>{assignment.evidence_refs.length} evidence refs</p>
            </article>
          ))}
        </div>
        {!proposal?.category_role_assignments.length ? <Empty label="当前证据不足以形成类目角色提案" /> : null}
        <ul className={styles.reasonList}>
          {(proposal?.source_gaps ?? []).map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>OFFICIAL CATEGORY TREE</span><h2>一级 / 二级 / 三级 / 叶子与衍生打法</h2></div>
          <p>衍生标签用于打法，不作为平台官方类目。</p>
        </header>
        <div className={styles.routeCards}>
          {(plan?.category_tree ?? []).map((path, index) => (
            <article className={styles.routeCard} key={path.path_id ?? `${path.leaf_category_id}:${index}`}>
              <header><span className={styles.status}>{path.role ?? "no_data"}</span><strong>{path.candidate_count} SKU</strong></header>
              <h3>{categoryText(path)}</h3>
              <div className={styles.categoryPath}>
                <span>L1 {path.level_1?.name ?? "no_data"}</span>
                <span>L2 {path.level_2?.name ?? "no_data"}</span>
                <span>L3 {path.level_3?.name ?? "no_data"}</span>
              </div>
              <p>LEAF {path.leaf_category_id ?? "no_data"} · TYPE {path.product_type_ids?.join("/") || "no_data"}</p>
              <p>DERIVED {path.derived_tags?.join(" / ") || "none"}</p>
            </article>
          ))}
        </div>
        {!plan?.category_tree.length ? <Empty label="没有可用官方类目树；原始商品仍完整保留" /> : null}
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}><div><span>CROSS-STORE ROUTING</span><h2>候选到最匹配店铺</h2></div><p>{matrix?.routes.length ?? 0} route proposals</p></header>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>候选</th><th>来源店铺</th><th>建议店铺</th><th>官方类目</th><th>角色 / 置信度</th><th>跨店交接</th></tr></thead>
            <tbody>
              {(matrix?.routes ?? []).map((route) => (
                <tr key={`${route.source_store_ref}:${route.candidate_id}`}>
                  <td><strong>{route.name || route.offer_id}</strong><span className={styles.mono}>{route.offer_id}</span></td>
                  <td>{route.source_store_ref}</td><td>{route.recommended_store_ref ?? "no_data"}</td>
                  <td>{categoryText(route.recommended_route?.target_category_path)}</td>
                  <td>{route.recommended_route ? `${route.recommended_route.category_role} / ${route.recommended_route.confidence}` : "no_data"}</td>
                  <td>{route.cross_store_handoff_required ? "required" : "same_store_or_no_data"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function RouteSummary({ route }: { route: StoreCategoryRoute | undefined }) {
  if (!route) return <Empty label="店铺经营属性未绑定" />;
  return (
    <div>
      <span className={styles.status}>{route.decision}</span>
      <h3>{route.target_store_ref ?? "no target store"}</h3>
      <p>{categoryText(route.target_category_path)}</p>
      <dl className={styles.playbook}>
        <div><dt>生命周期</dt><dd>{route.playbook.lifecycle}</dd></div>
        <div><dt>商品打法</dt><dd>{route.playbook.listing}</dd></div>
        <div><dt>流量打法</dt><dd>{route.playbook.traffic}</dd></div>
        <div><dt>库存打法</dt><dd>{route.playbook.inventory}</dd></div>
        <div><dt>增长渠道</dt><dd>{route.playbook.growth_channels.join(" / ") || "none"}</dd></div>
      </dl>
    </div>
  );
}

function TruthReadiness({ truth }: { truth: ProfitTruthReadiness | null }) {
  const metrics = [
    ["全量源记录", truth?.data_chain.source_total ?? "no_data", `retained ${truth?.data_chain.retained_total ?? "no_data"}`],
    ["身份来源", truth?.summary.identity_source_count ?? "no_data", `exact groups ${truth?.variant_identity.summary.exact_resolution_count ?? "no_data"}`],
    ["财务 Operation", truth?.summary.finance_operation_count ?? "no_data", `entry proposals ${truth?.summary.finance_entry_proposal_count ?? "no_data"}`],
    ["完整作用域 FX", truth?.summary.complete_scoped_fx_count ?? "no_data", `legacy blocked ${truth?.summary.legacy_unscoped_fx_count ?? "no_data"}`],
    ["成本补证任务", truth?.summary.cost_evidence_request_count ?? "no_data", "十五项成本 + FX + 数量 + 账本"],
    ["物流候选证据", truth?.summary.unbound_logistics_observation_count ?? "no_data", "unbound · 不计入 SKU 成本覆盖"],
  ];
  const books = ["scenario_profit", "accrual_profit", "settlement_profit", "cash_profit"];
  return (
    <>
      <section className={styles.metrics}>
        {metrics.map(([label, value, note]) => (
          <article className={styles.metric} key={label} data-tone={label === "成本补证任务" ? "risk" : ""}>
            <span>{label}</span><strong>{value}</strong><p>{note}</p>
          </article>
        ))}
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>UNBOUND LOGISTICS EVIDENCE</span><h2>物流证据待绑定池</h2></div>
          <p>
            {truth?.unbound_cost_evidence.status ?? "no_data"} · accepted {truth?.unbound_cost_evidence.summary.accepted ?? 0}
            {" / "}quarantined {truth?.unbound_cost_evidence.summary.quarantined ?? 0}
          </p>
        </header>
        <div className={styles.reasonMatrix}>
          {Object.entries(truth?.unbound_cost_evidence.summary.cost_leg_counts ?? {}).map(([costLeg, count]) => (
            <div key={costLeg}><span className={styles.mono}>{costLeg}</span><strong>{count}</strong></div>
          ))}
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>来源 / 定位</th><th>来源哈希</th><th>币种</th><th>候选成本腿</th><th>状态</th><th>阻断</th></tr></thead>
            <tbody>
              {(truth?.unbound_cost_evidence.records ?? []).slice(0, 50).map((record) => (
                <tr key={record.observation_id}>
                  <td>{record.source_relpath}<span className={styles.mono}>{record.source_location}</span></td>
                  <td className={styles.mono}>{record.source_sha256}</td>
                  <td>{record.currency ?? "UNKNOWN"}</td>
                  <td className={styles.mono}>{record.mapped_cost_legs.join(" / ") || "unclassified"}</td>
                  <td><span className={styles.status}>{record.disposition}</span></td>
                  <td className={styles.mono}>{record.reason_codes.join(" / ") || "binding_required"}</td>
                </tr>
              ))}
              {!truth?.unbound_cost_evidence.records.length ? <tr><td colSpan={6}><Empty label="暂无显式导入的物流 observation" /></td></tr> : null}
            </tbody>
          </table>
        </div>
        <p>
          接口保留全部 {truth?.unbound_cost_evidence.summary.source_total ?? 0} 条，页面显示前 50 条；
          未绑定 SKU、精确变体、shipment profile、数量与有效期前，不形成金额、reviewed/actual、15-cost covered、Fact、FinanceEntry、Pilot 或外写。
        </p>
        <p className={styles.mono}>
          NEXT {truth?.unbound_cost_evidence.next_action.action ?? "bind_logistics_observation_to_sku_shipment_profile"}
          {" · "}{truth?.unbound_cost_evidence.next_action.calculation_seam ?? "/v1/logistics/calculations"}
        </p>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>PROFIT TRUTH PIPELINE</span><h2>从源证据到现金利润的真实状态</h2></div>
          <p>accepted + quarantined = source_total · 守恒 {String(truth?.data_chain.conservation_passed ?? false)}</p>
        </header>
        <div className={styles.lineage}>
          {(truth?.data_chain.path ?? []).map((stage, index) => (
            <div key={stage} style={{ display: "contents" }}>
              <article className={styles.lineageNode}>
                <span className={styles.kicker}>{stageLabels[stage] ?? stage}</span>
                <strong>{truth?.data_chain.stage_counts[stage] ?? 0}</strong>
                <small className={styles.mono}>{stage.includes("profit") ? "strict book" : "retained stage"}</small>
              </article>
              {index < (truth?.data_chain.path.length ?? 0) - 1 ? <ArrowRight className={styles.lineageArrow} size={16} /> : null}
            </div>
          ))}
        </div>
      </section>

      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>FX EVIDENCE GATE</span><h2>币种与有效期</h2></div>
            <span className={styles.status}>{truth?.fx_readiness.status ?? "no_data"}</span>
          </header>
          <div className={styles.heroSignal}>
            <span>REQUIRED PAIR</span><strong>{truth?.fx_readiness.required_pair ?? "no_data"}</strong>
            <p>历史未分作用域汇率只显示候选，decision_eligible=false；不反向猜测、不使用过期证据。</p>
          </div>
          <div className={styles.reasonMatrix}>
            {(truth?.fx_readiness.required_pairs ?? []).map((pair) => (
              <div key={`${pair.source_currency}/${pair.quote_currency}`}>
                <span className={styles.mono}>{pair.source_currency}/{pair.quote_currency}</span>
                <strong>{pair.status}</strong>
              </div>
            ))}
          </div>
          <p className={styles.mono}>POST {truth?.fx_readiness.record_endpoint ?? "/v1/profit-command/fx-evidence"}</p>
        </article>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>VARIANT IDENTITY</span><h2>商品、目录与财务 SKU</h2></div>
            <p>守恒 {String(truth?.variant_identity.reconciliation.conservation_passed ?? false)}</p>
          </header>
          <div className={styles.reasonMatrix}>
            {Object.entries(truth?.variant_identity.summary ?? {}).map(([key, value]) => (
              <div key={key}><span className={styles.mono}>{key}</span><strong>{value}</strong></div>
            ))}
          </div>
          <p>Model ID、标题和类目相似度只能形成复核候选，不能自动成为精确变体。</p>
        </article>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>OZON FINANCE ALLOCATION</span><h2>Posting、SKU、金额与币种阻断</h2></div>
          <p>{truth?.finance_allocation.status ?? "no_data"} · count conservation {String(truth?.finance_allocation.reconciliation.count_conservation_passed ?? false)}</p>
        </header>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>Operation</th><th>Posting</th><th>SKU</th><th>原始金额</th><th>状态</th><th>阻断</th></tr></thead>
            <tbody>
              {(truth?.finance_allocation.operations ?? []).slice(0, 50).map((operation, index) => (
                <tr key={`${operation.operation_id ?? "missing"}:${index}`}>
                  <td className={styles.mono}>{operation.operation_id ?? "missing"}</td>
                  <td className={styles.mono}>{operation.posting_number ?? "no_data"}</td>
                  <td>{operation.sku ?? "unallocated"}</td>
                  <td>{operation.currency ?? "UNKNOWN"} {operation.amount_raw ?? "no_data"}</td>
                  <td><span className={styles.status}>{operation.disposition}</span></td>
                  <td className={styles.mono}>{operation.reason_codes.join(" / ") || "ready"}</td>
                </tr>
              ))}
              {!truth?.finance_allocation.operations.length ? <tr><td colSpan={6}><Empty label="暂无财务 operation" /></td></tr> : null}
            </tbody>
          </table>
        </div>
        <p className={styles.mono}>页面显示前 50 条；接口保留全部 {truth?.summary.finance_operation_count ?? 0} 条。多 SKU Posting 不按比例猜分。</p>
      </section>

      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>FOUR PROFIT BOOKS</span><h2>预测、权责、结算与现金永久分开</h2></div>
          </header>
          <div className={styles.basisGrid}>
            {books.map((key) => {
              const book = truth?.profit_books[key];
              const projection = typeof book === "object" ? book : null;
              return (
                <article className={styles.basisCard} key={key}>
                  <span>{key}</span><strong>{projection?.status ?? "no_data"}</strong>
                  <p>{projection?.record_count ?? 0} records · {projection?.currency ?? truth?.display_currency ?? ""}</p>
                </article>
              );
            })}
          </div>
        </article>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>BLOCKER OWNERSHIP</span><h2>当前不能盈利计算的原因</h2></div>
            <p>{truth?.summary.blocker_count ?? 0} blocker groups</p>
          </header>
          <div className={styles.reasonMatrix}>
            {(truth?.blockers ?? []).map((blocker) => (
              <div key={blocker.code}>
                <span className={styles.mono}>{blocker.code}<br />OWNER {blocker.owner}</span>
                <strong>{blocker.affected_count}</strong>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>15-COST EVIDENCE QUEUE</span><h2>逐 SKU 成本、数量、FX 与账本补证</h2></div>
          <p>接口保留全部 {truth?.summary.cost_evidence_request_count ?? 0} 条，页面显示最高优先级 50 条。</p>
        </header>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>优先级</th><th>SKU</th><th>类型 / 成本腿</th><th>责任人</th><th>所需单据</th><th>阻断</th></tr></thead>
            <tbody>
              {(truth?.cost_evidence.evidence_request_queue ?? []).slice(0, 50).map((request) => (
                <tr key={request.request_id}>
                  <td>{request.priority_rank}</td><td className={styles.mono}>{request.sku}</td>
                  <td>{request.request_type}<span className={styles.mono}>{request.cost_type ?? ""}</span></td>
                  <td>{request.owner}</td><td>{request.required_document}</td>
                  <td className={styles.mono}>{request.blocker_codes.join(" / ")}</td>
                </tr>
              ))}
              {!truth?.cost_evidence.evidence_request_queue.length ? <tr><td colSpan={6}><Empty label="暂无成本补证任务" /></td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Remediation({
  remediation,
  onPage,
}: {
  remediation: ProfitRemediation | null;
  onPage: (offset: number) => void;
}) {
  const metrics = [
    ["源记录", remediation?.reconciliation.source_total ?? "no_data", "全量留存基数"],
    ["已接收", remediation?.reconciliation.accepted ?? "no_data", "进入标准观察"],
    ["隔离记录", remediation?.reconciliation.quarantined ?? "no_data", "保留原件等待补证"],
    ["修复任务", remediation?.summary.remediation_items ?? "no_data", "服务端生成的证据任务"],
    ["受阻任务", remediation?.summary.blocked ?? "no_data", "不得绕过控制门禁"],
  ];
  return (
    <>
      <section className={styles.metrics}>
        {metrics.map(([label, value, note]) => (
          <article className={styles.metric} key={label} data-tone={label === "隔离记录" || label === "受阻任务" ? "risk" : ""}>
            <span>{label}</span><strong>{value}</strong><p>{note}</p>
          </article>
        ))}
      </section>

      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>REMEDIATION PRIORITY</span><h2>阻断类型与解锁顺序</h2></div>
            <p>排序由服务端按损失暴露、可解锁 SKU 和证据时效生成；前端不估算。</p>
          </header>
          <div className={styles.reasonMatrix}>
            {(remediation?.groups.by_error_code ?? []).map((item) => (
              <div key={item.key}><span className={styles.mono}>{item.key}</span><strong>{item.issue_count}</strong></div>
            ))}
            {!remediation?.groups.by_error_code.length ? <Empty label="暂无可审计阻断分布" /> : null}
          </div>
        </article>
        <article className={styles.panel}>
          <header className={styles.panelTitle}>
            <div><span>SOURCE CONSERVATION</span><h2>全量数据守恒</h2></div>
          </header>
          <div className={styles.heroSignal}>
            <span>ACCEPTED + QUARANTINED = SOURCE</span>
            <strong className={remediation?.reconciliation.conservation_passed ? styles.good : styles.danger}>
              {remediation ? String(remediation.reconciliation.conservation_passed) : "no_data"}
            </strong>
            <p>修复不会删除原始记录，也不会把缺币种、缺变体或缺 Evidence 的数据猜成正式事实。</p>
          </div>
        </article>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>PROFIT UNBLOCK QUEUE</span><h2>按赚钱与止损价值排队</h2></div>
          <p>每项任务明确责任角色、证据要求、期限和穿透入口；服务端分页保留全部任务。</p>
        </header>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>优先级</th><th>来源 / 数量</th><th>阻断与证据</th><th>受影响 SKU</th><th>责任 / 时限</th><th>下一动作</th><th>穿透</th></tr></thead>
            <tbody>
              {(remediation?.remediation_queue ?? []).map((item) => (
                <tr key={item.remediation_item_id}>
                  <td><span className={styles.status}>{item.severity}</span><p className={styles.mono}>RANK {item.priority_rank} · IMPACT {item.unblock_impact_score}</p></td>
                  <td><strong>{item.source_ref}</strong><span>{item.source_item_id ? "1 source record" : "profit candidate"}</span></td>
                  <td><ul className={styles.reasonList}><li>{item.error_code}</li></ul><p className={styles.mono}>{item.evidence_requirement}</p></td>
                  <td>{item.candidate_id ? 1 : 0}<p className={styles.mono}>{item.candidate_id ?? item.sku ?? "unbound"}</p></td>
                  <td><strong>{item.action.owner_role}</strong><span>{item.action.deadline_class}</span></td>
                  <td>{item.action.instruction}<p className={styles.mono}>LOSS {money(item.estimated_loss_exposure)} · VAR {money(item.value_at_risk)}</p></td>
                  <td>
                    {Object.entries(remediation?.drillthrough ?? {}).map(([label, href]) => href ? (
                      <Link key={label} href={backendHref(href)}>{label}</Link>
                    ) : null)}
                  </td>
                </tr>
              ))}
              {!remediation?.remediation_queue.length ? <tr><td colSpan={7}><Empty label="暂无服务端修复队列" /></td></tr> : null}
            </tbody>
          </table>
        </div>
        <div className={styles.pager}>
          <span>
            当前 {remediation?.pagination.page_count ?? 0} 条 · 共 {remediation?.pagination.total_count ?? 0} 条
          </span>
          <div>
            <button
              type="button"
              disabled={remediation?.pagination.previous_offset == null}
              onClick={() => onPage(remediation?.pagination.previous_offset ?? 0)}
            >
              上一页
            </button>
            <button
              type="button"
              disabled={remediation?.pagination.next_offset == null}
              onClick={() => onPage(remediation?.pagination.next_offset ?? 0)}
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </>
  );
}

function Lineage({ lineage }: { lineage: ProfitLineage | null }) {
  return (
    <>
      <section className={styles.panel}>
        <header className={styles.panelTitle}>
          <div><span>DATA GOVERNANCE LINEAGE</span><h2>从原始证据到经营决策</h2></div>
          <p>每一级独立，不自动晋升正式事实。</p>
        </header>
        <div className={styles.lineage}>
          {(lineage?.nodes ?? []).map((node, index) => (
            <div key={node.id} style={{ display: "contents" }}>
              <article className={styles.lineageNode}>
                <span className={styles.kicker}>{stageLabels[node.stage] ?? node.stage}</span>
                <strong>{node.count}</strong>
                <small className={styles.mono}>{node.status}</small>
              </article>
              {index < (lineage?.nodes.length ?? 0) - 1 ? <ArrowRight className={styles.lineageArrow} size={18} /> : null}
            </div>
          ))}
        </div>
      </section>

      <section className={styles.gridTwo}>
        <article className={styles.panel}>
          <header className={styles.panelTitle}><div><span>SKU EVIDENCE</span><h2>候选证据穿透</h2></div></header>
          <div className={styles.evidenceList}>
            {(lineage?.candidate_lineage ?? []).map((candidate) => (
              <div className={styles.evidenceRow} key={candidate.candidate_id}>
                <strong>{candidate.offer_id}</strong>
                <span>{candidate.evidence_ids.join(" / ") || "no evidence"}</span>
                <Link href={`/profit-command/products/${encodeURIComponent(candidate.candidate_id)}`}>商品详情</Link>
              </div>
            ))}
          </div>
        </article>
        <article className={styles.panel}>
          <header className={styles.panelTitle}><div><span>QUARANTINE</span><h2>隔离区</h2></div></header>
          <div className={styles.heroSignal}>
            <span>RETAINED RAW RECORDS</span>
            <strong>{lineage?.quarantine.count ?? "no_data"}</strong>
            <p>accepted + quarantined = source_total。无法解析、币种缺失、变体冲突的数据不删除。</p>
          </div>
        </article>
      </section>
    </>
  );
}

function Empty({ label }: { label: string }) {
  return <div className={styles.empty}><AlertTriangle size={20} /><p>{label}</p></div>;
}

function surfaceTitle(surface: ProfitSurface): string {
  return {
    overview: "先看真钱，再决定下一步。",
    products: "每个 SKU 都有利润、风险和证据。",
    "product-detail": "一件商品，穿透全部经营事实。",
    routing: "把商品放到最适合的店铺与官方类目。",
    truth: "先把利润输入变成真相，再允许经营判断。",
    remediation: "先修最值钱的数据，再让利润闭环前进。",
    lineage: "任何数字，都能回到它的原始证据。",
  }[surface];
}

function surfaceDescription(surface: ProfitSurface): string {
  return {
    overview: "集团到单店、类目到订单、费用到银行到账的利润经营指挥面。预测、权责、结算、现金和风险利润永久分离。",
    products: "按商品查看原币售价、十五项成本、风险利润、实际利润、库存与下一动作，适用于新手、小团队和企业同一经营内核。",
    "product-detail": "从官方类目身份、原币金额和 FX，到订单、费用、结算、供应商与 Evidence，全链路可审计。",
    routing: "店铺定位、经营模式、价格带、履约、区域、L1/L2/L3/叶子类目与衍生运营标签共同决定 proposal-only 路由。",
    truth: "逐层核对 FX、精确变体、Ozon 财务分摊、十五项成本、正式事实、平台结算与银行到账；缺一项就保持 blocked/no_data。",
    remediation: "将隔离记录和 SKU 利润缺口合并为优先任务，按止损价值、解锁影响和证据时效排序；不删除全量数据，不用估算冒充事实。",
    lineage: "全量采集、分级使用。质量不足的数据进入隔离区，保留来源、错误与修复入口，不为完整图表制造趋势。",
  }[surface];
}
