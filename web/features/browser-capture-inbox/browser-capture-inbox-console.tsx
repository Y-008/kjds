"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./browser-capture-inbox.module.css";

type Envelope = {
  contract_version:
    | "kjds-browser-capture-envelope/1.0"
    | "kjds-browser-capture-envelope/1.1"
    | "kjds-browser-capture-envelope/1.2";
  source_profile: "browser_observation";
  marketplace: "1688" | "ozon";
  store_ref: string;
  source_url: string;
  observed_at: string;
  idempotency_key: string;
  page: {
    title: string;
    canonical_url: string | null;
    language: string | null;
    extractor_version:
      | "kjds-visible-dom/1.0"
      | "kjds-visible-dom/1.1"
      | "kjds-visible-dom/1.2";
    capture_mode: "active_tab_visible_dom";
    capture_kind?:
      | "product_detail_variant_matrix"
      | "search_result_candidates"
      | "store_catalog_candidates"
      | "generic_product";
    provider_id?: string | null;
    provider_version?: string | null;
    structured_data_source?: string | null;
    search_query?: string | null;
    capture_coverage?: Record<string, unknown>;
  };
  merchant?: {
    supplier_ref: string;
    company_name: string | null;
    login_id: string | null;
    public_signals: Record<string, unknown>;
  } | null;
  items: Array<{
    external_item_id: string;
    supplier_ref: string;
    title: string;
    variant_key: string;
    currency: string;
    displayed_price: string;
    price_scope: "unit_price" | "checkout_total";
    price_kind: string;
    min_order_quantity: number | null;
    availability: string;
    specifications: Record<string, string>;
    product_identity: Record<string, string>;
    comparison_dimensions?: Record<string, string>;
    comparison_key_sha256?: string | null;
    observed_quantity?: number | null;
    checkout_verified?: boolean;
    tax_included?: boolean | null;
    domestic_freight_included?: boolean | null;
    purchase_available?: boolean;
    confidence?: string;
    market_signals?: Record<string, unknown>;
    supply_signals?: Record<string, unknown>;
    media_rights_status: "unverified_external_reference";
  }>;
  confirmed: true;
};

type VariantSummary = {
  external_item_id: string;
  currency: string;
  variant_count: number;
  minimum_unit_price: string;
  maximum_unit_price: string;
  minimum_variants: Array<{
    sku_id: string | null;
    spec_id: string | null;
    variant_key: string;
    unit_price: string;
  }>;
  comparison_groups: Array<{
    status: "comparable" | "requires_dimension_alignment";
    comparison_dimensions: Record<string, string>;
    item_count: number;
    minimum_unit_price: string;
    maximum_unit_price: string;
  }>;
};

type ErpStaging = {
  contract_id: string;
  status: string;
  row_count: number;
  exact_variant_count: number;
  rows: Array<{
    staging_key: string;
    mapping_status: "exact_variant_staged" | "requires_detail_enrichment";
    marketplace: string;
    supplier_ref: string;
    supplier_public_profile: Envelope["merchant"];
    offer_id: string;
    sku_id: string | null;
    spec_id: string | null;
    variant_key: string;
    title: string;
    product_identity: Record<string, string>;
    displayed_price: string;
    price_scope: "unit_price" | "checkout_total";
    unit_price: string;
    currency: string;
    price_kind: string;
    price_contract: string;
    min_order_quantity: number | null;
    availability: string;
    specifications: Record<string, string>;
    comparison_dimensions: Record<string, string>;
    comparison_key_sha256: string | null;
    observed_quantity: number | null;
    checkout_verified: boolean;
    tax_included: boolean | null;
    domestic_freight_included: boolean | null;
    purchase_available: boolean;
    confidence: string;
    market_signals: Record<string, unknown>;
    supply_signals: Record<string, unknown>;
    experiment_readbacks: Record<string, unknown>;
    target_product_id: string | null;
    target_offer_id: string | null;
    media_rights_status: "unverified_external_reference";
    image_references: string[];
    source_gaps: string[];
    source_observed_at: string;
    source_capture: {
      capture_kind: string;
      provider_id: string | null;
      provider_version: string | null;
      structured_data_source: string | null;
      capture_coverage: Record<string, unknown>;
    };
    source_url: string;
    item_sha256: string;
    source_observation: Envelope["items"][number];
  }>;
  formal_product_write: false;
  supplier_offer_write: false;
  external_write: false;
};

