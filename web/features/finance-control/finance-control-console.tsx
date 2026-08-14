"use client";

import {
  ArrowLeft,
  BadgeDollarSign,
  Banknote,
  Bot,
  ChevronRight,
  CircleAlert,
  Fingerprint,
  Landmark,
  LockKeyhole,
  RefreshCw,
  Scale,
  ShieldCheck,
  Store,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./finance-control.module.css";

type WorkspaceStatus = "ready" | "partial" | "blocked" | "no_data";
type ViewState = WorkspaceStatus | "loading" | "error";
type Stage =
  | "fact_pending"
  | "accrual_pending"
  | "settlement_pending"
  | "cash_pending"
  | "reconcile_pending"
  | "variance"
  | "unknown_fee"
  | "reconciled"
  | "blocked";

type Blocker = {
  code: string;
  severity: string;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type FinanceCycle = {
  reconciliation_key: string;
  reconciliation_key_sha256: string;
  currency: string | null;
  stage: Stage;
  latest_effective_at: string;
  books: {
    order_accrual: {
      order_fact_count: number;
      accrual_fact_count: number;
      fee_fact_count: number;
      return_fact_count: number;
      gross_revenue: string | null;
      accrual_total: string | null;
      status: string;
    };
    platform_settlement: {
      fact_count: number;
      entry_count: number;
      amount: string | null;
      status: string;
    };
    bank_cash: {
      entry_count: number;
      amount: string | null;
      status: string;
    };
  };
  variance: {
    expected_settlement: string | null;
    settlement_variance: string | null;
    settlement_variance_ratio: string | null;
    bank_variance: string | null;
    bank_variance_ratio: string | null;
  };
  classification: {
    unknown_fee_count: number;
    review_required_count: number;
    fee_entry_count: number;
  };
  latest_reconciliation: {
    id: string;
    status: string;
    recorded_at: string;
    created_by: string;
    input_sha256: string | null;
  } | null;
  actual_cash_cm3: {
    status: "available" | "no_data";
    amount: string | null;
    currency: string | null;
    reason: string | null;
    profit_snapshot_sha256: string | null;
  };
  evidence: {
    count: number;
    ids: string[];
    all_current_and_exact_scope: boolean;
  };
  blockers: string[];
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type Workspace = {
  contract_id: string;
  status: WorkspaceStatus;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
  };
  filters: {
    query: string | null;
    stage: Stage | null;
  };
  counts: Record<string, number>;
  pagination: {
    page_size: number;
    next_cursor: string | null;
  };
  cycles: FinanceCycle[];
  excluded: {
    count: number;
    reason_counts: Record<string, number>;
    business_values_exposed: false;
  };
  source_gaps: string[];
  blockers: Blocker[];
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
  upstream: {
    finance_source_snapshot_sha256: string | null;
  };
  agent_artifact: {
    contract_id: string;
    version: string;
    artifact_sha256: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    finance_record_creation_allowed: false;
    payment_or_refund_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    read_only: true;
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    legacy_finance_rows_admitted: false;
    proportional_allocation_allowed: false;
    finance_entry_created: false;
    reconciliation_created: false;
    fact_created: false;
    cash_plan_created: false;
    approval_created: false;
    permit_created: false;
    payment_initiated: false;
    collection_initiated: false;
    refund_initiated: false;
    dispute_initiated: false;
    external_write_allowed: false;
  };
  snapshot_sha256: string;
};

type StrategyPacks = {
  authorized_scope: {
    tenant_ref: string;
    store_refs: string[];
  };
};

type ErrorPayload = { detail?: string };

const stages: Stage[] = [
  "fact_pending",
  "accrual_pending",
  "settlement_pending",
  "cash_pending",
  "reconcile_pending",
  "variance",
  "unknown_fee",
  "reconciled",
  "blocked",
];

const labels: Record<string, string> = {
  ready: "权威可用",
  partial: "部分可用",
  blocked: "失败关闭",
  no_data: "真实 no_data",
  loading: "读取中",
  error: "读取失败",
  fact_pending: "订单事实待接入",
  accrual_pending: "应计待接入",
  settlement_pending: "平台结算待接入",
  cash_pending: "银行到账待接入",
  reconcile_pending: "三本账待核对",
  variance: "存在差异",
  unknown_fee: "未知费用",
  reconciled: "三本账已核对",
};

function label(value: string) {
  return labels[value] ?? value;
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "no_data";
}

function money(value: string | null, currency: string | null) {
  return value === null ? "no_data" : `${value} ${currency ?? ""}`.trim();
}

export function FinanceControlConsole() {
  const [stores, setStores] = useState<string[]>([]);
  const [storeRef, setStoreRef] = useState("");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [scopeBusy, setScopeBusy] = useState(true);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [detail, setDetail] = useState("");
  const [queryDraft, setQueryDraft] = useState("");
  const [stageDraft, setStageDraft] = useState("");
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("");

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
    setDetail("");
    try {
      const response = await fetchJson<StrategyPacks | ErrorPayload>(
        "/backend/v1/seller-os/strategy-packs",
        { cache: "no-store", signal },
      );
      if (redirectForAuth(response.status)) return;
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          "detail" in body
            ? body.detail ?? `API ${response.status}`
            : `API ${response.status}`,
        );
      }
      const authorized = (body as StrategyPacks).authorized_scope.store_refs;
      setStores(authorized);
      setStoreRef((current) =>
        current && authorized.includes(current)
          ? current
          : authorized[0] ?? "",
      );
      if (authorized.length === 0) {
        setViewState("blocked");
        setDetail(
          "当前身份没有授权店铺；财务控制不会回退到 legacy 或全局账。",
        );
      }
    } catch (reason) {
      if (signal?.aborted) return;
      setViewState("error");
      setDetail(
        reason instanceof Error ? reason.message : "授权作用域读取失败",
      );
    } finally {
      if (!signal?.aborted) setScopeBusy(false);
    }
  }, [redirectForAuth]);

  const loadWorkspace = useCallback(
    async (
      store: string,
      cursor?: string | null,
      signal?: AbortSignal,
    ) => {
      if (!store) return;
      setWorkspaceBusy(true);
      setDetail("");
      try {
        const params = new URLSearchParams({
          store_ref: store,
          page_size: "50",
        });
        if (query) params.set("query", query);
        if (stage) params.set("stage", stage);
        if (cursor) params.set("cursor", cursor);
        const response = await fetchJson<Workspace | ErrorPayload>(
          `/backend/v1/finance-control/workspace?${params.toString()}`,
          { cache: "no-store", signal },
        );
        if (redirectForAuth(response.status)) return;
        const body = await response.json();
        if (!response.ok) {
          setWorkspace(null);
          setViewState(
            response.status === 403 || response.status === 422
              ? "blocked"
              : "error",
          );
          setDetail(
            "detail" in body
              ? String(body.detail ?? `API ${response.status}`)
              : `API ${response.status}`,
          );
          return;
        }
        const next = body as Workspace;
        setWorkspace(next);
        setViewState(next.status);
      } catch (reason) {
        if (signal?.aborted) return;
        setWorkspace(null);
        setViewState("error");
        setDetail(
          reason instanceof Error
            ? reason.message
            : "结算与现金权威暂不可用",
        );
      } finally {
        if (!signal?.aborted) setWorkspaceBusy(false);
      }
    },
    [query, redirectForAuth, stage],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadScope(controller.signal);
    return () => controller.abort("finance scope unmounted");
  }, [loadScope]);

  useEffect(() => {
    if (!storeRef) return;
    const controller = new AbortController();
    void loadWorkspace(storeRef, null, controller.signal);
    return () => controller.abort("finance workspace changed");
  }, [loadWorkspace, storeRef]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/commerce-os" className={styles.backLink}>
          <ArrowLeft size={16} />
          Commerce OS
        </Link>
        <div className={styles.productMark}>
          <span><Landmark size={18} /></span>
          <div>
            <strong>结算与现金控制</strong>
            <small>KJDS AI ERP · THREE AUTHORITATIVE BOOKS</small>
          </div>
        </div>
        <label className={styles.storePicker}>
          <Store size={15} />
          <span>授权店铺</span>
          <select
            aria-label="选择授权店铺"
            value={storeRef}
            disabled={scopeBusy || stores.length === 0}
            onChange={(event) => setStoreRef(event.target.value)}
          >
            {stores.map((store) => <option key={store}>{store}</option>)}
          </select>
        </label>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>
            <ShieldCheck size={14} />
            EXACT SCOPE · NO PROPORTIONAL ALLOCATION · FAIL CLOSED
          </span>
          <h1>
            订单、结算、银行现金三本账，
            <em>没有核对就没有 Actual Cash CM3</em>
          </h1>
          <p>
            服务端以明确 reconciliation key 组合正式 Order/Accrual Fact、
            平台 Settlement 与独立 Bank Cash Evidence。页面不重算金额、差异、
            阶段或利润，也不把估算 CM3 冒充到账后利润。
          </p>
        </div>
        <aside>
          <LockKeyhole size={24} />
          <strong>财务和外部写全部关闭</strong>
          <p>
            未创建 Entry、Reconciliation、Cash Plan、Approval 或 Permit；
            未发起付款、收款、退款或争议。
          </p>
          <Link href="/accounts-payable">进入应付与供应商付款控制 →</Link>
          <Link href="/profit-ledger">进入十五项实际利润账 →</Link>
          <small>
            {workspace
              ? shortHash(workspace.snapshot_sha256)
              : "等待服务端权威快照"}
          </small>
        </aside>
      </section>

      <section className={styles.boundary} aria-label="结算与现金控制边界">
        <strong data-state={viewState}>{label(viewState)}</strong>
        <span>legacy admitted · false</span>
        <span>client recalculation · false</span>
        <span>proportional allocation · false</span>
        <span>Approval / Permit · false / false</span>
        <b>external write · false</b>
      </section>

      <section className={styles.flow} aria-label="三本账证据阶梯">
        <article>
          <Fingerprint size={18} />
          <b>01 · Order / Accrual</b>
          <span>正式经营事实</span>
        </article>
        <i>→</i>
        <article>
          <BadgeDollarSign size={18} />
          <b>02 · Settlement</b>
          <span>平台结算权威</span>
        </article>
        <i>→</i>
        <article>
          <Banknote size={18} />
          <b>03 · Bank Cash</b>
          <span>独立到账 Evidence</span>
        </article>
        <i>→</i>
        <article>
          <Scale size={18} />
          <b>04 · Reconcile</b>
          <span>差异与未知费用</span>
        </article>
        <i>→</i>
        <article>
          <Landmark size={18} />
          <b>05 · Actual Cash CM3</b>
          <span>到账后可复算利润</span>
        </article>
      </section>

      <form
        className={styles.filters}
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(queryDraft.trim());
          setStage(stageDraft);
        }}
      >
        <label>
          Reconciliation key / currency
          <input
            value={queryDraft}
            maxLength={160}
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder="exact server filter"
          />
        </label>
        <label>
          Server stage
          <select
            value={stageDraft}
            onChange={(event) => setStageDraft(event.target.value)}
          >
            <option value="">全部阶段</option>
            {stages.map((item) => (
              <option key={item} value={item}>{label(item)}</option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={workspaceBusy}>
          {workspaceBusy ? "重验中…" : "重验服务端快照"}
        </button>
      </form>

      {(scopeBusy || workspaceBusy) && !workspace ? (
        <section className={styles.notice} role="status">
          <RefreshCw size={21} />
          <div>
            <strong>正在读取 exact-scope 三本账</strong>
            <p>真实响应返回前不填充订单、结算、现金或利润。</p>
          </div>
        </section>
      ) : null}

      {viewState === "error" ? (
        <section className={styles.error} role="alert">
          <CircleAlert size={22} />
          <div>
            <strong>财务权威暂不可用</strong>
            <p>{detail}</p>
          </div>
          <button
            type="button"
            onClick={() => (
              storeRef ? void loadWorkspace(storeRef) : void loadScope()
            )}
          >
            重试
          </button>
        </section>
      ) : null}

      {!workspace && viewState === "blocked" && detail ? (
        <section className={styles.error} data-state="blocked">
          <CircleAlert size={22} />
          <div><strong>作用域已失败关闭</strong><p>{detail}</p></div>
          <button type="button" onClick={() => void loadScope()}>重试</button>
        </section>
      ) : null}

      {workspace ? (
        <>
          <section className={styles.scopeBar}>
            <div>
              <span>Tenant</span>
              <strong>{workspace.scope.tenant_ref}</strong>
            </div>
            <div>
              <span>Entity</span>
              <strong>{workspace.scope.entity_ref ?? "no_data"}</strong>
            </div>
            <div>
              <span>Store</span>
              <strong>{workspace.scope.store_ref}</strong>
            </div>
            <div>
              <span>Grant</span>
              <code>{shortHash(workspace.scope.scope_grant_authority_sha256)}</code>
            </div>
            <div>
              <span>As of</span>
              <strong>{workspace.as_of}</strong>
            </div>
          </section>

          <section className={styles.metrics}>
            <article>
              <span>Reconciliation cycles</span>
              <strong>{workspace.counts.total_cycles ?? 0}</strong>
              <small>exact key only</small>
            </article>
            <article>
              <span>平台结算已观察</span>
              <strong>{workspace.counts.settlement_cycles ?? 0}</strong>
              <small>Fact / Entry</small>
            </article>
            <article>
              <span>银行现金已观察</span>
              <strong>{workspace.counts.cash_cycles ?? 0}</strong>
              <small>independent Evidence</small>
            </article>
            <article>
              <span>三本账 reconciled</span>
              <strong>{workspace.counts.reconciled ?? 0}</strong>
              <small>server classified</small>
            </article>
            <article data-highlight>
              <span>Actual Cash CM3 可用</span>
              <strong>{workspace.counts.actual_cash_cm3_available ?? 0}</strong>
              <small>not estimated CM3</small>
            </article>
          </section>

          {workspace.status === "no_data" && workspace.cycles.length === 0 ? (
            <section className={styles.empty} data-state="no_data">
              <Fingerprint size={27} />
              <div>
                <strong>
                  真实 no_data · 当前作用域尚无可验证的三本账 cycle
                </strong>
                <p>
                  0 不代表订单、结算、银行到账或利润已完成。不会读取 legacy
                  财务行，也不会制造演示现金或按比例分摊未知费用。
                </p>
              </div>
            </section>
          ) : null}

          {workspace.status === "blocked" || workspace.status === "partial" ? (
            <section
              className={
                workspace.status === "blocked"
                  ? styles.error
                  : styles.notice
              }
              data-state={workspace.status}
            >
              <CircleAlert size={22} />
              <div>
                <strong>
                  {workspace.status === "blocked"
                    ? "最新权威记录失败关闭"
                    : "三本账尚未闭合"}
                </strong>
                <p>
                  坏 Evidence、未来记录、输入哈希漂移、双来源冲突、未知费用或
                  截断读取不会降级为旧状态；受影响业务值被隐藏。
                </p>
              </div>
            </section>
          ) : null}

          {workspace.blockers.length ? (
            <section className={styles.gapPanel}>
              <header>
                <span>SOURCE GAPS · OWNER · SLA · NEXT</span>
                <h2>先修权威，再结账</h2>
              </header>
              <div>
                {workspace.blockers.map((blocker) => (
                  <article key={blocker.code}>
                    <strong>{blocker.severity} · {blocker.code}</strong>
                    <p>{blocker.next}</p>
                    <small>{blocker.owner} · {blocker.sla}</small>
                    <Link href={blocker.next_workspace}>
                      打开处理工作区 <ChevronRight size={14} />
                    </Link>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          <section className={styles.cycleList}>
            {workspace.cycles.map((cycle) => (
              <details key={cycle.reconciliation_key_sha256} className={styles.cycle}>
                <summary>
                  <span>
                    <small>
                      {cycle.currency ?? "currency withheld"} ·{" "}
                      {cycle.latest_effective_at}
                    </small>
                    <b>{cycle.reconciliation_key}</b>
                    <code>{shortHash(cycle.reconciliation_key_sha256)}</code>
                  </span>
                  <i data-stage={cycle.stage}>{label(cycle.stage)}</i>
                </summary>
                <div className={styles.cycleDetail}>
                  <section className={styles.books}>
                    <article>
                      <span>BOOK 01 · ORDER / ACCRUAL</span>
                      <strong>
                        {money(
                          cycle.books.order_accrual.gross_revenue,
                          cycle.currency,
                        )}
                      </strong>
                      <p>
                        应计{" "}
                        {money(
                          cycle.books.order_accrual.accrual_total,
                          cycle.currency,
                        )}
                      </p>
                      <small>
                        Order {cycle.books.order_accrual.order_fact_count} ·
                        Accrual {cycle.books.order_accrual.accrual_fact_count} ·
                        Fee {cycle.books.order_accrual.fee_fact_count} ·
                        Return {cycle.books.order_accrual.return_fact_count}
                      </small>
                    </article>
                    <article>
                      <span>BOOK 02 · PLATFORM SETTLEMENT</span>
                      <strong>
                        {money(
                          cycle.books.platform_settlement.amount,
                          cycle.currency,
                        )}
                      </strong>
                      <p>{cycle.books.platform_settlement.status}</p>
                      <small>
                        Fact {cycle.books.platform_settlement.fact_count} ·
                        Entry {cycle.books.platform_settlement.entry_count}
                      </small>
                    </article>
                    <article>
                      <span>BOOK 03 · BANK CASH</span>
                      <strong>
                        {money(cycle.books.bank_cash.amount, cycle.currency)}
                      </strong>
                      <p>{cycle.books.bank_cash.status}</p>
                      <small>
                        Entry {cycle.books.bank_cash.entry_count} ·
                        independent Evidence
                      </small>
                    </article>
                  </section>

                  <section className={styles.reconcile}>
                    <article>
                      <span>Expected settlement</span>
                      <strong>
                        {money(
                          cycle.variance.expected_settlement,
                          cycle.currency,
                        )}
                      </strong>
                    </article>
                    <article>
                      <span>Settlement variance</span>
                      <strong>
                        {money(
                          cycle.variance.settlement_variance,
                          cycle.currency,
                        )}
                      </strong>
                      <small>
                        ratio {cycle.variance.settlement_variance_ratio ?? "no_data"}
                      </small>
                    </article>
                    <article>
                      <span>Bank variance</span>
                      <strong>
                        {money(cycle.variance.bank_variance, cycle.currency)}
                      </strong>
                      <small>
                        ratio {cycle.variance.bank_variance_ratio ?? "no_data"}
                      </small>
                    </article>
                    <article>
                      <span>Unknown / review</span>
                      <strong>
                        {cycle.classification.unknown_fee_count} /{" "}
                        {cycle.classification.review_required_count}
                      </strong>
                      <small>
                        fee entries {cycle.classification.fee_entry_count}
                      </small>
                    </article>
                  </section>

                  <section
                    className={styles.cashCm3}
                    data-state={cycle.actual_cash_cm3.status}
                  >
                    <Landmark size={24} />
                    <div>
                      <span>ACTUAL CASH CM3</span>
                      <strong>
                        {cycle.actual_cash_cm3.status === "available"
                          ? money(
                            cycle.actual_cash_cm3.amount,
                            cycle.actual_cash_cm3.currency,
                          )
                          : "no_data"}
                      </strong>
                      <p>
                        {cycle.actual_cash_cm3.reason
                          ?? "三本账与原生 exact-scope 利润权威均已核对"}
                      </p>
                    </div>
                    <code>
                      {shortHash(
                        cycle.actual_cash_cm3.profit_snapshot_sha256,
                      )}
                    </code>
                  </section>

                  <section className={styles.audit}>
                    <div>
                      <span>Latest reconciliation</span>
                      <strong>
                        {cycle.latest_reconciliation?.status ?? "no_data"}
                      </strong>
                      <small>
                        {cycle.latest_reconciliation
                          ? `${cycle.latest_reconciliation.created_by} · ${cycle.latest_reconciliation.recorded_at}`
                          : "独立核对尚未生成"}
                      </small>
                    </div>
                    <div>
                      <span>Evidence</span>
                      <strong>{cycle.evidence.count}</strong>
                      <small>
                        exact and current ·{" "}
                        {String(cycle.evidence.all_current_and_exact_scope)}
                      </small>
                    </div>
                    <div>
                      <span>Owner / SLA</span>
                      <strong>{cycle.owner}</strong>
                      <small>{cycle.sla}</small>
                    </div>
                  </section>

                  {cycle.blockers.length ? (
                    <div className={styles.codeList}>
                      {cycle.blockers.map((blocker) => (
                        <code key={blocker}>{blocker}</code>
                      ))}
                    </div>
                  ) : null}

                  <footer className={styles.next}>
                    <span>{cycle.next}</span>
                    <Link href={cycle.next_workspace}>
                      下一工作区 <ChevronRight size={14} />
                    </Link>
                  </footer>
                </div>
              </details>
            ))}
          </section>

          {workspace.pagination.next_cursor ? (
            <section className={styles.pagination}>
              <span>
                服务端 opaque cursor · 当前 {workspace.counts.page ?? 0}/
                {workspace.counts.filtered ?? 0}
              </span>
              <button
                type="button"
                disabled={workspaceBusy}
                onClick={() => void loadWorkspace(
                  workspace.scope.store_ref,
                  workspace.pagination.next_cursor,
                )}
              >
                {workspaceBusy ? "读取中…" : "读取下一页"}
              </button>
            </section>
          ) : null}

          <section className={styles.agent}>
            <Bot size={26} />
            <div>
              <span>AGENT ARTIFACT · {workspace.agent_artifact.contract_id}</span>
              <h2>Agent 可以建议和建立内部任务，不能记账或动钱</h2>
              <p>
                不能创建 Fact、Finance Entry、Reconciliation、Approval 或
                Permit；不能付款、收款、退款、发起争议或外部写。
              </p>
            </div>
            <code>{shortHash(workspace.agent_artifact.artifact_sha256)}</code>
          </section>

          <footer className={styles.footer}>
            <span>
              {workspace.contract_id} · scoped input{" "}
              {String(workspace.control_envelope.scoped_input_read)}
            </span>
            <span>
              Finance source{" "}
              {shortHash(
                workspace.upstream.finance_source_snapshot_sha256,
              )}
            </span>
            <code>{workspace.snapshot_sha256}</code>
          </footer>
        </>
      ) : null}
    </main>
  );
}
