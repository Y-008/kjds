"use client";

import {
  ArrowLeft,
  Bot,
  CircleAlert,
  Fingerprint,
  LockKeyhole,
  PackageCheck,
  RefreshCw,
  RotateCcw,
  Scale,
  ShieldCheck,
  WalletCards,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { FormEvent } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./returns.module.css";

type Stage =
  | "return_observed"
  | "refund_finance_pending"
  | "refund_settlement_pending"
  | "refund_cash_pending"
  | "refund_reconcile_pending"
  | "refund_reconciled"
  | "variance"
  | "blocked";
type Status = "ready" | "partial" | "blocked" | "no_data";
type ViewState = Status | "loading" | "error";

type ReturnEvent = {
  fact_id: string;
  external_id: string;
  order_external_id: string;
  product_id: string;
  sku: string;
  quantity: number;
  currency: string | null;
  amount: string | null;
  canonical_status: string;
  return_reason: string | null;
  effective_at: string;
  evidence_id: string;
};

type ReturnItem = {
  order_external_id: string;
  product_id: string;
  sku: string;
  stage: Stage;
  ordered_quantity: number;
  returned_quantity: number;
  remaining_quantity: number;
  currency: string | null;
  return_events: ReturnEvent[];
  latest_return: ReturnEvent;
  finance_cycle: {
    reconciliation_key: string;
    stage: string;
    books: Record<string, unknown>;
  } | null;
  finance_status: string;
  customer_service: {
    status: "gated";
    customer_service_case_authority_available: false;
    customer_message_authority_available: false;
    platform_dispute_authority_available: false;
    rma_authority_available: false;
  };
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type Workspace = {
  contract_id: string;
  status: Status;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
  };
  filters: { query: string | null; stage: Stage | null };
  counts: Record<string, number>;
  pagination: { page_size: number; next_cursor: string | null };
  returns: ReturnItem[];
  excluded: {
    count: number;
    reason_counts: Record<string, number>;
    business_values_exposed: false;
  };
  source_gaps: string[];
  blockers: {
    code: string;
    severity: string;
    owner: string;
    next_action: string;
  }[];
  customer_service_authority: {
    status: "gated";
    customer_service_case_authority_available: false;
    customer_message_authority_available: false;
    platform_dispute_authority_available: false;
    rma_authority_available: false;
  };
  owner: string;
  sla: string;
  next: string;
  agent_artifact: {
    artifact_sha256: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    refund_allowed: false;
    customer_message_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    read_only_projection: true;
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    legacy_return_rows_admitted: false;
    return_fact_created: false;
    refund_created: false;
    customer_service_case_created: false;
    customer_message_sent: false;
    dispute_created: false;
    reconciliation_created: false;
    approval_created: false;
    permit_created: false;
    external_write_allowed: false;
    private_erp_interface_allowed: false;
  };
  snapshot_sha256: string;
};

const stages: Stage[] = [
  "return_observed",
  "refund_finance_pending",
  "refund_settlement_pending",
  "refund_cash_pending",
  "refund_reconcile_pending",
  "refund_reconciled",
  "variance",
  "blocked",
];

const labels: Record<string, string> = {
  ready: "权威可用",
  partial: "部分可用",
  blocked: "失败关闭",
  no_data: "真实 no_data",
  loading: "读取中",
  error: "读取失败",
  return_observed: "已观察退货",
  refund_finance_pending: "待退款财务",
  refund_settlement_pending: "待平台结算",
  refund_cash_pending: "待银行回读",
  refund_reconcile_pending: "待独立对账",
  refund_reconciled: "退款已对账",
  variance: "存在差异",
};

function short(value: string | null | undefined) {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "—";
}

export function ReturnsConsole() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    setViewState("loading");
    setMessage("");
    const params = new URLSearchParams({
      store_ref: "ozon-primary",
      page_size: "25",
    });
    if (query.trim()) params.set("query", query.trim());
    if (stage) params.set("stage", stage);
    if (cursor) params.set("cursor", cursor);
    try {
      const response = await fetchJson<Workspace>(
        `/backend/v1/returns/workspace?${params.toString()}`,
        { cache: "no-store" },
      );
      const value = await response.json();
      if (!response.ok) {
        throw new Error(`Returns API ${response.status}`);
      }
      setWorkspace(value);
      setViewState(value.status);
      setSelected((current) =>
        value.returns.some((item) => item.order_external_id === current)
          ? current
          : value.returns[0]?.order_external_id ?? null,
      );
    } catch (error) {
      setViewState("error");
      setMessage(error instanceof Error ? error.message : "退货工作台读取失败");
    }
  }, [cursor, query, stage]);

  useEffect(() => {
    void load();
  }, [load]);

  const detail = useMemo(
    () =>
      workspace?.returns.find(
        (item) => item.order_external_id === selected,
      ) ?? null,
    [selected, workspace],
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    setCursor(null);
    void load();
  }

  return (
    <main className={styles.shell}>
      <header className={styles.hero}>
        <div>
          <Link href="/commerce-os" className={styles.back}>
            <ArrowLeft size={16} /> Commerce OS
          </Link>
          <p className={styles.eyebrow}>Native ERP · exact-scope · read only</p>
          <h1>退货、退款与售后财务控制</h1>
          <p>
            一条服务端链连接正式 Return Fact、订单时间线、平台结算与银行回读；
            客服工单和消息没有权威来源时保持 gated。
          </p>
        </div>
        <div className={styles.heroBadges}>
          <span data-state={viewState}>{labels[viewState]}</span>
          <span><ShieldCheck size={15} /> External write false</span>
          <span><LockKeyhole size={15} /> Private ERP false</span>
        </div>
      </header>

      <nav className={styles.links} aria-label="相邻原生工作台">
        <Link href="/oms">OMS</Link>
        <Link href="/finance-control">Finance Control</Link>
        <Link href="/profit-ledger">Actual Profit</Link>
        <Link href="/customer-service">Customer Service</Link>
        <Link href="/delivery-exceptions">Delivery Exceptions</Link>
        <Link href="/warehouse-fulfillment">Warehouse Fulfillment</Link>
        <Link href="/evidenceops">EvidenceOps</Link>
      </nav>

      <form className={styles.filters} onSubmit={submit}>
        <label>
          Order / Return / SKU
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="服务端精确筛选"
          />
        </label>
        <label>
          阶段
          <select
            value={stage}
            onChange={(event) => setStage(event.target.value)}
          >
            <option value="">全部阶段</option>
            {stages.map((item) => (
              <option key={item} value={item}>{labels[item]}</option>
            ))}
          </select>
        </label>
        <button type="submit"><RefreshCw size={16} /> 读取权威快照</button>
      </form>

      {viewState === "loading" && (
        <section className={styles.stateCard}>
          <RefreshCw className={styles.spin} /> 正在读取 exact-scope 权威…
        </section>
      )}
      {viewState === "error" && (
        <section className={styles.stateCard} data-error="true">
          <CircleAlert />
          <div><strong>读取失败</strong><p>{message}</p></div>
          <button onClick={() => void load()}>重试</button>
        </section>
      )}
      {workspace && viewState !== "loading" && viewState !== "error" && (
        <>
          <section className={styles.metrics}>
            <article><RotateCcw /><span>退货订单</span><strong>{workspace.counts.total_returns}</strong></article>
            <article><PackageCheck /><span>退货事件</span><strong>{workspace.counts.return_events}</strong></article>
            <article><Scale /><span>退货件数</span><strong>{workspace.counts.returned_units}</strong></article>
            <article><WalletCards /><span>完成对账</span><strong>{workspace.counts.refund_reconciled}</strong></article>
          </section>

          <section className={styles.authority}>
            <div>
              <LockKeyhole />
              <h2>客服权威尚未建立</h2>
              <p>
                Case、Message、Dispute、RMA 全部为 gated。页面不会把 Agent
                草稿、第三方 ERP 页面或私有接口冒充已发送消息或正式工单。
              </p>
            </div>
            <code>status={workspace.customer_service_authority.status}</code>
          </section>

          {workspace.returns.length === 0 ? (
            <section className={styles.empty}>
              <RotateCcw />
              <h2>没有可验证退货数据</h2>
              <p>
                当前状态是 {labels[workspace.status]}；Return Fact 不存在时没有读取
                Finance，也没有生成退款、客服或利润结果。
              </p>
              <ul>
                {workspace.source_gaps.map((gap) => <li key={gap}>{gap}</li>)}
              </ul>
            </section>
          ) : (
            <section className={styles.workspace}>
              <div className={styles.list}>
                {workspace.returns.map((item) => (
                  <button
                    key={item.order_external_id}
                    data-active={selected === item.order_external_id}
                    onClick={() => setSelected(item.order_external_id)}
                  >
                    <span>{labels[item.stage]}</span>
                    <strong>{item.order_external_id}</strong>
                    <small>{item.sku} · {item.returned_quantity}/{item.ordered_quantity} 件</small>
                  </button>
                ))}
              </div>
              {detail && (
                <article className={styles.detail}>
                  <header>
                    <div><p>Order</p><h2>{detail.order_external_id}</h2></div>
                    <span>{labels[detail.stage]}</span>
                  </header>
                  <div className={styles.detailGrid}>
                    <div><small>Product / SKU</small><strong>{detail.product_id} / {detail.sku}</strong></div>
                    <div><small>数量守恒</small><strong>{detail.returned_quantity} returned · {detail.remaining_quantity} remaining</strong></div>
                    <div><small>Finance</small><strong>{detail.finance_status}</strong></div>
                    <div><small>Owner / SLA</small><strong>{detail.owner} · {detail.sla}</strong></div>
                  </div>
                  <h3>Return Fact / Evidence timeline</h3>
                  <ol className={styles.timeline}>
                    {detail.return_events.map((event) => (
                      <li key={event.fact_id}>
                        <RotateCcw size={16} />
                        <div>
                          <strong>{event.external_id} · {event.quantity} 件</strong>
                          <p>{event.return_reason ?? "原因未提供"} · {event.amount ?? "金额未提供"} {event.currency ?? ""}</p>
                          <code>Fact {short(event.fact_id)} · Evidence {short(event.evidence_id)}</code>
                        </div>
                      </li>
                    ))}
                  </ol>
                  <p className={styles.next}><strong>Next:</strong> {detail.next}</p>
                </article>
              )}
            </section>
          )}

          <section className={styles.audit}>
            <div><Fingerprint /><span>Snapshot</span><code>{short(workspace.snapshot_sha256)}</code></div>
            <div><Bot /><span>Agent artifact</span><code>{short(workspace.agent_artifact.artifact_sha256)}</code></div>
            <p>
              Agent 只能建议内部任务；self approval、Permit、refund、message、
              dispute 与 external write 全部为 false。
            </p>
          </section>

          {workspace.pagination.next_cursor && (
            <button
              className={styles.nextPage}
              onClick={() => setCursor(workspace.pagination.next_cursor)}
            >
              下一页（opaque cursor）
            </button>
          )}
        </>
      )}
    </main>
  );
}
