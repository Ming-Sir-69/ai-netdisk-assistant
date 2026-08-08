# AI 网盘助手

> 把“搜索影视资源 → 验证链接 → 转存百度网盘 → 规范命名”固化为 Agent 可调度的确定性工作流。

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 最简单的使用方式

把下面这句话发给 Codex：

> Codex帮我安装这个工作流然后开始整理网盘资源 https://github.com/Ming-Sir-69/ai-netdisk-assistant

Agent 应在同一个目录完成下载、环境检查和授权引导，不创建第二份源码副本。安装后它会先确认你要处理的影视资源或精确云端路径；当前版本不会无差别扫描整个网盘。

## 当前能力

- 连接百度网盘，引导用户在百度官方页面完成 OAuth。
- 从 SeedHub 搜索少量影视资源，提取并验证百度网盘分享链接。
- 按电影、剧集、纪录片、动漫、网剧分类转存。
- 按 IMDb 标识和媒体信息生成整理计划，用户确认后执行。

当前只支持百度网盘写入，资源索引也只接入 SeedHub。它不是通用网盘客户端，也不支持磁力链接下载。

## 安装与初始化

### Agent 路径

1. 如果本地已有该仓库，必须复用现有目录；否则只 clone 一次。
2. 进入仓库根目录，运行 `./scripts/bootstrap.sh`。该命令执行本地初始化检查，必要时创建项目 `.venv`，但默认不联网下载依赖。
3. 如果缺少 Python 依赖，先向用户说明会联网安装的内容；获得同意后才运行 `./scripts/bootstrap.sh --install-deps`。
4. 如果缺少 `bdpan`，打开[百度官方 bdpan-storage 项目](https://github.com/baidu-netdisk/bdpan-storage)或[官方安装脚本页面](https://github.com/baidu-netdisk/bdpan-storage/blob/main/skills/baidu-drive/scripts/install.sh)，等用户确认后再继续。不静默下载或执行外部安装器。
5. 运行 `./scripts/login.sh`。脚本会尝试打开百度官方授权页；用户在浏览器登录，将 32 位授权码粘贴到终端并回车。授权码通过 stdin 提交，不出现在命令行。
6. 运行 `./bin/panlib-doctor`。只有顶层 `status=ready` 才进入业务流程。

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
./bin/panlib-doctor
```

`.env.example` 可选。需要修改云端根目录或命令路径时，复制为 `.env` 后再编辑；`.env` 被 Git 忽略，但发布前仍必须运行隐私扫描。

## 安全工作流

搜索、IMDb 查询、链接解析、链接验证和 doctor 是只读操作。写入分两个阶段：

1. **转存**：首次调用 `panlib-transfer` 只返回 `plan-only`计划；展示目标目录并获得用户确认后，使用完全相同的参数加 `--execute`。
2. **整理**：只有转存结果同时满足 `postcondition.status=verified`、`organize_ready=true` 且返回非空 `source_dir` 时才可继续。先调用 `panlib-organize` 生成计划，再获得第二次确认后加 `--execute`。

`--remove-empty-source` 必须在 organize 尚未执行时加入计划，展示 `verify-empty`/`rm` 后获得第三次单独授权，然后整个 organize 只执行一次。CLI 在末尾重读确认为空才移除，默认不使用。任何 `partial`、`unverified`、失败或歧义状态都必须停止；写操作不得自动重试。

详细状态机见 [SKILL.md](SKILL.md)，命令参数和 JSON 契约见 [docs/CLI_CONTRACT.md](docs/CLI_CONTRACT.md)。

## 命名结果

- 文件夹：`{Name}.{imdb-ttXXXXXXX}/`
- 电影：`{Title}.{Year}.{Quality}.{ext}`
- 剧集：`{Title}.SxxExx.{imdb-ttXXXXXXX}.{Quality}.{ext}`
- 整季：`{Title}.Sxx.{imdb-ttXXXXXXX}.{Quality}.{ext}`

输入中的路径分隔符、遍历片段、控制字符和危险扩展名会被拒绝；同名冲突会在尽可能靠近写入前再次检查。但真实网盘 API 不提供本项目可控的原子事务，整理仍可能部分完成。

## 验证状态

- 110 项核心与集成测试已通过，包含受控 bdpan fake、离线 SeedHub fixture、OAuth 交互、文档契约和隐私门禁。
- 2026-08-09 在发布候选目录运行 `PANLIB_NETWORK_SKIP=1 ./bin/panlib-doctor`，顶层状态为 `ready`；该检查不读取账号正文。
- 当前发布证据不包含外部 SeedHub/百度实时网络可达性；离线 fixture 通过不代表外部站点当前可用。
- **未执行真实网盘写入验收**：未获得精确测试目录、资源与清理范围授权前，不声称真实端到端通过。

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
- 真实 bdpan 没有由本项目控制的原子 no-clobber；我们通过重检和停止规则缩小风险。
- 后续方向：定期自动整理、批量处理效率、更多网盘、磁力链接与下载速率优化、更多资源库。

## 开发与许可

- [架构边界](docs/ARCHITECTURE.md)
- [CLI 契约](docs/CLI_CONTRACT.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [第三方许可声明](THIRD_PARTY_NOTICES.md)

本项目代码以 [MIT License](LICENSE) 开源，版权归 Eric Mingle。第三方代码与依赖保留各自原许可证和署名。
