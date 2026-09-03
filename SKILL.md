---
name: ai-netdisk-assistant
description: >-
  Use when a user asks to install this repository, find, add, update, migrate,
  or organize movie, TV, anime, documentary, web drama, or other media
  resources through SeedHub and Baidu Netdisk.
allowed-tools: Bash, Read, AskUserQuestion
---

# AI 网盘助手

## 第一步永远是问路由器（强制，2026-08-31 起）

**不要凭记忆规划步骤。** 收到任何影视获取/升级/整理请求，第一条命令固定是：

```bash
cd <仓库根> && .venv/bin/python bin/panlib-plan list
.venv/bin/python bin/panlib-plan show --task <匹配的task> --title "<片名>" --season <N>
```

它会返回**逐条可直接执行的命令**，每步自带 `why`（为什么不能跳）、`expect`（成功判据）、`on_fail`（唯一下一步）。照着执行即可，不需要自行推理顺序、不需要记住踩过的坑。

| 用户说 | task |
|---|---|
| 找/下/存某剧某季 | `acquire-season` |
| 找/存某部电影 | `acquire-movie` |
| 画质不一致、想换更清晰的剧集 | `upgrade-quality` |
| 画质不一致、想换更清晰的电影 | 先走 `panlib-lib ... --type movie`；电影升级配方待补，不能套用剧集配方 |
| 整理网盘里已有的乱结构 | `organize-existing` |
| 反复失败、报"资源失效" | `diagnose-failure` |

**这条规则存在的原因**：本仓库实测中最贵的几次失败，全部源于"不知道有某个工具"或"不知道该按什么顺序做"，而不是推理能力不足。路由器把这类知识从"需要模型记住"变成"查一下就有"。

## 四个高层算子（优先用它们，而不是裸调底层命令）

> 完整契约表（副作用 / 停机语义 / 退出码 / 分层）见 `references/operators.md`。
> **读写边界看 help 里的 `[只读]` / `[写网盘]` 标注**，不要靠命令名猜。

底层命令（`panlib-transfer` / `panlib-organize` / `panlib-library`）是**单次、无重试**的原语。
这条链路上三个环节都是间歇性失败的，裸用原语必然踩坑。**默认使用下面三个封装**：

| 算子 | 作用 | 替代了什么 |
|---|---|---|
| `bin/panlib-lib` | 查片库已有 / 验收命名合规 | 手工 list + 肉眼比对 |
| `bin/panlib-share` | 浏览分享内部 / 按 fs_id 精准转存 | 整包 `panlib-transfer` |
| `bin/panlib-run` | 带重试与断点续跑地执行写操作 | 裸调 transfer/organize/archive |

```bash
# 获取前必跑：确认片库是否已有（最高频的浪费来源）
.venv/bin/python bin/panlib-lib find --title "<片名>" [--season N]
# 交付前必跑：一条命令验完所有季的命名合规与清晰度一致性
.venv/bin/python bin/panlib-lib verify --title "<片名>"

# 分享健康度：单次失败不是结论，probe 多轮取证
.venv/bin/python bin/panlib-run probe -r <id> --title-en "<名>" --imdb-id <tt> --year <年> --rounds 5
# 精准转存：自动跨越候选列表重排/长度波动
.venv/bin/python bin/panlib-run transfer-select -r <id> --fsid <a>,<b> --dest-dir "<隔离区>"
# 整理一季：403 中断自动断点续跑至源目录清空
.venv/bin/python bin/panlib-run organize-season --source-dir "<源>" --season N \
  --title-en "<英文名>" --imdb-id <tt> --quality <2160p> [--numeric]
# 归档：自动重试
.venv/bin/python bin/panlib-run archive --source "<路径>" --new-name "<名>_待删除"
```

**韧性是 CLI 的责任，不是模型的责任。** 看到 `unverified`、`NETWORK`、`403/errno=20013`、
`share changed since the plan` 时，**不要自己写重试循环，也不要判定资源失效**——
换用对应的 `panlib-run` 子命令，它内建了实测收敛的重试策略。

环境自检（换机器或换模型后先跑一次）：

```bash
.venv/bin/python bin/panlib-run selfcheck
```

### 为什么是这四个算子（设计依据）

本仓库实测中的四次代价最高的失败，根因**全部是信息缺失，不是推理能力不足**——
因此对策必须是确定性封装，而不是更详细的文档（文档会被跳过，命令不会）：

