"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./project-manager-console.module.css";

type WorkNode = {
  node_id: string;
  level: string;
  title: string;
  parent_id: string | null;
  owner: string;
  reviewer: string;
  dependencies: string[];
  acceptance_tests: string[];
  exact_write_set: string[];
  status: string;
  blocker_kind: string | null;
  rollback_ref: string | null;
  claim_level: string;
};

type TaskContract = {
  project_id: string;
  source_snapshot_sha256?: string;
  snapshot_sha256: string;
  projection_sha256: string;
  projection_only: true;
  ready_frontier: string[];
  critical_path: string[];
  minimum_blocker_set: Array<{ node_id: string; kind: string; status: string; blocking_dependencies: string[] }>;
  nodes: WorkNode[];
  validation: { valid: boolean; errors: string[]; warnings: string[] };
  external_write_allowed: false;
};

type OperatingSnapshot = {
  admission_state?: string;
  proof_state?: string;
  evidence_state?: string;
  operational_state?: string;
  economic_state?: string;
  rollback_available?: boolean;
  external_readback_passed?: boolean;
  snapshot_sha256?: string;
  observed_at?: string;
  external_write_allowed: false;
};

type HeartbeatReplay = {
  status: string;
  heartbeat: { status?: string; revision?: number; observed_at?: string } | null;
  operating_snapshot?: OperatingSnapshot | null;
  external_write_allowed: false;
};

type FrontierItem = {
  id: string;
  node_id?: string;
  label: string;
  state: string;
  status?: string;
  frontier_kind?: string;
  priority?: number;
  weight?: number;
  dependencies: string[];
  unresolved_dependencies?: string[];
  reasons?: string[];
  evidence_refs?: string[];
  external_write_allowed?: false;
};

type TaskBrief = {
  task_id: string;
  parent_id: string | null;
  scope: Record<string, unknown>;
  owner: string;
  reviewer: string;
  objective: string;
  business_context: string;
  allowed_scope: string[];
  prohibited_scope: string[];
  dependencies: string[];
  input_snapshot: Record<string, unknown>;
  exact_files_or_domain: string[];
  expected_outputs: string[];
  acceptance_tests: string[];
  budget: Record<string, unknown>;
  lease: Record<string, unknown>;
  deadline: string | null;
  risk_tier: string;
  rollback_ref: string | null;
  reporting_format: string[];
};

type DefinitionOfReady = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  snapshot_sha256?: string;
};

type NextWaveTask = {
  task_ref: string;
  title: string;
  priority?: number;
  weight?: number;
  dependencies: string[];
  unresolved_dependencies?: string[];
  next_safe_action?: string | null;
  dispatch_allowed: false;
  task_contract_status: string;
  work_breakdown?: {
    node_id?: string;
    level?: string;
    parent_id?: string | null;
    status?: string;
    claim_level?: string;
  } | null;
  task_brief: TaskBrief | null;
  definition_of_ready: DefinitionOfReady;
};

type NextWavePlan = {
  status: string;
  as_of?: string | null;
  frontier: FrontierItem[];
  tasks: NextWaveTask[];
  critical_path?: Array<{ target_id?: string; node_ids?: string[]; status?: string }>;
  blockers?: FrontierItem[];
  minimum_blocker_set?: FrontierItem[];
  task_contract?: {
    status?: string;
    projection_sha256?: string;
    validation?: { valid?: boolean; errors?: string[]; warnings?: string[] };
  };
  snapshot_sha256?: string;
  plan_sha256?: string;
  projection_sha256?: string;
  projection_only: true;
  dispatch_allowed: false;
  external_write_allowed: false;
};

type ConsoleData = {
  contract: TaskContract;
  replay: HeartbeatReplay;
  nextWave: NextWavePlan | null;
};

function queryScope(): { projectId: string; storeRef: string } {
  if (typeof window === "undefined") return { projectId: "kjds-059-bas123", storeRef: "ozon-primary" };
  const params = new URLSearchParams(window.location.search);
  return {
    projectId: params.get("project")?.trim() || "kjds-059-bas123",
    storeRef: params.get("store")?.trim() || "ozon-primary",
  };
}

