# VT — Vibe-Trading 策略仓库

基于 Vibe-Trading 框架开发的量化选股策略，部署于国金 QMT 平台。

## 目录结构

- `*.py` — QMT 平台策略脚本（#coding:gbk）
- `QMT平台规则相关/` — QMT API 封装与工具
- `backtest_*.py` — 回测脚本
- `check_*.py`、`fetch_*.py`、`download_*.py` — 数据获取与验证工具

## 注意

所有策略文件需使用 GBK 编码，兼容 QMT 内置 Python 3.6.8 环境。