| 实测失败 | 代价 | 现在由谁兜住 |
|---|---|---|
| 不知道有 `transfer select`，整包转存 400GB 还漏掉 4K 目录 | 拿错版本 | `panlib-share browse` 是配方第 4 步，标了 ★ |
| 用 legacy 参数建出 `Stranger Things`（应为 `Stranger.Things.{series}`） | 全库返工 | `panlib-run organize-season` 只走 manifest 路径 |
| 单次探测失败就判"分享已失效" | 结论错误 | `panlib-run probe --rounds N` 多轮取证 |
| 反复转存一部**已在网盘里**的内容 | 白跑 37 轮 | `panlib-lib find` 是配方第 1 步，标了不可跳过 |

**判断新增能力该放哪一层**：一次性排查 → 临时脚本；会重复出现的判断 → 写进配方的
`expect`/`on_fail`；会重复出现的**动作** → 做成 `panlib-run` 子命令。
不要把需要重复执行的东西留在 SKILL.md 的散文里。

## 核心原则

Agent 只把用户意图翻译为结构化参数、调用本仓库 CLI、根据 JSON 状态决策。确定性逻辑必须留在 CLI，不临时编写脚本替代。

**参数纪律（2026-08-19 起强制）**：参数名一律以各命令 `--help` 与 `docs/CLI_CONTRACT.md` 为唯一事实源。本文示例已给出完整参数；任何不确定处先查这两个来源，**禁止凭印象脑补参数名**（实测教训：凭印象写 `--country` 被 CLI 拒绝，真实参数是 `--production-country`）。

**禁止直接调用 `bdpan`。** 唯一允许的入口是 `scripts/` 和 `bin/panlib-*`。不得读取或回显账号、Token、Cookie、BDUSS、账号密码、验证码、MFA 或 OAuth 授权码。SeedHub 资源只能通过 transfer 的 `--resource-id` 内部解析；Agent 不调用 `panlib-extract`，也不把 URL/提取码作为 transfer 参数。

## 能力边界

当前支持：

- SeedHub 影视搜索与百度分享链接提取。
- 磁力/直链云端离线下载（路线 A 首选，封装 `BaiduPCS-Go offlinedl`）。
- 本地已知表或用户提供的 IMDb ID。
- 百度网盘转存与影视文件整理。
- macOS 上通过官方百度网盘 MCP 读取全盘目录、搜索和读取元数据；旧资源仅能通过
  `panlib-library archive` 以 `file_move` 归档到指定目录，人工审核后再手动删除。
- `panlib-library migrate` 将 `/我的资源/Movies` 中一个已精确定位的媒体文件迁入 Apps
  片库的规范电影目录；它不是通用全盘移动。
- 可替换凭证接口默认使用 macOS Keychain；其他系统只能显式接入受控
  `external-command` 安全代理，不提供明文文件回退。

### Keychain 写入 128 字节截断（2026-08-30 实测修复，铁律）

`security add-generic-password -w` 走**交互式 stdin**（不带值、走隐藏两次输入提示）在 macOS 上会**静默截断到 128 字节，且返回码为 0、不报错**——用 178 字节的 MCP JSON 凭证和更长的 bdpan 凭证反复实测复现（50/100/120/127/128 字节写入无损，129 字节起精确截到 128 字节）。MCP 的 JSON payload、bdpan 的 access+refresh token 组合几乎总会超过 128 字节，这条路径此前一直在**悄悄丢数据**而不报任何错误。

修复：`panlib/keychain_store.py::MacOSKeychain.set()` 已改为 `security add-generic-password ... -w <value>`（值作为 argv 尾随参数直传，而不是走隐藏输入），实测 500 字节无损。代价是该值在这个短生命周期子进程运行期间对本机同用户的其他进程通过 `ps` 可见——铭哥已明确对单用户个人机场景接受此权衡（比静默丢数据更安全）。**任何未来改动都不得把 `set()` 改回走 `secret_input`/交互式 stdin 传参**，这是已验证过的真实回归点，不是理论顾虑。

### 通道能力矩阵（唯一权限判定）

