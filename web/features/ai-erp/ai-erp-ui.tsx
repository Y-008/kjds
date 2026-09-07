"use client";

import { AlertTriangle, Check, CircleHelp, Clock3, FileCheck2, History, LockKeyhole, RotateCcw, ShieldCheck, Sparkles, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useId, type ReactNode } from "react";
import styles from "./ai-erp-ui.module.css";

export type DataState = "READY" | "NO_DATA" | "PARTIAL" | "STALE" | "BLOCKED" | "FORBIDDEN" | "CONFLICTED" | "LOADING" | "ERROR";
export type AiState = "SUGGESTED" | "REVIEW_REQUIRED" | "GATED" | "EXECUTED" | "UNKNOWN_OUTCOME";
export type ActionStage = "suggestion" | "preflight" | "permit" | "execution" | "readback" | "rollback";

const dataStateCopy: Record<DataState, { label: string; description: string }> = {
  READY: { label: "READY", description: "服务端数据可用且在 freshness 窗口内" },
  NO_DATA: { label: "NO DATA", description: "没有可展示的真实数据" },
  PARTIAL: { label: "PARTIAL", description: "仅部分来源或范围可用" },
  STALE: { label: "STALE", description: "数据超过当前 freshness 窗口" },
  BLOCKED: { label: "BLOCKED", description: "被服务端门禁阻断" },
  FORBIDDEN: { label: "FORBIDDEN", description: "当前身份无权查看" },
  CONFLICTED: { label: "CONFLICTED", description: "来源之间存在冲突" },
  LOADING: { label: "LOADING", description: "正在读取服务端快照" },
  ERROR: { label: "ERROR", description: "读取服务端快照失败" },
};

const aiStateCopy: Record<AiState, { label: string; description: string }> = {
  SUGGESTED: { label: "建议中", description: "AI 只生成建议，尚未进入授权流程" },
  REVIEW_REQUIRED: { label: "待人审", description: "需要独立的人类复核" },
  GATED: { label: "已门禁", description: "等待 Permit 或其他服务端门禁" },
  EXECUTED: { label: "已执行", description: "已有执行记录，仍需核对读回" },
  UNKNOWN_OUTCOME: { label: "结果未知", description: "执行结果尚未被可信读回确认" },
};

export function DataStateBadge({ state }: { state: DataState }) {
  const copy = dataStateCopy[state];
  return <span className={`${styles.badge} ${styles[`data-${state.toLowerCase()}`]}`} title={copy.description}>
    <span className={styles.dot} aria-hidden="true" />{copy.label}<span className={styles.srOnly}>：{copy.description}</span>
  </span>;
}

/** Compact contract-facing name for compositions that render a data state. */
export function DataState({ state }: { state: DataState }) {
  return <DataStateBadge state={state} />;
}

export function AIStatusBadge({ state }: { state: AiState }) {
  const copy = aiStateCopy[state];
  return <span className={`${styles.badge} ${styles[`ai-${state.toLowerCase()}`]}`} title={copy.description}>
    <Sparkles size={13} aria-hidden="true" />{copy.label}<span className={styles.srOnly}>：{copy.description}</span>
  </span>;
}

export interface MetricCardProps {
  label: string;
  value: string | number | null | undefined;
  unit?: string;
  quality?: string;
  freshness?: string;
  asOf?: string | null;
  source?: string | null;
  state?: DataState;
  definition?: string;
}

function metricValue(value: MetricCardProps["value"], state: DataState) {
  if (state === "NO_DATA" || value === null || value === undefined || value === "") return "NO DATA";
  return `${value}`;
}

