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

restore() { cp "$BAK/plan" "$PLAN"; cp "$BAK/skill" "$SKILL"; }
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

echo "[基线]"
check "未变异" GREEN

echo "[变异1] 摘掉 panlib-master 的全部引用（重演「写了没接线」）"
sed -i '' 's|bin/panlib-master|bin/panlib-NOTHING|g' "$PLAN"
check "算子不可达" RED
restore

echo "[变异2] 配方引用不存在的子命令（重演 panlib-audit scan 那个 bug）"
sed -i '' 's|bin/panlib-audit --path|bin/panlib-audit scan --path|' "$PLAN"
check "配方腐烂" RED
restore

echo "[变异3] SKILL 路由表漏掉一个配方"
python3 -c "
import pathlib
p = pathlib.Path('$SKILL')
p.write_text(p.read_text(encoding='utf-8').replace('\`audit-library\`', '\`REMOVED\`', 1), encoding='utf-8')
"
check "路由表缺项" RED
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
