export const passportLabels = { product: "商品资料", compliance: "俄罗斯合规", quality: "样品质量" } as const;
export const productMediaRoleLabels: Record<string, string> = {
  front_main: "正面主图", back: "背面", side: "侧面", detail: "细节",
  accessories: "配件", packaging: "包装", scale_reference: "比例参照",
};
export const candidateMetricDefinitions = [
  ["demand_signal", "需求信号", "类目需求百分位；至少 28 天、30 个样本；询价线 ≥50", 30, 30],
  ["competition_gap", "竞争缺口", "类目供需缺口百分位；至少 28 天、30 个样本；询价线 ≥50", 30, 30],
  ["supplier_available", "可采购性", "是否已有可核验供应来源；至少核验 1 个供应对象", 30, 1],
  ["compliance_redline", "合规红线", "按当前官方规则核验；一旦确认红线，候选立即淘汰", 30, 1],
  ["return_risk", "退货风险", "预期 30 日退货率百分比；至少 28 天、30 个样本；询价线 ≤30%", 30, 30],
] as const;
export const candidateMetricLabels = Object.fromEntries(candidateMetricDefinitions.map(([key, label]) => [key, label]));
export const sourcingCostDefinitions = [
  ["product_cost", "采购成本"], ["domestic_logistics", "国内物流"],
  ["international_logistics", "头程物流"], ["packaging", "包装"],
  ["warehousing", "仓储"], ["customs", "关税"], ["tax", "税费"],
  ["last_mile", "尾程"], ["platform_fee", "平台佣金"], ["advertising", "广告"],
  ["return", "退款退货"], ["fx", "汇兑"], ["capital_cost", "资金占用"],
  ["aftersales", "售后"], ["loss", "损耗"],
] as const;
export const costStateLabels = { estimate: "预估", actual: "实际", unknown: "未知（阻断）" } as const;
export const financeReviewRecordTypes = new Set(["ozon_accrual", "ozon_fee", "ozon_return", "ozon_settlement"]);
export const imageQaDefinitions = [
  ["factual_grounding", "事实一致", "商品事实、参数与已批准 Passport 一致"],
  ["policy", "平台规则", "主图、文字和表达符合当前 Ozon 规则"],
  ["localization", "俄语本地化", "俄语自然、无歧义，适合目标消费者"],
  ["ip_rights", "知识产权", "图片、字体、品牌和素材权利可追溯"],
  ["brand", "品牌一致", "视觉语气、颜色与品牌规范一致"],
  ["product_fidelity", "商品保真", "外观、颜色、结构、配件和数量未被改变"],
  ["source_provenance", "来源血缘", "原图、权利文件、处理结果与 Evidence 对应"],
  ["text_accuracy", "文字参数", "图中俄语、尺寸、数量和声明准确无误"],
] as const;
export const procurementStatusLabels: Record<string, string> = {
  approved_to_order: "已批准，待确认样品单", order_confirmed: "供应商已确认", shipped: "样品运输中",
  received: "样品已签收", inspected: "验货完成，待决定", rework_required: "需要返工复验",
  golden_sample_approved: "黄金样已批准", sample_rejected: "样品已淘汰", cancelled: "样品单已取消",
};
export const procurementEventLabels: Record<string, string> = {
  order_confirmed: "确认样品订单", shipped: "记录发货", received: "记录签收", inspection_completed: "完成验货",
  golden_sample_approved: "批准黄金样", sample_rejected: "淘汰样品", rework_required: "要求返工", cancelled: "取消",
};
export const decisionStatusLabels: Record<string, string> = {
  clarification_required: "需要补充关键信息", ready_for_clarification: "可以开始澄清",
  evidence_pending: "等待可验证证据", ready_for_render: "可以生成通俗解释",
  ready_for_analysis: "可以进入分析",
};
