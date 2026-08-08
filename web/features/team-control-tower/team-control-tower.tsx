"use client";

import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Command,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  UserRoundCog,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { WebSession } from "../dashboard/contracts";
import { fetchJson } from "../../lib/fetch-json";
import type {
  TeamAdvanceReceipt,
  TeamControlBrief,
  TeamControlFlow,
} from "./contracts";
import styles from "./team-control-tower.module.css";

const statusLabels: Record<string, string> = {
  on_track: "ON TRACK",
  attention_required: "ATTENTION",
  blocked: "BLOCKED",
  awaiting_human: "AWAITING HUMAN",
  scope_invalid: "SCOPE INVALID",
  ready_for_dispatch: "READY",
  open: "OPEN",
  acknowledged: "ACKNOWLEDGED",
  in_progress: "IN PROGRESS",
  resolved: "RESOLVED",
  dismissed: "STOPPED",
  VERIFIED: "VERIFIED",
  PARTIAL: "PARTIAL",
  BLOCKED: "BLOCKED",
  STALE: "STALE",
  CONFLICTED: "CONFLICTED",
  UNKNOWN: "UNKNOWN",
};

const resultLabels = {
  take: "领取 / 推进",
  done: "完成并交证",
  blocked: "登记阻断",
  escalate: "升级总负责人",
  stop: "停止工作",
} as const;

function shortHash(value?: string | null) {
  return value ? `${value.slice(0, 8)}…${value.slice(-8)}` : "—";
}

function Status({ value }: { value: string }) {
  return <span className={`${styles.status} ${styles[value.toLowerCase()] ?? ""}`}>{statusLabels[value] ?? value}</span>;
}