export function MetricCard({ label, value, unit, quality = "未提供", freshness = "未提供", asOf, source, state = "READY", definition }: MetricCardProps) {
  const empty = state === "NO_DATA" || value === null || value === undefined || value === "";
  return <article className={`${styles.card} ${styles.metricCard}`} aria-label={`${label}，${dataStateCopy[state].label}`}>
    <div className={styles.cardHeader}><span className={styles.label}>{label}</span><DataStateBadge state={state} /></div>
    <p className={`${styles.metricValue} ${empty ? styles.muted : ""}`}>{metricValue(value, state)}{unit && !empty ? <small>{unit}</small> : null}</p>
    {definition ? <p className={styles.description}>{definition}</p> : null}
    <dl className={styles.metaGrid}>
      <div><dt>质量</dt><dd>{quality || "UNKNOWN"}</dd></div>
      <div><dt>Freshness</dt><dd>{freshness || "UNKNOWN"}</dd></div>
      <div><dt>As of</dt><dd>{asOf || "NO DATA"}</dd></div>
      <div><dt>来源</dt><dd>{source || "NO DATA"}</dd></div>
    </dl>
  </article>;
}

const stageCopy: Record<ActionStage, { label: string; icon: LucideIcon }> = {
  suggestion: { label: "建议", icon: Sparkles }, preflight: { label: "预检", icon: ShieldCheck }, permit: { label: "Permit", icon: LockKeyhole },
  execution: { label: "执行", icon: Clock3 }, readback: { label: "读回", icon: FileCheck2 }, rollback: { label: "回滚", icon: RotateCcw },
};

export interface ActionContractPanelProps {
  title: string;
  summary?: string;
  currentStage?: ActionStage;
  stages?: Partial<Record<ActionStage, "pending" | "passed" | "blocked" | "unknown">>;
  aiState?: AiState;
  onAdvance?: (stage: ActionStage) => void;
  onRollback?: () => void;
}

export function ActionContractPanel({ title, summary, currentStage = "suggestion", stages = {}, aiState = "SUGGESTED", onAdvance, onRollback }: ActionContractPanelProps) {
  const titleId = useId();
  const stageList = Object.keys(stageCopy) as ActionStage[];
  return <section className={`${styles.card} ${styles.actionPanel}`} aria-labelledby={titleId}>
    <div className={styles.cardHeader}><div><span className={styles.kicker}>ACTION CONTRACT</span><h2 id={titleId}>{title}</h2></div><AIStatusBadge state={aiState} /></div>
    {summary ? <p className={styles.description}>{summary}</p> : null}
    <ol className={styles.stageList} aria-label="动作合同阶段">
      {stageList.map((stage) => { const Icon = stageCopy[stage].icon; const status = stages[stage] ?? (stage === currentStage ? "pending" : "pending"); const active = stage === currentStage;
        return <li className={`${styles.stage} ${active ? styles.stageActive : ""} ${styles[`stage-${status}`]}`} key={stage}>
          <button type="button" aria-current={active ? "step" : undefined} aria-label={`${stageCopy[stage].label}：${status}`} onClick={() => onAdvance?.(stage)} disabled={!onAdvance || status === "blocked"}>
            <Icon size={15} aria-hidden="true" /><span>{stageCopy[stage].label}</span><span className={styles.stageStatus}>{status}</span>
          </button>
        </li>; })}
    </ol>
    <div className={styles.panelFooter} aria-live="polite"><span><CircleHelp size={14} aria-hidden="true" />每一步都必须有服务端记录与作用域绑定</span>{onRollback ? <button type="button" className={styles.secondaryButton} onClick={onRollback}><RotateCcw size={14} aria-hidden="true" />请求回滚</button> : null}</div>
  </section>;
}

export interface EvidenceItem { id: string; label: string; detail?: string; state?: DataState; recordedAt?: string; }
export function EvidenceTrail({ items, title = "Evidence trail" }: { items: EvidenceItem[]; title?: string }) {
  const titleId = useId();
  return <section className={`${styles.card} ${styles.evidenceTrail}`} aria-labelledby={titleId}><div className={styles.cardHeader}><h2 id={titleId}>{title}</h2><History size={17} aria-hidden="true" /></div>
    {items.length ? <ol className={styles.evidenceList}>{items.map((item) => <li key={item.id}><span className={styles.evidenceMarker} aria-hidden="true" /><div><strong>{item.label}</strong><span className={styles.evidenceId}>{item.id}</span>{item.detail ? <p>{item.detail}</p> : null}<small>{item.recordedAt || "时间未提供"}{item.state ? <> · <DataStateBadge state={item.state} /></> : null}</small></div></li>)}</ol> : <div className={styles.emptyState} role="status"><AlertTriangle size={16} aria-hidden="true" />NO DATA</div>}
  </section>;
}

