# ADR-0017：外部合同使用固定样本回放

- 状态：Accepted
- 日期：2026-07-21
- Owner：平台集成负责人
- Approver：控制面负责人

## 背景

Ozon、ComfyUI 和 Ozon 财务文件都可能在不通知 KJDS 的情况下改变字段、状态或错误响应。现有专项测试已覆盖限流、写入结果不确定、幂等和回读，但成功/漂移载荷主要内联在测试中，缺少可审计的合同样本及完整性校验。

## 决策

在 `tests/fixtures/external_contracts/` 保存版本化、脱敏、无凭证的最小固定样本。清单记录系统、合同版本、文件、预期结果和 SHA-256；测试先验证清单完整性，再把样本交给现有生产适配器解析。

不新增运行时回放服务、流量录制代理、Schema Registry 或第三方依赖。传输故障继续使用现有 `httpx.MockTransport` 专项测试，因为异常和重试时序不适合伪装成业务载荷。

## 取舍

- 优点：样本可审计、可复现，外部结构变化会在 CI 中失败。
- 代价：合成样本不能证明真实平台当前合同；获得真实响应后仍需脱敏、独立复核并替换样本。
- 禁止：生产密钥、个人信息、商户原始数据和未脱敏响应进入仓库。

## 回滚

删除固定样本与对应测试即可回到原有内联测试；不涉及数据库、API 或生产运行时。

## 验收

- 清单文件路径受限于样本目录，ID 唯一，所有 SHA-256 一致。
- Ozon、ComfyUI 和财务导入各有成功与结构漂移样本。
- 漂移样本由现有生产解析逻辑失败关闭。
- 现有限流、超时、写入不确定、幂等和回读测试继续通过。

## 复审触发

真实合同版本变化、出现无法用固定样本表达的协议故障，或回放总耗时成为 CI 的可测瓶颈时复审。

## 规范依据

- OpenAPI 3.2.0：<https://spec.openapis.org/oas/v3.2.0.html>
- JSON Schema 2020-12：<https://json-schema.org/draft/2020-12>
- ComfyUI Workflow JSON：<https://docs.comfy.org/specs/workflow_json>
- ComfyUI Server Routes：<https://docs.comfy.org/development/comfyui-server/comms_routes>
