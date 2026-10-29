# 广告写回批次

面板保存运营意见后，该意见就是本批次的业务执行授权。智能体不再要求用户重复确认 hash；hash 只用于审计和幂等。

## 1. 面板确认

静态 HTML 是只读快照。要真实保存意见，必须用审核服务打开：

```powershell
python scripts/serve_pmc.py `
  --board storage/pmc_sources/2026-10-22/board-pmc.json `
  --state storage/state/ops_state.sqlite3 `
  --port 8769
```

打开输出的 `http://127.0.0.1:.../`。首次加载会自动读取审核状态并刷新按钮。

如果换了新批次，先补齐广告组合归属：

```powershell
python scripts/attach_ad_group_options.py --board storage/pmc_sources/2026-10-22/board-pmc.json
```

- 否词：接受后保存为待写回项。
- 精准：先在“承接广告组”选择原广告组或同店铺其他活动广告组，再确认出价。
- 调价：按 target ID 确认基础竞价。
- 状态显示“已确认 · 待写回”，不是已写回。

## 2. 一条命令完成预览与执行

所有命令固定在这个目录执行，避免不同智能体用错工作目录：

```powershell
Set-Location "D:\Deepseek Harness\ZJL WORK\amazon-ops-b-runtime"
```

预览：

```powershell
python scripts/run_ad_writeback.py `
  --board storage/pmc_sources/2026-10-22/board-pmc.json `
  --state storage/state/ops_state.sqlite3 `
  --preview
```

面板保存后直接执行：

```powershell
python scripts/run_ad_writeback.py `
  --board storage/pmc_sources/2026-10-22/board-pmc.json `
  --state storage/state/ops_state.sqlite3 `
  --execute-saved
```

`--execute-saved` 会重新读取当前意见、重建批次、执行所有可执行项，不需要第二次 hash 确认。
高风险或手工场景仍可用 `--execute --confirm "<batch_id>:<content_sha256>"`。

单条 blocked / failed / unknown 不会阻止其他可执行项。最终同时生成回执和用户报告。

## 3. 生成冻结批次

```powershell
python scripts/prepare_ad_write_batch.py `
  --board storage/pmc_sources/2026-10-22/board-pmc.json `
  --state storage/state/ops_state.sqlite3 `
  --out storage/pmc_sources/2026-10-22/ad-write-batch.json
```

输出 `batch_id`、`content_sha256`、各类数量和 blocked 项。检查目标广告组、出价、否词和 blocked；不需要再把这些发回用户二次确认。

## 3. 预检

```powershell
python scripts/execute_ad_write_batch.py `
  storage/pmc_sources/2026-10-22/ad-write-batch.json `
  --board storage/pmc_sources/2026-10-22/board-pmc.json `
  --preflight-only
```

预检不写远端。记录输出里的批次指纹：

```text
batch_id:content_sha256
```

## 4. 执行（面板已授权）

默认使用 `--execute-saved`。只有高风险或人工抽查时才传 hash：

```powershell
python scripts/execute_ad_write_batch.py `
  storage/pmc_sources/2026-10-22/ad-write-batch.json `
  --board storage/pmc_sources/2026-10-22/board-pmc.json `
  --execute `
  --confirm "batch_id:content_sha256"
```

执行结果写入同目录 `*-receipt.json`。传输错误记为 unknown，不自动重试。

生成用户可读报告：

```powershell
python scripts/writeback_report.py `
  --board storage/pmc_sources/2026-10-22/board-pmc.json `
  --batch storage/pmc_sources/2026-10-22/ad-write-batch.json `
  --receipt storage/pmc_sources/2026-10-22/ad-write-batch-receipt.json `
  --out storage/pmc_sources/2026-10-22/ad-writeback-report.md
```

报告逐条包含产品、广告组合、活动、广告组、对象、调价原价/新价或精准/否定方式、结果。技术 ID 只放在折叠详情。

## 写工具映射

| 类型 | 领星工具 |
| --- | --- |
| SP 搜索词精准/词组否定 | `advertising_add_negative_keywords` |
| SP 否定 ASIN | `advertising_add_negative_targets` |
| SP 精准关键词新增 | `advertising_sp_add_keywords` |
| SP 商品精准投放 | `post_targets_sp` |
| SP 目标竞价修改 | `put_targets_sp` |

## 归属与显示约束

- 广告活动名、广告组名必须来自领星 `name` / `ad_group_name`，不得把 `ad_group_id` 当广告组名展示。
- 名称缺失或仍是纯数字时，批次直接 blocked。
- 精准承接组必须显示同广告组合；跨组合必须重新确认。
- 技术 ID、traceId 只放技术详情，不作为用户确认主文案。

## 边界

- 否词只写广告组层级；必须有 campaignId + adGroupId。
- 精准只能写已启用的 SP 活动广告组；默认原组，可选择同 profile 的其他已启用组。
- 调价按 targetId 写 `targets[].bid`。
- 不写 SB、预算、活动状态。
- 批次内容变化会生成新摘要，旧回执不复用；过期只作为提示，不阻止执行。
- 批次文件包含真实广告 ID；不要提交到公开仓库。
