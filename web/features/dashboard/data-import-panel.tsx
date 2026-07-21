"use client";

import { Activity, FileUp, ShieldCheck, Sparkles } from "lucide-react";
import { financeReviewRecordTypes } from "./dashboard-config";
import { DomainStatusPanel } from "./domain-status-panel";
import type { DashboardModel } from "./use-dashboard-controller";


export function DataImportPanel({ model }: { model: DashboardModel }) {
  const { accrualClassificationBusy, accrualClassificationStatus, approveAccrualClassification, approveFeeMapping, canReviewFinance, domainStates, feeCodeStatus, feeMappingBusy, financeReviewBusy, financeReviewImportId, financeReviewStatus, lastOzonImport, load, loadFinanceReviewStatus, notice, reviewFinanceReport, setFinanceReviewImportId, upload, uploading } = model;
  return <><section className="hero" id="ozon-import">
          <div>
            <span className="hero-tag"><Sparkles size={15} />核心目标：单品净利润 CM3</span>
            <h2>先用真实数据跑通 3 个 SKU，<br />再把成功打法复制成规模。</h2>
            <p>系统会追踪证据、利润、内容和实验结果；缺失数据会明确提示，不允许 AI 编造。</p>
          </div>
          <form className="upload" onSubmit={upload}>
            <FileUp size={23} />
            <label htmlFor="ozon-file">导入 Ozon 经营数据</label>
            <span>支持 CSV / XLSX；先只读预检原文件，通过后才存证和导入</span>
            <input id="ozon-file" name="file" type="file" accept=".csv,.xlsx" />
            <div className="report-period-fields">
              <label>查询开始日期<input name="report_period_start" type="date" required /></label>
              <label>查询结束日期<input name="report_period_end" type="date" required /></label>
            </div>
            <button disabled={uploading}>{uploading ? "正在处理…" : "预检并导入"}</button>
          </form>
        </section><div className="notice"><Activity size={17} /><span>{notice}</span></div><DomainStatusPanel states={domainStates} onRetry={() => void load()} />{(lastOzonImport && financeReviewRecordTypes.has(lastOzonImport.record_type)) || canReviewFinance ? (
          <section className="finance-review-panel" aria-labelledby="finance-review-title">
            <div className="finance-review-head">
              <div><p className="eyebrow">DOUBLE CONTROL</p><h3 id="finance-review-title">Ozon 财务来源复核</h3></div>
              <span className={`gate ${financeReviewStatus?.status === "accepted" ? "ready" : financeReviewStatus?.status === "rejected" ? "blocked" : ""}`}>
                {financeReviewStatus?.status === "accepted" ? "来源已接受" : financeReviewStatus?.status === "rejected" ? "来源已拒绝" : "等待复核"}
              </span>
            </div>
            <p className="finance-review-boundary">应计、费用、退货和结算文件上传后只进入暂存区。复核通过也不会自动入账、批准会计字段或启动对账。</p>
            <div className="finance-review-grid">
              <article className="finance-handoff">
                <strong>上传人交接</strong>
                {lastOzonImport && financeReviewRecordTypes.has(lastOzonImport.record_type) ? <>
                  <dl>
                    <div><dt>导入编号</dt><dd><code>{lastOzonImport.id}</code></dd></div>
                    <div><dt>文件类型</dt><dd>{lastOzonImport.record_type}</dd></div>
                    <div><dt>暂存结果</dt><dd>{lastOzonImport.accepted_count}/{lastOzonImport.row_count} 行可解析</dd></div>
                    <div><dt>当前状态</dt><dd>{financeReviewStatus?.status ?? "pending"} · 未入账</dd></div>
                    <div><dt>交接期间</dt><dd>{financeReviewStatus ? `${financeReviewStatus.report_period_start} — ${financeReviewStatus.report_period_end}` : "读取中"}</dd></div>
                  </dl>
                  <p>把导入编号交给另一位 Reviewer/Compliance 用户；上传人不能复核自己的文件。</p>
                </> : <p>本会话没有刚上传的财务文件。复核人可在右侧输入上传人提供的导入编号。</p>}
              </article>
              {canReviewFinance ? <form className="finance-review-form" onSubmit={reviewFinanceReport}>
                <strong>独立复核人</strong>
                <label>导入编号
                  <span className="finance-review-id-row">
                    <input name="finance_review_import_id" value={financeReviewImportId} onChange={(event) => setFinanceReviewImportId(event.target.value)} required />
                    <button type="button" disabled={financeReviewBusy || !financeReviewImportId.trim()} onClick={() => loadFinanceReviewStatus()}>{financeReviewBusy ? "读取中…" : "读取状态"}</button>
                  </span>
                </label>
                {financeReviewStatus ? <div className="finance-handoff" role="note" aria-label="财务原件只读核验包">
                  <strong>提交前核验包</strong>
                  <dl>
                    <div><dt>原件</dt><dd>{financeReviewStatus.review_packet.source.filename} · {financeReviewStatus.review_packet.source.byte_size} bytes</dd></div>
                    <div><dt>SHA-256</dt><dd><code>{financeReviewStatus.review_packet.source.sha256}</code></dd></div>
                    <div><dt>上传身份</dt><dd><code>{financeReviewStatus.review_packet.source.submitted_by}</code></dd></div>
                    <div><dt>解析覆盖</dt><dd>{financeReviewStatus.review_packet.import.accepted_count}/{financeReviewStatus.review_packet.import.row_count} 行通过；{financeReviewStatus.review_packet.import.rejected_count} 行拒绝</dd></div>
                    <div><dt>精确合计</dt><dd>{financeReviewStatus.review_packet.aggregates.currency_totals.length ? financeReviewStatus.review_packet.aggregates.currency_totals.map((item) => `${item.total_amount} ${item.currency}（${item.row_count} 行）`).join("；") : "原件没有可聚合金额"}</dd></div>
                    <div><dt>日期覆盖</dt><dd>{financeReviewStatus.review_packet.aggregates.earliest_effective_at && financeReviewStatus.review_packet.aggregates.latest_effective_at ? `${financeReviewStatus.review_packet.aggregates.earliest_effective_at} — ${financeReviewStatus.review_packet.aggregates.latest_effective_at}` : "无可聚合日期"}</dd></div>
                    <div><dt>完整性</dt><dd>{Object.values(financeReviewStatus.review_packet.integrity).every(Boolean) ? "原件、哈希、血缘和行号连续性均通过" : "存在完整性异常，禁止接受"}</dd></div>
                  </dl>
                  {financeReviewStatus.review_packet.aggregates.accrual_pairs.length ? <details>
                    <summary>查看原件中 {financeReviewStatus.review_packet.aggregates.accrual_pairs.length} 个应计组/类型</summary>
                    <ul>{financeReviewStatus.review_packet.aggregates.accrual_pairs.map((item) => <li key={`${item.accrual_group}:${item.accrual_type}`}><strong>{item.accrual_group} / {item.accrual_type}</strong><span>{item.row_count} 行 · {item.currency_totals.map((total) => `${total.total_amount} ${total.currency}`).join("；")}</span></li>)}</ul>
                  </details> : null}
                  <p>这里只展示只读聚合，不返回商品、订单或客户原始行；核验包不会自动接受、分类或入账。</p>
                </div> : null}
                <fieldset>
                  <legend>逐项核对原件</legend>
                  <label><input name="authentic_account_export" type="checkbox" />来自真实 Ozon 店铺账户导出</label>
                  <label><input name="period_matches" type="checkbox" />报告期间与上方结构化交接期间一致</label>
                  <label><input name="not_public_sample" type="checkbox" />不是公开样例或演示数据</label>
                  <label><input name="complete_export" type="checkbox" />导出完整，没有缺页或截断</label>
                </fieldset>
                <label>复核结论
                  <select name="finance_review_decision" defaultValue="accepted"><option value="accepted">接受来源</option><option value="rejected">拒绝并保持阻塞</option></select>
                </label>
                <label>依据与异常说明<textarea name="finance_review_rationale" minLength={1} required /></label>
                <button className="finance-review-submit" disabled={financeReviewBusy}>{financeReviewBusy ? "正在提交…" : "保存不可变复核记录"}</button>
              </form> : <article className="finance-review-locked"><ShieldCheck size={23} /><strong>当前身份只能上传</strong><p>请让另一位拥有 Reviewer 或 Compliance 角色的用户登录后完成复核。</p></article>}
            </div>
            {canReviewFinance && financeReviewStatus?.status === "accepted" && financeReviewStatus.record_type === "ozon_fee" ? (
              <div className="fee-mapping-panel">
                <div className="fee-mapping-status">
                  <strong>实际费用代码</strong>
                  <span className={`gate ${feeCodeStatus?.ready ? "ready" : "blocked"}`}>{feeCodeStatus?.ready ? "全部已映射" : "仍有未映射代码"}</span>
                  <p>只显示该已接受文件中真实出现的代码。每条映射单独留证；全部覆盖后 Operator 才能另行晋升事实。</p>
                  <ul>{feeCodeStatus?.codes.map((item) => <li key={item.raw_code}><code>{item.raw_code}</code><span>{item.row_count} 行 · {item.ready ? "已覆盖" : "待批准"}</span></li>)}</ul>
                </div>
                <form className="finance-review-form" onSubmit={approveFeeMapping}>
                  <strong>批准一个代码映射</strong>
                  <label>原始费用代码<select name="fee_raw_code" defaultValue="" required><option value="">选择文件中的代码</option>{feeCodeStatus?.codes.map((item) => <option value={item.raw_code} key={item.raw_code}>{item.raw_code}{item.ready ? "（已有有效映射）" : ""}</option>)}</select></label>
                  <label>会计类型<select name="fee_canonical_type" defaultValue="platform_fee" required><option value="platform_fee">平台佣金/服务费</option><option value="international_logistics">国际物流</option><option value="last_mile">尾程配送</option><option value="warehousing">仓储</option><option value="advertising">广告</option><option value="return">退货</option><option value="refund">退款</option><option value="tax">税费</option><option value="customer_compensation">客户补偿</option><option value="damage">损耗</option></select></label>
                  <label>金额符号<select name="fee_sign_rule" defaultValue="absolute_outflow" required><option value="absolute_outflow">始终记为支出</option><option value="absolute_inflow">始终记为收入</option><option value="preserve">保留原始正负号</option></select></label>
                  <label>生效时间<input name="fee_effective_from" type="datetime-local" required /></label>
                  <label>失效时间（可选）<input name="fee_effective_until" type="datetime-local" /></label>
                  <label>映射依据与口径<textarea name="fee_mapping_rationale" minLength={1} required /></label>
                  <button className="finance-review-submit" disabled={feeMappingBusy || !feeCodeStatus?.codes.length}>{feeMappingBusy ? "正在留证…" : "批准版本化映射"}</button>
                </form>
              </div>
            ) : null}
            {financeReviewStatus?.status === "accepted" && financeReviewStatus.record_type === "ozon_accrual" ? (
              <div className="fee-mapping-panel">
                <div className="accrual-classification-boundary" role="note">
                  <ShieldCheck size={20} />
                  <p><strong>来源已核验，仍禁止计入利润</strong><span>应计报告同时包含销售、折扣、佣金、物流、补偿等不同性质项目。系统保留原始“应计组 + 应计类型”，等待独立、版本化的会计分类合同；不得把整份报告当作平台费用。</span></p>
                </div>
                <div className="fee-mapping-status">
                  <p><strong>{accrualClassificationStatus?.ready ? "控制分类已完整" : "控制分类仍有缺口"}</strong><span>仅控制账；不生成财务分录；不替代订单收入。</span></p>
                  <span>{accrualClassificationStatus?.pairs.filter((item) => item.ready).length ?? 0}/{accrualClassificationStatus?.pairs.length ?? 0} 组已批准</span>
                </div>
                <div className="fee-code-list" aria-label="应计组与应计类型分类状态">
                  {accrualClassificationStatus?.pairs.map((item) => (
                    <div key={`${item.accrual_group}:${item.accrual_type}`}>
                      <strong>{item.accrual_group} / {item.accrual_type}</strong>
                      <span>{item.row_count} 行 · {item.currency_totals.map((total) => `${total.total_amount} ${total.currency}`).join(" / ")} · 实际符号 {item.observed_signs.join("、")} · {item.ready ? `${item.accounting_classes.join("、")}（合同符号 ${item.expected_signs.join("、")}）` : "待分类"}</span>
                    </div>
                  ))}
                </div>
                {canReviewFinance ? (
                  <form className="finance-review-form" onSubmit={approveAccrualClassification}>
                    <strong>批准一个应计组合</strong>
                    <label>应计组 / 类型<select name="accrual_pair" defaultValue="" required><option value="">选择文件中的组合</option>{accrualClassificationStatus?.pairs.map((item) => <option value={JSON.stringify([item.accrual_group, item.accrual_type])} key={`${item.accrual_group}:${item.accrual_type}`}>{item.accrual_group} / {item.accrual_type}{item.ready ? "（已有有效分类）" : ""}</option>)}</select></label>
                    <label>会计分类<select name="accrual_accounting_class" defaultValue="platform_fee" required><option value="sales">销售</option><option value="discount">折扣</option><option value="platform_fee">平台费用</option><option value="logistics">物流</option><option value="compensation">补偿</option><option value="other_review">其他待复核</option></select></label>
                    <label>预期金额符号<select name="accrual_expected_sign" defaultValue="either" required><option value="positive">正数</option><option value="negative">负数</option><option value="either">允许正负</option></select></label>
                    <label>生效时间<input name="accrual_effective_from" type="datetime-local" required /></label>
                    <label>失效时间（可选）<input name="accrual_effective_until" type="datetime-local" /></label>
                    <label>分类依据与口径<textarea name="accrual_classification_rationale" minLength={1} required /></label>
                    <button className="finance-review-submit" disabled={accrualClassificationBusy || !accrualClassificationStatus?.pairs.length}>{accrualClassificationBusy ? "正在留证…" : "批准版本化控制分类"}</button>
                  </form>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}</>;
}
