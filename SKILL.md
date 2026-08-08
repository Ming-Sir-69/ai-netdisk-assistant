---
name: ai-netdisk-assistant
description: >-
  Use when a user asks to install this repository, find or add film and TV
  resources, transfer a Baidu Netdisk share, or plan safe media organization.
allowed-tools: Bash, Read, AskUserQuestion
argument-hint: "[影视关键词、百度网盘分享链接或精确云端路径]"
---

# AI 网盘助手

## 核心原则

Agent 只把用户意图翻译为结构化参数、调用本仓库 CLI、根据 JSON 状态决策。确定性逻辑必须留在 CLI，不临时编写脚本替代。

**禁止直接调用 `bdpan`。** 唯一允许的入口是 `scripts/` 和 `bin/panlib-*`。不得读取或回显账号、Token、Cookie、BDUSS、账号密码、验证码、MFA 或 OAuth 授权码。SeedHub 资源只能通过 transfer 的 `--resource-id` 内部解析；Agent 不调用 `panlib-extract`，也不把 URL/提取码作为 transfer 参数。

## 能力边界

当前支持：

- SeedHub 影视搜索与百度分享链接提取。
- 本地已知表或用户提供的 IMDb ID。
- 百度网盘转存与影视文件整理。

当前不支持：整盘盘点、定期任务、其他网盘写入、磁力下载、实时豆瓣/OMDb 查询。对“整理我的网盘”这类宽泛请求，先请用户给出影视关键词或精确 `source_dir`，不扫描整盘，不直接拼接网盘命令。

## 安装状态机

1. 已有仓库就复用现有目录；没有时只 clone 用户给出的 URL 一次。
2. `cd` 到仓库根目录，运行 `./scripts/bootstrap.sh`。
3. Python 缺失/低于 3.13，或现有 `.venv` 无效：停止，请用户安装或修复 Python 3.13+，然后重跑审计；不在未支持解释器上安装依赖。
4. 缺少 Python 依赖：说明将联网安装 `requirements.txt`；只有用户明确同意才运行 `./scripts/bootstrap.sh --install-deps`。
5. 缺少 bdpan：展示并打开 `https://github.com/baidu-netdisk/bdpan-storage` 或官方 `skills/baidu-drive/scripts/install.sh` 页，停止等待用户安装。不静默下载或执行外部安装器。
6. 未授权：运行 `./scripts/login.sh`。用户自行阅读提示、在百度官方页登录、将 32 位授权码粘贴到终端并回车。Agent 不索要授权码。
7. 运行 `./bin/panlib-doctor`。仅顶层 `status=ready` 可继续；其他状态按 `next_steps` 停止或交给用户。

## 业务状态机

### A. 只读候选链

1. `.venv/bin/python bin/panlib-search --keyword "<keyword>" --type <all|movie|tv|anime> --limit <n>`
2. 用户选择或请求中已唯一确定候选后，获取返回的 `id`。
3. `.venv/bin/python bin/panlib-imdb --title "<title>"`；本地表无结果就请用户提供 `tt...`，然后用 `--imdb-id`验证。
4. 用 `.venv/bin/python bin/panlib-transfer --resource-id <id> ...` 生成转存计划，**不加** `--execute`。transfer 在自己的进程内解析链接，不把 URL/提取码返回给 Agent。
5. 若返回 `INVALID_ARG` 且 `error.details.candidates` 非空，只展示其中的 index、description、quality、resource_type 和 has_password，请用户选择唯一候选后用 `--link-index <index>` 重新生成计划；不默认选第一条。
6. `NOT_FOUND`、`NETWORK`、`PARSE` 或任何其他非零退出：停止并报告，可请用户选择另一资源；不自动进入写操作。

### B. 转存：计划 → 第一次确认 → 执行