| 通道 | 可读取 | 可写入 | 硬边界 |
|---|---|---|---|
| 官方百度网盘 MCP（`panlib-library`） | `/我的资源`、`/apps/bdpan` 等全盘绝对路径的目录、搜索和元数据 | 两个网盘根各自的同根 `archive`；受限 `migrate` 把 `/我的资源/Movies/`**的精确媒体文件移入 Apps 规范容器；**受限原地改名**（同一父目录内改名，仅当 bdpan 因路径校验拒绝该文件时） | 不删除、不覆盖、不执行分享转存、不提供任意跨根移动 |
| bdpan wrappers（`panlib-transfer` / `panlib-organize`） | 百度分享清单和 `/apps/bdpan` 内状态 | 分享转存，以及 `/apps/bdpan` 内建目录、移动和重命名 | 不能读取 `/我的资源` 或全盘；不能删除或任意跨根移动 |
| `panlib-offlinedl`（`BaiduPCS-Go offlinedl`） | 百度帐号登录态、BaiduPCS-Go 进程输出 | 向百度云端离线下载队列提交磁力/直链任务（**云端下载，零本地流量**）；只写 `/apps/bdpan` 下指定保存路径 | 不能直接控制百度网盘其他读写；不能上传本地文件到网盘；凭证与官方 OAuth 完全独立 |
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
8. 运行 `.venv/bin/python bin/panlib-library auth-status`。macOS 已有有效授权（保存在 Keychain）时继续。仅当 Keychain 未配置或过期时，进入下方「WebBridge 自动续期通道」（用户已明确授权此模式为个人单机场景默认路径）；用户明确拒绝或 WebBridge 不可用时才退回 `scripts/authorize_mcp_macos.py` 人工终端方式。其他系统只有在用户已配置 `external-command` 安全代理时继续；仓库不创建明文凭证文件。授权后非交互检查由 Agent 执行。

### WebBridge 自动续期通道（2026-08-30 铭哥定，个人单机场景默认路径）

MCP（简化模式，30 天硬限，无 refresh_token）与 bdpan（授权码模式，refresh_token 有效期 10 年但需定期触发刷新）都需要偶尔重新走一次浏览器授权页。铭哥已明确：这是他自己的账号仅供个人使用，Kimi WebBridge 驱动他本机已登录的真实浏览器（非无头爬虫、非新建干净会话）去读取官方 OAuth 回调，风险等同于他自己手动点击，可自动化、无需每次人工确认。

**判断入口**：`curl http://127.0.0.1:10086/status` 查 `extension_connected`；为 `false` 时先 `~/.kimi-webbridge/bin/kimi-webbridge start` 再复查一次，仍未连接则该次跳过并记录日志，不报错、不催用户去手动点插件——浏览器插件不常驻是预期状态，下个 cron 周期自然会重试。

**统一入口脚本**：`scripts/webbridge_reauth.py`（新增，2026-08-30）：
- `--check`：仅在 MCP/bdpan 任一方剩余天数 < 5 天时触发对应续期，否则原样跳过。
- `--force-mcp` / `--force-bdpan`：无视剩余天数强制续期一次，用于验证或紧急处理。
- 内部流程：`navigate` 到官方 OAuth 授权页 → `snapshot` 读取页面（MCP 读重定向 URL 里的 `access_token`/`expires_in`/`scope`；bdpan 读页面正文里的一次性授权码）→ 写回 Keychain（MCP）或经 `scripts/login.sh` 回填授权码（bdpan；脚本内部完成，Agent 不直调 bdpan）→ 写后用 `auth-status`/`whoami` 验证。
- 每次尝试（成功或失败）都追加一行到 `runtime/reauth_journal.jsonl`，字段含 `target`、`error_code`（失败时）、`next_action`、`status`（成功时），复用仓库既有台账规范，不新造格式。

**cron 化**：已建 Hermes cron job「网盘MCP+bdpan凭证自动续期」，`0 10 */5 * *`（每 5 天一次，30 天窗口留足冗余），`deliver=local` 静默运行，只有真正续期失败且临近过期时才提醒用户；正常续期成功或本次因插件未连接而跳过都不打扰。用户新开一台机器或重建 cron 时，照此 schedule 与 prompt 重建即可，不必每次重新设计。

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

**受限原地改名**（2026-08-16 新增）：bdpan 把文件名里的连续点判为路径穿越，
并拒绝**任何**操作——连只读的 ls 也拒绝，因此它无法寻址这类文件。文件名本身
合法且真实存在，不能因为一个工具的误判就永远改不了名，故由 `panlib-container
rename` 在 bdpan 明确因路径校验拒绝时改走 MCP `file_move`。边界与 archive 同样严：
**同一父目录内、只改名、不移动、不覆盖、不删除**，绑定 `plan_ref`、写前重读、
写后验收。不得把它当作通用改名通道。

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

#### 磁力入库主流程（路线 A，2026-08-19 固化）

当 SeedHub 资源无百度分享候选、或你已有一份明确磁力链接时，走本通道：

