"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Boxes,
  CheckCircle2,
  CircleDashed,
  Database,
  ExternalLink,
  Fingerprint,
  GitBranch,
  Layers3,
  Link2,
  LockKeyhole,
  RefreshCw,
  Route,
  ShieldCheck,
  Target,
  UserRoundCheck,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import type { WebSession } from "../dashboard/contracts";
import type {
  OperatingWorkspaceSnapshot,
  OperatingWorkspaceStage,
  RuntimeStatus,
  WorkspaceLink,
} from "./contracts";
import styles from "./operating-workspace.module.css";

type Props = { kind: string; itemId: string };

const kindMeta = {
  points: { label: "POINT · 原子功能", icon: Boxes },
  lines: { label: "LINE · 端到端价值流", icon: Route },
  surfaces: { label: "SURFACE · 经营控制面", icon: Layers3 },
} as const;

const runtimeLabel: Record<RuntimeStatus, string> = {
  verified: "真实已验证",
  in_progress: "真实进行中",
  blocked: "真实阻断",
  no_data: "无运行真源",
  contract_only: "仅有能力合同",
};

const contractLabel = {
  implemented: "能力已实现",
  ready: "能力已设计",
  gated: "能力受门禁",
  research_only: "仅研究",
};

function shortHash(value: string | null | undefined) {
  if (!value) return "—";
  return `${value.slice(0, 8)}…${value.slice(-8)}`;
}

function readableKey(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function readableValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "YES" : "NO";
  if (Array.isArray(value)) return value.map(readableValue).join(" · ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function ListBlock({
  label,
  values,
  empty = "尚无服务端事实",
}: {
  label: string;
  values: string[];
  empty?: string;
}) {
  return (
    <section className={styles.listBlock}>
      <span>{label}</span>
      <div>
        {values.length ? values.map((value) => <small key={value}>{value}</small>) : <em>{empty}</em>}
      </div>
    </section>
  );
}

function StageDetail({ stage }: { stage: OperatingWorkspaceStage }) {
  return (
    <article className={styles.stageDetail}>
      <header>
        <div>
          <span>STAGE {String(stage.sequence).padStart(2, "0")} · {stage.operation_kind}</span>
          <h2>{stage.label}</h2>
          <p>{stage.objective}</p>
        </div>
        <div className={styles.statusStack}>
          <b className={styles[stage.contract_status]}>{contractLabel[stage.contract_status]}</b>
          <b className={styles[stage.runtime_status]}>{runtimeLabel[stage.runtime_status]}</b>
        </div>
      </header>

      <div className={styles.stageFacts}>
        <article><small>业务对象</small><strong>{stage.business_object}</strong></article>
        <article><small>当前 / 目标</small><strong>{stage.current ?? "—"} / {stage.target ?? "—"}</strong></article>
        <article><small>进度</small><strong>{stage.progress_percent ?? "—"}{stage.progress_percent === null ? "" : "%"}</strong></article>
        <article><small>SLO / SLA</small><strong>{stage.sla}</strong></article>
      </div>

      <section className={styles.nextAction}>
        <Target size={18} />
        <div><span>服务端下一动作</span><strong>{stage.next_action}</strong></div>
        <Link href={stage.domain_href}>进入领域工作区 <ArrowRight size={14} /></Link>
      </section>

      <div className={styles.truthGrid}>
        <section className={styles.truthPanel}>
          <header><Database size={16} /><span>真实事实</span></header>
          {stage.facts.length ? stage.facts.map((fact) => <p key={fact}><CheckCircle2 size={13} />{fact}</p>) : (
            <p className={styles.unknown}><CircleDashed size={13} />没有与该原子点精确匹配的运行事实</p>
          )}
        </section>
        <section className={styles.truthPanel}>
          <header><Fingerprint size={16} /><span>Evidence</span></header>
          {stage.evidence_ids.length ? stage.evidence_ids.map((id) => <code key={id}>{id}</code>) : (
            <p className={styles.unknown}><AlertTriangle size={13} />Evidence 缺口保持可见，页面不会补造</p>
          )}
        </section>
      </div>

      <div className={styles.contractGrid}>
        <ListBlock label="输入合同" values={stage.input_contract} />
        <ListBlock label="输出合同" values={stage.output_contract} />
        <ListBlock label="失败模式" values={stage.failure_modes} />
        <ListBlock label="经营 KPI" values={stage.kpi} />
      </div>

      <div className={styles.governanceGrid}>
        <article><ShieldCheck size={16} /><div><span>Evidence 门</span><p>{stage.evidence_gate}</p></div></article>
        <article><AlertTriangle size={16} /><div><span>失败队列</span><p>{stage.failure_queue}</p></div></article>
        <article><Activity size={16} /><div><span>独立回读</span><p>{stage.readback}</p></div></article>
        <article><UserRoundCheck size={16} /><div><span>责任 / 复核</span><p>{stage.owner} / {stage.reviewer}</p></div></article>
      </div>
    </article>
  );
}

