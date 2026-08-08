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
vendor/seedhub-cli（只读网络） | bdpan（外部网盘能力）
```

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
2. 所有云端路径必须在 `BDPAN_BASE` 内，禁止遍历、空组件、反斜杠和控制字符。
3. 成功 JSON 写 stdout，人类日志写 stderr；错误、日志和 transfer 输出中的分享 URL/提取码以及所有个人路径必须脱敏。Agent 的 SeedHub 路径由 transfer 通过 resource-id 内部解析，计划/执行只交接不包含提取码的 share_ref。extract 的敏感 stdout 仅为人工诊断兼容边界，不得进入 Agent 状态机。
4. transfer 和 organize 默认 plan-first；仅显式 `--execute` 写入。
5. 写前重新读取目标状态；写后只有唯一、合法、新增目录才能交给 organize。
6. 转存与整理分开，不支持隐式串联。
7. 任何部分完成或读回失败都不得触发自动写重试。
8. organize 的 `target-dir` 叶子名必须等于 naming 模块根据 title/IMDb 生成的标准文件夹名；Agent 只拼接已验证分类父目录与 CLI 确定性叶子。
9. resource-id 计划与执行会分别解析候选；只有绑定资源、候选索引和 URL 的 share_ref 完全一致才允许写入，防止确认后的资源目标漂移。

## 非事务写入

bdpan 不向本项目提供跨 `mkdir` / `mv` / `rename` / 空目录移除的原子事务。因此 organize 是**非事务**的 fail-fast 流程：每次写前检查冲突，首个失败立即停止，返回已完成动作，不自动回滚。Agent 必须把这一限制告知用户。

## 扩展规则

- 新网盘先建独立 adapter，不在现有 bdpan wrapper 中混入分支。
- 新资源站先建独立只读 provider，统一映射到现有 JSON 契约。
- 磁力获取与下载是独立信任边界，不复用百度转存确认。
- 改变 JSON、错误码或写入顺序时，必须同步 `SKILL.md`、CLI 契约和回归测试。
