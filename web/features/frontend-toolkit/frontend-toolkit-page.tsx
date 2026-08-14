"use client";

import { useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  BadgeCheck,
  ChartSpline,
  ChevronRight,
  LockKeyhole,
  MessageSquareMore,
  ShieldCheck,
  Sparkles,
  Users,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import styles from "./frontend-toolkit.module.css";

type TierId = "starter" | "growth" | "scale";

type SellerTier = {
  id: TierId;
  rank: string;
  badge: string;
  title: string;
  subtitle: string;
  audience: string;
  outcome: string;
  reason: string;
  highlights: string[];
  metrics: Array<{ label: string; value: string }>;
  cta: string;
  recommended?: boolean;
};

type DecisionTool = {
  name: string;
  href: string;
  role: string;
  summary: string;
  output: string;
  reason: string;
  icon: LucideIcon;
  recommended?: boolean;
};

type JourneyStep = {
  index: string;
  title: string;
  description: string;
  icon: LucideIcon;
};

type ReasonCard = {
  title: string;
  description: string;
  icon: LucideIcon;
};

type ProofCard = {
  label: string;
  value: string;
  note: string;
};

type RiskPoint = {
  title: string;
  description: string;
};

type ImplementationPhase = {
  step: string;
  title: string;
  deliverable: string;
  description: string;
};

type StackEntry = {
  name: string;
  href: string;
  status: string;
  summary: string;
  fit: string;
};

const heroStats = [
  { value: "3", label: "设计工具" },
  { value: "5", label: "研究阶段" },
  { value: "3", label: "内部预览层级" },
  { value: "1", label: "主入口" },
];

const heroTags = [
  "internal_preview",
  "not_for_sale",
  "open-design 主流程",
  "hallmark 审美闸门",
  "design-md-chrome 采样",
  "研究路径",
  "高端质感",
];

const journeyCurve = [
  { stage: "看见", score: 32 },
  { stage: "理解", score: 57 },
  { stage: "信任", score: 81 },
  { stage: "行动", score: 96 },
];

const decisionTools: DecisionTool[] = [
  {
    name: "open-design",
    href: "https://github.com/nexu-io/open-design",
    role: "主生成引擎",
    summary: "把页面结构、组件语义和设计语言收敛成可复用蓝图，适合作为第一层输出。",
    output: "页面结构 / 组件蓝图 / DESIGN.md",
    reason: "它负责把零散想法整理成可执行方案，适合把创意转成稳定页面。",
    icon: Sparkles,
    recommended: true,
  },
  {
    name: "hallmark",
    href: "https://github.com/Nutlope/hallmark",
    role: "审美闸门",
    summary: "过滤掉 AI 味、拼贴感和过度装饰，把信息层级和视觉质感拉回正轨。",
    output: "审美规则 / 视觉约束 / 文案标准",
    reason: "如果没有审美闸门，生成得再多也会变成杂乱的拼图。",
    icon: ShieldCheck,
    recommended: true,
  },
  {
    name: "design-md-chrome",
    href: "https://github.com/bergside/design-md-chrome",
    role: "标杆采样",
    summary: "从高质感页面提取结构、层级和按钮节奏，快速形成设计输入。",
    output: "竞品样式采样 / 参考库 / 设计输入",
    reason: "它负责定标样式和信息密度，而不是替代最终设计。",
    icon: ChartSpline,
    recommended: true,
  },
];

const sellerTiers: SellerTier[] = [
  {
    id: "starter",
    rank: "01",
    badge: "起盘方案",
    title: "新卖家起盘包",
    subtitle: "先把第一单做顺，再把页面做得像品牌",
    audience: "刚入场 / 刚换类目 / 想快速试错",
    outcome: "目标：验证起盘路径是否清晰",
    reason: "用于检验新卖家是否能更快理解方案结构和下一步动作。",
    highlights: ["选品与测算预览", "首屏内容结构", "低门槛上架路径", "基础风控提醒"],
    metrics: [
      { label: "验证焦点", value: "机会是否成立" },
      { label: "内部诉求", value: "少走弯路" },
      { label: "界面重点", value: "清晰可信" },
      { label: "预期观察", value: "路径是否顺畅" },
    ],
    cta: "预览起盘方案",
  },
  {
    id: "growth",
    rank: "02",
    badge: "增长方案",
    title: "成长卖家加速包",
    subtitle: "把利润、库存、内容和执行拉成一个完整闭环",
    audience: "已有订单 / 想提升毛利 / 想减少返工",
    outcome: "目标：验证毛利/库存改善机会",
    reason: "用于检验利润、库存、内容与执行能否在同一页被讲清楚。",
    highlights: ["利润测算与复盘", "库存预警与周转", "内容工厂与批量处理", "多店协同与审批"],
    metrics: [
      { label: "验证焦点", value: "毛利改善机会" },
      { label: "观察项", value: "库存周转表达" },
      { label: "风险关注", value: "流程返工" },
      { label: "协作项", value: "多店协调" },
    ],
    cta: "预览增长方案",
    recommended: true,
  },
  {
    id: "scale",
    rank: "03",
    badge: "治理方案",
    title: "成熟卖家治理包",
    subtitle: "重点不是做更多，而是做得更稳、更统一、更可复制",
    audience: "多店铺 / 多角色 / 更重风控和标准化",
    outcome: "目标：验证治理/复制路径",
    reason: "用于检验多店、多角色和标准化协作是否能被清晰表达。",
    highlights: ["权限体系与审批", "统一经营看板", "标准化复盘", "规模化风险控制"],
    metrics: [
      { label: "治理焦点", value: "权限清晰" },
      { label: "协作焦点", value: "流程统一" },
      { label: "经营焦点", value: "数据一致" },
      { label: "扩张焦点", value: "可复制" },
    ],
    cta: "预览治理方案",
  },
];

const journeySteps: JourneyStep[] = [
  {
    index: "01",
    title: "首屏校验",
    description: "高端视觉和一句话价值主张先把内部评审停住。",
    icon: Sparkles,
  },
  {
    index: "02",
    title: "价值理解",
    description: "三档预览路径让内部评审立刻知道页面在讲什么。",
    icon: Users,
  },
  {
    index: "03",
    title: "方案确认",
    description: "把验证目标、边界和适合场景讲透，形成内部结论。",
    icon: ShieldCheck,
  },
  {
    index: "04",
    title: "内部跳转",
    description: "单主 CTA 只负责跳到锚点或切换预览，不承担销售动作。",
    icon: Waypoints,
  },
];

const reasonCards: ReasonCard[] = [
  {
    title: "高级感先到位",
    description: "深色、金属、玻璃、留白和克制动效，第一眼就像成熟品牌。",
    icon: Sparkles,
  },
  {
    title: "内容足够厚",
    description: "每一屏都在讲验证目标，不是空泛的功能罗列。",
    icon: MessageSquareMore,
  },
  {
    title: "信任边界清楚",
    description: "明确这是内部研究预览，不混淆成已上线客户页。",
    icon: LockKeyhole,
  },
  {
    title: "适合规模化",
    description: "从单页研究到后续产品化都能接住。",
    icon: Users,
  },
];

const proofCards: ProofCard[] = [
  {
    label: "信息顺序",
    value: "先看懂再行动",
    note: "把理解成本压到最低，便于评审判断下一步。",
  },
  {
    label: "视觉语言",
    value: "深色金属统一",
    note: "整体不散、不乱、不廉价，第一眼就像成熟产品。",
  },
  {
    label: "交互节奏",
    value: "单主 CTA",
    note: "按钮体系统一，减少分心，保持内部操作路径一致。",
  },
  {
    label: "响应能力",
    value: "桌面 / 移动双端",
    note: "层级在小屏不塌，内容仍然能顺畅推进。",
  },
];

const riskPoints: RiskPoint[] = [
  {
    title: "不提前承诺未证实结果",
    description: "页面只讲可验证的结构、流程和体验，不写夸张的收益承诺。",
  },
  {
    title: "不让用户多走一步",
    description: "全页保留一个主 CTA，避免把评审分流到多个判断入口。",
  },
  {
    title: "不靠堆砌制造高级感",
    description: "高级感来自层级、留白、节奏和克制，而不是元素数量。",
  },
  {
    title: "不把工具链做成大杂烩",
    description: "主流程只用 3 个 GitHub 工具，其余只作为辅助或参考。",
  },
];

const implementationPhases: ImplementationPhase[] = [
  {
    step: "01",
    title: "定义研究目标",
    deliverable: "一页 brief",
    description: "明确研究对象、主入口、信任资产和 KPI，把页面先定到内部预览方向。",
  },
  {
    step: "02",
    title: "采样标杆页面",
    deliverable: "DESIGN.md",
    description: "抓 3-5 个高质感竞品页，提炼结构、色彩、按钮节奏和信息密度。",
  },
  {
    step: "03",
    title: "生成设计蓝图",
    deliverable: "组件蓝图",
    description: "用 open-design 生成页面结构，再用 hallmark 过滤 AI 味和拼贴感。",
  },
  {
    step: "04",
    title: "完成页面落地",
    deliverable: "研究页 / 详情 / 控制台样式草案",
    description: "把首屏、分层、研究路径、证明区和风险逆转区一次补齐。",
  },
  {
    step: "05",
    title: "QA 与验证",
    deliverable: "桌面 / 移动 / A/B",
    description: "检查可访问性、性能和预览路径，只保留高确定性的方案。",
  },
];

const runtimeStack: StackEntry[] = [
  {
    name: "Next.js + CSS Modules",
    href: "https://github.com/vercel/next.js",
    status: "页面骨架",
    summary: "当前页面已经使用的路由与样式底座，适合承载内部研究页的可读结构。",
    fit: "路由 / 组件 / 局部样式",
  },
  {
    name: "Radix Primitives",
    href: "https://github.com/radix-ui/primitives",
    status: "交互底座",
    summary: "强可访问的交互底座，适合做 Tabs、Dialog、Dropdown、Tooltip。",
    fit: "交互 / 可访问性 / 结构化布局",
  },
  {
    name: "Motion",
    href: "https://github.com/motiondivision/motion",
    status: "动效引擎",
    summary: "让页面更有节奏感，用于进入、切换、强调和数据呈现。",
    fit: "动效 / 过渡 / 节奏感",
  },
  {
    name: "Lucide",
    href: "https://github.com/lucide-icons/lucide",
    status: "图标系统",
    summary: "统一图标语言，保证页面不乱、不廉价，适合高密度信息页面。",
    fit: "图标 / 状态 / 导航",
  },
  {
    name: "TanStack Table",
    href: "https://github.com/tanstack/table",
    status: "数据表格",
    summary: "如果页面有 SKU、报价、订单或权限列表，它会非常稳。",
    fit: "复杂列表 / 筛选 / 排序",
  },
  {
    name: "Recharts",
    href: "https://github.com/recharts/recharts",
    status: "经营图表",
    summary: "经营图表和趋势面板的轻量方案，适合做增长、利润和风险视图。",
    fit: "折线图 / 面积图 / 趋势",
  },
  {
    name: "Sonner",
    href: "https://github.com/emilkowalski/sonner",
    status: "轻反馈",
    summary: "轻量反馈和操作提示，保持页面节奏，不打断用户决策。",
    fit: "Toast / 成功反馈 / 轻提示",
  },
];

const panelTiles = [
  { label: "研究原则", value: "验证优先" },
  { label: "主流程", value: "3 件事" },
  { label: "实施节奏", value: "5 阶段" },
  { label: "验收方式", value: "3 秒看懂" },
];

const panelChecklist = [
  "3 个主工具",
  "5 个实施阶段",
  "1 个主 CTA",
  "桌面 / 移动双端",
];

const panelMotion = {
  hidden: { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0 },
};

export function FrontendToolkitPage() {
  const [activeTier, setActiveTier] = useState<TierId>("growth");
  const currentTier = sellerTiers.find((tier) => tier.id === activeTier) ?? sellerTiers[1];

  return (
    <MotionConfig reducedMotion="user">
      <main className={styles.page}>
      <div className={styles.gridOverlay} />
      <div className={styles.glowOne} />
      <div className={styles.glowTwo} />

      <header className={styles.header}>
        <div className={styles.brand}>
          <div className={styles.brandMark}>K</div>
          <div>
            <strong>AI Seller Research</strong>
            <span>内部设计研究预览 · not_for_sale</span>
          </div>
        </div>

        <div className={styles.headerActions}>
          <Link className={styles.ghostButton} href="/">
            回到主控制台
          </Link>
          <a className={styles.primaryButton} href="#decision">
            看内部选型
            <ArrowRight size={16} />
          </a>
        </div>
      </header>

      <section className={styles.hero}>
        <motion.div
          className={styles.heroCopy}
          initial="hidden"
          animate="visible"
          variants={{
            hidden: { opacity: 0, y: 18 },
            visible: { opacity: 1, y: 0, transition: { staggerChildren: 0.08 } },
          }}
        >
          <motion.span className={styles.eyebrow} variants={panelMotion}>
            内部设计研究 / internal_preview / not_for_sale
          </motion.span>
          <motion.h1 variants={panelMotion}>
            把 GitHub 设计工具收敛成一张内部设计研究页。
            <span>不是更花哨，而是更能被内部评审看懂。</span>
          </motion.h1>
          <motion.p variants={panelMotion}>
            这不是工具目录，而是一个内部设计研究预览页。主流程只保留 3 个 GitHub 工具，落地仍然使用现有前端底座，把灵感采样、审美过滤和组件实现拆开，页面才会稳、准、清楚。
          </motion.p>

          <motion.div className={styles.heroActions} variants={panelMotion}>
            <a className={styles.primaryButton} href="#tiers">
              查看内部预览
              <ArrowRight size={16} />
            </a>
            <a className={styles.secondaryButton} href="#implementation">
              查看内部计划
            </a>
          </motion.div>

          <motion.div className={styles.heroStats} variants={panelMotion}>
            {heroStats.map((item) => (
              <article className={styles.statCard} key={item.label}>
                <strong>{item.value}</strong>
                <span>{item.label}</span>
              </article>
            ))}
          </motion.div>

          <motion.div className={styles.heroTags} variants={panelMotion}>
            {heroTags.map((tag) => (
              <span className={styles.heroTag} key={tag}>
                <BadgeCheck size={14} />
                {tag}
              </span>
            ))}
          </motion.div>
        </motion.div>

        <motion.aside
          className={styles.heroPanel}
          initial={{ opacity: 0, x: 18 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.45, ease: "easeOut" }}
        >
          <div className={styles.panelIntro}>
            <span className={styles.panelLabel}>内部研究结论</span>
            <strong>先看懂，再校验，再决策，再迭代</strong>
            <p>
              页面不是先展示功能，而是先建立决策顺序。内部评审只要能在第一屏理解这页在验证什么，后面的判断就会顺很多。
            </p>
          </div>

          <div className={styles.panelTiles}>
            {panelTiles.map((item) => (
              <article className={styles.panelTile} key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </article>
            ))}
          </div>

          <div className={styles.panelChartCard}>
            <div className={styles.chartHeader}>
              <div>
                <span>结构示意曲线</span>
                <strong>结构示意，非实测数据</strong>
              </div>
              <ChartSpline size={18} />
            </div>
            <p className={styles.chartNote}>内部观察路径：从看见到行动的页面结构示意，不代表真实转化结果。</p>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={journeyCurve} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <defs>
                  <linearGradient id="purchaseFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.42} />
                    <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                <XAxis dataKey="stage" tick={{ fill: "#a7b4ba", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#a7b4ba", fontSize: 11 }} axisLine={false} tickLine={false} width={28} />
                <Tooltip
                  contentStyle={{
                    background: "rgba(12, 18, 22, 0.96)",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: 14,
                    color: "#fff",
                  }}
                  cursor={{ stroke: "rgba(245, 158, 11, 0.2)" }}
                />
                <Area type="monotone" dataKey="score" stroke="#f59e0b" fill="url(#purchaseFill)" strokeWidth={2.2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className={styles.panelChecklist}>
            {panelChecklist.map((item) => (
              <span className={styles.checkChip} key={item}>
                <BadgeCheck size={14} />
                {item}
              </span>
            ))}
          </div>
        </motion.aside>
      </section>

      <section className={styles.section} id="decision">
        <div className={styles.sectionHead}>
          <div>
            <span className={styles.eyebrow}>内部选型</span>
            <h2>三层工具链，不再堆插件</h2>
          </div>
          <p>主流程只保留 3 个 GitHub 工具。`designer-skills`、`ai-design-skills` 只做参考，不进入主流程。</p>
        </div>

        <div className={styles.decisionLayout}>
          <div className={styles.decisionGrid}>
            {decisionTools.map((tool) => {
              const Icon = tool.icon;
              return (
                <motion.article
                  className={styles.decisionCard}
                  key={tool.name}
                  whileHover={{ y: -2 }}
                  transition={{ duration: 0.18 }}
                >
                  <div className={styles.decisionHeader}>
                    <div className={styles.decisionIcon}>
                      <Icon size={16} />
                    </div>
                    <div className={styles.decisionHeaderText}>
                      <span>{tool.role}</span>
                      <strong>{tool.name}</strong>
                    </div>
                    {tool.recommended ? <span className={styles.decisionBadge}>主推</span> : null}
                  </div>

                  <p>{tool.summary}</p>

                  <div className={styles.decisionBlock}>
                    <span>输出</span>
                    <strong>{tool.output}</strong>
                  </div>

                  <div className={styles.decisionBlock}>
                    <span>为什么选它</span>
                    <p>{tool.reason}</p>
                  </div>

                  <div className={styles.toolFooter}>
                    <a className={styles.toolLink} href={tool.href} target="_blank" rel="noreferrer">
                      打开仓库
                      <ArrowRight size={14} />
                    </a>
                  </div>
                </motion.article>
              );
            })}
          </div>

          <aside className={styles.decisionSidebar}>
            <span className={styles.panelLabel}>内部研究结论</span>
            <strong>主流程是 3 个 GitHub 工具，落地层是现有前端栈。</strong>
            <p>
              这套组合的意义是把“灵感采样、审美过滤、结构生成”分开，避免一次性把所有技能包塞进流程里，最后看起来像工具大杂烩。
            </p>

            <div className={styles.decisionList}>
              <div className={styles.decisionListItem}>
                <b>1</b>
                <span>先定研究对象与预览分层。</span>
              </div>
              <div className={styles.decisionListItem}>
                <b>2</b>
                <span>再采样 3-5 个高质感页面。</span>
              </div>
              <div className={styles.decisionListItem}>
                <b>3</b>
                <span>最后回到现有组件底座落地。</span>
              </div>
            </div>

            <div className={styles.decisionChips}>
              <span className={styles.tierChip}>designer-skills 不进主流程</span>
              <span className={styles.tierChip}>ai-design-skills 仅参考</span>
              <span className={styles.tierChip}>先 brief 后设计</span>
            </div>

            <div className={styles.decisionNote}>
              保持克制，才会高级。
            </div>
          </aside>
        </div>
      </section>

      <section className={styles.section} id="tiers">
        <div className={styles.sectionHead}>
          <div>
            <span className={styles.eyebrow}>预览分层</span>
            <h2>三档预览，三种验证关注点</h2>
          </div>
          <p>每一档都要让内部评审迅速对号入座。看到的是“这页在验证什么”，不是“它能卖什么”。</p>
        </div>

        <div className={styles.tierGrid}>
          <div className={styles.tierList}>
            {sellerTiers.map((tier) => {
              const isActive = tier.id === activeTier;
              return (
                <motion.button
                  key={tier.id}
                  type="button"
                  className={isActive ? styles.tierButtonActive : styles.tierButton}
                  aria-pressed={isActive}
                  aria-label={`内部预览：${tier.title}`}
                  onClick={() => setActiveTier(tier.id)}
                  whileHover={{ y: -2 }}
                  transition={{ duration: 0.18 }}
                >
                  <div className={styles.tierTop}>
                    <div className={styles.tierRank}>{tier.rank}</div>
                    <div className={styles.tierMeta}>
                      <span>{tier.badge}</span>
                      <strong>{tier.title}</strong>
                      <span>{tier.audience}</span>
                    </div>
                    <ChevronRight size={18} />
                  </div>
                  <p>{tier.outcome}</p>
                  <div className={styles.tierChipRow}>
                    {tier.recommended ? <span className={styles.tierChip}>默认研究档</span> : null}
                    {tier.highlights.slice(0, 3).map((item) => (
                      <span className={styles.tierChip} key={item}>
                        {item}
                      </span>
                    ))}
                  </div>
                </motion.button>
              );
            })}
          </div>

          <AnimatePresence mode="wait">
            <motion.article
              key={currentTier.id}
              className={styles.detailCard}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.25 }}
            >
              <div className={styles.detailHeader}>
                <div>
                  <span className={styles.detailBadge}>{currentTier.badge}</span>
                  <h3>{currentTier.title}</h3>
                  <p>{currentTier.subtitle}</p>
                </div>
                <div className={styles.detailSignal}>
                  <strong>{currentTier.outcome}</strong>
                  <span>{currentTier.reason}</span>
                </div>
              </div>

              <div className={styles.detailMetrics}>
                {currentTier.metrics.map((item) => (
                  <article className={styles.detailMetric} key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </article>
                ))}
              </div>

              <div className={styles.detailColumns}>
                <div className={styles.detailColumn}>
                  <span>适合谁</span>
                  <p>{currentTier.audience}</p>
                </div>
                <div className={styles.detailColumn}>
                  <span>核心模块</span>
                  <ul>
                    {currentTier.highlights.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div className={styles.detailColumn}>
                  <span>验证理由</span>
                  <p>{currentTier.reason}</p>
                </div>
              </div>

              <div className={styles.detailFooter}>
                <a className={styles.primaryButton} href="#implementation">
                  {currentTier.cta}
                  <ArrowRight size={16} />
                </a>
                <a className={styles.secondaryButton} href="#journey">
                  看研究路径
                </a>
                <a className={styles.secondaryButton} href="#stack">
                  看落地底座
                </a>
              </div>
            </motion.article>
          </AnimatePresence>
        </div>
      </section>

      <section className={styles.section} id="journey">
        <div className={styles.sectionHead}>
          <div>
            <span className={styles.eyebrow}>内部研究路径</span>
            <h2>页面要顺着内部评审的心理路径推进，而不是只展示信息</h2>
          </div>
          <p>每一步都应该让评审获得更清楚的边界和更充分的证据，最后形成可复核的内部判断。</p>
        </div>

        <div className={styles.journeyGrid}>
          {journeySteps.map((step) => {
            const Icon = step.icon;
            return (
              <motion.article
                className={styles.journeyCard}
                key={step.title}
                whileHover={{ y: -2 }}
                transition={{ duration: 0.18 }}
              >
                <div className={styles.journeyTop}>
                  <div>
                    <span className={styles.panelLabel}>阶段 {step.index}</span>
                    <strong>{step.title}</strong>
                  </div>
                  <div className={styles.journeyBadge}>
                    <Icon size={16} />
                  </div>
                </div>
                <p>{step.description}</p>
              </motion.article>
            );
          })}
        </div>
      </section>

      <section className={styles.section} id="implementation">
        <div className={styles.sectionHead}>
          <div>
            <span className={styles.eyebrow}>内部实施计划</span>
            <h2>五阶段落地，先稳再快</h2>
          </div>
          <p>真正的实施顺序是先定 brief，再采样，再生成，再落地，最后做 QA 和验证。</p>
        </div>

        <div className={styles.phaseGrid}>
          {implementationPhases.map((phase) => (
            <motion.article
              className={styles.phaseCard}
              key={phase.step}
              whileHover={{ y: -2 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.phaseHeader}>
                <div className={styles.phaseNumber}>{phase.step}</div>
                <div className={styles.phaseMeta}>
                  <span>{phase.title}</span>
                  <strong>{phase.deliverable}</strong>
                </div>
              </div>
              <p>{phase.description}</p>
            </motion.article>
          ))}
        </div>

        <div className={styles.qaBand}>
          <div>
            <span className={styles.panelLabel}>验收标准</span>
            <strong>首屏 3 秒看懂，375 / 390 / 414 宽度无溢出，一主入口不分心。</strong>
          </div>
          <div className={styles.qaChecklist}>
            <span className={styles.checkChip}>首屏看懂</span>
            <span className={styles.checkChip}>移动端无溢出</span>
            <span className={styles.checkChip}>图表不抢主信息</span>
            <span className={styles.checkChip}>主入口统一</span>
          </div>
        </div>
      </section>

      <section className={styles.section} id="reasons">
        <div className={styles.sectionHead}>
          <div>
            <span className={styles.eyebrow}>研究结论</span>
            <h2>为什么这页值得继续评审</h2>
          </div>
        </div>

        <div className={styles.reasonGrid}>
          {reasonCards.map((item) => {
            const Icon = item.icon;
            return (
              <motion.article
                className={styles.reasonCard}
                key={item.title}
                whileHover={{ y: -2 }}
                transition={{ duration: 0.18 }}
              >
                <Icon size={18} className={styles.reasonIcon} />
                <strong>{item.title}</strong>
                <p>{item.description}</p>
              </motion.article>
            );
          })}
        </div>
      </section>

      <section className={styles.section} id="proof">
        <div className={styles.sectionHead}>
          <div>
            <span className={styles.eyebrow}>设计证明</span>
            <h2>让内部评审看到这是可验证的页面能力</h2>
          </div>
          <p>这里不讲未经证实的收益，只讲页面能证明什么、不能证明什么。</p>
        </div>

        <div className={styles.proofGrid}>
          {proofCards.map((item) => (
            <motion.article
              className={styles.proofCard}
              key={item.label}
              whileHover={{ y: -2 }}
              transition={{ duration: 0.18 }}
            >
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <p>{item.note}</p>
            </motion.article>
          ))}
        </div>

        <div className={styles.riskBand}>
          <div className={styles.riskIntro}>
            <span className={styles.panelLabel}>风险逆转</span>
            <strong>先看结构，再看细节，最后再决定是否继续推进。</strong>
            <p>如果这页没有让内部评审在第一眼建立信任，我们就继续压缩表达，而不是硬塞更多内容。</p>
          </div>

          <div className={styles.riskList}>
            {riskPoints.map((item) => (
              <article className={styles.riskItem} key={item.title}>
                <b />
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.description}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.section} id="stack">
        <div className={styles.sectionHead}>
          <div>
            <span className={styles.eyebrow}>实现底座</span>
            <h2>现有实现栈已经足够支撑这版页面</h2>
          </div>
          <p>这部分不是主流程工具，而是页面真正的实现层。第一阶段不换框架，只做收敛和增强。</p>
        </div>

        <div className={styles.toolGrid}>
          {runtimeStack.map((item) => (
            <motion.article
              className={styles.toolCard}
              key={item.name}
              whileHover={{ y: -2 }}
              transition={{ duration: 0.18 }}
            >
              <div className={styles.toolTop}>
                <div className={styles.toolTitle}>
                  <div>
                    <strong>{item.name}</strong>
                  </div>
                </div>
                <span className={styles.toolStatus}>{item.status}</span>
              </div>

              <p>{item.summary}</p>
              <div className={styles.toolFit}>
                <span>{item.fit}</span>
              </div>

              <div className={styles.toolFooter}>
                <a className={styles.toolLink} href={item.href} target="_blank" rel="noreferrer">
                  打开仓库
                  <ArrowRight size={14} />
                </a>
              </div>
            </motion.article>
          ))}
        </div>

        <div className={styles.toolNote}>
          当前依赖清单已包含 <strong>Next.js</strong>、<strong>Radix</strong>、<strong>Motion</strong>、<strong>Lucide</strong>、<strong>TanStack Table</strong>、<strong>Recharts</strong> 和 <strong>Sonner</strong>，足够支撑这版内部预览页。
          如果后面要再提高一个层级，再考虑 <strong>Magic UI</strong> 之类的氛围增强，但不进入第一阶段主流程。
        </div>
      </section>

      <section className={styles.ctaBand}>
        <div className={styles.ctaCopy}>
          <span className={styles.eyebrow}>内部结论</span>
          <h2>这版页面的目标不是炫技，而是让内部评审愿意继续看、愿意验证、愿意进入下一版。</h2>
          <p>下一轮仅在内部评审批准后，再决定是否把这套研究语言扩展到首页、详情页和控制台。</p>
        </div>
        <div className={styles.ctaActions}>
          <a className={styles.primaryButton} href="#decision">
            继续内部预览
            <ArrowRight size={16} />
          </a>
          <a className={styles.secondaryButton} href="#stack">
            继续看底座
          </a>
        </div>
      </section>
      </main>
    </MotionConfig>
  );
}
