# 领星 API 补充数据契约

状态：开发版本 0.2.0-alpha.2。在 0.2.0-alpha.1 的 ETA 适配上补齐 FBA 内容、SKU 箱规/MOQ、采购明细和实际收货四类数据，尚未正式部署。MCP 仍是运营身份与现有经营数据的主要来源。API 企业凭据不能替代当前用户的店铺授权。

## 本批接口与边界

`b_ops.collect.lingxing_supply.collect_supply` 接收宿主提供的 `read_api(path, body)`、可信 `allowed_sids` 和店铺-ASIN目标列表。只允许以下两个 POST 查询接口：

1. `/erp/sc/routing/fbaSug/asin/getSourceList`：`sid + asin + type="2"`，取货件号和当前在途数量。
2. `/erp/sc/routing/storage/shipment/getInboundShipmentList`：`sids + search_field="shipment_id" + search_value`，读取发货单；在返回的 `relate_list` 再按 sid、asin、shipment_id 三项精确关联。

适配器不持有 App Secret，不实现登录、签名或刷新 token。独立运行时复用已有领星 API 客户端；南斗接入后由服务端凭据层注入签名调用。这一层未新增第三方 Python 依赖。当前没有一个可独立认证的 OpenAPI CLI，不能将其描述为完整 API SDK。

仅 `expected_arrival_date` 作为 FBA 到仓日期；不用 `eta_date`（港口）、`amazon_sale_date`（预计可售）。先确认关联，再独立判定状态：待拣货、待发货、已发货、完成、作废分别保留。只有已发货且日期有效的记录才可用于未来到仓。多张发货单匹配同一货件且无法分配批次时标记歧义；重复来源货件、数量异常不累加。过期日期保留，但不作为未来新增到货。空日期与未匹配货件保持未知。

ASIN 来源接口无分页参数，实测非空 `source_list` 的顶层 `total` 也可能为 0，不以此判定缺页。发货单按 100 条分页；四类明细按 500 条分页。重复页、总数变化、缺页均报错，不把截断数据当作完整结果。

同一批次按店铺+货件复用发货单查询；失败无隐藏重试，调用次数有硬上限。计数是适配器调用次数，宿主 API 客户端的重试仍需另外审计。跨进程 API 缓存和更新时间增量尚未实现；不能与已有 SIF 缓存混称完成。

## 本地离线挂接

```powershell
<隔离环境Python> runtime/scripts/attach_supply_data.py `
  --snapshot <原始inventory-snapshot.json> `
  --supply <supply.json> `
  --details <details.json> `
  --board <现有board-pmc.json> `
  --output-dir <外置新目录> `
  --allowed-sids <当前授权店铺ID...>
```

要求同一业务日期、已有店铺-ASIN、唯一关联及允许范围。拒绝输出覆盖输入文件。先补充原始库存记录，再复用 `analyze_snapshot.mjs → fuse_board → render_board`，不直接改已计算的补货结论。保留原有广告/SIF批次、日期、字段和母版布局。生成目录是候选快照，不自动替换正在服务的面板。

计算和渲染在同文件系统的临时目录执行，全部成功后替换输出文件；任一步计算失败不破坏已有成功产物。该机制不保证多文件发布过程中磁盘异常或进程被杀时的整组原子性，服务化时需要不可变批次与单个发布指针。

本地命令行的 allowed-sids 不是企业权限系统；进入南斗后必须由后端重新计算，禁止接受浏览器或 Agent 自报的权限。该适配器还没有跨用户服务入口。

## 四类补充数据（本次已接入）

| 数据 | 接口 | 必须保留的语义 | 验收前不得做的推断 |
|---|---|---|---|
| FBA货件内容 | `/erp/sc/data/fba_report/shipmentList` | SKU/MSKU/FNSKU，计划/实发/已收数量分列；箱信息单独关联 | 不把整张货件总量分给每个ASIN |
| 本地产品箱规与MOQ | `/erp/sc/routing/data/local_inventory/productInfo` | `cg_box_pcs`是标准箱规；MOQ按supplier_quote/quotes/step_prices分层 | 多供应商、多阶梯不能压成一个全局MOQ；个人参数不能覆盖来源事实 |
| 采购未结 | `/erp/sc/routing/data/local_inventory/purchaseOrderList` | `quantity_real`、`quantity_receive`、`quantity_entry`、`expect_arrive_time`分列 | 待到货不等于已发货；关闭、作废、退货处理验收前不重算总采购缺口 |
| 实际采购收货 | `/erp/sc/routing/deliveryReceipt/PurchaseReceiptOrder/getOrderList` | 头部receive_time、行product_receive_num、seller_id、business_order_sn+order_item_id | seller_id=0留在未分配池，不能通过SKU猜店铺；部分收货不代表整单完成 |

