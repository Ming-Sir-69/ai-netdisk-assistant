# Changelog

## Unreleased - 2026-08-19

- `panlib-imdb` 改为默认联网查询（Wikidata）：`--title` 必须配 `--year`；内置已知表降为测试夹具，仅 `--known-table` 显式启用；`--online` 保留但废弃。
- 联网查询增加降级源：Wikidata 不可达时自动走 IMDb suggestion API；降级源空候选不算「查过且没有」，两路都不通才报 NETWORK。
- 全部网盘读取解析点改走 resilient 通道：`file_list` 对含 `&` 或全角括号【】的路径会失败（errno 1002），现在自动降级到关键词搜索，且搜索 key 支持多候选重试（规格词如"1080P蓝光原盘"排最后，优先中文片名 token）。
- SKILL.md 新增：参数纪律（以 --help 与 CLI_CONTRACT.md 为唯一事实源，禁止脑补参数名）、合集分享处理流程、无百度候选降级表、"验收用直读不用搜索"规则。

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
