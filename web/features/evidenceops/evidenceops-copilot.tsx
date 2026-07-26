"use client";

import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CheckCircle2,
  Database,
  FileQuestion,
  Fingerprint,
  LockKeyhole,
  Radar,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
  Workflow,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import type { WebSession } from "../dashboard/contracts";
import type { EvidenceOpsPlan } from "./contracts";
import styles from "./evidenceops-copilot.module.css";

const defaultObjective = "提升当前 Ozon 商品利润，先找出最关键的证据缺口和下一步";

const exampleObjectives = [
  "补齐三家供应商报价并验证真实 CM3",
  "为现有商品准备俄语 Listing 和有权素材",
  "提升利润并完成结算、银行与 FX 对账",
  "基于真实数据设计第一个有止损的增长实验",
];

const statusLabel = {
  verified: "已验证",
  in_progress: "进行中",
  blocked: "被阻断",
  no_data: "无真源",
};

function shortHash(value: string) {
  return value ? `${value.slice(0, 8)}…${value.slice(-8)}` : "—";
}

function formatAsOf(value: string | null) {
  if (!value) return "尚无可复验观测时间";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(date);
}

export function EvidenceOpsCopilot() {
  const [session, setSession] = useState<WebSession | null>(null);
  const [objective, setObjective] = useState(defaultObjective);
  const [plan, setPlan] = useState<EvidenceOpsPlan | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);

  const requestPlan = useCallback(async (nextObjective: string, signal?: AbortSignal) => {
    const version = ++requestVersion.current;
    setBusy(true);
    setError("");
    try {
      const response = await fetchJson<EvidenceOpsPlan | { detail?: string }>(
        "/backend/v1/evidenceops/plan",
        {
          method: "POST",
          cache: "no-store",
          signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            objective: nextObjective,
            store_ref: "ozon-primary",
          }),
        },
      );
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      if (response.status === 428) {
        window.location.assign("/mfa");
        return;
      }
      const body = await response.json();
      if (version !== requestVersion.current) return;
      if (!response.ok) {
        setError("detail" in body && body.detail ? body.detail : "无法编译目标，请检查控制平面状态");
        setBusy(false);
        return;
      }
      setPlan(body as EvidenceOpsPlan);
      setBusy(false);
    } catch {
      if (signal?.aborted || version !== requestVersion.current) return;
      setError("无法连接经营控制平面；现有计划不会被网络错误覆盖");
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function boot() {
      try {
        const response = await fetchJson<WebSession | { detail?: string }>(
          "/auth/session",
          { cache: "no-store", signal: controller.signal },
        );
        if (response.status === 401) return window.location.assign("/login");
        if (response.status === 428) return window.location.assign("/mfa");
        const body = await response.json();
        if (!response.ok) {
          setError("detail" in body && body.detail ? body.detail : "Web 身份服务尚未就绪");
          setBusy(false);
          return;
        }
        setSession(body as WebSession);
        await requestPlan(defaultObjective, controller.signal);
      } catch {
        if (controller.signal.aborted) return;
        setError("无法验证 Web 身份；未读取或生成任何经营计划");
        setBusy(false);
      }
    }
    void boot();
    return () => controller.abort("evidenceops unmounted");
  }, [requestPlan]);

  const selectedAgents = useMemo(
    () => plan?.agent_team.filter((agent) => agent.selected_for_objective) ?? [],
    [plan],
  );

  async function submitObjective(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await requestPlan(objective);
  }

  async function useExample(value: string) {
    setObjective(value);
    await requestPlan(value);
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/" className={styles.backLink}>
          <ArrowLeft size={16} />
          KJDS Control Plane
        </Link>
        <div className={styles.productMark}>
          <span><Radar size={18} /></span>
          <div>
            <strong>EvidenceOps</strong>
            <small>COPILOT · 0.54.0</small>
          </div>
        </div>
        <div className={styles.identity}>
          <span>{session?.email?.slice(0, 1).toUpperCase() ?? "K"}</span>
          <div>
            <strong>{session?.email ?? "验证身份中"}</strong>
            <small>{session?.roles?.join(" / ") ?? "server-owned identity"}</small>
          </div>
        </div>
      </header>

      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.versionPill}><Sparkles size={14} /> EVIDENCE-NATIVE AI OPERATIONS</div>
          <h1><span>经营目标，不再变成</span><em>一段漂亮答案</em></h1>
          <p>
            EvidenceOps 把目标编译成可复验的任务合同：先展示真实事实与 unknown，
            再分派 Agent、验证条件和安全边界。
          </p>
          <div className={styles.heroProofs}>
            <span><ShieldCheck size={15} /> 同一经营真源</span>
            <span><Fingerprint size={15} /> 每次计划带哈希</span>
            <span><LockKeyhole size={15} /> 外部写入关闭</span>
          </div>
        </div>

        <form className={styles.commandCard} onSubmit={submitObjective}>
          <div className={styles.commandHead}>
            <div>
              <span>01</span>
              <strong>描述经营目标</strong>
            </div>
            <small>它是意图，不是事实或批准</small>
          </div>
          <textarea
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            minLength={3}
            maxLength={1000}
            aria-label="经营目标"
          />
          <div className={styles.examples}>
            {exampleObjectives.map((item) => (
              <button type="button" key={item} onClick={() => void useExample(item)}>
                {item}
              </button>
            ))}
          </div>
          <button className={styles.compileButton} type="submit" disabled={busy || objective.trim().length < 3}>
            {busy ? <RefreshCw className={styles.spin} size={18} /> : <Zap size={18} />}
            {busy ? "正在读取真源…" : "编译证据任务合同"}
            {!busy && <ArrowRight size={18} />}
          </button>
          <footer>
            <Database size={14} />
            不保存对话 · 不调用外部模型 · 不生成演示经营数据
          </footer>
        </form>
      </section>

      {error ? (
        <section className={styles.errorState}>
          <FileQuestion size={22} />
          <div><strong>计划暂不可用</strong><p>{error}</p></div>
          <button type="button" onClick={() => void requestPlan(objective)}>重试</button>
        </section>
      ) : null}

      {plan ? (
        <div className={styles.workspace}>
          <section className={styles.planHeader}>
            <div>
              <span className={styles.sectionEyebrow}>TRUSTED PLAN · {plan.intent.label}</span>
              <h2>{plan.objective.text}</h2>
              <p>{plan.intent.interpretation}；目标文本不会改变业务事实。</p>
            </div>
            <div className={styles.planMeta}>
              <span className={styles.statusDot} />
              <div><small>计划状态</small><strong>{plan.status === "needs_evidence" ? "需要补证" : "待人工复核"}</strong></div>
              <div><small>真源时间</small><strong>{formatAsOf(plan.source_snapshots.source_as_of)}</strong></div>
              <div title={plan.plan_sha256}><small>计划指纹</small><strong>{shortHash(plan.plan_sha256)}</strong></div>
            </div>
          </section>

          <section className={styles.metrics}>
            <article><CheckCircle2 size={18} /><div><small>已验证事实</small><strong>{plan.truth_ledger.verified_facts.length}</strong></div></article>
            <article><FileQuestion size={18} /><div><small>明确 Unknown</small><strong>{plan.truth_ledger.unknowns.length}</strong></div></article>
            <article><Workflow size={18} /><div><small>任务合同</small><strong>{plan.missions.length}</strong></div></article>
            <article><Users size={18} /><div><small>责任 Agent</small><strong>{selectedAgents.length}</strong></div></article>
          </section>

          <section className={styles.twoColumn}>
            <article className={styles.panel}>
              <header>
                <div><span>02 · TRUTH LEDGER</span><h3>先看事实，再谈策略</h3></div>
                <Database size={19} />
              </header>
              <div className={styles.factGrid}>
                {plan.truth_ledger.verified_facts.map((fact) => (
                  <div key={fact.id}>
                    <span>{fact.label}</span>
                    <strong>{fact.value}<small> {fact.unit}</small></strong>
                    <p>{fact.fact_type.replaceAll("_", " ")}</p>
                  </div>
                ))}
              </div>
              <footer>
                <Fingerprint size={14} />
                Analytics {shortHash(plan.source_snapshots.operating_analytics)}
              </footer>
            </article>

            <article className={`${styles.panel} ${styles.unknownPanel}`}>
              <header>
                <div><span>UNKNOWN REGISTER</span><h3>不知道，就明确写不知道</h3></div>
                <FileQuestion size={19} />
              </header>
              <div className={styles.unknownList}>
                {plan.truth_ledger.unknowns.slice(0, 6).map((item) => (
                  <div key={item.id}>
                    <span />
                    <div><strong>{item.label}</strong><p>{item.reason}</p></div>
                  </div>
                ))}
              </div>
              <footer>synthetic fill = OFF · 无真实历史不画趋势</footer>
            </article>
          </section>

          <section className={`${styles.panel} ${styles.missionPanel}`}>
            <header>
              <div><span>03 · MISSION STACK</span><h3>目标到证据的执行前任务链</h3><p>排序由服务端合同拥有；任务完成仍需重新投影和人工复核。</p></div>
              <Target size={20} />
            </header>
            <div className={styles.missionStack}>
              {plan.missions.map((mission) => (
                <article key={mission.id} className={mission.objective_relevant ? styles.relevantMission : ""}>
                  <div className={styles.missionRank}>{String(mission.rank).padStart(2, "0")}</div>
                  <div className={styles.missionBody}>
                    <div className={styles.missionTitle}>
                      <span>{mission.stage_step} · {mission.agent.name}</span>
                      <h4>{mission.title}</h4>
                    </div>
                    <p>{mission.rationale}</p>
                    <div className={styles.progressTrack}><span style={{ width: `${mission.progress.percent}%` }} /></div>
                    <div className={styles.missionFooter}>
                      <span className={`${styles.missionStatus} ${styles[mission.status]}`}>{statusLabel[mission.status]}</span>
                      <span>{mission.progress.current} / {mission.progress.target}</span>
                      <span>{mission.next_action}</span>
                    </div>
                  </div>
                  <Link href={`/#${mission.workspace}`} title="进入既有工作区">
                    <ArrowRight size={18} />
                  </Link>
                </article>
              ))}
            </div>
          </section>

          <section className={styles.twoColumn}>
            <article className={`${styles.panel} ${styles.agentPanel}`}>
              <header>
                <div><span>04 · AGENT MESH</span><h3>专家分工，不是角色扮演</h3></div>
                <Bot size={20} />
              </header>
              <div className={styles.agentGrid}>
                {plan.agent_team.map((agent) => (
                  <div className={agent.selected_for_objective ? styles.selectedAgent : ""} key={agent.agent_id}>
                    <span>{agent.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span>
                    <div><strong>{agent.name}</strong><p>{agent.current_focus}</p></div>
                    <small>{agent.work_item_count}</small>
                  </div>
                ))}
              </div>
            </article>

            <article className={`${styles.panel} ${styles.controlPanel}`}>
              <header>
                <div><span>CONTROL ENVELOPE</span><h3>AI 能做什么，不能做什么</h3></div>
                <ShieldCheck size={20} />
              </header>
              <div className={styles.controlState}>
                <div><CheckCircle2 size={16} /><span>解释、排序、分派、导航</span><b>ON</b></div>
                <div><LockKeyhole size={16} /><span>平台写入与自动执行</span><b>OFF</b></div>
              </div>
              <div className={styles.forbiddenList}>
                {plan.control_envelope.forbidden_actions.slice(0, 6).map((item) => <span key={item}>{item}</span>)}
              </div>
              <footer>{plan.control_envelope.continuation_rule}</footer>
            </article>
          </section>
        </div>
      ) : busy ? (
        <section className={styles.loadingState}>
          <Radar className={styles.spin} size={26} />
          <strong>正在交叉读取经营简报与分析快照</strong>
          <p>事实不会由页面猜测，缺失数据会继续保持 unknown。</p>
        </section>
      ) : null}
    </main>
  );
}
