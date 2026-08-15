# 发布候选验证证据

验证日期：2026-08-09 至 2026-08-10（Asia/Shanghai）

## 本地发布候选

以下本地门禁在仓库唯一源码目录执行；测试与日志不输出 Token、分享链接、提取码或账号正文：

| 验证 | 结果 |
|---|---|
| `.venv/bin/pip check` | 通过，无损坏依赖 |
| `.venv/bin/python -m unittest discover -s tests -p 'test*.py'` | 174/174 通过 |
| `.venv/bin/python -m compileall -q panlib bin vendor/seedhub-cli` | 通过 |
| 所有公开 CLI `--help` | 通过 |
| `bash -n` 检查 setup/login/doctor/privacy 脚本 | 通过 |
| `./scripts/privacy-guard --whole-tree` | 通过 |
| `PANLIB_NETWORK_SKIP=1 ./bin/panlib-doctor` | 顶层 `status=ready`，network=`skipped` |
| `git diff --check` | 通过 |

测试包含：配置优先级、路径包含、严格命名、stdout/stderr 脱敏、SeedHub 直链/QR fixture、确定性候选排序、OAuth/Keychain、可替换 `external-command` 凭证接口、官方 MCP SDK bridge、resource-id/share-ref 安全交接、transfer/organize/archive plan-first、写前冲突与 TOCTOU、写后歧义、部分失败、无删除归档、文档契约和隐私门禁。

## 2026-08-11 分层与 manifest 回归

| 验证 | 结果 |
|---|---|
| `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v` | 254/254 通过 |
| `tests.test_media_manifest tests.test_organize_cli` | 80/80 通过 |
| Skill `quick_validate.py` | `Skill is valid!` |

本轮新增覆盖：宇宙/系列/作品/季层级、严格纯数字集号、manifest v1 精确源身份、
`plan_ref` 重建与漂移拒绝、父子目录创建顺序、源名/目标名交叉冲突、动作级 `fs_id`/`size`
复核、mkdir/mv/rename 部分失败和多目标写后身份验收。这是本地 fake/契约回归，本轮没有执行真实网盘写入。

## 层级与 manifest v1 验证边界

公共层级为 `类别根 / [分组节点 × 任意层] / 内容节点 / 文件`。分组节点以 `.{series}` 结尾，
**层数不限、无封闭名单**；不带该后缀的是内容节点。manifest 用 `groups` 数组按从外到内声明分组层。
中国制作使用中文正式片名，非中国制作使用英文正式片名。字面例子包括
`The Batman.2022/The Batman.2022.{imdb-tt1874999}.1080p.mkv`、
`Loki.{series}/Loki.S01/Loki.S01E01.{imdb-tt1286039}.1080p.mkv` 和
`Loki.{series}/Loki.S02.{imdb-tt1286039}.1080p.mkv`。

manifest v1 验证每项精确 `source_path`、可用 `fs_id`/`size` 和规范化元数据；文件名不能确定电影身份。
`--manifest-file` plan-only 必须产生 `plan_ref`，执行必须带同一 manifest 和精确 `--plan-ref`，并在写入前重读状态。
现有平铺目录不静默重排，必须重新生成 manifest 或 legacy hierarchical plan 并做 postcondition 验收。
纯数字集名只在 `--expected-episodes N` 下接受完整 `1..N`、明确季号且无混合集号；CLI 不按顺序猜测季号或集号。
普通更新或整理请求不可停在 `plan-only`；计划或执行失败/`partial` 时必须重新读取当前状态并生成新计划。
验证边界明确不覆盖、不删除、不自动重试、不自动回滚，也不直接调用 `bdpan`。

## 真实单片链路

2026-08-09 在用户明确授权的单片范围内，以《云中漫步》完成 macOS 真实验收：

1. 官方 MCP 读取并定位旧版资源；未做无差别整盘扫描。
2. SeedHub 搜索得到单片资源，多候选按固定规则选中蓝光 REMUX 候选；分享只读探测为 `valid`、顶层单项。
3. `panlib-transfer` 计划、确认、单次执行后，写后验收得到唯一 `source_dir`。
4. `panlib-organize` 当次历史验收曾将视频、简繁 SUP 字幕和海报整理到 IMDb 规范目录；现行规则已改为只纳入主视频和外挂播放字幕，图片及说明文档留在源目录并进入同根待删除归档区。
5. 官方 MCP `file_move` 将旧版资源和不纳入片库的截图残留移至待人工审核区，源消失、目标唯一存在，`postcondition.status=verified`；没有调用 delete。

整理过程中曾在部分旁车文件已移动后遇到一次外部目录读回异常。流程按 fail-fast 停止，先用独立 MCP 读取现状，再由新的 plan 完成剩余海报移动；没有自动重试写操作，也没有重复转存。

## 可替换凭证接口与第二部单片链路

同日完成凭证 provider 接口后，以《遇见你之前》再次执行独立真实验收：

1. 官方 MCP 精确读取旧版单片，Apps 规范目标写前确认不存在。
2. SeedHub 搜索得到 9 个候选，`preset-quality-v1` 自动选中 4K HDR/DV、外挂双语字幕候选；分享只读探测为 `valid`、顶层单项。
3. transfer 计划、确认、执行及唯一新增目录验收通过；organize 将 2160p 视频和简体 ASS 字幕规范命名到 IMDb 目录。
4. 旧版资源通过 MCP `file_move` 归档并验证；Apps 空源第一次执行因归档目标状态变化被 `plan_ref` 拒绝，未写入。重新只读生成计划后归档并验证；没有调用 delete。
5. 该真实链路仍在 macOS Keychain 上执行。`external-command` 的安全进程协议、错误边界和调用接线由自动化测试覆盖，但未宣称 Windows/Linux 实机安全存储已通过。

## 《中国机长》命名修正与双归档验收

2026-08-10 按现行命名和内容规则完成真实整理并只读回验：

1. 中国制作的电影使用官方中文片名；活动片库目录为 `中国机长.2019.tt10218664`，主视频为 `中国机长.2019.2160p.mp4`。
2. 活动目录只保留主视频；海报、图片、NFO 等非播放内容不进入规范片库。
3. “我的资源”旧版视频留在同根 `/我的资源/_已归档_待删除/`；Apps 片库旧英文目录、海报和历史残留留在同根 `/apps/bdpan/片库/_已归档_待删除/`，没有跨根归档。
4. 最终 MCP 回读确认：`/我的资源/Movies` 不再有活动旧版；活动 Apps 目录只含 1 个 2160p 视频；两个待删除归档区均存在对应旧内容。全程没有调用 delete。

## 证据边界

- 单片真实验收只证明 2026-08-09 当时的 SeedHub、百度分享、bdpan 与官方 MCP 链路可用，不保证外部服务持续可达。
- 当前不支持无界整盘扫描或自动删除；Windows/Linux 仅有外部安全凭证代理接口，没有仓库内置实现或实机跨平台验收。
- macOS 授权存入系统 Keychain；只有 Keychain 缺失或过期时才由用户在可见终端完成浏览器授权，后续非交互检查由 Agent 执行。
- Git 可达历史、Gitleaks 和 GitHub Actions 必须在公开发布提交上再次通过，远端 CI 才是清洁检出的最终证据。

发布后可在 [GitHub Actions](https://github.com/Ming-Sir-69/ai-netdisk-assistant/actions) 查看远端验收。
