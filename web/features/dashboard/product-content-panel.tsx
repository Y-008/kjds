"use client";

import { CheckCircle2, Image as ImageIcon, ShieldCheck } from "lucide-react";
import { passportLabels, productMediaRoleLabels, imageQaDefinitions } from "./dashboard-config";
import { selectListingExecutionPresentations } from "./listing-execution-presentation";
import type { DashboardModel } from "./use-dashboard-controller";


export function ProductContentPanel({ model }: { model: DashboardModel }) {
  const { approvals, approvedListingApprovals, canReviewExecutionAuthority, comparisons, contentAssets, createImageBrief, createListingDraft, evidenceRecords, health, imageBriefBusy, imageExecutionBusy, imageQaBusy, lifecycleBusy, limitedExecutionCommands, listingDraftBusy, listingExecutionPlans, operationalIncidents, passportReviews, pendingListingApprovals, prepareListingExecutionPlan, productMediaReadiness, productMediaUploading, products, reviewImageAsset, reviewListingRussianNative, reviewNotes, reviewOzonExecutionIdentity, reviewPassport, reviewingKey, runImageGeneration, setReviewNotes, skuUploading, uploadProductMedia, uploadSkuEpisode } = model;
  const executionIdentityEvidence = evidenceRecords.filter((item) => item.source === "ozon_execution_identity_inventory" && item.grade === "A");
  const listingExecutionPresentations = selectListingExecutionPresentations({
    listingApprovals: approvedListingApprovals,
    approvals,
    plans: listingExecutionPlans,
    commands: limitedExecutionCommands,
    incidents: operationalIncidents,
    evidenceRecords,
  });
  return <><section className="sku-intake-panel" id="sku-intake">
          <div className="panel-title"><div><p className="eyebrow">SKU EPISODE INTAKE</p><h3>候选 SKU 一站式录入</h3></div><span className="badge">草稿 · 需人工审核</span></div>
          <form className="sku-intake" onSubmit={uploadSkuEpisode}>
            <div className="intake-basic">
              <label>SKU<input name="sku" placeholder="例如 RU-001" required /></label>
              <label>商品名称<input name="product_name" placeholder="使用可稳定识别的商品名称" required /></label>
            </div>
            <div className="intake-passports">
              <details open>
                <summary><span>1</span><strong>商品 Passport</strong><small>材料、用途、产地、重量与尺寸</small></summary>
                <div className="intake-fields">
                  <label>材料<input name="material" required /></label><label>用途<input name="intended_use" required /></label>
                  <label>原产国<input name="country_of_origin" defaultValue="CN" required /></label><label>重量 kg<input name="weight_kg" type="number" min="0.001" step="0.001" required /></label>
                  <label>长 cm<input name="length_cm" type="number" min="0" step="0.1" required /></label><label>宽 cm<input name="width_cm" type="number" min="0" step="0.1" required /></label>
                  <label>高 cm<input name="height_cm" type="number" min="0" step="0.1" required /></label><label>商品证据<input name="product_evidence" type="file" required /></label>
                </div>
              </details>
              <details open>
                <summary><span>2</span><strong>俄罗斯合规 Passport</strong><small>先记录事实与未知项，审核人再作结论</small></summary>
                <div className="intake-fields">
                  <label>HS Code<input name="hs_code" required /></label><label>EAC 要求<input name="eac_requirement" defaultValue="unknown" required /></label>
                  <label>诚实标要求<input name="chestny_znak_requirement" defaultValue="unknown" required /></label><label>俄文标签<input name="russian_labeling" defaultValue="unknown" required /></label>
                  <label>知识产权状态<input name="ip_status" defaultValue="review_required" required /></label><label>运输限制<input name="transport_restrictions" defaultValue="unknown" required /></label>
                  <label>可售状态<input name="sellability" defaultValue="pending_review" required /></label><label>合规证据<input name="compliance_evidence" type="file" required /></label>
                  <label className="wide">EAEU 规则依据（每行一条）<textarea name="eaeu_rules" required /></label>
                </div>
              </details>
              <details open>
                <summary><span>3</span><strong>样品质量 Passport</strong><small>黄金样、验货计划与包装测试</small></summary>
                <div className="intake-fields">
                  <label>黄金样编号<input name="golden_sample_ref" required /></label><label>包装测试<input name="packaging_test" defaultValue="pending" required /></label>
                  <label>质量证据<input name="quality_evidence" type="file" required /></label><label className="wide">验货项目（每行一条）<textarea name="inspection_plan" required /></label>
                </div>
              </details>
            </div>
            <div className="intake-submit"><p>提交只建立可追溯草稿，不代表合规批准、采购授权或上架放行。</p><button disabled={skuUploading}>{skuUploading ? "正在建立…" : "建立 SKU Episode"}</button></div>
          </form>
        </section><section className="sku-intake-panel" id="product-media-intake">
          <div className="panel-title">
            <div><p className="eyebrow">PRODUCT MEDIA EVIDENCE</p><h3>真实原图与权利证据</h3></div>
            <span className="badge">上传不触发生成</span>
          </div>
          <form className="sku-intake" onSubmit={uploadProductMedia}>
            <div className="intake-basic">
              <label>候选 SKU<select name="product_media_product_id" required><option value="">选择 SKU</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
              <label>变体标识<input name="product_media_variant_id" defaultValue="base" required /></label>
              <label>图片角色<select name="product_media_role" defaultValue="front_main">{Object.entries(productMediaRoleLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>来源类型<select name="product_media_source_kind" defaultValue="sample_photo"><option value="sample_photo">真实样品拍摄</option><option value="supplier_authorized">供应商授权原图</option></select></label>
              <label>来源编号 / 链接<input name="product_media_source_ref" placeholder="样品编号、供应商报价编号或原始链接" required /></label>
              <label>真实原图<input name="product_media_image" type="file" accept="image/jpeg,image/png,image/webp" required /></label>
              <label>权利 / 授权文件<input name="product_media_rights" type="file" accept="application/pdf,text/plain,image/jpeg,image/png" required /></label>
            </div>
            <div className="intake-submit"><p>服务端校验文件签名并哈希固化；最新 Quality Passport 未获人工批准前，Content Agent 无权引用。</p><button disabled={productMediaUploading}>{productMediaUploading ? "正在固化…" : "提交一组素材证据"}</button></div>
          </form>
          {productMediaReadiness.length > 0 && <div className="media-readiness-grid">{productMediaReadiness.map((item) => <article className="media-readiness-card" key={item.product.id}>
            <div className="sku-card-head"><div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div><span className={item.ready_for_full_production ? "gate ready" : "gate"}>{item.approved_role_count}/7</span></div>
            <div className="media-role-row">{item.roles.map((role) => <span className={role.status} key={role.role}>{productMediaRoleLabels[role.role]}</span>)}</div>
            <p>{item.ready_for_full_production ? "七类原图与权利证据均已批准，可以建立受控图片 Brief。" : item.pending_passport_roles.length ? "已捕获素材正在等待 Passport 人工批准。" : `仍缺：${item.missing_roles.map((role) => productMediaRoleLabels[role]).join("、")}`}</p>
          </article>)}</div>}
          <form className="sku-intake image-brief-form" onSubmit={createImageBrief}>
            <div className="procurement-guardrail">
              <ImageIcon size={18} />
              <p>
                <strong>官方 ComfyUI · {health.comfyui?.status === "ok" ? "本地执行器在线" : "执行器离线"}</strong>
                <span>{health.comfyui?.detail || "仅建立 Brief；执行器恢复后再受控生成。"} 第三方 custom nodes 默认禁用。</span>
              </p>
            </div>
            <div className="intake-basic">
              <label>已就绪 SKU<select name="image_brief_product_id" required><option value="">选择已通过 7/7 的 SKU</option>{productMediaReadiness.filter((item) => item.ready_for_full_production).map((item) => <option value={item.product.id} key={item.product.id}>{item.product.sku} · {item.product.name}</option>)}</select></label>
              <label>来源图片角色<select name="image_brief_role" defaultValue="front_main">{Object.entries(productMediaRoleLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>处理模式<select name="image_brief_mode" defaultValue="retouch"><option value="retouch">真实图精修</option><option value="composite">受控场景合成</option><option value="infographic">固定模板信息图</option></select></label>
              <label>图片目标<input name="image_brief_goal" defaultValue="Ozon 正面主图" required /></label>
            </div>
            <div className="intake-submit"><p>提交只冻结事实、来源与权利证据，不向 ComfyUI 暴露任意工作流，也不会自动生成或上架。</p><button disabled={imageBriefBusy || !productMediaReadiness.some((item) => item.ready_for_full_production)}>{imageBriefBusy ? "正在冻结…" : "建立受控图片 Brief"}</button></div>
          </form>
          {contentAssets.length > 0 && <div className="content-execution-grid">{contentAssets.map((asset) => {
            const product = products.find((item) => item.id === asset.product_id);
            const mode = String(asset.brief.generation_mode ?? "");
            const busy = imageExecutionBusy === asset.id;
            const comparison = comparisons.find((item) => item.product.id === asset.product_id);
            const profitableRows = comparison?.rows.filter((item) => item.has_positive_cm3 && item.scenario) ?? [];
            return <article className={`content-execution-card ${["generated", "approved"].includes(asset.status) ? "wide" : ""}`} key={asset.id}>
              <div className="sku-card-head">
                <div><strong>{product?.sku ?? asset.product_id}</strong><small>{String(asset.brief.goal ?? "受控图片任务")}</small></div>
                <span className={`gate ${asset.status === "generated" ? "ready" : asset.status === "execution_failed" ? "blocked" : ""}`}>{asset.status}</span>
              </div>
              <p>{mode === "retouch" ? "固定核心节点：真实原图 → Lanczos 4MP 保真缩放 → 证据回收" : "当前只冻结 Brief；场景合成与信息图需真实 SKU 模板验证后开放。"}</p>
              {Boolean(asset.generation.prompt_id) && <small>Prompt · {String(asset.generation.prompt_id)}</small>}
              {asset.artifact_ref && <small>Evidence · {asset.artifact_ref}</small>}
              {mode === "retouch" && ["brief", "qa_failed", "execution_failed"].includes(asset.status) && <button disabled={busy || health.comfyui?.status !== "ok"} onClick={() => runImageGeneration(asset, "queue")}>{busy ? "提交中…" : "提交保真处理"}</button>}
              {asset.status === "queued" && <button disabled={busy} onClick={() => runImageGeneration(asset, "sync")}>{busy ? "同步中…" : "同步执行结果"}</button>}
              {asset.status === "generated" && <form className="image-qa-form" onSubmit={(event) => reviewImageAsset(event, asset)}>
                <div className="content-next-step"><ShieldCheck size={14} />八项必须全部判断；任一失败都会退回</div>
                {imageQaDefinitions.map(([check, label, help]) => <label key={check}>
                  <span><strong>{label}</strong><small>{help}</small></span>
                  <select name={`qa_${check}_passed`} defaultValue="" required>
                    <option value="" disabled>请选择结论</option>
                    <option value="true">通过</option>
                    <option value="false">不通过</option>
                  </select>
                  <textarea name={`qa_${check}_notes`} placeholder="填写核查依据、看到的证据或失败原因" required />
                </label>)}
                <button disabled={imageQaBusy === asset.id}>{imageQaBusy === asset.id ? "正在提交…" : "提交完整人工 QA"}</button>
                <small>审核身份与 UTC 时间由服务端记录；提交后仍不触发 Ozon 发布。</small>
              </form>}
              {asset.status === "approved" && <div className="content-next-step"><CheckCircle2 size={14} />八项 QA 已通过，可进入 Listing 草稿引用；发布仍需独立审批</div>}
              {asset.status === "approved" && <form className="listing-handoff-form" onSubmit={(event) => createListingDraft(event, asset)}>
                <div>
                  <label>正 CM3 方案<select name="listing_scenario" defaultValue="" required>
                    <option value="" disabled>选择已复算方案</option>
                    {profitableRows.map((row) => <option key={row.scenario!.id} value={`${row.offer.id}::${row.scenario!.id}`}>
                      {row.offer.supplier_ref} · CM3 ¥{row.scenario!.cm3_cny} · {row.scenario!.cm3_rate}
                    </option>)}
                  </select></label>
                  <label>Ozon 类目 ID<input name="listing_category_id" required /></label>
                  <label>俄语标题<input name="listing_title" required /></label>
                  <label className="wide">俄语描述<textarea name="listing_description" required /></label>
                </div>
                <p>{profitableRows.length ? "草稿会锁定当前图片 Evidence 与利润场景；创建后只进入发布审批。" : "尚无正 CM3 供应商方案，禁止建立 Listing 草稿。"}</p>
                <button disabled={listingDraftBusy === asset.id || profitableRows.length === 0}>{listingDraftBusy === asset.id ? "正在建立…" : "建立待审批 Listing 草稿"}</button>
              </form>}
              {asset.status === "qa_failed" && asset.qa_results.length > 0 && <div className="image-qa-failures">
                <strong>退回原因</strong>
                {asset.qa_results.filter((item) => !item.passed).map((item) => <span key={item.check}>{imageQaDefinitions.find(([check]) => check === item.check)?.[1] ?? item.check} · {item.notes}</span>)}
              </div>}
            </article>;
          })}</div>}
        </section><section className="passport-review-panel" id="listing-approval">
          <div className="panel-title">
            <div><p className="eyebrow">IMMUTABLE LISTING REVIEW</p><h3>Ozon Listing 发布审批快照</h3></div>
            <span className={pendingListingApprovals.length ? "badge" : "gate ready"}>{pendingListingApprovals.length ? `${pendingListingApprovals.length} 项待独立审批` : "队列已清空"}</span>
          </div>
          {canReviewExecutionAuthority && <details className="listing-snapshot-details">
            <summary>复核专用 Ozon 执行身份</summary>
            {executionIdentityEvidence.length ? <form className="listing-handoff-form" onSubmit={reviewOzonExecutionIdentity}>
              <div>
                <label>身份盘点 Evidence<select name="execution_identity_evidence" defaultValue="" required><option value="">选择 OZN-001 原件</option>{executionIdentityEvidence.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename} · {item.sha256.slice(0, 12)}…</option>)}</select></label>
                <label>脱敏身份引用<input name="execution_identity_ref" placeholder="例如 ozon-listing-worker" maxLength={120} required /></label>
                <label>结论<select name="execution_identity_decision" defaultValue="accepted"><option value="accepted">接受</option><option value="rejected">拒绝</option></select></label>
              </div>
              <div className="review-actions">
                <label><input name="inventory_complete" type="checkbox" />盘点完整</label>
                <label><input name="credential_material_absent" type="checkbox" />不含凭证材料</label>
                <label><input name="owner_verified" type="checkbox" />Owner 已核验</label>
                <label><input name="caller_system_verified" type="checkbox" />调用系统已核验</label>
                <label><input name="scope_minimized" type="checkbox" />权限已最小化</label>
                <label><input name="dedicated_executor" type="checkbox" />身份专用于执行器</label>
              </div>
              <label>复核依据<textarea name="execution_identity_rationale" maxLength={2000} required /></label>
              <p>只登记脱敏身份引用和独立结论，不读取或保存 API Key；接受也不会开启运行开关。</p>
              <button disabled={lifecycleBusy?.startsWith("ozon-execution-identity:")}>{lifecycleBusy?.startsWith("ozon-execution-identity:") ? "正在固化…" : "固化身份复核"}</button>
            </form> : <p>尚无来源为 <code>ozon_execution_identity_inventory</code> 的 OZN-001 Grade A 原件；请先通过 Evidence 入口固化脱敏盘点。</p>}
          </details>}
          {pendingListingApprovals.length ? <div className="review-grid">{pendingListingApprovals.map((approval) => {
            const payload = approval.payload;
            const product = products.find((item) => item.id === String(payload.product_id ?? ""));
            const contentAssetIds = Array.isArray(payload.content_asset_ids) ? payload.content_asset_ids : [];
            const imageRefs = Array.isArray(payload.image_evidence_refs) ? payload.image_evidence_refs : [];
            const snapshot = String(payload.listing_snapshot_sha256 ?? "");
            return <article className="review-card listing-approval-card" key={approval.id}>
              <div className="review-head">
                <div><strong>{product?.sku ?? String(payload.product_id ?? "未知商品")}</strong><small>{String(payload.title ?? "无标题")}</small></div>
                <span>等待独立审批</span>
              </div>
              <div className="fact-list">
                <div><span>Ozon 类目</span><b>{String(payload.category_id ?? "未填写")}</b></div>
                <div><span>预计 CM3</span><b>¥{String(payload.expected_cm3_cny ?? "未知")} · {String(payload.expected_cm3_rate ?? "未知")}</b></div>
                <div><span>图片血缘</span><b>{contentAssetIds.length} 个内容资产 / {imageRefs.length} 份产物证据</b></div>
                <div><span>申请人</span><b>{approval.requested_by}</b></div>
              </div>
              <details className="listing-snapshot-details">
                <summary>查看审批中的完整文案与属性</summary>
                <p>{String(payload.description ?? "无描述")}</p>
                <pre>{JSON.stringify(payload.attributes ?? {}, null, 2)}</pre>
              </details>
              <div className="review-evidence"><ShieldCheck size={14} /><span>草稿摘要</span><b title={snapshot}>{snapshot ? `${snapshot.slice(0, 16)}…` : "摘要缺失"}</b></div>
              <div className="content-next-step"><ShieldCheck size={14} />平台未写入；必须由不同身份核对完整摘要后审批</div>
            </article>;
          })}</div> : <div className="empty"><CheckCircle2 size={25} /><strong>没有待审批 Listing</strong><p>批准图片建立草稿后，会在这里显示完整快照、CM3 和内容血缘。</p></div>}
          {approvedListingApprovals.length > 0 && <div className="review-grid">{approvedListingApprovals.map((listingApproval) => {
            const presentation = listingExecutionPresentations.get(listingApproval.id)!;
            const { draftId, plan, executionApproval, lifecycle, rollbackLifecycle, incident, blockers, evidenceReferences } = presentation;
            return <article className="review-card listing-approval-card" key={`execution:${listingApproval.id}`}>
              <div className="review-head"><div><strong>{String(listingApproval.payload.title ?? draftId)}</strong><small>准备执行计划 · 尚未发布</small></div><span>{lifecycle}</span></div>
              <div className="fact-list">
                <div><span>Listing Approval</span><b>{listingApproval.id} · {listingApproval.status}</b></div>
                <div><span>Execution Approval</span><b>{plan ? `${plan.approval_id} · ${executionApproval?.status ?? plan.approval_status}` : "尚未申请"}</b></div>
                <div><span>后端放行状态</span><b>{blockers.length ? blockers.join("、") : plan ? "无后端阻断" : "等待服务端预检"}</b></div>
                <div><span>执行生命周期</span><b>{lifecycle}</b></div>
                {rollbackLifecycle && <div><span>补偿生命周期</span><b>{rollbackLifecycle}</b></div>}
                {incident && <div><span>事故关联</span><b>{incident.id} · {incident.status}</b></div>}
              </div>
              {evidenceReferences.length ? <div className="review-evidence"><ShieldCheck size={14} /><span>脱敏证据引用</span><b>{evidenceReferences.map((item) => `${item.id} · ${item.sha256}`).join("；")}</b></div> : null}
              {canReviewExecutionAuthority && <details className="listing-snapshot-details">
                <summary>执行前俄语母语复核</summary>
                <form className="listing-handoff-form" onSubmit={(event) => reviewListingRussianNative(event, listingApproval)}>
                  <div>
                    <label>结论<select name="russian_review_decision" defaultValue="accepted"><option value="accepted">接受</option><option value="rejected">拒绝</option></select></label>
                    <label><input name="native_russian_verified" type="checkbox" />母语表达已核验</label>
                    <label><input name="listing_snapshot_reviewed" type="checkbox" />当前快照已完整核对</label>
                    <label><input name="terminology_accepted" type="checkbox" />术语可接受</label>
                    <label><input name="claims_grounded" type="checkbox" />宣称有证据</label>
                    <label><input name="ozon_policy_checked" type="checkbox" />Ozon 规则已核对</label>
                  </div>
                  <label>复核依据<textarea name="russian_review_rationale" maxLength={2000} required /></label>
                  <p>复核绑定当前 Listing 摘要；内容一旦变化必须重新复核。接受结论不会直接发布。</p>
                  <button disabled={lifecycleBusy === `listing-russian-review:${draftId}`}>{lifecycleBusy === `listing-russian-review:${draftId}` ? "正在固化…" : "固化俄语复核"}</button>
                </form>
              </details>}
              {!plan && <form className="listing-handoff-form" onSubmit={(event) => prepareListingExecutionPlan(event, listingApproval)}>
                <div>
                  <label>前置快照 SHA-256<input name="execution_state_hash" minLength={64} maxLength={64} required /></label>
                  <label>前置状态证据<select name="execution_evidence" defaultValue="" required><option value="">选择证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select></label>
                  <label>本次预期损失<input name="execution_expected_loss" type="number" min="0" step="0.01" required /></label>
                  <label>最大预期损失<input name="execution_max_expected_loss" type="number" min="0" step="0.01" required /></label>
                  <label>风险币种<input name="execution_risk_currency" defaultValue="CNY" minLength={3} maxLength={3} required /></label>
                </div>
                <p>服务端负责目标、适配器、Ozon item、readiness 与风险放行规则；网页只提交幂等键、前置证据/哈希和有界风险。</p>
                <button disabled={lifecycleBusy === `listing-execution-plan:${draftId}`}>{lifecycleBusy === `listing-execution-plan:${draftId}` ? "正在准备…" : "准备执行计划"}</button>
              </form>}
            </article>;
          })}</div>}
        </section><section className="passport-review-panel" id="passport-review">
          <div className="panel-title">
            <div><p className="eyebrow">HUMAN REVIEW</p><h3>Passport 人工审核</h3></div>
            <span className={passportReviews.length ? "badge" : "gate ready"}>{passportReviews.length ? `${passportReviews.length} 项待审` : "队列已清空"}</span>
          </div>
          {passportReviews.length ? <div className="review-grid">{passportReviews.map((item) => {
            const key = item.passport.id;
            const busy = reviewingKey === key;
            return <article className="review-card" key={key}>
              <div className="review-head">
                <div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div>
                <span>{passportLabels[item.passport.kind]} · V{item.passport.version}</span>
              </div>
              <div className="fact-list">{Object.entries(item.passport.facts).filter(([name]) => name !== "decision").map(([name, value]) => <div key={name}><span>{name}</span><b>{typeof value === "object" ? JSON.stringify(value) : String(value)}</b></div>)}</div>
              <div className="review-evidence"><ShieldCheck size={14} /><span>{item.passport.evidence.length} 份不可变证据</span>{item.passport.missing_fields.length ? <b>缺少 {item.passport.missing_fields.join("、")}</b> : <b>必填事实完整</b>}</div>
              <label>审核说明<textarea value={reviewNotes[key] ?? ""} onChange={(event) => setReviewNotes((current) => ({ ...current, [key]: event.target.value }))} placeholder="记录核查依据；阻断时必须填写原因" /></label>
              <div className="review-actions">
                <button className="reject" disabled={busy} onClick={() => reviewPassport(item, "blocked")}>阻断并退回</button>
                <button className="approve" disabled={busy || item.passport.missing_fields.length > 0} onClick={() => reviewPassport(item, "approved")}>{busy ? "提交中…" : "批准 Passport"}</button>
              </div>
            </article>;
          })}</div> : <div className="empty"><CheckCircle2 size={25} /><strong>没有待审核 Passport</strong><p>新的 SKU Episode 提交后会自动进入这里。</p></div>}
        </section></>;
}
