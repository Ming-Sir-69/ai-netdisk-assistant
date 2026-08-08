from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.sh"
LOGIN = REPO_ROOT / "scripts" / "login.sh"
BASH = shutil.which("bash") or "/bin/bash"


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class SetupScriptTests(unittest.TestCase):
    def run_script(
        self,
        script: Path,
        *,
        env: dict[str, str],
        input_text: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(script)],
            cwd=REPO_ROOT,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
        )

    def test_bootstrap_is_idempotent_and_preserves_existing_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            _executable(
                venv_python,
                "#!/bin/sh\n[ \"${1:-}\" = --version ] && echo 'Python 3.13.12'\nexit 0\n",
            )
            (root / "requirements.txt").write_text("", encoding="utf-8")
            bdpan = root / "bdpan"
            _executable(bdpan, "#!/bin/sh\nexit 0\n")
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root),
                    "HOME": str(root / "home"),
                    "BDPAN_BIN": str(bdpan),
                }
            )

            first = self.run_script(BOOTSTRAP, env=env)
            second = self.run_script(BOOTSTRAP, env=env)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("Python 3.13.12", venv_python.read_text(encoding="utf-8"))
            self.assertIn("existing", first.stdout + second.stdout)

    def test_bootstrap_preserves_but_rejects_non_executable_venv_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.write_text("keep-me\n", encoding="utf-8")
            (root / "requirements.txt").write_text("", encoding="utf-8")
            env = os.environ.copy()
            env.update({"PANLIB_ROOT": str(root), "BDPAN_BIN": str(root / "missing")})

            result = self.run_script(BOOTSTRAP, env=env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["venv"]["status"], "invalid")
            self.assertEqual(venv_python.read_text(encoding="utf-8"), "keep-me\n")

    def test_bootstrap_reports_official_bdpan_install_entry_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".venv" / "bin").mkdir(parents=True)
            _executable(
                root / ".venv" / "bin" / "python",
                "#!/bin/sh\n[ \"${1:-}\" = --version ] && echo 'Python 3.13.12'\nexit 0\n",
            )
            (root / "requirements.txt").write_text("", encoding="utf-8")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root),
                    "HOME": str(root / "home"),
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "BDPAN_BIN": str(bin_dir / "missing-bdpan"),
                }
            )

            result = self.run_script(BOOTSTRAP, env=env)

            self.assertNotEqual(result.returncode, 0)
            output = result.stdout + result.stderr
            self.assertIn("baidu-netdisk/bdpan-storage", output)
            self.assertIn("skills/baidu-drive/scripts/install.sh", output)
            self.assertNotIn("bdpan-storage/main/install.sh", output)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "missing_bdpan")
            self.assertTrue(payload["next_steps"])

    def test_bootstrap_default_is_audit_only_and_install_deps_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "deps-installed"
            pip_log = root / "pip.log"
            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            _executable(
                venv_python,
                """#!/bin/sh
set -eu
case "${1:-}" in
  --version) printf 'Python 3.13.12\n' ;;
  -c) [ -f "$PIP_MARKER" ] ;;
  -m)
    [ "${2:-}" = pip ]
    printf '%s\n' "$*" >> "$PIP_LOG"
    printf 'pip progress must not corrupt JSON\n'
    : > "$PIP_MARKER"
    ;;
  *) exit 64 ;;
esac
""",
            )
            (root / "requirements.txt").write_text("beautifulsoup4==4.15.0\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root),
                    "PIP_MARKER": str(marker),
                    "PIP_LOG": str(pip_log),
                    "BDPAN_BIN": str(root / "missing-bdpan"),
                }
            )

            audit = self.run_script(BOOTSTRAP, env=env)

            self.assertNotEqual(audit.returncode, 0)
            audit_payload = json.loads(audit.stdout)
            self.assertEqual(audit_payload["dependencies"]["status"], "missing")
            self.assertEqual(audit_payload["bdpan"]["status"], "missing")
            self.assertGreaterEqual(len(audit_payload["next_steps"]), 2)
            self.assertFalse(pip_log.exists())

            installed = subprocess.run(
                [BASH, str(BOOTSTRAP), "--install-deps"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(installed.returncode, 0)  # bdpan is still absent
            installed_payload = json.loads(installed.stdout)
            self.assertEqual(installed_payload["dependencies"]["status"], "ready")
            self.assertEqual(installed_payload["bdpan"]["status"], "missing")
            self.assertIn("-m pip install", pip_log.read_text(encoding="utf-8"))

    def test_bootstrap_blocks_unsupported_python_before_dependencies_or_pip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pip_log = root / "pip.log"
            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            _executable(
                venv_python,
                """#!/bin/sh
case "${1:-}" in
  --version) printf 'Python 3.12.9\n' ;;
  -c) exit 0 ;;
  -m) printf '%s\n' "$*" >> "$PIP_LOG" ;;
esac
""",
            )
            (root / "requirements.txt").write_text("beautifulsoup4==4.15.0\n", encoding="utf-8")
            bdpan = root / "bdpan"
            _executable(bdpan, "#!/bin/sh\nexit 0\n")
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root),
                    "BDPAN_BIN": str(bdpan),
                    "PIP_LOG": str(pip_log),
                }
            )

            result = subprocess.run(
                [BASH, str(BOOTSTRAP), "--install-deps"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["venv"]["status"], "unsupported")
            self.assertEqual(payload["dependencies"]["status"], "blocked")
            self.assertFalse(pip_log.exists())

    def test_bootstrap_json_does_not_expose_absolute_root_or_control_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root\nprivate"
            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            _executable(
                venv_python,
                "#!/bin/sh\n[ \"${1:-}\" = --version ] && echo 'Python 3.13.12'\nexit 0\n",
            )
            (root / "requirements.txt").write_text("", encoding="utf-8")
            bdpan = root / "bdpan"
            _executable(bdpan, "#!/bin/sh\nexit 0\n")
            env = os.environ.copy()
            env.update({"PANLIB_ROOT": str(root), "BDPAN_BIN": str(bdpan)})

            result = self.run_script(BOOTSTRAP, env=env)

            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)
            self.assertNotIn(str(root), result.stdout + result.stderr)
            self.assertNotIn("private", result.stdout + result.stderr)

    def test_bootstrap_venv_failure_does_not_leave_fixed_error_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            fake_python = Path(tmp) / "python3"
            _executable(fake_python, "#!/bin/sh\nexit 9\n")
            temp_dir = Path(tmp) / "tmp"
            temp_dir.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root),
                    "PANLIB_PYTHON_BIN": str(fake_python),
                    "TMPDIR": str(temp_dir),
                    "BDPAN_BIN": str(root / "missing-bdpan"),
                }
            )

            result = self.run_script(BOOTSTRAP, env=env)

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((temp_dir / "panlib-bootstrap-venv.err").exists())

    def _fake_bdpan(self, root: Path) -> tuple[Path, Path]:
        log = root / "bdpan.log"
        fake = root / "bdpan"
        _executable(
            fake,
            """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$BDPAN_FAKE_LOG"
case "${1:-}" in
  whoami)
    if [ "${BDPAN_AUTHENTICATED:-0}" = 1 ] || [ -f "${BDPAN_FAKE_AUTH_FILE:-}" ]; then
      printf 'account=private@example.invalid\\n'
      exit 0
    fi
    exit 7
    ;;
  login)
    if [ "${2:-}" = "--get-auth-url" ]; then
      printf '%s\\n' "${BDPAN_AUTH_URL:-https://openapi.baidu.com/oauth/2.0/authorize?client_id=fake}"
      exit 0
    fi
    if [ "${2:-}" = "--set-code-stdin" ]; then
      read -r code
      printf 'stdin-length=%s\\n' "${#code}" >> "$BDPAN_FAKE_LOG"
      [ "$code" = "0123456789abcdef0123456789abcdef" ] || exit 8
      : > "${BDPAN_FAKE_AUTH_FILE:?}"
      exit 0
    fi
    exit 9
    ;;
  --version|version)
    printf 'bdpan 3.8.5\\n'
    ;;
  --help)
    printf 'usage: bdpan\\n'
    ;;
  *)
    exit 64
    ;;
esac
""",
        )
        return fake, log

    def test_login_oauth_code_is_stdin_only_and_doctor_runs_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake, log = self._fake_bdpan(root)
            open_fake = root / "open"
            _executable(
                open_fake,
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$OPEN_LOG\"\n",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(REPO_ROOT),
                    "BDPAN_BIN": str(fake),
                    "BDPAN_FAKE_LOG": str(log),
                    "BDPAN_FAKE_AUTH_FILE": str(root / "authenticated"),
                    "OPEN_LOG": str(root / "open.log"),
                    "PATH": f"{root}:{os.environ.get('PATH', '')}",
                    "PANLIB_NETWORK_SKIP": "1",
                    "PANLIB_REQUIRED_MODULES": "json",
                    "TMPDIR": str(root),
                }
            )

            result = self.run_script(
                LOGIN,
                env=env,
                input_text="y\n0123456789abcdef0123456789abcdef\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = result.stdout + result.stderr
            self.assertNotIn("0123456789abcdef0123456789abcdef", output)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("login --get-auth-url --accept-disclaimer", calls)
            self.assertIn("login --set-code-stdin --accept-disclaimer", calls)
            self.assertIn("stdin-length=32", calls)
            self.assertNotIn("0123456789abcdef0123456789abcdef", calls)
            self.assertTrue((root / "open.log").read_text(encoding="utf-8").strip())
            self.assertFalse(list(root.glob("panlib-login.*")))

    def test_login_keeps_https_link_visible_when_open_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake, log = self._fake_bdpan(root)
            open_fake = root / "open"
            _executable(open_fake, "#!/bin/sh\nexit 1\n")
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(REPO_ROOT),
                    "BDPAN_BIN": str(fake),
                    "BDPAN_FAKE_LOG": str(log),
                    "BDPAN_FAKE_AUTH_FILE": str(root / "authenticated"),
                    "PATH": f"{root}:{os.environ.get('PATH', '')}",
                    "PANLIB_NETWORK_SKIP": "1",
                    "PANLIB_REQUIRED_MODULES": "json",
                    "TMPDIR": str(root),
                }
            )

            result = self.run_script(
                LOGIN,
                env=env,
                input_text="y\n0123456789abcdef0123456789abcdef\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("https://openapi.baidu.com/oauth/2.0/authorize", result.stdout + result.stderr)
            self.assertFalse(list(root.glob("panlib-login.*")))

    def test_login_rejects_non_baidu_https_oauth_url_without_opening_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake, log = self._fake_bdpan(root)
            open_fake = root / "open"
            _executable(open_fake, "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$OPEN_LOG\"\n")
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(REPO_ROOT),
                    "BDPAN_BIN": str(fake),
                    "BDPAN_FAKE_LOG": str(log),
                    "BDPAN_FAKE_AUTH_FILE": str(root / "authenticated"),
                    "BDPAN_AUTH_URL": "https://evil.example/oauth/2.0/authorize?client_id=fake",
                    "OPEN_LOG": str(root / "open.log"),
                    "PATH": f"{root}:{os.environ.get('PATH', '')}",
                    "TMPDIR": str(root),
                }
            )

            result = self.run_script(LOGIN, env=env, input_text="y\n")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("非百度官方", result.stderr)
            self.assertFalse((root / "open.log").exists())
            self.assertFalse(list(root.glob("panlib-login.*")))

    def test_login_failure_cleans_temporary_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake, log = self._fake_bdpan(root)
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(REPO_ROOT),
                    "BDPAN_BIN": str(fake),
                    "BDPAN_FAKE_LOG": str(log),
                    "BDPAN_FAKE_AUTH_FILE": str(root / "authenticated"),
                    "PATH": f"{root}:{os.environ.get('PATH', '')}",
                    "TMPDIR": str(root),
                }
            )

            result = self.run_script(LOGIN, env=env, input_text="y\nnot-a-code\n")

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(list(root.glob("panlib-login.*")))

    def test_setup_help_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root / "must-not-exist"),
                    "BDPAN_BIN": str(root / "must-not-run"),
                    "TMPDIR": str(root),
                }
            )

            for script in (BOOTSTRAP, LOGIN):
                with self.subTest(script=script.name):
                    result = subprocess.run(
                        [BASH, str(script), "--help"],
                        cwd=REPO_ROOT,
                        env=env,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Usage:", result.stdout)
            self.assertFalse((root / "must-not-exist").exists())
            self.assertFalse(list(root.glob("panlib-login.*")))


if __name__ == "__main__":
    unittest.main()
