"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./graph-console.module.css";

type Task = {
  id: string;
  title: string;
  owner: string;
  dependencies: string[];
  verification_condition: string;
  verifier: { id: string; version: string };
  state: string;
  freshness: string;
  blockers: string[];
  next_safe_action: string;
  workspace: string;
  observation_id: string | null;
  artifact_ref: string | null;
  evidence_ref: string | null;
};

type Node = {
  id: string;
  kind: string;
  stable_key: string;
  type: string;
  label: string;
  authority: string;
  source: string;
  version: string;
  content_sha256: string;
  artifact_ref: string | null;
  verification: {
    state: string;
    freshness: string;
    why: string;
    blockers: string[];
    owner: string | null;
    sla_seconds: number | null;
    dependencies: string[];
    verifier: { id: string; version: string } | null;
    observation_id: string | null;
    artifact_ref: string | null;
    evidence_ref: string | null;
    next_safe_action: string;
    workspace: string;
    binding_sha256: string;
  } | null;
};

type Edge = {
  id: string;
  kind: string;
  source: string;
  target: string;
  type: string;
  derivation: string;
  confidence: number;
  can_satisfy_gate: boolean;
  content_sha256: string;
};

type Workspace = {
  status: string;
  as_of: string;
  snapshot_sha256: string;
  project: {
    id: string;
    title: string;
    lifecycle: string;
    baseline_sha256: string;
  };
  scope: { tenant_ref: string; entity_ref: string | null; store_ref: string | null };
  counts: Record<string, number>;
  tasks: Task[];
  nodes: Node[];
  edges: Edge[];
  external_write_allowed: false;
  model_self_certification_allowed: false;
};

const projections = [
  ["project", "Project"],
  ["requirements", "Requirements"],
  ["engineering", "Engineering"],
  ["runtime", "Runtime"],
  ["evidence", "Evidence"],
  ["commerce", "Commerce"],
  ["authority", "Authority"],
] as const;