function FlowCard({ flow }: { flow: TeamControlFlow }) {
  return (
    <article className={styles.flowCard}>
      <header>
        <div>
          <span>{flow.flow_ref}</span>
          <h3>{flow.display_title}</h3>
        </div>
        <Status value={flow.runtime_status} />
      </header>
      <p>{flow.objective}</p>
      <dl>
        <div><dt>Accountable</dt><dd>{flow.accountable_role}</dd></div>
        <div><dt>Risk</dt><dd>{flow.risk_level}</dd></div>
        <div><dt>Current task</dt><dd>{flow.current_operating_task?.id ?? "尚未进入 OperatingTask"}</dd></div>
        <div><dt>Due</dt><dd>{flow.due_at ? new Date(flow.due_at).toLocaleString("zh-CN") : "由下一任务合同确定"}</dd></div>
      </dl>
      <section className={styles.flowAction}>
        <strong>当前建议</strong>
        <span>{flow.default_next_action}</span>
      </section>
      <div className={styles.lanes}>
        {flow.source_assignments?.map((lane) => (
          <span key={`${flow.flow_ref}-${lane.lane_id}`}>
            {lane.lane_id} · {lane.current_task?.task_id ?? lane.next_task_id ?? "空闲"}
          </span>
        ))}
      </div>
      {flow.blockers.length ? (
        <details>
          <summary>{flow.blockers.length} 个阻断</summary>
          <ul>{flow.blockers.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
      ) : null}
    </article>
  );
}

function reason(value?: string[]) {
  return value?.length ? value.join(" · ") : "无附加原因";
}

function valueLabel(value?: { mode: string; value?: string; lower?: string; upper?: string } | null) {
  if (!value) return "UNKNOWN";
  if (value.mode === "public_exact") return value.value ?? "UNKNOWN";
  if (value.lower || value.upper) return `${value.lower ?? "?"} – ${value.upper ?? "?"}`;
  return value.mode.toUpperCase();
}

export function TeamControlTowerPage() {
  const [session, setSession] = useState<WebSession | null>(null);
  const [brief, setBrief] = useState<TeamControlBrief | null>(null);
  const [busy, setBusy] = useState(true);
  const [advancing, setAdvancing] = useState(false);
  const [rationale, setRationale] = useState("");
  const [evidence, setEvidence] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const retryCommand = useRef<{
    continuation: string;
    key: string;
    payload: {
      continuation: string;
      result: "take" | "done" | "blocked" | "escalate" | "stop";
      rationale: string;
      evidence_ids: string[];
      idempotency_key: string;
    };
  } | null>(null);

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
      setError("身份服务不可用；总控未读取任何跨境经营数据。");
      return setBusy(false);
    }
    setSession(sessionBody as WebSession);
    const response = await fetchJson<TeamControlBrief>(
      "/backend/v1/team-control/brief?store_ref=ozon-primary",
      { cache: "no-store", signal },
    );
    const body = await response.json();
    if (!response.ok) {
      setBrief(null);
      setError((body as { detail?: string }).detail ?? "团队总控快照不可用。");
    } else {
      const nextBrief = body as TeamControlBrief;
      if (retryCommand.current?.continuation !== nextBrief.next_action?.continuation) {
        retryCommand.current = null;
      }
      setBrief(nextBrief);
    }
    setBusy(false);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch(() => {
      if (!controller.signal.aborted) {
        setError("无法连接团队总控；页面没有生成演示状态。");
        setBusy(false);
      }
    });
    return () => controller.abort("team control unmounted");
  }, [load]);

  const canAdvance = useMemo(
    () => Boolean(session?.roles.some((role) => role === "operator" || role === "admin")),
    [session?.roles],
  );

  const advance = useCallback(async (result: "take" | "done" | "blocked" | "escalate" | "stop") => {
    if (!brief?.next_action) return;
    if (!rationale.trim()) {
      setNotice("推进动作必须填写理由。完成或停止时还必须绑定 Evidence。 ");
      return;
    }
    const evidenceIds = evidence.split(",").map((item) => item.trim()).filter(Boolean);
    if (brief.next_action.evidence_required && !evidenceIds.length) {
      setNotice("当前动作必须绑定至少一条 exact-scope Evidence。");
      return;
    }
    if ((result === "done" || result === "stop") && !evidenceIds.length) {
      setNotice("完成或停止必须绑定至少一条 exact-scope Evidence。");
      return;
    }
    setAdvancing(true);
    setNotice("");
    try {
      if (retryCommand.current?.continuation !== brief.next_action.continuation) {
        const key = `team-control-${crypto.randomUUID()}`;
        retryCommand.current = {
          continuation: brief.next_action.continuation,
          key,
          payload: {
            continuation: brief.next_action.continuation,
            result,
            rationale: rationale.trim(),
            evidence_ids: evidenceIds,
            idempotency_key: key,
          },
        };
      }
      const response = await fetchJson<TeamAdvanceReceipt | { detail?: string }>(
        "/backend/v1/team-control/advance?store_ref=ozon-primary",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(retryCommand.current.payload),
        },
      );
      const body = await response.json();
      setNotice(
        response.ok
          ? `已写入现有 OperatingTask/Event：${(body as TeamAdvanceReceipt).outcome}；没有创建 Permit 或平台外写。`
          : (body as { detail?: string }).detail ?? "推进失败",
      );
      if (response.ok) {
        retryCommand.current = null;
        setRationale("");
        setEvidence("");
        await load();
      }
    } catch {
      setNotice("网络失败；再次提交会复用同一幂等键，不会重复推进任务。");
    } finally {
      setAdvancing(false);
    }
  }, [brief?.next_action, evidence, load, rationale]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/"><ArrowLeft size={15} />经营总览</Link>
        <div className={styles.identity}>
          <span>{session?.email?.slice(0, 1).toUpperCase() ?? "K"}</span>
          <div><strong>{session?.email ?? "身份校验中"}</strong><small>{session?.roles?.join(" / ") ?? "exact-scope identity"}</small></div>
        </div>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}><Command size={14} />TEAM CONTROL · EXACT SCOPE</span>
          <h1>老板总控与专家协作塔</h1>
          <p>四条主线、一个唯一下一动作。团队协作写入既有 OperatingTask/Event；高风险决定、Approval、Permit 与执行继续保持独立。</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} />刷新权威快照</button>
      </section>

      {error ? <div className={styles.notice} role="alert"><AlertTriangle size={16} />{error}</div> : null}
      {busy ? <div className={styles.loading} role="status" aria-live="polite"><RefreshCw size={18} />读取 exact-scope、工作流租约与任务事件…</div> : null}

      {brief ? (
        <>
          <section className={styles.summary}>
            <article><UsersRound size={20} /><span>组织合同</span><strong>18 + 12 + 20–40 + 5</strong><small><Status value={brief.organization_readiness.status} /> 真人绑定 {brief.organization_readiness.verified_bindings?.human_core ?? "UNKNOWN"}/18</small></article>
            <article><Clock3 size={20} /><span>13 周现金</span><strong>{brief.cash_at_risk.status}</strong><small>真实 SKU 现金闭环：<Status value={brief.cash_at_risk.actual_cash_truth?.status ?? "UNKNOWN"} /></small></article>
            <article><Command size={20} /><span>当前战役阶段</span><strong>{brief.critical_path.actual_campaign_day ? `DAY ${brief.critical_path.actual_campaign_day}` : "UNKNOWN"}</strong><small>{brief.critical_path.earliest_blocking_phase_ref ?? "kickoff Evidence 未到"}</small></article>
            <article><AlertTriangle size={20} /><span>最大 Top1 差距</span><strong>{brief.top1_scorecard.largest_open_gap?.title ?? "UNKNOWN"}</strong><small>{brief.top1_scorecard.metric_leader_count ?? 0}/12 个维度为 metric leader</small></article>
            <article><ShieldCheck size={20} /><span>正式交付 Gate</span><strong>{brief.delivery_gate.passed_gate_count ?? 0}/{brief.delivery_gate.gate_count ?? 5}</strong><small><Status value={brief.delivery_gate.status} /> 不以任务完成替代 PASS</small></article>
          </section>

          <section className={styles.commandPanel}>
            <header>
              <div>
                <span>ONE EXECUTIVE NEXT ACTION</span>
                <h2>{brief.headline}</h2>
              </div>
              <Status value={brief.status} />
            </header>
            {brief.next_action ? (
              <div className={styles.nextAction}>
                <div className={styles.actionIcon}><UserRoundCog size={24} /></div>
                <div className={styles.actionCopy}>
                  <strong>{brief.next_action.label}</strong>
                  <span>Owner · {brief.next_action.owner} · {brief.next_action.risk_level}</span>
                  <code>continuation {shortHash(brief.next_action.continuation)}</code>
                </div>
                <div className={styles.actionInputs}>
                  <label>处理理由<input aria-label="处理理由" value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="处理理由（必填）" /></label>
                  <label>Evidence{brief.next_action.evidence_required ? "（当前动作必填）" : ""}<input aria-label="Evidence ID" aria-required={brief.next_action.evidence_required} value={evidence} onChange={(event) => setEvidence(event.target.value)} placeholder="Evidence ID，多个用逗号分隔" /></label>
                </div>
                <div className={styles.actionButtons}>
                  {brief.next_action.allowed_results.map((result) => (
                    <button
                      type="button"
                      key={result}
                      disabled={!canAdvance || advancing}
                      onClick={() => void advance(result)}
                    >
                      {resultLabels[result]}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className={styles.empty}><CheckCircle2 size={24} /><strong>当前没有待推进动作</strong></div>
            )}
            {!canAdvance ? <p className={styles.readOnly}>当前身份只读；只有 operator/admin 可以推进，Reviewer/Approver/Risk 保持独立。</p> : null}
            {notice ? <div className={styles.notice} role="status" aria-live="polite">{notice}</div> : null}
          </section>

          <section className={`${styles.controlSection} ${styles.enterpriseSection}`} aria-labelledby="enterprise-ai-erp-title" aria-describedby="enterprise-ai-erp-disclaimer">
            <header>
              <div><span>ENTERPRISE AI ERP · SERVER-OWNED CONTRACT</span><h2 id="enterprise-ai-erp-title">八个 Squad 与并行交付控制</h2></div>
              <Status value={brief.squad_readiness.status} />
            </header>
            <p id="enterprise-ai-erp-disclaimer" className={styles.enterpriseDisclaimer}>
              静态合同完整性 VERIFIED 不代表真人到岗、当前 WIP、容量可用、列车已排期或正式 Gate PASS。以下状态、原因和顺序均来自服务端；前端不计算晋级、依赖、候选或发布结论。
            </p>
            <div className={styles.enterpriseGrid}>
              <article>
                <header><h3>Squad readiness</h3><Status value={brief.squad_readiness.status} /></header>
                <strong>{brief.squad_readiness.contract_count ?? "UNKNOWN"} 个 Squad 合同</strong>
                <p>运行态：{reason(brief.squad_readiness.reason_codes)}</p>
                <details>
                  <summary>查看服务端 Squad 合同</summary>
                  <div className={styles.enterpriseList}>
                    {brief.squad_readiness.items?.map((item) => (
                      <section key={item.squad_ref} aria-label={item.title}>
                        <b>{item.squad_ref} · {item.title}</b>
                        <span>Owner {item.owner_role_ref} · Reviewer {item.reviewer_role_ref}</span>
                        <span>Lane {item.primary_lane_id} · <Status value={item.status} /></span>
                        <small>{item.first_acceptance_contract}</small>
                      </section>
                    )) ?? <span>UNKNOWN · Program authority unavailable</span>}
                  </div>
                </details>
              </article>

              <article>
                <header><h3>Role conflicts</h3><Status value={brief.role_conflicts.status} /></header>
                <strong>{brief.role_conflicts.contract_rules_verified ? "静态 SoD 规则 VERIFIED" : "UNKNOWN"}</strong>
                <p>已观察冲突：{brief.role_conflicts.observed_conflicts ? "服务端已返回" : "UNKNOWN"}</p>
                <details>
                  <summary>查看职责分离规则</summary>
                  <ul>
                    {brief.role_conflicts.rules?.map((rule) => (
                      <li key={rule.rule_ref}>{rule.rule_ref} · {rule.left_function_ref} ≠ {rule.right_function_ref}</li>
                    )) ?? <li>UNKNOWN · identity authority unavailable</li>}
                  </ul>
                </details>
              </article>

              <article>
                <header><h3>Parallel execution</h3><Status value={brief.parallel_execution.status} /></header>
                <dl className={styles.enterpriseFacts}>
                  <div><dt>控制 Agent</dt><dd>{brief.parallel_execution.policy?.control_agent_count ?? "UNKNOWN"}</dd></div>
                  <div><dt>专业 Agent 上限</dt><dd>{brief.parallel_execution.policy?.max_parallel_specialist_agents ?? "UNKNOWN"}</dd></div>
                  <div><dt>Writer 上限</dt><dd>{brief.parallel_execution.policy?.max_active_writers ?? "UNKNOWN"}</dd></div>
                  <div><dt>当前 Writer</dt><dd>{brief.parallel_execution.observed_active_writers ?? "UNKNOWN"}</dd></div>
                </dl>
                <p>{reason(brief.parallel_execution.reason_codes)}</p>
              </article>

              <article>
                <header><h3>Integration queue</h3><Status value={brief.integration_queue.status} /></header>
                <strong>计划初态：{brief.integration_queue.planned_initial_state ?? "UNKNOWN"}</strong>
                <div className={styles.enterpriseList}>
                  {brief.integration_queue.items?.map((item) => (
                    <section key={item.work_item_ref}>
                      <b>{item.work_item_ref} · {item.title}</b>
                      <span>Execution <Status value={item.execution_status} /></span>
                      <small>依赖：{item.dependency_refs.join(" · ") || "无"}</small>
                    </section>
                  )) ?? <span>UNKNOWN · OperatingTask authority unavailable</span>}
                </div>
              </article>

              <article>
                <header><h3>Capacity risk</h3><Status value={brief.capacity_risk.status} /></header>
                <strong>{brief.capacity_risk.capacity_proven_available ? "容量已证明" : "容量未被证明"}</strong>
                <dl className={styles.enterpriseFacts}>
                  <div><dt>Writer policy</dt><dd>{brief.capacity_risk.limits?.max_active_writers ?? "UNKNOWN"}</dd></div>
                  <div><dt>Writer observed</dt><dd>{brief.capacity_risk.observed_active_writers ?? "UNKNOWN"}</dd></div>
                  <div><dt>Lane observed</dt><dd>{brief.capacity_risk.observed_lane_wip ?? "UNKNOWN"}</dd></div>
                  <div><dt>Weekly outcomes</dt><dd>{brief.capacity_risk.observed_weekly_company_outcomes ?? "UNKNOWN"}</dd></div>
                </dl>
                <p>{reason(brief.capacity_risk.reason_codes)}</p>
              </article>

              <article>
                <header><h3>Next release train</h3><Status value={brief.next_release_train.status} /></header>
                <dl className={styles.enterpriseFacts}>
                  <div><dt>静态政策</dt><dd>{brief.next_release_train.release_trains_per_week ?? "UNKNOWN"} 次/周</dd></div>
                  <div><dt>计划时间</dt><dd>{brief.next_release_train.scheduled_at ?? "UNKNOWN"}</dd></div>
                  <div><dt>Gate</dt><dd>{brief.next_release_train.gate_status ?? "UNKNOWN"}</dd></div>
                  <div><dt>候选</dt><dd>{brief.next_release_train.eligible_work_item_refs ? "服务端已返回" : "UNKNOWN"}</dd></div>
                </dl>
                <p>Registry proves schedule = {String(brief.next_release_train.registry_proves_schedule ?? false)} · {reason(brief.next_release_train.reason_codes)}</p>
              </article>
            </div>
            <footer className={styles.enterpriseFooter}>
              Program snapshot · {shortHash(brief.squad_readiness.program_contract?.program_snapshot_sha256)} · runtime authority connected = false
            </footer>
          </section>

          <section className={styles.controlSection} aria-labelledby="critical-path-title">
            <header>
              <div><span>90-DAY CRITICAL PATH</span><h2 id="critical-path-title">90 天关键路径与阶段阻断</h2></div>
              <Status value={brief.critical_path.status} />
            </header>
            <p className={styles.sectionNote}>计划 {brief.critical_path.planned_start_on ?? "UNKNOWN"} → {brief.critical_path.planned_end_on ?? "UNKNOWN"}；kickoff <Status value={brief.critical_path.kickoff?.status ?? "UNKNOWN"} />，只有 Evidence 绑定的首阶段 start Event 才启动实际战役日。</p>
            <div className={styles.phaseGrid}>
              {brief.critical_path.phases?.map((phase) => (
                <article key={phase.phase_ref}>
                  <header><span>DAY {phase.day_from}–{phase.day_to}</span><Status value={phase.status} /></header>
                  <h3>{phase.title}</h3>
                  <p>{phase.owner_role} → review: {phase.reviewer_role}</p>
                  <strong>{phase.planned_start_on} → {phase.planned_end_on}</strong>
                  <small>OperatingTask · {phase.runtime_task_status ?? "NOT OPENED"} · formal Gate PASS = false</small>
                  <details><summary>{phase.blockers.length} 个泳道阻断 · {phase.reason_codes.length} 个状态原因</summary><p>{reason([...phase.blockers, ...phase.reason_codes])}</p></details>
                </article>
              )) ?? <p>UNKNOWN · exact-scope authority unavailable</p>}
            </div>
          </section>

          <section className={styles.controlSection} aria-labelledby="top1-title">
            <header>
              <div><span>TOP1 SCORECARD · SERVER PROJECTION</span><h2 id="top1-title">十二维 Top1 评分卡</h2></div>
              <div className={styles.headerStatus}><Status value={brief.top1_scorecard.status} /><b>global_top1_claim = false</b></div>
            </header>
            <div className={styles.scoreGrid}>
              {brief.top1_scorecard.dimensions?.map((dimension) => (
                <article key={dimension.dimension_ref}>
                  <header><Status value={dimension.status} /><span>{dimension.leadership_status}</span></header>
                  <h3>{dimension.title}</h3>
                  <strong>{valueLabel(dimension.current_value)}</strong>
                  <p>{dimension.market ?? "UNKNOWN market"} · {dimension.cohort_ref ?? "UNKNOWN cohort"}</p>
                  <dl><div><dt>Owner</dt><dd>{dimension.owner_role}</dd></div><div><dt>Verifier</dt><dd>{dimension.verifier_role}</dd></div></dl>
                  <small>{reason(dimension.reason_codes)}</small>
                  <footer>下一实验：{dimension.next_experiment}</footer>
                </article>
              )) ?? <p>UNKNOWN · benchmark authority unavailable</p>}
            </div>
          </section>

          <section className={styles.controlSplit}>
            <article className={styles.controlSection} aria-labelledby="organization-title">
              <header><div><span>ORGANIZATION READINESS</span><h2 id="organization-title">组织缺口与专家池</h2></div><Status value={brief.organization_readiness.status} /></header>
              <div className={styles.readinessNumbers}>
                <span><b>{brief.organization_readiness.registry_counts?.human_core_contracts ?? 18}</b>核心角色合同</span>
                <span><b>{brief.organization_readiness.registry_counts?.ai_specialist_contracts ?? 12}</b>AI 专家合同</span>
                <span><b>20–40</b>专家池目标</span>
                <span><b>{brief.organization_readiness.registry_counts?.control_role_contracts ?? 5}</b>控制角色合同</span>
              </div>
              <p className={styles.warningCopy}>合同数量不代表真人已到岗。当前缺口：{reason(brief.organization_readiness.blockers)}</p>
              <details><summary>缺失主责 / 替补 / 资质 / 冲突证明</summary><p>{reason([
                ...(brief.organization_readiness.missing?.primary_role_refs ?? []),
                ...(brief.organization_readiness.missing?.alternate_role_refs ?? []),
                ...(brief.organization_readiness.missing?.qualification_role_refs ?? []),
                ...(brief.organization_readiness.missing?.conflict_attestation_role_refs ?? []),
              ])}</p></details>
            </article>
            <article className={styles.controlSection} aria-labelledby="gate-title">
              <header><div><span>DELIVERY GATES</span><h2 id="gate-title">五个独立验收 Gate</h2></div><Status value={brief.delivery_gate.status} /></header>
              <div className={styles.gateList}>
                {brief.delivery_gate.gates?.map((gate) => (
                  <div key={gate.gate_ref}><Status value={gate.status} /><span><b>{gate.title}</b><small>readiness {gate.readiness_status ?? "UNKNOWN"} · formal PASS = false · {reason(gate.reason_codes)}</small></span></div>
                )) ?? <p>UNKNOWN · canonical Gate authority unavailable</p>}
              </div>
            </article>
          </section>

          <section className={styles.flowSection}>
            <header><div><span>FOUR CONTROL FLOWS</span><h2>项目、SKU、双轮商业化与 LG-001</h2></div><code>{shortHash(brief.snapshot_sha256)}</code></header>
            <div className={styles.flowGrid}>{brief.flows.map((flow) => <FlowCard flow={flow} key={flow.flow_ref} />)}</div>
          </section>

          <footer className={styles.controlFooter}>
            <LockKeyhole size={18} />
            <span>总负责人可以排序、领取、升级和停止，但不能自审自批，也不能签发 Permit。</span>
            <ShieldCheck size={18} />
            <b>external_write_allowed = false</b>
          </footer>
        </>
      ) : null}
    </main>
  );
}
