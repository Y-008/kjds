"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  authorityStateView,
  transitionAuthorityState,
  type AuthorityStatus,
} from "../../lib/authority-state-model";
import styles from "./growth-experiment.module.css";

type Status = Exclude<AuthorityStatus, "loading" | "error">;
type Workspace = {
  status: Status;
  counts: { total: number; ready: number; partial: number; blocked: number };
  experiments: Array<{
    product: { id: string; sku: string; name: string };
    actions: Record<string, { status: string; shadow_experiment_allowed: boolean }>;
    status: string;
    next: string;
  }>;
  source_gaps: string[];
  snapshot_sha256: string;
  agent_artifact: {
    artifact_sha256: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    legacy_marketplace_growth_used: false;
    price_changed: false;
    promotion_created: false;
    advertising_spend_created: false;
    private_erp_interface_allowed: false;
    external_write_allowed: false;
  };
};

export function GrowthExperimentConsole() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [state, setState] = useState<AuthorityStatus>("loading");
  const [action, setAction] = useState("");

  const load = useCallback(async () => {
    setState((current) => transitionAuthorityState(current, { type: "request" }));
    try {
      const params = new URLSearchParams({ store_ref: "ozon-primary", page_size: "25" });
      if (action) params.set("action", action);
      const response = await fetch(`/backend/v1/growth-experiments/workspace?${params}`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Growth API ${response.status}`);
      const value = (await response.json()) as Workspace;
      setWorkspace(value);
      setState((current) => transitionAuthorityState(current, { type: "success", status: value.status }));
    } catch {
      setState((current) => transitionAuthorityState(current, { type: "failure" }));
    }
  }, [action]);

  useEffect(() => { void load(); }, [load]);
  const view = authorityStateView(state, Boolean(workspace?.experiments.length));

  return (
    <main className={styles.shell}>
      <header className={styles.hero}>
        <div>
          <Link href="/commerce-os">← Commerce OS</Link>
          <p>Native exact-scope · shadow only</p>
          <h1>增长实验权威工作台</h1>
          <span>价格、促销、广告 readiness 只由服务端投影，不在浏览器重算。</span>
        </div>
        <strong data-state={state}>{state}</strong>
      </header>
      <nav className={styles.nav}>
        <Link href="/pim">PIM</Link><Link href="/listings">Listings</Link>
        <Link href="/inventory">Inventory</Link><Link href="/profit-ledger">Actual CM3</Link>
        <Link href="/customer-service">Customer Service</Link>
      </nav>
      <section className={styles.controls}>
        <label>动作
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="">全部</option><option value="price">调价</option>
            <option value="promotion">促销</option><option value="advertising">广告</option>
          </select>
        </label>
        <button onClick={() => void load()}>刷新 exact-scope 权威</button>
      </section>
      {view.showLoading && <section className={styles.card}>loading</section>}
      {view.showRetry && <section className={styles.card}>error · 读取失败 <button onClick={() => void load()}>重试</button></section>}
      {workspace && state !== "loading" && state !== "error" && (
        <>
          <section className={styles.metrics}>
            {Object.entries(workspace.counts).map(([key, value]) => (
              <article key={key}><span>{key}</span><strong>{value}</strong></article>
            ))}
          </section>
          {workspace.experiments.length === 0 ? (
            <section className={styles.card}>
              <h2>{view.heading}</h2>
              <p>没有生成合成市场数据、利润、评价、Approval 或 Permit。</p>
              <ul>{workspace.source_gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
            </section>
          ) : workspace.experiments.map((item) => (
            <article className={styles.card} key={item.product.id}>
              <h2>{item.product.sku} · {item.product.name}</h2>
              <div className={styles.actions}>
                {Object.entries(item.actions).map(([name, value]) => (
                  <div key={name}><strong>{name}</strong><span>{value.status}</span><small>shadow {String(value.shadow_experiment_allowed)}</small></div>
                ))}
              </div>
              <p>{item.next}</p>
            </article>
          ))}
          <footer className={styles.audit}>
            <code>snapshot {workspace.snapshot_sha256}</code>
            <code>artifact {workspace.agent_artifact.artifact_sha256}</code>
            <p>price_changed=false · promotion_created=false · advertising_spend_created=false · self_approval_allowed=false · permit_issue_allowed=false · private_erp_interface_allowed=false · external_write_allowed=false</p>
          </footer>
        </>
      )}
    </main>
  );
}
