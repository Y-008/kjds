# 供应链证明与 AI-BOM 前沿复核 Evidence

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-EVD-FRONTIER-SUPPLY-CHAIN-20260906 |
| date | 2026-09-06 |
| status | Engineering governance evidence; not a Gate approval |
| owner | platform_security |
| exact_scope | `slsa_cyclonedx_supply_chain_evidence` 的 SLSA v1.2 provenance 验证与 CycloneDX AI/ML-BOM 官方材料复核 |
| frontier_review | checked_no_change |
| source_access_date | 2026-09-06 |
| external_write | false |
| runtime_dependency_changed | false |
| registry_decision_changed | false; review metadata advanced after a completed source review |
| next_review | 2026-10-06 |

## 1. 复核结论

本次复核确认 `slsa_cyclonedx_supply_chain_evidence` 继续保持 `adopt_now`。该决定只允许
进入有界的工程实现切片，不表示生产依赖、部署放行、业务事实晋级或外部写授权已经获得。
本次更新 `frontier_technology_adoption.json` 的 `reviewed_on`、`review_due_on` 和注册表
`as_of`，因为复核已由当前官方材料和本 Evidence 真实支撑；没有通过单独改日期模拟新鲜度。

## 2. 官方来源与观察

- [SLSA v1.2 specification](https://slsa.dev/spec/v1.2/) 页面标示该规范为 `Approved`，当前页面
  明确为 Version 1.2，并将 provenance、Build Track 和验证流程作为规范组成部分。
- [SLSA Build: Verifying artifacts](https://slsa.dev/spec/v1.2/verifying-artifacts) 要求验证器
  检查受信任 builder identity、provenance 签名、artifact subject digest、`predicateType`，
  以及预期的 `buildType` 和 `externalParameters`；这支持 KJDS 的 subject、签名和参数漂移
  失败关闭约束。
- [CycloneDX Authoritative Guide to AI/ML-BOM](https://cyclonedx.org/guides/OWASP_CycloneDX-Authoritative-Guide-to-AI-ML-BOM-en.pdf)
  标示为 First Edition (Revision 1)，更新时间为 2026-06-10，并覆盖模型、数据集、模型卡、
  量化分析、tokenizer、prompt template 等 AI/ML 供应链描述。该指南仍是透明度与清单指导，
  不能单独证明 KJDS 的业务正确性或生产安全性。

## 3. KJDS 边界与未决项

- G1 的 SLSA/CycloneDX 产物验证继续绑定精确 commit、migration head、镜像 digest、依赖和
  受限 AI-BOM；BOM 不得包含 secret、客户数据、私有 prompt 或不必要的部署拓扑。
- 当前 signer 仍是本地临时 signer，未配置独立托管签名者；因此
  `production_dependency_allowed=false`、`external_write_allowed=false`、
  `formal_fact_promotion_allowed=false` 保持不变。
- 本次没有连接外部 resolver，也没有保存内容哈希、签名回执或独立 reviewer attestation；
  官方链接是可追溯来源定位，不是外部认证证据。
- `SUPPLY-CHAIN-EVIDENCE-EXIT` 的 fresh-build、schema/no-secret、PostgreSQL patch/digest
  和部署策略分离条件仍需按每个候选发布物重新验证，不能由本次材料复核代替。

## 4. 关联机器真源与合同

- `docs/project/registries/frontier_technology_adoption.json`
- `docs/project/contracts/release-provenance-policy-v1.json`
- `docs/adr/ADR-0016-risk-tiered-decision-and-loop-control.md`
- `docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md`（BAS-175）

