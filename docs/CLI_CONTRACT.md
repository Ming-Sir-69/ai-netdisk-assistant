# CLI 契约

## 通用 I/O

本项目原有 **8 个 CLI**：`panlib-doctor`、`panlib-search`、`panlib-imdb`、`panlib-offlinedl`（磁力云端离线下载，路线 A 首选）、`panlib-extract`、`panlib-verify`、`panlib-transfer`、`panlib-organize`；另提供 `panlib-library` 全盘 MCP 入口。

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
| `panlib-imdb` | `--title` + `--year`（默认联网），或 `--imdb-id`；`--known-table` 仅测试夹具用 | 是 | 无 |
| `panlib-offlinedl add` | `--link`（magnet/直链，自动补 tracker），可选 `--save-path` | 是 | `--execute`（可选 `--wait <秒>` 轮询） |
| `panlib-offlinedl status` | `--task-id` | 是 | 无 |
| `panlib-offlinedl who` | 无 | 是 | 无 |
| `panlib-extract` | `--resource-id`, `--limit` | 是 | 无 |
| `panlib-verify` | canonical Baidu `--url` | 是 | 无 |
| `panlib-transfer` | resource-id/type/title/IMDb/year/quality；人工兼容 share URL | 是 | `--execute` |
| `panlib-organize` | source/target/title/IMDb/year/quality/mode | 是 | `--execute` |
| `panlib-library auth-status` | 无 | 是 | 无 |
| `panlib-library auth-store` | stdin 凭证 JSON | 否 | 写入当前安全凭证后端 |
| `panlib-library list` | `--path` 绝对云端目录 | 是 | 无 |
| `panlib-library search` | `--keyword`, 可选 `--path`/`--dir` | 是 | 无 |
| `panlib-library meta` | `--path` 或 `--fsid` | 是 | 无 |
| `panlib-library archive` | `--source`, 可选 `--archive-dir`/`--new-name` | 是 | `--execute --plan-ref` |
| `panlib-library migrate` | `--source`, `--target-dir`, `--new-name` | 是 | `--execute --plan-ref` |
| `panlib-master query` | `--title`, `--year` | 是 | 无 |
| `panlib-master record` | `--title`, `--year`, `--source`, `--evidence` 或 `--no-evidence` | 否 | 追加本地台账（不触网盘） |
| `panlib-master verdict` | `--title`, `--year` | 是 | 无 |
| `panlib-plan` | `list` / `show --task` | 是 | 无（纯规划，不做 I/O） |
| `panlib-lib` | `find` / `verify`（可选 `--type movie`） | 是 | 无 |
| `panlib-share` | `browse` / `select` | 默认 | `select --execute` |
| `panlib-run` | `probe`/`selfcheck`（只读）；`transfer-select`/`organize-season`/`archive`/`sweep-empty`（写网盘） | 默认 | 写类子命令内建重试 |
| `panlib-audit` | `--path` 片库根，可选 `--severity` | 是 | 无 |
| `panlib-container` | `rename --source --new-name` | 默认 | `--execute --plan-ref` |

`panlib-master` 是**母版发行史判定**算子，回答「这部片子官方到底发行过多高分辨率」，
用于在升级画质前排除软件超分的假 4K。它**自己不联网**：证据检索由 Agent 层用
`web_search`/`web_extract` 执行，本 CLI 只给检索指引、记录证据句、给出判定。
台账写在 `runtime/master_lookup.jsonl`，可用 `PANLIB_MASTER_LEDGER` 重定向（测试用）。
同一片名 24 小时内已有记录直接复用，避免重复检索。
证据冲突时返回 `CONFLICTING_EVIDENCE` 并非零退出，**不自动取最大值**。

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
5. `.ass/.srt/.ssa/.sub/.sup/.vtt/.idx` 外挂字幕随正片移动；简体/繁体标记分别规范为
   `.zh-Hans`/`.zh-Hant`。电影整理不接收任何图片、海报、剧照、NFO、TXT、PDF
   或阅读说明文件；它们不出现在 organize actions 中。
6. 默认保留源目录；旧版或空残留目录另通过 `panlib-library archive` 生成移动计划。

### 统一影视命名契约

电影、剧集、动漫、纪录片、网剧及配置新增的所有影视类型使用同一决策模型：**类别提供默认类型根目录，
宇宙和系列决定可选父层，形态只决定内容单元和文件名模板**。`category` 选择 `Movies`、
`TV shows`、`动漫`、`Documentary`、`网剧` 或显式配置根；`layout` 只能是
`single`、`episode`、`season` 之一。
`/我的资源/<类型目录>/...` 与 `/apps/bdpan/片库/<类型目录>/...` 使用相同相对结构。

通用路径公式为 `类别根 / [分组节点 × 任意层] / 内容节点 / 文件`。标准化字段为：

```json
{
  "category": "movie | tv | anime | documentary | webdrama | configured",
  "layout": "single | episode | season",
  "groups": ["最外层分组名", "…", "最内层分组名"],
  "item": "内容单元目录名",
  "canonical_title": "内容规范名",
  "year": "YYYY",
  "media_id": "ttXXXXXXX",
  "season": null,
  "episode": null,
  "quality": "2160p",
  "extension": "mkv"
}
```

