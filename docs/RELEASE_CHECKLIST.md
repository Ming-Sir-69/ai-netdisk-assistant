# 发布检查表

## 状态语义

- `verified`：有本次可复现执行证据。
- `static-only`：仅静态审查通过。
- `partial`：链路中部分环节通过，不可声称端到端成功。
- `untested`：本次未执行。

0.1.0 的实际执行记录见 [VERIFICATION.md](VERIFICATION.md)；本文件保留为每次发布都需重新执行的清单。

## 本地门禁

- [ ] Python 版本满足 3.13+，`.venv/bin/pip check` 通过。
- [ ] 完整 unittest 通过，包含 docs contract、fake mutation 和 privacy guard。
- [ ] `compileall` 通过；doctor help 直接执行，其余 Python CLI 的 help 通过 `.venv/bin/python` 执行。
- [ ] bootstrap/login/doctor 只读或 fake 验收通过，不输出账号正文。
- [ ] SeedHub 离线 fixture 只包含 `.example` 保留域名和假提取码。
- [ ] transfer/organize 默认 plan-only，写前冲突和写后状态测试通过。

## 隐私与 Git

- [ ] `scripts/privacy-guard --whole-tree` 通过。
- [ ] `scripts/privacy-guard --history` 通过。
- [ ] Gitleaks 使用仓库 `.gitleaks.toml` 扫描完整可达历史。
- [ ] 可达历史仅包含公开身份 `Eric Mingle <164483854+Ming-Sir-69@users.noreply.github.com>`。
- [ ] 无 `.env`、凭证、个人绝对路径、真实分享链接、账号信息和本地大文件。
- [ ] 仓库是原位唯一源码副本，无 alternates、嵌套上游 `.git` 或额外 worktree。

## 文档与许可

- [ ] README 的一句话安装方式、GitHub URL、官方 bdpan 链接和 OAuth 交互仍有效。
- [ ] `SKILL.md` 与实际 `--help` 一致，三个确认点不可绕过。
- [ ] `LICENSE` 保留标准 MIT 正文和 Eric Mingle 署名。
- [ ] vendor 许可证与第三方署名原样保留，`THIRD_PARTY_NOTICES.md` 与实际依赖一致。

## 外部验收

- [ ] 仓库 URL 可公开 clone，清洁 clone 中 bootstrap 与 CI 通过。
- [ ] GitHub Actions 绿色，仓库描述、topics 和 License 识别正确。
- [ ] 只读网络 smoke 单独记录成功/失败，不与离线 fixture 混为“端到端通过”。

## 真实网盘写入

发布不默认授权真实网盘写入。执行前必须获得用户对以下全部内容的明确同意：

1. 唯一测试资源或分享链接。
2. 唯一云端目标目录。
3. 允许的 transfer/organize/空目录移除范围。
4. 成功标准、残留物和清理方式。

执行后必须使用只读列表对照已确认的每个 action 和 `data.cleanup`；不能仅凭 exit 0 宣称转存、整理或空源移除完成。

未授权时标记 `untested`；仅转存或仅只读环节成功时标记 `partial`。
