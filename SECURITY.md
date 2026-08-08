# 安全策略

## 报告漏洞或凭证事故

请使用 [GitHub 私密安全报告](https://github.com/Ming-Sir-69/ai-netdisk-assistant/security/advisories/new)。不要在公开 Issue 中粘贴 Token、Cookie、BDUSS、分享链接、提取码、OAuth 授权码、账号信息或个人文件路径。

如果凭证曾进入 Git 历史，仅删除文件不足够：先在对应平台撤销/轮换凭证，再评估历史清理和已导出副本。

## 安全边界

- OAuth 密码、验证码、MFA 和授权码由用户在百度官方页面/本地终端完成，Agent 不代填。
- `scripts/login.sh` 只接受官方 HTTPS OAuth URL，授权码通过隐藏 stdin 提交。
- 不读取 `$HOME/.config/bdpan/` 的内容；doctor 仅根据退出码判断授权状态。
- 分享链接跳转只允许百度官方主机、已知路径和已知查询参数。SeedHub 中间页不自动跟随任意重定向。
- Agent 的索引资源路径只把 resource-id/link-index/share-ref 放入命令；分享 URL 与提取码在 transfer 内部解析和使用，不进入 Agent 参数或输出。执行时 share-ref 不一致会在 bdpan 写入前停止。
- `panlib-extract` 和 transfer 的 `--url/--password` 仅为人工兼容入口，可能进入 shell 历史或会话记录；不要在共享终端或 Agent 状态机中使用。bdpan 上游没有本项目可用的 stdin 转存接口，内部子进程参数仍是残余边界。
- 云端写入必须在 `BDPAN_BASE` 内。transfer/organize 都是 plan-first，默认不写。
- 不保证真实网盘 API 的原子 no-clobber。项目用写前重检、fail-fast 和禁止自动重试缩小风险。

## 开发与发布扫描

```bash
./scripts/setup-dev.sh
./scripts/privacy-guard --whole-tree
./scripts/privacy-guard --history
```

pre-commit 扫描 staged blobs；whole-tree 扫描当前跟踪与未跟踪文件；history 扫描可达 Git 历史和提交元数据。CI 另用锁定版本 Gitleaks 检查完整历史。

扫描工具是防线，不是凭证可以进入仓库的理由。测试 fixture 只能使用 `.example` 保留域名和明显假数据。
