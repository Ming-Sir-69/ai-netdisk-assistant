---
name: ai-netdisk-assistant
description: >-
  Use when a user asks to install this repository, find, add, update, migrate,
  or organize movie, TV, anime, documentary, web drama, or other media
  resources through SeedHub and Baidu Netdisk.
allowed-tools: Bash, Read, AskUserQuestion
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
- macOS 上通过官方百度网盘 MCP 读取全盘目录、搜索和读取元数据；旧资源仅能通过
  `panlib-library archive` 以 `file_move` 归档到指定目录，人工审核后再手动删除。
- `panlib-library migrate` 将 `/我的资源/Movies` 中一个已精确定位的媒体文件迁入 Apps
  片库的规范电影目录；它不是通用全盘移动。
- 可替换凭证接口默认使用 macOS Keychain；其他系统只能显式接入受控
  `external-command` 安全代理，不提供明文文件回退。

### 通道能力矩阵（唯一权限判定）

| 通道 | 可读取 | 可写入 | 硬边界 |
|---|---|---|---|
| 官方百度网盘 MCP（`panlib-library`） | `/我的资源`、`/apps/bdpan` 等全盘绝对路径的目录、搜索和元数据 | 两个网盘根各自的同根 `archive`；受限 `migrate` 把 `/我的资源/Movies/**` 的精确媒体文件移入 Apps 规范容器 | 不删除、不覆盖、不执行分享转存、不提供任意跨根移动 |
| bdpan wrappers（`panlib-transfer` / `panlib-organize`） | 百度分享清单和 `/apps/bdpan` 内状态 | 分享转存，以及 `/apps/bdpan` 内建目录、移动和重命名 | 不能读取 `/我的资源` 或全盘；不能删除或任意跨根移动 |
| SeedHub provider | 资源站搜索、详情和百度分享引用 | 无 | 不读取或写入个人网盘 |

`/apps/bdpan` 是 bdpan wrappers 的 OAuth/写入范围，不是 MCP 的读取范围。不得把这一限制
泛化到 MCP 的全盘读取能力；权限判断只查本矩阵和 `preflight` 的实际结果。

当前不支持：整盘盘点、定期任务、其他网盘写入、磁力下载、实时豆瓣/OMDb 查询。对“整理我的网盘”这类宽泛请求，先请用户给出影视关键词或精确 `source_dir`，不扫描整盘，不直接拼接网盘命令。

## 对话初始化与模式选择

每一轮新对话先把用户请求归为一级“使用类”或“测试类”。这是为了让用户用一句自然语言
触发完整范围，而不是要求用户记住 CLI 或把每个后续步骤逐条交代。

### 一级：使用类（默认展开）

| 用户表达 | 识别模式 | 不包含 |
|---|---|---|
| `更新《这个杀手不太冷》`、`替换《…》` | **更新影视**（默认完整更新） | 无；必须走识别、搜索比较、转存、整理、同根归档和最终验收。 |
| `找《…》资源`、`比较《…》版本` | **找资源** | 不转存、不整理、不归档。 |
| `转存这部资源`、`把这个分享存进片库` | **转存资源** | 不整理、不归档。 |
| `整理这个目录：/…` | **整理已有资源** | 不搜索、不转存。 |
| `归档这个目录：/…` | **归档旧资源** | 不删除、不处理其他目录。 |

### 一级：测试类（默认折叠）

用户明确说“测试、验证、验收、性能计时或排查工作流”时才进入**测试类**。先确认测试目的和
样本，再按需展开步骤、计时、日志和验收；普通“更新/找/整理”请求不得误入测试类。

### 初始化动作与模式卡

1. 用户表达已能映射到上表时，直接采用该模式；意图不明确才展示五条使用类入口与一条测试类入口。
2. 每次都先用一行**模式卡**复述范围：`模式卡：<使用类或测试类> / <模式>｜对象：<片名或路径>｜默认检索：<路径>｜下一步：<动作>`。
3. `更新《这个杀手不太冷》` 进入默认完整更新。先在 `/我的资源` 和 `/apps/bdpan/片库` 按片名定位旧资源和已存在版本；在搜索层报告实际命中路径。两处都找不到再询问用户旧资源路径，或确认本次是新入库。不得因用户没有预先给出路径而把更新缩减为只搜索。
4. 模式卡只声明业务范围，不取代后续 CLI 的 plan、执行和写后验收信息。默认使用风险分级确认：
   可恢复、无冲突且不扩大权限的动作由 Agent 自动连续执行；只有不可逆、权限变化、目标冲突、
   歧义或验收异常才暂停询问。

## 安装状态机

所有 Python CLI 必须从仓库根目录使用项目解释器 `.venv/bin/python` 启动；不得直接运行
`python3 bin/...`，也不得依赖 shell 是否已激活虚拟环境。

