"use client";

import { ArrowLeft, BadgeCheck, CircleAlert, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { nativeParityView, stateLabel, type NativeParityViewState } from "../../lib/native-parity-state";
import type {
  AcceptanceItem,
  AcceptanceRecord,
  AcceptanceState,
  NativeParityWorkspace,
} from "./contracts";
import styles from "./native-parity.module.css";

const states: AcceptanceState[] = [
  "mapped", "implemented_unverified", "gated", "verified_native", "blocked", "stale",
];

const dimensions: AcceptanceRecord["dimension"][] = [
  "code", "migration", "api_openapi", "web", "permission_write_path",
  "runtime_replay", "immutable_evidence", "external_graph_verifier",
];

function shortHash(value: string | null | undefined) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";
}

function AcceptanceCard({ item }: { item: AcceptanceItem }) {
  const byDimension = new Map(item.records.map((record) => [record.dimension, record]));
  return (
    <article className={styles.card} data-state={item.state} data-testid="native-parity-row">
      <header>
        <div><span>{item.scope.provider_id}</span><h2>{item.scope.capability_id}</h2><small>version {item.scope.capability_version}</small></div>
        <strong>{stateLabel(item.state)}</strong>
      </header>
      <div className={styles.dimensions}>
        {dimensions.map((dimension) => {
          const record = byDimension.get(dimension);
          const state = item.missing_dimensions.includes(dimension)
            ? "missing"
            : item.stale_dimensions.includes(dimension)
              ? "stale"
              : record?.status ?? "missing";
          return <div key={dimension} data-check={state}><span>{dimension}</span><b>{state}</b><small>{record?.verifier_id ?? "verifier no_data"}</small></div>;
        })}
      </div>
      {(item.source_gaps.length || item.acceptance_artifact.blockers.length) ? (
        <section className={styles.blockers}><CircleAlert size={17} /><div>
          {[...item.acceptance_artifact.blockers, ...item.source_gaps].map((value) => <code key={value}>{value}</code>)}
        </div></section>
      ) : null}
      <footer>
        <span>input <code>{shortHash(item.acceptance_artifact.input_sha256)}</code></span>
        <span>artifact <code>{shortHash(item.acceptance_artifact.artifact_sha256)}</code></span>
        <span>snapshot <code>{shortHash(item.snapshot_sha256)}</code></span>
      </footer>
    </article>
  );
}

