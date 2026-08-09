# 架构与不变量

## 目标

AI 网盘助手把容易变动的 Agent 决策压缩到最小，将参数验证、路径包含、命名、脱敏、冲突检查和状态核验放在确定性 CLI 中。

```text
用户意图
  ↓
SKILL.md 状态机（参数翻译 + 确认点）
  ↓
bin/panlib-* 公开 CLI（JSON 契约）
  ↓
panlib/ 配置、路径、命名、脱敏与进程边界
  ↓
vendor/seedhub-cli（只读网络/直链与受限 QR 解析） | bdpan（wrapper 内只读探测与外部网盘能力）
```

## 官方 MCP 与可替换凭证边界

`panlib-library` 是与既有 transfer/organize 并列的全盘能力入口。它通过
内置 `bin/panlib-mcp-bridge` 调用官方 Python MCP SDK（SSE `ClientSession`），不要求
默认设置 `PANLIB_MCP_COMMAND`。默认 provider 从 macOS Keychain
`ai-netdisk-manager.baidu-mcp.oauth` 读取 JSON 授权载荷，Token 只存在进程内存，不进入
argv、日志或 JSON 输出。可替换 provider 只允许一个绝对可执行的 `external-command`
安全代理，以受限 JSON stdin/stdout、无 shell、超时和大小限制工作；不提供明文文件回退。
仓库不捆绑 Windows/Linux 系统安全存储实现，因此跨平台能力只完成接口契约和自动化测试，
不声称实机验收。

`list`、`search`、`meta` 只读；`archive` 仅调用官方 `file_move`，参数固定为
`async=0`、`ondup=fail`、`filelist=[{path,dest,newname}]`。归档默认 plan-first，执行前
重读精确源/目标并绑定 `plan_ref`，执行后必须验证源路径消失且目标名称唯一存在；没有
delete CLI 或 delete MCP 调用，归档内容由用户人工审核后手动删除。MCP 路径允许官方全盘
绝对 POSIX 根（包括 `/apps/bdpan` 与 `/我的资源`），但仍拒绝遍历、反斜杠、控制字符和
模糊目标。

organize 的媒体侧车规则属于现有 bdpan 流程：`.ass/.srt/.ssa/.sub/.sup/.vtt/.idx` 随正片
一起移动；文件名中的简体/繁体标记稳定映射为 `.zh-Hans`/`.zh-Hant`；电影 `.jpg` 统一
落为 `poster.jpg`。organize 不再移除源目录，兼容参数 `--remove-empty-source` 直接
返回 `INVALID_ARG`，旧源应转交上面的 MCP archive 做人工审核。

## 层级职责

| 层 | 允许 | 禁止 |
|---|---|---|
| Agent | 理解请求、补齐参数、展示计划、等待确认 | 猜测云端路径、自写替代脚本、读凭证 |
| 公开 CLI | 验证输入、输出 JSON、调用共享库 | 将 plan 隐式升级为写入 |
| `panlib/` | 配置优先级、路径包含、命名、脱敏、受控子进程 | 依赖个人绝对路径 |
| vendor | 小型可审计补丁、离线 fixture seam | 通过环境变量改写正式网络目标 |
| bdpan | 被项目 wrapper 调用 | 由 Agent 直接调用 |

## 不变量

1. 配置优先级为环境变量 > 仓库根 `.env` > 可移植默认值。
2. legacy bdpan 路径必须在 `BDPAN_BASE` 内；MCP 全盘路径可使用官方允许的绝对 POSIX
   根，但两类路径都禁止遍历、空组件、反斜杠和控制字符。
3. 成功 JSON 写 stdout，人类日志写 stderr；错误、日志和 transfer 输出中的分享 URL/提取码以及所有个人路径必须脱敏。Agent 的 SeedHub 路径由 transfer 通过 resource-id 内部解析，计划/执行只交接不包含提取码的 share_ref。extract 的敏感 stdout 仅为人工诊断兼容边界，不得进入 Agent 状态机。
4. transfer 和 organize 默认 plan-first；仅显式 `--execute` 写入。
5. 写前重新读取目标状态；写后只有唯一、合法、新增目录才能交给 organize。
6. 转存与整理分开，不支持隐式串联。
7. 任何部分完成或读回失败都不得触发自动写重试。
8. organize 的 `target-dir` 叶子名必须等于 naming 模块根据 title/IMDb 生成的标准文件夹名；Agent 只拼接已验证分类父目录与 CLI 确定性叶子。
9. resource-id 计划与执行会分别解析候选；只有绑定资源、候选索引和 URL 的 share_ref 完全一致才允许写入，防止确认后的资源目标漂移。
10. resource-id 计划/执行在写入前先由 wrapper 调用官方 `bdpan transfer list --json`；只有 `share_probe.status=valid` 才能继续。探测失败不执行 transfer，且 URL/提取码不进入 Agent 输出。

## 非事务写入

bdpan 不向本项目提供跨 `mkdir` / `mv` / `rename` / 空目录移除的原子事务。因此 organize 是**非事务**的 fail-fast 流程：每次写前检查冲突，首个失败立即停止，返回已完成动作，不自动回滚。Agent 必须把这一限制告知用户。

## 扩展规则

- 新网盘先建独立 adapter，不在现有 bdpan wrapper 中混入分支。
- 新资源站先建独立只读 provider，统一映射到现有 JSON 契约。
- 磁力获取与下载是独立信任边界，不复用百度转存确认。
- 改变 JSON、错误码或写入顺序时，必须同步 `SKILL.md`、CLI 契约和回归测试。