0. 先要求用户在 Codex、WorkBuddy 或当前 Agent 宿主中开启完全访问，使进程可访问
   macOS 钥匙串、百度 MCP 和百度网盘网络。不根据平台按钮文案猜测是否已开启；
   初始化末尾必须运行 `./scripts/preflight.sh` 做实际能力验证。
1. 已有仓库就复用现有目录；没有时只 clone 用户给出的 URL 一次。
2. `cd` 到仓库根目录，运行 `./scripts/bootstrap.sh`。
3. Python 缺失/低于 3.13，或现有 `.venv` 无效：停止，请用户安装或修复 Python 3.13+，然后重跑审计；不在未支持解释器上安装依赖。
4. 缺少 Python 依赖：`requirements.txt` 已固定版本且用户已明确启动安装/使用流程时，Agent 可自动运行
   `./scripts/bootstrap.sh --install-deps`；只有依赖未固定、需要外部安装器或网络范围超出清单时才暂停询问。
5. 缺少 bdpan：展示并打开 `https://github.com/baidu-netdisk/bdpan-storage` 或官方 `skills/baidu-drive/scripts/install.sh` 页，停止等待用户安装。不静默下载或执行外部安装器。
6. 未授权：运行 `./scripts/login.sh`。用户自行阅读提示、在百度官方页登录、将 32 位授权码粘贴到终端并回车。Agent 不索要授权码。
7. 运行 `./bin/panlib-doctor`。仅顶层 `status=ready` 可继续；其他状态按 `next_steps` 停止或交给用户。
8. 运行 `.venv/bin/python bin/panlib-library auth-status`。macOS 已有有效授权（保存在 Keychain）时继续，且不得再次打开浏览器。仅当 Keychain 未配置或过期时，给用户 `scripts/authorize_mcp_macos.py` 的绝对路径和唯一命令，让用户在自己可见的终端手动运行；完整回调只粘贴到脚本的隐藏输入，不发送给 Agent。其他系统只有在用户已配置 `external-command` 安全代理时继续；仓库不创建明文凭证文件。授权后非交互检查由 Agent 执行。

   **`reason=missing` 分流（先诊断，不要让用户重授权）**：自 2026-08-11 起账户解析用 `_current_user()`（`$USER` → `pwd.getpwuid` → getuser 兜底），WorkBuddy 沙盒 `LOGNAME=root` 不再误判。若仍报 missing，按序只读排查：
   1. `security find-generic-password -a "$USER" -s "ai-netdisk-manager.baidu-mcp.oauth"`（不带 `-w`）——有条目输出 = 凭证存在，是账户名不匹配；
   2. 比对 `echo "USER=$USER LOGNAME=$LOGNAME"` 与条目的 `acct` 属性；
   3. 账户不一致时用 `PANLIB_KEYCHAIN_ACCOUNT=<条目的 acct>` 显式指定后重测；
   4. 只有确认条目**不存在或 expired** 时才给授权脚本。**禁止**在 missing 时直接让用户重授权——若账户不匹配，重授权会把凭证写进错误账户，问题依旧。
9. 运行 `./scripts/preflight.sh`。只有 `status=ready` 才进入业务流程；`blocked`
   说明宿主完全访问、安全凭证或百度 MCP 根目录读取至少有一项不可用。

## 业务状态机

用户提出“更新某个影视内容”时，默认完整主链路是：只读识别旧资源 → SeedHub 搜索与自动选择 →
transfer 计划/执行/验收 → organize 计划/执行/验收 → 按来源根分别 archive 旧资源和 Apps
残留 → 最终读回四个路径。完整更新模式自动执行上述可恢复写入，**无需逐阶段确认**；每一步
仍必须先生成计划、重检状态、使用 `ondup=fail`，并在写后验收。只有风险分级规则命中时才暂停。

### 风险分级确认：自动执行与暂停（唯一审批判定）

本表是唯一审批判定来源；后文各阶段只定义参数、顺序和验收，不新增人工确认点。

| 判定 | 可观察条件 | Agent 动作 |
|---|---|---|
| **自动连续执行** | 用户进入 `更新影视`、`转存资源`、`整理已有资源` 或 `归档旧资源` 模式；计划身份唯一、无冲突、不覆盖，且操作属于通道矩阵允许的范围 | 该模式即视为已明确授权该模式定义范围内的写入。自动完成只读定位、IMDb/SeedHub 搜索、固定规则候选比较、无冲突转存、视频与外挂字幕整理、受限跨根迁移、同根 `file_move` 归档、最终读回和恢复台账；旧版目录、空壳目录和未入库残留也自动同根归档。不得再次要求逐阶段确认。 |
| **暂停询问** | 首次或过期授权；权限变化或安全凭证后端变化；源/目标身份不唯一；目标冲突、需要覆盖或只能二选一丢弃一个版本；非受限跨根迁移；删除或其他不可逆操作；计划过期；写后验收失败；`AUTH`、`PERMISSION`、`ambiguous`、`unverified` 或 `partial` | 保留现场，报告精确阻塞点和唯一下一步，不扩大权限、不重试写操作。 |
| **保持只读** | 用户只进入 `找资源` 模式，或明确要求只读检查/测试而未选择写入范围 | 只完成该模式定义的只读工作；如需转存、整理或归档，再切换到对应使用模式。 |

