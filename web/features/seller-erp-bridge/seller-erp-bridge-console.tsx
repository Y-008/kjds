"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./seller-erp-bridge.module.css";

type Status = "ready" | "partial" | "blocked" | "no_data";
type DiffState =
  | "matched"
  | "source_only"
  | "canonical_only"
  | "conflict"
  | "blocked";
type DiffItem = {
  domain: "catalog" | "orders" | "inventory";
  canonical_key: string;
  state: DiffState;
  source: Record<string, unknown> | null;
  canonical: Record<string, unknown> | null;
  field_diffs: {
    field: string;
    source_value: unknown;
    canonical_value: unknown;
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
  source: {
    evidence_id: string | null;
    sha256: string | null;
    provider: string | null;
    source_kind: string | null;
    domain: string | null;
    schema_version: string | null;
    exported_at: string | null;
    authorization_mode: string | null;
    row_count: number;
  };
  authority: {
    source_evidence_id: string | null;
    source_evidence_sha256: string | null;
    review_evidence_id: string | null;
    binding_evidence_id: string | null;
    revocation_evidence_id: string | null;
    three_party_independence: boolean;
  };
  query: {
    page_size: number;
    cursor: string | null;
    next_cursor: string | null;
    search: string | null;
    state: string | null;
  };
  counts: Record<string, number>;
  diff_items: DiffItem[];
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
    contract_id?: string;
    status?: string;
    snapshot_sha256?: string;
  };
  control_envelope: {
    read_only: true;
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    formal_fact_promoted: false;
    product_created: false;
    listing_created: false;
    order_created: false;
    inventory_created: false;
    approval_created: false;
    permit_created: false;
    external_write_allowed: false;
    private_interface_used: false;
  };
  agent_artifact: {
    contract_id: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    formal_fact_promotion_allowed: false;
    external_write_allowed: false;
  };
  snapshot_sha256: string;
};

const stateLabels: Record<DiffState, string> = {
  matched: "一致",
  source_only: "仅外部快照",
  canonical_only: "仅 KJDS",
  conflict: "字段冲突",
  blocked: "阻断",
};

