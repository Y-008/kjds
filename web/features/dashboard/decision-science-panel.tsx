"use client";

import { BrainCircuit, Clock3, FlaskConical, ShieldCheck, Waypoints } from "lucide-react";
import { decisionStatusLabels } from "./dashboard-config";
import type { DashboardModel } from "./use-dashboard-controller";


export function DecisionSciencePanel({ model }: { model: DashboardModel }) {
  const { analysisHardConstraints, analysisNeedsForecast, analysisOptions, assessCapabilityEconomics, capabilityEconomicAssessments, causalExperimentReviews, causalExperiments, causalKnowledge, causalPolicies, claimIncident, closeIncident, compileDecisionContract, createExecutionPlan, createObservationWindow, decisionAnalyses, decisionBusy, decisionCalibration, decisionContracts, decisionOutcomes, decisionResolutions, decisionReviews, dryRunExecutionPlan, evidenceRecords, executionObservationWindows, experimentEvaluations, experimentResolutions, governedExecutionPlans, interactionProfiles, isBestSolutionAnalysis, lifecycleBusy, limitedExecutionCommands, operationalIncidents, policyActivationHandoffs, policyShadowBatches, proposeCausalPolicy, publishCausalKnowledge, queueLimitedExecution, recordCausalPolicyOutcome, recordDecisionOutcome, recordExecutionObservation, recordExperimentSafety, recordIncidentCheck, registerCausalExperiment, releaseCausalPolicyStage, releaseIncidentFreeze, requestPolicyActivation, resolveDecisionAnalysis, reviewCausalExperiment, reviewCausalPolicy, reviewDecisionAnalysis, reviewIncident, runPolicyShadowBatch, selectedAnalysisContract, selectedAnalysisContractId, selectedAnalysisOptionId, selectedProfile, selectedProfileId, setSelectedAnalysisContractId, setSelectedAnalysisOptionId, setSelectedProfileId, submitDecisionAnalysis, submitIncidentReview, transitionCausalExperiment } = model;
  return <><section className="decision-workbench">
          <div className="panel-title">
            <div><p className="eyebrow">DECISION CONTRACT COMPILER</p><h3>把问题变成可审计的决策合同</h3></div>
            <span className="gate ready">只分析，不执行经营动作</span>
          </div>
          <div className="procurement-guardrail"><ShieldCheck size={17} /><p><strong>“深度思考”等口令只负责选择流程。</strong><span>证据、备选方案、损失上限、责任人与人工审批仍是硬门槛；缺什么就明确显示什么。</span></p></div>
          <div className="interaction-mode-grid">
            {interactionProfiles.map((profile) => <button type="button" className={selectedProfileId === profile.id ? "selected" : ""} onClick={() => setSelectedProfileId(profile.id)} key={profile.id}>
              <span>{profile.aliases.join(" · ")}</span><strong>{profile.label}</strong><small>{profile.description}</small><em>v{profile.version}</em>
            </button>)}
          </div>
          <div className="decision-layout">
            <form className="decision-form" onSubmit={compileDecisionContract}>
              <div className="decision-form-head"><div><strong>{selectedProfile?.label ?? "选择一种工作方式"}</strong><small>{selectedProfile?.workflow_steps.join(" → ")}</small></div><BrainCircuit size={19} /></div>
              <div className="decision-fields">
                <label className="wide">你要解决的真实问题<textarea name="decision_objective" placeholder="例如：是否应把某 SKU 的首批样品量从 100 件增加到 300 件？" required /></label>
                <label>决策领域<input name="decision_domain" defaultValue="operations" placeholder="采购 / 定价 / 广告" required /></label>
                <label>风险等级<select name="decision_risk" defaultValue="medium"><option value="low">低风险</option><option value="medium">中风险</option><option value="high">高风险</option><option value="critical">重大不可逆风险</option></select></label>
                <label>最坏可承受损失<input name="decision_maximum_loss" type="number" min="0" step="0.01" placeholder="高风险问题必须填写" /></label>
                <label>币种<input name="decision_currency" defaultValue="CNY" maxLength={3} /></label>
                <label>观察期限（天）<input name="decision_horizon" type="number" min="1" max="3650" placeholder="预测模式必须填写" /></label>
                <label>可验证证据<select name="decision_evidence" defaultValue=""><option value="">暂未选择；系统会标为待证据</option>{evidenceRecords.slice(0, 100).map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename} · {item.source}</option>)}</select></label>
                {selectedProfile?.presentation_only && <label className="wide">要解释的来源合同<select name="source_contract_id" defaultValue=""><option value="">选择一份已有合同</option>{decisionContracts.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.objective}</option>)}</select></label>}
                {selectedProfile?.requires_options && <label className="wide">备选方案（每行一个，至少两个）<textarea name="decision_options" placeholder={"方案 A\n方案 B\n不行动"} /></label>}
                {selectedProfile?.id === "best_solution" && <><label className="wide">不可突破的硬约束（每行一个）<textarea name="decision_hard_constraints" placeholder={"必须有一手证据\n不得越权或自动执行\n最坏损失不得超过预算"} /></label><label className="wide">比较维度（每行一个）<textarea name="decision_criteria" defaultValue={"长期风险调整价值\n证据质量\n总拥有成本\n可逆性与回滚\n落地时间\n运维适配"} /></label></>}
                {selectedProfile?.requires_forecast_basis && <><label className="wide">基准情景 / 基础概率<textarea name="forecast_baseline" placeholder="写明历史基准、匹配样本或基础概率及其来源" /></label><label className="wide">未来情景（每行一个，至少两个）<textarea name="forecast_scenarios" placeholder={"基准情景\n下行情景\n上行情景"} /></label></>}
                <label className="wide">当前假设（每行一个）<textarea name="decision_assumptions" placeholder="尚未证实、但本轮暂时采用的前提" /></label>
                <label className="wide">已知未知项（每行一个）<textarea name="decision_unknowns" placeholder="缺少的数据、规则、责任人或外部条件" /></label>
              </div>
              <div className="decision-submit"><p>提交后生成不可变合同。即便“可以分析”，也不能直接改价、投放、采购或付款。</p><button disabled={decisionBusy}>{decisionBusy ? "正在编译…" : "建立决策合同"}</button></div>
            </form>
            <div className="decision-register">
              <div className="decision-register-head"><strong>最近的决策合同</strong><span>{decisionContracts.length} 份</span></div>
              {decisionContracts.length ? decisionContracts.slice(0, 6).map((contract) => <article key={contract.id}>
                <div><span>{interactionProfiles.find((item) => item.id === contract.profile_id)?.label ?? contract.profile_id}</span><b>{decisionStatusLabels[contract.status] ?? contract.status}</b></div>
                <strong>{contract.objective}</strong>
                <small>{contract.decision_domain} · {contract.risk_level} · v{contract.profile_version}</small>
                {contract.missing_inputs.length > 0 && <p>待补：{contract.missing_inputs.join("、")}</p>}
                <footer><span>{contract.evidence_ids.length} 份证据</span><em>{contract.requires_human_approval ? "必须人工审批" : "分析合同"}</em><b>无执行权</b></footer>
              </article>) : <div className="empty"><BrainCircuit size={25} /><strong>还没有决策合同</strong><p>先选择工作方式，再把第一个真实经营问题提交进来。</p></div>}
            </div>
          </div>
        </section><section className="decision-lifecycle-panel">
          <div className="panel-title">
            <div><p className="eyebrow">DECISION LEARNING LOOP</p><h3>分析 → 独立复核 → 正式决定 → 结果回填</h3></div>
            <span className="badge">分权留痕 · 预测可校准</span>
          </div>
          <div className="lifecycle-summary">
            <article><span>分析</span><b>{decisionAnalyses.length}</b><small>提交人不能自审</small></article>
            <article><span>正式决定</span><b>{decisionResolutions.length}</b><small>仍然没有执行权</small></article>
            <article><span>真实结果</span><b>{decisionOutcomes.length}</b><small>证据到期后回填</small></article>
            <article><span>区间命中率</span><b>{decisionCalibration.length ? `${(Number(decisionCalibration[0].interval_coverage) * 100).toFixed(0)}%` : "待形成"}</b><small>{decisionCalibration.length ? `${decisionCalibration[0].outcome_count} 次可核验预测` : "先完成一次结果闭环"}</small></article>
          </div>
          <div className="lifecycle-grid">
            <form className="lifecycle-form" onSubmit={submitDecisionAnalysis}>
              <div className="lifecycle-form-title"><span>1</span><div><strong>提交证据化分析</strong><small>{isBestSolutionAnalysis ? "先过硬约束，再比较长期价值与总成本" : "必须先给出预测值、区间和回填日期"}</small></div></div>
              <label>可分析合同<select name="analysis_contract_id" value={selectedAnalysisContractId} onChange={(event) => { setSelectedAnalysisContractId(event.target.value); setSelectedAnalysisOptionId(""); }} required><option value="">选择一份已就绪合同</option>{decisionContracts.filter((item) => item.status === "ready_for_analysis" && ["decision_review", "best_solution", "probabilistic_forecast"].includes(item.profile_id)).map((item) => <option value={item.id} key={item.id}>{item.objective}</option>)}</select></label>
              {selectedAnalysisContract && ["decision_review", "best_solution"].includes(selectedAnalysisContract.profile_id) && <label>推荐方案<select name="analysis_option_id" value={selectedAnalysisOptionId} onChange={(event) => setSelectedAnalysisOptionId(event.target.value)} required><option value="">选择合同中的方案</option>{analysisOptions.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.label}</option>)}</select></label>}
              <label>分析结论<textarea name="analysis_conclusion" placeholder="结论必须说明为什么，并保留未知项" required /></label>
              <label>置信度<input name="analysis_confidence" type="number" min="0" max="1" step="0.01" defaultValue="0.6" required /></label>
              {analysisNeedsForecast && <><div className="lifecycle-pair"><label>预测指标<input name="analysis_metric" placeholder="例如 30天 CM3" required /></label><label>单位<input name="analysis_unit" defaultValue="CNY" required /></label></div><div className="lifecycle-triple"><label>预测值<input name="analysis_value" type="number" step="0.01" required /></label><label>下界<input name="analysis_low" type="number" step="0.01" required /></label><label>上界<input name="analysis_high" type="number" step="0.01" required /></label></div><label>结果回填时间<input name="analysis_due_at" type="datetime-local" required /></label></>}
              {isBestSolutionAnalysis && <div className="best-solution-assessment">
                <strong>逐项方案比较</strong>
                <p>每个方案都必须覆盖全部硬约束与六项经营判断；系统不会把“最新”或“最复杂”自动当成最好。</p>
                {analysisOptions.map((option, optionIndex) => <fieldset key={String(option.id)}>
                  <legend>{option.id} · {option.label}</legend>
                  {analysisHardConstraints.map((constraint, constraintIndex) => <div className="lifecycle-pair" key={`${option.id}-${constraint}`}><label>{constraint}<select name={`best_constraint_${optionIndex}_${constraintIndex}_passed`} defaultValue="false" required><option value="false">不满足</option><option value="true">满足</option></select></label><label>判断依据<input name={`best_constraint_${optionIndex}_${constraintIndex}_rationale`} placeholder="引用证据或说明缺口" required /></label></div>)}
                  <label>证据质量<select name={`best_evidence_quality_${optionIndex}`} defaultValue="UNKNOWN" required><option value="A">A · 官方原件/直接事实</option><option value="B">B · 可靠二手/独立复核</option><option value="C">C · 第三方参考</option><option value="D">D · 弱信号</option><option value="UNKNOWN">未知</option></select></label>
                  <label>长期风险调整价值<textarea name={`best_long_term_value_${optionIndex}`} required /></label>
                  <label>总拥有成本<textarea name={`best_tco_${optionIndex}`} placeholder="建设、采购、运维、迁移、失败和人工成本" required /></label>
                  <label>最大损失<textarea name={`best_maximum_loss_${optionIndex}`} required /></label>
                  <label>可逆性与回滚<textarea name={`best_rollback_${optionIndex}`} required /></label>
                  <label>见效时间<textarea name={`best_time_to_value_${optionIndex}`} required /></label>
                  <label>现有团队与系统适配<textarea name={`best_operational_fit_${optionIndex}`} required /></label>
                  {selectedAnalysisOptionId && selectedAnalysisOptionId !== String(option.id) && <label>淘汰该方案的原因<textarea name={`best_rejection_reason_${optionIndex}`} required /></label>}
                </fieldset>)}
                <label>不行动方案<select name="best_no_action_option_id" defaultValue=""><option value="">合同中没有明确的不行动方案</option>{analysisOptions.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.label}</option>)}</select></label>
                <label>若没有不行动方案，说明原因<textarea name="best_no_action_omission_reason" /></label>
                <label>敏感性驱动因素（每行一个）<textarea name="best_sensitivity_drivers" required /></label>
                <label>结论失效条件（每行一个）<textarea name="best_invalidation_conditions" required /></label>
                <label>重新审查时间<input name="best_review_at" type="datetime-local" required /></label>
                <label>审批要求<textarea name="best_approval_requirement" placeholder="谁复核、谁批准、什么条件下才能进入执行" required /></label>
              </div>}
              <label>分析证据<select name="analysis_evidence" defaultValue="" required><option value="">选择原始证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select></label>
              <label>分析者 / 模型版本<input name="analysis_model_ref" placeholder="例如 human+qwen-v3" /></label>
              <label>关键假设（每行一个）<textarea name="analysis_assumptions" /></label><label>剩余未知项（每行一个）<textarea name="analysis_unknowns" /></label>
              <button disabled={lifecycleBusy === "analysis" || !selectedAnalysisContractId}>{lifecycleBusy === "analysis" ? "正在固化…" : "提交分析，进入独立复核"}</button>
            </form>

            <div className="analysis-review-queue">
              <div className="lifecycle-form-title"><span>2</span><div><strong>独立复核与正式决定</strong><small>分析者、复核者、重大决策者按风险分离</small></div></div>
              {decisionAnalyses.length ? decisionAnalyses.slice(0, 4).map((item) => {
                const reviews = decisionReviews[item.id] ?? [];
                const contract = decisionContracts.find((row) => row.id === item.contract_id);
                const blocking = reviews.some((row) => row.verdict !== "accepted");
                const requiredReviews = contract?.risk_level === "critical" ? 2 : 1;
                const acceptedCount = reviews.filter((row) => row.verdict === "accepted").length;
                const resolution = decisionResolutions.find((row) => row.analysis_id === item.id);
                return <article className="analysis-review-card" key={item.id}>
                  <div className="analysis-review-head"><div><strong>{item.conclusion}</strong><small>{contract?.risk_level ?? "-"} · 置信度 {(Number(item.confidence) * 100).toFixed(0)}% · {item.submitted_by}</small></div><span>{resolution ? "已决定" : blocking ? "需重做" : `${acceptedCount}/${requiredReviews} 复核`}</span></div>
                  {item.forecast && <p>预测 {item.forecast.value} {item.forecast.unit} · 区间 {item.forecast.low}–{item.forecast.high} · {new Date(item.forecast.due_at).toLocaleDateString("zh-CN")} 回填</p>}
                  {contract?.profile_id === "best_solution" && <p>推荐 {item.recommended_option_id} · 已记录 {Array.isArray(item.selection_assessment.rejected_options) ? item.selection_assessment.rejected_options.length : 0} 个淘汰理由 · 仍需反方审查</p>}
                  {reviews.map((review) => <div className={`review-result ${review.verdict}`} key={review.id}><b>{review.verdict}</b><span>{review.rationale}</span><small>{review.reviewed_by}</small></div>)}
                  {!blocking && !resolution && acceptedCount < requiredReviews && <form className="mini-lifecycle-form" onSubmit={(event) => reviewDecisionAnalysis(event, item.id)}>
                    <select name="review_verdict" defaultValue="accepted"><option value="accepted">证据支持</option><option value="needs_revision">需要修订</option><option value="rejected">拒绝结论</option></select>
                    <textarea name="review_rationale" placeholder="独立复核理由" required />
                    <textarea name="review_counterarguments" placeholder="反方解释（每行一个）" required={contract?.profile_id === "best_solution"} />
                    <select name="review_evidence" defaultValue=""><option value="">无新增证据（接受结论时必须选择）</option>{evidenceRecords.map((evidence) => <option value={evidence.id} key={evidence.id}>{evidence.grade} · {evidence.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === item.id}>提交独立复核</button>
                  </form>}
                  {!blocking && !resolution && acceptedCount >= requiredReviews && <form className="mini-lifecycle-form resolution" onSubmit={(event) => resolveDecisionAnalysis(event, item)}>
                    <select name="resolution_disposition" defaultValue="experiment"><option value="experiment">受控实验</option><option value="adopt">采纳方案</option><option value="defer">暂缓</option><option value="reject">拒绝</option></select>
                    <textarea name="resolution_rationale" placeholder="正式决定理由" required /><textarea name="resolution_conditions" placeholder="执行前条件（每行一个）" />
                    <button disabled={lifecycleBusy === item.id}>固化正式决定</button>
                  </form>}
                  {blocking && <p className="lifecycle-warning">存在阻断复核。不能覆盖旧分析，请基于反馈提交一份新分析。</p>}
                  {resolution && <div className="resolution-result"><b>{resolution.disposition}</b><span>{resolution.rationale}</span><em>无执行权</em></div>}
                </article>;
              }) : <div className="empty"><BrainCircuit size={24} /><strong>等待第一份分析</strong><p>合同就绪后，先提交带预测区间的分析。</p></div>}
            </div>

            <div className="outcome-queue">
              <div className="lifecycle-form-title"><span>3</span><div><strong>真实结果与校准</strong><small>只接受到期后的证据化事实</small></div></div>
              {decisionResolutions.filter((item) => ["adopt", "experiment"].includes(item.disposition)).length ? decisionResolutions.filter((item) => ["adopt", "experiment"].includes(item.disposition)).slice(0, 4).map((resolution) => {
                const outcome = decisionOutcomes.find((item) => item.resolution_id === resolution.id);
                const selectedAnalysis = decisionAnalyses.find((item) => item.id === resolution.analysis_id);
                return <article className="outcome-card" key={resolution.id}>
                  <div><strong>{selectedAnalysis?.forecast?.metric ?? "待回填指标"}</strong><span>{resolution.disposition}</span></div>
                  {selectedAnalysis?.forecast && <small>预测 {selectedAnalysis.forecast.value} {selectedAnalysis.forecast.unit} · 到期 {new Date(selectedAnalysis.forecast.due_at).toLocaleString("zh-CN")}</small>}
                  {outcome ? <div className={`outcome-result ${outcome.interval_covered ? "covered" : "missed"}`}><b>实际 {outcome.actual_value} {outcome.unit}</b><span>误差 {outcome.signed_error}</span><em>{outcome.interval_covered ? "区间命中" : "区间未命中"}</em></div> : <form className="mini-lifecycle-form" onSubmit={(event) => recordDecisionOutcome(event, resolution.id)}>
                    <input name="outcome_actual" type="number" step="0.01" placeholder="实际结果" required /><input name="outcome_observed_at" type="datetime-local" required />
                    <select name="outcome_evidence" defaultValue="" required><option value="">选择结果证据</option>{evidenceRecords.map((evidence) => <option value={evidence.id} key={evidence.id}>{evidence.grade} · {evidence.filename}</option>)}</select>
                    <textarea name="outcome_notes" placeholder="结果说明与异常" required /><button disabled={lifecycleBusy === resolution.id}>回填真实结果</button>
                  </form>}
                </article>;
              }) : <div className="empty"><Clock3 size={24} /><strong>还没有待回填决定</strong><p>正式采纳或实验后，系统才建立结果回填任务。</p></div>}
              {decisionCalibration.map((item) => <div className="calibration-card" key={`${item.metric}:${item.unit}`}><strong>{item.metric}</strong><span>平均绝对误差 {item.mean_absolute_error} {item.unit}</span><b>区间命中率 {(Number(item.interval_coverage) * 100).toFixed(0)}%</b></div>)}
            </div>
          </div>
        </section><section className="causal-experiment-panel">
          <div className="panel-title">
            <div><p className="eyebrow">CAUSAL EXPERIMENT GATE</p><h3>预注册 → 稳定分流 → SRM 检查 → 独立复核</h3></div>
            <span className="gate ready">实验结果永不自动放量</span>
          </div>
          <div className="procurement-guardrail"><FlaskConical size={17} /><p><strong>先锁定假设与停止条件，再看结果。</strong><span>分流密钥不出系统，原始用户标识不入库；样本比例异常会直接阻断解释。</span></p></div>
          <div className="causal-experiment-layout">
            <form className="experiment-register-form" onSubmit={registerCausalExperiment}>
              <strong>登记一项受控实验</strong>
              <label>试验型正式决议<select name="experiment_resolution_id" required><option value="">选择尚未登记的决议</option>{experimentResolutions.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.rationale}</option>)}</select></label>
              <label className="wide">可证伪假设<textarea name="experiment_hypothesis" placeholder="例如：新版详情页将每访客贡献利润提高至少 5 CNY" required /></label>
              <div className="lifecycle-pair"><label>唯一主指标<input name="experiment_metric" defaultValue="cm3_per_visitor" required /></label><label>随机化单位<input name="experiment_unit" defaultValue="visitor" required /></label></div>
              <div className="lifecycle-pair"><label>干扰集群<input name="experiment_cluster" defaultValue="product_family" placeholder="避免相似 SKU 互相污染" /></label><label>预注册分层字段<input name="experiment_segment_key" placeholder="例如 country_tier；可留空" /></label></div>
              <div className="lifecycle-pair"><label>内部蚕食成本指标<input name="experiment_cannibalization_metric" placeholder="例如 cannibalized_cm3；可留空" /></label><label>长期成本指标<input name="experiment_long_term_cost_metric" placeholder="例如 refund_cost_30d；可留空" /></label></div>
              <div className="lifecycle-pair"><label>对照组<input name="experiment_control_label" defaultValue="现行策略" required /></label><label>实验组<input name="experiment_treatment_label" defaultValue="候选策略" required /></label></div>
              <div className="lifecycle-triple"><label>目标样本<input name="experiment_sample_size" type="number" min="20" defaultValue="100" required /></label><label>最小有意义效果<input name="experiment_mde" type="number" min="0.0001" step="0.0001" defaultValue="5" required /></label><label>结果观察天数<input name="experiment_outcome_days" type="number" min="0" max="365" defaultValue="30" required /></label></div>
              <div className="lifecycle-triple"><label>实验预算<input name="experiment_budget" type="number" min="0.01" step="0.01" required /></label><label>止损线<input name="experiment_stop_loss" type="number" min="0.01" step="0.01" required /></label><label>币种<input name="experiment_currency" defaultValue="CNY" maxLength={3} required /></label></div>
              <div className="lifecycle-pair"><label>开始时间<input name="experiment_start_at" type="datetime-local" required /></label><label>结束时间<input name="experiment_end_at" type="datetime-local" required /></label></div>
              <div className="lifecycle-pair"><label>护栏指标<input name="experiment_guardrail_metric" defaultValue="refund_rate" required /></label><label>最大阈值<input name="experiment_guardrail_threshold" type="number" step="0.0001" defaultValue="0.1" required /></label></div>
              <label>预注册证据<select name="experiment_evidence" defaultValue="" required><option value="">选择原始证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select></label>
              <button disabled={lifecycleBusy === "experiment-register" || !experimentResolutions.length}>{lifecycleBusy === "experiment-register" ? "正在固化…" : "固化实验协议"}</button>
            </form>
            <div className="experiment-register-list">
              {causalExperiments.length ? causalExperiments.map((experiment) => {
                const evaluation = experimentEvaluations[experiment.id];
                const experimentReviews = causalExperimentReviews[experiment.id] ?? [];
                const acceptedReview = experimentReviews.find((item) => item.verdict === "accepted");
                const knowledgeEntry = causalKnowledge.find((item) => item.protocol_id === experiment.id);
                const nextEvent = experiment.status === "registered" ? "started" : experiment.status === "running" ? "paused" : experiment.status === "paused" ? "resumed" : null;
                return <article className="experiment-card" key={experiment.id}>
                  <div className="experiment-card-head"><div><strong>{experiment.hypothesis}</strong><small>{experiment.primary_metric} · {experiment.randomization_unit} · 50/50</small></div><span className={evaluation?.sample_ratio_mismatch ? "gate blocked" : "gate ready"}>{experiment.status}</span></div>
                  <div className="experiment-facts"><span>样本 <b>{evaluation?.observed_count ?? 0}/{experiment.target_sample_size}</b></span><span>分流 <b>{evaluation?.assignment_count ?? 0}</b></span><span>SRM <b>{evaluation?.sample_ratio_mismatch ? "阻断" : "通过"}</b></span><span>安全门 <b>{evaluation?.safety_gate_breached ? "冻结" : "通过"}</b></span></div>
                  <p>{evaluation?.interpretation === "SAFETY_BREACH_FREEZES_ASSIGNMENT" ? "预算、止损或护栏已越线，后续分流已冻结。" : evaluation?.interpretation === "SRM_BLOCKS_DECISION" ? "样本比例异常，禁止解释和决策。" : evaluation?.missing_required_metrics.length ? `仍缺长期/蚕食结果：${evaluation.missing_required_metrics.join("、")}` : evaluation?.review_eligible ? `净增量 ${evaluation.incremental_value_per_unit ?? evaluation.treatment_effect?.absolute_effect ?? "-"}/单位，已达到独立复核条件。` : "继续收集预注册样本，不允许提前挑选赢家。"}</p>
                  {evaluation?.review_eligible && !experimentReviews.length && <form className="causal-review-form" onSubmit={(event) => reviewCausalExperiment(event, experiment)}>
                    <strong>独立复核实验结论</strong>
                    <select name="causal_review_verdict" defaultValue="accepted"><option value="accepted">接受为待登记知识</option><option value="needs_replication">必须先复现</option><option value="rejected">拒绝结论</option></select>
                    <textarea name="causal_review_rationale" placeholder="复核结论与适用限制" required />
                    <textarea name="causal_review_method" placeholder="随机化、干扰、样本与估计方法审查" required />
                    <textarea name="causal_review_data" placeholder="SRM、缺失、异常、币种和长期窗口审查" required />
                    <textarea name="causal_review_counterarguments" placeholder="至少写一个替代解释或反方意见，每行一条" required />
                    <select name="causal_review_evidence" defaultValue="" required><option value="">选择复核证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === `causal-review:${experiment.id}`}>固化独立复核</button>
                  </form>}
                  {acceptedReview && !knowledgeEntry && evaluation?.review_eligible && <form className="causal-knowledge-form" onSubmit={(event) => publishCausalKnowledge(event, experiment, acceptedReview.id)}>
                    <strong>把复核结论登记成有边界的知识</strong>
                    <textarea name="knowledge_claim" defaultValue={experiment.hypothesis} required />
                    <textarea name="knowledge_mechanism" placeholder="为什么有效：动作 → 中介机制 → 结果" required />
                    <div className="lifecycle-pair"><label>平台<input name="knowledge_platform" defaultValue="Ozon" required /></label><label>国家<input name="knowledge_country" defaultValue="RU" required /></label></div>
                    <div className="lifecycle-pair"><label>品类<input name="knowledge_category" placeholder="精确到可迁移边界" required /></label><label>适用人群<input name="knowledge_population" placeholder="例如 eligible-visitors" required /></label></div>
                    <textarea name="knowledge_falsification" placeholder="什么证据出现时必须推翻或暂停使用，每行一条" required />
                    <div className="lifecycle-pair"><label>生效时间<input name="knowledge_valid_from" type="datetime-local" required /></label><label>最晚复验时间<input name="knowledge_reevaluate_at" type="datetime-local" required /></label></div>
                    <select name="knowledge_replication_source" defaultValue=""><option value="">不是复现实验</option>{causalKnowledge.filter((item) => item.usable && item.protocol_id !== experiment.id).map((item) => <option value={item.id} key={item.id}>复现：{item.claim}</option>)}</select>
                    <input name="knowledge_replication_rationale" placeholder="若为复现，说明独立协议和范围关系" />
                    <select name="knowledge_evidence" defaultValue="" required><option value="">选择知识证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === `causal-knowledge:${experiment.id}`}>登记不可变知识</button>
                  </form>}
                  {knowledgeEntry && <div className={knowledgeEntry.usable ? "knowledge-status usable" : "knowledge-status invalid"}><strong>{knowledgeEntry.knowledge_strength}</strong><span>{knowledgeEntry.validity_status} · {knowledgeEntry.usable ? "可供后续策略引用" : "禁止继续引用"}</span><b>执行权：无</b></div>}
                  {experiment.status === "running" && <form className="experiment-safety-form" onSubmit={(event) => recordExperimentSafety(event, experiment)}>
                    <select name="safety_metric" defaultValue="budget_spend_amount"><option value="budget_spend_amount">累计实验支出</option><option value="cumulative_loss_amount">累计实验损失</option>{experiment.guardrails.map((item) => <option value={item.metric} key={item.metric}>{item.metric}</option>)}</select>
                    <input name="safety_value" type="number" step="0.0001" placeholder="当前读数" required />
                    <select name="safety_evidence" defaultValue="" required><option value="">读数证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === `safety:${experiment.id}`}>记录安全读数</button>
                  </form>}
                  {nextEvent && <form className="experiment-event-form" onSubmit={(event) => transitionCausalExperiment(event, experiment, nextEvent)}>
                    <input name="experiment_event_reason" placeholder={nextEvent === "started" ? "启动前检查结论" : nextEvent === "paused" ? "暂停原因" : "恢复原因"} required />
                    <select name="experiment_event_evidence" defaultValue="" required><option value="">选择事件证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === experiment.id}>{nextEvent === "started" ? "人工批准启动" : nextEvent === "paused" ? "暂停实验" : "恢复实验"}</button>
                  </form>}
                  <footer><span>预算 {experiment.budget_cap_amount} {experiment.currency}</span><span>止损 {experiment.stop_loss_amount}</span><b>自动放量：禁止</b></footer>
                </article>;
              }) : <div className="empty"><FlaskConical size={25} /><strong>还没有预注册实验</strong><p>先完成分析、独立复核和“受控实验”正式决议。</p></div>}
            </div>
          </div>
          <div className="causal-knowledge-registry">
            <div className="panel-title"><div><p className="eyebrow">CAUSAL KNOWLEDGE REGISTRY</p><h3>企业因果知识账</h3></div><span className="badge">{causalKnowledge.filter((item) => item.usable).length} 条当前可用</span></div>
            {causalKnowledge.length ? <div className="knowledge-grid">{causalKnowledge.map((item) => <article className={item.usable ? "knowledge-card" : "knowledge-card invalid"} key={item.id}>
              <div><span>{item.knowledge_strength}</span><b>{item.validity_status}</b></div>
              <strong>{item.claim}</strong><p>{item.mechanism}</p>
              <small>{String(item.applicability.platform)} · {String(item.applicability.country)} · {String(item.applicability.category)} · {String(item.applicability.population)}</small>
              {item.usable && !causalPolicies.some((policy) => policy.knowledge_ids.includes(item.id)) && <details><summary>编译为条件策略</summary><form className="causal-policy-form" onSubmit={(event) => proposeCausalPolicy(event, item)}>
                <input name="policy_title" placeholder="策略名称" required /><textarea name="policy_objective" placeholder="策略要解决的决策问题" required />
                <div className="lifecycle-triple"><input name="policy_condition_field" defaultValue="inventory_cover_days" aria-label="条件字段" required /><select name="policy_condition_operator" defaultValue="gte" aria-label="条件比较"><option value="gte">不低于</option><option value="lte">不高于</option><option value="eq">等于</option></select><input name="policy_condition_value" defaultValue="45" aria-label="条件值" required /></div>
                <div className="lifecycle-pair"><select name="policy_action_type" defaultValue="recommend_listing_change"><option value="recommend_listing_change">建议切换详情页</option><option value="recommend_no_action">建议保持不动</option></select><input name="policy_action_variant" defaultValue="treatment" aria-label="候选方案" required /></div>
                <div className="lifecycle-pair"><input name="policy_guardrail_metric" defaultValue="refund_rate" aria-label="护栏指标" required /><input name="policy_guardrail_threshold" defaultValue="0.1" type="number" step="0.0001" aria-label="护栏阈值" required /></div>
                <div className="lifecycle-pair"><input name="policy_shadow_samples" defaultValue="20" type="number" min="0" aria-label="影子阶段最小样本" required /><input name="policy_shadow_value" defaultValue="0" type="number" step="0.0001" aria-label="影子阶段最小增量" required /></div>
                <div className="lifecycle-triple"><input name="policy_limited_fraction" defaultValue="0.1" type="number" min="0.0001" max="1" step="0.0001" aria-label="有限放量比例" required /><input name="policy_limited_samples" defaultValue="100" type="number" min="1" aria-label="有限阶段最小样本" required /><input name="policy_limited_value" defaultValue="3" type="number" step="0.0001" aria-label="有限阶段最小增量" required /></div>
                <select name="policy_evidence" defaultValue="" required><option value="">选择策略证据</option>{evidenceRecords.map((evidenceItem) => <option value={evidenceItem.id} key={evidenceItem.id}>{evidenceItem.grade} · {evidenceItem.filename}</option>)}</select>
                <button disabled={lifecycleBusy === `policy-propose:${item.id}`}>固化条件策略</button>
              </form></details>}
              <footer><span>最晚复验 {new Date(item.reevaluate_at).toLocaleDateString("zh-CN")}</span><b>不会自动执行</b></footer>
            </article>)}</div> : <div className="empty"><BrainCircuit size={24} /><strong>还没有通过复核的因果知识</strong><p>实验完成后先独立复核，再登记适用边界和失效时间。</p></div>}
          </div>
          <div className="causal-policy-registry">
            <div className="panel-title"><div><p className="eyebrow">CONDITIONAL POLICY GATE</p><h3>条件策略与分阶段晋级</h3></div><span className="gate ready">影子 → 有限；逐级人工批准</span></div>
            {causalPolicies.length ? <div className="policy-grid">{causalPolicies.map((policy) => {
              const acceptedReview = policy.reviews.find((item) => item.verdict === "accepted");
              const latestRelease = policy.releases[policy.releases.length - 1];
              const shadowRelease = policy.releases.find((item) => item.stage.max_exposure_fraction === "0");
              const shadowBatch = [...policyShadowBatches].reverse().find((item) => item.policy_id === policy.id && item.release_id === shadowRelease?.id);
              const activationHandoff = policyActivationHandoffs.find((item) => item.policy_id === policy.id);
              const executionPlan = governedExecutionPlans.find((item) => item.policy_id === policy.id);
              const executionCommand = limitedExecutionCommands.find((item) => item.plan_id === executionPlan?.id && item.command_kind === "execute");
              const observationWindow = executionObservationWindows.find((item) => item.command_id === executionCommand?.id);
              const capabilityAssessment = capabilityEconomicAssessments.find((item) => item.window_id === observationWindow?.id);
              const operationalIncident = operationalIncidents.find((item) => item.impact.includes(`observation_window:${observationWindow?.id}`));
              const canReleaseNext = acceptedReview && policy.usable && policy.releases.length < policy.rollout_stages.length && (!latestRelease || latestRelease.outcome?.verdict === "passed");
              return <article className={policy.usable ? "policy-card" : "policy-card invalid"} key={policy.id}>
                <div className="policy-card-head"><div><strong>{policy.title}</strong><small>{policy.validity_status} · 来源知识 {policy.knowledge_ids.length} 条</small></div><span className={policy.usable ? "gate ready" : "gate blocked"}>{policy.usable ? "可评估" : "已冻结"}</span></div>
                <p>{policy.objective}</p><div className="policy-condition"><b>当</b>{policy.conditions.map((item) => <span key={`${item.field}:${item.operator}`}>{item.field} {item.operator} {String(item.value)}</span>)}<b>建议</b><span>{policy.action.type}</span></div>
                {!policy.reviews.length && <form className="policy-review-form" onSubmit={(event) => reviewCausalPolicy(event, policy)}><select name="policy_review_verdict" defaultValue="accepted"><option value="accepted">接受策略合同</option><option value="needs_revision">退回修改</option><option value="rejected">拒绝</option></select><textarea name="policy_review_rationale" placeholder="条件、护栏、退回和阶段门审查" required /><textarea name="policy_review_counterarguments" placeholder="至少一个反方意见" required /><select name="policy_review_evidence" defaultValue="" required><option value="">复核证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button>固化策略复核</button></form>}
                {canReleaseNext && <form className="policy-release-form" onSubmit={(event) => releaseCausalPolicyStage(event, policy, acceptedReview.id)}><strong>下一阶段：{policy.rollout_stages[policy.releases.length].name} · 最大暴露 {(Number(policy.rollout_stages[policy.releases.length].max_exposure_fraction) * 100).toFixed(0)}%</strong><input name="policy_release_rationale" placeholder="批准理由" required /><select name="policy_release_evidence" defaultValue="" required><option value="">阶段批准证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button>人工批准该阶段</button></form>}
                {shadowRelease && !shadowRelease.outcome && <form className="policy-outcome-form" onSubmit={(event) => runPolicyShadowBatch(event, policy, shadowRelease.id)}><strong>运行零暴露影子批次</strong><p>粘贴实际库存覆盖天数，用逗号分隔；仅记录策略会如何判断，不修改任何经营数据。</p><input name="policy_shadow_cover_days" placeholder="例如：60, 52, 47, 31（最多100条）" required /><select name="policy_shadow_evidence" defaultValue="" required><option value="">选择本批数据证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `policy-shadow:${shadowRelease.id}`}>固化影子批次</button></form>}
                {shadowBatch && <div className="knowledge-status usable"><strong>影子批次 {shadowBatch.context_count} 条</strong><span>命中 {shadowBatch.matched_count} · 退回 {shadowBatch.fallback_count} · 暴露 0%</span><b>执行权：无</b></div>}
                {latestRelease && !latestRelease.outcome && <form className="policy-outcome-form" onSubmit={(event) => recordCausalPolicyOutcome(event, policy, latestRelease.id)}><strong>回填 {latestRelease.stage.name} 真实结果</strong><div className="lifecycle-triple"><select name="policy_outcome_verdict" defaultValue="passed"><option value="passed">通过</option><option value="failed">失败</option><option value="inconclusive">不确定</option></select><input name="policy_outcome_count" type="number" min="0" placeholder="观察数" required /><input name="policy_outcome_value" type="number" step="0.0001" placeholder="单位增量" required /></div><select name="policy_outcome_guardrail" defaultValue="false"><option value="false">护栏未越线</option><option value="true">护栏已越线</option></select><textarea name="policy_outcome_notes" placeholder="真实结果说明" required /><select name="policy_outcome_evidence" defaultValue="" required><option value="">结果证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button>固化阶段结果</button></form>}
                {latestRelease && latestRelease.stage.max_exposure_fraction !== "0" && shadowBatch && !activationHandoff && <form className="policy-release-form" onSubmit={(event) => requestPolicyActivation(event, policy, latestRelease.id, shadowBatch)}><strong>移交阶段激活审批</strong><p>只创建独立审批事项；批准后仍不会直接操作平台。</p><select name="policy_handoff_evidence" defaultValue="" required><option value="">选择交接证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `policy-handoff:${latestRelease.id}`}>送入审批中心</button></form>}
                {activationHandoff && <div className={activationHandoff.validity_status === "active" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>审批 {activationHandoff.approval_status}</strong><span>{activationHandoff.validity_status} · {activationHandoff.activation_eligible ? "可进入执行设计" : "不可激活"}</span><b>自动执行：禁止</b></div>}
                {activationHandoff?.activation_eligible && !executionPlan && <form className="policy-outcome-form" onSubmit={(event) => createExecutionPlan(event, activationHandoff)}><strong>建立可回滚执行计划</strong><p>绑定具体 Listing、当前状态指纹、新标题和恢复标题；系统会另行申请执行审批。</p><input name="execution_listing_id" placeholder="Ozon Listing ID" required /><input name="execution_state_hash" minLength={64} maxLength={64} placeholder="当前平台快照 SHA-256" required /><input name="execution_old_title" placeholder="当前标题（用于回滚）" required /><input name="execution_new_title" placeholder="拟更新标题" required /><select name="execution_evidence" defaultValue="" required><option value="">选择当前状态证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `execution-plan:${activationHandoff.id}`}>固化计划并申请执行审批</button></form>}
                {executionPlan && <div className={executionPlan.ready_for_executor ? "knowledge-status usable" : "knowledge-status invalid"}><strong>执行计划 {executionPlan.approval_status}</strong><span>{executionPlan.dry_run?.passed ? "预演通过" : "等待预演"} · {executionPlan.handoff_validity_status}</span><b>平台写入：禁用</b></div>}
                {executionPlan && !executionPlan.dry_run && <form className="policy-release-form" onSubmit={(event) => dryRunExecutionPlan(event, executionPlan)}><strong>执行前预演</strong><p>重新读取平台状态后填写快照指纹；与计划前置状态不一致将失败并要求重建计划。</p><input name="dry_run_state_hash" minLength={64} maxLength={64} defaultValue={executionPlan.precondition_state_hash} required /><select name="dry_run_evidence" defaultValue="" required><option value="">选择最新平台快照证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `execution-dry-run:${executionPlan.id}`}>只做预演</button></form>}
                {executionPlan?.ready_for_executor && executionPlan.live_execution_supported && !executionCommand && <div className="policy-release-form"><strong>受限执行队列</strong><p>默认全局关闭。启用后仍由专用执行器按状态指纹领取，网页不会直接调用 Ozon。</p><button type="button" disabled={lifecycleBusy === `execution-queue:${executionPlan.id}`} onClick={() => queueLimitedExecution(executionPlan)}>进入受限队列</button></div>}
                {executionCommand && <div className={executionCommand.status === "succeeded" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>{executionCommand.command_kind === "rollback" ? "回滚" : "执行"}命令 {executionCommand.status}</strong><span>{executionCommand.claimed_by ? `执行器 ${executionCommand.claimed_by}` : "等待专用执行器领取"}</span><b>远端写入：{executionCommand.platform_write_performed ? "已由回执确认" : "未确认"}</b></div>}
                {executionCommand?.status === "succeeded" && executionCommand.platform_write_performed && !observationWindow && <form className="policy-outcome-form" onSubmit={(event) => createObservationWindow(event, executionCommand)}><strong>固化执行后观察合同</strong><p>预先锁定利润指标、退款护栏、基线和期限。超过护栏会先排队补偿并冻结写操作，不会自动继续放量。</p><div className="lifecycle-pair"><input name="observation_primary_metric" defaultValue="contribution_profit_per_visitor" aria-label="主要结果指标" required /><input name="observation_primary_baseline" defaultValue="0" type="number" step="0.0001" aria-label="主要指标基线" required /></div><div className="lifecycle-pair"><input name="observation_guardrail_metric" defaultValue={policy.guardrails[0]?.metric ?? "refund_rate"} aria-label="护栏指标" required /><input name="observation_guardrail_baseline" defaultValue="0" type="number" step="0.0001" aria-label="护栏基线" required /></div><input name="observation_required_count" defaultValue="2" type="number" min="1" max="10000" aria-label="最少观察数" required /><div className="lifecycle-pair"><input name="observation_starts_at" type="datetime-local" aria-label="观察开始时间" required /><input name="observation_ends_at" type="datetime-local" aria-label="观察结束时间" required /></div><select name="observation_evidence" defaultValue="" required><option value="">选择基线证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `observation-window:${executionCommand.id}`}>锁定观察合同</button></form>}
                {observationWindow && <div className={observationWindow.evaluation.status === "guardrail_breached" ? "knowledge-status invalid" : "knowledge-status usable"}><strong>执行后观察：{observationWindow.evaluation.status}</strong><span>{observationWindow.primary_metric} · 已记录 {observationWindow.observations.length}/{observationWindow.required_observations}</span><b>{observationWindow.evaluation.status === "guardrail_breached" ? "补偿已排队，写操作冻结" : "自动策略晋级：禁止"}</b></div>}
                {observationWindow?.evaluation.status === "monitoring" && <form className="policy-outcome-form" onSubmit={(event) => recordExecutionObservation(event, observationWindow)}><strong>上报真实经营结果</strong><p>只能填写合同内的主指标或护栏指标；记录一经提交不可修改。</p><select name="observed_metric" defaultValue={observationWindow.primary_metric} required><option value={observationWindow.primary_metric}>{observationWindow.primary_metric}</option>{observationWindow.guardrails.map((guardrail) => <option value={guardrail.metric} key={guardrail.metric}>{guardrail.metric}（{guardrail.direction} {guardrail.threshold}）</option>)}</select><input name="observed_value" type="number" step="0.0001" placeholder="实际结果" required /><input name="observed_at" type="datetime-local" aria-label="结果发生时间" required /><select name="observed_evidence" defaultValue="" required><option value="">选择结果证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `observation:${observationWindow.id}`}>记录并核对护栏</button></form>}
                {observationWindow && ["passed", "guardrail_breached"].includes(observationWindow.evaluation.status) && !capabilityAssessment && <form className="policy-outcome-form" onSubmit={(event) => assessCapabilityEconomics(event, observationWindow)}><strong>核算这项能力是否值得保留</strong><p>把实际增量、避免损失、模型费、人工审核、事故损失和维护成本放在同一本账里。金额必须由证据支持。</p><div className="lifecycle-pair"><input name="economics_realized_value" type="number" step="0.01" placeholder="实际增量（可为负）" required /><input name="economics_avoided_loss" type="number" min="0" step="0.01" defaultValue="0" placeholder="避免损失" required /></div><div className="lifecycle-pair"><input name="economics_model_cost" type="number" min="0" step="0.01" defaultValue="0" placeholder="模型与计算成本" required /><input name="economics_review_cost" type="number" min="0" step="0.01" defaultValue="0" placeholder="人工审核成本" required /></div><div className="lifecycle-pair"><input name="economics_incident_loss" type="number" min="0" step="0.01" defaultValue="0" placeholder="事故损失" required /><input name="economics_maintenance_cost" type="number" min="0" step="0.01" defaultValue="0" placeholder="维护成本" required /></div><div className="lifecycle-pair"><input name="economics_currency" defaultValue="CNY" minLength={3} maxLength={3} aria-label="币种" required /><input name="economics_as_of" type="datetime-local" aria-label="核算时间" required /></div><select name="economics_evidence" defaultValue="" required><option value="">选择损益证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `capability-economics:${observationWindow.id}`}>固化能力损益</button></form>}
                {capabilityAssessment && <div className={Number(capabilityAssessment.net_value) > 0 && capabilityAssessment.outcome_status !== "guardrail_breached" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>能力净价值 {capabilityAssessment.net_value} {capabilityAssessment.currency}</strong><span>增量 {capabilityAssessment.realized_incremental_value} · 避免损失 {capabilityAssessment.avoided_loss} · 事故损失 {capabilityAssessment.incident_loss}</span><b>自动权限变更：禁止</b></div>}
                {operationalIncident && <div className={operationalIncident.status === "closed" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>{operationalIncident.mode === "drill" ? "恢复演练" : "生产事故"}：{operationalIncident.status}</strong><span>{operationalIncident.summary} · {Object.keys(operationalIncident.checks).length}/{operationalIncident.required_checks.length} 项恢复检查</span><b>熔断：{operationalIncident.kill_switch_engaged ? "保持" : "已解除"} · 自动解除：禁止</b></div>}
                {operationalIncident && !operationalIncident.owner_id && <button type="button" disabled={lifecycleBusy === `incident-claim:${operationalIncident.id}`} onClick={() => claimIncident(operationalIncident)}>领取事故恢复责任</button>}
                {operationalIncident?.status === "recovering" && <form className="policy-outcome-form" onSubmit={(event) => recordIncidentCheck(event, operationalIncident)}><strong>恢复检查表</strong><p>远端状态、回滚、数据、凭证和监控必须逐项提供证据，不能一键全部通过。</p><select name="incident_check" defaultValue="" required><option value="">选择待确认项目</option>{operationalIncident.required_checks.filter((check) => !operationalIncident.checks[check]?.passed).map((check) => <option value={check} key={check}>{check}</option>)}</select><input name="incident_check_notes" placeholder="核对方法与结果" required /><select name="incident_check_evidence" defaultValue="" required><option value="">选择恢复证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `incident-check:${operationalIncident.id}`}>记录本项检查</button>{operationalIncident.required_checks.every((check) => operationalIncident.checks[check]?.passed) && <button type="button" disabled={lifecycleBusy === `incident-submit:${operationalIncident.id}`} onClick={() => submitIncidentReview(operationalIncident)}>提交独立复核</button>}</form>}
                {operationalIncident?.status === "pending_review" && <form className="policy-outcome-form" onSubmit={(event) => reviewIncident(event, operationalIncident)}><strong>独立恢复复核</strong><p>复核者不能是事故发起人或恢复负责人；通过也不会自动解除熔断。</p><select name="incident_review_verdict" defaultValue="" required><option value="">选择复核结论</option><option value="accepted">接受恢复</option><option value="rejected">退回继续处理</option></select><input name="incident_review_rationale" placeholder="独立复核理由" required /><select name="incident_review_evidence" defaultValue="" required><option value="">选择复核证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `incident-review:${operationalIncident.id}`}>提交独立复核</button></form>}
                {operationalIncident?.status === "ready_for_release" && operationalIncident.kill_switch_engaged && <div className="policy-release-form"><strong>管理员解除熔断</strong><p>只有独立复核通过后才显示；解除熔断与关闭事故是两个独立动作。</p><button type="button" disabled={lifecycleBusy === `incident-release:${operationalIncident.id}`} onClick={() => releaseIncidentFreeze(operationalIncident)}>明确解除熔断</button></div>}
                {operationalIncident?.status === "ready_for_release" && !operationalIncident.kill_switch_engaged && <form className="policy-outcome-form" onSubmit={(event) => closeIncident(event, operationalIncident)}><strong>关闭事故</strong><input name="incident_close_notes" placeholder="关闭结论与后续行动" required /><select name="incident_close_evidence" defaultValue="" required><option value="">选择关闭证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `incident-close:${operationalIncident.id}`}>固化并关闭事故</button></form>}
                <div className="policy-stages">{policy.rollout_stages.map((stage, index) => { const release = policy.releases.find((item) => item.stage_index === index); return <span className={release?.outcome?.verdict === "passed" ? "passed" : release ? "released" : ""} key={stage.name}>{stage.name}<b>{(Number(stage.max_exposure_fraction) * 100).toFixed(0)}%</b></span>; })}</div>
                <footer><span>条件不满足：{policy.fallback_action.type}</span><b>自动执行：禁止</b></footer>
              </article>;
            })}</div> : <div className="empty"><Waypoints size={24} /><strong>还没有条件策略</strong><p>先从仍有效的因果知识编译，不能从聊天建议直接生成经营动作。</p></div>}
          </div>
        </section></>;
}
