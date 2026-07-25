import {
  BadgeRussianRuble,
  Boxes,
  ChartNoAxesCombined,
  FileSearch,
  PackageCheck,
  RadioTower,
  Search,
  ShoppingCart,
  Tags,
  Truck,
} from "lucide-react";
import type { DashboardModel } from "./use-dashboard-controller";

const capabilityGroups = [
  {
    icon: Search,
    title: "选品与市场",
    status: "已接入证据门",
    links: [
      ["候选商品研究", "#candidate-research"],
      ["热销/类目/品牌信号", "#candidate-research"],
      ["商品事实工作台", "#sku-workbench"],
    ],
  },
  {
    icon: Tags,
    title: "关键词与竞品",
    status: "只读研究信号",
    links: [
      ["关键词与需求证据", "#reality-gate"],
      ["竞品与店铺快照", "#sku-workbench"],
      ["变化与异常队列", "#operations-control"],
    ],
  },
  {
    icon: Boxes,
    title: "商品与内容",
    status: "Passport 管控",
    links: [
      ["商品库", "#sku-intake"],
      ["图片与视频", "#product-media-intake"],
      ["Ozon 商品卡草稿", "#listing-approval"],
    ],
  },
  {
    icon: BadgeRussianRuble,
    title: "利润与经营",
    status: "15 项全成本",
    links: [
      ["三家供应商比价", "#sourcing-intake"],
      ["实际成本复核", "#actual-cost-review"],
      ["增长实验", "#causal-experiments"],
    ],
  },
  {
    icon: Truck,
    title: "订单与跨境履约",
    status: "销售出单后触发",
    links: [
      ["Ozon 销售单", "#sales-fulfillment"],
      ["跨境巴士动态选仓", "#sales-fulfillment"],
      ["采购审批与国际交接", "#sales-fulfillment"],
    ],
  },
  {
    icon: RadioTower,
    title: "店铺与自动化",
    status: "默认只读",
    links: [
      ["官方数据导入", "#ozon-import"],
      ["受控执行与监控", "#operations-control"],
      ["审批中心", "#listing-approval"],
    ],
  },
] as const;

export function IntelligenceHubPanel({ model }: { model: DashboardModel }) {
  const liveConnectors = model.sourceConnectors.filter((item) =>
    ["ready", "connected", "authenticated"].includes(item.status),
  ).length;
  return (
    <section className="intelligence-hub" id="capability-map" aria-labelledby="capability-map-title">
      <div className="intelligence-hub-head">
        <div>
          <p className="eyebrow">KJDS COMMERCE INTELLIGENCE</p>
          <h2 id="capability-map-title">从市场机会到真实履约，一套系统闭环</h2>
          <p>竞品负责启发功能，KJDS 负责保存事实、证据、利润、审批和订单责任。</p>
        </div>
        <div className="hub-live-facts" aria-label="当前真实数据概览">
          <span><FileSearch size={15} /><b>{model.evidenceRecords.length}</b> 份证据</span>
          <span><PackageCheck size={15} /><b>{model.products.length}</b> 个商品</span>
          <span><ChartNoAxesCombined size={15} /><b>{liveConnectors}</b> 个可用连接器</span>
        </div>
      </div>
      <div className="capability-grid">
        {capabilityGroups.map(({ icon: Icon, title, status, links }) => (
          <article key={title}>
            <div className="capability-title"><span><Icon size={18} /></span><div><strong>{title}</strong><small>{status}</small></div></div>
            <nav aria-label={title}>
              {links.map(([label, href]) => <a href={href} key={label}>{label}<span>→</span></a>)}
            </nav>
          </article>
        ))}
      </div>
      <div className="three-order-rule">
        <div><ShoppingCart size={17} /><strong>商品卡 / Listing</strong><span>上线售卖，不创建采购</span></div>
        <i>→</i>
        <div><PackageCheck size={17} /><strong>Ozon 销售订单</strong><span>买家真实出单，建立履约需求</span></div>
        <i>→</i>
        <div><Truck size={17} /><strong>供应商采购订单</strong><span>动态选仓并独立批准后确认</span></div>
      </div>
    </section>
  );
}
