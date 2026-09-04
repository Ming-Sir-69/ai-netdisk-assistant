from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_GUARD = REPO_ROOT / "scripts" / "privacy-guard"
SETUP_DEV = REPO_ROOT / "scripts" / "setup-dev.sh"
BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git") or "git"


def run_command(
    args: list[str], *, cwd: Path, env: dict[str, str] | None = None, input_text: str = ""
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env or {})
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=merged,
            input=input_text,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        # Keep RED assertions readable when a planned command does not exist yet.
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_command(
        [GIT, *args],
        cwd=root,
        env={
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Fixture Author",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture Committer",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
    )


def init_repo(root: Path) -> None:
    result = git(root, "init", "-q")
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    for key, value in (
        ("user.name", "Fixture Author"),
        ("user.email", "fixture@example.invalid"),
    ):
        result = git(root, "config", key, value)
        if result.returncode != 0:
            raise AssertionError(result.stderr)


def commit_all(root: Path, message: str = "fixture") -> subprocess.CompletedProcess[str]:
    staged = git(root, "add", "--all")
    if staged.returncode != 0:
        raise AssertionError(staged.stderr)
    return git(root, "commit", "-qm", message)


class PrivacyGuardTests(unittest.TestCase):
    def run_guard(self, root: Path, mode: str) -> subprocess.CompletedProcess[str]:
        return run_command([str(PRIVACY_GUARD), mode], cwd=root)

    def test_safe_placeholders_and_spaces_pass_staged_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            safe = root / "safe fixture with spaces.md"
            safe.write_text(
                """# Fixture
                Maintainer: fixture@users.noreply.github.com
                Docs: https://pan.baidu.example/s/fake-share-90001?pwd=abcd
                Path: /Users/alice/example-project
                Token: <REDACTED>
                """,
                encoding="utf-8",
            )
            result = git(root, "add", "--", safe.name)
            self.assertEqual(result.returncode, 0, result.stderr)

            scan = self.run_guard(root, "--staged")

            self.assertEqual(scan.returncode, 0, scan.stdout + scan.stderr)

    def test_staged_scan_reports_each_sensitive_class_without_secret_text(self):
        cases = (
            (
                "personal-path",
                "mac path.txt",
                "/Users/" + "eric-mingle-69/Documents/private/project\n",
                "eric-mingle-69",
            ),
            (
                "personal-email",
                "author.txt",
                "Maintainer: person" + "@protonmail.com\n",
                "person" + "@protonmail.com",
            ),
            (
                "credential",
                "settings.txt",
                "BDUSS=" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6" + "\n",
                "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6",
            ),
            (
                "credential",
                "headers.txt",
                "Authorization: Bearer " + "tok_1234567890ABCDEFGHIJKL" + "\n",
                "tok_1234567890ABCDEFGHIJKL",
            ),
            (
                "private-key",
                "private-key.txt",
                "-----BEGIN " + "PRIVATE KEY-----\nfixture-material\n-----END PRIVATE KEY-----\n",
                "fixture-material",
            ),
            (
                "forced-credential-file",
                "credentials.json",
                '{"account": "fixture"}\n',
                '"account": "fixture"',
            ),
            (
                "baidu-share",
                "share.txt",
                "https://pan.baidu.com/s/" + "1AbCdEfGhIjKlMnOpQrStUv?pwd=Qwer\n",
                "1AbCdEfGhIjKlMnOpQrStUv",
            ),
        )
        for expected_class, filename, content, secret in cases:
            with self.subTest(expected_class=expected_class):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    init_repo(root)
                    (root / filename).write_text(content, encoding="utf-8")
                    staged = git(root, "add", "--", filename)
                    self.assertEqual(staged.returncode, 0, staged.stderr)

                    scan = self.run_guard(root, "--staged")
                    output = scan.stdout + scan.stderr

                    self.assertEqual(scan.returncode, 1, output)
                    self.assertIn(expected_class, output)
                    self.assertIn(filename, output)
                    self.assertNotIn(secret, output)

    def test_journal_files_are_judged_by_content_not_by_name(self):
        """凭证台账不能仅因文件名含 auth/token 就被判为凭据文件。

        实测缺陷（2026-09-03）：`runtime/reauth_journal.jsonl` 只记
        ts/target/error_code/next_action，却因名字里的 `auth_` 被判
        forced-credential-file。它已被 gitignore，所以 CI 的干净 checkout
        扫不到、恒绿，而本地 `--whole-tree` 恒红——**本地红 + CI 绿会训练人
        忽略真实告警**，比漏报一次更危险。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            name = "reauth_journal.jsonl"
            (root / name).write_text(
                '{"ts": "2026-08-30T15:44:53Z", "target": "mcp", '
                '"error_code": "WEBBRIDGE_EXTENSION_NOT_CONNECTED", '
                '"next_action": "start_webbridge_or_reconnect_extension"}\n',
                encoding="utf-8",
            )
            self.assertEqual(git(root, "add", "--", name).returncode, 0)
            scan = self.run_guard(root, "--staged")
            self.assertEqual(scan.returncode, 0, scan.stdout + scan.stderr)

    def test_real_credential_filenames_are_still_blocked_by_name(self):
        """台账豁免必须收窄——第一版按后缀豁免，把真凭据文件一起放行了。

        `credentials.json` / `token.json` 这类文件本身就是凭据容器，
        无论内容如何都必须按名字拦截。
        """
        for name in ("credentials.json", "token.json", "secret.json"):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    init_repo(root)
                    (root / name).write_text('{"account": "fixture"}\n', encoding="utf-8")
                    self.assertEqual(git(root, "add", "--", name).returncode, 0)
                    scan = self.run_guard(root, "--staged")
                    output = scan.stdout + scan.stderr
                    self.assertEqual(scan.returncode, 1, output)
                    self.assertIn("forced-credential-file", output)

    def test_credentials_inside_a_journal_are_still_caught_by_content(self):
        """放行台账不等于放宽安全边界：真凭据写进台账仍必须被拦。

        配套修复：值两侧的 `"` `}` 此前没被剥掉，候选串因"含引号/括号"
        被当作代码片段跳过，导致 JSON 形态的 access_token / BDUSS **完全漏报**。
        这个洞此前被文件名规则掩盖，一旦按内容判定台账就会暴露——两处必须同修。
        """
        cases = {
            "access_token": '{"ts": "x", "access_token": '
                            '"ya29.' + "A" * 32 + '"}\n',
            "BDUSS": '{"ts": "x", "BDUSS": "' + "b" * 40 + '"}\n',
            "refresh_token": '{"ts": "x", "refresh_token": "1//0' + "c" * 32 + '"}\n',
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    init_repo(root)
                    name = "reauth_journal.jsonl"
                    (root / name).write_text(content, encoding="utf-8")
                    self.assertEqual(git(root, "add", "--", name).returncode, 0)
                    scan = self.run_guard(root, "--staged")
                    output = scan.stdout + scan.stderr
                    self.assertEqual(scan.returncode, 1, output)
                    self.assertIn("credential", output)

    def test_identifier_references_in_source_are_not_credentials(self):
        """源码里 `"password": effective_password,` 引用的是变量，不是密码。

        这是放宽正则以覆盖 JSON 形态后引入的误报（实测 bin/panlib-transfer:321）。
        仓库内已跟踪的源码触发误报会直接让 CI 变红，必须精确区分。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            name = "resolver.py"
            (root / name).write_text(
                "def build(effective_password):\n"
                "    return {\n"
                '        "password": effective_password,\n'
                '        "access_token": stored_token,\n'
                "    }\n",
                encoding="utf-8",
            )
            self.assertEqual(git(root, "add", "--", name).returncode, 0)
            scan = self.run_guard(root, "--staged")
            self.assertEqual(scan.returncode, 0, scan.stdout + scan.stderr)

    def test_literal_secrets_are_still_caught_even_when_identifier_shaped(self):
        """标识符豁免不得放走真凭据——每条都对应一次实测到的回归。

        `api_key = "sk_live_999…"` 加了引号；`BDUSS=A_A_…_ZZZZ` 是裸赋值但
        由随机片段构成。两者在放宽过程中都曾被误放行，必须锁死。
        """
        cases = {
            "quoted-underscore-token": 'api_key = "sk_live_' + "9" * 30 + '"\n',
            "bare-random-underscores": "BDUSS=" + "A_" * 12 + "Z" * 8 + "\n",
            "json-access-token": '{"access_token": "ya29.' + "A" * 32 + '"}\n',
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    init_repo(root)
                    name = "config.txt"
                    (root / name).write_text(content, encoding="utf-8")
                    self.assertEqual(git(root, "add", "--", name).returncode, 0)
                    scan = self.run_guard(root, "--staged")
                    output = scan.stdout + scan.stderr
                    self.assertEqual(scan.returncode, 1, output)
                    self.assertIn("credential", output)

    def test_staged_scan_rejects_oversized_binary_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            binary = root / "fixture with spaces.bin"
            binary.write_bytes(b"\x00\x01" + os.urandom(1_100_000))
            staged = git(root, "add", "--", binary.name)
            self.assertEqual(staged.returncode, 0, staged.stderr)

            scan = self.run_guard(root, "--staged")
            output = scan.stdout + scan.stderr

            self.assertEqual(scan.returncode, 1, output)
            self.assertIn("large-binary", output)
            self.assertIn(binary.name, output)

    def test_staged_mode_ignores_unstaged_unsafe_file_but_whole_tree_catches_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "README.md").write_text("safe fixture\n", encoding="utf-8")
            self.assertEqual(commit_all(root).returncode, 0)
            unsafe = root / "not staged yet.txt"
            unsafe.write_text("BDUSS=" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4" + "\n", encoding="utf-8")

            staged_scan = self.run_guard(root, "--staged")
            whole_scan = self.run_guard(root, "--whole-tree")

            self.assertEqual(staged_scan.returncode, 0, staged_scan.stdout + staged_scan.stderr)
            self.assertEqual(whole_scan.returncode, 1, whole_scan.stdout + whole_scan.stderr)
            self.assertIn("credential", whole_scan.stdout + whole_scan.stderr)
            self.assertIn(unsafe.name, whole_scan.stdout + whole_scan.stderr)
            self.assertNotIn("Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4", whole_scan.stdout + whole_scan.stderr)

    def test_setup_dev_installs_hook_and_preserves_unmanaged_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(PRIVACY_GUARD, scripts / "privacy-guard")
            shutil.copy2(SETUP_DEV, scripts / "setup-dev.sh")
            (scripts / "privacy-guard").chmod(0o755)
            hooks = root / ".git" / "hooks"
            hook = hooks / "pre-commit"
            hook.write_text("#!/bin/sh\nprintf '%s\\n' existing-hook\n", encoding="utf-8")
            hook.chmod(0o755)

            setup = run_command([str(scripts / "setup-dev.sh")], cwd=root, env={"PANLIB_ROOT": str(root)})

            self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
            installed = hook.read_text(encoding="utf-8")
            self.assertIn("existing-hook", installed)
            self.assertIn("privacy-guard", installed)
            self.assertEqual(installed.count("# >>> seedhub privacy-guard (managed) >>>"), 1)

    def test_hook_allows_safe_commit_and_blocks_unsafe_commit_without_moving_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(PRIVACY_GUARD, scripts / "privacy-guard")
            shutil.copy2(SETUP_DEV, scripts / "setup-dev.sh")
            (scripts / "privacy-guard").chmod(0o755)
            setup = run_command([str(scripts / "setup-dev.sh")], cwd=root, env={"PANLIB_ROOT": str(root)})
            self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)

            (root / "safe.txt").write_text("fixture@example.invalid\n", encoding="utf-8")
            safe_commit = commit_all(root, "safe")
            self.assertEqual(safe_commit.returncode, 0, safe_commit.stdout + safe_commit.stderr)
            before = git(root, "rev-parse", "HEAD").stdout.strip()

            token_value = "Xx9Yy8Zz7Aa6Bb5Cc4Dd3Ee2Ff1Gg0Hh"
            (root / "unsafe.txt").write_text("API_KEY=" + token_value + "\n", encoding="utf-8")
            git(root, "add", "--", "unsafe.txt")
            blocked = git(root, "commit", "-m", "unsafe")
            after = git(root, "rev-parse", "HEAD").stdout.strip()

            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(before, after)
            self.assertNotIn(token_value, blocked.stdout + blocked.stderr)


if __name__ == "__main__":
    unittest.main()
