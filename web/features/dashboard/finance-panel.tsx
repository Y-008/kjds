"use client";

import { ShieldCheck } from "lucide-react";
import type { DashboardModel } from "./use-dashboard-controller";


export function FinancePanel({ model }: { model: DashboardModel }) {
  const { actualCostAuthorityItem, actualCostAuthorityStatus, actualCostEvidenceId, actualCostReviewBusy, actualCostType, canReviewFinance, costAuthorityCatalog, loadActualCostAuthorityStatus, reviewActualCostAuthority, reviewableCostEvidence, setActualCostAuthorityStatus, setActualCostEvidenceId, setActualCostType } = model;
  return <><section className="finance-review-panel" id="actual-cost-review" aria-labelledby="actual-cost-review-title">
          <div className="finance-review-head">
            <div><p className="eyebrow">ACTUAL COST PROOF</p><h3 id="actual-cost-review-title">实际成本权威复核</h3></div>
            <span className={`gate ${actualCostAuthorityStatus?.status === "accepted" ? "ready" : actualCostAuthorityStatus?.status === "rejected" ? "blocked" : ""}`}>
              {actualCostAuthorityStatus?.status === "accepted" ? "实际依据已接受" : actualCostAuthorityStatus?.status === "rejected" ? "实际依据已拒绝" : "等待独立复核"}
            </span>
          </div>
          <p className="finance-review-boundary">只有非上传者核对原件、成本范围、计费主体以及金额—币种—期间后，Evidence 才能证明对应成本为实际值。复核不会自动改写利润场景、入账、采购、定价或上架。</p>
          <div className="finance-review-grid">
            <article className="finance-handoff">
              <strong>原件与规则交接</strong>
              <dl>
                <div><dt>规则版本</dt><dd><code>{costAuthorityCatalog?.schema_version ?? "读取中"}</code></dd></div>
                <div><dt>成本项</dt><dd>{costAuthorityCatalog?.items.length ?? 0}/15</dd></div>
                <div><dt>当前原件</dt><dd>{actualCostEvidenceId ? <code>{actualCostEvidenceId}</code> : "尚未选择"}</dd></div>
                <div><dt>复核记录</dt><dd>{actualCostAuthorityStatus ? `${actualCostAuthorityStatus.review_count} 条 · ${actualCostAuthorityStatus.status}` : "尚未读取"}</dd></div>
                <div><dt>已接受权威</dt><dd>{actualCostAuthorityStatus?.accepted_authorities.length ? actualCostAuthorityStatus.accepted_authorities.join("、") : "无"}</dd></div>
              </dl>
              <p>权威类型由后端统一下发，页面不能自造或修改。上传人不能复核自己的原件；任一拒绝结论优先阻断。</p>
            </article>
            <form className="finance-review-form" onSubmit={canReviewFinance ? reviewActualCostAuthority : (event) => event.preventDefault()}>
              <strong>{canReviewFinance ? "独立复核人" : "只读状态查询"}</strong>
              <label>原件 Evidence
                <select name="actual_cost_evidence_id" value={actualCostEvidenceId} onChange={(event) => { setActualCostEvidenceId(event.target.value); setActualCostAuthorityStatus(null); }} required>
                  <option value="">选择已有原件</option>
                  {reviewableCostEvidence.map((item) => <option value={item.id} key={item.id}>{item.filename} · {item.source} · 上传者 {item.created_by}</option>)}
                </select>
              </label>
              <label>精确成本项
                <select name="actual_cost_type" value={actualCostType} onChange={(event) => { setActualCostType(event.target.value); setActualCostAuthorityStatus(null); }} required>
                  {costAuthorityCatalog?.items.map((item) => <option value={item.cost_type} key={item.cost_type}>{item.label}</option>)}
                </select>
              </label>
              <label>允许的实际权威类型
                <select name="actual_cost_authority_id" key={`${actualCostType}:${actualCostAuthorityItem?.authorities[0]?.id ?? "loading"}`} defaultValue={actualCostAuthorityItem?.authorities[0]?.id ?? ""} required>
                  {actualCostAuthorityItem?.authorities.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}
                </select>
              </label>
              <button type="button" className="finance-review-submit" disabled={actualCostReviewBusy || !actualCostEvidenceId} onClick={() => loadActualCostAuthorityStatus()}>{actualCostReviewBusy ? "读取中…" : "读取当前状态"}</button>
              {canReviewFinance ? <>
                <fieldset>
                  <legend>逐项核对实际原件</legend>
                  <label><input name="actual_cost_authentic_original" type="checkbox" />原件真实、完整且哈希有效</label>
                  <label><input name="actual_cost_scope_matches" type="checkbox" />原件范围与该成本项精确对应</label>
                  <label><input name="actual_cost_charging_party_matches" type="checkbox" />计费方与实际责任主体一致</label>
                  <label><input name="actual_cost_amount_currency_period_matches" type="checkbox" />金额、币种和归属期间一致</label>
                </fieldset>
                <label>复核结论<select name="actual_cost_decision" defaultValue="accepted"><option value="accepted">接受为实际成本依据</option><option value="rejected">拒绝并保持阻断</option></select></label>
                <label>依据与异常说明<textarea name="actual_cost_rationale" minLength={1} required /></label>
                <button className="finance-review-submit" disabled={actualCostReviewBusy || !actualCostEvidenceId || !actualCostAuthorityItem}>{actualCostReviewBusy ? "正在保存…" : "保存不可变实际成本复核"}</button>
              </> : <div className="finance-review-locked"><ShieldCheck size={23} /><strong>当前身份不能提交结论</strong><p>Operator 可以查询状态；请由另一位 Reviewer、Compliance 或 Admin 核对并留证。</p></div>}
            </form>
          </div>
        </section></>;
}
