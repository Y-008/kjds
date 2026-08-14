"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./browser-capture-inbox.module.css";

type Envelope = {
  contract_version: "kjds-browser-capture-envelope/1.0";
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
    extractor_version: "kjds-visible-dom/1.0";
    capture_mode: "active_tab_visible_dom";
  };
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
    observed_quantity?: number | null;
    checkout_verified?: boolean;
    tax_included?: boolean | null;
    domestic_freight_included?: boolean | null;
    purchase_available?: boolean;
    confidence?: string;
    supply_signals?: Record<string, unknown>;
    media_rights_status: "unverified_external_reference";
  }>;
  confirmed: true;
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
              </dl>
            </article>
          ) : (
            <div className={styles.empty}>
              在允许的 1688/Ozon 商品页点击 KJDS 浏览器助手；也可粘贴一个受控 envelope 做本地验收。
            </div>
          )}
          <label className={styles.raw}>
            <span>受控 envelope JSON</span>
            <textarea
              value={rawEnvelope}
              onChange={(event) => setRawEnvelope(event.target.value)}
              placeholder="等待浏览器助手，或粘贴 kjds-browser-capture-envelope/1.0"
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