`panlib-library migrate` 仍是唯一的受限跨根迁移：只接受精确媒体文件和规范 Apps 容器；目录源、
任意其他跨根路径、冲突或计划漂移会命中上表的暂停条件。

### 双通道落位

从第一性原理看，现有权限已足够完成完整更新：MCP 负责 `/我的资源` 读取与同根归档，
转存 CLI 负责分享转存，整理 CLI 负责 Apps 内建目录、移动和重命名；没有删除和覆盖权限反而
保留了可恢复边界，**不需要新增网盘权限**。双通道是落位策略，不是新增授权范围。

#### 快速通道

只有当转存 CLI 明确提供确定性的 `--target-dir`/直达落位能力，且转存前只读清单确认“单片、媒体身份唯一、
无目标冲突、无不明文件”时启用。先使用 `Movies/<规范目录>.importing.<run_id>` 作为处理中目录，
直接转存并原地规范命名；写后验收通过后再将处理中目录变为正式目录。旧的 `/我的资源` 只在新目录
验收通过后归档。处理中失败只留下可定位的 importing 目录，不进入 `_已归档_待删除`。

当前版本转存直达能力未提供；Agent 不得伪造 `--target-dir` 参数或把类别目录当作快速通道，必须自动
退回兼容通道。

若未来实现显式处理中隔离，处理中目录固定写成
`/apps/bdpan/片库/_待整理/<run_id>`；它只是可恢复的工作区，不是归档区。

#### 兼容通道

使用当前已验收路径：转存到 `/apps/bdpan/片库/Movies` → 读取真实 `source_dir` → 创建规范目录并
移动/重命名视频与外挂字幕 → 对仍有内容的转存源做同根 `file_move` 归档。合集、目录型分享、清单
不完整、含不明文件或任何匹配歧义都走此通道。不得把转存源直接转入 `_已归档_待删除`，也不得
把处理中状态标记为可删除。

### 既有资源迁入 Apps（受限跨根入口）

当用户要求把 `/我的资源/Movies` 内已经保存的影视整理到 Apps 片库时，使用
`panlib-library migrate`，而不是修改 `BDPAN_BASE` 或直接调用 MCP。它只接受一个精确媒体文件，
目标只能是 `/apps/bdpan/片库/Movies` 下的规范电影容器；容器缺失时先 `make_dir(rtype=0)`，
已存在时只追加一个不重名媒体文件，再 `file_move(async=0,ondup=fail)`，并以 `plan_ref`、写前重读和写后源消失/目标唯一验收闭环。
不得开放任意全盘移动，不移动目录、不覆盖、不删除。已整理目录由 Agent 逐项迁移主视频和外挂字幕；
源目录残留只按同根 archive 归档。

### A. 只读候选链

0. 从 IMDb 或等价的结构化元数据取得制片国家、中文正式片名和英文正式片名。
   中国制作时“内容规范名”取中文，非中国制作取英文；将制片国家、
   `--title-zh` 和 `--title-en` 交给 CLI 选择，不让 Agent 自由翻译。

1. `.venv/bin/python bin/panlib-search --keyword "<keyword>" --type <all|movie|tv|anime> --limit <n>`
2. 用户选择或请求中已唯一确定候选后，获取返回的 `id`。
3. `.venv/bin/python bin/panlib-imdb --title "<title>"`；本地表无结果就请用户提供 `tt...`，然后用 `--imdb-id`验证。
4. 用 `.venv/bin/python bin/panlib-transfer --resource-id <id> ...` 生成转存计划，**不加** `--execute`。transfer 在自己的进程内解析链接，不把 URL/提取码返回给 Agent。
   resource-id 路径会在计划生成前通过官方 `bdpan transfer list --json` 做只读探测；只有 `share_probe.status=valid` 才继续返回计划。过期分享返回 `NOT_FOUND/share_status=expired`，网络、认证、权限或未知响应为 `share_status=unverified` 并停止。
