# CLI 契约

## 通用 I/O

本项目原有 **7 个 CLI**：`panlib-doctor`、`panlib-search`、`panlib-imdb`、`panlib-extract`、`panlib-verify`、`panlib-transfer`、`panlib-organize`；另提供 `panlib-library` 全盘 MCP 入口。

- Python 业务 CLI 进入主逻辑后，stdout 为机器可读 JSON：成功为 `{"data": ..., "meta": ...}`，失败为 `{"error": {"code": ..., "message": ..., "details": ...}}`。
- `panlib-doctor` 是独立诊断契约：`{"status": ..., "checks": ..., "next_steps": [...]}`。只有顶层 `status=ready` 可继续。
- argparse 在缺少必填参数或出现未知开关时使用标准 usage/stderr 并退出 2；这一边界不使用 JSON 信封。
- stderr：经脱敏的人类诊断。
- 退出码：成功 0；失败非 0。
- 错误码：`NETWORK`、`PARSE`、`AUTH`、`NOT_FOUND`、`PERMISSION`、`INVALID_ARG`、`INTERNAL`。
- 公开参数真源是 `<command> --help`。隐藏的 `--fixture-dir`、兼容参数和测试 seam 以测试契约为准，Agent 不使用。

## 命令矩阵

| 命令 | 主要输入 | 默认只读 | 写入开关 |
|---|---|---:|---|
| `panlib-doctor` | 无 | 是 | 无 |
| `panlib-search` | `--keyword`, `--type`, `--limit` | 是 | 无 |
| `panlib-imdb` | `--title` 或 `--imdb-id` | 是 | 无 |
| `panlib-extract` | `--resource-id`, `--limit` | 是 | 无 |
| `panlib-verify` | canonical Baidu `--url` | 是 | 无 |
| `panlib-transfer` | resource-id/type/title/IMDb/year/quality；人工兼容 share URL | 是 | `--execute` |
| `panlib-organize` | source/target/title/IMDb/year/quality/mode | 是 | `--execute` |
| `panlib-library auth-status` | 无 | 是 | 无 |
| `panlib-library auth-store` | stdin 凭证 JSON | 否 | 写入当前安全凭证后端 |
| `panlib-library list` | `--path` 绝对云端目录 | 是 | 无 |
| `panlib-library search` | `--keyword`, 可选 `--path`/`--dir` | 是 | 无 |
| `panlib-library meta` | `--path` 或 `--fsid` | 是 | 无 |
| `panlib-library archive` | `--source`, `--archive-dir`, 可选 `--new-name` | 是 | `--execute --plan-ref` |

`--fixture-dir` 是测试专用的显式离线 seam，在正常 Agent 调用中不使用。`--episode` 与 `--dry-run` 仅保留旧调用兼容性，已从公开 help 隐藏；TV 季集号从源文件名解析。

## transfer 契约

不加 `--execute`：

- 不调用任何 bdpan 写操作。
- `meta.mode=plan-only`。
- `data.execute_required=true`，并给出脱敏 plan 和 `dest_dir`。
- Agent 路径使用 `--resource-id`。唯一候选直接选择；多候选使用 `preset-quality-v1` 确定性排序：分辨率 → 片源（REMUX/原盘/蓝光/流媒体）→ HDR/杜比视界 → 音轨 → 字幕 → 大小，完全相同以资源站原始顺序决胜。计划返回脱敏的 `selection.strategy`、候选数和 `selection.selected`（index/description/quality/resource_type/has_password，不含 URL 或提取码），便于核对依据而不询问用户。`--link-index` 仅用于用户明确要求的人工覆盖。
- resource-id 计划/执行在内部通过官方 `bdpan transfer list --json` 做只读分享探测；成功时返回 `share_probe.status=valid`。过期分享返回 `NOT_FOUND` 与 `share_status=expired`；网络、认证、权限或无法解析的响应返回 `share_status=unverified` 并停止。该探测不执行转存。
- resource-id 计划返回 64 位小写十六进制 `share_ref`，它绑定资源、候选索引和 URL，但不编码提取码；输出不返回 URL 或提取码。

加 `--execute`：

- resource-id 路径必须传回计划的 `--share-ref`；CLI 重新解析后若候选或 URL 漂移，写前拒绝执行。
- 在 transfer 前两次读取目标并拒绝同名冲突。
- 结果 `executed=true` 只表示转存子进程返回成功。
- 只有写后读到唯一、合法的新增目录，才返回 `postcondition.status=verified`、`organize_ready=true` 和非空 `source_dir`。
- 零条目、多条目、非目录、非法元数据或读回失败都不交给 organize。

## organize 契约

不加 `--execute`：只读发现源文件、验证目标和生成 `actions`。

加 `--execute`：

1. 再次检查目标类型与冲突。
2. 需要时创建目标目录。
3. 每个文件在 `mv` 前重检中间同名，在 `rename` 前重检最终同名。
4. 第一个失败立即停止，返回已完成动作。
5. `.ass/.srt/.ssa/.sub/.sup/.vtt/.idx` 字幕随正片移动；简体/繁体标记分别规范为
   `.zh-Hans`/`.zh-Hant`，电影 `.jpg` 海报统一为 `poster.jpg`。
6. 默认保留源目录；旧版或空残留目录另通过 `panlib-library archive` 生成移动计划。

