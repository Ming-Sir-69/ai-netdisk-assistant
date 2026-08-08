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
DOCTOR = REPO_ROOT / "bin" / "panlib-doctor"
BASH = shutil.which("bash") or "/bin/bash"


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class DoctorCliTests(unittest.TestCase):
    def run_doctor(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(DOCTOR)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
        )

    def _fake_bdpan(self, root: Path, version: str = "3.8.5") -> Path:
        fake = root / "bdpan"
        _executable(
            fake,
            f"""#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$BDPAN_FAKE_LOG"
case "${{1:-}}" in
  --version|version) printf 'bdpan {version}\\n' ;;
  --help) printf 'usage: bdpan\\n' ;;
  whoami)
    if [ "${{BDPAN_AUTHENTICATED:-1}}" = 1 ]; then
      printf 'private-account@example.invalid\\n'
      exit 0
    fi
    printf 'not logged in\\n' >&2
    exit 7
    ;;
  *) exit 64 ;;
esac
""",
        )
        return fake

    def base_env(self, root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PANLIB_ROOT": str(REPO_ROOT),
                "PATH": f"{root}:{os.environ.get('PATH', '')}",
                "PANLIB_PYTHON_BIN": str(REPO_ROOT / ".venv" / "bin" / "python"),
                "BDPAN_FAKE_LOG": str(root / "bdpan.log"),
                "PANLIB_NETWORK_SKIP": "1",
            }
        )
        return env

    def test_defaults_to_project_venv_and_maps_distribution_name_to_import_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_log = root / "python.log"
            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            _executable(
                venv_python,
                """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$PYTHON_FAKE_LOG"
case "${1:-}" in
  --version) printf 'Python 3.13.12\n' ;;
  -c) [ "${3:-}" = bs4 ] ;;
  *) exit 64 ;;
esac
""",
            )
            (root / "requirements.txt").write_text("beautifulsoup4==4.15.0\n", encoding="utf-8")
            fake_bdpan = self._fake_bdpan(root)
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root),
                    "BDPAN_BIN": str(fake_bdpan),
                    "BDPAN_FAKE_LOG": str(root / "bdpan.log"),
                    "PYTHON_FAKE_LOG": str(python_log),
                    "PANLIB_NETWORK_SKIP": "1",
                    "PANLIB_TIMEOUT_PYTHON": str(REPO_ROOT / ".venv" / "bin" / "python"),
                }
            )

            result = self.run_doctor(env)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["python"]["version"], "3.13.12")
            self.assertEqual(payload["checks"]["dependencies"]["status"], "ready")
            calls = python_log.read_text(encoding="utf-8")
            self.assertIn("bs4", calls)
            self.assertNotIn("beautifulsoup4", calls)

    def test_python_below_3_13_is_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_python = root / "python"
            _executable(fake_python, "#!/bin/sh\nprintf 'Python 3.12.9\\n'\n")
            env = self.base_env(root)
            env["PANLIB_PYTHON_BIN"] = str(fake_python)
            env["BDPAN_BIN"] = str(root / "missing-bdpan")

            result = self.run_doctor(env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["python"]["status"], "unsupported")

    def test_python_version_nonzero_exit_or_timeout_is_not_ready(self):
        cases = (
            ("#!/bin/sh\nprintf 'Python 3.13.12\\n'\nexit 9\n", "error"),
            ("#!/bin/sh\nexec sleep 5\n", "timeout"),
        )
        for body, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fake_python = root / "python"
                _executable(fake_python, body)
                env = self.base_env(root)
                env.update(
                    {
                        "PANLIB_PYTHON_BIN": str(fake_python),
                        "PANLIB_TIMEOUT_PYTHON": str(REPO_ROOT / ".venv" / "bin" / "python"),
                        "PANLIB_COMMAND_TIMEOUT": "1",
                        "BDPAN_BIN": str(root / "missing-bdpan"),
                    }
                )

                result = self.run_doctor(env)

                self.assertNotEqual(result.returncode, 0)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["checks"]["python"]["status"], expected)

    def test_dependency_timeout_and_nonzero_bdpan_version_are_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_python = root / "python"
            _executable(
                fake_python,
                """#!/bin/sh
case "${1:-}" in
  --version) printf 'Python 3.13.12\n' ;;
  -c) exec sleep 5 ;;
esac
""",
            )
            fake_bdpan = root / "bdpan"
            _executable(
                fake_bdpan,
                "#!/bin/sh\nprintf 'bdpan 3.8.5\\n'\nexit 9\n",
            )
            env = self.base_env(root)
            env.update(
                {
                    "PANLIB_PYTHON_BIN": str(fake_python),
                    "PANLIB_TIMEOUT_PYTHON": str(REPO_ROOT / ".venv" / "bin" / "python"),
                    "PANLIB_COMMAND_TIMEOUT": "1",
                    "BDPAN_BIN": str(fake_bdpan),
                    "PANLIB_REQUIRED_MODULES": "json",
                }
            )

            result = self.run_doctor(env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["dependencies"]["status"], "timeout")
            self.assertEqual(payload["checks"]["bdpan"]["status"], "error")

    def test_non_executable_project_venv_python_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.write_text("not executable\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root),
                    "BDPAN_BIN": str(root / "missing-bdpan"),
                    "PANLIB_NETWORK_SKIP": "1",
                }
            )

            result = self.run_doctor(env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["python"]["status"], "invalid")

    def test_missing_bdpan_is_reported_as_structured_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.base_env(root)
            env["BDPAN_BIN"] = str(root / "missing-bdpan")
            result = self.run_doctor(env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["bdpan"]["status"], "missing")
            self.assertNotIn("private-account@example.invalid", result.stdout + result.stderr)

    def test_unsupported_bdpan_version_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = self._fake_bdpan(root, version="2.0.0")
            env = self.base_env(root)
            env["BDPAN_BIN"] = str(fake)
            result = self.run_doctor(env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["bdpan"]["status"], "unsupported")

    def test_unauthenticated_whoami_and_network_failure_are_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = self._fake_bdpan(root)
            curl = root / "curl"
            _executable(curl, "#!/bin/sh\nexit 1\n")
            env = self.base_env(root)
            env.update({"BDPAN_BIN": str(fake), "BDPAN_AUTHENTICATED": "0", "PANLIB_NETWORK_SKIP": "0"})
            result = self.run_doctor(env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["auth"]["status"], "unauthenticated")
            self.assertEqual(payload["checks"]["network"]["status"], "failure")
            self.assertNotIn("private-account@example.invalid", result.stdout + result.stderr)
            calls = (root / "bdpan.log").read_text(encoding="utf-8")
            self.assertIn("whoami", calls)
            self.assertNotIn("doctor", calls)

    def test_ready_status_uses_only_read_only_bdpan_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = self._fake_bdpan(root)
            curl = root / "curl"
            _executable(curl, "#!/bin/sh\nexit 0\n")
            env = self.base_env(root)
            env["BDPAN_BIN"] = str(fake)
            env["PANLIB_NETWORK_SKIP"] = "0"
            env["PANLIB_REQUIRED_MODULES"] = "json"
            result = self.run_doctor(env)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ready")
            self.assertTrue(all(item["status"] in {"ready", "skipped"} for item in payload["checks"].values()))
            calls = (root / "bdpan.log").read_text(encoding="utf-8")
            self.assertIn("--version", calls)
            self.assertIn("--help", calls)
            self.assertIn("whoami", calls)
            self.assertNotIn("doctor", calls)

    def test_hung_bdpan_is_bounded_and_has_structured_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "bdpan"
            _executable(fake, "#!/bin/sh\nexec sleep 5\n")
            env = self.base_env(root)
            env.update(
                {
                    "BDPAN_BIN": str(fake),
                    "PANLIB_REQUIRED_MODULES": "json",
                    "PANLIB_COMMAND_TIMEOUT": "1",
                    "PANLIB_TIMEOUT_PYTHON": str(REPO_ROOT / ".venv" / "bin" / "python"),
                }
            )

            result = self.run_doctor(env)

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["checks"]["bdpan"]["status"], "timeout")
            self.assertIn("超时", " ".join(payload["next_steps"]))

    def test_help_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            call_log = root / "called"
            forbidden = root / "forbidden"
            _executable(forbidden, f"#!/bin/sh\nprintf called > '{call_log}'\nexit 9\n")
            env = os.environ.copy()
            env.update(
                {
                    "PANLIB_ROOT": str(root / "missing-root"),
                    "PANLIB_PYTHON_BIN": str(forbidden),
                    "BDPAN_BIN": str(forbidden),
                    "PANLIB_CURL_BIN": str(forbidden),
                }
            )

            result = subprocess.run(
                [BASH, str(DOCTOR), "--help"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Usage:", result.stdout)
            self.assertFalse(call_log.exists())


if __name__ == "__main__":
    unittest.main()