5. 多个百度候选由 transfer 的 `preset-quality-v1` 固定策略自动排序，依次比较分辨率、片源、HDR、音轨、字幕和大小，完全相同才按资源站原始顺序稳定选择。Agent 不询问用户；只有用户明确覆盖时才传 `--link-index <index>`。计划必须回传 `selection.strategy`、候选数和脱敏的 `selection.selected`，其中不得包含 URL 或提取码。
6. `NOT_FOUND`、`NETWORK`、`PARSE` 或任何其他非零退出：停止并报告，可请用户选择另一资源；不自动进入写操作。

### B. 转存：计划 → 自动执行（风险命中才暂停）

1. 运行 `.venv/bin/python bin/panlib-transfer` 并传入 `--resource-id`、可选 `--link-index`、type、title、IMDb ID、year、quality，**不加** `--execute`。
2. 必须确认返回 `meta.mode=plan-only` 和 64 位小写十六进制 `share_ref`，并检查 `dest_dir`、动作类型、
   影响范围和验收方式。若未命中风险分级规则，计划通过后直接执行；计划成功本身仍不等于已转存。
3. 使用相同业务参数，加计划返回的 `--share-ref <share_ref>` 和 `--execute`。transfer 会重新解析；候选或
   URL 发生漂移时必须停止并重新计划，不能把漂移当作可自动确认事项。
4. 只有结果同时满足 `executed=true`、`postcondition.status=verified`、`organize_ready=true`、`source_dir` 非空，才可进入整理。
5. `postcondition.status=ambiguous|unverified`、`partial`、空 `source_dir` 或失败：立即停止。**不得猜测 `source_dir`**，不得自动重试写操作。

### B+. 通用影视层级约束（强制；2026-08-15 起为递归模型）

所有影视类型共用同一条**递归**路径公式：

```
类别根 / [分组节点 × 任意层] / 内容节点 / 文件
```

1. **只有两种节点，靠后缀区分**：目录名以 `.{series}` 结尾即**分组节点**，其中可继续放分组节点或
   内容节点，**层数不限**；不带该后缀即**内容节点**，其中只允许媒体文件与外挂字幕，**不得再有子目录**。
   该判定是纯字符串判断——不看年份、不查名单、不依赖 Agent 常识，因此程序不会认错。
2. **类别根由配置提供**：`movie → Movies`、`tv → TV shows`、`anime → 动漫`、
   `documentary → Documentary`、`webdrama → 网剧`。新增类别只改配置，不改代码，也不临时猜路径。
3. **不存在“宇宙”这一特殊层**：漫威、DC 及任何其他聚合都只是普通分组节点，命名同样是
   `{分组名}.{series}`。**不得再维护“只允许两个宇宙”的封闭名单**——那是 2026-08-15 之前的僵化规则，已废止。
4. **内容节点两种形态**：单体用 `{内容规范名}.{年份}`；分季用 `{作品规范名}.Sxx`。文件夹一律不带 IMDB。
5. **深度不设上限**：`Movies/Marvel.{series}/Spider-Man.{series}/Spider-Man.Tobey.{series}/Spider-Man.2002/`
   是**合法**结构，不再要求拉平到三层。当内容在现有层级里理不清时，正确做法是**继续往下细分**。
6. **分组只在语义成立时建立**：存在一个可命名的自然分组（同一 franchise、同一重启线、同一分季作品）
   才建层。剧集一律建分组层（天然会增长），即使当前只有一季。不得创建空占位分组。
7. **程序不自行发明分组**：分组是语义判断，必须由 manifest 显式声明后才执行。CLI 只负责照清单精确
   执行与验收；判断力在 Agent 侧，确定性在 CLI 侧，两者不互相越界。
8. **剧集不留在电影分组内**：凡分季剧集（含动画剧集）一律进 `TV shows/`，按剧集契约整理。
   例：`TV shows/Loki.{series}/Loki.S01/` 与 `TV shows/Loki.{series}/Loki.S02/`，即相对片段
   `Loki.{series}/Loki.S01`、`Loki.{series}/Loki.S02`；而不是放在任何电影分组之下。

### B++. 公共 manifest v1 与身份契约

- **分组节点没有封闭名单**：manifest 用 `groups` 数组按从外到内的顺序显式声明每一层分组名，
  CLI 只校验命名合法性与层级自洽，**不校验分组名是否在某个预设清单里**。旧的 `universe`
  单值字段（只接受 `marvel`/`dc`）已于 2026-08-15 废止。
- 内容规范名必须遵循国家契约：中国制作使用中文正式片名，非中国制作使用英文正式片名。
  **IMDB 只在视频文件名上，文件夹一律不带 IMDB**。电影例子：文件夹 `The Batman.2022/` 内为
  `The Batman.2022.{imdb-tt1874999}.1080p.mkv`；国产《中国机长》文件夹 `中国机长.2019/` 内为
  `中国机长.2019.{imdb-tt10218664}.2160p.mp4`。剧集例子：作品层 `Loki/`、季目录
  `Loki.S01/`，单集文件为 `Loki.S01E01.{imdb-tt1286039}.1080p.mkv`；整季文件为
  `Loki.S02.{imdb-tt1286039}.1080p.mkv`。
