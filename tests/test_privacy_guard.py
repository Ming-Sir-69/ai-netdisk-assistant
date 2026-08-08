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
