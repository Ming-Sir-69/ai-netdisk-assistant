from __future__ import annotations

import re
import subprocess
import sys
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
            "panlib-library archive",
            "file_move",
            "plan_ref",
            "人工审核后再手动删除",
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
        self.assertIn("github.com/zricethezav/gitleaks/v8@v8.24.2", ci)
        self.assertNotIn("github.com/gitleaks/gitleaks/v8", ci)
        self.assertIn("--config .gitleaks.toml", ci)
        self.assertNotIn("--config-path", ci)
        self.assertIn('"status": ..., "checks": ..., "next_steps": [...]', cli_contract)
        self.assertIn("error.details.completed", cli_contract)
        self.assertIn("panlib-library archive", cli_contract)
        self.assertIn("file_move", cli_contract)
        self.assertIn("plan_ref", cli_contract)
        self.assertIn("--remove-empty-source", cli_contract)
        self.assertIn("已禁用", cli_contract)
        self.assertIn("不会调用 `rm`", cli_contract)
        self.assertNotIn("data.cleanup", cli_contract)
        self.assertIn("preset-quality-v1", cli_contract)
        self.assertIn("selection.selected", cli_contract)
        self.assertNotIn("多候选返回 `INVALID_ARG`", cli_contract)
        for document in (self.read("README.md"), self.read("SKILL.md")):
            self.assertIn("scripts/authorize_mcp_macos.py", document)
            self.assertIn("已有有效授权", document)
            self.assertIn("external-command", document)
            self.assertIn("不提供明文文件回退", document)

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

    def test_readme_reports_bounded_live_e2e_without_overclaiming_safety(self):
        readme = self.read("README.md")
        for stale in (
            "6 个 CLI",
            "4 部候选验证通过",
            "同名目录自动跳过",
            "你的任何配置都不会泄露",
            "cloudscraper](https://github.com/VeNoMouS/cloudscraper)（AGPL",
        ):
            self.assertNotIn(stale, readme)
        self.assertNotIn("未执行真实网盘写入验收", readme)
        self.assertIn("macOS 单片真实链路验收通过", readme)
        self.assertIn("《云中漫步》", readme)
        self.assertIn("MCP 归档写后验收", readme)
        self.assertIn("《遇见你之前》", readme)
        self.assertIn("可替换凭证接口", readme)
        self.assertIn("254 项核心与集成测试已通过", readme)
        self.assertRegex(readme, r"(?s)转存.*plan-only.*--execute")

    def test_update_workflow_derives_same_root_archive_and_excludes_non_playback_files(self):
        readme = self.read("README.md")
        skill = self.read("SKILL.md")
        cli_contract = self.read("docs/CLI_CONTRACT.md")
        architecture = self.read("docs/ARCHITECTURE.md")

        for document in (readme, skill):
            self.assertIn("默认完整主链路", document)
            self.assertIn("不接收任何图片", document)
            self.assertIn("/我的资源/_已归档_待删除", document)
            self.assertIn("/apps/bdpan/片库/_已归档_待删除", document)
            self.assertIn("不得跨根归档", document)
            self.assertIn("`.venv/bin/python`", document)
            self.assertIn("中国制作", document)
            self.assertIn("{内容规范名}.{年份}", document)
            self.assertIn("{内容规范名}.{年份}.{imdb-IMDb ID}.{清晰度}.{扩展名}", document)

        for document in (readme, skill):
            self.assertIn("scripts/preflight.sh", document)
            self.assertIn("完全访问", document)
            self.assertIn("Codex", document)
            self.assertIn("WorkBuddy", document)

        self.assertIn("`--archive-dir` 可选", cli_contract)
        self.assertIn("由 `--source` 自动推导", cli_contract)
        self.assertIn("同根归档", architecture)
        self.assertIn("macOS 优先", architecture)
        self.assertIn("Windows/Linux", architecture)

    def test_conversation_initialization_uses_two_level_mode_selection(self):
        for document in (self.read("README.md"), self.read("SKILL.md")):
            self.assertIn("对话初始化与模式选择", document)
            self.assertIn("使用类", document)
            self.assertIn("测试类", document)
            self.assertIn("更新《这个杀手不太冷》", document)
            self.assertIn("默认完整更新", document)
            self.assertIn("/我的资源", document)
            self.assertIn("/apps/bdpan/片库", document)
            self.assertIn("找不到再询问用户", document)
            self.assertIn("模式卡", document)

    def test_skill_defines_agent_readable_recovery_journal_without_human_log_review(self):
        skill = self.read("SKILL.md")
        for item in (
            "Agent 可读恢复台账",
            "不面向用户展示完整日志",
            "run_id",
            "source_path",
            "target_path",
            "completed_actions",
            "failed_action",
            "recovery_read_paths",
            "不得猜测文件去向",
            "台账缺失或字段不全",
            "original_cli_code",
            "next_action",
            "JRN-001",
            "JRN-002",
            "JRN-003",
            "RCV-001",
            "RCV-002",
            "RCV-003",
            "RCV-004",
            "RCV-005",
        ):
            self.assertIn(item, skill)

    def test_default_update_uses_risk_based_confirmation(self):
        for document in (self.read("README.md"), self.read("SKILL.md")):
            for item in (
                "风险分级确认",
                "完整更新模式自动执行",
                "无需逐阶段确认",
                "不可逆",
                "权限变化",
                "目标冲突",
                "歧义",
            ):
                self.assertIn(item, document)

    def test_channel_and_approval_boundaries_have_single_unambiguous_tables(self):
        for document in (self.read("README.md"), self.read("SKILL.md")):
            for item in (
                "通道能力矩阵（唯一权限判定）",
                "官方百度网盘 MCP",
                "bdpan wrappers",
                "MCP 的全盘读取能力",
                "风险分级确认：自动执行与暂停（唯一审批判定）",
                "本表是唯一审批判定来源",
                "模式即视为已明确授权该模式定义范围内的写入",
                "旧版目录、空壳目录和未入库残留",
                "不得再次要求逐阶段确认",
            ):
                self.assertIn(item, document)
            self.assertNotIn("以及用户没有明确表达写入意图", document)

        agents = self.read("AGENTS.md")
        self.assertNotIn("空源移除是第三个独立确认点", agents)
        self.assertIn("同根归档按 `SKILL.md` 风险分级自动执行", agents)

    def test_skill_defines_dual_channel_landing_and_current_permission_boundary(self):
        for document in (self.read("README.md"), self.read("SKILL.md")):
            for item in (
                "双通道落位",
                "快速通道",
                "兼容通道",
                "importing.<run_id>",
                "_待整理/<run_id>",
                "直达能力未提供",
                "现有权限已足够",
                "不需要新增网盘权限",
                "不进入 `_已归档_待删除`",
            ):
                self.assertIn(item, document)

    def test_docs_define_restricted_cross_root_library_migration(self):
        documents = (
            self.read("README.md"),
            self.read("SKILL.md"),
            self.read("docs/CLI_CONTRACT.md"),
            self.read("docs/ARCHITECTURE.md"),
            self.read("AGENTS.md"),
        )
        for document in documents:
            for item in (
                "panlib-library migrate",
                "/我的资源/Movies",
                "/apps/bdpan/片库/Movies",
                "ondup=fail",
                "不得开放任意全盘移动",
                "受限跨根迁移",
            ):
                self.assertIn(item, document)

    def test_docs_define_one_media_naming_contract_for_all_library_categories(self):
        documents = (
            self.read("README.md"),
            self.read("SKILL.md"),
            self.read("docs/CLI_CONTRACT.md"),
            self.read("docs/ARCHITECTURE.md"),
        )
        for document in documents:
            for item in (
                "统一影视命名契约",
                "类别提供默认类型根目录",
                "形态只决定内容单元和文件名模板",
                "single",
                "episode",
                "season",
                "/我的资源/<类型目录>",
                "/apps/bdpan/片库/<类型目录>",
                "电影、剧集、动漫、纪录片、网剧",
                "内容规范名",
                "主媒体文件",
            ):
                self.assertIn(item, document)
        self.assertNotIn("## 电影命名契约", self.read("SKILL.md"))

    def test_docs_define_recursive_group_and_item_media_hierarchy(self):
        # 2026-08-15：层级由写死的「类型根/宇宙/作品系列/内容单元」改为递归的
        # 「类别根 / 分组节点×任意层 / 内容节点」。分组节点以 .{series} 结尾，
        # 层数不限且没有封闭名单——漫威、DC 不再是特殊的「宇宙层」。
        documents = (
            self.read("README.md"),
            self.read("SKILL.md"),
            self.read("docs/CLI_CONTRACT.md"),
            self.read("docs/ARCHITECTURE.md"),
        )
        for document in documents:
            for item in (
                "类别根 / [分组节点 × 任意层] / 内容节点 / 文件",
                "分组节点",
                "内容节点",
                ".{series}",
                "层数不限",
                "Loki.{series}/Loki.S01",
                "Loki.{series}/Loki.S02",
                "所有影视类型",
            ):
                self.assertIn(item, document)
            # 旧的僵化契约不得复活
            for banned in (
                "类型根 / 宇宙（可选）/ 作品系列（可选）/ 内容单元 / 文件",
                "宇宙覆盖类别根",
            ):
                self.assertNotIn(banned, document)
        skill = self.read("SKILL.md")
        self.assertIn("通用影视层级约束", skill)
        self.assertNotIn("系列电影结构约束（强制）", skill)

    def test_docs_define_public_manifest_identity_and_hierarchy_contract(self):
        skill = self.read("SKILL.md")
        readme = self.read("README.md")
        cli_contract = self.read("docs/CLI_CONTRACT.md")
        architecture = self.read("docs/ARCHITECTURE.md")
        verification = self.read("docs/VERIFICATION.md")

        for document in (skill, readme, cli_contract, architecture, verification):
            self.assertIn(
                "类别根 / [分组节点 × 任意层] / 内容节点 / 文件",
                document,
            )
            self.assertIn("文件名不能确定电影身份", document)
            self.assertIn("现有平铺目录", document)
            self.assertIn("重新读取当前状态并生成新计划", document)
            for boundary in ("不覆盖", "不删除", "不自动重试", "不自动回滚"):
                self.assertIn(boundary, document)

        for document in (skill, readme, cli_contract, architecture):
            self.assertIn("manifest v1", document)
            for field in ("source_path", "fs_id", "size", "plan_ref"):
                self.assertIn(field, document)

        # 分组节点不得再有封闭名单：manifest 用 groups 数组声明，
        # 文档里不能重新出现「只允许 marvel/dc 两个宇宙」这类固定映射。
        for document in (skill, readme, cli_contract, architecture):
            self.assertIn("groups", document)
            for banned in ("宇宙目录键只有", "宇宙键只有", "宇宙覆盖类别根"):
                self.assertNotIn(banned, document)

        for document in (skill, readme, cli_contract, architecture, verification):
            self.assertIn("--expected-episodes", document)
            self.assertIn("1..N", document)
            self.assertIn("纯数字", document)
            self.assertIn("猜测季号或集号", document)

    def test_organize_help_exposes_manifest_and_numeric_episode_arguments(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "panlib-organize"), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for argument in ("--manifest-file", "--plan-ref", "--expected-episodes"):
            self.assertIn(argument, completed.stdout)


if __name__ == "__main__":
    unittest.main()