1. 取得 magnet 或 http 直链 → `.venv/bin/python bin/panlib-offlinedl add --link "<magnet>"`（默认 plan-only，返回 plan 包含自动补全的公共 tracker 与 magnet_xt）。
2. 风险分级规则命中（如用户进入"更新影视"或"转存资源"模式且无冲突）→ 加 `--execute` 真正提交；
4. `--wait <秒>` 可选：提交后轮询任务状态至"下载成功/下载失败"。**热门资源（百度已有缓存）通常 ≤1 分钟完成，零本地流量**。
5. 离线下载完成后，目标路径已是真实媒体文件 → 走 organize 整理进片库，archive 旧版（同转存流程 D 节）。

**回退（路线 B，本地中转）**：当云端离线下载一直失败（冷种/死种/限速）时，本地用 aria2c 多线程下载磁力，再用 `bdpan upload` 上传——上传若命中秒传则瞬间完成；若不命中则按你的出口带宽跑。SeedHub 共享 URL 仍可走原 transfer 通道。

**磁力 tracker 补全**（关键）：裸磁力在隔离网络中 DHT 节点发现可能数分钟无进展；`panlib-offlinedl add` 自动注入 8 个公共 tracker，**调用方不需要自己记得这件事**。

#### 合集分享处理（2026-08-19 新增；实测《爱在三部曲》踩坑后固化）

SeedHub 上一个"单片"资源的百度分享，内容可能是**多部打包的合集**（实测：请求《爱在日落黄昏时》，
转存进来的目录同时含三部曲全部）。**禁止把合集当单片处理。** 固定流程：

1. 转存验收通过后，先**只读盘点** `source_dir` 的全部子项（用 list 直读，见下条），与本次请求的单片比对。
2. 内容恰为请求的单片 → 按正常流程整理。
3. 内容为合集 → 逐部处理：
   - 每部各自走 organize（各自的 IMDb、年份、规范目录）；
   - 与片库既有同名片段做**画质裁决**：新版规格明确更高（分辨率/片源/音轨可查证）才替换，否则保留旧版、新版归档；
   - 被替换的旧版同根 `archive`；已整理完的空壳子目录随合集源一起归档；
   - 合集里未被请求的其余部分，**不得擅自丢弃或删除**——报告用户后再决定。
4. 后续同系列请求先检查片库是否已含该部（可能已随合集入库），避免重复转存。

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
3. `.venv/bin/python bin/panlib-imdb --title "<title>" --year <YYYY>` —— **联网查询是默认且唯一的真实路径**（2026-08-19 起）；内置已知表只是测试夹具，仅 `--known-table` 显式启用，离线也不用。联网超时/失败（`NETWORK`）时：重试一次 → 仍不通就请用户提供 `tt...`，再用 `--imdb-id` 验证。**查不通 ≠ 查过且没有**，绝不能据此写 `{imdb-none}`。
4. 用 `.venv/bin/python bin/panlib-transfer --resource-id <id> --type <type> --title-en "<英文正式名>" --title-zh "<中文正式名>" --production-country "<制片国家>" --imdb-id <tt...> --year <YYYY>` 生成转存计划，**不加** `--execute`。transfer 在自己的进程内解析链接，不把 URL/提取码返回给 Agent。
   resource-id 路径会在计划生成前通过官方 `bdpan transfer list --json` 做只读探测；只有 `share_probe.status=valid` 才继续返回计划。过期分享返回 `NOT_FOUND/share_status=expired`，网络、认证、权限或未知响应为 `share_status=unverified` 并停止。
5. 多个百度候选由 transfer 的 `preset-quality-v1` 固定策略自动排序，依次比较分辨率、片源、HDR、音轨、字幕和大小，完全相同才按资源站原始顺序稳定选择。Agent 不询问用户；只有用户明确覆盖时才传 `--link-index <index>`。计划必须回传 `selection.strategy`、候选数和脱敏的 `selection.selected`，其中不得包含 URL 或提取码。
6. `NOT_FOUND`、`NETWORK`、`PARSE` 或任何其他非零退出：停止并报告，可请用户选择另一资源；不自动进入写操作。

### B. 转存：计划 → 自动执行（风险命中才暂停）

