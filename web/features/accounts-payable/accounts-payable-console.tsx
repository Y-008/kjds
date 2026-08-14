"use client";

import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  FileCheck2,
  Fingerprint,
  Landmark,
  LockKeyhole,
  ReceiptText,
  RefreshCw,
  Scale,
  ShieldCheck,
  Store,
  WalletCards,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./accounts-payable.module.css";

type WorkspaceStatus = "ready" | "partial" | "blocked" | "no_data";
type ViewState = WorkspaceStatus | "loading" | "error";
type Stage =
  | "invoice_captured"
  | "review_pending"
  | "rejected"
  | "three_way_match_pending"
  | "matched"
  | "payment_approval_pending"
  | "payment_permit_pending"
  | "payment_readback_pending"
  | "partially_paid"
  | "settled"
  | "variance"
  | "blocked";

type Invoice = {
  invoice_id: string;
  invoice_ref: string;
  purchase_order_id: string;
  supplier_ref: string;
  currency: string;
  issued_at: string;
  due_at: string;
  recorded_at: string;
  amounts: {
    net: string;
    tax: string;
    gross: string;
    paid: string;
    open: string;
    client_recalculation_allowed: false;
  };
  lines: {
    id: string;
    line_number: number;
    product_id: string;
    description: string;
    quantity: string;
    unit_price: string;
    net_amount: string;
    tax_amount: string;
    gross_amount: string;
    evidence_id: string;
  }[];
  stage: Stage;
  review: {
    status: string;
    review_evidence_id: string | null;
    reviewed_by: string | null;
    independent: boolean;
    checks: Record<string, boolean>;
  };
  three_way_match: {
    status: string;
    matched: boolean;
    checks: Record<string, boolean>;
    server_authoritative: true;
  };
  procurement: {
    stage: string;
    product: { id: string; sku: string; name: string };
    ordered_quantity: number;
    unit_price: string;
    order_value: string;
    receipt: {
      ordered_quantity: number;
      received_quantity: number | null;
      inspected_quantity: number | null;
      passed_quantity: number | null;
      defect_count: number | null;
      quantity_conserved: true;
    };
    decision_basis: {
      approval_id: string;
      approval_status: string;
      independent_approval: boolean;
    };
  };
  payment_control: {
    status: string;
    approval_id: string | null;
    command_id: string | null;
    receipt_id: string | null;
    bank_entry_ids: string[];
    one_time_permit_verified: boolean;
    readback_verified: boolean;
    adapter_enabled: false;
    payment_execution_available: false;
  };
  evidence: {
    invoice_evidence_id: string;
    invoice_evidence_sha256: string;
    payload_sha256: string;
    payment_evidence_ids: string[];
  };
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
  filters: { query: string | null; stage: Stage | null };
  counts: Record<string, number>;
  pagination: { page_size: number; next_cursor: string | null };
  invoices: Invoice[];
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
    workspace: string;
  }[];
  owner: string;
  sla: string;
  next: string;
  upstream: { source_snapshot_sha256: string | null };
  agent_artifact: {
    contract_id: string;
    version: string;
    artifact_sha256: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    invoice_creation_allowed: false;
    payment_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    read_only_projection: true;
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    legacy_invoice_rows_admitted: false;
    invoice_created: false;
    invoice_review_created: false;
    approval_created: false;
    permit_created: false;
    payment_initiated: false;
    bank_entry_created: false;
    external_write_allowed: false;
    private_erp_interface_allowed: false;
  };
  snapshot_sha256: string;
};

type StrategyPacks = {
  authorized_scope: { tenant_ref: string; store_refs: string[] };
};
type ErrorPayload = { detail?: string };

const stages: Stage[] = [
  "invoice_captured",
  "review_pending",
  "rejected",
  "three_way_match_pending",
  "matched",
  "payment_approval_pending",
  "payment_permit_pending",
  "payment_readback_pending",
  "partially_paid",
  "settled",
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
  invoice_captured: "发票已捕获",
  review_pending: "待独立复核",
  rejected: "复核拒绝",
  three_way_match_pending: "三单匹配待完成",
  matched: "三单匹配完成",
  payment_approval_pending: "待付款审批",
  payment_permit_pending: "待一次性 Permit",
  payment_readback_pending: "待付款回读",
  partially_paid: "部分付款",
  settled: "已结清",
  variance: "付款差异",
};

function label(value: string) {
  return labels[value] ?? value;
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "no_data";
}

