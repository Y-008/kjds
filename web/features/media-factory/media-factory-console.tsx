"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./media-factory.module.css";

type Status = "ready" | "partial" | "blocked" | "no_data";
type Stage =
  | "brief"
  | "source_rights_ready"
  | "queued"
  | "executing"
  | "generated"
  | "qa_pending"
  | "qa_failed"
  | "delivery_ready"
  | "blocked";

type Blocker = {
  code: string;
  severity: string;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type Execution = {
  id: string;
  status: string;
  attempt: number;
  template_id: string;
  input_sha256: string;
  queued_at: string;
  latency_ms: number | null;
  cost: { amount: string; currency: string };
  error_code: string | null;
  event_count: number;
};

type Asset = {
  id: string;
  product_id: string | null;
  content_type: string;
  locale: string | null;
  channel: string | null;
  status: string;
  stage: Stage;
  role: string | null;
  aspect_ratios: string[];
  template: {
    id: string;
    version: string;
    status: string;
    executor: string;
    fixed_workflow: boolean;
  } | null;
  qa_results: Array<Record<string, unknown>>;
  latest_execution: Execution | null;
  execution_timeline: Execution[];
  delivery_manifest: {
    manifest_id: string;
    manifest_sha256: string;
    listing_eligible: boolean;
    artifact_evidence_ids: string[];
  } | null;
  readiness: {
    source_rights_ready: boolean;
    template_admitted: boolean;
    execution_retry_allowed: boolean;
    qa_passed: boolean;
    delivery_manifest_ready: boolean;
  };
  evidence_ids: string[];
  source_gaps: string[];
  blockers: Blocker[];
  owner: string;
  sla: string;
  next: string;
};

type ProductGroup = {
  product: {
    id: string;
    sku: string;
    name: string;
    status: string;
  };
  stage: Stage;
  assets: Asset[];
  coverage: {
    image: {
      required_roles: string[];
      observed_roles: string[];
      delivery_ready_roles: string[];
      missing_roles: string[];
    };
    video: {
      present: boolean;
      required_ratios: string[];
      observed_ratios: string[];
      delivery_ready_ratios: string[];
      missing_ratios: string[];
    };
  };
  readiness: {
    source_rights_ready: boolean;
    all_qa_passed: boolean;
    delivery_manifest_ready: boolean;
    listing_media_ready: boolean;
  };
  source_gaps: string[];
  blockers: Blocker[];
  owner: string;
  sla: string;
  next: string;
  snapshot_sha256: string;
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
    stage: Stage | null;
  };
  counts: Record<string, number>;
  product_groups: ProductGroup[];
  source_gaps: string[];
  blockers: Blocker[];
  upstream_authority: {
    product_content_snapshot_sha256?: string;
    media_source_snapshot_sha256?: string;
  };
  agent_artifact: {
    contract_id: string;
    artifact_sha256: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    asset_or_job_creation_allowed: false;
    qa_or_manifest_creation_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    fixed_templates_only: true;
    external_video_provider_enabled: false;
    asset_created: false;
    job_created: false;
    qa_decided: false;
    manifest_created: false;
    listing_created: false;
    approval_created: false;
    permit_created: false;
    external_write_allowed: false;
  };
  snapshot_sha256: string;
};

const stages: Stage[] = [
  "brief",
  "source_rights_ready",
  "queued",
  "executing",
  "generated",
  "qa_pending",
  "qa_failed",
  "delivery_ready",
  "blocked",
];

const shortHash = (value: string | undefined) =>
  value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "no_data";