1. 运行 `.venv/bin/python bin/panlib-transfer` 并传入 `--resource-id`、可选 `--link-index`、`--type`、`--title-en`、`--title-zh`、`--production-country`、`--imdb-id`、`--year`、可选 `--quality`，**不加** `--execute`。
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
2. **类别根由配置提供**：`movie → Movies`、`tv → TV shows`、`anime → Animation`（2026-08-30 起，见下方「类别根命名统一」）、
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
| 资源无百度候选（`no Baidu share candidates`） | **不进入转存、不换关键词硬凑**。报告该资源实际可用的其他渠道（夸克/阿里/UC/磁力），给用户选项：① 接受其他网盘 ② 用户自行提供百度分享链接 ③ 放弃。等用户拍板 |
| `NETWORK`（SeedHub 侧）连续出现 | **先怀疑自己把站点打限流了**，不要判定"资源失效"。见下方「分享健康度分诊」 |
| `share_status=unverified` | 报告只读探测未确认；按 `AUTH`/`NETWORK`/`PERMISSION`/`PARSE` 处理，不进入转存 |
| MCP `AUTH`/`expired` | 只运行 `panlib-library auth-status`，让用户完成官方授权；不读取 Token 正文 |
| `auth-status` 报 `reason=missing` | 先按启动检查第 8 步的「missing 分流」诊断（Keychain 条目存在性 + 账户名比对），确认真缺失/过期才让授权；禁止账户不匹配时重授权 |
| `ambiguous` / `unverified` 或上层验收标为 `partial` | 停止，不继续整理，不宣称完成 |

### 分享健康度分诊（2026-08-31 实测固化，铭哥《怪奇物语》案例）

**核心教训：单次探测结果不可作为判据。** 实测同一批 resource-id 连跑三轮，同一条链接出现 valid / expired / unverified 三种结果轮换——不是分享状态在变，是**探测本身不可靠**。据单次失败就向用户报告"分享已失效"是错误结论。

失败分两个独立层，必须先分层再决策：

| 现象 | 层 | 判据 | 处置 |
|---|---|---|---|
| `NETWORK`、`PARSE`（SeedHub 取详情失败） | 资源站层 | 裸 `curl` 资源页返回 **429**（限流）或 **403**（Cloudflare 挑战） | **我们自己打的**。停手冷却 ≥5 分钟再试，不是资源问题 |
| `share_status=unverified` + `errno=13001` | 百度分享层 | 冷却后**多次**探测仍稳定失败 | 该百度分享真的坏了（已取消/已删除/已失效），换资源或换通道 |
| 探测结果在多次间跳变 | 探测层 | 同一 id 出现 valid↔expired↔unverified | 判据不足，**必须冷却后重测**，不得据此下结论 |

**强制流程**：任何 `NETWORK`/`unverified` 结论，都要求「冷却 + 至少 3 次复测 + 结果一致」才能写进给用户的报告。**禁止串行连打多个 resource-id**——实测连打 15 次即触发 429，之后所有探测结果全部失真，会把好资源误判成坏资源。批量处理时每次探测间隔 ≥3 秒。

**健康度优先选源**：同一部剧的多个季条目，先各探 1 次做健康度排序，优先转存 `valid` 的条目；一个 `valid` 的合集分享（常含全系列）胜过五个逐季探测。实测 S05 条目的分享内含 S01–S05 全集，一次转存解决四个季。

### 通道选择判据（不要盲目换方案）

四条通道解决的是**不同层**的问题，换通道只在对应层失败时才有意义：

| 通道 | 绕过什么 | 什么时候换过去 |
|---|---|---|
| 分享链接转存（默认） | —— | 默认 |
| QR→HTML 提取 | 页面无明文直链 | **已内置在 `link_start` 解析里**，不是独立方案，无需人工切换 |
| 磁力云端离线（`panlib-offlinedl`） | 绕过 SeedHub 分享 + 百度分享**两层** | 百度分享确认坏死（冷却后稳定 13001）时的唯一有效替代 |
| 本地下载再上传 | 绕过百度云端离线（冷/死种） | 云端离线也失败时的兜底，有本地流量成本 |

**关键判断**：分享坏死是**源的问题**，不是传输方式的问题。换 QR、换解析路径都无效——它们取的是同一条已经死掉的链接。只有磁力通道换了源，才真正有效。

### 重试是一等公民（2026-08-31 实测固化）

这条链路上**三个独立环节都是间歇性失败**，单次失败一律不构成结论：

| 环节 | 症状 | 实测 | 对策 |
|---|---|---|---|
| SeedHub 探测 | `unverified` / `NETWORK` | S01/S03/S04 都在第 3–4 次重试后拿到 `valid` | 探测重试 ≥5 次，间隔 8–12 秒 |
| 百度 `mv`/`list` | HTTP 403 `errno=20013` | S01、S02 迁移中途各断一次，重跑即继续 | **循环重跑至源目录清空**，不是权限问题 |
| plan→execute | `share changed since the plan` | 候选 ref 在两个值间摆动 | 见下方「候选摆动」 |