type SourcingComparison = {
  contract_id: "kjds-sourcing-comparison/1.0";
  status: "comparable" | "requires_more_exact_offers" | "no_data";
  reference_quantity: number;
  latest_exact_offer_count: number;
  candidate_capture_count: number;
  candidate_row_count: number;
  excluded_capture_count: number;
  supplier_drift_offer_count: number;
  unresolved_exact_row_count: number;
  groups: Array<{
    comparison_group_sha256: string;
    marketplace: string;
    currency: string;
    price_basis: string;
    comparison_dimensions: Record<string, string>;
    status: "comparable" | "insufficient_exact_offers";
    exact_offer_count: number;
    exact_row_count: number;
    eligible_offer_count: number;
    eligible_row_count: number;
    minimum_eligible_unit_price: string | null;
    lowest_rows: SourcingComparisonRow[];
    rows: SourcingComparisonRow[];
  }>;
  formal_cost_created: false;
  freight_included: false;
  tax_included: false;
  external_write: false;
};

type SourcingComparisonRow = {
  capture_id: string;
  supplier_ref: string;
  offer_id: string;
  sku_id: string;
  spec_id: string;
  variant_key: string;
  unit_price: string;
  currency: string;
  min_order_quantity: number | null;
  availability: string;
  eligibility:
    | "eligible_public_display_price"
    | "reference_quantity_below_moq"
    | "moq_unverified"
    | "out_of_stock"
    | "availability_unverified"
    | "price_basis_not_public_unit";
  source_url: string;
};

type Blocker = {
  code: string;
  severity: string;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type Preflight = {
  status: "ready_with_constraints";
  capture_allowed: true;
  request_sha256: string;
  capture_state_if_saved: "quarantined" | "pending_independent_binding";
  normalized: Envelope & {
    scope: {
      tenant_ref: string;
      entity_ref: string | null;
      store_ref: string;
      entity_scope_status: string;
    };
    source_adapter: {
      adapter_id: string;
      adapter_version: string;
      semantic_authority: string;
      source_grade: string;
    };
    variant_summary: VariantSummary[];
    erp_staging: ErpStaging;
  };
  promotion_readiness: {
    status: "no_data" | "blocked";
    source_gaps: string[];
    blockers: Blocker[];
  };
  control_envelope: ControlEnvelope;
};

type ControlEnvelope = {
  internal_evidence_write_only: true;
  formal_observation_created: false;
  supplier_offer_created: false;
  actual_cost_created: false;
  product_created: false;
  listing_created: false;
  approval_created: false;
  permit_created: false;
  external_write_allowed: false;
};

type Submission = {
  id: string;
  status: "quarantined" | "pending_independent_binding";
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    entity_scope_status: string;
  };
  marketplace: string;
  source_url: string;
  observed_at: string;
  request_sha256: string;
  evidence: {
    evidence_id: string;
    sha256: string;
    grade: string;
    integrity_status: string;
  };
  item_count: number;
  items: Envelope["items"];
  page?: Envelope["page"];
  merchant?: Envelope["merchant"];
  variant_summary?: VariantSummary[];
  erp_staging?: ErpStaging;
  promotion_readiness: {
    status: "ready" | "blocked" | "no_data";
    source_gaps: string[];
    blockers: Blocker[];
    observation_promotion_route_exposed: false;
  };
  control_envelope: ControlEnvelope;
};

type Inbox = {
  status: "ready" | "partial" | "no_data";
  items: Submission[];
  sourcing_comparison: SourcingComparison;
  counts: {
    total: number;
    quarantined: number;
    pending_independent_binding: number;
    ready_for_promotion: number;
    promoted: 0;
  };
  control_envelope: ControlEnvelope;
};

type ExtensionResponse = {
  ok?: boolean;
  envelope?: Envelope;
  error?: string;
};

type RuntimeApi = {
  lastError?: { message?: string };
  sendMessage: (
    extensionId: string,
    message: Record<string, unknown>,
    callback: (response?: ExtensionResponse) => void,
  ) => void;
};

declare global {
  interface Window {
    chrome?: { runtime?: RuntimeApi };
  }
}

const STORE_REF = "ozon-primary";
const EXTENSION_ID = /^[a-p]{32}$/;