- 新的多条目或拆分目录整理必须使用 **manifest v1**。每个 item 都绑定精确
  `source_path`、可用的 `fs_id`/`size` 和规范化元数据；文件名不能确定电影身份，
  不能用模型记忆、目录序号或数字前缀替代 IMDb/源身份。
- `--manifest-file` 的 plan-only 返回 `plan_ref`；执行必须提交完全相同的 manifest 和精确的
  `--plan-ref`，CLI 会先重读源与目标。现有平铺目录不会被静默重排，必须先生成新的 manifest
  或 legacy hierarchical plan，并按正常 postcondition 验收。
- 纯数字集名只有在 `--expected-episodes N` 严格契约下才允许：视频 stem 必须恰为 `1..N`、
  季号必须明确、不得混入已解析集号；CLI 不会仅按文件排序猜测季号或集号。
- 该流程不覆盖、不删除、不自动重试、不自动回滚，也不直接调用 `bdpan`。

### C. 整理：计划 → 自动执行（风险命中才暂停）

1. `source_dir` 只能来自上一步已验证输出，或用户显式给出的精确路径。
2. 运行 `.venv/bin/python bin/panlib-organize` 并传入 source/target/title/IMDb/year/quality/mode，**不加** `--execute`。
3. 检查完整 `actions`、源目录、目标目录、文件数和“该流程非事务，可能部分完成”。无冲突且不涉及删除时
   直接继续；命中歧义、覆盖或不可逆操作时暂停。
4. 用完全相同的参数加 `--execute` 且只执行一次。整理默认保留源目录；遗留旧目录按 D 生成归档移动计划。
5. 视频旁的 `.ass/.srt/.ssa/.sub/.sup/.vtt/.idx` 外挂字幕一并移动；文件名含简体/简中/`zh-Hans`/`chs` 时使用 `.zh-Hans`，含繁体/繁中/`zh-Hant`/`cht` 时使用 `.zh-Hant`。不接收任何图片、海报、剧照、NFO、TXT、PDF 或阅读说明文件；它们保留在源目录并随旧目录归档。
6. 源为空、文件名无法解析或发生冲突时停止，不创建、不删除。任何部分失败：报告 `error.details.completed` 与 `error.details.failed_action`，停止当前项及批处理；不自动重试、不猜测回滚。旧版 `--remove-empty-source` 会立即返回 `INVALID_ARG`，不能绕过归档流程。
7. 用户的普通更新或整理请求是端到端任务，不可停在 `plan-only`；仅在风险分级确认点暂停。任一计划或执行步骤返回失败或 `partial`，先重新读取当前状态并生成新计划，不能静默跳过整理或归档。

### D. 旧资源归档：自动移动（风险命中才暂停）

整理完成后若留下旧版或空残留目录，不调用删除接口。先用官方 MCP 只读确认源路径和归档目标：

```bash
.venv/bin/python bin/panlib-library archive \
  --source "/apps/bdpan/片库/Movies/旧目录" \
  --new-name "旧目录_旧版_待删除"
```

CLI 根据源路径自动选择归档根：`/我的资源/...` → `/我的资源/_已归档_待删除`，
`/apps/bdpan/片库/...` → `/apps/bdpan/片库/_已归档_待删除`；不得跨根归档。
可选 `--archive-dir` 只用于核对且必须等于自动结果。计划会绑定 `plan_ref`，并只生成一次
`file_move(async=0,ondup=fail)`。无冲突且同根时，使用完全相同的参数加 `--execute --plan-ref <plan_ref>`
自动移动；跨根、目标冲突或需要删除时暂停。CLI 在写前重读源/目标，写后按源路径消失和目标名称存在验收；
任何失败立即停止。归档目录中的内容由用户人工审核后再在百度网盘 App 中手动删除。

### E. Agent 可读恢复台账

运行日志是 Agent→Agent 的恢复台账，**不面向用户展示完整日志**，也不要求用户据此判断
文件去向。凡是 transfer、organize 或 archive 的计划、执行、部分失败和写后读回，都必须由
仓库的确定性日志模块追加私有 JSONL 事件；Agent 不手写临时日志代替该模块。

每个写入事件至少包含：`run_id`、事件时间、阶段、尝试次数、`source_path`、`target_path`、
文件身份（名称、fsid、size、mtime 中可获得的字段）、计划引用、`completed_actions`、
`failed_action`、执行状态、写后验收和 `recovery_read_paths`。失败事件还必须同时记录
`error_code`（恢复决策码）、`original_cli_code`（CLI 原始状态）和 `next_action`（唯一下一步）。
不得用其中任一字段替代另一个。可以记录资源 ID、IMDb ID 和
不含提取码的引用指纹；不得记录分享 URL、提取码、Token、Cookie 或账号正文。

