"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./sourcing-intelligence.module.css";

type Status = "ready" | "partial" | "blocked" | "no_data";
type WorkItem = {
  work_item_key: string;
  candidate_key: string | null;
  canonical_products: {
    id: string;
    sku: string;
    name: string;
    readiness_status: string;
    listing_count: number;
  }[];
  market_research: {
    counts: {
      competitor_listing_rows: number;
      supplier_option_rows: number;
      checkout_comparable_at_target: number;
    };
    target_purchase_quantity: number;
    sales_is_actual: false;
  } | null;
  rfq_and_quotes: {
    rfq_packages: unknown[];
    dispatch_proofs: unknown[];
    quotes: unknown[];
    accepted_unique_suppliers: string[];
    rfq_draft_ready: boolean;
    three_accepted_quotes_ready: boolean;
    automatic_supplier_contact: false;
  };
  economics: {
    authority: string;
    native_candidate_present: boolean;
    fifteen_component_downside_ready: boolean;
    downside: { cm3_cny?: string | null; components?: unknown[] } | null;
    formal_cm3: null;
    actual_cash_cm3: null;
  };
  readiness: {
    status: "ready" | "partial" | "blocked";
    market_research_ready: boolean;
    canonical_product_bound: boolean;
    rfq_draft_ready: boolean;
    three_accepted_quotes_ready: boolean;
    fifteen_component_downside_ready: boolean;
  };
  owner: string;
  sla: string;
  next: string;
  item_snapshot_sha256: string;
};
type Workspace = {
  status: Status;
  as_of: string;
  scope: { store_ref: string; entity_ref: string | null };
  query: {
    page_size: number;
    cursor: string | null;
    next_cursor: string | null;
    search: string | null;
    readiness: string | null;
  };
  counts: Record<string, number>;
  work_items: WorkItem[];
  source_gaps: string[];
  blockers: { code: string; owner: string; sla: string; next: string }[];
  authority_levels: Record<string, string>;
  agent_artifact: {
    contract_id: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    supplier_contact_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    client_recalculation_allowed: false;
    supplier_contacted: false;
    rfq_dispatched: false;
    quote_accepted: false;
    purchase_order_created: false;
    payment_created: false;
    approval_created: false;
    permit_created: false;
    external_write_allowed: false;
  };
  snapshot_sha256: string;
};

function flag(value: boolean) {
  return value ? "ready" : "missing";
}

