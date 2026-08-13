"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./pim.module.css";

type Status = "ready" | "partial" | "blocked" | "no_data";
type Group = {
  product: { id: string; sku: string; name: string; status: string };
  source_lineage: {
    status: "observed" | "no_data";
    competitive_market_url: string | null;
    primary_supplier_url: string | null;
    backup_supplier_urls: string[];
    source_evidence_id: string | null;
    links_are_observations_not_orders: true;
    external_sync_performed: false;
  };
  passports: { kind: string; status: string }[];
  content_assets: { id: string; content_type: string; status: string; qa_check_count: number }[];
  listings: { offer_id: string; marketplace_sku: string | null; listing_status: string | null }[];
  readiness: { status: "ready" | "incomplete" | "blocked"; pre_listing_stage: string };
  owner: string;
  sla: string;
  next: string;
  group_snapshot_sha256: string;
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
  product_groups: Group[];
  unbound_listings: { offer_id: string; marketplace_sku: string | null; binding_issue: string }[];
  source_gaps: string[];
  blockers: { code: string; owner: string; sla: string; next: string }[];
  snapshot_sha256: string;
  agent_artifact: { contract_id: string; authority: string; permit_issue_allowed: false; external_write_allowed: false };
  control_envelope: {
    client_recalculation_allowed: false;
    product_created: false;
    passport_created: false;
    listing_created: false;
    approval_created: false;
    permit_created: false;
    external_write_allowed: false;
  };
};

