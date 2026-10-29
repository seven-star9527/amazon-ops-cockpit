# 0.2.0-alpha.1 验收记录

日期：2026-10-29。范围：本项目只读 API 适配、离线候选面板及南斗接入规划。南斗未修改，未开启定时任务、业务写入或正式发布。

## 结果

| 检查 | 结果 |
|---|---|
| Python回归 | 220项通过，含18项API适配测试 |
| JavaScript回归 | 88项通过，含API来源展示测试 |
| 当前领星MCP权限 | 重新查询本人店铺，API限定在这两家店铺 |
| OpenAPI真实业务查询 | 19次返回code=0；包含一个返回空的店铺-ASIN探测，未纳入快照；认证/内部重试不计作这19个业务调用 |
| 有效挂接 | 4个已有商品、14条货件，均为partial：10条ETA过期、2条ETA缺失、2条发货单未匹配 |
| 供给判断 | 没有新增未来确认到仓；旧日期不用于推迟断货日；API来源量与MCP当前库存差异保留 |
| 原面板数据 | 171个商品；关键词状态、排名数据、广告actions及run_id与输入完全一致 |
| 浏览器 | 样本显示30个核心词、11个双周有效词；自然排名14/14天、广告排名13/14天；API来源卡片可见并标记ETA待补 |
| 只读HTTP | 首页200；数据文件路径404；POST首页501 |
| 凭据与依赖 | 无新增Python运行依赖；既有API客户端在自身环境运行；密钥、响应和面板不进Git |

## 可复现命令

```text
<venv-python> -m pytest runtime/tests runtime/pmc/tests -q
node --test runtime/tests_js/*.test.mjs runtime/pmc/tests/*.test.mjs
<venv-python> runtime/scripts/attach_supply_data.py --snapshot <input-snapshot> --supply <supply-json> --board <input-board> --output-dir <external-preview> --allowed-sids <authorized-sids>
```

真实响应、追踪ID、截图及哈希留在本机外置验收目录，不随源码发布。真实样本未覆盖有效未来ETA；该正向分支由合成测试验证，不能宣称真实未来到仓链路已完整验收。

未完成：货件完整内容、箱规MOQ、采购/收货/入库API适配、API跨进程增量、企业权限和应用接入。详细顺序见 [接入计划](nandou-integration-plan.md)。
