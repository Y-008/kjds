---
workflow: motion-graphics
flow: automation
storyboard: no
mode: autonomous
message: "覆盖 LinkFox 每个入口，把 AI 创作接入俄罗斯真实经营闭环并可扩全球"
destination: "KJDS 产品发布、企业评审与桌面演示"
aspect: "1920x1080"
language: "zh-CN"
audience: "跨境业务负责人、产品与技术决策者"
length: "8.5s"
angle: "一棵由 KJDS 中枢生长出的点—线—面运行图谱：原子点连接为端到端价值流，再汇成跨域经营控制面"
narration: "no"
export: "mp4"
---

## Intent

一支 8.5 秒、单屏、无旁白的企业级运行图谱动效。观众先看到 KJDS 中枢，随后三条主枝依次生长：`LinkFox 同功能覆盖`、`Russia / Ozon 真实运营`、`全球治理适配`。三条主枝继续展开为 10 个真实能力域，并以每个域下的微型节点准确累计到 143 个原子功能点；末帧同时锁定 `14 条端到端价值流` 与 `8 个经营控制面`。最终文案明确 KJDS 的差异：不是功能菜单，而是让原子点连接为价值流，让价值流汇成有真源、有指标、有预警和有权限边界的经营控制面。

## Assets

- `../../docs/project/registries/cross_border_capability_atlas.json` — 唯一数据真源；10 个域、49 个宏观能力、143 个原子点、14 条价值流、8 个经营面及其真实状态、市场与平台边界。
- `compositions/decision_tree.html` — 已 scaffold 的决策树结构参考；仅复用其 SVG 路径绘制与节点层级思路，不沿用示例文案、白底便签风格或 12 秒节奏。
- HyperFrames `flowchart` catalog block — Builder 的首选复用块。

不需要搜索、截图、图标、Logo 或其他外部媒体。

## Customizations

- 画布：1920×1080、30fps、8.5 秒、单一连续镜头。
- 色板：深常青 `#07120F`、暖白 `#ECF5EF`、KJDS lime `#B8EF65`、amber `#FFB760`、cobalt `#6E8CFF`。
- 三条主枝必须准确表达：
  - `LinkFox 同功能覆盖`：域 01–05，共 65 个原子点。
  - `Russia / Ozon 真实运营`：域 06、08、09，共 44 个原子点。
  - `全球治理适配`：域 07、10，共 34 个原子点。
- 10 个域节点全部可读；每个域携带真实原子点数徽标，合计 143。143 个点用有层级连接的微型节点表达，不用装饰性散点冒充；14 条线与 8 个面在末帧作为服务端合同计数锁定。
- 主要动效规则：`svg-path-draw`、`spring-pop-entrance`、`counting-dynamic-scale`、`ambient-glow-bloom`。
- 保持企业级、精确、克制：平滑长尾落位，不使用弹跳、随机运动、无限循环、景深推镜或星座式环绕来破坏真实树结构。

## Notes

- 真实结构优先于“炫技”：树的父子关系、域编号、域计数和总计数在任何证明帧都不能被动效遮蔽或改写。
- LinkFox 只作为公开竞品功能覆盖参考；不暗示 LinkFox 已验证接入 Ozon，也不把其营销宣称提升为 KJDS 事实。
- `Russia / Ozon` 主枝使用 amber 作为聚焦色；`全球治理适配`使用 cobalt；LinkFox 覆盖使用 KJDS lime。
- 末帧至少保持 0.9 秒，显示完整图谱、`143 原子点`、`14 条价值流`、`8 个经营面`与核心信息。
- 本阶段只产出导演计划；不修改 composition，不启动预览，不渲染。