function printable(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function SellerErpBridgeConsole() {
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sourceEvidenceId, setSourceEvidenceId] = useState("");
  const [appliedSourceId, setAppliedSourceId] = useState("");
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);

  const load = useCallback(
    async (requestedCursor: string | null = cursor) => {
      setLoading(true);
      setError("");
      const params = new URLSearchParams({
        store_ref: "ozon-primary",
        page_size: "100",
      });
      if (appliedSourceId) params.set("source_evidence_id", appliedSourceId);
      if (query.trim()) params.set("query", query.trim());
      if (state) params.set("state", state);
      if (requestedCursor) params.set("cursor", requestedCursor);
      try {
        const response = await fetchJson<Workspace>(
          `/backend/v1/seller-erp-bridge/reconcile?${params.toString()}`,
        );
        const body = await response.json();
        if (!response.ok) throw new Error(`Seller ERP Bridge API ${response.status}`);
        setData(body);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Seller ERP Bridge 加载失败");
      } finally {
        setLoading(false);
      }
    },
    [appliedSourceId, cursor, query, state],
  );

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className={styles.page}>
      <nav>
        <Link href="/commerce-os">← Commerce OS</Link>
        <strong>KJDS · AUTHORIZED SELLER ERP BRIDGE</strong>
        <Link href="/pim">PIM →</Link>
      </nav>

      <header>
        <p>FORMAL EXPORT · THREE-PARTY AUTHORITY · CANONICAL DIFF</p>
        <h1>
          接入外部 ERP，
          <em>但经营真相留在 KJDS。</em>
        </h1>
        <span>
          店小秘等仅作为正式导出或授权 Adapter 来源；原始 Evidence、独立复核、Compliance
          binding、撤销与每次重验缺一不可。
        </span>
      </header>

      <section className={styles.boundary}>
        <span>Private endpoint · false</span>
        <span>Cookie / Token · never stored</span>
        <span>Fact promotion · false</span>
        <span>Approval / Permit · false / false</span>
        <span>External write · false</span>
      </section>

      <section className={styles.authorityFlow} aria-label="三方权威链">
        <article>
          <b>01 · SOURCE</b>
          <span>Operator 固化正式导出与列映射</span>
        </article>
        <i>→</i>
        <article>
          <b>02 · REVIEW</b>
          <span>独立 Reviewer 核验来源、授权与 schema</span>
        </article>
        <i>→</i>
        <article>
          <b>03 · BIND</b>
          <span>第三位 Compliance 记录 exact-scope binding</span>
        </article>
        <i>→</i>
        <article>
          <b>04 · RECONCILE</b>
          <span>只读比较 PIM / OMS / Inventory 真源</span>
        </article>
      </section>

      <form
        className={styles.filters}
        onSubmit={(event) => {
          event.preventDefault();
          setCursor(null);
          setAppliedSourceId(sourceEvidenceId.trim());
        }}
      >
        <label>
          Source Evidence ID
          <input
            value={sourceEvidenceId}
            onChange={(event) => setSourceEvidenceId(event.target.value)}
            placeholder="evd_…；留空显示真实 no_data"
          />
        </label>
        <label>
          搜索
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(null);
            }}
            placeholder="SKU、offer、订单或仓库"
          />
        </label>
        <label>
          Diff state
          <select
            value={state}
            onChange={(event) => {
              setState(event.target.value);
              setCursor(null);
            }}
          >
            <option value="">全部状态</option>
            <option value="matched">matched</option>
            <option value="source_only">source only</option>
            <option value="canonical_only">canonical only</option>
            <option value="conflict">conflict</option>
            <option value="blocked">blocked</option>
          </select>
        </label>
        <button type="submit">重验并对账</button>
      </form>

      {loading && (
        <section role="status" className={styles.notice}>
          正在重验 immutable Evidence、最新 review/binding/revocation 与 Canonical authority…
        </section>
      )}
      {error && (
        <section role="alert" className={styles.error}>
          <p>{error}</p>
          <button type="button" onClick={() => void load()}>
            重试
          </button>
        </section>
      )}

      {!loading && !error && data && (
        <>
          <section className={styles.metrics}>
            <article>
              <strong>{data.counts.matched}</strong>
              <span>Matched</span>
            </article>
            <article>
              <strong>{data.counts.conflict}</strong>
              <span>Conflict</span>
            </article>
            <article>
              <strong>{data.counts.source_only}</strong>
              <span>Source only</span>
            </article>
            <article>
              <strong>{data.counts.canonical_only}</strong>
              <span>Canonical only</span>
            </article>
            <article>
              <strong>{data.source.row_count}</strong>
              <span>Immutable source rows</span>
            </article>
          </section>

          <section className={styles.authorityState} data-ready={data.authority.three_party_independence}>
            <div>
              <span>Scope</span>
              <b>{data.scope.entity_ref ?? "no_data"} / {data.scope.store_ref}</b>
            </div>
            <div>
              <span>Provider / domain</span>
              <b>{data.source.provider ?? "no_data"} / {data.source.domain ?? "no_data"}</b>
            </div>
            <div>
              <span>Independent review</span>
              <b>{data.authority.review_evidence_id ?? "missing"}</b>
            </div>
            <div>
              <span>Compliance binding</span>
              <b>{data.authority.binding_evidence_id ?? "missing"}</b>
            </div>
          </section>

          {data.status === "no_data" && data.diff_items.length === 0 && (
            <section className={styles.notice} data-state="no_data">
              <h2>真实 no_data</h2>
              <p>
                尚未选择通过三方权威链的正式导出；0 行不代表店铺、订单或库存已经覆盖。
              </p>
              {data.source_gaps.map((gap) => <code key={gap}>{gap}</code>)}
            </section>
          )}

          {(data.status === "blocked" || data.status === "partial") && (
            <section
              className={data.status === "blocked" ? styles.error : styles.notice}
              data-state={data.status}
            >
              <h2>{data.status === "blocked" ? "对账已失败关闭" : "差异需要独立复核"}</h2>
              <p>
                最新拒绝、撤销、坏 Evidence、scope/hash/schema 漂移不会回退旧记录或泄露被阻断业务行。
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

          <section className={styles.diffGrid}>
            {data.diff_items.map((item) => (
              <details key={`${item.state}:${item.canonical_key}`} className={styles.diffCard}>
                <summary>
                  <span>
                    <small>{item.domain}</small>
                    <b>{item.canonical_key}</b>
                  </span>
                  <i data-state={item.state}>{stateLabels[item.state]}</i>
                </summary>
                <div className={styles.diffBody}>
                  {item.field_diffs.length > 0 ? (
                    <div className={styles.fieldDiffs}>
                      {item.field_diffs.map((field) => (
                        <article key={field.field}>
                          <b>{field.field}</b>
                          <span>外部 · {printable(field.source_value)}</span>
                          <span>KJDS · {printable(field.canonical_value)}</span>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p>
                      {item.state === "matched"
                        ? "版本化字段完全一致。"
                        : "一侧缺失；不得据此自动创建 Canonical Fact。"}
                    </p>
                  )}
                  <p>Owner · {item.owner}　SLA · {item.sla}</p>
                  <p>Next · {item.next}</p>
                  <Link href={item.next_workspace}>打开 Canonical workspace →</Link>
                  <code>{item.item_sha256}</code>
                </div>
              </details>
            ))}
          </section>

          {data.query.next_cursor && (
            <section className={styles.pagination}>
              <button
                type="button"
                onClick={() => setCursor(data.query.next_cursor)}
              >
                下一页
              </button>
              <span>
                服务端 opaque cursor · 当前 {data.counts.page_diff_items}/
                {data.counts.total_diff_items}
              </span>
            </section>
          )}

          <footer>
            <span>{data.contract_id} · {data.agent_artifact.contract_id}</span>
            <span>
              Agent 只能建议或建立内部任务；不能晋升 Fact、自批、发 Permit 或写外部平台。
            </span>
            <code>{data.snapshot_sha256}</code>
          </footer>
        </>
      )}
    </main>
  );
}