export function ProjectManagerConsole() {
  const [scope, setScope] = useState(queryScope);
  const [data, setData] = useState<ConsoleData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nextWaveError, setNextWaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNextWaveError(null);
    const nextScope = queryScope();
    setScope(nextScope);
    const encodedProject = encodeURIComponent(nextScope.projectId);
    const encodedStore = encodeURIComponent(nextScope.storeRef);
    const [contractResponse, replayResponse, nextWaveResponse] = await Promise.all([
      fetchJson<TaskContract>(
        `/backend/v1/project-graph/${encodedProject}/task-contract?store_ref=${encodedStore}`,
      ),
      fetchJson<HeartbeatReplay>(
        `/backend/v1/project-graph/${encodedProject}/heartbeat/latest?store_ref=${encodedStore}`,
      ),
      fetchJson<NextWavePlan>(
        `/backend/v1/project-graph/${encodedProject}/next-wave?store_ref=${encodedStore}&max_tasks=8`,
      ),
    ]);
    if (!contractResponse.ok) {
      setError(`WBS contract unavailable (${contractResponse.status})`);
      setLoading(false);
      return;
    }
    if (!replayResponse.ok) {
      setError(`Heartbeat replay unavailable (${replayResponse.status})`);
      setLoading(false);
      return;
    }
    const contract = await contractResponse.json();
    const replay = await replayResponse.json();
    if (contract.external_write_allowed !== false || replay.external_write_allowed !== false) {
      setError("server contract did not prove read-only scope");
      setLoading(false);
      return;
    }
    let nextWave: NextWavePlan | null = null;
    if (!nextWaveResponse.ok) {
      setNextWaveError(`Next-wave projection unavailable (${nextWaveResponse.status})`);
    } else {
      const candidate = await nextWaveResponse.json();
      if (
        candidate.external_write_allowed !== false ||
        candidate.projection_only !== true ||
        candidate.dispatch_allowed !== false
      ) {
        setNextWaveError("next-wave contract did not prove read-only scope");
      } else {
        nextWave = candidate;
      }
    }
    setData({ contract, replay, nextWave });
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const taskNodes = useMemo(
    () => (data?.contract.nodes ?? []).filter((node) => node.level === "task"),
    [data],
  );
  const nextWaveTasks = data?.nextWave?.tasks ?? [];
  const snapshot = data?.replay.operating_snapshot ?? null;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>AI PROJECT MANAGER · READ-ONLY CONTROL TOWER</p>
          <h1>项目经理控制塔</h1>
          <span>从五级工作分解到心跳回放，所有状态都绑定服务端快照。</span>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "读取中…" : "刷新快照"}
        </button>
      </header>
      <section className={styles.scope} aria-label="当前范围">
        <b>{scope.projectId}</b>
        <span>store · {scope.storeRef}</span>
        <span>projection only</span>
        <strong>external write false</strong>
      </section>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {loading && !data ? <p className={styles.loading} role="status">正在读取项目合同与心跳回放…</p> : null}
      {data ? (
        <>
          <section className={styles.metrics} aria-label="控制塔指标">
            <Metric label="合同" value={data.contract.validation.valid ? "VALID" : "BLOCKED"} />
            <Metric label="可调度前沿" value={String(data.contract.ready_frontier.length)} />
            <Metric label="关键路径" value={String(data.contract.critical_path.length)} />
            <Metric label="最小阻塞集" value={String(data.contract.minimum_blocker_set.length)} />
            <Metric label="心跳回放" value={data.replay.status} />
            <Metric label="Admission" value={snapshot?.admission_state ?? "NO_DATA"} />
          </section>
          <section className={styles.gates} aria-label="四状态门禁">
            <div className={styles.sectionHeading}><div><p className={styles.kicker}>OPERATING SNAPSHOT</p><h2>四状态与经济护栏</h2></div><code>{snapshot?.snapshot_sha256?.slice(0, 14) ?? "no snapshot"}…</code></div>
            <div className={styles.gateGrid}>
              <Gate label="Proof" value={snapshot?.proof_state ?? "NO_DATA"} />
              <Gate label="Evidence" value={snapshot?.evidence_state ?? "NO_DATA"} />
              <Gate label="Operational" value={snapshot?.operational_state ?? "UNKNOWN"} />
              <Gate label="Economic" value={snapshot?.economic_state ?? "UNKNOWN"} />
            </div>
            <p className={styles.guardLine}>
              rollback · {snapshot?.rollback_available ? "available" : "blocked"} · readback · {snapshot?.external_readback_passed ? "passed" : "blocked"}
            </p>
          </section>
          <section className={styles.work}>
            <div className={styles.sectionHeading}><div><p className={styles.kicker}>INITIATIVE → PROGRAM → EPIC → SLICE → TASK</p><h2>可验收工作包</h2></div><span>{taskNodes.length} tasks</span></div>
            <div className={styles.taskList}>
              {taskNodes.map((node) => (
                <article key={node.node_id} className={styles.task} data-state={node.status}>
                  <div><b>{node.status}</b><small>{node.claim_level}</small></div>
                  <div><h3>{node.title}</h3><p>{node.node_id}</p><small>owner {node.owner || "missing"} · reviewer {node.reviewer || "missing"}</small></div>
                  <div><strong>验收</strong><p>{node.acceptance_tests.length ? node.acceptance_tests.join(" · ") : "missing"}</p><small>写域 {node.exact_write_set.length ? node.exact_write_set.join(" · ") : "missing"}</small></div>
                </article>
              ))}
              {!taskNodes.length ? <p className={styles.empty}>NO_DATA · 当前快照没有任务节点</p> : null}
            </div>
          </section>
          <section className={styles.nextWave} aria-label="下一波任务候选">
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.kicker}>NEXT WAVE · PROJECTION ONLY</p>
                <h2>下一波任务候选</h2>
              </div>
              <span>{data.nextWave ? `${nextWaveTasks.length} tasks` : "NO_DATA"}</span>
            </div>
            <p className={styles.readOnlyNote}>
              这里是服务端根据图谱和任务契约计算的候选波次；页面不会派发 Agent、获取租约或写入 Ozon。
            </p>
            {nextWaveError ? <p className={styles.inlineError} role="status">{nextWaveError}</p> : null}
            {data.nextWave ? (
              <div className={styles.frontierList}>
                {nextWaveTasks.map((task) => {
                  const brief = task.task_brief;
                  const dor = task.definition_of_ready;
                  const unresolved = task.unresolved_dependencies ?? [];
                  return (
                    <article key={task.task_ref} className={styles.frontierCard} data-state={task.task_contract_status}>
                      <div className={styles.frontierMeta}>
                        <span>{task.task_contract_status}</span>
                        <b>{dor.valid ? "DOR_READY" : "DOR_BLOCKED"}</b>
                      </div>
                      <div>
                        <h3>{task.title}</h3>
                        <p>{task.task_ref}</p>
                        <small>
                          priority {task.priority ?? 0} · weight {task.weight ?? 0} ·
                          {unresolved.length ? ` unresolved ${unresolved.join(", ")}` : " dependencies clear"}
                        </small>
                        {brief ? <small>{brief.objective}</small> : <small>TaskBrief：NO_DATA</small>}
                      </div>
                      <div className={styles.frontierContract}>
                        <strong>TaskBrief / DoR</strong>
                        {brief ? (
                          <small>
                            owner {brief.owner || "missing"} · reviewer {brief.reviewer || "missing"} · risk {brief.risk_tier}
                          </small>
                        ) : (
                          <small>任务契约不可用，需先补齐五级 WBS</small>
                        )}
                        {brief?.exact_files_or_domain.length ? (
                          <small>写域 {brief.exact_files_or_domain.join(" · ")}</small>
                        ) : (
                          <small>写域：NO_DATA</small>
                        )}
                        <small>{dor.valid ? "DoR 通过" : `DoR 阻塞：${dor.errors.join(" · ") || "缺少验收条件"}`}</small>
                        {dor.warnings.length ? <small>警告 {dor.warnings.join(" · ")}</small> : null}
                        <small>dispatch_allowed=false · 仅供评审</small>
                      </div>
                    </article>
                  );
                })}
                {!nextWaveTasks.length ? (
                  <p className={styles.empty}>
                    NO_DATA · 当前没有满足依赖和 WIP 门禁的下一波任务（前沿 {data.nextWave.frontier.length} 项）
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>
          <section className={styles.columns}>
            <Panel title="Ready frontier" items={data.contract.ready_frontier} />
            <Panel title="Critical path" items={data.contract.critical_path} />
            <Panel title="Blockers" items={data.contract.minimum_blocker_set.map((item) => `${item.node_id} · ${item.kind} · ${item.status}`)} />
          </section>
        </>
      ) : null}
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <article className={styles.metric}><span>{label}</span><strong>{value}</strong></article>;
}

function Gate({ label, value }: { label: string; value: string }) {
  return <div className={styles.gate} data-state={value}><span>{label}</span><b>{value}</b></div>;
}

function Panel({ title, items }: { title: string; items: string[] }) {
  return <article className={styles.panel}><h3>{title}</h3>{items.length ? <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p>NO_DATA</p>}</article>;
}
