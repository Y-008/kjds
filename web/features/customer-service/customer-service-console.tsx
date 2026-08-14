"use client";

import {
  ArrowLeft,
  Bot,
  CircleAlert,
  Clock3,
  Fingerprint,
  Languages,
  LockKeyhole,
  MessageSquareText,
  RefreshCw,
  Scale,
  ShieldCheck,
  TicketCheck,
  UserRoundCheck,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./customer-service.module.css";

type Stage =
  | "opened"
  | "triaged"
  | "reply_drafted"
  | "reply_approval_pending"
  | "reply_permit_pending"
  | "reply_readback_pending"
  | "awaiting_customer"
  | "return_in_progress"
  | "dispute_in_progress"
  | "resolved"
  | "closed"
  | "blocked";
type Status = "ready" | "partial" | "blocked" | "no_data";
type ViewState = Status | "loading" | "error";

type ServiceEvent = {
  id: string;
  source_event_ref: string;
  sequence: number;
  event_type: string;
  direction: "inbound" | "outbound" | "system";
  locale: string;
  summary: string;
  body_sha256: string | null;
  evidence_id: string;
  effective_at: string;
  approval_id: string | null;
  command_id: string | null;
  receipt_id: string | null;
};

type ServiceCase = {
  case_id: string;
  external_case_ref: string;
  channel: string;
  order_external_id: string;
  product: { id: string; sku: string };
  locale: string;
  classification: string;
  priority: string;
  stage: Stage;
  opened_at: string;
  latest_effective_at: string;
  timeline: ServiceEvent[];
  event_count: number;
  return_authority: { status: string };
  dispute: { status: string };
  rma: { status: string };
  execution_authority: {
    status: string;
    approval_id: string | null;
    command_id: string | null;
    receipt_id: string | null;
    readback_evidence_ids: string[];
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
  filters: {
    query: string | null;
    stage: Stage | null;
    channel: string | null;
    priority: string | null;
  };
  counts: Record<string, number>;
  pagination: { page_size: number; next_cursor: string | null };
  cases: ServiceCase[];
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
  privacy_envelope: {
    raw_message_body_exposed: false;
    customer_name_exposed: false;
    customer_address_exposed: false;
    customer_phone_exposed: false;
    customer_email_exposed: false;
    platform_handle_exposed: false;
    pii_allowed_in_artifact: false;
    pii_allowed_in_cursor: false;
  };
  agent_artifact: {
    artifact_sha256: string;
    authority: string;
    raw_pii_read_allowed: false;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    mark_sent_allowed: false;
    refund_allowed: false;
    dispute_allowed: false;
    customer_contact_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    read_only_projection: true;
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    case_created: false;
    event_created: false;
    message_marked_sent: false;
    refund_created: false;
    dispute_created: false;
    rma_created: false;
    approval_created: false;
    permit_created: false;
    message_adapter_enabled: false;
    external_write_allowed: false;
    private_erp_interface_allowed: false;
  };
  snapshot_sha256: string;
};

const stages: Stage[] = [
  "opened",
  "triaged",
  "reply_drafted",
  "reply_approval_pending",
  "reply_permit_pending",
  "reply_readback_pending",
  "awaiting_customer",
  "return_in_progress",
  "dispute_in_progress",
  "resolved",
  "closed",
  "blocked",
];

const labels: Record<string, string> = {
  ready: "权威可用",
  partial: "部分可用",
  blocked: "失败关闭",
  no_data: "真实 no_data",
  loading: "读取中",
  error: "读取失败",
  opened: "新 Case",
  triaged: "已分诊",
  reply_drafted: "回复草稿",
  reply_approval_pending: "待独立审批",
  reply_permit_pending: "待一次性 Permit",
  reply_readback_pending: "待发送回读",
  awaiting_customer: "等待客户",
  return_in_progress: "退货处理中",
  dispute_in_progress: "争议处理中",
  resolved: "已解决",
  closed: "已关闭",
};

function label(value: string) {
  return labels[value] ?? value;
}

function short(value: string | null | undefined) {
  return value ? `${value.slice(0, 10)}…${value.slice(-7)}` : "no_data";
}

export function CustomerServiceConsole() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("");
  const [priority, setPriority] = useState("");
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
    if (priority) params.set("priority", priority);
    if (cursor) params.set("cursor", cursor);
    try {
      const response = await fetchJson<Workspace>(
        `/backend/v1/customer-service/workspace?${params.toString()}`,
        { cache: "no-store" },
      );
      const value = await response.json();
      if (!response.ok) {
        throw new Error(`Customer Service API ${response.status}`);
      }
      setWorkspace(value);
      setViewState(value.status);
      setSelected((current) =>
        value.cases.some((item) => item.case_id === current)
          ? current
          : value.cases[0]?.case_id ?? null,
      );
    } catch (error) {
      setViewState("error");
      setMessage(
        error instanceof Error ? error.message : "客服权威工作台读取失败",
      );
    }
  }, [cursor, priority, query, stage]);

  useEffect(() => {
    void load();
  }, [load]);

  const detail = useMemo(
    () =>
      workspace?.cases.find((item) => item.case_id === selected) ?? null,
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
          <p className={styles.eyebrow}>Native service authority · redacted</p>
          <h1>客户服务证据控制台</h1>
          <p>
            Case、Event、Return 与发送权威在一个 exact-scope
            投影中对账。正文和客户身份只留在受治理 Evidence Blob。
          </p>
        </div>
        <div className={styles.heroBadges}>
          <span data-state={viewState}>{label(viewState)}</span>
          <span><ShieldCheck size={15} /> External write false</span>
          <span><LockKeyhole size={15} /> PII projection false</span>
        </div>
      </header>

      <nav className={styles.links} aria-label="相邻原生工作台">
        <Link href="/oms">OMS</Link>
        <Link href="/returns">Returns</Link>
        <Link href="/delivery-exceptions">Delivery Exceptions</Link>
        <Link href="/warehouse-fulfillment">Warehouse Fulfillment</Link>
        <Link href="/evidenceops">EvidenceOps</Link>
        <Link href="/agent-control">Agent Control</Link>
      </nav>

      <form className={styles.filters} onSubmit={submit}>
        <label>
          Case / Order / SKU
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="服务端筛选，不搜索正文"
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
              <option key={item} value={item}>{label(item)}</option>
            ))}
          </select>
        </label>
        <label>
          优先级
          <select
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
          >
            <option value="">全部优先级</option>
            {["low", "normal", "high", "urgent"].map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <button type="submit"><RefreshCw size={16} /> 刷新权威</button>
      </form>

      {viewState === "loading" && (
        <section className={styles.stateCard}>
          <RefreshCw className={styles.spin} />
          正在读取脱敏 exact-scope Case/Event…
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
            <article><TicketCheck /><span>可验证 Case</span><strong>{workspace.counts.total_cases}</strong></article>
            <article><MessageSquareText /><span>不可变 Event</span><strong>{workspace.counts.total_events}</strong></article>
            <article><Scale /><span>开放争议</span><strong>{workspace.counts.open_disputes}</strong></article>
            <article><UserRoundCheck /><span>验证发送</span><strong>{workspace.counts.verified_sends}</strong></article>
          </section>

          <section className={styles.privacy}>
            <LockKeyhole />
            <div>
              <h2>正文不进入工作台</h2>
              <p>
                列表、详情、Artifact、游标和 Graph 只含非敏感摘要、正文哈希与
                Evidence 引用。Agent 不获得原始姓名、地址、电话、邮箱或平台账号。
              </p>
            </div>
            <code>raw_message_body_exposed=false</code>
          </section>

          {workspace.cases.length === 0 ? (
            <section className={styles.empty}>
              <MessageSquareText />
              <h2>没有可验证客服 Case</h2>
              <p>
                当前是 {label(workspace.status)}。页面没有生成合成客户、消息、
                争议、RMA、Approval 或 Permit。
              </p>
              <ul>
                {workspace.source_gaps.map((gap) => <li key={gap}>{gap}</li>)}
              </ul>
            </section>
          ) : (
            <section className={styles.workspace}>
              <div className={styles.list}>
                {workspace.cases.map((item) => (
                  <button
                    key={item.case_id}
                    data-active={selected === item.case_id}
                    onClick={() => setSelected(item.case_id)}
                  >
                    <span>{label(item.stage)}</span>
                    <strong>{item.external_case_ref}</strong>
                    <small>{item.product.sku} · {item.priority} · {item.channel}</small>
                  </button>
                ))}
              </div>

              {detail && (
                <article className={styles.detail}>
                  <header>
                    <div><p>Customer Service Case</p><h2>{detail.external_case_ref}</h2></div>
                    <span>{label(detail.stage)}</span>
                  </header>
                  <div className={styles.detailGrid}>
                    <div><Fingerprint /><small>Order / Product</small><strong>{detail.order_external_id}<br />{detail.product.id} / {detail.product.sku}</strong></div>
                    <div><Languages /><small>Locale / class</small><strong>{detail.locale}<br />{detail.classification}</strong></div>
                    <div><Clock3 /><small>Owner / SLA</small><strong>{detail.owner}<br />{detail.sla}</strong></div>
                    <div><ShieldCheck /><small>Execution authority</small><strong>{detail.execution_authority.status}<br />Receipt {short(detail.execution_authority.receipt_id)}</strong></div>
                  </div>

                  <h3>脱敏事件时间线</h3>
                  <ol className={styles.timeline}>
                    {detail.timeline.map((item) => (
                      <li key={item.id}>
                        <span>{String(item.sequence).padStart(2, "0")}</span>
                        <div>
                          <strong>{label(item.event_type)} · {item.direction}</strong>
                          <p>{item.summary}</p>
                          <code>
                            Body {short(item.body_sha256)} · Evidence {short(item.evidence_id)}
                          </code>
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
              Agent 仅能产出脱敏草稿建议和内部任务；raw PII、self approval、
              Permit、mark sent、refund、dispute、customer contact 与 external
              write 全部为 false。
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