`target-dir` 的叶子名必须精确等于 naming 模块生成的 `{Name}.{imdb-ttXXXXXXX}`；任意自定义叶子名在第一次 bdpan 读取前被拒绝。

`partial` 是发布/上层验收标签，不是 CLI 字段。organize 失败且 `error.details.completed` 非空，表示已产生部分副作用。

兼容参数 `--remove-empty-source` 已禁用；传入即返回 `INVALID_ARG`，不会调用 `rm`。
需要清理的旧源统一走 MCP archive 的 `file_move`，由用户人工审核后再手动删除。

整理为非事务流程。**失败不得自动重试**，不自动回滚，不继续后续资源。

## 参数约束摘要

- IMDb ID：`tt` + 7–8 位数字。
- year：1800–2199 的四位年份；电影模式必填。
- quality：仅接受 naming 模块列出的精确别名，不做模糊前后缀匹配。
- 媒体扩展名：`mkv`, `mp4`, `ts`, `avi`, `iso`。
- legacy bdpan 云端路径：绝对 POSIX 路径，必须包含在 `BDPAN_BASE`；MCP 全盘路径允许官方绝对根（如 `/apps/bdpan`、`/我的资源`），两者均拒绝遍历、反斜杠、控制字符。
- 分享 URL：仅 canonical `https://pan.baidu.com/s/<id>`，可选单个 4 位字母数字 `pwd`。
- resource-id：1–32 位数字；link-index 从 0 开始；share-ref 为计划返回的 64 位小写十六进制值。

`panlib-extract` 与 transfer 的 `--url/--password` 是人工兼容入口，可能把链接或提取码带入终端/会话记录。Agent 状态机不得使用它们；Agent 只使用 resource-id/link-index/share-ref 路径。

SeedHub `link_start` 解析优先读取页面 allowlist 内的 `.direct-pan`、`panLink`
和 `window.location` 直链，并将 URL 中唯一的 `pwd` 查询项拆分为内部字段。
没有直链时才尝试 QR 图片：仅接受 data URI 或 HTTPS 同源图片，单图不超过
2 MiB、像素不超过 16 MP，结果必须再次通过 canonical Baidu URL 校验。

`bdpan transfer list` 的进程参数在内部短暂包含分享链接和提取码，这是上游
CLI 的既有边界；wrapper 不把 argv、stdout 或 stderr 转发给 Agent，并对错误
和日志做脱敏。项目不读取本地 bdpan 配置，也不允许 Agent 直接调用 bdpan。

## 可替换凭证与 MCP library 契约

`panlib-library` 默认通过仓库内 `bin/panlib-mcp-bridge` 调用官方 MCP Python SDK；只有
测试或替代 host 才设置 `PANLIB_MCP_COMMAND`。默认凭证从 macOS Keychain 服务
`ai-netdisk-manager.baidu-mcp.oauth` 读取 JSON（`access_token`、`scope`、`expires_at_utc`
或兼容 `expires_at`），不输出 Token；过期状态返回 `AUTH`。

其他系统可显式设置 `PANLIB_CREDENTIAL_BACKEND=external-command` 与绝对可执行的
`PANLIB_CREDENTIAL_COMMAND`（兼容 `PANLIB_CREDENTIAL_HELPER`）。helper 每次只接收一个
JSON stdin 请求：`{"op":"get"}` 或 `{"op":"set","credential":"..."}`，并返回受限
JSON stdout。进程使用 `shell=False`、超时与输入/输出大小上限；凭证不进入 argv 或日志。
仓库不捆绑 Windows/Linux 安全存储 helper，也不提供明文文件回退。

交互授权入口为 `scripts/authorize_mcp_macos.py`：已有有效授权时直接退出且不打开浏览器；仅缺失、过期或用户显式 `--force` 时打开百度官方个人体验授权页，完整回调只从 `getpass` 隐藏输入读取。脚本固定校验官方 HTTPS 主机、成功回调路径以及 `response_type=token`、`redirect_uri=oob`、`scope=basic,netdisk`，并只把 JSON 载荷写入 Keychain。

- `auth-status` 只读并返回 backend/available/configured/reason/expiry/scope。
- `auth-store` 从 stdin 写入当前安全凭证后端并返回实际 backend；不回显凭证。
- `list` 调用 `file_list(dir=<path>,page=1)`；官方列表缺少 `isdir` 时，`category=6` 且
  `size=0` 视为目录，显式 `isdir` 优先。
- `search` 调用 `file_keyword_search(dir=<path>,key=<keyword>,page=1,num=100)`；`--path`
  与 `--dir` 等价，默认 `/`。
- `meta` 只接受 `--path` 或 `--fsid` 其中一个。
- `archive` 默认 plan-only，要求绝对精确源和归档目录；执行时必须回传 `plan_ref`。写前
  再读源/目标并拒绝目标冲突，唯一写请求必须是
  `file_move(async=0,ondup=fail,filelist=[{path,dest,newname}])`。写后重读父目录和归档目录，
  只有源路径消失、目标名称唯一存在才返回 `postcondition.status=verified`。
- 不提供 `file_delete`/`delete`；归档目录由用户人工审核后手动删除。任何网络、权限、
  过期或验收失败均停止，不自动重试。

## 重试规则

- doctor/search/extract/verify 的只读 `NETWORK` 失败：由用户决定是否重试。
- transfer/organize 只要已进入 `--execute`：不自动重试，先重新读取现状并展示给用户。
