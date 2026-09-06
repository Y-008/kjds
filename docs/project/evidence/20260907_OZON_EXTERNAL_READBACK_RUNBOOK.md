# Ozon 外部事实回读与生产验收运行手册

本手册描述一条真实、只读、可审计的 Ozon 商品事实接入路径。它使用
受管渠道凭据、SQL Pilot Run 和原始 response Evidence；不会通过环境变量
直接授权生产写入。

## 执行前检查

在 `D:/KJDS/kjds` 执行：

```powershell
uv run python scripts/capture_ozon_readback.py --preflight
```

预检必须报告 `network_calls_performed=false`、
`explicit_execution_required=true` 和官方 Seller API origin。预检不读取或
输出凭据值。

真实 Pilot Worker 必须使用 `KJDS_CHANNEL_CREDENTIAL_MODE=managed`，并由
服务端签发与租户、主体、店铺、Pilot、操作和 `catalog.read` 能力绑定的
一次性 grant。`unbound` 模式只能预检，不能执行。

## 单目标只读执行

启动已配置数据库和运行时身份的控制平面后，执行一个目标：

```powershell
uv run python apps/control_plane/ozon_read_worker.py --execute `
  --operation ozon.product.read `
  --pilot-id <pilot-id> `
  --offer-id <offer-id> `
  --idempotency-key <new-idempotency-key>
```

Worker 的顺序是：创建 Pilot Run → 兑换受管 grant → 调用官方商品读接口 →
上传不可变 response checkpoint → 完成 Pilot Run。失败、超时、授权拒绝或
未知结果都不能生成成功事实。

执行结果必须包含一个已完成且成功的 `run_id`、唯一原始 response Evidence、
响应哈希和 `ozon-product-read-v1` 合同。任何响应或摘要修订都生成新版本，
不得覆盖旧 Evidence。

## 生产验收

使用同一租户和店铺作用域查询：

```text
GET /v1/ozon/production-acceptance/{run_id}?store_ref=<store-ref>
```

只有同时满足以下条件才会得到 `gate_status=PASS`：

- Pilot Run 成功且完成状态不可变。
- 原始响应 Evidence 唯一、完整、哈希和字节数一致。
- 两个官方商品响应通过合同解析并绑定同一 `offer_id` 哈希。
- Evidence 和观察时间在新鲜度窗口内。
- 服务端渠道身份、租约、店铺作用域和 `catalog.read` 能力全部通过。

验收投影始终返回 `external_write_allowed=false`、
`formal_fact_promotion_allowed=false` 和 `production_release_allowed=false`；
验收通过只表示外部观察可供后续受控重放，不会自动授予写权限。

## 阻断和恢复

- 传输失败进入 `OZON_READ_TRANSPORT_FAILED`。
- Ozon HTTP 401/403 进入 `OZON_READ_AUTHORIZATION_FAILED`。
- 没有原始工件进入 `OZON_READBACK_ARTIFACT_MISSING`。
- 任何阻断都保持 `BLOCKED_EVIDENCE`，不能降级为 `NO_DATA`。

修复网络、权限或受管租约后，使用新的幂等键和新的输出目录重放单目标读回；
禁止重复提交同一个已失败的外部请求，也禁止手工伪造 bundle、summary 或
验收结果。

本手册不包含 Client-Id、Api-Key、Offer ID、API key 或任何其他秘密材料。
