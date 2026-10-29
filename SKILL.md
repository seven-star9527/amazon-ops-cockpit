---
name: amazon-ops-cockpit
description: Use when an Amazon operator needs the complete Amazon operations cockpit (advertising, inventory, Listing), the live review panel, SIF keyword tracking, or the unified ad writeback entrypoint.
metadata:
  tabtin:
    displayName: "亚马逊运营工作台"
  short-description: "广告/库存/Listing 一体看板与写回"
---

# 亚马逊运营工作台

这是完整看板 skill，不是否词单页。

## 主入口

```powershell
python scripts/bootstrap.py --data-dir <外置数据目录>
<外置数据目录>/venvs/readonly-v1/Scripts/python.exe scripts/run_cockpit.py --check --data-dir <外置数据目录>
<外置数据目录>/venvs/readonly-v1/Scripts/python.exe scripts/run_cockpit.py --serve --data-dir <外置数据目录>
```

`--serve` 仅提供只读完整面板，不提供业务保存或写回 API。Windows 示例见 references/readonly-foundation.md；macOS/Linux 的 venv Python 位于 bin/python。既有写回脚本属于独立显式操作，本只读入口不会调用。

禁止用旧的：

```text
dashboard_server.py
run_analysis.py
```

来代表完整看板。旧否词诊断是另一个 legacy skill。

## 完整看板包含

- 广告：否词、精准、调价、观察池、竞品机会、关键词排名；
- 库存：可售、覆盖、断货/冗余、发货建议；
- Listing：标题/五点/评论/流量结构；
- 可写审核面板：面板保存即授权，由 runtime 统一写回。

## 数据前置

代码包不含业务数据。完整看板需要：

1. Lingxing MCP 凭证；
2. SIF MCP 凭证；
3. PMC 同日源文件；
4. ETA/发货工作簿；
5. 第一次生成 `board-pmc.json`。

没有完整看板数据时，`run_cockpit.py` 会明确报缺，不会启动否词单页冒充完整看板。

## 写回

统一入口在 runtime：

```text
scripts/run_ad_writeback.py
```

规则见：

```text
references/ad-writeback-contract.md
```

面板保存即业务授权；不要求第二次 `batch_id:hash` 确认。只有 schema、batch identity、digest 等批次级错误才整体停止；单个失败/未知/阻断不阻止其余项。

## UI 约束

- 产品页三个板块：广告 / 库存 / Listing；
- 三格等宽、居中；
- 顶部广告摘要只能有一份，不再重复底部筛选；
- 关键词面板保留最新自然/SP 和隐藏趋势图；
- 不新增重复计数、不伪造 SIF 未返回的排名。

## 参考

```text
references/cockpit-summary.md
references/full-cockpit.md
references/ad-writeback-contract.md
```