function extensionMessage(
  extensionId: string,
  message: Record<string, unknown>,
): Promise<ExtensionResponse> {
  return new Promise((resolve, reject) => {
    const runtime = window.chrome?.runtime;
    if (!runtime) {
      reject(new Error("当前页面没有检测到 KJDS 浏览器助手"));
      return;
    }
    runtime.sendMessage(extensionId, message, (response) => {
      if (runtime.lastError) {
        reject(new Error(runtime.lastError.message ?? "浏览器助手连接失败"));
        return;
      }
      resolve(response ?? {});
    });
  });
}

async function responsePayload<T>(response: {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}): Promise<T> {
  const payload: unknown = await response.json();
  if (!response.ok) {
    const detail = (
      payload !== null
      && typeof payload === "object"
      && "detail" in payload
      && typeof payload.detail === "string"
    )
      ? payload.detail
      : `API ${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

export function BrowserCaptureInboxConsole() {
  const [envelope, setEnvelope] = useState<Envelope | null>(null);
  const [rawEnvelope, setRawEnvelope] = useState("");
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [state, setState] = useState<
    "loading" | "idle" | "preflighting" | "saving" | "saved" | "error"
  >("loading");
  const [detail, setDetail] = useState<string | null>(null);
  const [extensionId, setExtensionId] = useState<string | null | undefined>(
    undefined,
  );

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("extension_id");
    setExtensionId(value && EXTENSION_ID.test(value) ? value : null);
  }, []);

  const loadInbox = useCallback(async () => {
    const response = await fetchJson<Inbox>(
      `/backend/v1/browser-capture-inbox/submissions?store_ref=${encodeURIComponent(STORE_REF)}`,
      { cache: "no-store" },
    );
    setInbox(await responsePayload<Inbox>(response));
  }, []);

  useEffect(() => {
    if (extensionId === undefined) return;
    let active = true;
    Promise.all([
      loadInbox(),
      extensionId
        ? extensionMessage(extensionId, { type: "KJDS_CAPTURE_PEEK" })
        : Promise.resolve({} as ExtensionResponse),
    ])
      .then(([, extension]) => {
        if (!active) return;
        if (extension.envelope) {
          setEnvelope(extension.envelope);
          setRawEnvelope(JSON.stringify(extension.envelope, null, 2));
        }
        setState("idle");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setDetail(error instanceof Error ? error.message : "读取失败");
        setState("error");
      });
    return () => {
      active = false;
    };
  }, [extensionId, loadInbox]);

  const parseManual = () => {
    try {
      const value = JSON.parse(rawEnvelope) as Envelope;
      setEnvelope(value);
      setPreflight(null);
      setDetail(null);
      setState("idle");
    } catch {
      setDetail("JSON 不是有效的 KJDS capture envelope");
      setState("error");
    }
  };

  const runPreflight = async () => {
    if (!envelope) return;
    setState("preflighting");
    setDetail(null);
    try {
      const response = await fetchJson<Preflight>(
        "/backend/v1/browser-capture-inbox/preflight",
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(envelope),
        },
      );
      setPreflight(await responsePayload<Preflight>(response));
      setState("idle");
    } catch (error) {
      setDetail(error instanceof Error ? error.message : "预检失败");
      setState("error");
    }
  };

  const save = async () => {
    if (!envelope || !preflight) return;
    setState("saving");
    setDetail(null);
    try {
      const response = await fetchJson<Submission>(
        "/backend/v1/browser-capture-inbox/submissions",
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(envelope),
        },
      );
      const saved = await responsePayload<Submission>(response);
      if (extensionId) {
        await extensionMessage(extensionId, {
          type: "KJDS_CAPTURE_ACK",
          idempotency_key: envelope.idempotency_key,
          submission_id: saved.id,
        });
      }
      await loadInbox();
      setState("saved");
    } catch (error) {
      setDetail(error instanceof Error ? error.message : "保存失败");
      setState("error");
    }
  };

  const item = preflight?.normalized.items[0] ?? envelope?.items[0] ?? null;
  const previewItems = preflight?.normalized.items ?? envelope?.items ?? [];
  const summary = preflight?.normalized.variant_summary?.[0] ?? null;
  const erpStaging = preflight?.normalized.erp_staging ?? null;
  const coverage = preflight?.normalized.page.capture_coverage
    ?? envelope?.page.capture_coverage ?? {};

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p>BROWSER CAPTURE · EVIDENCE INBOX</p>
          <h1>网页采集收件箱</h1>
          <span>在 1688/Ozon 当前页面显式采集，先保存原始观察，再独立审查和晋级。</span>
        </div>
        <nav>
          <Link href="/">返回经营台</Link>
          <Link href="/evidenceops">EvidenceOps</Link>
        </nav>
      </header>

      <section className={styles.boundary}>
        <strong>VISIBLE DOM ONLY</strong>
        <span>Cookie / localStorage · 不读取</span>
        <span>Supplier Offer / actual cost · false</span>
        <span>Approval / Permit · false / false</span>
        <b>external write · false</b>
      </section>

      {state === "loading" ? (
        <section className={styles.notice}>正在读取服务端收件箱与浏览器助手…</section>
      ) : null}
      {detail ? (
        <section className={styles.error} role="alert">
          <strong>当前动作未完成</strong>
          <span>{detail}</span>
          <button type="button" onClick={() => {
            setDetail(null);
            setState("idle");
          }}>返回预览</button>
        </section>
      ) : null}

      <section className={styles.workflow}>
        <article data-active={Boolean(envelope)}>
          <span>01</span><strong>当前页采集</strong>
          <small>{envelope ? "已收到 envelope" : "等待浏览器助手或受控 JSON"}</small>
        </article>
        <article data-active={Boolean(preflight)}>
          <span>02</span><strong>服务端预检</strong>
          <small>adapter · host · price scope · authority</small>
        </article>
        <article data-active={state === "saved"}>
          <span>03</span><strong>保存 Evidence</strong>
          <small>独立点击，不自动晋级 Observation</small>
        </article>
      </section>

      <div className={styles.columns}>
        <section className={styles.capture}>
          <div className={styles.sectionHeading}>
            <div><p>PENDING ENVELOPE</p><h2>当前页预览</h2></div>
            <span>{extensionId ? "extension handshake" : "manual fallback"}</span>
          </div>
          {item ? (
            <article className={styles.item}>
              <div>
                <span>{envelope?.marketplace}</span>
                <strong>{item.title}</strong>
                <a href={envelope?.source_url} target="_blank" rel="noreferrer">
                  {envelope?.source_url}
                </a>
              </div>
              <dl>
                <div><dt>商品 / 变体</dt><dd>{item.external_item_id} · {item.variant_key}</dd></div>
                <div><dt>观察价格</dt><dd>{item.displayed_price} {item.currency}</dd></div>
                <div><dt>价义</dt><dd>{item.price_kind} / {item.price_scope}</dd></div>
                <div><dt>MOQ / 数量</dt><dd>{item.min_order_quantity ?? "unknown"} / {item.observed_quantity ?? "not observed"}</dd></div>
                <div><dt>采集类型</dt><dd>{preflight?.normalized.page.capture_kind ?? envelope?.page.capture_kind ?? "generic_product"}</dd></div>
                <div><dt>覆盖</dt><dd>{String(coverage.captured_count ?? previewItems.length)} / {String(coverage.discovered_count ?? previewItems.length)}{coverage.truncated ? " · truncated" : ""}</dd></div>
              </dl>
            </article>
          ) : (
            <div className={styles.empty}>
              在允许的 1688/Ozon 商品页点击 KJDS 浏览器助手；也可粘贴一个受控 envelope 做本地验收。
            </div>
          )}
          {previewItems.length ? (
            <section className={styles.variantMatrix} aria-label="SKU 与价格一一对应矩阵">
              <div>
                <strong>SKU / SPEC / PRICE MATRIX</strong>
                <span>{previewItems.length} 行 · 不跨规格补值</span>
              </div>
              <div className={styles.tableScroll}>
                <table>
                  <thead><tr><th>Offer</th><th>SKU / Spec</th><th>规格</th><th>价格</th><th>库存 / 销量信号</th><th>ERP 映射</th></tr></thead>
                  <tbody>
                    {previewItems.map((row) => {
                      const mapping = erpStaging?.rows.find(
                        (entry) => entry.offer_id === row.external_item_id
                          && entry.sku_id === (row.product_identity.sku_id ?? null)
                          && entry.spec_id === (row.product_identity.spec_id ?? null),
                      );
                      return (
                        <tr key={`${row.external_item_id}:${row.product_identity.sku_id ?? row.variant_key}`}>
                          <td><code>{row.external_item_id}</code></td>
                          <td><code>{row.product_identity.sku_id ?? "unknown"}</code><small>{row.product_identity.spec_id ?? "unknown"}</small></td>
                          <td>{row.variant_key}<small>{Object.entries(row.comparison_dimensions ?? {}).map(([key, value]) => `${key}=${value}`).join(" · ") || "comparison dimensions missing"}</small></td>
                          <td><strong>{row.displayed_price} {row.currency}</strong><small>{row.price_kind}</small></td>
                          <td><span>{String(row.supply_signals?.stock_count ?? "unknown")} / {String(row.market_signals?.sku_sale_count_signal ?? "unknown")}</span></td>
                          <td data-state={mapping?.mapping_status ?? "pending_preflight"}>
                            {mapping?.mapping_status ?? "pending_preflight"}
                            {mapping ? (
                              <small>
                                ERP: MOQ={mapping.min_order_quantity ?? "unknown"}
                                {` · ${mapping.availability}`}
                                {` · stock=${String(mapping.supply_signals.stock_count ?? "unknown")}`}
                                {` · sales=${String(mapping.market_signals.sku_sale_count_signal ?? "unknown")}`}
                              </small>
                            ) : null}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {summary ? (
                <div className={styles.summaryStrip}>
                  <span>服务端最低价 <strong>{summary.minimum_unit_price} {summary.currency}</strong></span>
                  <span>对应 SKU <strong>{summary.minimum_variants.map((entry) => entry.sku_id ?? "unknown").join(", ")}</strong></span>
                  <span>可比组 <strong>{summary.comparison_groups.length}</strong></span>
                  <span>ERP 暂存 <strong>{erpStaging?.exact_variant_count ?? 0}/{erpStaging?.row_count ?? previewItems.length}</strong></span>
                </div>
              ) : null}
            </section>
          ) : null}
          <label className={styles.raw}>
            <span>受控 envelope JSON</span>
            <textarea
              value={rawEnvelope}
              onChange={(event) => setRawEnvelope(event.target.value)}
              placeholder="等待浏览器助手，或粘贴 kjds-browser-capture-envelope/1.2"
            />
          </label>
          <div className={styles.actions}>
            <button type="button" onClick={parseManual} disabled={!rawEnvelope || state === "saving"}>
              载入 JSON
            </button>
            <button type="button" onClick={runPreflight} disabled={!envelope || state === "preflighting" || state === "saving"}>
              {state === "preflighting" ? "预检中…" : "服务端预检"}
            </button>
            <button type="button" className={styles.primary} onClick={save} disabled={!preflight || state === "saving"}>
              {state === "saving" ? "保存中…" : "保存为 C 级 Evidence"}
            </button>
          </div>
        </section>

        <aside className={styles.readiness}>
          <div className={styles.sectionHeading}>
            <div><p>PROMOTION READINESS</p><h2>为什么还不能晋级</h2></div>
            <strong data-state={preflight?.promotion_readiness.status ?? "no_data"}>
              {preflight?.promotion_readiness.status ?? "no_data"}
            </strong>
          </div>
          {preflight ? (
            <>
              <dl>
                <div><dt>Tenant</dt><dd>{preflight.normalized.scope.tenant_ref}</dd></div>
                <div><dt>Entity</dt><dd>{preflight.normalized.scope.entity_ref ?? "null · authority missing"}</dd></div>
                <div><dt>Store</dt><dd>{preflight.normalized.scope.store_ref}</dd></div>
                <div><dt>Adapter</dt><dd>{preflight.normalized.source_adapter.adapter_id}</dd></div>
                <div><dt>Semantic authority</dt><dd>{preflight.normalized.source_adapter.semantic_authority}</dd></div>
                <div><dt>Request hash</dt><dd><code>{preflight.request_sha256.slice(0, 20)}…</code></dd></div>
              </dl>
              <div className={styles.blockers}>
                {preflight.promotion_readiness.blockers.map((blocker) => (
                  <article key={blocker.code}>
                    <span>{blocker.severity} · {blocker.owner}</span>
                    <strong>{blocker.code}</strong>
                    <p>{blocker.next}</p>
                    <Link href={blocker.next_workspace}>下一工作区</Link>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className={styles.empty}>先运行服务端预检。客户端不自行判断 entity、Evidence 或晋级状态。</div>
          )}
        </aside>
      </div>

      <section className={styles.ledger}>
        <div className={styles.sectionHeading}>
          <div><p>APPEND-ONLY RECEIPTS</p><h2>当前店铺收件箱</h2></div>
          <button type="button" onClick={() => loadInbox().catch((error: unknown) => {
            setDetail(error instanceof Error ? error.message : "刷新失败");
            setState("error");
          })}>刷新</button>
        </div>
        <div className={styles.metrics}>
          <div><span>总计</span><strong>{inbox?.counts.total ?? 0}</strong></div>
          <div><span>隔离</span><strong>{inbox?.counts.quarantined ?? 0}</strong></div>
          <div><span>待独立绑定</span><strong>{inbox?.counts.pending_independent_binding ?? 0}</strong></div>
          <div><span>可申请晋级</span><strong>{inbox?.counts.ready_for_promotion ?? 0}</strong></div>
          <div><span>已晋级</span><strong>0</strong></div>
        </div>
        {inbox?.sourcing_comparison ? (
          <section className={styles.comparisonWorkspace} aria-label="跨供应商同维度比价">
            <div className={styles.sectionHeading}>
              <div>
                <p>SOURCING COMPARISON · QTY {inbox.sourcing_comparison.reference_quantity}</p>
                <h2>跨供应商同维度比价</h2>
              </div>
              <strong data-state={inbox.sourcing_comparison.status}>
                {inbox.sourcing_comparison.status}
              </strong>
            </div>
            <div className={styles.comparisonMetrics}>
              <span>最新详情 offer <strong>{inbox.sourcing_comparison.latest_exact_offer_count}</strong></span>
              <span>待展开候选 <strong>{inbox.sourcing_comparison.candidate_row_count}</strong></span>
              <span>缺关键维度 SKU <strong>{inbox.sourcing_comparison.unresolved_exact_row_count}</strong></span>
              <span>供应商漂移 offer <strong>{inbox.sourcing_comparison.supplier_drift_offer_count}</strong></span>
              <span>运费 / 税 <strong>未计入 / 未计入</strong></span>
            </div>
            {!inbox.sourcing_comparison.groups.length ? (
              <div className={styles.empty}>先采集候选详情的完整 SKU 矩阵；搜索卡价格不进入最低价排行。</div>
            ) : (
              <div className={styles.comparisonGroups}>
                {inbox.sourcing_comparison.groups.map((group) => (
                  <details key={group.comparison_group_sha256} open={group.status === "comparable"}>
                    <summary>
                      <span>{Object.entries(group.comparison_dimensions).map(([key, value]) => `${key}=${value}`).join(" · ")}</span>
                      <strong>{group.minimum_eligible_unit_price ?? "no eligible price"} {group.currency}</strong>
                      <b>{group.eligible_offer_count}/{group.exact_offer_count} offer 可参与</b>
                    </summary>
                    <div className={styles.tableScroll}>
                      <table>
                        <thead><tr><th>供应商 / Offer</th><th>SKU / Spec</th><th>规格</th><th>公开单价</th><th>MOQ / 库存</th><th>资格</th></tr></thead>
                        <tbody>
                          {group.rows.map((row) => (
                            <tr key={`${row.capture_id}:${row.sku_id}:${row.spec_id}`}>
                              <td>{row.supplier_ref}<small>{row.offer_id}</small></td>
                              <td><code>{row.sku_id}</code><small>{row.spec_id}</small></td>
                              <td>{row.variant_key}</td>
                              <td><strong>{row.unit_price} {row.currency}</strong></td>
                              <td>{row.min_order_quantity ?? "unknown"} / {row.availability}</td>
                              <td data-state={row.eligibility}>{row.eligibility}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                ))}
              </div>
            )}
          </section>
        ) : null}
        {!inbox?.items.length ? (
          <div className={styles.empty}>no_data · 尚无当前 tenant/store 的浏览器采集 Evidence。</div>
        ) : (
          <div className={styles.receipts}>
            {inbox.items.map((submission) => (
              <article key={submission.id}>
                <div>
                  <span>{submission.marketplace} · {submission.status}</span>
                  <strong>{submission.items[0]?.title ?? submission.id}</strong>
                  <code>{submission.id}</code>
                </div>
                <dl>
                  <div><dt>Entity</dt><dd>{submission.scope.entity_ref ?? "null"}</dd></div>
                  <div><dt>Evidence</dt><dd>{submission.evidence.evidence_id}</dd></div>
                  <div><dt>Integrity</dt><dd>{submission.evidence.integrity_status}</dd></div>
                  <div><dt>Promotion</dt><dd>{submission.promotion_readiness.status}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
