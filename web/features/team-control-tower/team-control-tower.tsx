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
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type RefObject } from "react";
import type { WebSession } from "../dashboard/contracts";
import { fetchJson } from "../../lib/fetch-json";
import type {
  EnterpriseHeadcountBand,
  EnterprisePositioningProjection,
  EnterprisePrimaryObjective,
  EnterpriseRiskClass,
  EnterpriseStage,
  EnterpriseBusinessModel,
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
  RECOMMENDATION_ONLY: "只读建议",
  BLOCKED_EVIDENCE: "等待证据",
  required_now: "当前必需",
  supporting_ai: "AI 支撑",
  on_demand: "按需激活",
  standby: "待命",
  unsupported_gap: "能力缺岗",
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

function EnterprisePositioningPanel({
  projection,
  busy,
  simulating,
  mode,
  error,
  notice,
  onSimulate,
  onRestore,
  focusTargetRef,
}: {
  projection: EnterprisePositioningProjection | null;
  busy: boolean;
  simulating: boolean;
  mode: "current" | "simulation";
  error: string;
  notice: string;
  onSimulate: (event: FormEvent<HTMLFormElement>) => void;
  onRestore: () => void;
  focusTargetRef: RefObject<HTMLHeadingElement | null>;
}) {
  return (
    <section
      className={`${styles.controlSection} ${styles.positioningSection}`}
      aria-labelledby="enterprise-positioning-title"
      aria-describedby="enterprise-positioning-boundary"
      aria-busy={busy || simulating}
    >
      <header>
        <div>
          <span>ENTERPRISE POSITIONING · READ-ONLY ADVISOR</span>
          <h2 id="enterprise-positioning-title" ref={focusTargetRef} tabIndex={-1}>企业定位与角色编制</h2>
        </div>
        <Status value={projection?.status ?? "UNKNOWN"} />
      </header>
      <p id="enterprise-positioning-boundary" className={styles.positioningBoundary}>
        这是能力岗位模板，不是虚拟员工或生产身份。模拟画像未保存、不任命、不授权、不启动任务；角色状态、缺岗、Gate 与顺序全部由服务端返回。
      </p>

      {error ? <div className={styles.positioningError} role="alert"><AlertTriangle size={16} />{error}</div> : null}
      {busy && !projection ? (
        <div className={styles.positioningLoading} role="status" aria-live="polite">
          <RefreshCw size={16} aria-hidden="true" />读取当前企业画像与角色合同…
        </div>
      ) : null}
      {notice ? <p className={styles.positioningNotice} role="status" aria-live="polite">{notice}</p> : null}

      {projection ? (
        <>
          <div className={styles.positioningModeBar}>
            <span>{mode === "current" ? "当前版本化画像" : "未保存的情景模拟"}</span>
            <code>{projection.enterprise_profile.enterprise_ref} · {shortHash(projection.snapshot_sha256)}</code>
          </div>

          <details className={styles.positioningAudit}>
            <summary>查看完整合同、作用域与审计边界</summary>
            <dl>
              <div><dt>合同</dt><dd>{projection.contract_id} · {projection.version}</dd></div>
              <div><dt>作用域</dt><dd>{projection.profile_scope.scope_ref}</dd></div>
              <div><dt>企业原型</dt><dd>{projection.enterprise_positioning.archetype_ref}</dd></div>
              <div><dt>角色构成</dt><dd>core {projection.role_summary.core} · AI {projection.role_summary.ai_specialist} · control {projection.role_summary.independent_control} · gap {projection.role_summary.unsupported_gap}</dd></div>
              <div><dt>容量</dt><dd>{projection.capacity_plan.headcount_band} · {projection.capacity_plan.role_bundle_mode} · 每人 WIP {projection.capacity_plan.max_active_work_per_human} · AI 不计真人 {String(projection.capacity_plan.ai_templates_count_as_humans)}</dd></div>
              <div><dt>来源包</dt><dd><code>{projection.source_bundle_sha256}</code></dd></div>
              <div><dt>快照</dt><dd><code>{projection.snapshot_sha256}</code></dd></div>
            </dl>
            <p>边界：{Object.entries(projection.enterprise_positioning.boundaries).map(([key, value]) => `${key}=${String(value)}`).join(" · ")}</p>
            <p>来源：{Object.entries(projection.source_hashes).map(([key, value]) => `${key}=${shortHash(value)}`).join(" · ")}</p>
          </details>

          <div className={styles.positioningLeadGrid}>
            <article>
              <span>CURRENT POSITIONING</span>
              <h3>当前定位</h3>
              <p>{projection.enterprise_positioning.current_positioning}</p>
              <strong>{projection.enterprise_positioning.value_wedge}</strong>
              <p>商业模式重点：{projection.enterprise_positioning.business_model_emphasis}</p>
            </article>
            <article>
              <span>TARGET POSITIONING</span>
              <h3>目标定位</h3>
              <p>{projection.enterprise_positioning.target_positioning}</p>
              <Status value={projection.enterprise_positioning.promotion_gate_status} />
              <p>自动化上限：{projection.enterprise_positioning.automation_ceiling}</p>
            </article>
          </div>

          <section className={styles.positioningSubsection} aria-labelledby="role-composition-title">
            <header>
              <div><span>SERVER-OWNED ROLE COMPOSITION</span><h3 id="role-composition-title">四类角色建议</h3></div>
              <strong>{projection.role_summary.catalog_total} 个能力模板</strong>
            </header>
            <dl className={styles.roleSummary}>
              <div><dt>当前必需</dt><dd>{projection.role_summary.required_now}</dd></div>
              <div><dt>AI 支撑</dt><dd>{projection.role_summary.supporting_ai}</dd></div>
              <div><dt>按需激活</dt><dd>{projection.role_summary.on_demand}</dd></div>
              <div><dt>待命</dt><dd>{projection.role_summary.standby}</dd></div>
            </dl>
            <details>
              <summary>查看服务端顺序的 35 个能力模板</summary>
              <div className={styles.roleRoster}>
                {projection.role_roster.map((role) => (
                  <article key={role.role_template_ref}>
                    <header><h4>{role.title}</h4><Status value={role.recommendation_status} /></header>
                    <code>{role.role_template_ref}</code>
                    <small>{role.role_ref} · {role.role_kind} · priority {role.objective_priority ?? "—"}</small>
                    <p>{role.mission}</p>
                    <small>{reason(role.reason_codes)}</small>
                    <footer>{role.runtime_mode} · 真人席位 {String(role.human_seat_eligible)} · 真人绑定 {role.human_binding_status} · 生产授权 {String(role.production_authority_granted)} · 事实晋级 {String(role.formal_fact_promotion_allowed)} · 外写 {String(role.external_write_allowed)}</footer>
                  </article>
                ))}
              </div>
            </details>
          </section>

          <div className={styles.positioningControlGrid}>
            <section aria-labelledby="seat-plan-title">
              <header><h3 id="seat-plan-title">真人席位与兼岗</h3><span>{projection.capacity_plan.planned_human_seats}/{projection.capacity_plan.max_human_seats} 席 · 最多 {projection.capacity_plan.max_parallel_workstreams} 条并行线</span></header>
              <div className={styles.positioningList}>
                {projection.seat_plan.map((seat) => (
                  <article key={seat.seat_ref}>
                    <strong>{seat.title}</strong>
                    <code>{seat.seat_ref}</code>
                    <p>{seat.mission}</p>
                    <p>{seat.role_bundle_refs.join(" · ")}</p>
                    <small>真人绑定 {seat.binding_status} · AI 模板排除 {String(seat.ai_templates_excluded)} · 任命证据 {String(seat.appointment_evidence_present)} · SoD {seat.sod_conflict_refs.join(" / ") || "无已登记冲突"}</small>
                  </article>
                ))}
              </div>
              <details><summary>最低真人责任节点</summary><ul>{projection.minimum_human_accountability.map((item) => <li key={item.seat_ref}>{item.seat_ref} · {item.binding_status} · 任命证据 {String(item.appointment_evidence_present)} · 模板不是任命证据 {String(!item.role_template_is_appointment_evidence)}</li>)}</ul></details>
            </section>

            <section aria-labelledby="sod-plan-title">
              <header><h3 id="sod-plan-title">不可兼任冲突</h3><span>服务端 SoD</span></header>
              <ul className={styles.sodList}>
                {projection.separation_of_duties.map((rule) => (
                  <li key={rule.rule_ref}><b>{rule.rule_ref}</b><span>{rule.left_function_ref} ≠ {rule.right_function_ref} · 同岗 {String(rule.same_role_allowed)} · 同人 {String(rule.same_principal_allowed)} · 身份权威 {String(rule.identity_authority_required)}</span></li>
                ))}
              </ul>
            </section>

            <section aria-labelledby="role-gap-title">
              <header><h3 id="role-gap-title">市场 / 平台专业缺岗</h3><span>不以通用角色冒充</span></header>
              {projection.role_gaps.length ? (
                <ul className={styles.gapList}>
                  {projection.role_gaps.map((gap) => <li key={gap.gap_ref}><Status value={gap.recommendation_status} /><span><b>{gap.gap_ref}</b><small>{gap.reason_code} · {gap.authority_status}</small></span></li>)}
                </ul>
              ) : <p className={styles.noGap}>服务端未返回当前市场或平台缺岗。</p>}
            </section>

            <section aria-labelledby="activation-title">
              <header><h3 id="activation-title">唯一下一角色</h3><Status value={projection.next_role_activation.target_status ?? "UNKNOWN"} /></header>
              <strong className={styles.nextRole}>{projection.next_role_activation.role_ref ?? "当前没有待激活角色"}</strong>
              <code>{projection.next_role_activation.role_template_ref ?? "无待激活模板"} · 当前 {projection.next_role_activation.current_status ?? "none"}</code>
              <p>{projection.next_role_activation.reason_code}</p>
              <h4>激活 Gate</h4>
              <p>{projection.next_role_activation.required_gate}</p>
              <h4>目标晋级 Gate</h4>
              <ol>{projection.enterprise_positioning.required_gates.map((gate) => <li key={gate}>{gate}</li>)}</ol>
            </section>
          </div>

          <form className={styles.profileForm} onSubmit={onSimulate} aria-describedby="profile-simulator-note">
            <header>
              <div><span>NON-PERSISTENT SCENARIO</span><h3>企业画像模拟器</h3></div>
              <b>未保存 / 不任命 / 不授权</b>
            </header>
            <p id="profile-simulator-note">提交只调用确定性只读建议接口；不会修改当前企业画像，也不会创建身份或任务。</p>
            <div className={styles.profileFields} key={projection.snapshot_sha256}>
              <label htmlFor="positioning-enterprise-ref">企业标识<input id="positioning-enterprise-ref" name="enterprise_ref" required pattern="[A-Za-z0-9_.:-]+" defaultValue={projection.enterprise_profile.enterprise_ref} /></label>
              <label htmlFor="positioning-business-model">商业模式<select id="positioning-business-model" name="business_model" required defaultValue={projection.enterprise_profile.business_model}><option value="merchant_operator">自营经营</option><option value="commerce_control_plane_provider">控制平台服务</option><option value="hybrid_operator_and_control_plane">自营 + 控制平台</option></select></label>
              <label htmlFor="positioning-stage">企业阶段<select id="positioning-stage" name="stage" required defaultValue={projection.enterprise_profile.stage}><option value="validation">验证期</option><option value="repeatable">可复制期</option><option value="scale">规模化</option><option value="enterprise">企业级</option></select></label>
              <label htmlFor="positioning-headcount">人数带<select id="positioning-headcount" name="headcount_band" required defaultValue={projection.enterprise_profile.headcount_band}><option value="solo_to_micro">1–4 人</option><option value="small">小型</option><option value="medium">中型</option><option value="large">大型</option></select></label>
              <label htmlFor="positioning-markets">市场（逗号分隔）<input id="positioning-markets" name="markets" required defaultValue={projection.enterprise_profile.markets.join(",")} /></label>
              <label htmlFor="positioning-platforms">平台（逗号分隔）<input id="positioning-platforms" name="platforms" required defaultValue={projection.enterprise_profile.platforms.join(",")} /></label>
              <label htmlFor="positioning-risk">风险等级<select id="positioning-risk" name="risk_class" required defaultValue={projection.enterprise_profile.risk_class}><option value="standard">标准</option><option value="elevated">较高</option><option value="regulated">强监管</option></select></label>
              <label htmlFor="positioning-objective">首要目标<select id="positioning-objective" name="primary_objective" required defaultValue={projection.enterprise_profile.primary_objective}><option value="actual_cash_truth">真实现金闭环</option><option value="repeatable_growth">可复制增长</option><option value="multi_market_scale">多市场规模化</option><option value="enterprise_ai_erp">企业 AI ERP</option></select></label>
            </div>
            <div className={styles.profileActions}>
              <button type="submit" disabled={simulating} aria-busy={simulating}>{simulating ? "计算建议中…" : "模拟角色编制"}</button>
              {mode === "simulation" ? <button type="button" className={styles.secondaryButton} onClick={onRestore} disabled={busy || simulating}>恢复当前权威画像</button> : null}
            </div>
          </form>

          <footer className={styles.positioningFooter}>
            <ShieldCheck size={17} aria-hidden="true" />
            <span>profile_scope.grants_authority={String(projection.profile_scope.grants_authority)} · identities_created={String(projection.system_actions.identities_created)} · agents_created={String(projection.system_actions.agents_created)} · humans_appointed={String(projection.system_actions.humans_appointed)} · appointments_created={String(projection.system_actions.appointments_created)} · roles_bound={String(projection.system_actions.roles_bound)} · tasks_started={String(projection.system_actions.tasks_started)} · budgets_created={String(projection.system_actions.budgets_created)} · approvals_created={String(projection.system_actions.approvals_created)} · permits_issued={String(projection.system_actions.permits_issued)} · production_authority_granted={String(projection.system_actions.production_authority_granted)} · facts_promoted={String(projection.system_actions.facts_promoted)} · external_write_performed={String(projection.system_actions.external_write_performed)}</span>
          </footer>
        </>
      ) : null}
    </section>
  );
}

export function TeamControlTowerPage() {
  const [session, setSession] = useState<WebSession | null>(null);
  const [brief, setBrief] = useState<TeamControlBrief | null>(null);
  const [positioning, setPositioning] = useState<EnterprisePositioningProjection | null>(null);
  const [busy, setBusy] = useState(true);
  const [positioningBusy, setPositioningBusy] = useState(true);
  const [advancing, setAdvancing] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [rationale, setRationale] = useState("");
  const [evidence, setEvidence] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [positioningError, setPositioningError] = useState("");
  const [positioningNotice, setPositioningNotice] = useState("");
  const [positioningMode, setPositioningMode] = useState<"current" | "simulation">("current");
  const positioningHeadingRef = useRef<HTMLHeadingElement>(null);
  const retryCommand = useRef<{
    logicalPayload: string;
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
    setPositioningBusy(true);
    setError("");
    setPositioningError("");
    setPositioningNotice("");
    const sessionResponse = await fetchJson<WebSession | { detail?: string }>("/auth/session", {
      cache: "no-store",
      signal,
    });
    if (sessionResponse.status === 401) return window.location.assign("/login");
    if (sessionResponse.status === 428) return window.location.assign("/mfa");
    const sessionBody = await sessionResponse.json();
    if (!sessionResponse.ok) {
      setError("身份服务不可用；总控未读取任何跨境经营数据。");
      setPositioningError("身份服务不可用；企业定位建议未读取。");
      setPositioningBusy(false);
      return setBusy(false);
    }
    setSession(sessionBody as WebSession);
    const [briefOutcome, positioningOutcome] = await Promise.allSettled([
      fetchJson<TeamControlBrief | { detail?: string }>(
        "/backend/v1/team-control/brief?store_ref=ozon-primary",
        { cache: "no-store", signal },
      ).then(async (response) => ({ response, body: await response.json() })),
      fetchJson<EnterprisePositioningProjection | { detail?: string }>(
        "/backend/v1/enterprise-positioning/current",
        { cache: "no-store", signal },
      ).then(async (response) => ({ response, body: await response.json() })),
    ]);
    if (signal?.aborted) return;
    if (briefOutcome.status === "rejected") {
      setError("无法连接团队总控；页面没有生成演示状态。");
    } else if (!briefOutcome.value.response.ok) {
      setBrief(null);
      setError((briefOutcome.value.body as { detail?: string }).detail ?? "团队总控快照不可用。");
    } else {
      const nextBrief = briefOutcome.value.body as TeamControlBrief;
      retryCommand.current = null;
      setBrief(nextBrief);
    }
    if (positioningOutcome.status === "rejected") {
      setPositioningError("企业定位与角色建议服务不可用；团队总控仍保持独立可用。");
    } else if (!positioningOutcome.value.response.ok) {
      setPositioning(null);
      setPositioningError(
        (positioningOutcome.value.body as { detail?: string }).detail
          ?? "企业定位与角色建议不可用；团队总控仍保持独立可用。",
      );
    } else {
      setPositioning(positioningOutcome.value.body as EnterprisePositioningProjection);
      setPositioningMode("current");
    }
    setBusy(false);
    setPositioningBusy(false);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch(() => {
      if (!controller.signal.aborted) {
        setError("无法连接团队总控；页面没有生成演示状态。");
        setPositioningError("企业定位与角色建议服务不可用；团队总控仍保持独立可用。");
        setBusy(false);
        setPositioningBusy(false);
      }
    });
    return () => controller.abort("team control unmounted");
  }, [load]);

  const canAdvance = useMemo(
    () => Boolean(session?.roles.some((role) => role === "operator" || role === "admin")),
    [session?.roles],
  );

  const simulatePositioning = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const profile = {
      enterprise_ref: String(form.get("enterprise_ref") ?? ""),
      business_model: String(form.get("business_model") ?? "") as EnterpriseBusinessModel,
      stage: String(form.get("stage") ?? "") as EnterpriseStage,
      headcount_band: String(form.get("headcount_band") ?? "") as EnterpriseHeadcountBand,
      markets: String(form.get("markets") ?? "").split(",").map((item) => item.trim()).filter(Boolean),
      platforms: String(form.get("platforms") ?? "").split(",").map((item) => item.trim()).filter(Boolean),
      risk_class: String(form.get("risk_class") ?? "") as EnterpriseRiskClass,
      primary_objective: String(form.get("primary_objective") ?? "") as EnterprisePrimaryObjective,
    };
    setSimulating(true);
    setPositioningError("");
    setPositioningNotice("");
    try {
      const response = await fetchJson<EnterprisePositioningProjection | { detail?: string; error?: { message?: string } }>(
        "/backend/v1/enterprise-positioning/recommend",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(profile),
        },
      );
      const body = await response.json();
      if (!response.ok) {
        const failure = body as { detail?: string; error?: { message?: string } };
        setPositioningError(failure.detail ?? failure.error?.message ?? "画像模拟失败；当前建议未被覆盖。");
      } else {
        setPositioning(body as EnterprisePositioningProjection);
        setPositioningMode("simulation");
        setPositioningNotice("模拟建议已更新：此画像未保存，角色未任命，权限未授予。");
      }
    } catch {
      setPositioningError("画像模拟网络失败；当前建议未被覆盖，也没有保存任何输入。");
    } finally {
      setSimulating(false);
    }
  }, []);

  const restorePositioning = useCallback(async () => {
    await load();
    requestAnimationFrame(() => positioningHeadingRef.current?.focus());
  }, [load]);

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
      const logicalPayload = JSON.stringify({
        continuation: brief.next_action.continuation,
        result,
        rationale: rationale.trim(),
        evidence_ids: evidenceIds,
      });
      if (retryCommand.current?.logicalPayload !== logicalPayload) {
        const key = `team-control-${crypto.randomUUID()}`;
        retryCommand.current = {
          logicalPayload,
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
      } else {
        retryCommand.current = null;
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

      <EnterprisePositioningPanel
        projection={positioning}
        busy={positioningBusy}
        simulating={simulating}
        mode={positioningMode}
        error={positioningError}
        notice={positioningNotice}
        onSimulate={(event) => void simulatePositioning(event)}
        onRestore={() => void restorePositioning()}
        focusTargetRef={positioningHeadingRef}
      />

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
