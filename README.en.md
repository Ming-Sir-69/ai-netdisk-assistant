<picture>
  <source media="(prefers-color-scheme: dark)" srcset="readme-assets/header-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="readme-assets/header-light.svg">
  <img alt="AI Netdisk Assistant · ✦ EricMingle69" src="readme-assets/header-light.svg" width="100%">
</picture>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README.en.md">English</a> · <a href="PERSONAL-NOTICE.md">✦ EricMingle69</a>
</p>

> Send this exact installation request to Codex:
>
> Codex帮我安装这个工作流然后开始整理网盘资源 https://github.com/Ming-Sir-69/ai-netdisk-assistant

# AI Netdisk Assistant

An Agent workflow for media search, candidate comparison, Baidu Netdisk transfers and consistent naming.
Resource discovery stays read-only; library updates use a defined target, a plan and read-back verification.

## First setup

Start with macOS: prepare Python 3.13+, Baidu's official `bdpan` tool and the necessary authorization.
Credentials default to macOS Keychain. Windows/Linux require an `external-command` secure credential agent; there is no plaintext fallback.

Check the environment from the repository root:

```sh
./scripts/bootstrap.sh
```

The default performs local checks. Install missing pinned dependencies with `./scripts/bootstrap.sh --install-deps` when needed.
Complete Baidu authorization personally through `./scripts/login.sh`; check MCP authorization with the project interpreter:

```sh
.venv/bin/python bin/panlib-library auth-status
./bin/panlib-doctor
./scripts/preflight.sh
```

Enter a media workflow only when both `doctor` and `preflight` report `ready`; follow their instructions for missing or expired authorization.

## Choose the scope in one sentence

| Request | Behavior |
| --- | --- |
| Find a film | Search, compare and verify candidates without writing to the drive |
| Update a media item | Locate existing resources, transfer, organize, archive within the same root and verify |
| Organize a specified directory | Organize existing media without search or transfer |
| Archive a specified directory | Move within the same root to a pending-deletion area, without deleting |

## Capability boundaries

- SeedHub supplies search; wrappers handle Baidu share transfers and organization within Apps.
- The official Baidu MCP handles drive-wide directory/metadata reads, same-root archiving and restricted media migration; this does not permit arbitrary drive-wide moves.
- Organization accepts main videos and external subtitles; images, posters, NFO files and reading notes stay outside media containers.
- Conflicts, ambiguity and `partial`/`unverified` stop the workflow; writes are not overwritten, deleted or retried automatically.
- Offline-download wording conflicts with the `bin/panlib-offlinedl` entry; verify its support scope before use rather than treating it as a quickstart feature.

## Further reading

[SKILL.md](SKILL.md) defines workflow and permissions. [The CLI contract](docs/CLI_CONTRACT.md) covers parameters and states; [architecture](docs/ARCHITECTURE.md), [contributing](CONTRIBUTING.md) and [security](SECURITY.md) cover maintenance.

## Sources and license

[MIT License](LICENSE): Copyright (c) 2026 Eric Mingle.
CaliCastle/seedhub-cli and other components retain their attribution and licenses in [third-party notices](THIRD_PARTY_NOTICES.md); the software license does not grant rights to copy or share media content.

<details>
<summary>Detailed usage contract and verification record (canonical Chinese)</summary>

<!-- BEGIN PRESERVED DOCUMENTATION CONTRACT -->
# AI 网盘助手

> 把“搜索影视资源 → 验证链接 → 转存百度网盘 → 规范命名”固化为 Agent 可调度的确定性工作流。

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 先了解，再开始

这是面向 Agent 的百度网盘影视资源工作流，适合想通过对话查找影视、转存资源、规范片库目录，以及维护确定性 CLI 的用户。它把资源搜索、候选比较、计划生成和执行验收串成可追踪的流程；日常使用可以从一句自然语言请求开始。

**首次使用建议从 macOS 开始**：需要 Python 3.13+、百度官方 `bdpan` 工具及相应授权。默认凭证后端是 macOS Keychain；Windows/Linux 需要自行接入文档约定的安全凭证代理，其实机兼容性仍待验证。

