# 0.1.0 发布验证证据

验证日期：2026-08-09（Asia/Shanghai）

## 本地发布候选

以下命令在仓库唯一源码目录执行，未登录账号、未读取凭证、未调用真实网盘写入：

| 验证 | 结果 |
|---|---|
| `.venv/bin/pip check` | 通过，无损坏依赖 |
| `.venv/bin/python -m unittest discover -s tests -p 'test*.py'` | 110/110 通过 |
| `.venv/bin/python -m compileall -q panlib bin vendor/seedhub-cli` | 通过 |
| 所有公开 CLI `--help` | 通过 |
| `bash -n` 检查 setup/login/doctor/privacy 脚本 | 通过 |
| `./scripts/privacy-guard --whole-tree` | 通过 |
| `PANLIB_NETWORK_SKIP=1 ./bin/panlib-doctor` | 顶层 `status=ready`，network=`skipped` |
| `git diff --check` | 通过 |

测试包含：配置优先级、路径包含、严格命名、stdout/stderr 脱敏、SeedHub 保留域名 fixture、OAuth fake、resource-id/share-ref 安全交接、transfer/organize plan-first、写前冲突与 TOCTOU、写后歧义、部分失败、空源移除状态、文档契约和隐私门禁。

## 证据边界

- SeedHub fixture 与 bdpan fake 只证明确定性工作流，不证明外部服务当前可达。
- 本次未执行 SeedHub/百度实时网络 smoke。
- 本次未执行真实网盘 transfer、organize 或空源移除；这些状态为 `untested`。
- Git 可达历史、Gitleaks 和 GitHub Actions 必须在公开发布提交上再次通过，远端 CI 才是清洁检出的最终证据。

发布后可在 [GitHub Actions](https://github.com/Ming-Sir-69/ai-netdisk-assistant/actions) 查看远端验收。