`groups` 按从外到内的顺序列出每一层分组节点名，**层数不限、无封闭名单**。分组节点以
`.{series}` 结尾；不带该后缀的是内容节点，其中只放媒体文件与外挂字幕。没有分组时传空数组。
CLI 根据 `--production-country`、`--title-zh`、`--title-en` 选出**内容规范名**：中国制作选中文，
非中国制作选英文，所有类别执行同一规则。

- `single`：内容单元 `{内容规范名}.{年份}.{IMDb ID}`；主媒体文件
  `{内容规范名}.{年份}.{清晰度}.{扩展名}`。
- `episode`：内容单元 `{作品规范名}.Sxx`；主媒体文件
  `{内容规范名}.SxxExx.{imdb-IMDb ID}.{清晰度}.{扩展名}`。
- `season`：内容单元同 `episode`；主媒体文件
  `{内容规范名}.Sxx.{imdb-IMDb ID}.{清晰度}.{扩展名}`。
- 外挂字幕与主媒体文件同主名，仅在扩展名前增加可确定的语言标签。
- Loki 使用 `TV shows/Loki.{series}/Loki.S01/` 与 `TV shows/Loki.{series}/Loki.S02/`，
  即 `Loki.{series}/Loki.S01`、`Loki.{series}/Loki.S02`；剧集一律进 `TV shows/`。
  同一层级规则适用于所有影视类型。

#### manifest v1 与严格身份

分组节点没有封闭名单，`groups` 数组的每一项都按普通分组名校验。中国制作使用中文正式片名，
非中国制作使用英文正式片名。字面例子：`The Batman.2022/` 内为
`The Batman.2022.{imdb-tt1874999}.1080p.mkv`；`Loki.{series}/Loki.S01/` 内的单集为
`Loki.S01E01.{imdb-tt1286039}.1080p.mkv`，整季文件为
`Loki.S02.{imdb-tt1286039}.1080p.mkv`。

新的多条目或拆分目录使用 **manifest v1**。每个 item 至少保留并校验精确
`source_path`、可用 `fs_id`、`size`、`layout`、规范标题、年份/季集、IMDb 和清晰度；文件名不能确定电影身份。
`--manifest-file PATH` 的 plan-only 返回 `plan_ref`；执行必须使用相同 manifest、精确 `--plan-ref HASH`
并在第一次写入前重新读取源/目标。现有平铺目录不静默重排，必须先生成新的 manifest 或 legacy hierarchical plan，
再按正常 postcondition 验收。

纯数字集名只允许 `--expected-episodes N` 严格契约：视频 stem 必须完整覆盖 `1..N`、季号必须明确、
不得混入已解析集号；CLI 不按文件顺序猜测季号或集号。用户普通更新/整理请求是端到端任务，不可停在
`plan-only`；任一计划或执行返回失败或 `partial`，先重新读取当前状态并生成新计划，不能跳过后续整理或归档。
本契约不引入覆盖、删除、自动重试或自动回滚，也不允许直接调用 `bdpan`。

`target-dir` 叶子名和文件名必须精确符合相应模板；任意自定义叶子名在第一次 bdpan 读取前被拒绝。
`episode` 缺少季号或集号、`season` 缺少季号、类别根未配置或身份不唯一时返回 `INVALID_ARG`。

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
- `archive` 默认 plan-only，要求绝对精确源；`--archive-dir` 可选，省略时由 `--source` 自动推导
  同根归档目录。`/我的资源/...` 固定映射到 `/我的资源/_已归档_待删除`，
  `/apps/bdpan/片库/...` 固定映射到 `/apps/bdpan/片库/_已归档_待删除`；显式传入跨根路径
  返回 `INVALID_ARG`。执行时必须回传 `plan_ref`。写前
  再读源/目标并拒绝目标冲突，唯一写请求必须是
  `file_move(async=0,ondup=fail,filelist=[{path,dest,newname}])`。写后重读父目录和归档目录，
  只有源路径消失、目标名称唯一存在才返回 `postcondition.status=verified`。
- `migrate` 是唯一允许的**受限跨根迁移**：`--source` 必须是 `/我的资源/Movies` 下的精确媒体文件，
  `--target-dir` 必须是 `/apps/bdpan/片库/Movies` 下的规范电影容器，`--new-name` 为单个目标文件名。
  计划不写入；执行必须带回 `plan_ref`，仅在容器缺失时先 `make_dir(rtype=0)`；容器已存在时只能
  追加一个不重名媒体文件，再
  `file_move(async=0,ondup=fail,filelist=[{path,dest,newname}])`，最后验证源消失且目标唯一。
  不移动目录、不覆盖、不删除，**不得开放任意全盘移动**；已整理目录由上层逐项迁移媒体文件，
  残留目录仍使用同根 `archive`。
- 不提供 `file_delete`/`delete`；归档目录由用户人工审核后手动删除。任何网络、权限、
  过期或验收失败均停止，不自动重试。

## 重试规则

- doctor/search/extract/verify 的只读 `NETWORK` 失败：由用户决定是否重试。
- transfer/organize 只要已进入 `--execute`：不自动重试，先重新读取现状并展示给用户。
