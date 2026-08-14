# W1 红队发现：taxonomy 必填属性校验缺口（P2，已实证）

| 字段 | 值 |
|---|---|
| doc_id | KJDS-REDTEAM-20260814-001 |
| 状态 | CONFIRMED（独立脚本复现，未改并发方代码） |
| 定位 | `apps/control_plane/ai_listing.py::_validate_taxonomy` |
| 严重度 | P2（fail-open，需模型「漏填 + 不报」双重失败才触发，但后果是缺必填属性的 listing 通过本地校验） |

## 一、问题

`_validate_taxonomy` 对「必填属性已填」的强制**只依赖模型自报的 `missing_required_attributes` 字段**，未独立验证 `attribute_mapping` 是否包含全部 `is_required=true` 属性定义。

现有校验仅做：
1. `mapping` 键 ⊆ `definitions`（防发明 ID）；
2. enum 值合法；
3. `missing_required_attributes` 非空串 → 抛错。

**缺失**：`definitions 中 is_required=true 的 id` ⊆ `mapping 的 key` 这一独立门。

## 二、复现证据（独立脚本，bypass __init__ 直接调 _validate_taxonomy）

| 用例 | 输入 | 结果 |
|---|---|---|
| 负例 | `attribute_mapping={}` + `missing_required_attributes=[]`（漏填两个必填 85/9048 且不报） | **PASS-through（缺口）** |
| 对照1 | `attribute_mapping={}` + `missing=["85","9048"]`（漏填但正确上报） | FAIL-CLOSED（正确） |
| 对照2 | `attribute_mapping={85,9048 全填}` + `missing=[]` | PASS-through（正确） |

结论：模型「漏填必填属性 + 误报空 missing」时，本地校验放行，缺必填属性的 listing 会进入下游（可能在 Ozon 侧被拒或产生不完整 listing）。

与结构化输出不冲突：`output_schema` 允许 `attribute_mapping:{}` 与 `missing_required_attributes:[]`，schema 校验同样放行空 mapping。

## 三、建议修复（供并发方 Owner，不代改）

在 `_validate_taxonomy` 建好 `definitions`/`mapping` 后、`missing` 判断前增加独立门：

```python
required_ids = {
    str(k) for k, v in definitions.items()
    if isinstance(v, dict) and v.get("is_required") is True
}
absent = required_ids - {str(k) for k in mapping}
if absent:
    raise AiListingPipelineError(
        "required_ozon_attributes_missing",
        f"Required official Ozon attributes absent from mapping: {sorted(absent)}",
    )
```

该门独立于模型自报的 `missing_required_attributes`，可确保 fail-closed。

## 四、边界

- 本发现只读复现，未修改并发方任何文件；由并发方 Owner 决定是否采纳并补负测。
- 不影响既有 T1 调价、财务对账、24a 决策包结论；仅属 taxonomy 阶段的健壮性缺口。

## 五、提交后状态更新（2026-08-14 22:48）

- 并发方已提交 `eb3a2ae`（5 文件，含新增 `tests/test_ai_listing_taxonomy.py`，4 passed）。
- 但本缺口**仍未修复**：对已提交代码复现「空 mapping + 空 missing」仍 PASS-through。
- 新测试仅覆盖「blank missing 容忍」与「已填但误报 missing」，未覆盖「漏填且不报」的 fail-open 场景。
- 建议后续补一条负测：`attribute_mapping={}` + `missing=[]` 必须抛 `required_ozon_attributes_missing`，并加第三节的独立 `required_ids ⊆ mapping` 门。



## 六、修复落地（2026-08-14）

- `apps/control_plane/ai_listing.py` 已增加独立 `required_ids ⊆ mapping` fail-closed 门；空 mapping 且空 missing 会抛 `required_ozon_attributes_missing`。
- `tests/test_ai_listing_taxonomy.py` 已增加 `test_validate_taxonomy_rejects_omitted_required_mapping` 负测。
- 聚焦测试：`test_ai_listing_taxonomy.py` 5 passed；`test_agent_inference.py` + taxonomy 合计 15 passed；`test_ozon_worker.py` 88 passed；Ruff 通过。
- 本缺口闭合。
