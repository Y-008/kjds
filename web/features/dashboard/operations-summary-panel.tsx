import {
  BarChart3,
  Boxes,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Database,
  ShieldCheck,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import type { Health, ProductReadiness, Recommendation, SourceConnector } from "./contracts";

const passportLabels = { product: "商品资料", compliance: "俄罗斯合规", quality: "样品质量" } as const;

type Props = {
  health: Record<string, Health>;
  recommendations: Recommendation[];
  sourceConnectors: SourceConnector[];
  offersCount: number;
  skuReadiness: ProductReadiness[];
};

export function OperationsSummaryPanel({ health, recommendations, sourceConnectors, offersCount, skuReadiness }: Props) {
  const readySkuCount = skuReadiness.filter((item) => item.ready_for_validation).length;
  const configuredTools = Object.entries(health);
  const onlineTools = configuredTools.filter(([, item]) => item.status === "ok").length;

  return <>
    <section className="metrics">
      <article><span className="metric-icon green"><CircleDollarSign /></span><div><p>CM3 净利润</p><strong>待导入</strong><small>真实费用齐全后计算</small></div></article>
      <article><span className="metric-icon blue"><ShieldCheck /></span><div><p>SKU 准入门</p><strong>{readySkuCount} / 3</strong><small>{skuReadiness.length ? "三类护照全部批准才可上线" : "先录入 3 个真实候选 SKU"}</small></div></article>
      <article><span className="metric-icon violet"><Waypoints /></span><div><p>全球货源平台</p><strong>{sourceConnectors.length}</strong><small>{offersCount} 个商品报价已入库</small></div></article>
      <article><span className="metric-icon amber"><CheckCircle2 /></span><div><p>工具连接</p><strong>{onlineTools} / {configuredTools.length}</strong><small>{configuredTools.length ? configuredTools.map(([key]) => key).join(" · ") : "未配置可选工具"}</small></div></article>
    </section>

    <section className="grid">
      <article className="panel agents">
        <div className="panel-title"><div><p className="eyebrow">AI SQUAD</p><h3>Agent 团队</h3></div><span className="badge">影子模式</span></div>
        <div className="agent-list">
          {["市场分析", "商品策略", "俄语 Listing", "内容生产", "运营建议", "利润审计", "质量检查"].map((name, index) => (
            <div className="agent" key={name}><span>{index + 1}</span><div><strong>{name}</strong><small>{index < 2 ? "等待数据" : "等待上游任务"}</small></div><Clock3 size={16} /></div>
          ))}
        </div>
      </article>

      <article className="panel">
        <div className="panel-title"><div><p className="eyebrow">INFRASTRUCTURE</p><h3>已配置工具状态</h3></div><Database size={20} /></div>
        <div className="health-list">
          {configuredTools.length ? configuredTools.map(([key, item]) => {
            const ok = item.status === "ok";
            return <div key={key}><span className={ok ? "health-dot ok" : "health-dot"} /><div><strong>{item.name || key}</strong><small>{item.detail || (ok ? "连接正常" : "等待连接")}</small></div><span className={ok ? "state ok" : "state"}>{ok ? "在线" : "离线"}</span></div>;
          }) : <div className="empty"><Database size={25} /><strong>没有已配置的可选工具</strong><p>核心经营功能不依赖可选集成。</p></div>}
        </div>
        <div className="license-note"><ShieldCheck size={18} /><p><strong>商业授权保护已开启</strong><span>授权不明的模型默认不能参与生产。</span></p></div>
      </article>

      <article className="panel recommendations">
        <div className="panel-title"><div><p className="eyebrow">DECISIONS</p><h3>最新经营建议</h3></div><BarChart3 size={20} /></div>
        {recommendations.length ? recommendations.slice(0, 4).map((item) => (
          <div className="recommendation" key={item.id}><span className="risk">{item.risk}</span><div><strong>{item.action}</strong><small>{item.agent} · {item.status}</small></div><b>{item.expected_cm3_delta ? `¥${item.expected_cm3_delta}` : "待评估"}</b></div>
        )) : <div className="empty"><TriangleAlert size={25} /><strong>还没有可验证的建议</strong><p>导入经营数据后，Agent 才会生成有证据的建议。</p></div>}
      </article>

      <article className="panel sku-gates">
        <div className="panel-title"><div><p className="eyebrow">GATE 0–1</p><h3>三 SKU 准入门</h3></div><ShieldCheck size={20} /></div>
        {skuReadiness.length ? <div className="sku-list">{skuReadiness.map((item) => {
          const approved = item.passports.filter((passport) => passport.status === "approved").length;
          const blocked = item.passports.some((passport) => passport.status === "blocked");
          const next = item.passports.find((passport) => passport.status !== "approved");
          return <div className="sku-card" key={item.product.id}>
            <div className="sku-card-head"><div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div><span className={blocked ? "gate blocked" : item.ready_for_validation ? "gate ready" : "gate"}>{blocked ? "已阻断" : item.ready_for_validation ? "可验证" : `${approved}/3`}</span></div>
            <div className="passport-row">{item.passports.map((passport) => <span className={passport.status} key={passport.kind}>{passportLabels[passport.kind]}</span>)}</div>
            <p>{item.ready_for_validation ? "资料、合规和样品质量均已通过人工批准。" : blocked ? "存在否决结论，停止采购和上架。" : next ? `下一步：补齐${passportLabels[next.kind]}（缺 ${next.missing_fields.length} 项）` : "等待审核。"}</p>
          </div>;
        })}</div> : <div className="empty"><Boxes size={25} /><strong>尚未录入真实候选 SKU</strong><p>下一步先确定 3 个 SKU，再逐个补齐商品、合规和质量护照。</p></div>}
      </article>

      <article className="panel source-platforms">
        <div className="panel-title"><div><p className="eyebrow">GLOBAL SOURCING</p><h3>货源连接器</h3></div><Waypoints size={20} /></div>
        <div className="platform-chips">{sourceConnectors.map((item) => <span key={item.platform}>{item.platform}<small>{item.ingestion}</small></span>)}</div>
        <div className="license-note"><Database size={18} /><p><strong>PostgreSQL 事实底座</strong><span>报价、证据、利润方案和上架草稿统一留痕。</span></p></div>
      </article>
    </section>
  </>;
}
