"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  authorityStateView,
  transitionAuthorityState,
  type AuthorityStatus,
} from "../../lib/authority-state-model";
import styles from "./delivery-exception.module.css";

type Status = Exclude<AuthorityStatus, "loading" | "error">;
type Workspace = {
  status: Status;
  counts: Record<string, number>;
  shipments: Array<{
    delivery_case_id: string;
    shipment_id: string | null;
    order_external_id: string;
    product: { id: string; sku: string };
    state: string;
    owner: string;
    sla: string;
    next: string;
  }>;
  source_gaps: string[];
  snapshot_sha256: string;
  agent_artifact: { artifact_sha256: string };
};

export function DeliveryExceptionConsole() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [state, setState] = useState<AuthorityStatus>("loading");
  const [filter, setFilter] = useState("");
  const load = useCallback(async () => {
    setState((current) => transitionAuthorityState(current, { type: "request" }));
    try {
      const params = new URLSearchParams({ store_ref: "ozon-primary", page_size: "25" });
      if (filter) params.set("state", filter);
      const response = await fetch(`/backend/v1/delivery-exceptions/workspace?${params}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Delivery API ${response.status}`);
      const value = (await response.json()) as Workspace;
      setWorkspace(value); setState((current) => transitionAuthorityState(current, { type: "success", status: value.status }));
    } catch { setState((current) => transitionAuthorityState(current, { type: "failure" })); }
  }, [filter]);
  useEffect(() => { void load(); }, [load]);
  const view = authorityStateView(state, Boolean(workspace?.shipments.length));
  return (
    <main className={styles.shell}>
      <header className={styles.hero}>
        <div><Link href="/commerce-os">← Commerce OS</Link><p>Native exact-scope · readback first</p><h1>物流交付与异常工作台</h1><span>Order、Tracking Evidence、库存、退货、客服和费用影响由服务端统一投影。</span></div>
        <strong data-state={state}>{state}</strong>
      </header>
      <nav className={styles.nav}><Link href="/oms">OMS</Link><Link href="/inventory">Inventory</Link><Link href="/warehouse-fulfillment">Warehouse Fulfillment</Link><Link href="/procurement">Procurement</Link><Link href="/returns">Returns</Link><Link href="/customer-service">Customer Service</Link></nav>
      <section className={styles.controls}><label>状态<select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="">全部</option>{["pick_pack","handover","transit","delivery","exception","return","blocked"].map((item) => <option key={item}>{item}</option>)}</select></label><button onClick={() => void load()}>重试 / 刷新权威</button></section>
      {view.showLoading && <section className={styles.card}>loading</section>}
      {view.showRetry && <section className={styles.card}>error · 读取失败 <button onClick={() => void load()}>重试</button></section>}
      {workspace && state !== "loading" && state !== "error" && <>
        <section className={styles.metrics}>{Object.entries(workspace.counts).map(([key,value]) => <article key={key}><span>{key}</span><strong>{value}</strong></article>)}</section>
        {workspace.shipments.length === 0 ? <section className={styles.card}><h2>{view.heading}</h2><p>没有用库存模板、报价或网页轨迹生成 Shipment。</p><ul>{workspace.source_gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></section> : workspace.shipments.map((item) => <article className={styles.card} key={item.delivery_case_id}><h2>{item.order_external_id} · {item.product.sku}</h2><p>{item.shipment_id ? `Shipment ${item.shipment_id}` : "正式 Shipment Readback 缺失"} · {item.state} · {item.owner} · {item.sla}</p><strong>Next: {item.next}</strong></article>)}
        <footer className={styles.audit}><code>snapshot {workspace.snapshot_sha256}</code><code>artifact {workspace.agent_artifact.artifact_sha256}</code><p>shipment_created=false · inventory_modified=false · order_modified=false · return_modified=false · carrier_contact_allowed=false · customer_contact_allowed=false · self_approval_allowed=false · permit_issue_allowed=false · private_erp_interface_allowed=false · external_write_allowed=false</p></footer>
      </>}
    </main>
  );
}
