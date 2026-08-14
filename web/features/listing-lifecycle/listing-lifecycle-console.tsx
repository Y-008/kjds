"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./listing-lifecycle.module.css";

type Status = "ready" | "partial" | "blocked" | "no_data";
type DiffState = "same" | "changed" | "source_missing" | "desired_missing";
type FieldDiff = {
  field: string;
  state: DiffState;
  observed_value: unknown;
  desired_value: unknown;
};
type LifecycleItem = {
  identity: {
    product_id: string;
    sku: string;
    product_name: string;
    offer_id: string;
    draft_id: string;
    target_platform: string;
  };
  authority: {
    listing_snapshot_sha256: string;
    frozen_product_snapshot_sha256: string;
    current_product_snapshot_sha256: string | null;
    approval_plan_sha256: string;
    evidence_ids: string[];
  };
  observed_platform_listing: {
    marketplace_sku: string | null;
    listing_status: unknown;
    source_evidence_id: string | null;
  } | null;
  desired_listing_draft: Record<string, unknown> | null;
  field_diffs: FieldDiff[];
  review: {
    status: string;
    review_id: string | null;
    reviewed_by: string | null;
  };
  approval: {
    status: string;
    approval_id: string | null;
    decided_by: string | null;
    independent: boolean;
  };
  execution_plan: {
    plan_id: string;
    plan_sha256: string | null;
    approval_status: string;
    dry_run: Record<string, unknown> | null;
    permit_created: false;
    external_execution_ready: false;
  } | null;
  readback: {
    status: "not_available";
    receipt_id: null;
    matches_approved_snapshot: null;
  };
  lifecycle: {
    stage: string;
    owner: string;
    next: string;
    next_workspace: string;
    external_write_allowed: false;
  };
  source_gaps: string[];
  blockers: {
    code: string;
    severity: string;
    owner: string;
    sla: string;
    next: string;
    next_workspace: string;
  }[];
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
  item_sha256: string;
};
type Workspace = {
  contract_id: string;
  status: Status;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
  };
  query: {
    page_size: number;
    cursor: string | null;
    next_cursor: string | null;
    search: string | null;
    stage: string | null;
  };
  counts: Record<string, number>;
  items: LifecycleItem[];
  source_gaps: string[];
  blockers: {
    code: string;
    severity: string;
    owner: string;
    sla: string;
    next: string;
    next_workspace: string;
  }[];
  upstream_authority: {
    pim_snapshot_sha256?: string;
  };
  control_envelope: {
    read_only: true;
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    draft_created: false;
    review_created: false;
    approval_created: false;
    execution_plan_created: false;
    permit_created: false;
    platform_task_created: false;
    readback_created: false;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    external_write_allowed: false;
  };
  agent_artifact: {
    contract_id: string;
    artifact_sha256: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    publish_allowed: false;
    external_write_allowed: false;
  };
  snapshot_sha256: string;
};

const stages = [
  "draft_pending_review",
  "review_rejected",
  "approval_pending",
  "approval_rejected",
  "approved",
  "plan_created",
  "plan_approval_pending",
  "dry_run_failed",
  "dry_run_verified_external_gate",
  "blocked",
];

const diffLabels: Record<DiffState, string> = {
  same: "一致",
  changed: "变更",
  source_missing: "平台源缺失",
  desired_missing: "目标值缺失",
};

