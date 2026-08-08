import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ORGANIZE = REPO_ROOT / "bin" / "panlib-organize"


class OrganizeValidationCliTests(unittest.TestCase):
    def test_invalid_media_arguments_fail_as_stdout_json_before_bdpan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "bdpan-called"
            fake_bdpan = root / "bdpan"
            fake_bdpan.write_text(
                "#!/bin/sh\n"
                f"printf called > {marker}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_bdpan.chmod(fake_bdpan.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["BDPAN_BIN"] = str(fake_bdpan)

            common_args = [
                sys.executable,
                str(ORGANIZE),
                "--source-dir",
                "/apps/bdpan/片库/Movies/source",
                "--target-dir",
                "/apps/bdpan/片库/Movies/Show.{imdb-tt1234567}",
                "--title-en",
                "Show",
                "--imdb-id",
                "tt1234567",
                "--quality",
                "1080p",
            ]
            cases = (
                ("missing-year", []),
                ("invalid-quality", ["--year", "2020", "--quality", "2160p-untrusted"]),
                ("invalid-imdb", ["--year", "2020", "--imdb-id", "bad-id"]),
                (
                    "non-deterministic-target-leaf",
                    [
                        "--year",
                        "2020",
                        "--target-dir",
                        "/apps/bdpan/片库/Movies/arbitrary-target",
                    ],
                ),
            )
            for name, extra in cases:
                with self.subTest(name=name):
                    proc = subprocess.run(
                        common_args + extra,
                        cwd=REPO_ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    payload = json.loads(proc.stdout)
                    self.assertEqual(payload["error"]["code"], "INVALID_ARG")
                    self.assertNotIn("Traceback", proc.stderr)
                    self.assertFalse(marker.exists(), proc.stderr)

    def test_public_help_hides_compatibility_only_episode_and_dry_run_flags(self):
        proc = subprocess.run(
            [sys.executable, str(ORGANIZE), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("--episode", proc.stdout)
        self.assertNotIn("--dry-run", proc.stdout)


if __name__ == "__main__":
    unittest.main()