**批量写操作必须写成"重跑到源目录为空"的循环**，而不是单次执行 + 失败报错。已固化为 `panlib-run organize-season`（每轮重新 list → 重新生成 manifest → plan → execute），实测 S01 两轮、S02 两轮收敛。403 中断**不会丢文件**，已迁移的留在目标、未迁移的留在源，重跑即补齐。

**候选摆动（根因已查明，2026-08-31）**：**SeedHub 的候选列表每次请求都会重排，`--link-index` 不是稳定标识符。** 实测同一 resource-id 连探三轮，`idx=0` 返回了两个完全不同的资源，`idx=3`/`idx=4` 同样各返回两个。因此：

- `--share-ref` 在 execute 重解析时对不上是**必然**，不是偶发；
- **缩短 plan→execute 间隔无效**（实测 12 轮全败）；
- **锁 `--link-index` 也无效**（实测 25 轮全败）；
- 用 description 内容指纹匹配同样无法稳定拿到 valid。

**正确对策：不要跟这个摆动硬拼。** 转存一个资源时，SeedHub 上同一部作品往往有 5–12 个候选，且**大量候选是"全系列合集"**——转存任意一个成功的合集，往往就同时拿到了其他所有季。本次 S01–S05 全部来自**一次**成功的 S05 转存，S04 也在同一个合集里。

**关键认知转变：先在已转存内容里找，再考虑新转存。** 遇到某一季转存不下来时，第一步应该是 `panlib-library list` 检查已有合集里是不是已经有了，而不是反复重试转存。本次 S04 卡了 37 轮转存，最后发现文件早就躺在网盘里。

### 精准转存：`panlib-share`（2026-08-31 新增，铭哥提议）

**能力**：先看清分享内部结构，再只转存需要的文件，不必整包吞下几百 GB。

```bash
# 1) 只读浏览分享根层
.venv/bin/python bin/panlib-share browse -r <resource_id>
# 2) 逐层深入（用上一步返回的 path）
.venv/bin/python bin/panlib-share browse -r <resource_id> --source-dir "/某目录/子目录"
# 3) 精准转存指定 fs_id（plan-only）
.venv/bin/python bin/panlib-share select -r <resource_id> --type tv \
  --dest-dir "/apps/bdpan/片库/TV shows/_待整理_<标签>" --fsid <id1>,<id2>,...
# 4) 回传 share_ref 执行
.venv/bin/python bin/panlib-share select ... --share-ref <64hex> --execute
```

安全边界与 `panlib-transfer` 一致：URL/提取码只在进程内解析，输出全脱敏；plan-only 默认；execute 必须回传 `share_ref`；写前后各读一次目标目录做验收。

**实测价值**：S05 合集分享共 400+ GB，其中「4K HDR 杜比视界」子目录 85 GB 是想要的。整包转存会拖进大量无关内容并淹没目标；`browse` 三层定位 + `select` 八个 fs_id，**一轮成功，只落 85 GB**。之前整包转存时恰恰漏掉了这个 4K 目录，只拿到同级的 1080p 版本——**不 browse 就不知道分享里还有更好的版本**。

**必读坑**：`bdpan transfer list --json` 的字段是 `items` 和 `is_dir`（不是 `list`/`isdir`），用错会把目录全判成文件、或报 "no recognizable file list"。

**share_ref 定向重找（候选摆动的正解）**：`panlib-share select --execute` 在首次解析 ref 失配时，会遍历候选集按 `share_ref` 定向重找目标分享。因为 ref 绑定的是 URL+提取码本身，无论这次它排在第几位都能锁定，而 ref 不匹配的分享依然被拒绝——**安全边界没放宽，只是不再被顺序抖动误伤**。`panlib-run transfer-select` 已内建该重试，可跨越候选列表的长度波动（实测同一分钟内候选数在 1 和 9 之间跳）。

### 让"不小心存到"变成"刻意存到"（确定性提升）

本次 S01–S04 能成，一半靠运气：合集恰好被整包转存进来了。**下次没有这个运气时，正确顺序是：**

1. **先 `browse`，不要先 `transfer`。** 用 `panlib-share browse` 逐层看清分享里到底有什么、各版本画质如何、目标内容的 fs_id 是多少。这一步是**只读**的，不消耗网盘空间，也不产生需要清理的残留。
2. **按需 `select`，落到隔离区。** 转存到 `/apps/bdpan/片库/TV shows/_待整理_<标签>`，而不是直接落到类别根——避免与片库既有内容混在一起难以分辨本次转存了什么。
3. **`organize` 进规范容器，再归档隔离区。** 隔离区清空后随即 archive，保持根目录干净。