#### 台账错误码

| `error_code` | 含义 | `next_action` |
|---|---|---|
| `JRN-001` | 台账不存在、不可读或找不到对应运行 | `bounded_relocate` |
| `JRN-002` | 台账 JSONL 或必需结构无效 | `stop_journal_invalid` |
| `JRN-003` | 缺少源、目标或文件身份，无法恢复 | `bounded_relocate` |
| `RCV-001` | 当前网盘读回与台账记录不一致 | `stop_state_mismatch` |
| `RCV-002` | 检测到部分写入 | `read_recovery_paths_and_replan` |
| `RCV-003` | 计划引用或写前状态已过期 | `regenerate_plan` |
| `RCV-004` | 精确路径或文件身份匹配不唯一 | `stop_ambiguous` |
| `RCV-005` | 写后验收未通过 | `stop_postcondition_unverified` |

处理同一影片的新对话、`partial`、`unverified` 或写入异常时：

1. 先按片名/IMDb ID/`run_id` 读取最近相关台账，取得 `recovery_read_paths` 和最后一个未完成阶段。
2. 只读重查这些精确路径及文件身份，使用“台账记录 + 当前网盘状态”决定重新计划、继续归档或报告完成。
3. 台账缺失或字段不全时：缺失记录 `JRN-001`，字段不全记录 `JRN-003`；只在默认库根做有界重新定位，**不得猜测文件去向**、重放旧计划或把部分完成说成完成。
4. 只有日志写后验收与当前读回一致，才继续下一写阶段；不一致时停止并记录新的恢复事件。

## 错误决策

| 状态 | 动作 |
|---|---|
| `AUTH` | 只运行 `scripts/login.sh`，然后 doctor；不查看账号正文 |
| `NETWORK` | 只读步骤可请用户决定是否重试；写入步骤绝不自动重试 |
| `PARSE` | 停止，报告外部页面契约变化；不修补正则后直接写入 |
| `INVALID_ARG` | 补全参数或处理冲突后重新生成计划 |
| `NOT_FOUND` | 区分资源、分享链接和源目录；不用“换关键词”处理空源目录 |
| `PERMISSION` | 停止并报告精确目标，不改到更宽范围 |
| `share_status=expired` | 报告分享已失效，不进入转存 |
| `share_status=unverified` | 报告只读探测未确认；按 `AUTH`/`NETWORK`/`PERMISSION`/`PARSE` 处理，不进入转存 |
| MCP `AUTH`/`expired` | 只运行 `panlib-library auth-status`，让用户完成官方授权；不读取 Token 正文 |
| `auth-status` 报 `reason=missing` | 先按启动检查第 8 步的「missing 分流」诊断（Keychain 条目存在性 + 账户名比对），确认真缺失/过期才让授权；禁止账户不匹配时重授权 |
| `ambiguous` / `unverified` 或上层验收标为 `partial` | 停止，不继续整理，不宣称完成 |

## 统一影视命名契约

电影、剧集、动漫、纪录片、网剧及以后新增的所有影视类型共用一个判断模型：**类别提供默认类型根目录，
宇宙和系列决定可选父层，形态只决定内容单元和文件名模板**。不得用“动漫必定分集”或
“纪录片必定单体”之类的类别猜测形态。

先把输入归一为下面的决策对象；使用 `layout` 单选值，避免多个真假字段互相矛盾：

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

- **内容规范名**：中国制作用中文正式片名；非中国制作用英文正式片名。电影、电视剧、动漫和纪录片
  都执行同一条国家判断，不让 Agent 自由翻译。
- **通用层级**：`类别根 / [分组节点 × 任意层] / 内容节点 / 文件`。分组节点数量不限、无封闭名单，
  判定与建层规则见 B+ 节。
- **类别根目录**：`movie → Movies`、`tv → TV shows`、`anime → 动漫`、
  `documentary → Documentary`、`webdrama → 网剧`；新增类别必须由配置提供根目录，不能临时猜路径。
- **两套网盘根使用同一相对结构**：`/我的资源/<类型目录>/...` 与
  `/apps/bdpan/片库/<类型目录>/...` 的类型目录、作品容器和文件模板完全一致。
- **内容单元**：`single` 使用 `{内容规范名}.{年份}/`（文件夹**不带 IMDB**）；`episode` 与 `season` 使用
  `{作品规范名}.Sxx/`。作品系列层聚合同一 franchise 或同一分季作品，不改变内容单元内部模板。
- **Loki 示例**：目标相对结构为 `Loki/Loki.S01`、`Loki/Loki.S02`，完整路径位于
  `Movies/Marvel Cinematic Universe/` 之下；同样的层级逻辑适用于所有影视类型。
