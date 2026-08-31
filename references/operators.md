# 算子清单（internal components）

本文件是 `ai-netdisk-assistant` 的内部组件登记表，**不独立安装、不软链、不注册为 Skill**。
分类依据：`agent-skill-builder` 的 `artifact.py plan --independent no --requires-execution yes`
判定为 `kind=internal, parent=ai-netdisk-assistant`。

## 分层

```text
router       panlib-plan     意图 → 有序命令序列（纯规划，不做 I/O）
resilient    panlib-run      重试 + 断点续跑 + 可验证停机
             panlib-lib      查已有 / 验收合规（三态停机）
             panlib-share    浏览分享内部 / 按 fs_id 精准转存
primitives   panlib-transfer / panlib-organize / panlib-library / panlib-container ...
             单次、无重试、单一职责
```

**不要把韧性塞进 primitives**——会变得不可测试、不可 mock。
**不要让 router 做 I/O**——它必须保持为任何模型都能读懂的纯规划器。

## 算子契约

**读写边界必须在 help 里可见**——调用方不能靠猜。只读的可随意重跑，写网盘的均为可恢复操作（不删除、不覆盖）。

| 算子 | 子命令 | 副作用 | 停机语义 | 退出码 |
|---|---|---|---|---|
| `panlib-plan` | `list` / `show --task` | 只读 | 纯规划，不做 I/O | 0 |
| `panlib-lib` | `find` | 只读 | `DONE` / `CONTINUE` / `BLOCKED` | 0 / 0 / 2 |
| `panlib-lib` | `verify` | 只读 | 同上 | 0 / 1 / 2 |
| `panlib-share` | `browse` | 只读 | 返回 entries | 0 |
| `panlib-share` | `select` | **写网盘** | 默认 plan-only，`--execute` 才写 | 0 / 1 |
| `panlib-run` | `probe` | 只读 | healthy 与否 | 0 / 1 |
| `panlib-run` | `selfcheck` | 只读 | 算子齐备 | 0 / 1 |
| `panlib-run` | `transfer-select` | **写网盘** | 数量齐 = DONE | 0 / 1 / 2 |
| `panlib-run` | `organize-season` | **写网盘** | 源目录清空 = DONE | 0 / 1 / 2 |
| `panlib-run` | `archive` | **写网盘** | verified（不删除） | 0 / 1 |

**BLOCKED 一律非零退出**，且必须走 `emit_error`——`emit_success` 硬编码 exit 0，
BLOCKED 走它会让 `return 2` 永不生效，脚本化调用把失败读成成功。

## 为什么不拆成更多文件

`panlib-run` 同时含只读与写网盘子命令，看似该拆。但实测：子命令间共享的只是
**无状态工具函数**（`sh` / `cloud_list` / `build_manifest`），不是可变状态；
四个算子各 240–340 行，体量并非问题。真正的缺陷是**读写边界不可见**，
已通过 help 标注 `[只读]` / `[写网盘]` 解决——比拆成两个文件成本更低、
且不会让调用方为同一个意图记两个命令名。

判据见 `agent-skill-builder` 的「Split on responsibility, not on size」。

## 四条不变量

1. **读不到 ≠ 不存在**：`cloud_list` 失败返回 `None`，调用方禁止写 `or []`。
2. **判断要标注来源**：清晰度取自文件名而非 ffprobe 实测时，输出 `quality_source: "filename"`。
3. **进展用可观测量衡量**：循环靠"剩余文件数是否下降"判空转，不靠子命令返回码。
4. **部分完成不算成功**：requested ≠ landed 时必须非零退出。

## 归档

`runtime/_archived_2026-08-31/` 存放已被算子取代的一次性脚本，含两个实测失败方案
（缩短 plan→execute 窗口、description 指纹匹配），保留以防重走。**不要再调用。**