export function SourcingIntelligenceConsole() {
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [readiness, setReadiness] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);

  const load = useCallback(async (requestedCursor: string | null = cursor) => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      store_ref: "ozon-primary",
      page_size: "50",
      target_purchase_quantity: "3",
    });
    if (query.trim()) params.set("query", query.trim());
    if (readiness) params.set("readiness", readiness);
    if (requestedCursor) params.set("cursor", requestedCursor);
    try {
      const response = await fetchJson<Workspace>(
        `/backend/v1/sourcing-intelligence/workspace?${params.toString()}`,
      );
      const body = await response.json();
      if (!response.ok) throw new Error(`Sourcing Intelligence API ${response.status}`);
      setData(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "供应智能工作台加载失败");
    } finally {
      setLoading(false);
    }
  }, [cursor, query, readiness]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className={styles.page}>
      <nav>
        <Link href="/commerce-os">← Commerce OS</Link>
        <strong>KJDS · SOURCING INTELLIGENCE</strong>
        <Link href="/procurement">采购与收货控制 →</Link>
      </nav>
      <header>
        <p>EXACT IDENTITY · EVIDENCE-BOUND · READ ONLY</p>
        <h1>供应研究，<em>直到三报价与十五项下行利润。</em></h1>
        <span>
          Accio 级 JTBD 由 KJDS 原生权威实现；观察、正式报价、screening CM3 与 Actual Cash CM3 严格分层。
        </span>
      </header>
      <section className={styles.boundary}>
        <span>Supplier contact · false</span>
        <span>RFQ dispatch · false</span>
        <span>PO / Payment · false / false</span>
        <span>Approval / Permit · false / false</span>
        <span>external write · false</span>
      </section>
      <form
        className={styles.filters}
        onSubmit={(event) => {
          event.preventDefault();
          setCursor(null);
          void load(null);
        }}
      >
        <input
          aria-label="搜索商品、候选或供应商"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setCursor(null);
          }}
          placeholder="搜索商品、候选或供应商"
        />
        <select
          aria-label="Readiness"
          value={readiness}
          onChange={(event) => {
            setReadiness(event.target.value);
            setCursor(null);
          }}
        >
          <option value="">全部阶段</option>
          <option value="research">research ready</option>
          <option value="rfq">RFQ draft</option>
          <option value="three_quotes">three quotes</option>
          <option value="downside">15-item downside</option>
          <option value="blocked">blocked</option>
        </select>
        <button type="submit">刷新</button>
      </form>
      {loading && (
        <section role="status" className={styles.notice}>
          正在读取 exact-scope 供应研究快照…
        </section>
      )}
      {error && (
        <section role="alert" className={styles.error}>
          <p>{error}</p>
          <button onClick={() => void load()}>重试</button>
        </section>
      )}
      {!loading && !error && data && (
        <>
          <section className={styles.metrics}>
            <article><strong>{data.counts.exact_research_cohorts}</strong><span>Exact Cohorts</span></article>
            <article><strong>{data.counts.supplier_option_rows}</strong><span>供应观察</span></article>
            <article><strong>{data.counts.accepted_quotes}</strong><span>已接受报价</span></article>
            <article><strong>{data.counts.fifteen_component_downside_ready}</strong><span>十五项 CM3 ready</span></article>
            <article><strong>{data.counts.products_with_three_accepted_quotes}</strong><span>三报价 Product</span></article>
          </section>
          {(data.status === "blocked" || data.status === "partial") && (
            <section
              className={data.status === "blocked" ? styles.error : styles.notice}
              data-state={data.status}
            >
              <h2>{data.status === "blocked" ? "供应权威链已阻断" : "部分研究可用"}</h2>
              <p>页面不回退旧 Evidence，也不把公开观察价升格为 Supplier Offer。</p>
              {data.source_gaps.length > 0 && (
                <ul>{data.source_gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
              )}
              {data.blockers.map((blocker) => (
                <p key={`${blocker.code}:${blocker.owner}`}>
                  {blocker.code} · {blocker.owner} · {blocker.next}
                </p>
              ))}
            </section>
          )}
          {data.status === "no_data" && data.work_items.length === 0 && (
            <section className={styles.notice}>
              <h2>真实 no_data</h2>
              <p>当前 exact scope 没有可验证供应研究对象；0 不代表已覆盖或可采购。</p>
              {data.source_gaps.map((gap) => <p key={gap}>{gap}</p>)}
            </section>
          )}
          <section className={styles.grid}>
            {data.work_items.map((item) => (
              <details key={item.work_item_key} className={styles.card}>
                <summary>
                  <span>
                    <b>{item.canonical_products[0]?.sku ?? item.candidate_key ?? "unbound"}</b>
                    {item.canonical_products[0]?.name ?? "Exact identity research cohort"}
                  </span>
                  <i data-status={item.readiness.status}>{item.readiness.status}</i>
                </summary>
                <div className={styles.detail}>
                  <div className={styles.rail}>
                    <span data-ready={item.readiness.market_research_ready}>市场研究 · {flag(item.readiness.market_research_ready)}</span>
                    <span data-ready={item.readiness.canonical_product_bound}>Product · {flag(item.readiness.canonical_product_bound)}</span>
                    <span data-ready={item.readiness.rfq_draft_ready}>RFQ · {flag(item.readiness.rfq_draft_ready)}</span>
                    <span data-ready={item.readiness.three_accepted_quotes_ready}>三报价 · {flag(item.readiness.three_accepted_quotes_ready)}</span>
                    <span data-ready={item.readiness.fifteen_component_downside_ready}>下行 CM3 · {flag(item.readiness.fifteen_component_downside_ready)}</span>
                  </div>
                  <p>
                    竞品 {item.market_research?.counts.competitor_listing_rows ?? 0} ·
                    供应选项 {item.market_research?.counts.supplier_option_rows ?? 0} ·
                    target checkout {item.market_research?.counts.checkout_comparable_at_target ?? 0}
                  </p>
                  <p>
                    RFQ {item.rfq_and_quotes.rfq_packages.length} · dispatch proof {item.rfq_and_quotes.dispatch_proofs.length} ·
                    quote {item.rfq_and_quotes.quotes.length}
                  </p>
                  <p>
                    downside CM3 · {item.economics.downside?.cm3_cny ?? "no_data"} ·
                    formal CM3 · no_data · Actual Cash CM3 · no_data
                  </p>
                  <p>Owner · {item.owner}　SLA · {item.sla}</p>
                  <p>Next · {item.next}</p>
                  <code>{item.item_snapshot_sha256}</code>
                </div>
              </details>
            ))}
          </section>
          {data.query.next_cursor && (
            <section className={styles.pagination}>
              <button type="button" onClick={() => setCursor(data.query.next_cursor)}>
                下一页
              </button>
              <span>
                服务端 opaque cursor · 当前 {data.counts.page_work_items}/{data.counts.total_work_items}
              </span>
            </section>
          )}
          <footer>
            <span>{data.agent_artifact.contract_id} · {data.agent_artifact.authority}</span>
            <span>Agent 只能建议/内部任务；不能联系供应商、自批、发 Permit、采购或付款。</span>
            <code>{data.snapshot_sha256}</code>
          </footer>
        </>
      )}
    </main>
  );
}
