# Changelog

## 0.1.0 - 2026-08-09

- 新增搜索、IMDb 本地解析、链接提取、链接验证、转存、整理和环境诊断 7 个 CLI。
- 转存与整理采用 plan-first，只有显式 `--execute` 才会写入。
- 新增安全 OAuth 引导、幂等 bootstrap、doctor 与结构化错误契约。
- 新增路径包含检查、严格命名、冲突防护、写前重检与写后状态核验。
- Agent 转存改为 resource-id/share-ref 安全交接，分享链接和提取码不进入 Agent 参数或输出。
- 新增隐私扫描、pre-commit 门禁和 GitHub Actions CI。
- 新增离线 SeedHub fixture 和受控 bdpan fake 集成测试。

### 验证边界

- 2026-08-09 的自动化测试与跳过网络的本机只读 doctor 已通过。
- 外部实时网络可达性未纳入当前发布验收。
- 本版发布前未执行真实网盘写入验收。
