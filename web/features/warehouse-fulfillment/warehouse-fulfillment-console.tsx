"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  transitionWarehouseState,
  warehouseView,
  type WarehouseStatus,
} from "../../lib/warehouse-fulfillment-state";
import styles from "./warehouse-fulfillment.module.css";

type Status = Exclude<WarehouseStatus, "loading" | "error">;
type FulfillmentItem = {
  order_external_id: string;
  product: { product_id: string; sku: string };
  state: string;
  latest_effective_at: string;
  location_refs: string[];
  bin_refs: string[];
  lot_refs: string[];
  wave_refs: string[];
  parcel_refs: string[];
  label_refs: string[];
  reservation_quantity: number;
  picked_quantity: number;
  packed_quantity: number;
  measured_weight_kg: string | null;
  owner: string;
  sla: string;
  next: string;
};
type Workspace = {
  status: Status;
  scope: { warehouse_ref: string; entity_ref: string | null };
  counts: Record<string, number>;
  fulfillment_items: FulfillmentItem[];
  source_gaps: string[];
  pagination: { next_cursor: string | null };
  snapshot_sha256: string;
  agent_artifact: { artifact_sha256: string };
};

export function WarehouseFulfillmentConsole() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [status, setStatus] = useState<WarehouseStatus>("loading");
  const [warehouseRef, setWarehouseRef] = useState("warehouse-cn-1");
  const [stateFilter, setStateFilter] = useState("");

  const load = useCallback(async () => {
    setStatus((current) =>
      transitionWarehouseState(current, { type: "request" }),
    );
    try {
      const params = new URLSearchParams({
        store_ref: "ozon-primary",
        warehouse_ref: warehouseRef,
        page_size: "25",
      });
      if (stateFilter) params.set("state", stateFilter);
      const response = await fetch(
        `/backend/v1/warehouse-fulfillment/workspace?${params}`,
        { cache: "no-store" },
      );
      if (!response.ok) {
        throw new Error(`Warehouse API ${response.status}`);
      }
      const value = (await response.json()) as Workspace;
      setWorkspace(value);
      setStatus((current) =>
        transitionWarehouseState(current, {
          type: "success",
          status: value.status,
        }),
      );
    } catch {
      setStatus((current) =>
        transitionWarehouseState(current, { type: "failure" }),
      );
    }
  }, [stateFilter, warehouseRef]);

  useEffect(() => {
    void load();
  }, [load]);
  const view = warehouseView(
    status,
    workspace?.fulfillment_items.length ?? 0,
  );

  return (
    <main className={styles.shell} data-authority-state={view.domState}>
      <header className={styles.hero}>
        <div>
          <Link href="/commerce-os">← Commerce OS</Link>
          <p>Native exact-scope · append-only warehouse authority</p>
          <h1>仓库执行与包裹交接权威</h1>
          <span>
            location、bin、lot、reservation、wave、pick、pack、parcel、weight
            与 handoff 均由服务端验证，不在浏览器重算。
          </span>
        </div>
        <strong data-state={status}>{status}</strong>
      </header>
      <nav className={styles.nav} aria-label="相邻原生工作台">
        <Link href="/oms">OMS</Link>
        <Link href="/inventory">Inventory</Link>
        <Link href="/procurement">Procurement / Receiving</Link>
        <Link href="/delivery-exceptions">Delivery</Link>
        <Link href="/returns">Returns</Link>
        <Link href="/customer-service">Customer Service</Link>
        <Link href="/evidenceops">EvidenceOps</Link>
      </nav>
      <section className={styles.controls}>
        <label>
          仓库
          <input
            value={warehouseRef}
            onChange={(event) => setWarehouseRef(event.target.value)}
          />
        </label>
        <label>
          状态
          <select
            value={stateFilter}
            onChange={(event) => setStateFilter(event.target.value)}
          >
            <option value="">全部</option>
            {[
              "unstarted",
              "reserved",
              "picking",
              "packing",
              "parcel_ready",
              "handoff_ready",
              "handed_over",
              "exception",
              "blocked",
            ].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <button onClick={() => void load()}>重试 / 刷新权威</button>
      </section>
      {view.showLoading ? (
        <section className={styles.card} data-testid="warehouse-loading">
          loading
        </section>
      ) : null}
      {view.showRetry ? (
        <section className={styles.card} data-testid="warehouse-error">
          error · 读取失败
          <button onClick={() => void load()}>重试</button>
        </section>
      ) : null}
      {workspace && status !== "loading" && status !== "error" ? (
        <>
          <section className={styles.metrics}>
            {Object.entries(workspace.counts).map(([key, value]) => (
              <article key={key}>
                <span>{key}</span>
                <strong>{value}</strong>
              </article>
            ))}
          </section>
          {workspace.fulfillment_items.length === 0 ? (
            <section
              className={styles.card}
              data-testid={`warehouse-${status}`}
            >
              <h2>{view.heading}</h2>
              <p>{view.emptyMessage}</p>
              <ul>
                {workspace.source_gaps.map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            </section>
          ) : (
            workspace.fulfillment_items.map((item) => (
              <article
                className={styles.card}
                key={item.order_external_id}
                data-testid="warehouse-ready-row"
              >
                <header className={styles.rowHeader}>
                  <div>
                    <p>{item.product.sku}</p>
                    <h2>{item.order_external_id}</h2>
                  </div>
                  <strong>{item.state}</strong>
                </header>
                <div className={styles.quantities}>
                  <span>reserved {item.reservation_quantity}</span>
                  <span>picked {item.picked_quantity}</span>
                  <span>packed {item.packed_quantity}</span>
                  <span>weight {item.measured_weight_kg ?? "pending"}</span>
                </div>
                <dl>
                  <div><dt>bin</dt><dd>{item.bin_refs.join(", ") || "—"}</dd></div>
                  <div><dt>lot</dt><dd>{item.lot_refs.join(", ") || "—"}</dd></div>
                  <div><dt>wave</dt><dd>{item.wave_refs.join(", ") || "—"}</dd></div>
                  <div><dt>parcel</dt><dd>{item.parcel_refs.join(", ") || "—"}</dd></div>
                  <div><dt>label</dt><dd>{item.label_refs.join(", ") || "—"}</dd></div>
                </dl>
                <p>{item.owner} · {item.sla}</p>
                <strong>Next: {item.next}</strong>
              </article>
            ))
          )}
          <footer className={styles.audit}>
            <code>snapshot {workspace.snapshot_sha256}</code>
            <code>artifact {workspace.agent_artifact.artifact_sha256}</code>
            <p>
              inventory_adjustment_allowed=false ·
              outbound_confirmation_allowed=false · label_purchase_allowed=false
              · carrier_handoff_allowed=false · self_approval_allowed=false ·
              permit_issue_allowed=false · carrier_contact_allowed=false ·
              customer_contact_allowed=false · fictional_authority_allowed=false
              · private_erp_interface_allowed=false · external_write_allowed=false
            </p>
          </footer>
        </>
      ) : null}
    </main>
  );
}
