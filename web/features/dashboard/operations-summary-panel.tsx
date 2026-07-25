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
import type { Health, IdentityStatus, OperatingWorkbenchBriefing, ProductReadiness, Recommendation, SourceConnector } from "./contracts";

const passportLabels = { product: "商品资料", compliance: "俄罗斯合规", quality: "样品质量" } as const;

type Props = {
  identityStatus: IdentityStatus;
  health: Record<string, Health>;
  operatingWorkbench: OperatingWorkbenchBriefing | null;
  recommendations: Recommendation[];
  sourceConnectors: SourceConnector[];
  offersCount: number;
  skuReadiness: ProductReadiness[];
};

const connectorStatusLabels: Record<string, string> = {
  ready: "可采集",
  idle: "待配置目标",
  needs_human_login: "需人工登录",
  human_action_required: "需人工接管",
  degraded: "异常停机",
  not_configured: "工具未配置",
  managed_elsewhere: "官方接口管理",
  not_automated: "仅受控研究",
};

export function OperationsSummaryPanel({ identityStatus, health, operatingWorkbench, recommendations, sourceConnectors, offersCount, skuReadiness }: Props) {
  const identityReady = identityStatus === "ready";
  const readySkuCount = skuReadiness.filter((item) => item.ready_for_validation).length;
  const configuredTools = Object.entries(health);
  const onlineTools = configuredTools.filter(([, item]) => item.status === "ok").length;
  const platformCount = new Set(sourceConnectors.map((item) => item.platform)).size;
  const agentMode = operatingWorkbench?.mode === "shadow_advisory" ? "影子建议" : "状态未知";

  return <>
    <section className="metrics">
      <article><span className="metric-icon green"><CircleDollarSign /></span><div><p>CM3 净利润</p><strong>{identityReady ? "待导入" : "未知"}</strong><small>{identityReady ? "真实费用齐全后计算" : "身份服务恢复后读取"}</small></div></article>
      <article><span className="metric-icon blue"><ShieldCheck /></span><div><p>SKU 准入门</p><strong>{identityReady ? `${readySkuCount} / 3` : "未知"}</strong><small>{identityReady ? skuReadiness.length ? "三类护照全部批准才可上线" : "先录入 3 个真实候选 SKU" : "身份服务恢复后读取"}</small></div></article>
      <article><span className="metric-icon violet"><Waypoints /></span><div><p>全球货源平台</p><strong>{identityReady ? platformCount : "未知"}</strong><small>{identityReady ? `${offersCount} 个正式商品报价已入库` : "正式报价数量未知"}</small></div></article>
      <article><span className="metric-icon amber"><CheckCircle2 /></span><div><p>工具连接</p><strong>{identityReady ? `${onlineTools} / ${configuredTools.length}` : "未知"}</strong><small>{identityReady ? configuredTools.length ? configuredTools.map(([key]) => key).join(" · ") : "未配置可选工具" : "连接状态未读取"}</small></div></article>
    </section>

    <section className="grid">
      <article className={`panel agents${operatingWorkbench ? "" : " unavailable"}`}>
        <div className="panel-title"><div><p className="eyebrow">AI SQUAD</p><h3>Agent 团队</h3></div><span className="badge">{agentMode}</span></div>
        <div className="agent-list">
          {operatingWorkbench ? operatingWorkbench.agents.map((agent, index) => (
            <div className="agent" key={agent.agent_id}><span>{index + 1}</span><div><strong>{agent.name}</strong><small>{agent.work_item_count ? `${agent.work_item_count} 项 · ${agent.current_focus}` : agent.current_focus}</small></div><Clock3 size={16} /></div>
          )) : <div className="empty"><TriangleAlert size={25} /><strong>Agent 简报暂不可用</strong><p>页面不会自行猜测 Agent 状态；请检查控制平面只读简报接口。</p></div>}
        </div>
      </article>

      <article className="panel">
        <div className="panel-title"><div><p className="eyebrow">INFRASTRUCTURE</p><h3>已配置工具状态</h3></div><Database size={20} /></div>
        <div className="health-list">
          {configuredTools.length ? configuredTools.map(([key, item]) => {
            const ok = item.status === "ok";
            return <div key={key}><span className={ok ? "health-dot ok" : "health-dot"} /><div><strong>{item.name || key}</strong><small>{item.detail || (ok ? "连接正常" : "等待连接")}</small></div><span className={ok ? "state ok" : "state"}>{ok ? "在线" : "离线"}</span></div>;
          }) : <div className="empty"><Database size={25} /><strong>{identityReady ? "没有已配置的可选工具" : "工具状态未知"}</strong><p>{identityReady ? "核心经营功能不依赖可选集成。" : "身份服务恢复后重新读取连接状态。"}</p></div>}
        </div>
        <div className="license-note"><ShieldCheck size={18} /><p><strong>商业授权保护已开启</strong><span>授权不明的模型默认不能参与生产。</span></p></div>
      </article>

      <article className="panel recommendations">
        <div className="panel-title"><div><p className="eyebrow">DECISIONS</p><h3>最新经营建议</h3></div><BarChart3 size={20} /></div>
        {recommendations.length ? recommendations.slice(0, 4).map((item) => (
          <div className="recommendation" key={item.id}><span className="risk">{item.risk}</span><div><strong>{item.action}</strong><small>{item.agent} · {item.status}</small></div><b>{item.expected_cm3_delta ? `¥${item.expected_cm3_delta}` : "待评估"}</b></div>
        )) : <div className="empty"><TriangleAlert size={25} /><strong>{identityReady ? "还没有可验证的建议" : "经营建议状态未知"}</strong><p>{identityReady ? "导入经营数据后，Agent 才会生成有证据的建议。" : "身份服务恢复前不展示空数据结论。"}</p></div>}
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
        })}</div> : <div className="empty"><Boxes size={25} /><strong>{identityReady ? "尚未录入真实候选 SKU" : "SKU 状态未知"}</strong><p>{identityReady ? "下一步先确定 3 个 SKU，再逐个补齐商品、合规和质量护照。" : "身份服务恢复前不把未知显示为零。"}</p></div>}
      </article>

      <article className="panel source-platforms">
        <div className="panel-title"><div><p className="eyebrow">GLOBAL SOURCING</p><h3>货源连接器</h3></div><Waypoints size={20} /></div>
        {sourceConnectors.length ? <div className="platform-chips">{sourceConnectors.map((item) => <span className={item.status} key={item.name}>{item.platform}<small>{item.name} · {connectorStatusLabels[item.status] ?? item.status}</small><em>{item.error_code ?? (item.target_count ? `${item.target_count} 个目标` : item.search_count ? `${item.search_count} 个受控搜索` : item.ingestion)}</em></span>)}</div> : <div className="empty"><Waypoints size={25} /><strong>连接器状态未知</strong><p>没有把未加载状态显示成“已就绪”。</p></div>}
        <div className="license-note"><Database size={18} /><p><strong>PostgreSQL 事实底座</strong><span>报价、证据、利润方案和上架草稿统一留痕。</span></p></div>
      </article>
    </section>
  </>;
}
