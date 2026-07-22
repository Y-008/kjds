"use client";

import { ShieldCheck } from "lucide-react";
import { candidateMetricDefinitions, candidateMetricLabels } from "./dashboard-config";
import type { DashboardModel } from "./use-dashboard-controller";


export function ResearchGatePanel({ model }: { model: DashboardModel }) {
  const { acceptedDemandReports, canReviewFinance, candidateAssessment, candidateAuthorityBusy, candidateAuthorityStatus, candidateEvidenceUploading, candidateHandoff, candidateHandoffBusy, candidateResearchBusy, createCandidateSourcingWorkspace, demandSourceReports, evidenceRecords, gateReadiness, gateUploading, lifecycleBusy, loadCandidateAuthorityStatus, realExecutionReadiness, researchReadiness, researchSignals, reviewCandidateEvidenceAuthority, reviewDemandReport, submitCandidateResearch, uploadCandidateEvidence, uploadDemandReport, uploadGateEvidence } = model;
  return <><section className="gate-overview" id="reality-gate">
          <div className="gate-overview-head">
            <div><p className="eyebrow">REALITY GATE</p><h3>G0–G1 真实准入状态</h3></div>
            <span className={gateReadiness?.status === "ready_for_review" ? "gate ready" : "gate blocked"}>
              {gateReadiness?.status === "ready_for_review" ? "等待人工放行" : "等待真实输入"}
            </span>
          </div>
          {gateReadiness ? <div className="requirement-grid">
            {gateReadiness.requirements.map((item) => <article className={item.ready ? "requirement ready" : "requirement"} key={item.id}>
              <div><span>{item.id}</span><b>{item.current}/{item.target}</b></div>
              <strong>{item.title}</strong>
              <small>{item.ready ? "证据条件已满足，仍需阶段门人工复核" : item.next_action}</small>
            </article>)}
          </div> : <div className="gate-loading">正在读取阶段门事实…</div>}
          {gateReadiness && <div className="requirement-grid">
            <article className={researchReadiness?.ready ? "requirement ready" : "requirement"}>
              <div><span>研究闭环</span><b>{researchReadiness?.ready ? "READY" : "BLOCKED"}</b></div>
              <strong>分析、模拟、生图/视频与 Listing 草稿</strong>
              <small>{researchReadiness?.ready ? "只允许 research_signal / estimate / simulation / draft，不允许外部副作用" : researchReadiness?.blocking_reasons.join("；") || "等待合格研究原件及独立复核"}</small>
            </article>
            <article className={realExecutionReadiness?.ready ? "requirement ready" : "requirement"}>
              <div><span>真实经营</span><b>{realExecutionReadiness?.ready ? "READY" : "BLOCKED"}</b></div>
              <strong>付款、采购、发布、广告、补货与 actual 晋升</strong>
              <small>{realExecutionReadiness?.ready ? "动作仍需按风险等级、审批、额度和执行时复验" : realExecutionReadiness?.blocking_reasons.join("；") || "等待 Ozon Data 或两项独立官方分析证据"}</small>
            </article>
          </div>}
          <form className="gate-evidence-upload" onSubmit={uploadDemandReport}>
            <div><strong>1. 上传需求研究原件</strong><small>上传后只进入待复核。测试数据最多放行研究闭环；真实经营要求 Ozon Data，或至少两个独立 Ozon 官方分析入口。</small></div>
            <select name="demand_report_source_system" aria-label="需求研究来源" defaultValue="ozon_category_analytics" required>
              <option value="ozon_data">Ozon Data 正式报告</option>
              <option value="ozon_seller_analytics">Ozon Seller Analytics（店铺级，仅研究）</option>
              <option value="ozon_category_analytics">Ozon 类目分析</option>
              <option value="ozon_trends">Ozon 趋势数据</option>
              <option value="ozon_what_to_sell">Ozon 卖什么</option>
              <option value="ozon_search_terms">Ozon 搜索词</option>
              <option value="ozon_competitor_compare">Ozon 竞品/类目比较</option>
              <option value="sanitized_history">脱敏历史样本</option>
              <option value="fixed_test_data">固定工程测试数据</option>
            </select>
            <input name="demand_report_source_locator" aria-label="需求研究来源定位" placeholder="原始页面 URL、导出编号或 fixture:// 路径" required />
            <input name="demand_report_window_days" aria-label="需求报告窗口天数" type="number" min="28" max="365" defaultValue="28" required />
            <input name="demand_report_file" aria-label="需求研究原件文件" type="file" accept=".json,.csv,.xlsx,.xls,.pdf,.png,.jpg,.jpeg,.webp" required />
            <button disabled={gateUploading}>{gateUploading ? "正在固化…" : "固化研究原件"}</button>
          </form>
          <form className="gate-evidence-upload" onSubmit={reviewDemandReport}>
            <div><strong>2. 独立复核需求报告</strong><small>复核身份必须与上传者不同；接受或拒绝都会形成不可覆盖的证据。</small></div>
            <select name="demand_report_evidence_id" aria-label="待复核需求报告" defaultValue="" required>
              <option value="" disabled>{demandSourceReports.length ? "选择报告" : "暂无待复核报告"}</option>
              {demandSourceReports.map((item) => <option value={item.id} key={item.id}>{item.filename} · {String(item.metadata.source_system ?? "unknown")} · 上传者 {item.created_by}</option>)}
            </select>
            <select name="demand_report_decision" aria-label="需求报告复核结论" defaultValue="accepted" required>
              <option value="accepted">接受：已核对后台来源、窗口与字段</option>
              <option value="rejected">拒绝：来源或范围不可复验</option>
            </select>
            <input name="demand_report_rationale" aria-label="需求报告复核理由" placeholder="写明核对位置、日期范围和异常" required />
            <button disabled={lifecycleBusy === "demand-report-review" || demandSourceReports.length === 0}>{lifecycleBusy === "demand-report-review" ? "正在复核…" : "固化独立复核"}</button>
          </form>
          <form className="gate-evidence-upload" onSubmit={uploadGateEvidence}>
            <div><strong>补充阶段门证据</strong><small>原文件将哈希固化并自动链接，不覆盖历史。</small></div>
            <select name="requirement_id" aria-label="阶段门证据类型" defaultValue="" required>
              <option value="" disabled>选择证据类型</option>
              <option value="GOV-001">负责人、审批人与风险预算</option>
              <option value="OZN-001">Ozon 账户、权限与收款路径</option>
            </select>
            <input name="gate_file" aria-label="阶段门证据文件" type="file" required />
            <button disabled={gateUploading}>{gateUploading ? "正在固化…" : "提交证据"}</button>
          </form>
        </section><section className="sku-intake-panel" id="candidate-research">
          <div className="panel-title">
            <div><p className="eyebrow">CANDIDATE RESEARCH</p><h3>新上新候选预检</h3></div>
            <span className="badge">先证据 · 后报价</span>
          </div>
          <div className="procurement-guardrail">
            <ShieldCheck size={18} />
            <p><strong>系统不会替你编造来源</strong><span>先固化原文件，再让每个指标绑定一份可复验原件。预检通过也只进入三家真实报价。</span></p>
          </div>
          <form className="candidate-evidence-form" onSubmit={uploadCandidateEvidence}>
            <div><strong>1. 研究收集箱：固化信号与原件</strong><small>保存原文件、来源时间、原始字段和候选关联；不自动生成商品或上架</small></div>
            <input name="candidate_evidence_source" placeholder="来源机构，例如 Seerfar、萌啦或 Ozon Analytics" required />
            <input name="candidate_evidence_source_ref" placeholder="提供方稳定记录编号，例如 export://2026-07/row-18" required />
            <input name="candidate_evidence_source_url" type="url" placeholder="原始页面 URL（不得包含账号、Token 或密钥）" required />
            <input name="candidate_evidence_candidate_refs" placeholder="关联候选编号，可用逗号分隔；允许一条信号关联多个候选" />
            <textarea name="candidate_evidence_raw_fields" aria-label="提供方原始字段" defaultValue="{}" placeholder='原始字段 JSON，例如 {"keyword":"storage box","search_index":81.5}' required />
            <select name="candidate_evidence_license_status" defaultValue="requires_review" aria-label="来源使用状态"><option value="requires_review">使用条款待核对</option><option value="verified">已核对允许保存/使用</option><option value="restricted">受限，仅留档不得复用</option></select>
            <select name="candidate_evidence_grade" defaultValue="C" aria-label="证据等级"><option value="A">A · 官方原件</option><option value="B">B · 一手业务数据</option><option value="C">C · 可追溯二手资料</option><option value="D">D · 探索线索</option></select>
            <small>第三方选品、ERP 和利润计算器默认是 C 级辅助资料；A/B 只能按原始账户、供应商或官方规则依据声明，后续仍需独立复核。</small>
            <input name="candidate_evidence_file" type="file" required />
            <button disabled={candidateEvidenceUploading}>{candidateEvidenceUploading ? "正在固化…" : "固化原件"}</button>
          </form>
          {researchSignals.length > 0 && <div className="candidate-inbox-list">
            <strong>最近研究信号</strong>
            {researchSignals.slice(0, 5).map((record) => <p key={`signal-${record.id}`}><code>{record.id}</code><span>{record.source} · {String(record.metadata.license_status ?? "requires_review")} · 辅助资料</span></p>)}
          </div>}
          <div className="finance-review-grid">
            <article className="finance-handoff">
              <strong>2. 上传人交接复核</strong>
              <p>把 Evidence 编号、对应指标和原始依据交给另一位 Reviewer/Compliance 用户。上传时选择的 A/B/C/D 只是声明，不会直接推动候选进入三报价。</p>
              {candidateAuthorityStatus && <dl>
                <div><dt>Evidence</dt><dd><code>{candidateAuthorityStatus.evidence_id}</code></dd></div>
                <div><dt>指标</dt><dd>{candidateMetricLabels[candidateAuthorityStatus.metric] ?? candidateAuthorityStatus.metric}</dd></div>
                <div><dt>状态</dt><dd>{candidateAuthorityStatus.status}</dd></div>
                <div><dt>有效等级</dt><dd>{candidateAuthorityStatus.accepted_grades.join("/") || "无"}</dd></div>
              </dl>}
            </article>
            {canReviewFinance ? <form className="finance-review-form" onSubmit={reviewCandidateEvidenceAuthority}>
              <strong>独立权威复核人</strong>
              <label>候选 Evidence<select name="candidate_authority_evidence_id" defaultValue="" required><option value="">选择原件</option>{evidenceRecords.filter((record) => record.source !== "candidate_evidence_authority_review").map((record) => <option value={record.id} key={`authority-${record.id}`}>{record.source} · {record.filename}</option>)}</select></label>
              <label>适用指标<select name="candidate_authority_metric" defaultValue="" required><option value="">选择指标</option>{candidateMetricDefinitions.map(([metric, label]) => <option value={metric} key={`authority-metric-${metric}`}>{label}</option>)}</select></label>
              <label>批准等级<select name="candidate_authority_grade" defaultValue="B"><option value="A">A · 官方原件</option><option value="B">B · 一手业务数据</option></select></label>
              <fieldset>
                <legend>逐项核对原件</legend>
                <label><input name="candidate_authority_authentic" type="checkbox" />原件真实、完整且哈希可复验</label>
                <label><input name="candidate_authority_scope" type="checkbox" />来源范围与本指标、市场和时间窗口一致</label>
                <label><input name="candidate_authority_basis" type="checkbox" />A/B 权威依据已核对，不依赖二手计算器声明</label>
              </fieldset>
              <label>复核结论<select name="candidate_authority_decision" defaultValue="accepted"><option value="accepted">接受该指标的 A/B 等级</option><option value="rejected">拒绝并保持阻塞</option></select></label>
              <label>依据与异常说明<textarea name="candidate_authority_rationale" minLength={1} required /></label>
              <span className="finance-review-id-row">
                <button type="button" disabled={candidateAuthorityBusy} onClick={(event) => { const form = event.currentTarget.form; if (form) loadCandidateAuthorityStatus((form.elements.namedItem("candidate_authority_evidence_id") as HTMLSelectElement).value, (form.elements.namedItem("candidate_authority_metric") as HTMLSelectElement).value); }}>读取状态</button>
                <button className="finance-review-submit" disabled={candidateAuthorityBusy}>{candidateAuthorityBusy ? "处理中…" : "保存不可变复核记录"}</button>
              </span>
            </form> : <article className="finance-review-locked"><ShieldCheck size={23} /><strong>当前身份只能上传</strong><p>请让另一位 Reviewer 或 Compliance 用户核对原件；上传人不能复核自己的证据。</p></article>}
          </div>
          <form className="sku-intake candidate-research-form" onSubmit={submitCandidateResearch}>
            <div className="candidate-heading"><strong>3. 绑定五类证据并预检</strong><small>每份原件还必须有该指标的独立 A/B 复核；五项全部验真后才会一起落账。</small></div>
            <div className="candidate-basics">
              <label>已接受需求报告<select name="candidate_demand_report_evidence_id" defaultValue="" required><option value="" disabled>{acceptedDemandReports.length ? "选择本次研究依据" : "请先完成需求报告独立复核"}</option>{acceptedDemandReports.map((report) => <option value={report.id} key={`candidate-report-${report.id}`}>{report.filename} · {report.effective_at.slice(0, 10)}</option>)}</select></label>
              <label>候选编号<input name="candidate_ref" placeholder="candidate://stable-name-v1" required /></label>
              <label>候选名称<input name="candidate_name" placeholder="便于经营人员识别的名称" required /></label>
              <label>市场<input name="candidate_market" defaultValue="RU" required /></label>
              <label>类目<input name="candidate_category" placeholder="例如 kitchen_storage" required /></label>
            </div>
            <div className="candidate-metric-list">
              {candidateMetricDefinitions.map(([metric, label, help, defaultWindow, defaultSample]) => <div className="candidate-metric" key={metric}>
                <div><strong>{label}</strong><small>{help}</small></div>
                {metric === "supplier_available" || metric === "compliance_redline"
                  ? <select name={`candidate_${metric}_value`} aria-label={`${label}数值`} defaultValue="" required><option value="" disabled>请选择</option><option value="1">是</option><option value="0">否</option></select>
                  : <input name={`candidate_${metric}_value`} aria-label={`${label}数值`} type="number" min="0" max="100" step="0.1" placeholder="0–100" required />}
                <select name={`candidate_${metric}_evidence`} aria-label={`${label}原件`} defaultValue="" required>
                  <option value="" disabled>{evidenceRecords.length ? "选择 Evidence 原件" : "请先固化原件"}</option>
                  {evidenceRecords.map((record) => <option value={record.id} key={`${metric}-${record.id}`}>{record.grade}级 · {record.source} · {record.filename} · {record.effective_at.slice(0, 10)}</option>)}
                </select>
                <label>可信度<input name={`candidate_${metric}_confidence`} aria-label={`${label}可信度`} type="number" min="0.01" max="1" step="0.01" defaultValue="0.8" required /></label>
                <label>观察窗口（天）<input name={`candidate_${metric}_window_days`} aria-label={`${label}观察窗口`} type="number" min={metric === "supplier_available" || metric === "compliance_redline" ? 1 : 28} max="90" step="1" defaultValue={defaultWindow} required /></label>
                <label>样本量<input name={`candidate_${metric}_sample_size`} aria-label={`${label}样本量`} type="number" min={defaultSample} step="1" defaultValue={defaultSample} required /></label>
              </div>)}
            </div>
            <div className="intake-submit"><p>同一候选包重复提交不会重复建账；需求报告未接受、坏原件或缺任一指标时，五条观测全部不写入。</p><button disabled={candidateResearchBusy || evidenceRecords.length === 0 || acceptedDemandReports.length === 0}>{candidateResearchBusy ? "正在预检…" : "执行候选预检"}</button></div>
          </form>
          {candidateAssessment && <article className={`candidate-result ${candidateAssessment.decision}`}>
            <div><strong>{candidateAssessment.candidate_name}</strong><span>{candidateAssessment.decision === "request_three_quotes" ? "进入三报价" : candidateAssessment.decision === "reject" ? "淘汰" : "需要补证"}</span></div>
            <p>测量合同：{candidateAssessment.measurement_policy_id}；筛选策略：{candidateAssessment.quote_policy_id}（工程默认值，G0 前需经营负责人复核）</p>
            <p>需求报告：{candidateAssessment.demand_report_evidence_id}</p>
            <p>聚合值：需求 {candidateAssessment.metric_values.demand_signal ?? "—"} · 缺口 {candidateAssessment.metric_values.competition_gap ?? "—"} · 退货风险 {candidateAssessment.metric_values.return_risk ?? "—"}%</p>
            {candidateAssessment.threshold_failures.length > 0 && <ul>{candidateAssessment.threshold_failures.map((item) => <li key={item.metric}>{candidateMetricLabels[item.metric] ?? item.metric}：实际 {item.actual}，要求 {item.operator === "gte" ? "≥" : "≤"} {item.threshold}</li>)}</ul>}
            <p>{candidateAssessment.decision === "request_three_quotes"
              ? `已核验 ${candidateAssessment.evidence_ids.length} 份原件、${candidateAssessment.source_family_count} 个独立来源族；下一步必须收集 ${candidateAssessment.required_supplier_quotes} 家真实报价并计算风险调整后 CM3。`
              : candidateAssessment.reasons.join("；")}</p>
            {candidateAssessment.missing_metrics.length > 0 && <small>缺失或无效：{candidateAssessment.missing_metrics.map((metric) => candidateMetricLabels[metric] ?? metric).join("、")}</small>}
            {candidateAssessment.low_authority_evidence_ids.length > 0 && <small>有 {candidateAssessment.low_authority_evidence_ids.length} 条辅助资料已保留，但权威等级不足，不能推动三报价。</small>}
            <small>不会自动创建商品、采购或 Listing。</small>
            {candidateAssessment.decision === "request_three_quotes" && !candidateHandoff && <form className="candidate-handoff" onSubmit={createCandidateSourcingWorkspace}>
              <label>内部 SKU<input name="candidate_handoff_sku" placeholder="例如 RU-CAND-001" required /></label>
              <label className="candidate-confirm"><input name="candidate_handoff_confirmed" type="checkbox" required />我确认建立报价工作区；这不代表采购或上架批准</label>
              <button disabled={candidateHandoffBusy}>{candidateHandoffBusy ? "正在建立…" : "建立报价工作区"}</button>
            </form>}
            {candidateHandoff && <div className="candidate-next-step"><strong>{candidateHandoff.product.sku} 已就绪</strong><a href="#sourcing-intake">前往录入三家报价</a></div>}
          </article>}
        </section></>;
}
