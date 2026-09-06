# 2026-09-07 Ozon 外部事实回读阻断记录

本记录对应一次严格限定为单商品、官方 Seller API、只读的真实回读尝试。

## 结果

- 预检：通过。确认官方来源、只读端点和凭据变量名称存在；预检没有读取凭据值，也没有发起网络请求。
- 执行：`READBACK_FAILED`。
- 首次错误：`Ozon read transport failure`（代理链路提前关闭 TLS）。
- 直连复核：官方域名 DNS 与 TCP/443 可达；绕过代理后返回 HTTP `403`，因此当前账号/权限未获得可接受的商品读回。
- 错误分类：capture_ozon_readback.py 保留官方错误代码 OZON_HTTP_403；生产验收投影增加稳定阻断码 OZON_READ_AUTHORIZATION_FAILED。
- 原始响应工件：未生成。
- 外部写入：未执行。
- 重试：仅在明确修正代理路径后进行一次直连复核；收到 `403` 后停止，避免重复请求。

## 验收含义

本次尝试不能证明 Ozon 商品事实、库存事实、财务事实或生产发布就绪。生产验收接口必须返回 `BLOCKED_EVIDENCE`，并保留 `OZON_READBACK_ARTIFACT_MISSING`/传输或授权失败原因，不能降级为 `NO_DATA` 或 `PASS`。

## 恢复条件

恢复后应重新执行同一单目标读回，生成不可覆盖的 response bundle 和 summary，再通过：

1. 官方响应合同与目标绑定校验。
2. 原始 Evidence 完整性和唯一血缘校验。
3. 新鲜度、作用域、托管渠道身份和独立验证器校验。
4. `/v1/ozon/production-acceptance/{run_id}` 返回 `PASS`。

本记录不包含 Client-Id、Api-Key、Offer ID 或任何其他秘密材料。