export function GraphConsole({
  graphKind,
  mode = "graph",
}: {
  graphKind?: string;
  mode?: "graph" | "control" | "todo";
}) {
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    const suffix = graphKind ? `/graphs/${graphKind}` : "";
    fetchJson<Workspace>(
      `/backend/v1/agent-control/projects/kjds-059-bas123${suffix}?store_ref=ozon-primary`,
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(`Graph API ${response.status}`);
        setData(await response.json());
      })
      .catch((value: unknown) => setError(value instanceof Error ? value.message : "读取失败"));
  }, [graphKind]);
  useEffect(load, [load]);

  const nodeById = useMemo(
    () => new Map((data?.nodes ?? []).map((node) => [node.id, node])),
    [data],
  );
  const title =
    mode === "control"
      ? "Agent Control"
      : mode === "todo"
        ? "Verifier-owned TODO"
        : `${graphKind ?? "Project"} Graph`;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p>EXTERNAL OBSERVATION · CANONICAL GRAPH</p>
          <h1>{title}</h1>
          <span>模型只报告；只有注册 Verifier 的 fresh observation 可以通过 TODO。</span>
        </div>
        <button type="button" onClick={load}>刷新观测</button>
      </header>
      <nav className={styles.nav} aria-label="Graph projections">
        <Link href="/agent-control">Control</Link>
        <Link href="/goal-todo">TODO</Link>
        <Link href="/authority-intake">Authority Intake</Link>
        {projections.map(([kind, label]) => (
          <Link key={kind} href={`/${kind}-graph`}>
            {label}
          </Link>
        ))}
      </nav>
      {error ? <section className={styles.error}>error · {error}</section> : null}
      {!data && !error ? <section className={styles.loading}>running · 读取外部观测</section> : null}
      {data ? (
        <>
          <section className={styles.boundary}>
            <strong>{data.project.title}</strong>
            <span>{data.scope.tenant_ref} / {data.scope.entity_ref ?? "no_data"} / {data.scope.store_ref}</span>
            <span>as_of {data.as_of}</span>
            <span>snapshot {data.snapshot_sha256.slice(0, 12)}…</span>
            <b>external write false</b>
          </section>
          <section className={styles.metrics} aria-label="server-derived counts">
            {["tasks", "passed", "failed", "blocked", "stale", "pending", "nodes", "verified_nodes", "edges"].map((key) => (
              <article key={key}><span>{key}</span><strong>{data.counts[key] ?? 0}</strong></article>
            ))}
          </section>
          {(mode === "control" || mode === "todo") ? (
            <section className={styles.tasks}>
              <div className={styles.sectionHeading}>
                <div><p>GOAL CONTRACT</p><h2>TODO 由 Verifier 判定</h2></div>
                <span>{data.tasks.length ? "fresh/stale 分离" : "no_data"}</span>
              </div>
              {data.tasks.map((task) => (
                <article key={task.id} data-state={task.state}>
                  <div className={styles.taskState}><span>{task.state}</span><b>{task.freshness}</b></div>
                  <div>
                    <h3>{task.title}</h3>
                    <p>{task.verification_condition}</p>
                    <small>{task.verifier.id}@{task.verifier.version} · {task.observation_id ?? "no observation"}</small>
                  </div>
                  <div>
                    <strong>下一安全动作</strong>
                    <p>{task.next_safe_action}</p>
                    {task.evidence_ref ? <code>{task.evidence_ref}</code> : null}
                  </div>
                </article>
              ))}
            </section>
          ) : (
            <section className={styles.graph}>
              <div className={styles.sectionHeading}>
                <div><p>{graphKind?.toUpperCase()} PROJECTION</p><h2>Stable nodes / causal edges</h2></div>
                <span>{data.nodes.length ? "ready" : "no_data"}</span>
              </div>
              <div className={styles.nodeGrid}>
                {data.nodes.map((node) => (
                  <article key={node.id} data-state={node.verification?.state ?? "unbound"}>
                    <span>{node.type} · {node.authority}</span>
                    <h3>{node.label}</h3>
                    <p>{node.stable_key}</p>
                    <code>{node.content_sha256.slice(0, 14)}…</code>
                    <small>{node.artifact_ref ?? node.source}</small>
                    {node.verification ? (
                      <div className={styles.nodeVerification}>
                        <b>{node.verification.state} · {node.verification.freshness}</b>
                        <p>{node.verification.why}</p>
                        <span>
                          owner {node.verification.owner ?? "missing"} ·{" "}
                          {node.verification.sla_seconds === null
                            ? "SLA not set"
                            : `SLA ${node.verification.sla_seconds}s`}
                        </span>
                        <small>
                          dependencies{" "}
                          {node.verification.dependencies.length
                            ? node.verification.dependencies.join(", ")
                            : "none"}
                        </small>
                        <strong>下一安全动作</strong>
                        <p>{node.verification.next_safe_action}</p>
                        <small>
                          verifier {node.verification.verifier?.id ?? "missing"}@
                          {node.verification.verifier?.version ?? "missing"} ·{" "}
                          {node.verification.observation_id ?? "no observation"}
                        </small>
                        {node.verification.artifact_ref ? (
                          <code>{node.verification.artifact_ref}</code>
                        ) : null}
                        {node.verification.evidence_ref ? (
                          <code>{node.verification.evidence_ref}</code>
                        ) : null}
                        <Link href={node.verification.workspace}>
                          打开 verifier / TODO
                        </Link>
                      </div>
                    ) : (
                      <div className={styles.nodeUnbound}>
                        canonical only · no verifier-owned runtime status
                      </div>
                    )}
                  </article>
                ))}
              </div>
              <div className={styles.edgeList}>
                {data.edges.map((edge) => (
                  <article key={edge.id} data-inferred={!edge.can_satisfy_gate}>
                    <strong>{nodeById.get(edge.source)?.label ?? edge.source}</strong>
                    <span>— {edge.type} / {edge.derivation} →</span>
                    <strong>{nodeById.get(edge.target)?.label ?? edge.target}</strong>
                    <small>{edge.can_satisfy_gate ? "Gate-eligible derivation" : "Exploration only · cannot satisfy Gate"}</small>
                  </article>
                ))}
              </div>
            </section>
          )}
        </>
      ) : null}
    </main>
  );
}
