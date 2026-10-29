# 领星 API 补充数据契约

状态：0.2.0-alpha.1 只实现 FBA 在途到仓 ETA 适配、离线挂接与验收；其余接口列为后续实施项。MCP 仍是运营身份与现有经营数据的主要来源。API 企业凭据不能替代当前用户的店铺授权。

## 本批接口与边界

`b_ops.collect.lingxing_supply.collect_supply` 接收宿主提供的 `read_api(path, body)`、可信 `allowed_sids` 和店铺-ASIN目标列表。只允许以下两个 POST 查询接口：

1. `/erp/sc/routing/fbaSug/asin/getSourceList`：`sid + asin + type="2"`，取货件号和当前在途数量。
2. `/erp/sc/routing/storage/shipment/getInboundShipmentList`：`sids + search_field="shipment_id" + search_value`，读取发货单；在返回的 `relate_list` 再按 sid、asin、shipment_id 三项精确关联。

适配器不持有 App Secret，不实现登录、签名或刷新 token。独立运行时复用已有领星 API 客户端；南斗接入后由服务端凭据层注入签名调用。这一层未新增第三方 Python 依赖。当前没有一个可独立认证的 OpenAPI CLI，不能将其描述为完整 API SDK。

仅 `expected_arrival_date` 作为 FBA 到仓日期；不用 `eta_date`（港口）、`amazon_sale_date`（预计可售）。仅采用已发货状态的精确关联。多张发货单匹配同一货件且无法分配批次时标记歧义；重复来源货件、数量异常不累加。过期日期保留，但不作为未来新增到货。空日期与未匹配货件保持未知。

ASIN 来源接口无分页参数，实测非空 `source_list` 的顶层 `total` 也可能为 0，不以此判定缺页。发货单查询限制 100 条，若总数与返回条数不符，明确 `API_INCOMPLETE_PAGE`，本阶段不声称自动取全；后续实现分页后才能扩大该边界。

同一批次按店铺+货件复用发货单查询；失败无隐藏重试，调用次数有硬上限。计数是适配器调用次数，宿主 API 客户端的重试仍需另外审计。跨进程 API 缓存和更新时间增量尚未实现；不能与已有 SIF 缓存混称完成。

## 本地离线挂接

```powershell
<隔离环境Python> runtime/scripts/attach_supply_data.py `
  --snapshot <原始inventory-snapshot.json> `
  --supply <supply.json> `
  --board <现有board-pmc.json> `
  --output-dir <外置新目录> `
  --allowed-sids <当前授权店铺ID...>
```

要求同一业务日期、已有店铺-ASIN、唯一关联及允许范围。拒绝输出覆盖输入文件。先补充原始库存记录，再复用 `analyze_snapshot.mjs → fuse_board → render_board`，不直接改已计算的补货结论。保留原有广告/SIF批次、日期、字段和母版布局。生成目录是候选快照，不自动替换正在服务的面板。

本地命令行的 allowed-sids 不是企业权限系统；进入南斗后必须由后端重新计算，禁止接受浏览器或 Agent 自报的权限。该适配器还没有跨用户服务入口。

## 后续接口按顺序实施

| 数据 | 接口 | 必须保留的语义 | 验收前不得做的推断 |
|---|---|---|---|
| FBA货件内容 | `/erp/sc/data/fba_report/shipmentList` | SKU/MSKU/FNSKU，计划/实发/已收数量分列；箱信息单独关联 | 不把整张货件总量分给每个ASIN |
| 本地产品箱规与MOQ | `/erp/sc/routing/data/local_inventory/productInfo` | `cg_box_pcs`是标准箱规；MOQ按supplier_quote/quotes/step_prices分层 | 多供应商、多阶梯不能压成一个全局MOQ；个人参数不能覆盖来源事实 |
| 采购未结 | `/erp/sc/routing/data/local_inventory/purchaseOrderList` | `quantity_real`、`quantity_receive`、`quantity_entry`、`expect_arrive_time`分列 | 待到货不等于已发货；关闭、作废、退货处理验收前不重算总采购缺口 |
| 实际采购收货 | `/erp/sc/routing/deliveryReceipt/PurchaseReceiptOrder/getOrderList` | 头部receive_time、行product_receive_num、seller_id、business_order_sn+order_item_id | seller_id=0留在未分配池，不能通过SKU猜店铺；部分收货不代表整单完成 |
| 系统入库 | `/erp/sc/routing/storage/inbound/getOrders` | opt_time、inbound_time、product_total、seller_id、purchase_item_id分别留存 | 自定义入库日期不是系统操作时间；收货与入库不能重复增加库存 |

附带材料记录了此前 API 项目的真实抽样验证，但它是历史证据，不代表本项目已经实现这些接口，也不代表当前数据仍相同。

## 增量策略

发货单支持更新时间类型 `time_type=4`；下一阶段按账户+权限版本+端点保存成功水位，使用重叠窗口回查、稳定业务键 upsert、分页去重，完整成功才推进水位。删除/作废要同步变更状态并移除未来供给，不能只追加新单。ASIN 来源是当前状态查询，按活跃商品刷新，不伪造 since 参数。采购、收货、入库须分别确认自己的时间字段与删除语义后再做增量。

SIF 继续使用现有成功缓存和失败续跑。信号、周历史、日排名各有新鲜度需求；未来组织共享额度由宿主统一限流和预留预算。不能把“每日重新请求全部历史”称作增量，也不能把HTTP调用次数当作供应商配额消耗。
