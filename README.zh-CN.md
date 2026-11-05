# CaseFlow 中文导读

通过真实MCP及两个HTTP/PostgreSQL服务完成知识修订、审批、索引与工单关闭。72项合成任务中原始与任务化工具均72/72，任务化输入减少29.7%；按需Skills为71/72，未显示费用改善。

这是独立可安装的个人工程项目。历史测量在2026年11月1日完成，本次拆仓于2026年11月5日整理；运行检查与新模型效果实验分别记录。

先按英文 [README](README.md) 安装，再运行：

```bash
uv sync --locked
uv run pytest -q
uv run python scripts/verify_results.py
```

这三步分别完成依赖安装、离线回归和历史结果复算。需要真实模型调用的命令另见 [运行说明](docs/RUNNING.md)，需自行通过环境变量提供凭据。评测结果及适用范围见 [结果说明](docs/RESULTS.md)，逐条结果在 `results/`。本仓库不包含企业内部材料、访问密钥、大型模型缓存或原始数据库。
