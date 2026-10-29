# Amazon Ops Runtime 代码依赖包

这个包只包含运行代码，不包含 `storage/`、看板数据、审核意见或历史批次。

## 目标机器要求

- Windows
- Python 3.12+
- Node.js 24+（仅运行 JS 测试需要）
- 可访问领星 / SIF / SellerSprite MCP

## 安装

```powershell
Set-Location <解压后的 amazon-ops-b-runtime>
python -m pip install -r requirements-runtime.txt
```

## 环境变量

不要把密钥写进代码或提交到仓库。使用用户环境变量或当前进程环境变量：

```powershell
$env:AMAZON_OPS_RUNTIME = (Get-Location).Path
$env:LINGXING_MCP_KEY = "..."
$env:SIF_MCP_KEY = "..."
$env:SELLERSPRITE_MCP_KEY = "..."   # 可选，只有需要卖家精灵补充数据时
```

Skill 包通过 `$env:AMAZON_OPS_RUNTIME` 找到本目录。

## 数据

代码包不包含：

```text
storage/
board-pmc.html
ops_state.sqlite3
pmc_sources/
历史批次
```

因此新电脑第一次运行是空状态，需要重新拉取数据、重新生成批次，再在面板保存新的审核意见。

## 验证

```powershell
python -m pytest tests -q
node --test tests_js/app-render.test.mjs tests_js/model.test.mjs
```

## Skill + Runtime

复制时同时保留：

```text
amazon-ads-search-term-root-diagnosis/
amazon-ops-b-runtime/
```

并设置 `AMAZON_OPS_RUNTIME`。只复制 skill 包、不复制 runtime，会导致精准/调价写回入口找不到。