这条路径把"整包转存 + 事后大海捞针"换成了"先看清 + 精准取 + 隔离落地"，每一步的产出都可预期、可验收、可回滚。**整包 `panlib-transfer` 只在确实想要整个分享时才用。**

### 纯数字文件名的季号判定（ffprobe 实证法）

合集里常见 `01.mkv`–`09.mkv` 这类无季号命名。**禁止靠数量猜季**，但可以用 ffprobe 实测取证：

```bash
# 远端抽样画质探测尚未封装为安全算子，当前不可直接下载；升级配方会返回 BLOCKED。
.venv/bin/python bin/panlib-plan show --task upgrade-quality --title "<剧名>"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height \
  -show_entries format=duration,bit_rate -of default=nw=1 "<本地样本文件>"
```

判据示例（本次 S04）：时长 3786s（63 分钟）——第三季每集约 50 分钟，只有第四季才有 63–98 分钟的超长集；配合 9 集数量、父目录标注「第1-4季」、S01/S02/S03 三个子目录已被单独整理走，四条独立证据交叉确认季号。**单一证据不足以定季，至少要两条独立证据。**

生成器已内建：`panlib-run organize-season --numeric`（纯数字名 → manifest v1，季号由调用方在取证后指定）。

### 画质核验：只认 ffprobe，不认文件名和体积

体积大 ≠ 画质高。本次实测：

| 来源 | 分辨率 | 均值 | 码率 |
|---|---|---|---|
| 已入库 S03（WEB-DL HDR10） | 3840×2160 | 6.2 GB/集 | 5.9 Mbps |
| 合集 S04（REMUX） | 3840×**1920** | 12.7 GB/集 | 19.0 Mbps |

两者**同为 2160p**，高度差异是宽银幕裁切（第四季确有 2.00:1 画幅），不是降质。体积和码率的两倍差来自 REMUX 与 WEB-DL 的封装差别。**只用文件名或体积判断画质会得出错误结论，必须 ffprobe 实测 width/height。**

**候选标签本身可能是虚标，浏览进去看真实文件名才算数**（2026-09-02 实测，《爱在三部曲》案例）：SeedHub 候选列表给出的 `quality` 字段来自描述文字的模糊匹配，不是实测结果。实测反例：某候选 `description` 写「4k≥1080p」、选择器标为 `2160p`，浏览进目录后真实文件名是 `Before.Sunset.2004.1080p.BluRay.REMUX...`——描述文字本身就含糊（"≥1080p"不代表就是4K），选择器把它误判成了 2160p。**任何"升级画质"判断，浏览到最深一层看见真实视频文件名之前，都不能采信上层候选列表给出的 quality 标签。**

**"Upscaled"版本不算真实画质升级**（同案例）：网络磁力站点常见把 1080p 源用软件超分/插值放大到 2160p/4K 分辨率后重新打包，标题会诚实标注 `Upscaled`（如 `Before Sunrise 1995 Upscaled BluRay 2160p HDR10 HEVC...`）。这类文件的像素尺寸确实是 2160p，体积也确实更大，**但信息量没有增加，不构成真实的画质升级**，不应作为"upgrade-quality"任务的目标版本。判断一部作品是否存在真实高画质版本，应先查其官方发行历史（如 Blu-ray.com / Criterion 等碟商页面标注的 Resolution 字段），而不是仅凭资源站候选数量和标题字样。若官方从未发行超过 1080p/2K 的版本，网络上出现的所有更高分辨率资源默认视为 upscale，除非有明确的原生母版证据（如碟商页面标注真实 4K UHD 发行）。

### 结构规范：必须与库内既有约定一致

剧集容器一律 `Name.{series}/Name.Sxx/`（如 `Loki.{series}/Loki.S01/`）。

**`panlib-organize` 两条代码路径的命名规则不一致，是已知陷阱**：
- `--manifest-file` 路径 → 生成 `Stranger.Things.{series}` ✅ 合规
- legacy 参数路径（`--target-dir` + `--mode tv`）→ 生成 `--target-dir` 叶子名，如 `Stranger Things` ❌ 不合规

**因此剧集整理一律走 manifest v1**，不要用 legacy 参数路径，否则会建出与库内约定不符的平行容器。