export interface DecisionCardProps { title: string; recommendation?: string; rationale?: string; aiState?: AiState; confidence?: string; evidenceCount?: number | null; onReview?: () => void; }
export function DecisionCard({ title, recommendation, rationale, aiState = "REVIEW_REQUIRED", confidence, evidenceCount, onReview }: DecisionCardProps) {
  return <article className={`${styles.card} ${styles.decisionCard}`}><div className={styles.cardHeader}><div><span className={styles.kicker}>DECISION</span><h2>{title}</h2></div><AIStatusBadge state={aiState} /></div><p className={styles.recommendation}>{recommendation || "NO DATA"}</p>{rationale ? <p className={styles.description}>{rationale}</p> : null}<div className={styles.decisionMeta}><span>置信度：{confidence || "UNKNOWN"}</span><span>Evidence：{evidenceCount === null || evidenceCount === undefined ? "NO DATA" : evidenceCount}</span></div>{onReview ? <button className={styles.primaryButton} type="button" onClick={onReview}>打开人审</button> : null}</article>;
}

export interface QueueItem { id: string; title: string; detail?: string; state: AiState; owner?: string; }
export function TaskQueue({ items, onSelect }: { items: QueueItem[]; onSelect?: (item: QueueItem) => void }) {
  return <section className={`${styles.card} ${styles.queue}`} aria-labelledby="task-queue-title"><div className={styles.cardHeader}><h2 id="task-queue-title">Task queue</h2><span className={styles.count}>{items.length ? items.length : "NO DATA"}</span></div>{items.length ? <div className={styles.queueList}>{items.map((item) => <button type="button" className={styles.queueItem} key={item.id} onClick={() => onSelect?.(item)} disabled={!onSelect}><span><strong>{item.title}</strong><small>{item.detail || "详情未提供"}</small></span><span><AIStatusBadge state={item.state} /><small>{item.owner || "未分配"}</small></span></button>)}</div> : <div className={styles.emptyState} role="status">NO DATA · 暂无任务</div>}</section>;
}

export interface MatrixRow { label: string; data: ReactNode; ai: ReactNode; action: ReactNode; evidence: ReactNode; }
export function FourStateMatrix({ rows, title = "四状态矩阵" }: { rows: MatrixRow[]; title?: string }) {
  const titleId = useId();
  return <section className={`${styles.card} ${styles.matrix}`} aria-labelledby={titleId}><div className={styles.cardHeader}><h2 id={titleId}>{title}</h2><span className={styles.kicker}>DATA · AI · ACTION · EVIDENCE</span></div><div className={styles.tableWrap} tabIndex={0} role="region" aria-label={`${title}，可横向滚动`}><table><caption className={styles.srOnly}>{title}</caption><thead><tr><th scope="col">对象</th><th scope="col">数据状态</th><th scope="col">AI 状态</th><th scope="col">动作门禁</th><th scope="col">Evidence</th></tr></thead><tbody>{rows.length ? rows.map((row) => <tr key={row.label}><th scope="row">{row.label}</th><td>{row.data}</td><td>{row.ai}</td><td>{row.action}</td><td>{row.evidence}</td></tr>) : <tr><td colSpan={5}>NO DATA</td></tr>}</tbody></table></div></section>;
}

export { FourStateMatrix as StateMatrix };

export function ContractIcon({ status }: { status: "passed" | "blocked" | "unknown" }) { return status === "passed" ? <Check size={14} aria-label="通过" /> : status === "blocked" ? <X size={14} aria-label="阻断" /> : <CircleHelp size={14} aria-label="未知" />; }
