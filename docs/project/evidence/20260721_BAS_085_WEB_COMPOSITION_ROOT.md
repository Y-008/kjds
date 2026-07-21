# BAS-085 Web 组合根收敛证据

日期：2026-07-21
分支：`refactor/web-composition-root`

## 结果

- `web/app/page.tsx` 从 3,398 行收敛为 5 行，只委托给 `KjdsDashboard`。
- `KjdsDashboard` 只组合 `useDashboardController` 与 `DashboardView`；`DashboardView` 只组合布局和领域面板。
- 页面按财务、运营、决策科学、研究门禁、商品内容、采购供应和经营摘要拆分；稳定合同集中在 `contracts.ts`。
- 所有 Dashboard 业务请求统一经过原生 `fetchJson`，包含超时、取消和一致错误响应；初始加载通过 `Promise.allSettled` 保证单个领域失败不清空其他经营区域。
- 工具状态由后端实际返回的已配置 Provider 生成，不再假设固定四个可选工具。
- 未增加 Redux、Axios、React Query 或其他运行依赖；公共 `/` 路径和后端 API 合同不变。

## 机器验证

- Web 合同测试：21 项通过。
- Next.js 生产构建通过，首页和既有认证、后端代理路由均成功生成。
- 新增组合根检查，验证 `page.tsx` 不含后端调用，并验证可选请求失败不会拒绝同批其他请求。
- `git diff --check` 通过。

## 明确保留

`useDashboardController` 仍集中保存跨领域页面状态与动作协调。这是当前单页控制台的最小稳定边界；在出现可独立复用或独立发布的第二个页面前，不再为缩短文件而新增状态框架或抽象层。