**manifest 编写要点**：`panlib-library list` 返回的 `fsid` 是**字符串**，manifest 的 `fs_id` 必须是**整数**，否则报 `manifest fs_id does not match the discovered source`。`panlib-run organize-season` 已内建该转型（从文件名解析 SxxExx，fsid 自动转整数）。

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
- **类别根目录**：`movie → Movies`、`tv → TV shows`、`anime → Animation`、
  `documentary → Documentary`、`webdrama → 网剧`；新增类别必须由配置提供根目录，不能临时猜路径。

### 类别根命名统一（2026-08-30 铭哥定）

历史遗留的 `动漫` 目录名与 `Movies`/`TV shows`/`Documentary` 的英文风格不一致。铭哥要求全部类别根统一用英文，`anime` 类别根改名为 `Animation`（不用 `Anime`——`Anime` 偏日式动画语境，片库里既有欧美 3D 动画又有日系番剧，`Animation` 是行业通用叫法，覆盖两者不产生歧义）。

**改名当时留下的真实漏洞（2026-09-02 全库审计中发现并修复）**：云端目录已原地改名为 `Animation`，但代码里维护该映射的有 **两处独立字典**——`panlib/media_manifest.py::CATEGORY_DIRS` 和 `bin/panlib-transfer::TYPE_DIR`——只改了前者，后者仍写着旧值 `动漫`。后果分两层：`panlib-audit` 把 `Animation` 目录错判为"内容节点持有子目录"（审计层误报，只读，无害）；但 `panlib-transfer` 若真的转存动漫资源，会向一个不存在的旧路径写入（写操作层，实际会出错或建出错误目录）。这条漏洞潜伏了三天没被触发，直到一次全库只读扫描才暴露。**同类问题的教训**：任何"改名/改路径映射"类决策落地后，必须 `grep` 全仓库确认没有第二份副本；`CATEGORY_DIRS` 之类的常量只能有一个真源，其余地方必须 `import` 而不是各自维护一份字面量字典。

**执行方式：改名优先于新建**——两个网盘根各自现有的 `动漫` 目录都用 `panlib-container rename` 原地改名为 `Animation`（同一父目录内改名，属于既有的「受限原地改名」能力，不新建平行目录、不产生迁移工作量）。已入库内容默认不追溯重排（工作量与铭哥意愿判断，见下条）；只有新一批要更新画质/规范化的资源才顺带把其容器从旧类别根迁移到新类别根。

**通用原则（2026-08-30 铭哥定，写入本节供所有整理场景引用）**：**能用改名或迁移解决的，不新建**。原地改名（`panlib-container rename`）与跨类别迁移（`panlib-organize` 换 `--target-dir`，源和目标都在同一网盘根内时是普通整理操作，不需要 `panlib-library migrate`）都不产生额外冗余目录；只有目标路径确实不存在且语义上必须是新容器时才新建。判断准则：若一个动作的净效果是「同一份文件换了个位置/名字」，优先选改名或 mv 类操作；只有「内容从无到有」才用 mkdir/新建。
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
  该规则已由 `is_normalized_movie_filename()` / `is_normalized_episode_filename()` 实现并覆盖 `{imdb-none}`。

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
   - **但当前没有可用的取尾通道**：现有网盘下载接口只有普通的远端路径到本地参数，
     无任何 Range/分段能力；MCP `file_meta` 不返回 `dlink`（`dlink=1` 等入参实测无效）。
     因此稀疏重建暂不可实施，moov 后置的 MP4 一律标 `unknown` 进异常队列，**不得盲猜**。
3. **云端 API 元数据**：bdpan `ls` 无分辨率字段。MCP `file_meta` **已于 2026-08-15 打通**——
   入参必须是复数数组 `{"fsids": [<fsid>]}`（单数 `fsid` 会被百度侧拒为 `fsids is required`）。
   但返回体只有 `filename / size / md5 / category / abstract / thumbnail / path`，
   **不含宽高、时长或编码**，故对清晰度判定仍不可用；它的价值在于取 `md5` 与 `size` 做身份校验。

**全自动策略**：先跑文件名解析批量打标 → 无标注的进入抽样 ffprobe 队列 → ffprobe 失败的少数
（moov 后置/损坏/封装异常）进异常清单由 AI 逐个裁决。全程无人值守，只有异常队列需要 AI 介入。

## 禁止的快捷方式

- **写后验收与读回一律用 `list`/`meta` 按路径直读，不用 `search` 验收**（2026-08-19 实测：搜索索引有延迟，刚转存的内容可能搜不到，会把"成功"误判成"失败"）。
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
