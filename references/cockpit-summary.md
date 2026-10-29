# 完整运营看板 Skill 摘要

## 一个入口

```powershell
python scripts/run_cockpit.py --check
python scripts/run_cockpit.py --serve
```

## 三个板块

### 广告

- 产品级广告决策；
- 否词复核、精准方案、调价可审；
- 观察池、外部核验、已处理、待补证据；
- SIF 关键词排名与 14 天趋势；
- 竞品机会池；
- 面板保存后统一写回。

### 库存

- FBA 可售、库存覆盖、断货风险；
- 冗余/采购/发货建议；
- 库存时间线与补货测算；
- 缺样本时明确标记，不伪造补货建议。

### Listing

- 标题、五点、图片/评论证据；
- 自然/广告流量结构；
- 关键词覆盖与转化问题；
- Listing 问题与广告动作分离。

## 统一写回

```text
runtime/scripts/run_ad_writeback.py
```

- 否词：SP 关键词、SP ASIN；
- 精准：SP 关键词、SP ASIN；
- 调价：SP 目标出价；
- 单个失败不阻断其余项；
- 批次级 schema / identity / digest 错误才整体停止；
- 面板保存即业务授权，不重复要求 `batch_id:hash`。

## 数据前置

包内不含业务数据。完整看板需要：

```text
Lingxing 同日源文件
ETA/发货工作簿
B-line 广告/Listing 基础看板
```

构建命令见 `references/full-cockpit.md`。

## 明确不做

- 不自动把领星表现词塞入词库；
- 不用旧否词单页冒充完整看板；
- 不展示未观测到的 SIF 自然/广告排名；
- 不改写 PMC/库存核心计算规则。