function valueLabel(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function ListingLifecycleConsole() {
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);

  const load = useCallback(
    async (requestedCursor: string | null = cursor) => {
      setLoading(true);
      setError("");
      const params = new URLSearchParams({
        store_ref: "ozon-primary",
        page_size: "50",
      });
      if (query.trim()) params.set("query", query.trim());
      if (stage) params.set("stage", stage);
      if (requestedCursor) params.set("cursor", requestedCursor);
      try {
        const response = await fetchJson<Workspace>(
          `/backend/v1/listing-lifecycle/workspace?${params.toString()}`,
        );
        const body = await response.json();
        if (!response.ok) {
          throw new Error(`Listing lifecycle API ${response.status}`);
        }
        setData(body);
      } catch (reason) {
        setError(
          reason instanceof Error ? reason.message : "Listing 生命周期加载失败",
        );
      } finally {
        setLoading(false);
      }
    },
    [cursor, query, stage],
  );

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className={styles.page}>
      <nav>
        <Link href="/pim">← PIM</Link>
        <strong>KJDS · LISTING LIFECYCLE</strong>
        <Link href="/commerce-os">Commerce OS →</Link>
      </nav>

      <header>
        <p>EXACT SCOPE · IMMUTABLE SNAPSHOT · EXTERNAL WRITE FALSE</p>
        <h1>
          Listing 变更不是一次点击，
          <em>而是一条可回放的权威链。</em>
        </h1>
        <span>
          OBSERVED ≠ DESIRED ≠ APPROVED ≠ READBACK。服务端冻结商品、草稿、俄语母语复核、
          独立审批与 Dry Run；页面只呈现，不重算阶段或差异。
        </span>
      </header>

      <section className={styles.boundary}>
        <span>Draft create · false</span>
        <span>Review / Approval · false / false</span>
        <span>Execution Plan · false</span>
        <span>Permit / Publish · false / false</span>
        <span>External write · false</span>
      </section>

      <section className={styles.lifecycle} aria-label="Listing 权威阶梯">
        <article><b>01</b><span>Observed</span><small>平台 Evidence</small></article>
        <i>→</i>
        <article><b>02</b><span>Desired</span><small>冻结 Listing Draft</small></article>
        <i>→</i>
        <article><b>03</b><span>Reviewed</span><small>独立俄语母语复核</small></article>
        <i>→</i>
        <article><b>04</b><span>Approved</span><small>独立业务决定</small></article>
        <i>→</i>
        <article><b>05</b><span>Dry Run</span><small>确定性前置验证</small></article>
        <i>→</i>
        <article><b>06</b><span>Readback</span><small>当前仍未创建</small></article>
      </section>

      <form
        className={styles.filters}
        onSubmit={(event) => {
          event.preventDefault();
          setCursor(null);
          void load(null);
        }}
      >
        <label>
          搜索 SKU、商品、offer 或 draft
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(null);
            }}
            placeholder="exact identity"
          />
        </label>
        <label>
          Lifecycle stage
          <select
            value={stage}
            onChange={(event) => {
              setStage(event.target.value);
              setCursor(null);
            }}
          >
            <option value="">全部阶段</option>
            {stages.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <button type="submit">重验快照</button>
      </form>

      {loading && (
        <section role="status" className={styles.notice}>
          正在读取 exact-scope PIM、Listing Draft、Review、Approval 与 Execution Plan…
        </section>
      )}
      {error && (
        <section role="alert" className={styles.error}>
          <p>{error}</p>
          <button type="button" onClick={() => void load()}>重试</button>
        </section>
      )}

      {!loading && !error && data && (
        <>
          <section className={styles.metrics}>
            <article><strong>{data.counts.total}</strong><span>当前 Listing Draft</span></article>
            <article><strong>{data.counts.changed}</strong><span>字段有变更</span></article>
            <article><strong>{data.counts.source_missing}</strong><span>平台源缺失</span></article>
            <article><strong>{data.counts.approval_pending}</strong><span>待独立审批</span></article>
            <article><strong>{data.counts.dry_run_verified}</strong><span>Dry Run 已验证</span></article>
          </section>

          <section className={styles.scopeLine}>
            <span>Entity · <b>{data.scope.entity_ref ?? "no_data"}</b></span>
            <span>Store · <b>{data.scope.store_ref}</b></span>
            <span>As of · <b>{data.as_of}</b></span>
            <span>PIM authority · <code>{data.upstream_authority.pim_snapshot_sha256 ?? "no_data"}</code></span>
          </section>

          {data.status === "no_data" && data.items.length === 0 && (
            <section className={styles.notice} data-state="no_data">
              <h2>真实 no_data</h2>
              <p>
                当前 exact scope 没有可验证的 Product / Listing Draft；0 不代表刊登已完成，
                也不会伪造平台覆盖、Readback 或外部发布。
              </p>
              <div className={styles.gaps}>
                {data.source_gaps.map((gap) => <code key={gap}>{gap}</code>)}
              </div>
            </section>
          )}

          {(data.status === "blocked" || data.status === "partial") && (
            <section
              className={data.status === "blocked" ? styles.error : styles.notice}
              data-state={data.status}
            >
              <h2>{data.status === "blocked" ? "Listing 权威链已失败关闭" : "Listing 生命周期尚未闭环"}</h2>
              <p>
                最新坏 Evidence、scope/hash/product/approval 漂移不会回退到旧记录；
                被阻断的业务 payload 不向客户端泄露。
              </p>
              <div className={styles.gaps}>
                {data.source_gaps.map((gap) => <code key={gap}>{gap}</code>)}
              </div>
              {data.blockers.map((blocker) => (
                <p key={`${blocker.code}:${blocker.owner}`}>
                  {blocker.severity} · {blocker.owner} · {blocker.next}
                </p>
              ))}
            </section>
          )}

          <section className={styles.list}>
            {data.items.map((item) => (
              <details key={item.identity.draft_id} className={styles.card}>
                <summary>
                  <span>
                    <small>{item.identity.target_platform} · {item.identity.offer_id}</small>
                    <b>{item.identity.sku || item.identity.product_id}</b>
                    <em>{item.identity.product_name || "未命名 Canonical Product"}</em>
                  </span>
                  <i data-stage={item.lifecycle.stage}>{item.lifecycle.stage}</i>
                </summary>

                <div className={styles.detail}>
                  <section className={styles.authorityGrid}>
                    <article>
                      <span>Review</span>
                      <b>{item.review.status}</b>
                      <small>{item.review.review_id ?? "not created"}</small>
                    </article>
                    <article>
                      <span>Listing Approval</span>
                      <b>{item.approval.status}</b>
                      <small>{item.approval.independent ? "independent" : "not independently decided"}</small>
                    </article>
                    <article>
                      <span>Execution Plan</span>
                      <b>{item.execution_plan?.approval_status ?? "not created"}</b>
                      <small>{item.execution_plan?.plan_id ?? "no plan"}</small>
                    </article>
                    <article>
                      <span>Readback</span>
                      <b>{item.readback.status}</b>
                      <small>receipt · not created</small>
                    </article>
                  </section>

                  <div className={styles.diffTable} role="table" aria-label="服务端 Listing 字段差异">
                    <div className={styles.diffHead} role="row">
                      <b>字段</b><b>状态</b><b>Observed</b><b>Desired</b>
                    </div>
                    {item.field_diffs.map((diff) => (
                      <div className={styles.diffRow} role="row" key={diff.field}>
                        <b>{diff.field}</b>
                        <i data-state={diff.state}>{diffLabels[diff.state]}</i>
                        <span>{valueLabel(diff.observed_value)}</span>
                        <span>{valueLabel(diff.desired_value)}</span>
                      </div>
                    ))}
                  </div>

                  <section className={styles.next}>
                    <p>Owner · <b>{item.owner}</b></p>
                    <p>SLA · {item.sla}</p>
                    <p>Next · {item.next}</p>
                    <Link href={item.next_workspace}>打开下一权威工作台 →</Link>
                  </section>

                  {item.source_gaps.length > 0 && (
                    <div className={styles.gaps}>
                      {item.source_gaps.map((gap) => <code key={gap}>{gap}</code>)}
                    </div>
                  )}
                  <code className={styles.hash}>{item.item_sha256}</code>
                </div>
              </details>
            ))}
          </section>

          {data.query.next_cursor && (
            <section className={styles.pagination}>
              <button type="button" onClick={() => setCursor(data.query.next_cursor)}>
                下一页
              </button>
              <span>服务端 opaque cursor · 当前 {data.counts.page}/{data.counts.total}</span>
            </section>
          )}

          <footer>
            <span>{data.contract_id} · {data.agent_artifact.contract_id}</span>
            <span>
              Agent 只能建议或建立内部任务；不能创建 Draft/Approval、不能自批、
              不能发 Permit、不能发布或写外部平台。
            </span>
            <Link href="/media-factory">进入内容媒体工厂 →</Link>
            <code>{data.snapshot_sha256}</code>
          </footer>
        </>
      )}
    </main>
  );
}
