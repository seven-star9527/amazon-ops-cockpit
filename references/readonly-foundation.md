# 可靠只读底座

安装时显式运行 `python scripts/bootstrap.py --data-dir <外置目录>`。运行和测试依赖分别固定在 runtime/requirements-runtime.txt、requirements-test.txt；测试环境使用 bootstrap 的 --test。安装只作用于外置目录下 venv，启动不安装或升级依赖。当前实测 Windows、Python 3.13.15、系统 Node；其他 Python 3.11+ 平台尚未实测。

数据目录由 --data-dir 或 AMAZON_OPS_DATA_DIR 指定。未配置时 Windows 使用 LOCALAPPDATA/amazon-ops-cockpit，其他系统使用 ~/.local/share/amazon-ops-cockpit。拒绝把显式数据目录设在技能包内部。旧 runtime/storage 不自动迁移、不删除；迁移须确认原件及数据归属。

个人箱规 carton-rules.json、店铺别名 store-names.json、运输策略 transit-policy.json 由快照构建器优先读取 AMAZON_OPS_CONFIG_DIR，或 AMAZON_OPS_DATA_DIR/config。未提供时使用包内通用策略和空箱规；账户定制不写入源码。单独调用构建器时需显式设置上述环境变量。

运行隔离环境里的 Python：

```powershell
<数据目录>/venvs/readonly-v1/Scripts/python.exe scripts/run_cockpit.py --check --data-dir <数据目录> --board <board-pmc.json>
<数据目录>/venvs/readonly-v1/Scripts/python.exe scripts/run_cockpit.py --serve --data-dir <数据目录> --board <board-pmc.json> --port 0
```

端口 0 由系统分配空闲端口，日志显示实际地址。只监听 127.0.0.1，只提供首页，不提供目录下载、审核保存或业务写入。--check 的 READY_READ_ONLY 表示运行依赖及完整面板结构满足启动要求，不表示所有数据已取全／已更新；来源日期与 partial 仍在面板中保留。旧 serve_pmc.py 是独立交互审核入口，不是本底座的启动方式。

读取数据使用隔离环境运行 runtime/scripts/refresh.py --data-dir <目录>。原有 --replay-lingxing、--replay-sif、--resume-sif、--extend-sif 保留。该命令仅采集和写本地快照，仍会消耗外部读取额度；不会执行广告写回。缓存位于 storage/cache/sif.sqlite3，原始批次位于 storage/runs，状态位于 storage/state。每个目录只允许一个刷新写入者，进程退出自动释放 OS 锁。

SIF 成功响应持久缓存，按连接身份摘要、工具、参数、schema 版本和滚动窗口日期隔离；参数统一 pageSize，关键词列表排序去重。重启后重复相同请求可命中，失败不缓存为成功，失败项冷却 60 秒后允许下次运行重试。信号缓存一天内有效并按 UTC+8 日期切换；其他查询有效期 7 天。--sif-max-calls 默认限制每次运行 100 次缓存未命中调用，不等于供应商配额单位，也不包括底层限流／会话恢复的实际网络重试。连接撤权的企业校验待南斗接入，不把本地缓存作为授权系统。

当前是请求级缓存和同日续跑；还未实现跨不同组批的词级复用、供应商原生 since 增量、跨账号缓存共享及自动历史回补规划。改变关键词组批会形成新请求。缓存到期由读取惰性更新，容量淘汰／组织保留策略待宿主接入。不要宣称完整企业增量平台已完成。

ResumeSif 的成功响应可重复使用；纯历史 ReplaySif／ReplayLingxing 保留逐响应消费语义。需要从当天完整批次补失败项时用 --extend-sif；中断且无 manifest 的批次用 --resume-sif。历史回放不是新鲜采集。

数据质量：库存两个必要字段没有完整证据时不判定已证明断货；缺失销量、日历日期缺口在输入／序列化／计算中保留未知，不补成零；真实零销售仍参与计算。原有诊断阈值、补货策略、布局与交互保留，修正缺失值后部分风险判断会变化。