- **主媒体文件**：`single` 使用 `{内容规范名}.{年份}.{imdb-IMDb ID}.{清晰度}.{扩展名}`；`episode` 使用
  `{内容规范名}.SxxExx.{imdb-IMDb ID}.{清晰度}.{扩展名}`；`season` 使用
  `{内容规范名}.Sxx.{imdb-IMDb ID}.{清晰度}.{扩展名}`。**IMDB 只出现在视频文件名，文件夹不带 IMDB。**
- **清晰度是执行标准，不是判断标准**（铭哥 2026-08-11）：重命名/更新时尽量带清晰度段；但判断
  一个文件"是否已规范"时不看清晰度——只要文件名含 `{imdb-ttXXXXXXX}` 段且扩展名合法，即视为已规范、
  跳过不重复整理。对应判定函数：`naming.is_normalized_movie_filename()` /
  `naming.is_normalized_episode_filename()`。**禁止**因缺失清晰度段或清晰度为占位/未知值而把已含
  `{imdb-tt}` 的文件重新标记为"待整理"。
- **外挂字幕**：与对应主媒体文件同主名，只在扩展名前增加可确定的语言标签，例如
  `.zh-Hans` 或 `.zh-Hant`。
- `episode` 必须同时得到季号和集号；`season` 必须得到季号；信息缺失或同一源文件解析出多个集号时停止，
  不靠类别、目录名或 Agent 常识补值。
- 片名内部保留规范标题；点号只分隔年份、季集号、媒体 ID、清晰度、语言和扩展名等结构字段。
- **无 IMDB 编号一律用占位符**（铭哥 2026-08-15 定，取代 2026-08-12 的“省略段”特批）：
  搜得到就写真实编号；**搜不到统一写 `{imdb-none}`，不省略该段**。这样“确认没有编号”与
  “漏写了”在文件名上可区分，这批文件也不会被反复标记为待整理。
  **身份未确认的文件不改名**——既不写 `none` 也不猜编号，原地保留并进异常清单等人工裁决。
  这类文件不按人物/演员聚合建目录，一律按普通单体电影 `名.年` 容器管理。
  〔实现待补：`is_normalized_*` 判定函数当前只认 `{imdb-tt…}`，需扩展为同时接受 `{imdb-none}`。〕

## 内容类型与收录范围（2026-08-15 铭哥定）

判断一个文件是否进片库主结构，先归类再处置。**不得把非正片当正片入库**。

| 类型 | 典型线索 | 处置 |
|---|---|---|
| 正片 | 院线或流媒体正式发行，有独立 IMDb 条目 | 进主结构 |
| 官方短片 | 如漫威 One-Shots | 进主结构，单独分组节点 |
| 官方剧集 | 分季播出 | 进 `TV shows/` |
| 相关纪录片 | 有独立 IMDb 条目 | 进 `Documentary/` |
| 粉丝自制 | fan film、同人重制 | **不进主结构**，放 `Fan.Works.{series}` |
| 花絮 / 幕后 | Behind the Scenes、Making of | **不收** |
| 预告 / 宣传片 | Trailer、Teaser、TV Spot | **不收** |
| 删减片段 | Deleted / Extended Scenes | **不收** |
| 导演评论版 | Commentary 音轨版 | **不收** |
| 路透 / 片场 | 拍摄现场流出素材 | **不收** |

“不收”指：不转存、不整理进主结构；已在库的按同根 archive 归档，待用户人工确认后自行删除。

## 分组归属与 AI 判断约束（2026-08-15 铭哥定）

### 先分离“事实”与“偏好”

归属争议大多不是事实问题，而是分类偏好问题。必须拆成两层：

- **事实层**（可查证，AI 负责取证）：制片公司、原作来源、官方系列归属、发行年份。
- **偏好层**（用户定，写死成规则，AI 不得自行发挥）：本片库要不要把某类内容聚到一起。

偏好一旦写成规则，归属就从主观变成客观判断，AI 只需查事实。

### 当前生效的偏好规则

1. **漫威分组**：凡漫威漫画改编，**不论出品方**（狮门、福克斯、索尼等一律计入）→ 分组名 `Marvel.{series}`。
   历史目录名 `Marvel Cinematic Universe` 名实不符（其中本就含非 MCU 影片），按本规则更名。
2. **DC 分组**：凡 DC 漫画改编，不论出品方 → 分组名 `DC.{series}`。历史目录名 `DC film series` 按此更名。
3. **其他系列**：按 franchise 正式名建分组节点。
4. **重启线再分层**：同一 franchise 存在多条互不连续的重启线时（如蜘蛛侠的托比线 / 荷兰弟线），
   允许在系列分组内再建一层分组，深度不受限。

