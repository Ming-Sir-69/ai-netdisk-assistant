# macOS 发布候选验证证据

验证日期：2026-08-09（Asia/Shanghai）

## 本地发布候选

以下本地门禁在仓库唯一源码目录执行；测试与日志不输出 Token、分享链接、提取码或账号正文：

| 验证 | 结果 |
|---|---|
| `.venv/bin/pip check` | 通过，无损坏依赖 |
| `.venv/bin/python -m unittest discover -s tests -p 'test*.py'` | 151/151 通过 |
| `.venv/bin/python -m compileall -q panlib bin vendor/seedhub-cli` | 通过 |
| 所有公开 CLI `--help` | 通过 |
| `bash -n` 检查 setup/login/doctor/privacy 脚本 | 通过 |
| `./scripts/privacy-guard --whole-tree` | 通过 |
| `PANLIB_NETWORK_SKIP=1 ./bin/panlib-doctor` | 顶层 `status=ready`，network=`skipped` |
| `git diff --check` | 通过 |

测试包含：配置优先级、路径包含、严格命名、stdout/stderr 脱敏、SeedHub 直链/QR fixture、确定性候选排序、OAuth/Keychain、官方 MCP SDK bridge、resource-id/share-ref 安全交接、transfer/organize/archive plan-first、写前冲突与 TOCTOU、写后歧义、部分失败、无删除归档、文档契约和隐私门禁。

## 真实单片链路

2026-08-09 在用户明确授权的单片范围内，以《云中漫步》完成 macOS 真实验收：

1. 官方 MCP 读取并定位旧版资源；未做无差别整盘扫描。
2. SeedHub 搜索得到单片资源，多候选按固定规则选中蓝光 REMUX 候选；分享只读探测为 `valid`、顶层单项。
3. `panlib-transfer` 计划、确认、单次执行后，写后验收得到唯一 `source_dir`。
4. `panlib-organize` 将视频、简繁 SUP 字幕和海报整理到 IMDb 规范目录；最终只读回验为 1 个视频、2 个字幕和 `poster.jpg`。
5. 官方 MCP `file_move` 将旧版资源和不纳入片库的截图残留移至待人工审核区，源消失、目标唯一存在，`postcondition.status=verified`；没有调用 delete。

整理过程中曾在部分旁车文件已移动后遇到一次外部目录读回异常。流程按 fail-fast 停止，先用独立 MCP 读取现状，再由新的 plan 完成剩余海报移动；没有自动重试写操作，也没有重复转存。

## 证据边界

- 单片真实验收只证明 2026-08-09 当时的 SeedHub、百度分享、bdpan 与官方 MCP 链路可用，不保证外部服务持续可达。
- 当前不支持无界整盘扫描、自动删除、Windows/Linux 凭证存储或跨平台验收。
- macOS 授权存入系统 Keychain；只有 Keychain 缺失或过期时才由用户在可见终端完成浏览器授权，后续非交互检查由 Agent 执行。
- Git 可达历史、Gitleaks 和 GitHub Actions 必须在公开发布提交上再次通过，远端 CI 才是清洁检出的最终证据。

发布后可在 [GitHub Actions](https://github.com/Ming-Sir-69/ai-netdisk-assistant/actions) 查看远端验收。