1. 运行 `.venv/bin/python bin/panlib-transfer` 并传入 `--resource-id`、可选 `--link-index`、type、title、IMDb ID、year、quality，**不加** `--execute`。
2. 必须确认返回 `meta.mode=plan-only` 和 64 位小写十六进制 `share_ref`，向用户展示 `dest_dir`、动作类型、影响范围和验收方式。计划成功不等于已转存。
3. 获得明确确认后，使用相同业务参数，加计划返回的 `--share-ref <share_ref>` 和 `--execute`。transfer 会重新解析；候选或 URL 发生漂移时必须停止并重新计划。
4. 只有结果同时满足 `executed=true`、`postcondition.status=verified`、`organize_ready=true`、`source_dir` 非空，才可进入整理。
5. `postcondition.status=ambiguous|unverified`、`partial`、空 `source_dir` 或失败：立即停止。**不得猜测 `source_dir`**，不得自动重试写操作。

### C. 整理：计划 → 第二次确认 → 执行

1. `source_dir` 只能来自上一步已验证输出，或用户显式给出的精确路径。
2. 运行 `.venv/bin/python bin/panlib-organize` 并传入 source/target/title/IMDb/year/quality/mode，**不加** `--execute`。
3. 展示完整 `actions`、源目录、目标目录、文件数和“该流程非事务，可能部分完成”，获得第二次明确确认。
4. 如果不移除空源，用完全相同的参数加 `--execute` 且只执行一次。如果用户希望移除空源，先执行 D 的额外计划与确认，然后只执行一次。
5. 源为空、文件名无法解析或发生冲突时停止，不创建、不删除。任何部分失败：报告 `error.details.completed` 与 `error.details.failed_action`，停止当前项及批处理；不自动重试、不猜测回滚。
6. 如计划包含空源移除，执行后必须检查 `data.cleanup`。只有 `requested=true`、`verified_empty=true`、`removed=true` 才报告已移除；`removed=false` 时报告“媒体整理已完成，源目录未移除”，不重试。

### D. 空源目录移除：第三次独立确认

`--remove-empty-source` 默认禁用。用户希望移除时，在尚未执行 organize 前，用同一组参数加 `--remove-empty-source` 但仍不加 `--execute` 重新生成计划；展示 `verify-empty`/`rm` 和精确源路径，获得**第三次独立确认**。然后才可用该已确认参数加 `--execute`，且整个 organize 只执行一次。CLI 会在末尾重读，仅源目录为空时移除；不删除非空目录或媒体文件。

## 错误决策

| 状态 | 动作 |
|---|---|
| `AUTH` | 只运行 `scripts/login.sh`，然后 doctor；不查看账号正文 |
| `NETWORK` | 只读步骤可请用户决定是否重试；写入步骤绝不自动重试 |
| `PARSE` | 停止，报告外部页面契约变化；不修补正则后直接写入 |
| `INVALID_ARG` | 补全参数或处理冲突后重新生成计划 |
| `NOT_FOUND` | 区分资源、分享链接和源目录；不用“换关键词”处理空源目录 |
| `PERMISSION` | 停止并报告精确目标，不改到更宽范围 |
| `ambiguous` / `unverified` 或上层验收标为 `partial` | 停止，不继续整理，不宣称完成 |

## 禁止的快捷方式

- 用户催促不能取消三个写入/移除确认点。
- 不将 plan-only 说成已执行。
- 不从标题、目标路径或 bdpan 文本输出猜测 `source_dir`。
- 不自动重试 transfer、mkdir、mv、rename 或移除操作。
- 不用直接网盘命令绕过路径、冲突、脱敏或状态核验。
- 不读取本地网盘配置文件。
- 不用 `panlib-extract` stdout 或 transfer 的 `--url/--password` 人工兼容参数拼接 Agent 命令。

## 快速参考

| 入口 | 只读 | 可写 | 确认 |
|---|---:|---:|---|
| `scripts/bootstrap.sh` | 只读外部系统 | 可创建项目 `.venv`；安装需开关 | 联网安装依赖前 |
| `scripts/login.sh` | 否 | 写入 bdpan 用户配置 | 用户在终端交互 |
| `panlib-doctor/search/imdb` | 是 | 否 | 无 |
| `panlib-extract/verify` | 人工诊断兼容入口，Agent 不调用 | 否 | 无 |
| `panlib-transfer` | 默认 | `--execute` | 第一次 |
| `panlib-organize` | 默认 | `--execute` | 第二次 |
| `--remove-empty-source` | 否 | 是 | 第三次 |

参数以各命令 `--help` 和 [docs/CLI_CONTRACT.md](docs/CLI_CONTRACT.md) 为准。