export function PimConsole() {
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [readiness, setReadiness] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);

  const load = useCallback(async (requestedCursor: string | null = cursor) => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ store_ref: "ozon-primary", page_size: "50" });
    if (query.trim()) params.set("query", query.trim());
    if (readiness) params.set("readiness", readiness);
    if (requestedCursor) params.set("cursor", requestedCursor);
    try {
      const response = await fetchJson<Workspace>(`/backend/v1/pim/workspace?${params.toString()}`);
      const body = await response.json();
      if (!response.ok) throw new Error(`PIM API ${response.status}`);
      setData(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "PIM 工作台加载失败");
    } finally {
      setLoading(false);
    }
  }, [cursor, query, readiness]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className={styles.page}>
      <nav><Link href="/commerce-os">← Commerce OS</Link><strong>KJDS · PIM</strong><Link href="/listings">Listing 生命周期 →</Link></nav>
      <header>
        <p>CANONICAL PRODUCT · EXACT SCOPE · READ ONLY</p>
        <h1>商品主数据，<em>不是另一套商品库。</em></h1>
        <span>服务端归并 Product、三 Passport、媒体 QA 与 Ozon Listing；客户端不重算 readiness。</span>
      </header>
      <section className={styles.boundary}>
        <span>Product create · false</span><span>Passport create · false</span>
        <span>Listing create · false</span><span>Approval / Permit · false / false</span>
        <span>external write · false</span>
      </section>
      <form className={styles.filters} onSubmit={(event) => { event.preventDefault(); setCursor(null); void load(null); }}>
        <input aria-label="搜索 SKU、商品或 offer" value={query} onChange={(event) => { setQuery(event.target.value); setCursor(null); }} placeholder="搜索 SKU、商品或 offer" />
        <select aria-label="Readiness" value={readiness} onChange={(event) => { setReadiness(event.target.value); setCursor(null); }}>
          <option value="">全部 readiness</option><option value="ready">ready</option>
          <option value="incomplete">incomplete</option><option value="blocked">blocked</option>
        </select>
        <button type="submit">刷新</button>
      </form>
      {loading && <section role="status" className={styles.notice}>正在读取 exact-scope PIM 快照…</section>}
      {error && <section role="alert" className={styles.error}><p>{error}</p><button onClick={() => void load()}>重试</button></section>}
      {!loading && !error && data && (
        <>
          <section className={styles.metrics}>
            <article><strong>{data.counts.total_product_groups}</strong><span>Canonical Products</span></article>
            <article><strong>{data.counts.bound_listings}</strong><span>已绑定 Listing</span></article>
            <article><strong>{data.counts.unbound_listings}</strong><span>未绑定 Listing</span></article>
            <article><strong>{data.counts.ready}</strong><span>刊登前 ready</span></article>
          </section>
          {(data.status === "blocked" || data.status === "partial") && (
            <section className={data.status === "blocked" ? styles.error : styles.notice} data-state={data.status}>
              <h2>{data.status === "blocked" ? "权威链已阻断" : "部分数据可用"}</h2>
              <p>状态由服务端 Evidence 与 exact-scope 权威决定，页面不会回退到旧记录。</p>
              {data.source_gaps.length > 0 && <ul>{data.source_gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>}
              {data.blockers.map((blocker) => <p key={`${blocker.code}:${blocker.owner}`}>{blocker.code} · {blocker.owner} · {blocker.next}</p>)}
            </section>
          )}
          {data.status === "no_data" && data.product_groups.length === 0 && data.unbound_listings.length === 0 && (
            <section className={styles.notice}><h2>真实 no_data</h2><p>当前 exact scope 没有可验证 Product 或 Listing；没有把 0 伪装为覆盖完成。</p>{data.source_gaps.map((gap) => <p key={gap}>{gap}</p>)}</section>
          )}
          <section className={styles.grid}>
            {data.product_groups.map((group) => (
              <details key={group.product.id} className={styles.card}>
                <summary><span><b>{group.product.sku}</b>{group.product.name}</span><i data-status={group.readiness.status}>{group.readiness.status}</i></summary>
                <div className={styles.detail}>
                  <p>阶段 · {group.readiness.pre_listing_stage}</p>
                  <p>Listing · {group.listings.length}　Passport · {group.passports.map((item) => `${item.kind}:${item.status}`).join(" / ") || "none"}</p>
                  <p>媒体资产 · {group.content_assets.length}　Owner · {group.owner}</p>
                  <section className={styles.lineage} aria-label={`${group.product.sku} 来源链`}>
                    <strong>竞标与货源映射</strong>
                    {group.source_lineage.competitive_market_url ? <a href={group.source_lineage.competitive_market_url} target="_blank" rel="noreferrer">竞标商品</a> : <span>竞标商品 no_data</span>}
                    {group.source_lineage.primary_supplier_url ? <a href={group.source_lineage.primary_supplier_url} target="_blank" rel="noreferrer">主货源候选</a> : <span>主货源 no_data</span>}
                    {group.source_lineage.backup_supplier_urls.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer">备选货源 {index + 1}</a>)}
                    <small>事件账本证据快照 · 未询价/下单 · 未同步第三方 ERP</small>
                  </section>
                  <p>SLA · {group.sla}</p><p>Next · {group.next}</p>
                  <code>{group.group_snapshot_sha256}</code>
                </div>
              </details>
            ))}
          </section>
          {data.unbound_listings.length > 0 && <section className={styles.notice}><h2>未绑定 Listing</h2>{data.unbound_listings.map((item) => <p key={item.offer_id}>{item.offer_id} · {item.marketplace_sku ?? "SKU missing"} · {item.binding_issue}</p>)}</section>}
          {data.query.next_cursor && <section className={styles.pagination}><button type="button" onClick={() => setCursor(data.query.next_cursor)}>下一页</button><span>服务端 opaque cursor · 当前 {data.counts.page_product_groups}/{data.counts.total_product_groups}</span></section>}
          <footer><span>{data.agent_artifact.contract_id} · {data.agent_artifact.authority}</span><span>Agent 只能建议/内部任务；不能自批、发 Permit 或外部写。</span><Link href="/media-factory">进入内容媒体工厂 →</Link><code>{data.snapshot_sha256}</code></footer>
        </>
      )}
    </main>
  );
}
