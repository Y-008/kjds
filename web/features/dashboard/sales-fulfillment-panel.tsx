import { AlertTriangle, CheckCircle2, MapPin, PackageCheck, Truck } from "lucide-react";
import type { DashboardModel } from "./use-dashboard-controller";

const statusLabels: Record<string, string> = {
  awaiting_route: "待选择物流路线",
  route_selected: "路线与国内仓已锁定",
  approval_pending: "采购审批中",
  supplier_order_confirmed: "供应商订单已确认",
  domestic_shipped: "发往国内仓",
  warehouse_received: "国内仓已签收",
  packed_for_export: "已打包贴标",
  international_handover: "已交国际物流",
  cancelled: "已取消",
};

function nextAction(status: string) {
  return {
    awaiting_route: "在跨境巴士读取该订单当时可用的 Ozon 渠道并固化仓址证据",
    route_selected: "复算订单级 CM3，并申请绑定销售单、报价和仓址的采购审批",
    approval_pending: "等待独立审批；禁止申请人自批",
    supplier_order_confirmed: "记录供应商国内运单和发货证据",
    domestic_shipped: "等待所选国内仓签收并核对数量",
    warehouse_received: "记录实测包装尺寸、重量和物流标签",
    packed_for_export: "按已选承运商完成国际交接",
    international_handover: "跟踪国际物流并等待 Ozon 履约回读",
    cancelled: "保留取消原因和历史，不自动重建",
  }[status] ?? "检查订单状态";
}

export function SalesFulfillmentPanel({ model }: { model: DashboardModel }) {
  return (
    <section className="sales-fulfillment-panel" id="sales-fulfillment" aria-labelledby="sales-fulfillment-title">
      <div className="panel-title">
        <div><p className="eyebrow">ORDER-TRIGGERED PROCUREMENT</p><h3 id="sales-fulfillment-title">销售出单后的采购与跨境履约</h3></div>
        <span className="badge">{model.salesFulfillmentPlans.length} 个订单履约需求</span>
      </div>
      <div className="fulfillment-boundary">
        <AlertTriangle size={18} />
        <p><strong>上线不等于采购</strong><span>只有真实 Ozon 销售单才能进入这里。国内收货地址在选定跨境巴士路线后才出现；系统不会自动下 1688 订单或付款。</span></p>
      </div>
      {model.salesFulfillmentPlans.length ? <div className="fulfillment-list">
        {model.salesFulfillmentPlans.map((plan) => (
          <article key={plan.id}>
            <header>
              <div><small>Ozon 销售单</small><strong>{plan.external_sales_order_id}</strong><span>{plan.quantity} 件 · {plan.product_id}</span></div>
              <b className={`fulfillment-state ${plan.status}`}>{statusLabels[plan.status] ?? plan.status}</b>
            </header>
            <div className="fulfillment-route">
              <MapPin size={16} />
              {plan.route ? <p><strong>{plan.route.carrier_code} · {plan.route.service_code}</strong><span>{plan.route.warehouse_name} · {plan.route.warehouse_address}</span><small>地址有效时间 {new Date(plan.route.address_valid_at).toLocaleString("zh-CN")}</small></p>
                : <p><strong>国内仓地址尚未产生</strong><span>这是正确状态：必须先针对该销售单选择物流路线。</span></p>}
            </div>
            <footer><CheckCircle2 size={15} /><span>{nextAction(plan.status)}</span></footer>
          </article>
        ))}
      </div> : <div className="fulfillment-empty"><PackageCheck size={22} /><div><strong>尚无真实销售订单触发的履约需求</strong><span>Listing 发布后保持等待；Ozon 买家出单并被 KJDS 记录后，才建立一条订单绑定需求。</span></div><Truck size={22} /></div>}
    </section>
  );
}
