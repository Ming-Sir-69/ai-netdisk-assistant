# CLI 契约

## 通用 I/O

本项目有 **7 个 CLI**：`panlib-doctor`、`panlib-search`、`panlib-imdb`、`panlib-extract`、`panlib-verify`、`panlib-transfer`、`panlib-organize`。

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

`--fixture-dir` 是测试专用的显式离线 seam，在正常 Agent 调用中不使用。`--episode` 与 `--dry-run` 仅保留旧调用兼容性，已从公开 help 隐藏；TV 季集号从源文件名解析。

## transfer 契约

不加 `--execute`：

- 不调用任何 bdpan 写操作。
- `meta.mode=plan-only`。
- `data.execute_required=true`，并给出脱敏 plan 和 `dest_dir`。
- Agent 路径使用 `--resource-id`。唯一候选自动选择 index 0；多候选返回 `INVALID_ARG` 和脱敏候选元数据，必须用 `--link-index` 明确选择。
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
5. 默认保留源目录。只有额外 `--remove-empty-source` 且再读确认为空时才移除空目录。

`target-dir` 的叶子名必须精确等于 naming 模块生成的 `{Name}.{imdb-ttXXXXXXX}`；任意自定义叶子名在第一次 bdpan 读取前被拒绝。

如请求空源移除，执行结果必须检查 `data.cleanup`：只有 `requested=true`、`verified_empty=true`、`removed=true` 可报告已移除。`removed=false` 仍可以表示媒体整理已完成，但必须明确报告空源没有移除，不自动重试。

`partial` 是发布/上层验收标签，不是 CLI 字段。organize 失败且 `error.details.completed` 非空，表示已产生部分副作用。

整理为非事务流程。**失败不得自动重试**，不自动回滚，不继续后续资源。

## 参数约束摘要

- IMDb ID：`tt` + 7–8 位数字。
- year：1800–2199 的四位年份；电影模式必填。
- quality：仅接受 naming 模块列出的精确别名，不做模糊前后缀匹配。
- 媒体扩展名：`mkv`, `mp4`, `ts`, `avi`, `iso`。
- 云端路径：绝对 POSIX 路径，必须包含在 `BDPAN_BASE`。
- 分享 URL：仅 canonical `https://pan.baidu.com/s/<id>`，可选单个 4 位字母数字 `pwd`。
- resource-id：1–32 位数字；link-index 从 0 开始；share-ref 为计划返回的 64 位小写十六进制值。

`panlib-extract` 与 transfer 的 `--url/--password` 是人工兼容入口，可能把链接或提取码带入终端/会话记录。Agent 状态机不得使用它们；Agent 只使用 resource-id/link-index/share-ref 路径。

## 重试规则

- doctor/search/extract/verify 的只读 `NETWORK` 失败：由用户决定是否重试。
- transfer/organize 只要已进入 `--execute`：不自动重试，先重新读取现状并展示给用户。