系统入库明细接口 `/erp/sc/routing/storage/inbound/getOrders` **尚未接入本项目**。附带会话中对它的验证属于此前 API 项目的历史证据。当前仅从采购订单保留 `quantity_entry` 入库数量，不含独立入库单明细、系统操作时间或入库日期，不能把它描述成已经实现了入库接口。四类已接入数据的来源与下游影响见 [本批数据影响清单](lingxing-api-impact-alpha2.md)。

## 增量策略

发货单支持更新时间类型 `time_type=4`；下一阶段按账户+权限版本+端点保存成功水位，使用重叠窗口回查、稳定业务键 upsert、分页去重，完整成功才推进水位。删除/作废要同步变更状态并移除未来供给，不能只追加新单。ASIN 来源是当前状态查询，按活跃商品刷新，不伪造 since 参数。采购、收货、入库须分别确认自己的时间字段与删除语义后再做增量。

SIF 继续使用现有成功缓存和失败续跑。信号、周历史、日排名各有新鲜度需求；未来组织共享额度由宿主统一限流和预留预算。不能把“每日重新请求全部历史”称作增量，也不能把HTTP调用次数当作供应商配额消耗。

## 采集与挂接顺序

1. 宿主先查当前连接用户的授权店铺，传给 `collect_details(read_api, snapshot=..., allowed_sids=..., start_date=..., max_calls=...)`。快照中的 SKU 精确查询产品详情；采购与收货无店铺筛选参数时，返回行在适配器内过滤。店铺 0、其他店铺不会进入产物，不按 SKU 猜店铺。
2. `collect_supply(..., shipment_rows=details["shipments"])` 的目标取当前在途商品与已知未关闭货件商品的并集。申报但未实发的货件也解析发货单关联，不伪装成当前在途。
3. `attach_supply_data.py --details ...` 先协调 FBA 实发/已收数量，再重算 ETA 汇总，然后补采购与产品规则，复用原库存引擎、融合与渲染。真实台账在现有采购台账内折叠展示，原建议采购策略继续保留。

## 数量、时间和归属

- FBA 申报量、本地实发量、FBA 已收量分列。有效在途最多为实发减已收，并受当前 MCP 实时在途上限约束；待发、完成、作废不进未来确认曲线。港口 ETA、预计可售时间均不代替 FBA 到仓日期。
- 采购稳定键为 `order_sn + item.id`，收货为 `order_sn + item_id`。相同重复行去重，冲突行拒绝。通过 `business_order_sn + order_item_id` 关联后再核对店铺、SKU；不把采购入库量再加到收货量上。
- `quantity_receive` 是官方待到货余额（可能尚未发货）。只对已下单、未删、未全部到货且无退换货/数量冲突的行使用；尚未下单不计，关闭/作废不计，异常余额为未知。
- 收货使用 `product_receive_num + receive_time`，完整保留时分秒；采购预计自有仓时间使用 `expect_arrive_time`。已收完的采购即使保留未来预计日期，未来数量仍为零。自有仓 ETA 不进入 FBA 到仓曲线或救急恢复日。
- 汇总使用 metadata 中唯一采购/收货台账。同店同 SKU 对多个 ASIN 时，面板可引用明细，但未结量不按销量分摊，也不按 ASIN 重复汇总。官方组合产品关系用于展示组件单据，不把组件量相加成成品或假设已齐套。
- 采购余额明确标为“窗口内”，不是全历史余额。窗口外的采购可能仍有本期收货，该实际收货保持自身店铺/时间/数量事实，并标记原采购行待关联。
- 箱规大于零才作为默认补充；已配置的个人箱规不被覆盖。阶梯 MOQ 取各报价最低阶梯，仅在所有有效报价最低量一致时形成默认 MOQ；0 保留原值、待确认，不作为正起订量。多 SKU、报价冲突不强选。

## 尚未实现

API 跨运行持久缓存、更新时间增量、关闭/删除回查水位属于宿主后续能力。本次真实验收使用外置、同日期、同权限范围的缓存复用成功响应，不宣称已经实现通用增量调度。没有定时任务、采购/库存业务写入或南斗服务修改；现有 SIF 缓存不变。
