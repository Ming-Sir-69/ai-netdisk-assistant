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
当前采用 macOS 优先策略。仓库不捆绑 Windows/Linux 系统安全存储实现；跨平台开发与
实机兼容测试暂缓，但保留 `external-command` 接口契约和自动化测试，便于后续继续而不遗忘。

`list`、`search`、`meta` 只读；`archive` 仅调用官方 `file_move`，参数固定为
`async=0`、`ondup=fail`、`filelist=[{path,dest,newname}]`。归档默认 plan-first，执行前
重读精确源/目标并绑定 `plan_ref`，执行后必须验证源路径消失且目标名称唯一存在。同根归档
由源路径确定：我的资源与 Apps 片库各用自己的 `_已归档_待删除`，跨根请求直接拒绝；没有
delete CLI 或 delete MCP 调用，归档内容由用户人工审核后手动删除。MCP 路径允许官方全盘
绝对 POSIX 根（包括 `/apps/bdpan` 与 `/我的资源`），但仍拒绝遍历、反斜杠、控制字符和
模糊目标。

`panlib-library migrate` 是唯一的**受限跨根迁移**入口：只允许一个精确媒体文件从
`/我的资源/Movies` 迁入 `/apps/bdpan/片库/Movies` 下的已验证电影容器。它先调用
`make_dir(path=<目标容器>,rtype=0)`；目标已存在时只允许追加一个不重名的媒体文件，再调用
`file_move(async=0,ondup=fail)`。计划与执行均重读源/目标并绑定 `plan_ref`，写后验证源消失、目标唯一存在。不得开放任意全盘移动，不移动目录、
不覆盖、不删除。已整理目录由上层逐个枚举视频与外挂字幕迁移，残留源目录仍走同根 archive。

organize 的媒体边界只有主视频和播放器可加载的 `.ass/.srt/.ssa/.sub/.sup/.vtt/.idx`
外挂字幕；文件名中的简体/繁体标记稳定映射为 `.zh-Hans`/`.zh-Hant`。
不接收任何图片、海报、剧照、NFO、TXT、PDF 或阅读说明文件；它们随残留目录同根归档。
统一影视命名契约不再依赖 Agent 翻译：CLI 接收制片国家和中英文正式片名，
中国制作选中文，非中国制作选英文，得到**内容规范名**。

电影、剧集、动漫、纪录片、网剧及以后新增的所有影视类型共用一个**递归**层级模型：**类别提供默认类型根目录，
分组节点可嵌套任意层，形态只决定内容单元和文件名模板**。通用公式是
`类别根 / [分组节点 × 任意层] / 内容节点 / 文件`。标准化决策对象至少包含：

```json
{
  "category": "movie | tv | anime | documentary | webdrama | configured",
  "layout": "single | episode | season",
  "groups": ["最外层分组名", "…", "最内层分组名"],
  "item": "内容单元目录名"
}
```

类别默认映射 `Movies/TV shows/动漫/Documentary/网剧` 或显式配置目录；分组节点以
`.{series}` 结尾，**层数不限、无封闭名单**，漫威与 DC 只是普通分组节点。
没有分组就省略该层，不创建空占位目录。形态只取 `single`、
`episode`、`season`。`/我的资源/<类型目录>/...` 与 `/apps/bdpan/片库/<类型目录>/...`
使用相同相对结构。`single` 的内容单元和主媒体文件包含年份，`episode` 以 `{作品规范名}.Sxx`
为内容单元且文件包含 `SxxExx`，`season` 文件包含 `Sxx`；外挂字幕继承对应主媒体文件主名。
Loki 的目标是 `TV shows/Loki.{series}/Loki.S01/` 与 `TV shows/Loki.{series}/Loki.S02/`，
即 `Loki.{series}/Loki.S01`、`Loki.{series}/Loki.S02`；剧集一律进 `TV shows/`。
这不是 Loki 专例，同一层级判断适用于所有影视类型；新增类别只增加默认根映射，不复制命名逻辑。

公共 **manifest v1** 契约用 `groups` 数组声明分组层，**没有封闭名单**；旧的 `universe`
单值字段已于 2026-08-15 废止。中国制作选中文正式片名，非中国制作选英文正式片名。电影例子是
`The Batman.2022/The Batman.2022.{imdb-tt1874999}.1080p.mkv`；剧集例子是
`Loki.{series}/Loki.S01/Loki.S01E01.{imdb-tt1286039}.1080p.mkv`，整季文件是
`Loki.{series}/Loki.S02.{imdb-tt1286039}.1080p.mkv`。

manifest item 必须绑定精确 `source_path`、可用 `fs_id`/`size` 和规范化元数据；文件名不能确定电影身份。
`--manifest-file` plan-only 返回 `plan_ref`，执行用同一 manifest 和精确 `--plan-ref`，写入前重读源/目标。
现有平铺目录不静默重排，必须生成新的 manifest 或 legacy hierarchical plan，并重新做 postcondition 验收。
纯数字集名只在 `--expected-episodes N` 下接受完整 `1..N`、明确季号且无混合集号；CLI 不按顺序猜测季号或集号。
用户普通更新/整理请求是端到端任务，不可停在 `plan-only`；计划或执行失败/`partial` 时先重新读取当前状态并生成新计划。
该流程不覆盖、不删除、不自动重试、不自动回滚，也不直接调用 `bdpan`。
organize 不再移除源目录，兼容参数 `--remove-empty-source` 直接
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
