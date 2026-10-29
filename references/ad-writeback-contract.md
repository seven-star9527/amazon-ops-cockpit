# 广告写回展示与执行契约

本契约适用于否词、精准投放、调价。代码可执行不代表可以跳过本契约。

## 1. 必须展示的目标归属

每条动作在确认页和结果页都必须包含：

```text
产品名称 + ASIN
广告组合名称
广告活动名称
广告组名称
动作
对象
```

名称必须来自领星：

- 活动：`campaign_name`
- 广告组：`ad_group_name`，缺失时用 `name`
- 组合：`portfolio_name`

禁止把 `campaign_id`、`ad_group_id`、`target_id`、`action_key` 当作名称展示。
名称缺失或仍是纯数字时，批次必须 blocked。

## 2. 调价必须展示原价和新价

```text
对象：toddler knife（EXACT）
原价：£0.40
新价：£0.41
变化：+£0.01
```

缺 `before_bid` 或 `after_bid` 任一项，禁止写回。
当前价复核为可选提示，不是执行前置条件；发现变化时该条标记并跳过，其他项继续。不要把整批作废。

## 3. 精准必须展示新增目标和承接组

```text
动作：新增精准关键词 / 新增商品精准
对象：kids knives for chopping
匹配方式：EXACT / PRODUCT_EXACT
广告组合：...
承接活动：...
承接广告组：...
出价：£0.50
```

承接组默认同广告组合。跨广告组合必须重新选择并二次确认。

## 4. 否词必须展示范围与影响

```text
动作：新增否定关键词 / 新增否定 ASIN
对象：...
匹配方式：negativeExact / negativePhrase / PRODUCT_EXACT
广告组合：...
广告活动：...
广告组：...
影响 ASIN：...
```

共享广告组必须列出全部受影响 ASIN。

## 5. 确认页

确认页主视图必须是业务表：

| 产品 | 动作 | 广告组合 | 活动 | 广告组 | 对象 | 原价 | 新价 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

技术信息只放折叠详情：

```text
batch_id:content_sha256
campaignId / adGroupId / targetId
```

面板保存意见就是本批次业务授权。业务表用于审计和结果展示；`batch_id:content_sha256` 只用于幂等和回执，不再要求用户二次确认。

## 6. 执行与回执

流程固定：

```text
保存意见（授权）
→ 生成冻结批次
→ 预检
→ 逐条执行可执行项
→ 用户报告
```

执行后必须生成：

```text
ad-write-batch-receipt.json   技术回执
ad-writeback-report.md        用户报告
```

用户报告必须逐条包含目标归属、变更前后、状态。

## 7. 工具映射

| 动作 | 领星工具 |
| --- | --- |
| SP 搜索词否定 | `advertising_add_negative_keywords` |
| SP 否定 ASIN | `advertising_add_negative_targets` |
| SP 关键词精准新增 | `advertising_sp_add_keywords` |
| SP 商品精准投放 | `post_targets_sp` |
| SP 目标调价 | `put_targets_sp` |

## 8. 统一入口（A 方案）

否词、精准、调价统一使用运营工作台写回入口。所有命令固定在工作台根目录执行：

```powershell
$runtime = $env:AMAZON_OPS_RUNTIME
if (-not $runtime) { throw "请先设置 AMAZON_OPS_RUNTIME 指向 amazon-ops-b-runtime" }
Set-Location $runtime

python scripts/run_ad_writeback.py `
  --board storage/pmc_sources/<date>/board-pmc.json `
  --state storage/state/ops_state.sqlite3 `
  --preview
```

面板保存后直接执行，不再二次确认：

```powershell
python scripts/run_ad_writeback.py `
  --board storage/pmc_sources/<date>/board-pmc.json `
  --state storage/state/ops_state.sqlite3 `
  --execute-saved
```

高风险或人工抽查仍可使用 `--execute --confirm "<batch_id>:<content_sha256>"`。

Skill 不再自建第二套精准/调价批次，也不维护第二套决策源。
Skill 负责诊断和展示；工作台负责确认、写回、回执、用户报告。

## 9. 逐条尽力执行

批次不能因为一条 blocked、失败或未知而停止其他动作。

```text
可执行项继续执行
已存在项视为满足
blocked 项单独列出
unknown 项不自动重试
最终报告全部状态
```

一条对象缺失、价格缺失或名称未解析只阻止该条，不阻止整批。
只有整个批次摘要被篡改、schema 无效或无法确定批次身份时，才阻止整批。

## 10. 禁止项

- 不允许无名称写回。
- 不允许调价没有原价。
- 不允许精准没有承接组。
- 不允许跨组合静默写回。
- 不允许重复写回已执行动作。
- 不允许只展示原始 JSON 作为结果。
- 面板保存意见即授权；不得再要求普通批次二次 hash 确认。
- 传输结果未知不得自动重试。
