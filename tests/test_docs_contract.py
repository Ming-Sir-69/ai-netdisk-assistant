from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicDocumentationContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_one_line_install_prompt_and_real_repository_url_are_prominent(self):
        readme = self.read("README.md")
        prompt = (
            "Codex帮我安装这个工作流然后开始整理网盘资源 "
            "https://github.com/Ming-Sir-69/ai-netdisk-assistant"
        )
        self.assertIn(prompt, readme[:1800])
        self.assertNotIn("github.com/yourname", readme)

    def test_skill_is_discoverable_and_forbids_unsafe_shortcuts(self):
        skill = self.read("SKILL.md")
        self.assertRegex(skill, r"(?m)^description:\s*>?-?\s*$|^description:\s+Use when")
        self.assertIn("Use when", skill[:800])
        for stale in (
            "--auto-organize",
            "--douban-id",
            "bdpan user_info",
            "bdpan login",
            "WorkBuddy",
        ):
            self.assertNotIn(stale, skill)
        self.assertIn("禁止直接调用 `bdpan`", skill)
        self.assertIn("Agent 不调用 `panlib-extract`", skill)
        self.assertNotIn("bin/panlib-extract --resource-id", skill)
        self.assertIn("不得猜测 `source_dir`", skill)
        self.assertIn("不得自动重试写操作", skill)

    def test_skill_state_machine_requires_plan_confirm_execute_and_verified_handoff(self):
        skill = self.read("SKILL.md")
        required = (
            "plan-only",
            "--execute",
            "postcondition.status=verified",
            "--resource-id",
            "--link-index",
            "--share-ref",
            "share_ref",
            "organize_ready=true",
            "source_dir",
            "--remove-empty-source",
            "第三次独立确认",
            "partial",
            "unverified",
        )
        for item in required:
            self.assertIn(item, skill)

    def test_public_docs_exist_and_match_project_safety_boundaries(self):
        required = (
            "docs/ARCHITECTURE.md",
            "docs/CLI_CONTRACT.md",
            "docs/RELEASE_CHECKLIST.md",
            "docs/VERIFICATION.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "AGENTS.md",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)
        self.assertTrue((ROOT / "CLAUDE.md").is_symlink())
        self.assertEqual((ROOT / "CLAUDE.md").readlink(), Path("AGENTS.md"))

        architecture = self.read("docs/ARCHITECTURE.md")
        cli_contract = self.read("docs/CLI_CONTRACT.md")
        security = self.read("SECURITY.md")
        contributing = self.read("CONTRIBUTING.md")
        release = self.read("docs/RELEASE_CHECKLIST.md")
        self.assertIn("plan-first", architecture)
        self.assertIn("非事务", architecture)
        self.assertIn("7 个 CLI", cli_contract)
        self.assertIn("失败不得自动重试", cli_contract)
        self.assertIn("Token", security)
        self.assertIn("scripts/privacy-guard --whole-tree", security)
        self.assertIn("先写失败测试", contributing)
        self.assertIn("真实网盘写入", release)
        self.assertIn("partial", release)
        self.assertRegex(
            self.read(".github/workflows/ci.yml"),
            r'python-version:\s*["\']3\.13["\']',
        )
        ci = self.read(".github/workflows/ci.yml")
        self.assertIn('.venv/bin/python "$cli" --help', ci)
        self.assertIn('"status": ..., "checks": ..., "next_steps": [...]', cli_contract)
        self.assertIn("error.details.completed", cli_contract)
        self.assertIn("data.cleanup", cli_contract)

    def test_license_and_third_party_attribution_are_exact(self):
        license_lines = self.read("LICENSE").splitlines()
        self.assertEqual(license_lines[0], "MIT License")
        self.assertEqual(license_lines[2], "Copyright (c) 2026 Eric Mingle")

        vendor_lines = self.read("vendor/seedhub-cli/LICENSE").splitlines()
        self.assertEqual(vendor_lines[0], "MIT License")
        self.assertIn("Cali Castle", vendor_lines[2])

        notices = self.read("THIRD_PARTY_NOTICES.md")
        self.assertNotIn("Task 7", notices)
        self.assertIn("cloudscraper", notices)
        self.assertIn("MIT", notices)
        self.assertIn("bdpan-storage", notices)
        self.assertIn("Apache-2.0", notices)
        self.assertIn("081b273c5842560e7be15949a5970dc3da25ede0", notices)

    def test_readme_does_not_claim_unverified_live_write_or_automatic_safety(self):
        readme = self.read("README.md")
        for stale in (
            "6 个 CLI",
            "4 部候选验证通过",
            "同名目录自动跳过",
            "你的任何配置都不会泄露",
            "cloudscraper](https://github.com/VeNoMouS/cloudscraper)（AGPL",
        ):
            self.assertNotIn(stale, readme)
        self.assertIn("未执行真实网盘写入验收", readme)
        self.assertRegex(readme, r"(?s)转存.*plan-only.*--execute")


if __name__ == "__main__":
    unittest.main()