| 你想做什么 | 从这里开始 |
| --- | --- |
| 让 Codex 安装并带你使用 | [最简单的使用方式](#最简单的使用方式) |
| 自己安装、检查依赖与授权 | [安装与初始化](#安装与初始化)；本地已有仓库时复用原目录 |
| 先找资源，暂不写入网盘 | [使用模式](#使用类)中的“找资源” |
| 更新、整理或归档指定资源 | [安全工作流](#安全工作流)与[通道能力矩阵](#通道能力矩阵唯一权限判定) |
| 理解目录、命名与命令参数 | [命名契约](#统一影视命名契约) · [CLI 契约](docs/CLI_CONTRACT.md) |
| 改进文档或代码 | [贡献指南](CONTRIBUTING.md) · [架构说明](docs/ARCHITECTURE.md) |

从仓库根目录运行 `./scripts/bootstrap.sh` 可以检查本地环境，默认不联网安装依赖；完整的安装、登录与门禁步骤见下文。`doctor` 与 `preflight` 实际报告就绪后再进入业务流程。

**使用边界**：搜索源目前围绕 SeedHub，网盘写入围绕百度网盘；整理仅接收主视频与外挂字幕。写操作可能部分完成，遇到冲突或验收失败会停止，具体路径权限与归档规则见下文。离线下载的支持范围仍需确认：仓库包含 `bin/panlib-offlinedl`，但正文尚写“不支持磁力链接下载”，因此此入口暂不列入快速开始。

下文“验证状态”保留既有版本的历史记录，外部服务可用性与当前机器是否就绪仍需实际检查。欢迎通过 [Issues](https://github.com/Ming-Sir-69/ai-netdisk-assistant/issues) 反馈可复现的问题、文档缺口或改进建议；敏感信息按[安全策略](SECURITY.md)处理。

仓库维护：[Ming-Sir-69](https://github.com/Ming-Sir-69)。项目采用 [MIT License](LICENSE)；许可证中的原版权署名，以及[第三方许可声明](THIRD_PARTY_NOTICES.md)中的上游归属继续保留。

## 最简单的使用方式

把下面这句话发给 Codex：

> Codex帮我安装这个工作流然后开始整理网盘资源 https://github.com/Ming-Sir-69/ai-netdisk-assistant

Agent 应在同一个目录完成下载、环境检查和授权引导，不创建第二份源码副本。安装后它会先确认你要处理的影视资源或精确云端路径；当前版本不会无差别扫描整个网盘。

## 对话初始化与模式选择

每次新对话先按下面两级分类用户意图。用户已经说清意图时，Agent 直接确认识别结果，
不重复要求用户从菜单选择；只有意图不明确时才展示这个简短入口。

### 使用类

| 你可以直接说 | 进入的模式 | 范围 |
|---|---|---|
| `更新《这个杀手不太冷》` | **更新影视**（默认完整更新） | 定位旧资源 → 搜索并自动比较 → 转存 → 整理 → 同根归档旧资源和 Apps 残留 → 四路径验收。 |
| `找《这个杀手不太冷》资源` | **找资源** | 仅搜索、比较、验证候选；不写网盘。 |
| `转存这部资源` | **转存资源** | 只对已确认候选执行转存；不整理、不归档。 |
| `整理这个目录：/…` | **整理已有资源** | 只整理用户指定的已存在目录；不搜索、不转存。 |
| `归档这个目录：/…` | **归档旧资源** | 只移动用户指定旧目录到同根待删除区；不删除。 |

### 测试类

只保留一个入口：`测试/验证这个工作流`。只有用户明确进入测试类时，Agent 才展开测试目标、
样本、计时、日志和验收维度；普通使用不显示这些选项。

#### 更新影视的默认路径与首句反馈

`更新《这个杀手不太冷》` 自动进入默认完整更新。对象是该电影资源，不要求用户预先提供
路径：Agent 先在 `/我的资源` 和 `/apps/bdpan/片库` 内按片名精确定位旧资源与已有 Apps
版本；在搜索层把实际命中路径写进首条反馈。两处都找不到再询问用户旧资源路径，或确认本次
是否是没有旧资源的新入库。

每次初始化都先输出一行**模式卡**，例如：

> 模式卡：使用类 / 更新影视｜对象：《这个杀手不太冷》｜默认检索：`/我的资源`、`/apps/bdpan/片库`｜下一步：定位现有资源后搜索 SeedHub。

这张卡是范围声明。默认采用风险分级确认：可恢复、无冲突且不扩大权限的动作自动连续执行；
只有授权、权限变化、歧义、冲突、覆盖、删除或验收异常才暂停询问。

## 当前能力

- 连接百度网盘，引导用户在百度官方页面完成 OAuth。
- 从 SeedHub 搜索少量影视资源，优先提取直链；页面确实只有二维码时，在受限同源图片范围内本地解码并验证百度网盘分享链接。
- 多个百度候选由 CLI 按固定的画质、片源、HDR、音轨、字幕和大小规则自动排序；不依赖 Agent 临场选择。
- 按电影、剧集、纪录片、动漫、网剧分类转存。
- 按 IMDb 标识和媒体信息生成整理计划；无冲突时由 Agent 自动执行并验收，风险命中才暂停。
- 整理时只接收主视频和供播放器加载的外挂字幕（含 `.sup`）；不接收任何图片、
  海报、剧照、NFO、TXT、PDF 或其他阅读说明文件。
- macOS 上通过官方百度 MCP 读取全盘目录、搜索和元数据；旧资源只通过
  `panlib-library archive` 的 `file_move` 归档，人工审核后再手动删除。
- `panlib-library migrate` 可将 `/我的资源/Movies` 内已精确定位的媒体文件迁入 Apps 片库；
  它不是任意网盘路径的通用移动功能。
- 提供可替换凭证接口：默认使用 macOS Keychain；其他系统可显式接入受控的
  `external-command` 安全凭证代理。

### 通道能力矩阵（唯一权限判定）

| 通道 | 可读取 | 可写入 | 硬边界 |
|---|---|---|---|
| 官方百度网盘 MCP（`panlib-library`） | `/我的资源`、`/apps/bdpan` 等全盘绝对路径的目录、搜索和元数据 | 两个网盘根各自的同根 `archive`；受限 `migrate` 把 `/我的资源/Movies/**` 的精确媒体文件移入 Apps 规范容器 | 不删除、不覆盖、不执行分享转存、不提供任意跨根移动 |
| bdpan wrappers（`panlib-transfer` / `panlib-organize`） | 百度分享清单和 `/apps/bdpan` 内状态 | 分享转存，以及 `/apps/bdpan` 内建目录、移动和重命名 | 不能读取 `/我的资源` 或全盘；不能删除或任意跨根移动 |
| SeedHub provider | 资源站搜索、详情和百度分享引用 | 无 | 不读取或写入个人网盘 |

`/apps/bdpan` 是 bdpan wrappers 的 OAuth/写入范围，不是 MCP 的读取范围。不得把这一限制
泛化到 MCP 的全盘读取能力；权限判断只查本矩阵和 `preflight` 的实际结果。

当前只支持百度网盘写入，资源索引也只接入 SeedHub。仓库内置并实机验收的凭证后端仍是
macOS Keychain；Windows/Linux 需要用户提供自己的安全凭证代理，本项目不捆绑系统实现，
也不提供明文文件回退。它不是通用网盘客户端，也不支持磁力链接下载。

## 安装与初始化

0. **先打开宿主完全访问。** 在 Codex、WorkBuddy 或其他 Agent 平台中，必须允许当前进程
   访问 macOS 钥匙串、百度 MCP 和百度网盘网络。平台按钮名称可能不同，但
   `./scripts/preflight.sh` 是硬门禁：它会实际读取安全凭证状态并调用百度 MCP 读取
   网盘根目录。返回 `blocked` 时不得进入业务流程，也不得把它误判为百度授权失效。

### Agent 路径

所有 Python CLI 必须从仓库根目录使用项目解释器 `.venv/bin/python` 启动；不得直接运行
`python3 bin/...` 或依赖 shell 当前是否激活虚拟环境，避免把系统 Python 误判为依赖缺失。

1. 如果本地已有该仓库，必须复用现有目录；否则只 clone 一次。
2. 进入仓库根目录，运行 `./scripts/bootstrap.sh`。该命令执行本地初始化检查，必要时创建项目 `.venv`，但默认不联网下载依赖。
3. 如果缺少 Python 依赖且 `requirements.txt` 已固定版本、用户已明确启动安装/使用流程，Agent 可直接运行
   `./scripts/bootstrap.sh --install-deps`；只有未固定依赖、外部安装器或超出清单的网络访问才询问。
4. 如果缺少 `bdpan`，打开[百度官方 bdpan-storage 项目](https://github.com/baidu-netdisk/bdpan-storage)或[官方安装脚本页面](https://github.com/baidu-netdisk/bdpan-storage/blob/main/skills/baidu-drive/scripts/install.sh)，等用户确认后再继续。不静默下载或执行外部安装器。
5. 运行 `./scripts/login.sh`。脚本会尝试打开百度官方授权页；用户在浏览器登录，将 32 位授权码粘贴到终端并回车。授权码通过 stdin 提交，不出现在命令行。
6. 运行 `.venv/bin/python bin/panlib-library auth-status`。若 macOS Keychain 已有有效授权，不打开浏览器；只有状态为缺失或过期时，Agent 才给出绝对路径，由用户在自己可见的终端手动运行 `.venv/bin/python scripts/authorize_mcp_macos.py`，并在隐藏输入提示中粘贴完整官方回调 URL。回调、Token 不发送给 Agent。
   非 macOS 主机必须显式设置 `PANLIB_CREDENTIAL_BACKEND=external-command` 和绝对可执行的
   `PANLIB_CREDENTIAL_COMMAND`；该 helper 通过受限 JSON stdin/stdout 协议读写系统安全存储，
   不经 shell，Token 不进入 argv。仓库不提供明文凭证文件兼容路径。
7. 运行 `./bin/panlib-doctor`。只有顶层 `status=ready` 才继续。
8. 运行 `./scripts/preflight.sh`。只有 `status=ready` 才进入业务流程；这一步不打开浏览器、
   不输出 Token，用实际能力结果取代 Agent 对“完全访问”开关的猜测。

resource-id 的转存计划会先在 wrapper 内调用官方 `bdpan transfer list --json`
做只读分享探测。探测结果为 `valid` 才能生成计划；`expired` 或
`unverified` 都会停止，不会执行转存。链接和提取码只在 wrapper 子进程的
短暂 argv 中出现，不进入 Agent 的 stdout/stderr 或计划 JSON。

### 人工快速路径

```bash
git clone https://github.com/Ming-Sir-69/ai-netdisk-assistant.git
cd ai-netdisk-assistant
./scripts/bootstrap.sh
```

如果检查报告依赖缺失，在确认允许联网安装后：

```bash
./scripts/bootstrap.sh --install-deps
./scripts/login.sh
.venv/bin/python bin/panlib-library auth-status
# 仅在上一步报告缺失或过期时，由用户手动运行：
.venv/bin/python scripts/authorize_mcp_macos.py
./bin/panlib-doctor
./scripts/preflight.sh
```

`.env.example` 可选。需要修改云端根目录或命令路径时，复制为 `.env` 后再编辑；`.env` 被 Git 忽略，但发布前仍必须运行隐私扫描。

## 安全工作流

搜索、IMDb 查询、链接解析、链接验证和 doctor 是只读操作。用户明确提出“更新某部电影”时，
默认完整主链路是：识别旧资源 → 搜索与自动选择 → 转存 → 整理 → 同根归档旧资源与 Apps 残留
→ 最终读回验收。完整更新模式自动执行可恢复写入，**无需逐阶段确认**；每一步仍必须先生成
计划、写前重检、使用 `ondup=fail` 并写后验收。

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

现有权限已足够完成完整更新：官方 MCP 负责 `/我的资源` 读取与同根归档，转存 CLI 负责分享转存，
整理 CLI 负责 Apps 内建目录、移动和重命名。没有删除和覆盖权限保留了可恢复边界，**不需要新增网盘权限**。
双通道是落位策略，不是新增授权范围。

快速通道只在转存 CLI 明确提供确定性的 `--target-dir`/直达落位能力，且转存前清单确认单片、身份唯一、
无目标冲突、无不明文件时启用：先写入 `Movies/<规范目录>.importing.<run_id>`，在该目录内完成转存和规范命名，
验收通过后再变为正式目录。失败只留下可定位的 importing 目录，不进入 `_已归档_待删除`。

当前版本转存直达能力未提供，Agent 不得伪造 `--target-dir` 参数；自动退回兼容通道：转存到
`/apps/bdpan/片库/Movies` → 读取真实 `source_dir` → 创建规范目录并移动/重命名有效媒体 → 对仍有内容的
转存源做同根 `file_move` 归档。合集、目录型分享、清单不完整或含不明文件时也走兼容通道，不能把处理中
状态直接放入 `_已归档_待删除`。
若未来显式隔离处理中状态，目录固定为 `/apps/bdpan/片库/_待整理/<run_id>`，失败时保留以便恢复，
不得把它当作待删除归档。

### 既有资源迁入 Apps

对于用户已经保存在 `/我的资源/Movies` 的影视，使用 `panlib-library migrate` 把主视频和外挂字幕
逐项迁入 `/apps/bdpan/片库/Movies` 下的规范电影容器；不要修改 `BDPAN_BASE`，也不要直接调用 MCP。
目标容器缺失时，该入口先 `make_dir(rtype=0)`；容器已存在时只允许追加一个不重名媒体文件，再
`file_move(async=0,ondup=fail)`。执行必须使用同一计划的 `plan_ref`，并在写后验证源消失、目标唯一。
它不移动目录、不覆盖、不删除，**不得开放任意全盘移动**。原目录中的
非播放文件保留，残留目录仍通过同根 `archive` 进入待删除区。

1. **转存**：首次调用 `panlib-transfer` 只返回 `plan-only`计划；检查 `share_ref`、目标和冲突状态后，
   未命中风险规则就使用完全相同的参数加 `--execute` 自动执行。
2. **整理**：只有转存结果同时满足 `postcondition.status=verified`、`organize_ready=true` 且返回非空
   `source_dir` 时才可继续。先调用 `panlib-organize` 生成计划；无冲突时自动加 `--execute`，命中风险才暂停。
   organize 会把视频旁的 `.ass/.srt/.ssa/.sub/.sup/.vtt/.idx` 外挂字幕一并搬入目标目录；
   文件名含简体/繁体标记时分别规范为 `.zh-Hans`/`.zh-Hant`。不接收任何图片，
   也不接收 NFO/TXT/PDF 等供人阅读的说明文件；它们留在源目录，随旧目录归档待人工审核。

3. **MCP 归档**：先运行 `.venv/bin/python bin/panlib-library auth-status` 确认当前安全凭证后端，再用
   `.venv/bin/python bin/panlib-library archive` 生成 plan-only。归档根由源路径自动确定：
   `/我的资源/...` 只能进入 `/我的资源/_已归档_待删除`，`/apps/bdpan/片库/...` 只能进入
   `/apps/bdpan/片库/_已归档_待删除`，不得跨根归档。计划只包含官方
   `file_move(async=0,ondup=fail)`，并绑定
   `plan_ref`；同根且无冲突时自动使用相同参数加 `--execute --plan-ref`。写前重检源/目标，写后
   验收源消失且目标唯一存在。CLI 不提供任何 delete；归档内容由用户人工审核后再手动删除。

任何 `partial`、`unverified`、失败或歧义状态都必须停止；写操作不得自动重试。
旧版 `--remove-empty-source` 仅保留兼容解析但会立即返回 `INVALID_ARG`；源目录不由 organize 删除，
需要清理时必须按上面的 MCP `file_move` 归档流程人工审核。

详细状态机见 [SKILL.md](SKILL.md)，命令参数和 JSON 契约见 [docs/CLI_CONTRACT.md](docs/CLI_CONTRACT.md)。

## 统一影视命名契约

电影、剧集、动漫、纪录片、网剧及以后新增的所有影视类型使用同一个决策模型：**类别提供默认类型根目录，
宇宙和系列决定可选父层，形态只决定内容单元和文件名模板**。动漫、纪录片等类别均可按实际内容
选择单体或分集形态。

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

- 内容规范名：中国制作用中文正式片名，非中国制作用英文正式片名；所有类别使用同一判断。
- 通用层级：`类别根 / [分组节点 × 任意层] / 内容节点 / 文件`（2026-08-15 起为递归模型）。
- **分组节点**以 `.{series}` 结尾，其中可继续放分组节点或内容节点，**层数不限、无封闭名单**；
  不带该后缀的是**内容节点**，其中只放媒体文件与外挂字幕，不再有子目录。
- 漫威、DC 及任何其他聚合都只是普通分组节点，不再是特殊的“宇宙层”。
- 分组只在语义成立时建立，不创建空占位目录；程序不自行发明分组，必须由 manifest 显式声明。
- 类别根目录：`movie → Movies`、`tv → TV shows`、`anime → 动漫`、
  `documentary → Documentary`、`webdrama → 网剧`；其他类别必须显式配置。
- `/我的资源/<类型目录>/...` 与 `/apps/bdpan/片库/<类型目录>/...` 使用完全相同的相对结构。
- **IMDB 只在视频文件名上，文件夹一律不带 IMDB**。
- `single` 内容单元：`{内容规范名}.{年份}/`（不带 IMDB）；主媒体文件：
  `{内容规范名}.{年份}.{imdb-IMDb ID}.{清晰度}.{扩展名}`。
- `episode`/`season` 内容单元：`{作品规范名}.Sxx/`；主媒体文件分别为
  `{内容规范名}.SxxExx.{imdb-IMDb ID}.{清晰度}.{扩展名}` 和
  `{内容规范名}.Sxx.{imdb-IMDb ID}.{清晰度}.{扩展名}`。
- Loki 目标结构为 `TV shows/Loki.{series}/Loki.S01/` 与 `TV shows/Loki.{series}/Loki.S02/`，
  即 `Loki.{series}/Loki.S01`、`Loki.{series}/Loki.S02`；剧集一律进 `TV shows/`，
  不留在任何电影分组内。该层级判断适用于所有影视类型，而不是 Loki 专例。
- 外挂字幕与对应主媒体文件同主名，必要时在扩展名前增加 `.zh-Hans`/`.zh-Hant`。
- `episode` 缺季号或集号、`season` 缺季号、类别根未配置或身份不唯一时停止，不由 Agent 猜测。

### 公共 manifest v1 与身份契约

路径层级是 `类别根 / [分组节点 × 任意层] / 内容节点 / 文件`。manifest 用 `groups` 数组
按从外到内的顺序声明每一层分组名，**不校验分组名是否属于某个预设清单**；旧的 `universe`
单值字段（只接受 `marvel`/`dc`）已于 2026-08-15 废止。中国制作使用中文正式片名，
非中国制作使用英文正式片名。

字面例子：电影单元 `The Batman.2022/` 包含
`The Batman.2022.{imdb-tt1874999}.1080p.mkv`；国产电影单元 `中国机长.2019/` 包含
`中国机长.2019.{imdb-tt10218664}.2160p.mp4`；剧集作品层 `Loki/` 下的季目录为 `Loki.S01/`，单集文件为
`Loki.S01E01.{imdb-tt1286039}.1080p.mkv`，整季文件为
`Loki.S02.{imdb-tt1286039}.1080p.mkv`。

新的多条目或拆分目录必须使用 **manifest v1**。每个 item 绑定精确 `source_path`、可用的
`fs_id`/`size` 和规范化元数据；文件名不能确定电影身份，不能以模型记忆、目录序号或数字前缀替代
IMDb/源身份。`--manifest-file` plan-only 返回 `plan_ref`；执行必须带回同一 manifest 和精确
`--plan-ref`，并在写入前重新读取源/目标。现有平铺目录不会静默重排，必须先生成新的 manifest 或
legacy hierarchical plan，再按正常 postcondition 验收。

纯数字集名只在 `--expected-episodes N` 严格契约下允许：视频 stem 必须恰为 `1..N`，季号必须明确，
不得混入已解析集号；CLI 不会按文件顺序猜测季号或集号。用户的普通更新或整理请求是端到端任务，
不可停在 `plan-only`。任一计划或执行步骤失败或返回 `partial`，先重新读取当前状态并生成新计划，
不能静默跳过整理或归档。流程不覆盖、不删除、不自动重试、不自动回滚，也不直接调用 `bdpan`。

输入中的路径分隔符、遍历片段、控制字符和危险扩展名会被拒绝；同名冲突会在尽可能靠近写入前再次检查。但真实网盘 API 不提供本项目可控的原子事务，整理仍可能部分完成。

## 验证状态

- 254 项核心与集成测试已通过，包含受控 bdpan fake、离线 SeedHub fixture、OAuth/Keychain 交互、可替换凭证接口、官方 MCP SDK 契约、分层/manifest 执行、文档契约和隐私门禁。
- 2026-08-09 在发布候选目录运行 `PANLIB_NETWORK_SKIP=1 ./bin/panlib-doctor`，顶层状态为 `ready`；该检查不读取账号正文。
- **macOS 单片真实链路验收通过**：2026-08-09 使用《云中漫步》完成官方 MCP 旧资源识别、SeedHub 搜索、百度分享只读验证、转存、规范整理和 MCP 归档写后验收。当次历史验收曾纳入海报；现行规则已收紧为只接收主视频和外挂播放字幕，图片及说明文档统一留在源目录并移入同根待删除归档区。旧版资源与未纳入片库的内容只移动到待人工审核区，没有调用 delete。
- **可替换凭证接口后的单片真实链路验收通过**：同日使用《遇见你之前》再次完成 SeedHub 搜索、固定规则自动选取 4K 候选、转存、规范整理与两项 MCP 归档。最终目录包含规范命名的 2160p 视频和简体字幕；旧版资源与 Apps 空源仅移动到待人工审核区，没有调用 delete。一次旧计划因目标状态变化被 `plan_ref` 拒绝，重新只读生成计划后成功，证明漂移保护有效。
- 这些证据只覆盖两个受控电影样本及当时的外部服务状态，不代表 SeedHub/百度永久可达，也不代表无界整盘自动扫描已实现。`external-command` 接口经过自动化契约测试，但 Windows/Linux 安全存储实现和实机跨平台验收仍未提供。

## 隐私与开源门禁

- Agent 不读取、输出或保存 Token、Cookie、BDUSS、账号正文、账号密码、验证码或 OAuth 授权码。
- Agent 的标准路径把 SeedHub `resource-id` 直接交给 transfer。链接和提取码只在 transfer 进程内部解析；计划返回不包含提取码的 `share_ref` 指纹，确认执行时重新解析并核对它，Agent 的命令参数、stdout 和 stderr 都不出现链接或提取码。
- `panlib-extract` 与 transfer 的 `--url/--password` 只保留给人工兼容和诊断；它们可能把敏感值带入终端或会话记录，不属于 Agent 安全路径。
- 本地 pre-commit、`scripts/privacy-guard` 和 CI 历史扫描共同阻止凭证、个人路径、个人邮箱和过大二进制文件。
- `.gitignore` 是第一道防线，不是泄露保证。

开发者请先运行 `./scripts/setup-dev.sh`，发布细节见 [SECURITY.md](SECURITY.md) 和 [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)。
本次发布候选的可复核命令与边界见 [docs/VERIFICATION.md](docs/VERIFICATION.md)。

## 已知限制与路线图

- IMDb 只支持内置已知表或用户显式提供 `tt...` 标识，不调用豆瓣或 OMDb。
- SeedHub 网页结构变化时会返回 `PARSE`，不猜测新结构。
- SeedHub 解析优先使用 `.direct-pan`、`panLink` 和 `window.location` 直链；QR 回退需要 Pillow/zxing-cpp，且只读取受限同源图片（2 MiB、16 MP 上限）。
- 真实 bdpan 没有由本项目控制的原子 no-clobber；我们通过重检和停止规则缩小风险。
- 当前采用 macOS 优先策略；Windows/Linux 的原生安全存储开发与实机兼容测试暂缓。
  已保留 `external-command` 接口契约供后续继续，不捆绑未验收实现，也不提供明文文件回退。
- 后续方向：定期自动整理、批量处理效率、更多网盘、磁力链接与下载速率优化、更多资源库。

## 开发与许可

- [架构边界](docs/ARCHITECTURE.md)
- [CLI 契约](docs/CLI_CONTRACT.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [第三方许可声明](THIRD_PARTY_NOTICES.md)

本项目代码以 [MIT License](LICENSE) 开源，版权归 Eric Mingle。第三方代码与依赖保留各自原许可证和署名。

<!-- END PRESERVED DOCUMENTATION CONTRACT -->

</details>

---

Documentation maintained by **✦ EricMingle69** · [Ming-Sir-69](https://github.com/Ming-Sir-69)  
[Personal identity, licensing and permissions](PERSONAL-NOTICE.md) · The header follows your GitHub theme.
