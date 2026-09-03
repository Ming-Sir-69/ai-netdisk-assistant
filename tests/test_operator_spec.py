"""算子体系的统一规格（可执行版）——把「审查时才发现」变成「提交时就拦住」。

## 为什么需要这个文件

本仓库反复出现的最贵失败，根因高度一致：**不是推理能力不足，而是信息缺失**——
"不知道有某个工具"、"不知道该按什么顺序做"。SKILL.md 为此建了路由器 panlib-plan，
把顺序性知识从"需要模型记住"变成"查一下就有"。

但 2026-09-03 的对抗性审查发现：**路由器自己没有被任何机制保护**。

实测到的三类真实缺陷，全部属于"写了但没接线"：
- `panlib-master` 写完后，路由器、selfcheck、CLI 契约里一处都没提它——
  一个模型永远不会发现的算子，等于没写；
- SKILL.md 把磁力称为"路线 A 首选"，但没有任何配方引用 `panlib-offlinedl`——
  声称的首选路线对模型不可达；
- `panlib-audit` / `sweep-empty` 实测解决过真问题，却不在任何配方里，
  只能靠"碰巧记得"才会被用到。

散文文档拦不住这类问题——**文档会被跳过，测试不会**。本文件因此是可执行的规格：
每条不变量都对应一个会失败的断言。

## 五条不变量

1. **可达性**：每个面向 Agent 的算子必须至少被一个配方引用，否则模型发现不了它。
2. **配方不腐烂**：配方里引用的每个 CLI 与子命令都必须真实存在且可运行。
3. **停机语义诚实**：BLOCKED/冲突类结论必须非零退出，不能被读成成功。
4. **文档与实现一致**：算子清单、CLI 契约、SKILL 路由表必须覆盖真实存在的算子。
5. **写操作可恢复**：任何写网盘的算子都不得新增删除能力。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
PY = ".venv/bin/python"
VENV_PY = ROOT / ".venv" / "bin" / "python"

# 不面向 Agent 的算子，豁免"必须被配方引用"。每一条都必须写明理由——
# 豁免清单是本规格唯一的逃生舱，不写理由就会变成藏污纳垢的地方。
#
# ★ 变异测试教训（2026-09-03）：最初把 panlib-master 也写进了这里，理由是
#   "它已被配方引用"——这恰恰让豁免清单吃掉了它。变异测试把 panlib-master
#   从所有配方里摘掉后，规格竟然还是绿的：**一个被豁免的算子，无论接没接线
#   都不会报警**。豁免的语义只能是"这个算子本来就不该出现在配方里"，
#   绝不能是"它已经接好了"——后者属于断言，必须由测试验证，不是由清单声明。
NOT_AGENT_FACING = {
    "panlib-doctor": "安装状态机专用，由 SKILL 的安装流程直接调用，不属于业务配方",
    "panlib-mcp-bridge": "panlib-library 的内部子进程，不是给 Agent 的入口",
    "panlib-extract": "SKILL 明确写着「Agent 不调用」，仅作人工诊断兼容入口",
    "panlib-verify": "同上，人工诊断兼容入口",
    "panlib-sandbox": "真机沙箱演练入口，仅在改动高风险代码时由人工使用",
    "panlib-plan": "路由器自身，是所有配方的入口，不需要被配方引用",
}

# 必须被至少一个配方引用的关键算子。这是正向断言，与上面的豁免清单相反：
# 豁免说"可以不接线"，这里说"必须接线"。每一条都对应一次真实的接线遗漏。
MUST_BE_REACHABLE = {
    "panlib-master": "母版判定；写完后曾三处未接线，模型完全发现不了",
    "panlib-offlinedl": "SKILL 称其为「路线 A 首选」，却一度没有任何配方引用它",
    "panlib-audit": "全库审计，实测解决过真问题，却只能靠「碰巧记得」才会被用到",
    "panlib-share": "browse 是识破虚标候选的唯一手段，跳过它会拿错版本",
    "panlib-lib": "「先查已有」是最高频的浪费来源，必须在配方第一步",
}


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(VENV_PY), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def recipes() -> dict[str, dict]:
    proc = run(str(BIN / "panlib-plan"), "list")
    tasks = [r["task"] for r in json.loads(proc.stdout)["data"]["recipes"]]
    out = {}
    for t in tasks:
        p = run(str(BIN / "panlib-plan"), "show", "--task", t)
        out[t] = json.loads(p.stdout)["data"]
    return out


def all_commands() -> list[tuple[str, str]]:
    """返回配方里出现的所有 (task, cmd)。"""
    return [(t, s["cmd"]) for t, d in recipes().items() for s in d["steps"]]


class ReachabilityTests(unittest.TestCase):
    """不变量 1：写了但没接线的算子 = 没写。"""

    def test_every_agent_facing_operator_is_reachable_from_some_recipe(self):
        referenced = set()
        for _, cmd in all_commands():
            referenced.update(re.findall(r"bin/(panlib-[a-z-]+)", cmd))

        existing = {p.name for p in BIN.glob("panlib-*") if p.is_file()}
        orphans = sorted(existing - referenced - set(NOT_AGENT_FACING))

        self.assertEqual(
            orphans, [],
            "以下算子存在但任何配方都不引用，模型永远发现不了它们。\n"
            "要么把它接进配方，要么加进 NOT_AGENT_FACING 并写明理由：\n  "
            + "\n  ".join(orphans),
        )

    def test_named_critical_operators_are_actually_wired_into_recipes(self):
        """正向断言：这几个算子必须真的出现在某个配方里。

        与豁免清单相反——豁免清单只能让一个算子"不被检查"，
        它无法证明任何算子"已接好"。每次接线遗漏都在这里加一条。
        """
        referenced = set()
        for _, cmd in all_commands():
            referenced.update(re.findall(r"bin/(panlib-[a-z-]+)", cmd))

        for name, why in MUST_BE_REACHABLE.items():
            self.assertIn(name, referenced,
                          f"{name} 必须被至少一个配方引用（{why}），"
                          f"否则模型发现不了它")

    def test_no_operator_is_both_exempted_and_required(self):
        """两张清单不能重叠——重叠会让豁免悄悄压过强制要求。"""
        overlap = sorted(set(NOT_AGENT_FACING) & set(MUST_BE_REACHABLE))
        self.assertEqual(overlap, [], f"算子同时出现在豁免与必需清单: {overlap}")

    def test_exemption_list_has_no_stale_entries(self):
        """豁免清单不能引用已删除的算子——否则它会悄悄失去保护作用。"""
        existing = {p.name for p in BIN.glob("panlib-*") if p.is_file()}
        stale = sorted(set(NOT_AGENT_FACING) - existing)
        self.assertEqual(stale, [], f"豁免清单里的算子已不存在: {stale}")

    def test_every_exemption_states_a_reason(self):
        for name, reason in NOT_AGENT_FACING.items():
            self.assertTrue(reason.strip(), f"{name} 的豁免理由为空")


class RecipeIntegrityTests(unittest.TestCase):
    """不变量 2：配方腐烂 = 模型照着执行会直接报错。"""

    def test_recipes_only_reference_existing_clis(self):
        missing = set()
        for task, cmd in all_commands():
            for cli in re.findall(r"bin/(panlib-[a-z-]+)", cmd):
                if not (BIN / cli).is_file():
                    missing.add(f"{task} → {cli}")
        self.assertEqual(sorted(missing), [], f"配方引用了不存在的算子: {sorted(missing)}")

    def test_recipes_only_reference_existing_subcommands(self):
        """实测教训：曾写出 `panlib-audit scan`，而该 CLI 根本没有子命令，只有 --path。

        照着执行会直接失败——这正是配方必须被机器校验、不能靠人眼的原因。
        """
        bad = []
        helps: dict[str, str] = {}
        for task, cmd in all_commands():
            m = re.search(r"bin/(panlib-[a-z-]+)\s+([a-z][a-z0-9-]*)", cmd)
            if not m:
                continue
            cli, sub = m.groups()
            path = BIN / cli
            if not path.is_file():
                continue
            if cli not in helps:
                h = run(str(path), "--help")
                helps[cli] = h.stdout if h.returncode == 0 else ""
            if helps[cli] and sub not in helps[cli]:
                bad.append(f"{task} → {cli} {sub}")
        self.assertEqual(sorted(bad), [], f"配方引用了不存在的子命令: {sorted(bad)}")

    def test_every_step_carries_why_expect_and_on_fail(self):
        """三个字段是配方的全部价值：没有它们，配方退化成一串命令。"""
        incomplete = []
        for task, data in recipes().items():
            for i, s in enumerate(data["steps"], 1):
                for field in ("why", "expect", "on_fail"):
                    if not str(s.get(field, "")).strip():
                        incomplete.append(f"{task} step{i}.{field}")
        self.assertEqual(sorted(incomplete), [], f"步骤缺少必填字段: {sorted(incomplete)}")

    def test_every_recipe_declares_why_it_must_not_be_skipped(self):
        for task, data in recipes().items():
            self.assertTrue(str(data.get("critical", "")).strip(),
                            f"{task} 缺少 critical 说明")


class HaltingSemanticsTests(unittest.TestCase):
    """不变量 3：把「需要人裁决」读成「成功」是最危险的失败模式。"""

    def test_emit_error_always_exits_nonzero_so_return_2_is_dead_code(self):
        """锁死一条已实测的事实：emit_error 硬编码 SystemExit(1)。

        算子里写的 `return 2` 永远不生效。调用方只能判断「是否为 0」，
        要区分错误类型必须读 JSON 的 error.code。references/operators.md
        此前记的退出码 2 与实际不符，已修正。
        """
        sys.path.insert(0, str(ROOT / "panlib"))
        import common  # noqa: E402

        with self.assertRaises(SystemExit) as raised:
            common.emit_error("NOT_FOUND", "x", {"status": "BLOCKED"})
        self.assertEqual(raised.exception.code, 1)

    def test_master_verdict_blocks_on_conflicting_evidence(self):
        """冲突时必须非零退出，而不是悄悄取最大值。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "l.jsonl"
            env = {"PANLIB_MASTER_LEDGER": str(ledger), "PATH": "/usr/bin:/bin"}
            for src, ev in (("dvdbeaver", "restored in 2K"), ("bluray_com", "new 4K scan")):
                subprocess.run(
                    [str(VENV_PY), str(BIN / "panlib-master"), "record",
                     "--title", "C", "--year", "2000", "--source", src, "--evidence", ev],
                    cwd=ROOT, capture_output=True, text=True, env=env)
            p = subprocess.run(
                [str(VENV_PY), str(BIN / "panlib-master"), "verdict",
                 "--title", "C", "--year", "2000"],
                cwd=ROOT, capture_output=True, text=True, env=env)
            self.assertNotEqual(p.returncode, 0)
            self.assertEqual(
                json.loads(p.stdout)["error"]["details"]["status"],
                "CONFLICTING_EVIDENCE")


