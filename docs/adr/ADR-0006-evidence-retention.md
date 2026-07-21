# ADR-0006：证据保留评估，不自动删除

- 状态：Accepted
- 日期：2026-07-17

## 决策

证据元数据可以声明 `retention_class`：`operational`、`financial`、`compliance`、`experiment`、`security`，以及可选布尔值 `legal_hold`。系统拒绝未知分类和非布尔 legal hold。

各分类只定义内部“复审最短间隔”，不是法定保存期限：运营 365 天、实验 1095 天、安全 2555 天、财务和合规 3650 天。`GET /v1/evidence/{id}/retention` 返回分类、复审时间、legal hold、状态与归档资格。

系统永远返回 `automatic_delete_allowed=false`。到期只表示可以进入人工归档复审，不允许自动删除 blob、记录或血缘。未分类证据返回 `classification_required`，legal hold 返回 `legal_hold` 且不可归档。

## 原因

现阶段证据跨经营、财务、合规和事故场景，法域与合同尚未冻结。自动删除会破坏事实链；无限无分类保留又会制造成本与隐私风险。先做可执行分类和人工复审门，是最小且可逆的安全基线。

## 后续条件

真实客户、银行或监管数据进入前，必须由合规/财务负责人确认国家、平台和合同要求，再把内部复审间隔升级为正式保留矩阵、加密归档和可证明销毁流程。
