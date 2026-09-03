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
| `panlib-lib` | `find` | 只读 | `DONE` / `CONTINUE` / `BLOCKED` | 0 / 0 / 1 |
| `panlib-lib` | `verify` | 只读 | 同上 | 0 / 1 / 1 |
| `panlib-master` | `query` | 只读 | `NEEDS_QUERY` / `CACHED` | 0 |
| `panlib-master` | `record` | 只写本地台账 | 记一条证据（或确认无证据） | 0 / 1 |
| `panlib-master` | `verdict` | 只读 | `NATIVE_CAP_2K` / `NATIVE_CAP_4K` / `UNKNOWN_CONSERVATIVE` / `CONFLICTING_EVIDENCE` / `NOT_QUERIED` | 0 / 0 / 0 / 1 / 1 |
| `panlib-audit` | `--path` | 只读 | findings 清单（含 unreadable_directory） | 0 / 1 |
| `panlib-search` | `--keyword` | 只读 | results 列表 | 0 / 1 |
| `panlib-imdb` | `--title --year` | 只读 | imdb_id | 0 / 1 |
| `panlib-offlinedl` | `add` | **写网盘** | 默认 plan-only，`--execute` 才提交 | 0 / 1 |
| `panlib-offlinedl` | `status` / `who` | 只读 | 任务状态 / 登录态 | 0 / 1 |
| `panlib-container` | `rename` | **写网盘** | 同父目录改名，写后验收 | 0 / 1 |
| `panlib-share` | `browse` | 只读 | 返回 entries | 0 |
| `panlib-share` | `select` | **写网盘** | 默认 plan-only，`--execute` 才写 | 0 / 1 |
| `panlib-run` | `probe` | 只读 | healthy 与否 | 0 / 1 |
| `panlib-run` | `selfcheck` | 只读 | 算子齐备 | 0 / 1 |
| `panlib-run` | `transfer-select` | **写网盘** | 数量齐 = DONE | 0 / 1 |
| `panlib-run` | `organize-season` | **写网盘** | 源目录清空 = DONE | 0 / 1 |
| `panlib-run` | `archive` | **写网盘** | verified（不删除） | 0 / 1 |

**BLOCKED 一律非零退出**，且必须走 `emit_error`——`emit_success` 硬编码 exit 0，
BLOCKED 走它会让 `return 2` 永不生效，脚本化调用把失败读成成功。

**注意 `emit_error` 硬编码 `SystemExit(1)`**（2026-09-03 实测确认）：函数体里
写的 `return 2` 是**死代码**，永远不会生效——`emit_error` 在 return 之前就退出了。
本表此前记的 `2` 与实际行为不符，已按实测改为 `1`。调用方**只能判断
「是否为 0」，不能依赖具体的非零值区分错误类型**；要区分请读 stdout JSON 里的
`error.code` 与 `error.details.status`。新增算子时不要再写 `return 2` 并假设它
会传出去。

## 解释器分派：按 shebang，不按印象（2026-09-03 实测教训）

`bin/` 下**不全是 Python**：`panlib-doctor` 是 bash 脚本，其余是 Python。
用 `.venv/bin/python` 去跑 bash 脚本会得到 `SyntaxError: unmatched ')'`——
这是**检查方式错了**，不是那个算子坏了。实测中我据此误报过一次"它的 --help 坏了"。

正确做法（`tests/test_operator_spec.py::ExecutabilityTests` 已固化）：
读首行 shebang，含 `bash` 就用 bash 跑，否则用项目解释器。

**每个算子都必须响应 `--help`，包括不面向 Agent 的内部子进程。**
`panlib-mcp-bridge` 是 stdin JSON 协议、本不需要命令行入口，但"没有 --help"
无法自证是**故意如此**还是**坏了**——调用方每次都要重新判断一遍。现已给它
一个说明自身定位的 `--help`，把这条隐性知识变成它自己会讲的话。

CI 的 help 巡检**必须自动发现** `bin/panlib-*`，不得维护硬编码清单：
此前那份清单漏掉了 10 个算子（audit/container/lib/library/master/offlinedl/
plan/run/sandbox/share），且失效方式是静默的——新增算子不受检查、也没人收到通知。

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

## 绿皮书回归沉淀（2026-09-02）

本次电影入库暴露三条可泛化规则：

1. **类型是路由输入，不是装饰字段**：电影和剧集的目标结构、验收字段、整理模式不同；不能让一个“升级画质”配方默认生成季目录。
2. **每种内容形态必须有对应验收器**：原 `panlib-lib verify` 只遍历季目录，电影会出现 `DONE` 但 `qualities=[]`。现在 `--type movie` 直接检查电影内容节点、主视频、字幕、规范命名和文件名清晰度。
3. **没有安全原语时必须停机**：远端抽样 + ffprobe 尚未封装前，升级配方（当前仅剧集）必须返回 `BLOCKED`，禁止让模型直调网盘下载命令。宁可暂缓升级，也不能越过封装边界。

**开放项**：实现 `quality-probe` 前，需要先获得受控的远端 Range/分段读取能力；现有下载接口只能整文件下载，不能安全抽样。此项不需要用户手工协助，但需要新增并验证底层能力。

电影回归样本：`Green.Book.2018`，1 个 2160p 视频 + 1 个 `zh-Hans` 字幕，`find --type movie` 与 `verify --type movie` 均返回 `DONE`，清晰度来源为 `filename`。
## 归档

`runtime/_archived_2026-08-31/` 存放已被算子取代的一次性脚本，含两个实测失败方案
（缩短 plan→execute 窗口、description 指纹匹配），保留以防重走。**不要再调用。**
