"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./formal-facts.module.css";

type Fact = {
  id: string;
  fact_type: string;
  natural_key: string;
  contract_version: string;
  payload_hash: string;
  effective_at: string;
  recorded_at: string;
  evidence_id: string;
  product_id: string;
  resolution_status: string;
  scope: {
    tenant_ref: string;
    entity_ref: string;
    store_ref: string;
    scope_grant_authority_sha256: string;
    source_evidence_sha256: string;
    scope_as_of: string;
  };
  formal_fact: true;
  accounting_posted: false;
  external_write_allowed: false;
  approval_created: false;
  permit_created: false;
};

type Workspace = {
  contract_id: string;
  status: "ready" | "no_data";
  scope: {
    tenant_ref: string;
    entity_ref: string;
    store_ref: string;
    scope_grant_authority_sha256: string;
  };
  as_of: string;
  items: Fact[];
  formal_fact_count: number;
  legacy_rows_inferred: false;
  claim_source_allowed: false;
  accounting_posted: false;
  external_write_allowed: false;
  approval_created: false;
  permit_created: false;
  snapshot_sha256: string;
};

type ErrorPayload = { detail?: string };

export function FormalFactsConsole() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "blocked" | "error">("loading");
  const [detail, setDetail] = useState<string | null>(null);

  const load = useCallback(() => {
    setState("loading");
    setDetail(null);
    fetchJson<Workspace | ErrorPayload>("/backend/v1/facts?store_ref=ozon-primary")
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          setWorkspace(null);
          setDetail("detail" in payload ? payload.detail ?? `API ${response.status}` : `API ${response.status}`);
          setState(response.status === 422 ? "blocked" : "error");
          return;
        }
        setWorkspace(payload as Workspace);
        setState("ready");
      })
      .catch((error: unknown) => {
        setWorkspace(null);
        setDetail(error instanceof Error ? error.message : "读取失败");
        setState("error");
      });
  }, []);

  useEffect(load, [load]);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p>FORMAL FACT AUTHORITY · READ ONLY</p>
          <h1>Formal Facts</h1>
          <span>只展示 exact tenant / entity / store / grant / Evidence scope 内的正式事实。</span>
        </div>
        <div className={styles.actions}>
          <Link href="/">返回经营台</Link>
          <button type="button" onClick={load}>刷新权威</button>
        </div>
      </header>

      <section className={styles.boundary}>
        <strong data-state={state}>{state}</strong>
        <span>legacy inferred · false</span>
        <span>Claim source · false</span>
        <span>accounting posted · false</span>
        <span>Approval / Permit · false / false</span>
        <b>external write · false</b>
      </section>

      {state === "loading" ? <section className={styles.notice}>running · 读取 PostgreSQL scoped projection</section> : null}
      {state === "blocked" ? (
        <section className={styles.blocked}>
          <p>BLOCKED BY AUTHORITY</p>
          <h2>当前主体不能建立 Formal Fact 视图</h2>
          <span>{detail}</span>
          <small>需要 current entity grant；页面不会回退到 legacy/global Fact，也不会推断主体。</small>
        </section>
      ) : null}
      {state === "error" ? <section className={styles.error}>error · {detail}</section> : null}

      {workspace ? (
        <>
          <section className={styles.scope}>
            <div><span>status</span><strong>{workspace.status}</strong></div>
            <div><span>formal facts</span><strong>{workspace.formal_fact_count}</strong></div>
            <div><span>tenant</span><code>{workspace.scope.tenant_ref}</code></div>
            <div><span>entity / store</span><code>{workspace.scope.entity_ref} / {workspace.scope.store_ref}</code></div>
            <div><span>snapshot</span><code>{workspace.snapshot_sha256.slice(0, 16)}…</code></div>
          </section>
          <section className={styles.facts}>
            <div className={styles.sectionHeading}>
              <div><p>POSTGRESQL PROJECTION</p><h2>{workspace.items.length ? "Evidence-bound Facts" : "No native Facts"}</h2></div>
              <span>{workspace.as_of}</span>
            </div>
            {workspace.items.length === 0 ? (
              <div className={styles.empty}>no_data · 没有把 legacy Fact 推断进当前租户。</div>
            ) : workspace.items.map((fact) => (
              <article key={fact.id}>
                <div><span>{fact.fact_type}</span><strong>{fact.natural_key}</strong><code>{fact.id}</code></div>
                <dl>
                  <div><dt>Product</dt><dd>{fact.product_id}</dd></div>
                  <div><dt>Evidence</dt><dd>{fact.evidence_id}</dd></div>
                  <div><dt>Effective</dt><dd>{fact.effective_at}</dd></div>
                  <div><dt>Resolution</dt><dd>{fact.resolution_status}</dd></div>
                </dl>
                <small>{fact.scope.source_evidence_sha256} · {fact.payload_hash}</small>
              </article>
            ))}
          </section>
        </>
      ) : null}
    </main>
  );
}
