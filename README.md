# 亚马逊运营工作台

提供完整运营看板、数据采集及诊断逻辑，可由 Agent 通过技能入口使用。当前基线是只读预览版；企业权限、多用户工作台和自动执行尚未接入。

## 隔离安装与启动

需要 Python 3.11+ 和 Node.js；已实测 Windows / Python 3.13。依赖安装在外置虚拟环境，不安装到宿主 Agent 的 Python。

```powershell
python scripts/bootstrap.py --data-dir D:/AmazonOpsData
D:/AmazonOpsData/venvs/readonly-v1/Scripts/python.exe scripts/run_cockpit.py --serve --data-dir D:/AmazonOpsData --board D:/AmazonOpsData/board-pmc.json --port 0
```

仓库不携带账户快照，首次需按 [完整看板流程](references/full-cockpit.md) 生成数据。缺少完整快照时启动明确失败。所有运行命令都应使用虚拟环境 Python；旧文档中的 `runtime/storage` 路径需改到外置目录。

只读入口绑定本机地址，不启动定时任务，不保存运营审核、不执行业务操作。旧交互入口及执行脚本保留，但不是默认入口，也不代表企业执行权限已验收。

## 数据与凭据

详见 [只读底座说明](references/readonly-foundation.md)。SIF 成功响应持久缓存，失败冷却后续跑；这属于请求复用，不是供应商原生增量接口。批次、缓存、面板和虚拟环境均保存在外置数据目录。

MCP 凭据由宿主连接器或进程环境注入，不从其他应用的历史会话中提取。不要把密钥、业务响应、个人配置和生成面板加入 Git。

## 版本与验证

版本见 [VERSION](VERSION)，变更见 [CHANGELOG](CHANGELOG.md)。预览标签表示代码基线，不表示生产发布或南斗已集成。

```powershell
python scripts/bootstrap.py --data-dir D:/AmazonOpsData --test
D:/AmazonOpsData/venvs/readonly-v1/Scripts/python.exe -m pytest runtime/tests runtime/pmc/tests -q
node --test runtime/tests_js/*.test.mjs runtime/pmc/tests/*.test.mjs
```