### AI 判断的证据链（不得凭印象）

按优先级取证，并在 manifest 中**记录本次判断用的是哪一级**：

1. **权威结构化数据**——IMDb 编号、制片公司、原作来源。
2. **大众共识**——检索主流媒体、维基、豆瓣的归类口径；**多数口径一致才可采纳**。
3. **用户既有先例**——片库中已有同类内容的放置方式。
4. **以上皆无 → 不判断**，写入待定清单交用户裁决。**禁止猜测**。

### 判断的触发时机（其余时间不判）

| 时刻 | 判断范围 |
|---|---|
| 新资源入库时 | 只判当前这一部 |
| 全盘一致性校验时 | 只判新出现的不确定项；**已固化的判断不重判** |
| 用户修改偏好规则后 | 只重跑受该规则影响的部分 |

判断结果一旦写入 manifest 即固化，后续照此执行，**不得每次重新推理**——避免同一对象前后结论不一致。

## 清晰度判定通道（2026-08-12 实测，2026-08-15 复核修正）

精准判定分辨率的可用性与排序：

1. **文件名解析**（零成本，首选）：正则命中 `2160p/1080p/720p/4K/UHD/BluRay/REMUX/WEB-DL` 等，
   命中即采纳。**实测覆盖率 49.6%（121 个视频中 60 个），不是此前记载的 80%**（2026-08-15 全库扫描）。
2. **抽样下载 + ffprobe**（兜底）：本地 `ffprobe` 读 `width/height`。2026-08-15 实测结论：
   - moov 前置的 MP4、MKV（SeekHead 前置）、AVI：**取文件头 512 KB 即可读出**，可靠；
   - **moov 后置的 MP4 读不出**（报 `moov atom not found`）。此时**朴素“头 + 尾拼接”无效**——
     实测拼接后仍报同一错误，因为字节偏移错乱。**正确算法是稀疏重建**：把文件头与文件尾各自写在
     它们在原文件中的真实绝对偏移上、中间留空，ffprobe 即可正常读出（已实测成功）。
   - **但当前没有可用的取尾通道**：`bdpan download` 只有 `<remote> <local>` 两个参数，
     无任何 Range/分段能力；MCP `file_meta` 不返回 `dlink`（`dlink=1` 等入参实测无效）。
     因此稀疏重建暂不可实施，moov 后置的 MP4 一律标 `unknown` 进异常队列，**不得盲猜**。
3. **云端 API 元数据**：bdpan `ls` 无分辨率字段。MCP `file_meta` **已于 2026-08-15 打通**——
   入参必须是复数数组 `{"fsids": [<fsid>]}`（单数 `fsid` 会被百度侧拒为 `fsids is required`）。
   但返回体只有 `filename / size / md5 / category / abstract / thumbnail / path`，
   **不含宽高、时长或编码**，故对清晰度判定仍不可用；它的价值在于取 `md5` 与 `size` 做身份校验。

**全自动策略**：先跑文件名解析批量打标 → 无标注的进入抽样 ffprobe 队列 → ffprobe 失败的少数
（moov 后置/损坏/封装异常）进异常清单由 AI 逐个裁决。全程无人值守，只有异常队列需要 AI 介入。

## 禁止的快捷方式

- 用户催促不能绕过风险分级规则、计划重检或写后验收。
- 不将 plan-only 说成已执行。
- 不从标题、目标路径或 bdpan 文本输出猜测 `source_dir`。
- 不自动重试 transfer、mkdir、mv、rename 或 `file_move` 归档操作。
- 不用直接网盘命令绕过路径、冲突、脱敏或状态核验。
- 不读取本地网盘配置文件。
- 不用 `panlib-extract` stdout 或 transfer 的 `--url/--password` 人工兼容参数拼接 Agent 命令。

## 快速参考

| 入口 | 只读 | 可写 | 确认 |
|---|---:|---:|---|
| `scripts/bootstrap.sh` | 只读外部系统 | 可创建项目 `.venv`；固定依赖可自动安装 | 未固定依赖或外部安装器 |
| `scripts/login.sh` | 否 | 写入 bdpan 用户配置 | 用户在终端交互 |
| `panlib-doctor/search/imdb` | 是 | 否 | 无 |
| `panlib-extract/verify` | 人工诊断兼容入口，Agent 不调用 | 否 | 无 |
| `panlib-transfer` | 默认 | `--execute` | 风险命中时 |
| `panlib-organize` | 默认 | `--execute` | 风险命中时 |
| `panlib-library auth-status/list/search/meta` | 是 | 否 | 无 |
| `panlib-library archive` | 默认 | `--execute`（仅 `file_move`） | 风险命中时 |

参数以各命令 `--help` 和 [docs/CLI_CONTRACT.md](docs/CLI_CONTRACT.md) 为准。