export function NativeParityConsole() {
  const [workspace, setWorkspace] = useState<NativeParityWorkspace | null>(null);
  const [viewState, setViewState] = useState<NativeParityViewState>("loading");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({ store: "ozon-primary", provider: "", capability: "", version: "", status: "" });
  const [filters, setFilters] = useState(draft);

  const load = useCallback(async (cursor?: string | null, signal?: AbortSignal, frozenAsOf?: string) => {
    setViewState("loading"); setError("");
    try {
      const params = new URLSearchParams({ store_ref: filters.store, page_size: "50" });
      if (filters.provider) params.set("provider_id", filters.provider);
      if (filters.capability) params.set("capability_id", filters.capability);
      if (filters.version) params.set("capability_version", filters.version);
      if (filters.status) params.set("status", filters.status);
      if (cursor) {
        params.set("cursor", cursor);
        // The opaque cursor is bound to the first page's frozen cutoff.
        // Reusing that server-returned instant prevents a second request from
        // silently projecting a different ledger snapshot.
        if (frozenAsOf) params.set("as_of", frozenAsOf);
      }
      const response = await fetch(`/backend/v1/native-parity-acceptance/workspace?${params}`, { cache: "no-store", signal });
      if (!response.ok) throw new Error(`Native parity API ${response.status}`);
      const value = await response.json() as NativeParityWorkspace;
      setWorkspace((current) => cursor && current ? { ...value, items: [...current.items, ...value.items] } : value);
      setViewState(value.status);
    } catch (value) {
      if (value instanceof DOMException && value.name === "AbortError") return;
      setError(value instanceof Error ? value.message : "读取失败"); setViewState("error");
    }
  }, [filters]);

  useEffect(() => { const controller = new AbortController(); void load(null, controller.signal); return () => controller.abort(); }, [load]);
  const filtered = Boolean(filters.provider || filters.capability || filters.version || filters.status);
  const view = nativeParityView(viewState, workspace?.items.length ?? 0, filtered);
  const apply = (event: FormEvent) => { event.preventDefault(); setFilters(draft); };

  return <main className={styles.page}>
    <nav><Link href="/commerce-os"><ArrowLeft size={16} />Commerce OS</Link><span><ShieldCheck size={17} />VERIFIER-OWNED · READ ONLY</span></nav>
    <header className={styles.hero}><div><small>BAS-159 · CAPABILITY-GRANULAR ACCEPTANCE</small><h1>原生同等能力<br /><em>验收权威</em></h1><p>映射不是实现，工程完成不是原生验证。每个 provider / capability / version 必须分别通过八维外部观测。</p></div><aside><BadgeCheck size={24} /><strong>客户端不得重算或晋升</strong><span>external_write_allowed=false</span><span>self_certification_allowed=false</span></aside></header>
    <form className={styles.filters} onSubmit={apply}>
      <label>Store<input value={draft.store} onChange={(e) => setDraft({ ...draft, store: e.target.value })} /></label>
      <label>Provider<input value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value })} placeholder="dianxiaomi_erp" /></label>
      <label>Capability<input value={draft.capability} onChange={(e) => setDraft({ ...draft, capability: e.target.value })} placeholder="listing_management" /></label>
      <label>Version<input value={draft.version} onChange={(e) => setDraft({ ...draft, version: e.target.value })} placeholder="1" /></label>
      <label>Status<select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}><option value="">全部</option>{states.map((state) => <option key={state}>{state}</option>)}</select></label>
      <button type="submit">应用筛选</button>
    </form>
    {view === "loading" ? <section className={styles.notice}><RefreshCw />正在读取 verifier ledger…</section> : null}
    {view === "error" ? <section className={styles.error}><CircleAlert /><div><strong>读取失败</strong><p>{error}</p></div><button onClick={() => void load()}>重试</button></section> : null}
    {workspace ? <>
      <section className={styles.scope}><div><span>tenant</span><b>{workspace.scope.tenant_ref}</b></div><div><span>entity</span><b>{workspace.scope.entity_ref ?? "no_data"}</b></div><div><span>store</span><b>{workspace.scope.store_ref}</b></div><div><span>authority</span><code>{shortHash(workspace.scope.authority_sha256)}</code></div><div><span>snapshot</span><code>{shortHash(workspace.snapshot_sha256)}</code></div></section>
      <section className={styles.metrics}>{states.map((state) => <article key={state}><span>{state}</span><strong>{workspace.counts.states[state] ?? 0}</strong></article>)}</section>
      {view === "no_data" || view === "filtered_empty" ? <section className={styles.empty}><CircleAlert /><div><strong>{view === "filtered_empty" ? "筛选结果为空" : "真实 no_data"}</strong><p>没有满足 exact scope 和 verifier 合同的 capability acceptance；不会显示虚假覆盖。</p></div></section> : null}
      <section className={styles.list}>{workspace.items.map((item) => <AcceptanceCard key={`${item.scope.provider_id}:${item.scope.capability_id}:${item.scope.capability_version}`} item={item} />)}</section>
      {workspace.next_cursor ? <button className={styles.more} onClick={() => void load(workspace.next_cursor, undefined, workspace.as_of)}>加载下一页</button> : null}
      <section className={styles.audit}><strong>Authority boundary</strong><code>read_only=true</code><code>client_can_recalculate_or_promote=false</code><code>self_certification_allowed=false</code><code>external_write_allowed=false</code></section>
    </> : null}
  </main>;
}
