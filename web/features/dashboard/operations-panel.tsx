"use client";

import { ChevronRight, Download, ShieldCheck } from "lucide-react";
import type { DashboardModel } from "./use-dashboard-controller";


export function OperationsPanel({ model }: { model: DashboardModel }) {
  const { activatePilot, attestPilotControl, createReadOnlyPilot, evidenceRecords, gateReadiness, lifecycleBusy, nextStartupStep, operationalIncidents, operationsQueue, pilotEvaluations, readOnlyPilots, requirement, reviewPilot, scanOperationsQueue, startupSteps, submitPilotReview } = model;
  return <><section className="startup-path" aria-labelledby="startup-path-title">
          <div className="startup-path-head">
            <div><p className="eyebrow">START HERE</p><h3 id="startup-path-title">真实业务启动路径</h3></div>
            <div className={nextStartupStep ? "startup-next" : "startup-next ready"}>
              <span>{nextStartupStep ? "当前下一步" : "资料条件已齐"}</span>
              <strong>{nextStartupStep?.title ?? "等待阶段门人工复核"}</strong>
            </div>
          </div>
          <p className="startup-explainer">按顺序准备真实资料。模板只帮助收集，不会代替原始凭证、独立审批或平台权限验证。</p>
          <div className="startup-boundary" role="note" aria-label="本地资料预检与系统证据状态边界">
            <strong>两层状态不要混淆</strong>
            <p>本地资料包只检查必填项是否齐全；下方卡片只认系统 Evidence、Passport、事实账与人工审批。两者都不会自动上架。</p>
            <code>uv run python scripts/validate_startup_package.py .runtime/startup-intake --require-review-ready</code>
          </div>
          <div className="startup-step-grid">
            {startupSteps.map((step, index) => {
              const state = requirement(step.id);
              return <article className={state?.ready ? "startup-step ready" : "startup-step"} key={step.id}>
                <div><span>{index + 1}</span><b>{step.id} · 系统证据</b><em>{state?.ready ? "已满足" : `${state?.current ?? 0}/${state?.target ?? "-"}`}</em></div>
                <strong>{step.title}</strong>
                <p>{state?.ready ? "证据条件已满足，等待人工阶段门复核。" : state?.next_action ?? "正在读取真实准入状态…"}</p>
                <footer>
                  {step.template ? <a href={step.template} download><Download size={13} />{step.templateLabel}</a> : null}
                  {step.secondaryTemplate ? <a href={step.secondaryTemplate} download><Download size={13} />{step.secondaryTemplateLabel}</a> : null}
                  <a className="primary" href={step.href} target={step.href.startsWith("https://") ? "_blank" : undefined} rel={step.href.startsWith("https://") ? "noreferrer" : undefined}>{step.actionLabel}<ChevronRight size={13} /></a>
                </footer>
              </article>;
            })}
          </div>
        </section><section className="decision-workbench" id="operations-control">
          <div className="panel-title"><div><p className="eyebrow">OPERATIONS CONTROL</p><h3>今日异常中心与 Ozon 只读试点</h3></div><button type="button" disabled={lifecycleBusy === "operations-scan"} onClick={scanOperationsQueue}>扫描逾期升级</button></div>
          <p className="section-copy">Gate 阻断来自服务端 readiness，不伪造 SLA；事故、命令和观察合同继续按真实截止时间升级。这里只解释和导航，不会自动补证、关事故或写平台。</p>
          <div className="lifecycle-summary"><article><span>经营阻断</span><b>{gateReadiness?.exception_workspace.blocked_count ?? 0}</b><small>按 Gate、来源对象和责任角色展示</small></article><article><span>运行待处理</span><b>{operationsQueue.length}</b><small>事故、命令和观察合同按 SLA 排序</small></article><article><span>已逾期</span><b>{operationsQueue.filter((item) => item.overdue).length}</b><small>只升级提醒，不自动执行经营动作</small></article><article><span>未关闭事故</span><b>{operationalIncidents.filter((item) => item.status !== "closed").length}</b><small>严重事故阻断试点准入</small></article></div>
          <div className="decision-layout">
            <div className="decision-register"><div className="decision-register-head"><strong>经营阻断与运行异常</strong><span>{(gateReadiness?.exception_workspace.blocked_count ?? 0) + operationsQueue.length} 项</span></div>{gateReadiness?.exception_workspace.items.map((item) => <article key={item.queue_key}><div><span>{item.gate} · {item.attention === "current_gate" ? "当前门" : "后续门"}</span><b>{item.current}/{item.target}</b></div><strong>{item.source_id} · {item.title}</strong><small>责任角色：{item.owner_role} · 来源：{item.source_type}</small><p>{item.next_action}</p></article>)}{operationsQueue.slice(0, Math.max(0, 8 - (gateReadiness?.exception_workspace.blocked_count ?? 0))).map((item) => <article key={item.queue_key}><div><span>{item.priority} · L{item.escalation_level}</span><b>{item.overdue ? `逾期 ${item.overdue_minutes} 分钟` : item.status}</b></div><strong>{item.title}</strong><small>截止 {new Date(item.due_at).toLocaleString("zh-CN")} · {item.owner_id ?? "待领取"}</small><p>{item.next_action}</p></article>)}{!(gateReadiness?.exception_workspace.blocked_count || operationsQueue.length) && <div className="empty"><ShieldCheck size={25} /><strong>当前没有待处理异常</strong><p>Gate 阻断由 readiness 计算；运行队列只展示事故、执行命令和观察窗口。</p></div>}</div>
            <form className="decision-form" onSubmit={createReadOnlyPilot}><div className="decision-form-head"><div><strong>建立 Ozon 只读试点</strong><small>不保存凭证，不允许商品、价格、广告或库存写入</small></div><ShieldCheck size={19} /></div><div className="decision-fields"><label>账户别名<input name="pilot_account_alias" placeholder="例如 ozon-ru-main（不得填写密钥）" required /></label><label>每日请求上限<input name="pilot_daily_limit" type="number" min="1" max="10000" defaultValue="100" required /></label><label>最大目标数<input name="pilot_target_limit" type="number" min="1" max="1000" defaultValue="10" required /></label><label>准入证据<select name="pilot_evidence" defaultValue="" required><option value="">选择账户范围或运行手册证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select></label><label>开始时间<input name="pilot_starts_at" type="datetime-local" required /></label><label>结束时间<input name="pilot_ends_at" type="datetime-local" required /></label><label className="wide">允许的只读能力<span><input name="pilot_operations" type="checkbox" value="ozon.product.read" />商品读取　<input name="pilot_operations" type="checkbox" value="ozon.inventory.read" />库存读取　<input name="pilot_operations" type="checkbox" value="ozon.orders.read" />订单读取　<input name="pilot_operations" type="checkbox" value="ozon.analytics.read" />分析读取　<input name="pilot_operations" type="checkbox" value="ozon.finance.read" />财务读取</span></label></div><div className="decision-submit"><p>最长 14 天；即使批准并激活，仍固定 execution_eligible=false。</p><button disabled={lifecycleBusy === "pilot-create"}>固化只读试点边界</button></div></form>
          </div>
          {readOnlyPilots.map((pilot) => { const evaluation = pilotEvaluations[pilot.id]; return <article className="policy-card" key={pilot.id}><div className="policy-card-head"><div><strong>{pilot.account_alias} · {pilot.status}</strong><small>{pilot.allowed_operations.join("、")} · 日限额 {pilot.max_daily_requests}</small></div><span className={evaluation?.ready_for_review ? "gate ready" : "gate blocked"}>{evaluation?.ready_for_review ? "准入条件齐备" : "仍有阻断项"}</span></div><div className="knowledge-status invalid"><strong>平台写入：永久禁止</strong><span>不保存凭证材料 · 不授予执行资格</span><b>自动激活：禁止</b></div>{["draft", "changes_requested"].includes(pilot.status) && <form className="policy-outcome-form" onSubmit={(event) => attestPilotControl(event, pilot)}><strong>逐项提交准入控制</strong><select name="pilot_control" defaultValue="" required><option value="">选择未完成控制项</option>{pilot.required_controls.filter((control) => !pilot.controls[control]?.passed).map((control) => <option value={control} key={control}>{control}</option>)}</select><input name="pilot_control_notes" placeholder="验证方法和结果" required /><select name="pilot_control_evidence" defaultValue="" required><option value="">选择控制证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `pilot-attest:${pilot.id}`}>记录控制项</button>{evaluation?.ready_for_review && <button type="button" disabled={lifecycleBusy === `pilot-submit:${pilot.id}`} onClick={() => submitPilotReview(pilot)}>提交独立复核</button>}</form>}{pilot.status === "pending_review" && <form className="policy-outcome-form" onSubmit={(event) => reviewPilot(event, pilot)}><strong>独立准入复核</strong><select name="pilot_review_verdict" defaultValue="" required><option value="">选择结论</option><option value="accepted">批准只读试点</option><option value="rejected">要求补充控制</option></select><input name="pilot_review_rationale" placeholder="独立复核理由" required /><button disabled={lifecycleBusy === `pilot-review:${pilot.id}`}>提交复核</button></form>}{pilot.status === "approved" && <button type="button" disabled={lifecycleBusy === `pilot-activate:${pilot.id}`} onClick={() => activatePilot(pilot)}>管理员重新核验并激活只读试点</button>}{evaluation?.blockers.length ? <footer><span>阻断：{evaluation.blockers.join("、")}</span><b>不得激活</b></footer> : <footer><span>近期演练 {evaluation?.recent_drill_ids.length ?? 0} 次</span><b>仍无写权限</b></footer>}</article>; })}
        </section></>;
}