export function AccountsPayableConsole() {
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

  const loadScope = useCallback(
    async (signal?: AbortSignal) => {
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
          setDetail("当前身份没有授权店铺；应付控制不会回退读取 legacy 全局发票。");
        }
      } catch (reason) {
        if (signal?.aborted) return;
        setViewState("error");
        setDetail(reason instanceof Error ? reason.message : "授权作用域读取失败");
      } finally {
        if (!signal?.aborted) setScopeBusy(false);
      }
    },
    [redirectForAuth],
  );

  const loadWorkspace = useCallback(
    async (store: string, cursor?: string | null, signal?: AbortSignal) => {
      if (!store) return;
      setWorkspaceBusy(true);
      setDetail("");
      try {
        const params = new URLSearchParams({
          store_ref: store,
          page_size: "25",
        });
        if (query) params.set("query", query);
        if (stage) params.set("stage", stage);
        if (cursor) params.set("cursor", cursor);
        const response = await fetchJson<Workspace | ErrorPayload>(
          `/backend/v1/accounts-payable/workspace?${params.toString()}`,
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
        setWorkspace((current) =>
          cursor && current
            ? { ...next, invoices: [...current.invoices, ...next.invoices] }
            : next,
        );
        setViewState(next.status);
      } catch (reason) {
        if (signal?.aborted) return;
        setWorkspace(null);
        setViewState("error");
        setDetail(reason instanceof Error ? reason.message : "应付权威暂不可用");
      } finally {
        if (!signal?.aborted) setWorkspaceBusy(false);
      }
    },
    [query, redirectForAuth, stage],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadScope(controller.signal);
    return () => controller.abort("accounts payable scope unmounted");
  }, [loadScope]);

  useEffect(() => {
    if (!storeRef) return;
    const controller = new AbortController();
    void loadWorkspace(storeRef, null, controller.signal);
    return () => controller.abort("accounts payable store changed");
  }, [loadWorkspace, storeRef]);

  const busy = scopeBusy || workspaceBusy;

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link className={styles.backLink} href="/commerce-os">
          <ArrowLeft size={15} />
          Commerce OS
        </Link>
        <div className={styles.productMark}>
          <span>
            <ReceiptText size={18} />
          </span>
          <div>
            <strong>KJDS ACCOUNTS PAYABLE</strong>
            <small>EXACT-SCOPE · THREE-WAY MATCH · READ ONLY</small>
          </div>
        </div>
        <label className={styles.storePicker}>
          <Store size={14} />
          <select
            aria-label="授权店铺"
            disabled={scopeBusy}
            onChange={(event) => setStoreRef(event.target.value)}
            value={storeRef}
          >
            {stores.length ? (
              stores.map((store) => (
                <option key={store} value={store}>
                  {store}
                </option>
              ))
            ) : (
              <option value="">无授权店铺</option>
            )}
          </select>
        </label>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>
            <Scale size={14} /> OBSERVATION → INVOICE → MATCH → CASH
          </span>
          <h1>
            发票不是付款，
            <em>三单匹配与银行回读才构成闭环。</em>
          </h1>
          <p>
            将供应商发票、采购订单、收货验货、独立 Approval、一次性 Permit、
            执行 Receipt 与 BANK_PAYMENT 绑定为同一 exact-scope 权威链。
            最新权威记录失败关闭，页面不重算金额、余额、匹配或阶段。
          </p>
        </div>
        <aside>
          <LockKeyhole size={22} />
          <b>付款 Adapter 未启用</b>
          <p>当前只读投影；Agent 不能自批、自发 Permit 或发起供应商付款。</p>
          <small>
            私有 ERP 接口、Cookie、内部 Token 与 external write 均为 false。
          </small>
        </aside>
      </section>

      <section className={styles.flow} aria-label="应付权威业务流">
        {[
          ["Supplier Invoice", "不可变头与行"],
          ["PO / Receipt", "采购与验货"],
          ["3-Way Match", "服务端确定性校验"],
          ["Approval / Permit", "独立审批与一次性授权"],
          ["Bank Readback", "唯一付款账与回读"],
        ].map(([title, text], index) => (
          <div className={styles.flowUnit} key={title}>
            <article>
              {index === 0 ? <ReceiptText size={17} /> : null}
              {index === 1 ? <FileCheck2 size={17} /> : null}
              {index === 2 ? <Scale size={17} /> : null}
              {index === 3 ? <ShieldCheck size={17} /> : null}
              {index === 4 ? <Landmark size={17} /> : null}
              <b>{title}</b>
              <span>{text}</span>
            </article>
            {index < 4 ? <ChevronRight size={16} /> : null}
          </div>
        ))}
      </section>

      <section className={styles.filters}>
        <label>
          搜索发票 / PO / 供应商 / SKU
          <input
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder="INV-001 / supplier / SKU"
            value={queryDraft}
          />
        </label>
        <label>
          服务端阶段
          <select
            onChange={(event) => setStageDraft(event.target.value)}
            value={stageDraft}
          >
            <option value="">全部阶段</option>
            {stages.map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={busy}
          onClick={() => {
            setQuery(queryDraft.trim());
            setStage(stageDraft);
          }}
          type="button"
        >
          {busy ? <RefreshCw className={styles.spin} size={15} /> : <Fingerprint size={15} />}
          应用权威筛选
        </button>
      </section>

      {viewState === "loading" || busy ? (
        <section className={styles.notice} role="status">
          <RefreshCw className={styles.spin} size={19} />
          <div>
            <strong>读取 exact-scope 应付快照</strong>
            <p>服务端正在验证 Evidence、发票、三单匹配与付款权威。</p>
          </div>
        </section>
      ) : null}

      {detail ? (
        <section className={styles.error} role="alert">
          <CircleAlert size={20} />
          <div>
            <strong>{label(viewState)}</strong>
            <p>{detail}</p>
          </div>
          <button
            onClick={() => {
              if (storeRef) void loadWorkspace(storeRef);
              else void loadScope();
            }}
            type="button"
          >
            重试
          </button>
        </section>
      ) : null}

      {workspace ? (
        <>
          <section className={styles.boundary}>
            <div>
              <span>状态</span>
              <strong data-state={workspace.status}>{label(workspace.status)}</strong>
            </div>
            <div>
              <span>Entity</span>
              <strong>{workspace.scope.entity_ref ?? "no_data"}</strong>
            </div>
            <div>
              <span>发票</span>
              <strong>{workspace.counts.total ?? 0}</strong>
            </div>
            <div>
              <span>排除</span>
              <strong>{workspace.excluded.count}</strong>
            </div>
            <div>
              <span>付款执行</span>
              <strong data-state="blocked">关闭</strong>
            </div>
            <div>
              <span>external write</span>
              <strong data-state="blocked">false</strong>
            </div>
          </section>

          <section className={styles.scopeBar}>
            <div>
              <span>tenant</span>
              <code>{workspace.scope.tenant_ref}</code>
            </div>
            <div>
              <span>store</span>
              <code>{workspace.scope.store_ref}</code>
            </div>
            <div>
              <span>as_of</span>
              <code>{workspace.as_of}</code>
            </div>
            <div>
              <span>scope grant</span>
              <code>{shortHash(workspace.scope.scope_grant_authority_sha256)}</code>
            </div>
            <div>
              <span>snapshot</span>
              <code>{shortHash(workspace.snapshot_sha256)}</code>
            </div>
          </section>

          <section className={styles.metrics}>
            {[
              ["发票总数", workspace.counts.total ?? 0],
              ["待复核", workspace.counts.review_pending ?? 0],
              ["三单待匹配", workspace.counts.three_way_match_pending ?? 0],
              ["待付款审批", workspace.counts.payment_approval_pending ?? 0],
              ["已结清", workspace.counts.settled ?? 0],
            ].map(([title, value]) => (
              <article key={String(title)}>
                <span>{title}</span>
                <strong>{value}</strong>
                <small>server-side count</small>
              </article>
            ))}
          </section>

          {workspace.source_gaps.length ? (
            <section className={styles.gapPanel}>
              <header>
                <div>
                  <CircleAlert size={16} />
                  <strong>Source gaps / blockers</strong>
                </div>
                <small>最新坏记录失败关闭；被排除业务值不展示</small>
              </header>
              <div>
                {workspace.source_gaps.map((gap) => (
                  <span key={gap}>{gap}</span>
                ))}
              </div>
            </section>
          ) : null}

          {workspace.status === "no_data" ? (
            <section className={styles.empty} role="status">
              <ReceiptText size={24} />
              <div>
                <strong>真实 no_data</strong>
                <p>
                  当前 exact tenant / entity / store / as_of 没有可用供应商发票；
                  系统不会把采购金额冒充应付，也不会伪造已付款。
                </p>
              </div>
            </section>
          ) : null}

          <section className={styles.invoiceList}>
            {workspace.invoices.map((invoice) => (
              <article className={styles.invoice} key={invoice.invoice_id}>
                <header>
                  <div>
                    <span className={styles.stage}>{label(invoice.stage)}</span>
                    <h2>{invoice.invoice_ref}</h2>
                    <p>{invoice.supplier_ref} · PO {invoice.purchase_order_id}</p>
                  </div>
                  <div className={styles.amount}>
                    <small>OPEN / GROSS</small>
                    <strong>
                      {invoice.currency} {invoice.amounts.open}
                    </strong>
                    <span>总额 {invoice.amounts.gross} · 已付 {invoice.amounts.paid}</span>
                  </div>
                </header>

                <section className={styles.invoiceGrid}>
                  <div>
                    <span>商品</span>
                    <strong>{invoice.procurement.product.name}</strong>
                    <small>{invoice.procurement.product.sku}</small>
                  </div>
                  <div>
                    <span>开票 / 到期</span>
                    <strong>{invoice.issued_at}</strong>
                    <small>{invoice.due_at}</small>
                  </div>
                  <div>
                    <span>发票 Evidence</span>
                    <code>{invoice.evidence.invoice_evidence_id}</code>
                    <small>{shortHash(invoice.evidence.invoice_evidence_sha256)}</small>
                  </div>
                  <div>
                    <span>Owner / SLA</span>
                    <strong>{invoice.owner}</strong>
                    <small>{invoice.sla}</small>
                  </div>
                </section>

                <section className={styles.controlGrid}>
                  <div>
                    <h3>
                      <FileCheck2 size={16} /> Invoice review
                    </h3>
                    <b data-pass={invoice.review.status === "accepted"}>
                      {invoice.review.status}
                    </b>
                    <p>
                      reviewer {invoice.review.reviewed_by ?? "no_data"} · independent{" "}
                      {String(invoice.review.independent)}
                    </p>
                    <ul>
                      {Object.entries(invoice.review.checks).map(([key, value]) => (
                        <li key={key} data-pass={value}>
                          {value ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}
                          {key}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h3>
                      <Scale size={16} /> Three-way match
                    </h3>
                    <b data-pass={invoice.three_way_match.matched}>
                      {invoice.three_way_match.status}
                    </b>
                    <p>Invoice ↔ PO ↔ receipt / inspection</p>
                    <ul>
                      {Object.entries(invoice.three_way_match.checks).map(
                        ([key, value]) => (
                          <li key={key} data-pass={value}>
                            {value ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}
                            {key}
                          </li>
                        ),
                      )}
                    </ul>
                  </div>
                  <div>
                    <h3>
                      <WalletCards size={16} /> Approval / Permit / Readback
                    </h3>
                    <b data-pass={invoice.payment_control.readback_verified}>
                      {invoice.payment_control.status}
                    </b>
                    <p>Approval {invoice.payment_control.approval_id ?? "no_data"}</p>
                    <p>Permit {invoice.payment_control.command_id ?? "no_data"}</p>
                    <p>Receipt {invoice.payment_control.receipt_id ?? "no_data"}</p>
                    <p>
                      one-time {String(invoice.payment_control.one_time_permit_verified)}
                      {" · "}readback {String(invoice.payment_control.readback_verified)}
                    </p>
                    <strong className={styles.closed}>Adapter disabled · payment false</strong>
                  </div>
                </section>

                <footer>
                  <span>Next</span>
                  <strong>{invoice.next}</strong>
                  <code>{shortHash(invoice.evidence.payload_sha256)}</code>
                </footer>
              </article>
            ))}
          </section>

          {workspace.pagination.next_cursor ? (
            <section className={styles.pagination}>
              <button
                disabled={workspaceBusy}
                onClick={() =>
                  void loadWorkspace(storeRef, workspace.pagination.next_cursor)
                }
                type="button"
              >
                读取下一页（服务端 opaque cursor）
              </button>
            </section>
          ) : null}

          <section className={styles.agent}>
            <Bot size={22} />
            <div>
              <strong>Agent artifact：仅建议与内部任务</strong>
              <p>
                {workspace.agent_artifact.contract_id} ·{" "}
                {shortHash(workspace.agent_artifact.artifact_sha256)}
              </p>
              <small>
                self approval false · permit issue false · payment false ·
                external write false · client recalculation false
              </small>
            </div>
          </section>
        </>
      ) : null}

      <footer className={styles.footer}>
        <div>
          <ShieldCheck size={18} />
          <p>
            不使用店小秘私有接口、Cookie 或内部 Token；仅接受官方、正式导出或明确授权 Adapter，
            并保持 Evidence、撤销与审计边界。
          </p>
        </div>
        <nav>
          <Link href="/procurement">采购与收货</Link>
          <Link href="/finance-control">结算与现金</Link>
          <Link href="/profit-ledger">十五项利润</Link>
          <Link href="/inventory">库存履约</Link>
        </nav>
      </footer>
    </main>
  );
}