class DocumentationConsistencyTests(unittest.TestCase):
    """不变量 4：文档说有、实际没有（或反之）会直接误导模型。"""

    def read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_operators_reference_lists_every_agent_facing_operator(self):
        doc = self.read("references/operators.md")
        referenced = set()
        for _, cmd in all_commands():
            referenced.update(re.findall(r"bin/(panlib-[a-z-]+)", cmd))
        missing = sorted(n for n in referenced if n not in doc)
        self.assertEqual(missing, [], f"references/operators.md 未收录: {missing}")

    def test_cli_contract_documents_every_agent_facing_operator(self):
        doc = self.read("docs/CLI_CONTRACT.md")
        referenced = set()
        for _, cmd in all_commands():
            referenced.update(re.findall(r"bin/(panlib-[a-z-]+)", cmd))
        missing = sorted(n for n in referenced if n not in doc)
        self.assertEqual(missing, [], f"docs/CLI_CONTRACT.md 未收录: {missing}")

    def test_skill_routing_table_covers_every_recipe(self):
        """SKILL 的意图路由表必须能把用户的话映射到每一个配方。

        配方存在但路由表没写 = 用户说了对应的话，模型也找不到它。
        """
        skill = self.read("SKILL.md")
        missing = sorted(t for t in recipes() if t not in skill)
        self.assertEqual(missing, [], f"SKILL.md 路由表未覆盖的配方: {missing}")

    def test_skill_no_longer_claims_the_movie_upgrade_recipe_is_missing(self):
        """SKILL 曾长期写着「电影升级配方待补」——待补状态本身就是风险来源。"""
        skill = self.read("SKILL.md")
        self.assertNotIn("电影升级配方待补", skill)


class WriteSafetyTests(unittest.TestCase):
    """不变量 5：可恢复边界是这个项目最重要的安全属性。"""

    def test_no_operator_gains_a_delete_capability(self):
        """归档（file_move）是唯一允许的"清理"，删除必须由用户在 App 里手动做。"""
        forbidden = re.compile(r"\b(file_delete|filemanager.*delete|--delete\b)")
        offenders = []
        for p in BIN.glob("panlib-*"):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                if forbidden.search(line) and "不删除" not in line and "禁止" not in line:
                    offenders.append(f"{p.name}:{lineno}")
        self.assertEqual(offenders, [],
                         f"检测到疑似删除能力，本项目只允许归档: {offenders}")

    def test_recipes_never_instruct_calling_bdpan_directly(self):
        for task, cmd in all_commands():
            # 只检查真正会被执行的命令；echo 出来的告警文本里提到 bdpan 是
            # 在**禁止**它，不是在调用它。
            if cmd.lstrip().startswith("echo "):
                continue
            self.assertNotRegex(
                cmd, r"(?<!panlib-)\bbdpan\s",
                f"{task} 的命令直调了 bdpan，SKILL 明确禁止")


if __name__ == "__main__":
    unittest.main()
