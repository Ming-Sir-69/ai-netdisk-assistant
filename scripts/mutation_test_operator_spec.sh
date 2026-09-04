#!/usr/bin/env bash
# 变异测试：验证 tests/test_operator_spec.py 真的是一道防线，而不是摆设。
#
# 为什么需要它：一个永远不会失败的测试等于没有测试。本仓库实测过这个陷阱——
# 规格最初把 panlib-master 写进豁免清单（理由是"它已被引用"），结果把该算子
# 从所有配方摘掉后规格依然全绿：豁免清单吃掉了它本该发出的警报。
#
# 更微妙的第二个陷阱：第一版变异脚本只替换了 `panlib-master query`，而配方里
# 还有 `panlib-master record`，算子其实仍然可达——此时规格保持绿色是**正确**的，
# 是变异没做到位。**变异测试自身也会有 bug，看到"没拦住"要先怀疑变异，
# 再怀疑规格。**
#
# 用法：bash scripts/mutation_test_operator_spec.sh
# 期望：三个变异全部 RED，基线与还原后全部 GREEN。任何一个 GREEN(未拦住)
#       都说明规格出现了盲区，必须先修规格再提交。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PLAN=bin/panlib-plan
SKILL=SKILL.md
BAK=$(mktemp -d)
cp "$PLAN" "$BAK/plan"
cp "$SKILL" "$BAK/skill"
cp bin/panlib-mcp-bridge "$BAK/bridge0"
cp .github/workflows/ci.yml "$BAK/ci0"
cp bin/panlib-transfer "$BAK/transfer0"
cp bin/panlib-lib "$BAK/lib0"

restore() {
  cp "$BAK/plan" "$PLAN"
  cp "$BAK/skill" "$SKILL"
  cp "$BAK/bridge0" bin/panlib-mcp-bridge
  cp "$BAK/ci0" .github/workflows/ci.yml
  cp "$BAK/transfer0" bin/panlib-transfer
  cp "$BAK/lib0" bin/panlib-lib
}
trap restore EXIT

fails=0

check() {
  label="$1"
  expect="$2"
  .venv/bin/python -m unittest tests.test_operator_spec > "$BAK/out.txt" 2>&1
  got="RED"
  grep -qE "^OK$" "$BAK/out.txt" && got="GREEN"
  if [ "$got" = "$expect" ]; then
    echo "  [PASS] $label -> $got (符合预期)"
  else
    echo "  [FAIL] $label -> $got (预期 $expect)"
    grep -oE "AssertionError: .{0,80}" "$BAK/out.txt" | head -2 | sed 's/^/      /'
    fails=$((fails + 1))
  fi
}

# 文本替换一律走 Python，不用 sed —— `sed -i ''` 是 macOS 语法，GNU sed 会把
# 那个空字符串当成文件名（实测 CI 报 `sed: can't read s|…|…|g`），于是变异
# 根本没生效、规格保持绿色，脚本却把"没拦住"判成失败。本地全绿、CI 全红，
# 正是本轮反复强调的那种平台差异，必须用可移植写法根除。
sub() {  # sub <文件> <原文> <替换> [count]
  SUB_FILE="$1" SUB_OLD="$2" SUB_NEW="$3" SUB_COUNT="${4:-0}" python3 -c '
import os, pathlib
p = pathlib.Path(os.environ["SUB_FILE"])
old, new = os.environ["SUB_OLD"], os.environ["SUB_NEW"]
count = int(os.environ["SUB_COUNT"])
text = p.read_text(encoding="utf-8")
if old not in text:
    raise SystemExit(f"变异目标未找到，脚本已过期: {old!r} in {p}")
p.write_text(text.replace(old, new, count) if count else text.replace(old, new),
             encoding="utf-8")
'
}

echo "[基线]"
check "未变异" GREEN

echo "[变异1] 摘掉 panlib-master 的全部引用（重演「写了没接线」）"
sub "$PLAN" "bin/panlib-master" "bin/panlib-NOTHING"
check "算子不可达" RED
restore

echo "[变异2] 配方引用不存在的子命令（重演 panlib-audit scan 那个 bug）"
sub "$PLAN" "bin/panlib-audit --path" "bin/panlib-audit scan --path" 1
check "配方腐烂" RED
restore

echo "[变异3] SKILL 路由表漏掉一个配方"
sub "$SKILL" '`audit-library`' '`REMOVED`' 1
check "路由表缺项" RED
restore

echo "[变异4] 拿掉 mcp-bridge 的 --help（重演「不能自证是故意还是坏了」）"
sub bin/panlib-mcp-bridge '    if any(a in ("-h", "--help") for a in sys.argv[1:]):' '    if False:' 1
check "算子无法自证" RED
restore

echo "[变异5] CI 退回硬编码清单（重演「新增算子静默不受检查」）"
sub .github/workflows/ci.yml 'for cli in bin/panlib-*' 'for cli in bin/panlib-imdb' 1
check "CI 硬编码清单" RED
restore

echo "[变异6] 类别根映射漂移（重演「动漫→Animation 漏改一份」）"
sub bin/panlib-transfer '"anime": "Animation"' '"anime": "动漫"' 1
check "映射副本漂移" RED
restore

echo "[变异7] 复活 emit_error 后的死代码 return 2"
MUT_FILE=bin/panlib-lib python3 -c '
import os, pathlib, re
p = pathlib.Path(os.environ["MUT_FILE"])
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
for i, line in enumerate(lines):
    if re.match(r"^\s*return 1\s*$", line) and "emit_error" in "".join(lines[max(0, i - 10):i]):
        lines[i] = line.replace("return 1", "return 2")
        break
else:
    raise SystemExit("变异目标未找到，脚本已过期：没有 emit_error 后的 return 1")
p.write_text("".join(lines), encoding="utf-8")
'
check "死代码 return 2" RED
restore

echo "[还原]"
check "还原后" GREEN

echo
if [ "$fails" -eq 0 ]; then
  echo "变异测试全部通过：规格确实能拦住这三类回归。"
else
  echo "变异测试失败 $fails 项——规格有盲区，先修规格再提交。"
fi
exit "$fails"
