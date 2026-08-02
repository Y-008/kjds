"use client";

import {
  ArrowLeft,
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
import styles from "./profit-ledger.module.css";

type LedgerStatus = "reconciled" | "partial" | "blocked" | "no_data";
type ViewState = LedgerStatus | "loading" | "error";

type CostLeg = {
  cost_type: string;
  status: "actual" | "zero" | "unknown";
  amount: string | null;
  currency: string;
  evidence_ids: string[];
  source_count: number;
};

type ProfitRow = {
  grain_key: string;
  order_ref: string | null;
  order_count: number;
  product_id: string | null;
  sku: string | null;
  product_name: string | null;
  latest_effective_at: string;
  status: "reconciled";
  currency: string;
  gross_revenue: string;
  net_revenue: string;
  total_cost: string;
  cm1: string;
  cm2: string;
  cm3: string;
  cm3_rate: string;
  actual_profit: string;
  actual_cash_cm3: {
    status: "available";
    amount: string;
    currency: string;
  };
  cost_legs: CostLeg[];
  cost_coverage: {
    required: number;
    actual_or_zero: number;
    unknown: number;
  };
  coverage_ratio: string;
  cash_conservation: {
    gross_plus_platform_adjustments: string;
    platform_settlement: string;
    bank_receipt: string;
    bank_payments: string;
    actual_cash_profit: string;
    conservation_delta: string;
    conserved: boolean;
  };
  reconciliation: {
    status: string;
    quote_currency: string;
    tolerance_ratio: string;
    recorded_at: string;
    input_sha256: string;
  };
  evidence_ids: string[];
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
  snapshot_sha256: string;
};

type Blocker = {
  code: string;
  severity: string;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type ProfitLedger = {
  contract_id: string;
  registry_version: string;
  status: LedgerStatus;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
    status: string;
    authority: string | null;
    reason?: string;
  };
  store_ref: string;
  grain: "order" | "sku";
  currency: string;
  counts: Record<string, number>;
  pagination: {
    page_size: number;
    next_cursor: string | null;
  };
  rows: ProfitRow[];
  excluded: {
    count: number;
    reason_counts: Record<string, number>;
    business_values_exposed: false;
  };
  source_gaps: string[];
  blockers: Blocker[];
  source_snapshot_sha256: string | null;
  artifact: {
    contract_id: string;
    artifact_version: string;
    input_sha256: string | null;
    status: string;
    artifact_sha256: string;
    writes: Record<string, false>;
  };
  control_envelope: {
    read_only: true;
    native_exact_scope: true;
    scoped_input_read: boolean;
    legacy_order_charge_read: false;
    legacy_finance_read: false;
    client_recalculation: false;
    explicit_order_binding_only: true;
    proportional_allocation_allowed: false;
    fifteen_cost_legs_required: true;
    explicit_zero_evidence_required: true;
    actual_profit_requires_reconciliation: true;
    agent_self_approval_allowed: false;
    agent_permit_issue_allowed: false;
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

const labels: Record<string, string> = {
  reconciled: "已核对",
  partial: "部分可用",
  blocked: "失败关闭",
  no_data: "真实 no_data",
  loading: "读取中",
  error: "读取失败",
};

const costLabels: Record<string, string> = {
  product_cost: "采购成本",
  domestic_logistics: "国内物流",
  international_logistics: "国际头程",
  packaging: "包装",
  warehousing: "仓储",
  customs: "关税",
  tax: "税费",
  last_mile: "尾程",
  platform_fee: "平台佣金",
  advertising: "广告",
  return: "退款退货",
  fx: "汇兑",
  capital_cost: "资金占用",
  customer_compensation: "售后赔付",
  damage: "损耗",
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

export function ProfitLedgerConsole() {
  const [stores, setStores] = useState<string[]>([]);
  const [storeRef, setStoreRef] = useState("");
  const [ledger, setLedger] = useState<ProfitLedger | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [scopeBusy, setScopeBusy] = useState(true);
  const [ledgerBusy, setLedgerBusy] = useState(false);
  const [detail, setDetail] = useState("");
  const [queryDraft, setQueryDraft] = useState("");
  const [grainDraft, setGrainDraft] = useState<"order" | "sku">("order");
  const [query, setQuery] = useState("");
  const [grain, setGrain] = useState<"order" | "sku">("order");

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
          "当前身份没有授权店铺；利润账不会回退到 legacy 或全局订单账。",
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

  const loadLedger = useCallback(
    async (
      store: string,
      cursor?: string | null,
      signal?: AbortSignal,
    ) => {
      if (!store) return;
      setLedgerBusy(true);
      setDetail("");
      try {
        const params = new URLSearchParams({
          store_ref: store,
          grain,
          currency: "CNY",
          page_size: "50",
        });
        if (query) params.set("query", query);
        if (cursor) params.set("cursor", cursor);
        const response = await fetchJson<ProfitLedger | ErrorPayload>(
          `/backend/v1/profit-ledger?${params.toString()}`,
          { cache: "no-store", signal },
        );
        if (redirectForAuth(response.status)) return;
        const body = await response.json();
        if (!response.ok) {
          setLedger(null);
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
        const next = body as ProfitLedger;
        setLedger(next);
        setViewState(next.status);
      } catch (reason) {
        if (signal?.aborted) return;
        setLedger(null);
        setViewState("error");
        setDetail(
          reason instanceof Error
            ? reason.message
            : "原生实际利润权威暂不可用",
        );
      } finally {
        if (!signal?.aborted) setLedgerBusy(false);
      }
    },
    [grain, query, redirectForAuth],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadScope(controller.signal);
    return () => controller.abort("profit scope unmounted");
  }, [loadScope]);

  useEffect(() => {
    if (!storeRef) return;
    const controller = new AbortController();
    void loadLedger(storeRef, null, controller.signal);
    return () => controller.abort("profit ledger changed");
  }, [loadLedger, storeRef]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/commerce-os" className={styles.backLink}>
          <ArrowLeft size={16} />
          Commerce OS
        </Link>
        <div className={styles.productMark}>
          <span><Scale size={18} /></span>
          <div>
            <strong>十五项实际利润账</strong>
            <small>NATIVE EXACT-SCOPE · ACTUAL CASH CM3</small>
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
            15 COST LEGS · EXACT ORDER BINDING · NO ALLOCATION
          </span>
          <h1>
            不是估算利润，
            <em>是到账后仍守恒的实际 CM3</em>
          </h1>
          <p>
            服务端直接组合当前 Order Fact、Canonical Product、逐订单
            Finance Entry、费用映射、FX 和独立 Reconciliation。页面不重算
            CM1/CM2/CM3，不把 unknown 当 0，也不按 SKU 或店铺比例分摊成本。
          </p>
        </div>
        <aside>
          <LockKeyhole size={24} />
          <strong>十五项缺一项即失败关闭</strong>
          <p>
            显式零也必须有 Evidence；Agent 不得创建账、审批、Permit、付款、
            调价、投放或任何外部写。
          </p>
          <small>
            {ledger
              ? shortHash(ledger.snapshot_sha256)
              : "等待服务端权威快照"}
          </small>
        </aside>
      </section>

      <section className={styles.boundary} aria-label="实际利润控制边界">
        <strong data-state={viewState}>{label(viewState)}</strong>
        <span>native exact scope · true</span>
        <span>client recalculation · false</span>
        <span>proportional allocation · false</span>
        <span>self Approval / Permit · false / false</span>
        <b>external write · false</b>
      </section>

      <section className={styles.truthRail} aria-label="实际利润证据阶梯">
        <article><Fingerprint size={18} /><b>ORDER FACT</b><span>当前订单与商品绑定</span></article>
        <i>→</i>
        <article><Scale size={18} /><b>15 COST LEGS</b><span>actual / zero / unknown</span></article>
        <i>→</i>
        <article><Landmark size={18} /><b>RECONCILIATION</b><span>独立复核与输入哈希</span></article>
        <i>→</i>
        <article><Banknote size={18} /><b>BANK CASH</b><span>到账、付款与守恒</span></article>
      </section>

      <form
        className={styles.filters}
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(queryDraft.trim());
          setGrain(grainDraft);
        }}
      >
        <label>
          Order / SKU / Product
          <input
            value={queryDraft}
            maxLength={160}
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder="服务端 exact filter"
          />
        </label>
        <label>
          Server grain
          <select
            value={grainDraft}
            onChange={(event) =>
              setGrainDraft(event.target.value as "order" | "sku")
            }
          >
            <option value="order">逐订单</option>
            <option value="sku">按 SKU 聚合</option>
          </select>
        </label>
        <button type="submit" disabled={ledgerBusy}>
          {ledgerBusy ? "重验中…" : "重验服务端快照"}
        </button>
      </form>

      {(scopeBusy || ledgerBusy) && !ledger ? (
        <section className={styles.notice} role="status">
          <RefreshCw size={21} />
          <div>
            <strong>正在读取原生 exact-scope 利润权威</strong>
            <p>真实响应返回前不填充订单、成本、现金或利润。</p>
          </div>
        </section>
      ) : null}

      {viewState === "error" ? (
        <section className={styles.error} role="alert">
          <CircleAlert size={22} />
          <div>
            <strong>实际利润权威暂不可用</strong>
            <p>{detail}</p>
          </div>
          <button
            type="button"
            onClick={() => (
              storeRef ? void loadLedger(storeRef) : void loadScope()
            )}
          >
            重试
          </button>
        </section>
      ) : null}

      {!ledger && viewState === "blocked" && detail ? (
        <section className={styles.error} data-state="blocked" role="alert">
          <CircleAlert size={22} />
          <div><strong>作用域已失败关闭</strong><p>{detail}</p></div>
          <button type="button" onClick={() => void loadScope()}>重试</button>
        </section>
      ) : null}

      {ledger ? (
        <>
          <section className={styles.scopeBar}>
            <div><span>Tenant</span><strong>{ledger.scope.tenant_ref}</strong></div>
            <div><span>Entity</span><strong>{ledger.scope.entity_ref ?? "no_data"}</strong></div>
            <div><span>Store</span><strong>{ledger.scope.store_ref}</strong></div>
            <div><span>Authority</span><strong>{ledger.scope.authority ?? "no_data"}</strong></div>
            <div><span>As of</span><strong>{ledger.as_of}</strong></div>
          </section>

          <section className={styles.metrics}>
            <article>
              <span>Order candidates</span>
              <strong>{ledger.counts.order_candidates ?? 0}</strong>
              <small>current scoped Fact</small>
            </article>
            <article>
              <span>Reconciled</span>
              <strong>{ledger.counts.reconciled ?? 0}</strong>
              <small>15 legs + cash</small>
            </article>
            <article>
              <span>Excluded</span>
              <strong>{ledger.counts.excluded ?? 0}</strong>
              <small>business values hidden</small>
            </article>
            <article>
              <span>Filtered</span>
              <strong>{ledger.counts.filtered ?? 0}</strong>
              <small>server-owned count</small>
            </article>
          </section>

          {ledger.status === "no_data" && ledger.rows.length === 0 ? (
            <section className={styles.empty} data-state="no_data">
              <Fingerprint size={27} />
              <div>
                <strong>
                  真实 no_data · 当前作用域没有可验证 Actual Cash CM3
                </strong>
                <p>
                  0 不代表订单、十五项成本、结算、银行现金或利润已完成；
                  不读取 legacy 行，也不制造演示订单或利润。
                </p>
              </div>
            </section>
          ) : null}

          {ledger.status === "blocked" || ledger.status === "partial" ? (
            <section
              className={
                ledger.status === "blocked" ? styles.error : styles.notice
              }
              data-state={ledger.status}
              role={ledger.status === "blocked" ? "alert" : "status"}
            >
              <CircleAlert size={22} />
              <div>
                <strong>
                  {ledger.status === "blocked"
                    ? "最新权威记录失败关闭"
                    : "部分订单可核对，其余仍被隔离"}
                </strong>
                <p>
                  坏 Evidence、未来记录、跨 scope、输入哈希漂移、unknown fee、
                  成本腿缺失或现金不守恒均不会回退到旧记录。
                </p>
              </div>
            </section>
          ) : null}

          {ledger.blockers.length ? (
            <section className={styles.gapPanel}>
              <header><span>SOURCE GAPS · OWNER · SLA · NEXT</span><h2>先补事实，再谈利润</h2></header>
              <div>
                {ledger.blockers.map((blocker) => (
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

          <section className={styles.rowList}>
            {ledger.rows.map((row) => (
              <details key={row.snapshot_sha256} className={styles.profitRow}>
                <summary>
                  <span>
                    <small>{row.latest_effective_at} · {row.currency}</small>
                    <b>{row.product_name ?? row.grain_key}</b>
                    <code>{row.sku ?? "sku withheld"} · {row.grain_key}</code>
                  </span>
                  <div>
                    <small>ACTUAL CASH CM3</small>
                    <strong>{money(row.actual_cash_cm3.amount, row.currency)}</strong>
                    <i>{label(row.status)}</i>
                  </div>
                </summary>
                <div className={styles.rowDetail}>
                  <section className={styles.marginGrid}>
                    <article><span>Gross revenue</span><strong>{money(row.gross_revenue, row.currency)}</strong></article>
                    <article><span>Net revenue</span><strong>{money(row.net_revenue, row.currency)}</strong></article>
                    <article><span>CM1</span><strong>{money(row.cm1, row.currency)}</strong></article>
                    <article><span>CM2</span><strong>{money(row.cm2, row.currency)}</strong></article>
                    <article data-highlight><span>CM3</span><strong>{money(row.cm3, row.currency)}</strong><small>rate {row.cm3_rate}</small></article>
                  </section>

                  <section className={styles.costSection}>
                    <header>
                      <div><span>FIFTEEN ACTUAL COST LEGS</span><h3>逐项 Evidence，不允许按比例补数</h3></div>
                      <strong>
                        {row.cost_coverage.actual_or_zero}/{row.cost_coverage.required}
                      </strong>
                    </header>
                    <div className={styles.costGrid}>
                      {row.cost_legs.map((leg, index) => (
                        <article key={leg.cost_type} data-state={leg.status}>
                          <small>{String(index + 1).padStart(2, "0")}</small>
                          <span>{costLabels[leg.cost_type] ?? leg.cost_type}</span>
                          <strong>{money(leg.amount, leg.currency)}</strong>
                          <i>{leg.status} · Evidence {leg.evidence_ids.length}</i>
                        </article>
                      ))}
                    </div>
                  </section>

                  <section className={styles.cashConservation}>
                    <div>
                      <span>Platform expected</span>
                      <strong>{money(row.cash_conservation.gross_plus_platform_adjustments, row.currency)}</strong>
                    </div>
                    <div>
                      <span>Platform settlement</span>
                      <strong>{money(row.cash_conservation.platform_settlement, row.currency)}</strong>
                    </div>
                    <div>
                      <span>Bank receipt</span>
                      <strong>{money(row.cash_conservation.bank_receipt, row.currency)}</strong>
                    </div>
                    <div>
                      <span>Bank payments</span>
                      <strong>{money(row.cash_conservation.bank_payments, row.currency)}</strong>
                    </div>
                    <div data-state={String(row.cash_conservation.conserved)}>
                      <span>Conservation delta</span>
                      <strong>{money(row.cash_conservation.conservation_delta, row.currency)}</strong>
                      <small>conserved · {String(row.cash_conservation.conserved)}</small>
                    </div>
                  </section>

                  <section className={styles.audit}>
                    <div><span>Reconciliation</span><strong>{row.reconciliation.status}</strong><small>{row.reconciliation.recorded_at}</small></div>
                    <div><span>Input hash</span><code>{shortHash(row.reconciliation.input_sha256)}</code><small>independent verifier input</small></div>
                    <div><span>Evidence</span><strong>{row.evidence_ids.length}</strong><small>exact scope and current</small></div>
                    <div><span>Owner / SLA</span><strong>{row.owner}</strong><small>{row.sla}</small></div>
                  </section>
                  <footer className={styles.next}>
                    <span>{row.next}</span>
                    <Link href={row.next_workspace}>
                      进入结算控制 <ChevronRight size={14} />
                    </Link>
                  </footer>
                </div>
              </details>
            ))}
          </section>

          {ledger.pagination.next_cursor ? (
            <section className={styles.pagination}>
              <span>
                服务端 opaque cursor · 当前 {ledger.counts.page ?? 0}/
                {ledger.counts.filtered ?? 0}
              </span>
              <button
                type="button"
                disabled={ledgerBusy}
                onClick={() => void loadLedger(
                  ledger.scope.store_ref,
                  ledger.pagination.next_cursor,
                )}
              >
                {ledgerBusy ? "读取中…" : "读取下一页"}
              </button>
            </section>
          ) : null}

          <section className={styles.agent}>
            <Bot size={26} />
            <div>
              <span>AGENT ARTIFACT · {ledger.artifact.contract_id}</span>
              <h2>Agent 只能建议或建立内部任务</h2>
              <p>
                Fact、Product、Mapping、FX、Entry、Reconciliation、Approval、
                Permit、付款、退款、调价、投放和 external write 全部为 false。
              </p>
            </div>
            <code>{shortHash(ledger.artifact.artifact_sha256)}</code>
          </section>

          <footer className={styles.footer}>
            <div>
              <Link href="/finance-control">结算与现金控制</Link>
              <Link href="/oms">原生 OMS</Link>
              <Link href="/commerce-os">Commerce OS</Link>
            </div>
            <span>
              {ledger.contract_id} · native exact scope{" "}
              {String(ledger.control_envelope.native_exact_scope)}
            </span>
            <code>{ledger.snapshot_sha256}</code>
          </footer>
        </>
      ) : null}
    </main>
  );
}
