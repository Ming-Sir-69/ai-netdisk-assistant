# AI 网盘助手开发约定

## 范围

本仓库是 Agent 可调度的影视资源 → 百度网盘工作流。不把它扩展成通用网盘客户端，除非有独立设计、测试和用户授权。

## 必须保持的设计

1. Agent 只调用 `scripts/` 和 `bin/panlib-*`；不直接调用 bdpan，不读本地 bdpan 配置。
2. transfer/organize 默认 plan-first，只有显式 `--execute` 写入。空源移除是第三个独立确认点。
3. 云端路径必须在 `BDPAN_BASE` 内；不猜测转存后源目录。
4. 写操作非事务、fail-fast、不自动重试。部分成功时保留已完成动作并停止。
5. stdout 保持 JSON，stderr 保持脱敏。Agent 的 SeedHub 路径必须让 transfer 通过 `--resource-id` 在进程内部解析链接，并用 `share_ref` 完成计划/执行交接；不得调用 extract 后再把 URL/提取码拼进下一条命令。`panlib-extract` 只保留给了解其敏感 stdout 边界的人工诊断。Token、Cookie、BDUSS、个人路径和账号正文不进入输出或仓库。
6. 配置优先级为环境 > `.env` > 可移植默认值。

## 修改流程

- 实现任何功能或修复前，先写测试并运行观察预期失败，然后写最小实现。
- 修改写入路径时，必须覆盖 plan-only、执行顺序、冲突、TOCTOU、部分失败、状态持久化和隐私输出。
- 修改 SKILL 或 README 前先建文档契约测试；修改参数/JSON 后同步文档。
- vendor 修改必须小、可审计，保留第三方许可和 provenance 说明。
- 发布前按 `docs/RELEASE_CHECKLIST.md` 执行，不将 fake/fixture 结果说成真实网盘端到端通过。

## 文档真源

- Agent 状态机：`SKILL.md`
- 分层与不变量：`docs/ARCHITECTURE.md`
- 参数与 JSON：`docs/CLI_CONTRACT.md` 与各 CLI `--help`
- 隐私与发布：`SECURITY.md`、`docs/RELEASE_CHECKLIST.md`
