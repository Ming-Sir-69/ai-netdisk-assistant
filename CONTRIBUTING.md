# 贡献指南

## 开发环境

1. 使用 Python 3.13+。
2. 运行 `./scripts/bootstrap.sh`；需要安装依赖时显式使用 `--install-deps`。
3. 运行 `./scripts/setup-dev.sh` 安装隐私 pre-commit。

## 修改流程

- **先写失败测试**，运行并观察它因预期缺陷失败；再写最小实现，最后运行受影响测试和全量测试。
- 不把决策逻辑从 CLI 退回 Agent prompt。新的路径、命名、脱敏、冲突或错误契约必须有行为测试。
- 不改变 plan-first 默认。新写操作必须有显式开关、用户确认语义、写前重检和失败停止证据。
- 改变 CLI 参数或 JSON 时，同步 `SKILL.md`、`docs/CLI_CONTRACT.md` 和 README。
- 不在 PR 测试中访问真实账号、真实分享链接或真实网盘写入。使用 `tests/fakes/` 和 `.example` fixture。

## vendor 修改

`vendor/seedhub-cli` 是本地补丁版。修改前必须：

1. 核对上游来源、版本或 commit 和许可证。
2. 保留上游 `LICENSE`。
3. 在 `THIRD_PARTY_NOTICES.md` 记录补丁与 provenance 边界。
4. 保证离线 fixture 只由显式参数激活，不允许环境变量改写正式目标。

## 提交前

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python -m compileall -q panlib bin vendor/seedhub-cli
./scripts/privacy-guard --whole-tree
git diff --check
```

提交作者使用公开的 GitHub noreply 邮箱。不降低隐私规则来让提交通过；应修复数据或历史。