function RelatedLinks({ label, links }: { label: string; links: WorkspaceLink[] }) {
  if (!links.length) return null;
  return (
    <section className={styles.relatedGroup}>
      <span>{label}</span>
      <div>{links.map((item) => <Link href={item.href} key={item.id}>{item.label}<ArrowRight size={12} /></Link>)}</div>
    </section>
  );
}

export function OperatingWorkspace({ kind, itemId }: Props) {
  const [session, setSession] = useState<WebSession | null>(null);
  const [snapshot, setSnapshot] = useState<OperatingWorkspaceSnapshot | null>(null);
  const [selectedStageId, setSelectedStageId] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    setError("");
    const sessionResponse = await fetchJson<WebSession | { detail?: string }>("/auth/session", {
      cache: "no-store",
      signal,
    });
    if (sessionResponse.status === 401) return window.location.assign("/login");
    if (sessionResponse.status === 428) return window.location.assign("/mfa");
    const sessionBody = await sessionResponse.json();
    if (!sessionResponse.ok) {
      setError("detail" in sessionBody && sessionBody.detail ? sessionBody.detail : "Web 身份服务尚未就绪");
      setBusy(false);
      return;
    }
    setSession(sessionBody as WebSession);

    const response = await fetchJson<OperatingWorkspaceSnapshot | { detail?: string }>(
      `/backend/v1/operating-workspaces/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}?store_ref=ozon-primary`,
      { cache: "no-store", signal },
    );
    const body = await response.json();
    if (!response.ok) {
      setError("detail" in body && body.detail ? body.detail : "工作区不存在或服务端快照不可用");
      setBusy(false);
      return;
    }
    const next = body as OperatingWorkspaceSnapshot;
    setSnapshot(next);
    setSelectedStageId((current) => next.stages.some((stage) => stage.id === current) ? current : next.stages[0]?.id ?? "");
    setBusy(false);
  }, [itemId, kind]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch(() => {
      if (!controller.signal.aborted) {
        setError("无法连接经营控制平面；页面没有生成任何替代业务数据");
        setBusy(false);
      }
    });
    return () => controller.abort("operating workspace unmounted");
  }, [load]);

  const selectedStage = useMemo(
    () => snapshot?.stages.find((stage) => stage.id === selectedStageId) ?? snapshot?.stages[0] ?? null,
    [selectedStageId, snapshot],
  );
  const meta = kindMeta[snapshot?.kind ?? (kind in kindMeta ? kind as keyof typeof kindMeta : "points")];
  const KindIcon = meta.icon;
  const contextRows = useMemo(() => {
    if (!snapshot) return [];
    const hidden = new Set(["type", "supporting_points", "lines"]);
    return Object.entries(snapshot.context).filter(([key, value]) => !hidden.has(key) && value !== null && value !== undefined);
  }, [snapshot]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/capability-atlas"><ArrowLeft size={16} />AI 能力树</Link>
        <div className={styles.productMark}><KindIcon size={17} /><div><strong>Operating Workspace</strong><small>RELEASE {snapshot?.release_version ?? "—"} · REGISTRY {snapshot?.registry_version ?? "—"} · READ ONLY</small></div></div>
        <div className={styles.identity}><span>{session?.email?.slice(0, 1).toUpperCase() ?? "K"}</span><div><strong>{session?.email ?? "身份校验中"}</strong><small>{session?.roles?.join(" / ") ?? "server-owned identity"}</small></div></div>
      </header>

      {busy ? (
        <section className={styles.state}><RefreshCw className={styles.spin} size={28} /><strong>正在读取能力合同与真实经营快照</strong><p>缺失数据将保持 unknown，不使用演示数字填充。</p></section>
      ) : error ? (
        <section className={`${styles.state} ${styles.error}`}><AlertTriangle size={28} /><strong>无法打开该业务工作区</strong><p>{error}</p><button type="button" onClick={() => void load()}>重新读取</button></section>
      ) : snapshot ? (
        <>
          <section className={styles.hero}>
            <div>
              <span className={styles.eyebrow}><KindIcon size={14} />{meta.label} · {snapshot.item_id}</span>
              <h1>{snapshot.title}</h1>
              <p>{snapshot.mission}</p>
              <div className={styles.proofs}>
                <span><LockKeyhole size={14} />外部写入关闭</span>
                <span><Database size={14} />Ozon RU · {snapshot.store_ref}</span>
                <span><Fingerprint size={14} />{shortHash(snapshot.workspace_sha256)}</span>
              </div>
            </div>
            <aside className={styles.heroMetrics}>
              <article><strong>{snapshot.counts.stages}</strong><span>阶段合同</span></article>
              <article><strong>{snapshot.counts.domain_signals}</strong><span>真实域信号</span></article>
              <article><strong>{snapshot.live.data_gaps.length}</strong><span>显式数据缺口</span></article>
              <article><strong>{snapshot.counts.related_lines}</strong><span>关联业务线</span></article>
            </aside>
          </section>

          <section className={styles.boundary}>
            <ShieldCheck size={17} />
            <div><strong>合同状态 ≠ 运行事实</strong><p>能力“已实现”只代表软件合同存在；真实完成度只读取服务端 Evidence 与经营分析投影。</p></div>
            <small>source as of · {snapshot.source_as_of ?? "no verified observation"}</small>
          </section>

          <section className={styles.liveStrip}>
            {Object.entries(snapshot.live.summary).slice(0, 8).map(([key, value]) => (
              <article key={key}><span>{readableKey(key)}</span><strong>{readableValue(value)}</strong></article>
            ))}
            {!Object.keys(snapshot.live.summary).length ? <article><span>LIVE SUMMARY</span><strong>NO DATA</strong></article> : null}
          </section>

          <section className={styles.workspace}>
            <aside className={styles.stageRail}>
              <header><Workflow size={17} /><div><span>全链路阶段</span><strong>{snapshot.stages.length} 个服务端合同</strong></div></header>
              <div>
                {snapshot.stages.map((stage) => (
                  <button
                    type="button"
                    key={stage.id}
                    className={stage.id === selectedStage?.id ? styles.selectedStage : ""}
                    onClick={() => setSelectedStageId(stage.id)}
                  >
                    <span>{String(stage.sequence).padStart(2, "0")}</span>
                    <div><strong>{stage.label}</strong><small>{stage.business_object}</small></div>
                    <i className={styles[stage.runtime_status]} title={runtimeLabel[stage.runtime_status]} />
                  </button>
                ))}
              </div>
            </aside>
            {selectedStage ? <StageDetail stage={selectedStage} /> : null}
          </section>

          <section className={styles.lowerGrid}>
            <article className={styles.panel}>
              <header><BarChart3 size={18} /><div><span>DOMAIN RUNTIME SIGNALS</span><h3>同领域真实运行投影</h3></div></header>
              <div className={styles.signalList}>
                {snapshot.domain_signals.map((signal) => (
                  <div key={signal.id}>
                    <span className={styles[signal.status]}>{signal.step}</span>
                    <div><strong>{signal.label}</strong><p>{signal.facts.join(" · ") || "无精确事实"}</p></div>
                    <b>{signal.progress_percent}%</b>
                  </div>
                ))}
                {!snapshot.domain_signals.length ? <p className={styles.emptyCopy}>该领域暂无真实运行信号。</p> : null}
              </div>
            </article>

            <article className={styles.panel}>
              <header><GitBranch size={18} /><div><span>CONTEXT CONTRACT</span><h3>点 / 线 / 面业务语境</h3></div></header>
              <dl className={styles.contextList}>
                {contextRows.map(([key, value]) => <div key={key}><dt>{readableKey(key)}</dt><dd>{readableValue(value)}</dd></div>)}
              </dl>
            </article>

            <article className={styles.panel}>
              <header><Link2 size={18} /><div><span>CONNECTED WORKSPACES</span><h3>继续穿透，不留死路</h3></div></header>
              <div className={styles.actions}>
                {snapshot.actions.map((action) => <Link href={action.href} key={action.id}>{action.label}<ExternalLink size={13} /></Link>)}
              </div>
              <RelatedLinks label="关联业务线" links={snapshot.navigation.related_lines} />
              <RelatedLinks label="关联原子点" links={snapshot.navigation.related_points.slice(0, 12)} />
              <RelatedLinks label="关联经营面" links={snapshot.navigation.related_surfaces} />
            </article>

            <article className={`${styles.panel} ${styles.gapsPanel}`}>
              <header><AlertTriangle size={18} /><div><span>EXCEPTION & DATA GAP</span><h3>阻断和未知必须显式</h3></div></header>
              <div>{snapshot.live.data_gaps.length ? snapshot.live.data_gaps.map((gap) => <p key={gap}>{gap}</p>) : <p>当前快照未报告数据缺口。</p>}</div>
              <footer><LockKeyhole size={14} />客户端不能重算运行状态，也不能触发外部写入。</footer>
            </article>
          </section>
        </>
      ) : null}
    </main>
  );
}