export function MediaFactoryConsole() {
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
          `/backend/v1/media-factory/workspace?${params.toString()}`,
        );
        const body = await response.json();
        if (!response.ok) {
          throw new Error(`Media factory API ${response.status}`);
        }
        setData(body);
      } catch (reason) {
        setError(
          reason instanceof Error ? reason.message : "内容媒体工厂加载失败",
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
        <strong>KJDS · CONTENT MEDIA FACTORY</strong>
        <Link href="/listings">Listing →</Link>
      </nav>

      <header>
        <p>EXACT SCOPE · FIXED WORKFLOW · APPEND-ONLY TIMELINE</p>
        <h1>
          生成内容不等于可刊登，
          <em>每个产物都要穿过证据链。</em>
        </h1>
        <span>
          ContentAsset、权利、模板、执行事件、QA 与 Delivery Manifest
          由服务端统一投影；页面不重算阶段、成本、资格或覆盖。
        </span>
      </header>

      <section className={styles.boundary}>
        <span>Asset / Job create · false / false</span>
        <span>QA decide · false</span>
        <span>Manifest create · false</span>
        <span>Approval / Permit · false / false</span>
        <span>External provider / platform write · false / false</span>
      </section>

      <section className={styles.flow} aria-label="媒体证据阶梯">
        <article><b>01</b><span>Brief</span><small>商品事实与媒体角色</small></article>
        <i>→</i>
        <article><b>02</b><span>Rights</span><small>来源与权利 Evidence</small></article>
        <i>→</i>
        <article><b>03</b><span>Execute</span><small>固定模板 + PG lease</small></article>
        <i>→</i>
        <article><b>04</b><span>Timeline</span><small>append-only events</small></article>
        <i>→</i>
        <article><b>05</b><span>QA</span><small>独立逐项复核</small></article>
        <i>→</i>
        <article><b>06</b><span>Manifest</span><small>Listing 可引用交付物</small></article>
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
          搜索 SKU、商品、Asset 或模板
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
          Server stage
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
          正在读取 exact-scope Product、ContentAsset、Execution/Event 与 Manifest…
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
            <article><strong>{data.counts.assets}</strong><span>ContentAssets</span></article>
            <article><strong>{data.counts.executions}</strong><span>执行账</span></article>
            <article><strong>{data.counts.failed_executions}</strong><span>失败 / 阻断执行</span></article>
            <article><strong>{data.counts.manifests}</strong><span>Delivery Manifests</span></article>
            <article><strong>{data.counts.delivery_ready}</strong><span>完整媒体组 ready</span></article>
          </section>

          <section className={styles.scopeLine}>
            <span>Entity · <b>{data.scope.entity_ref ?? "no_data"}</b></span>
            <span>Store · <b>{data.scope.store_ref}</b></span>
            <span>As of · <b>{data.as_of}</b></span>
            <span>Content · <code>{shortHash(data.upstream_authority.product_content_snapshot_sha256)}</code></span>
            <span>Media ledger · <code>{shortHash(data.upstream_authority.media_source_snapshot_sha256)}</code></span>
          </section>

          {data.status === "no_data" && data.product_groups.length === 0 && (
            <section className={styles.notice} data-state="no_data">
              <h2>真实 no_data</h2>
              <p>
                当前 exact scope 没有可验证 Product / ContentAsset。0 不代表图片、
                视频、QA 或 Listing 媒体覆盖已完成，也不会生成演示素材。
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
              <h2>
                {data.status === "blocked"
                  ? "媒体权威链已失败关闭"
                  : "媒体工厂尚未形成可刊登交付物"}
              </h2>
              <p>
                最新坏 Evidence、未来状态、input/template/hash 漂移、事件断链或
                Manifest 不一致不会回退到旧记录；受影响 payload 被隐藏。
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
            {data.product_groups.map((group) => (
              <details key={group.product.id} className={styles.card}>
                <summary>
                  <span>
                    <small>{group.product.status} · {group.product.id}</small>
                    <b>{group.product.sku}</b>
                    <em>{group.product.name}</em>
                  </span>
                  <i data-stage={group.stage}>{group.stage}</i>
                </summary>
                <div className={styles.detail}>
                  <section className={styles.coverage}>
                    <article>
                      <span>图片角色覆盖</span>
                      <b>{group.coverage.image.delivery_ready_roles.length} / {group.coverage.image.required_roles.length}</b>
                      <small>
                        缺口 · {group.coverage.image.missing_roles.join(" / ") || "none"}
                      </small>
                    </article>
                    <article>
                      <span>视频比例覆盖</span>
                      <b>
                        {group.coverage.video.present
                          ? `${group.coverage.video.delivery_ready_ratios.length} / ${group.coverage.video.required_ratios.length}`
                          : "not present"}
                      </b>
                      <small>
                        缺口 · {group.coverage.video.missing_ratios.join(" / ") || "none"}
                      </small>
                    </article>
                    <article>
                      <span>Source rights</span>
                      <b>{String(group.readiness.source_rights_ready)}</b>
                      <small>exact-scope Evidence</small>
                    </article>
                    <article>
                      <span>Listing media ready</span>
                      <b>{String(group.readiness.listing_media_ready)}</b>
                      <small>由服务端决定</small>
                    </article>
                  </section>

                  <section className={styles.assets}>
                    {group.assets.length === 0 && (
                      <p>尚无真实 ContentAsset；不会自动创建媒体 Job。</p>
                    )}
                    {group.assets.map((asset) => (
                      <article key={asset.id} data-stage={asset.stage}>
                        <header>
                          <span>
                            <small>{asset.content_type} · {asset.role ?? (asset.aspect_ratios.join(" / ") || "role missing")}</small>
                            <b>{asset.id}</b>
                          </span>
                          <i>{asset.stage}</i>
                        </header>
                        <div className={styles.assetFacts}>
                          <p>Template · <b>{asset.template?.id ?? "withheld"}</b></p>
                          <p>Executor · {asset.template?.executor ?? "withheld"}</p>
                          <p>Evidence · {asset.evidence_ids.length}</p>
                          <p>QA checks · {asset.qa_results.length}</p>
                          <p>Attempt · {asset.latest_execution?.attempt ?? 0}</p>
                          <p>Events · {asset.latest_execution?.event_count ?? 0}</p>
                          <p>
                            Cost · {asset.latest_execution
                              ? `${asset.latest_execution.cost.amount} ${asset.latest_execution.cost.currency}`
                              : "no execution"}
                          </p>
                          <p>
                            Manifest · {asset.delivery_manifest
                              ? shortHash(asset.delivery_manifest.manifest_sha256)
                              : "not created"}
                          </p>
                        </div>
                        <div className={styles.next}>
                          <p>Owner · <b>{asset.owner}</b></p>
                          <p>SLA · {asset.sla}</p>
                          <p>Next · {asset.next}</p>
                        </div>
                        {asset.source_gaps.length > 0 && (
                          <div className={styles.gaps}>
                            {asset.source_gaps.map((gap) => <code key={gap}>{gap}</code>)}
                          </div>
                        )}
                      </article>
                    ))}
                  </section>

                  <section className={styles.next}>
                    <p>Owner · <b>{group.owner}</b></p>
                    <p>SLA · {group.sla}</p>
                    <p>Next · {group.next}</p>
                    <Link href="/listings">进入 Listing 权威链 →</Link>
                  </section>
                  <code className={styles.hash}>{group.snapshot_sha256}</code>
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
                服务端 opaque cursor · 当前 {data.counts.page_product_groups}/
                {data.counts.total_product_groups}
              </span>
            </section>
          )}

          <footer>
            <span>
              {data.contract_id} · {data.agent_artifact.contract_id}
            </span>
            <span>
              Agent 只能建议或建立内部任务；不能创建 Asset/Job、不能决定 QA、
              不能创建 Manifest、不能自批、不能发 Permit 或外部写。
            </span>
            <Link href="/commerce-os">返回 Commerce OS →</Link>
            <code>{data.snapshot_sha256}</code>
          </footer>
        </>
      )}
    </main>
  );
}
