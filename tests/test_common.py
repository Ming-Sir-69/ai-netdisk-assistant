import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import panlib.common as common


class SettingsTests(unittest.TestCase):
    def test_environment_overrides_dotenv_and_portable_defaults(self):
        if not hasattr(common, "load_settings"):
            self.fail("load_settings is not implemented")
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "BDPAN_BASE=/dotenv/base\n"
                "BDPAN_LIB=DotEnvLib\n"
                "NETWORK_TIMEOUT=17\n"
                "BDPAN_TIMEOUT=29\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "BDPAN_BASE": "/environment/base",
                    "NETWORK_TIMEOUT": "23",
                },
                clear=False,
            ):
                settings = common.load_settings(env_file)

        self.assertEqual(settings.bdpan_base, "/environment/base")
        self.assertEqual(settings.bdpan_lib, "DotEnvLib")
        self.assertEqual(settings.network_timeout, 23)
        self.assertEqual(settings.bdpan_timeout, 29)

    def test_dotenv_overrides_portable_defaults(self):
        if not hasattr(common, "load_settings"):
            self.fail("load_settings is not implemented")
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("BDPAN_LIB=Archive\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                settings = common.load_settings(env_file)

        self.assertEqual(settings.bdpan_lib, "Archive")
        self.assertEqual(settings.bdpan_base, "/apps/bdpan")
        self.assertEqual(settings.network_timeout, 30)
        self.assertEqual(settings.bdpan_timeout, 600)

    def test_bdpan_bin_uses_path_when_no_explicit_value_exists(self):
        if not hasattr(common, "load_settings"):
            self.fail("load_settings is not implemented")
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("shutil.which", return_value="/fake/bin/bdpan"):
                    settings = common.load_settings(env_file)

        self.assertEqual(settings.bdpan_bin, Path("/fake/bin/bdpan"))

    def test_seedhub_cli_relative_value_resolves_from_repository_root(self):
        if not hasattr(common, "load_settings"):
            self.fail("load_settings is not implemented")
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "SEEDHUB_CLI=vendor/seedhub-cli/seedhub.py\n", encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                settings = common.load_settings(env_file)

        self.assertEqual(
            settings.seedhub_cli,
            common.SKILL_ROOT / "vendor/seedhub-cli/seedhub.py",
        )

    def test_invalid_timeout_is_rejected(self):
        if not hasattr(common, "load_settings"):
            self.fail("load_settings is not implemented")
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("NETWORK_TIMEOUT=0\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValueError):
                    common.load_settings(env_file)


class OutputAndRedactionTests(unittest.TestCase):
    def test_emit_error_writes_machine_json_to_stdout_and_human_log_to_stderr(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        message = (
            "bad https://pan.example/s/abc?pwd=secret "
            "Authorization: Digest credential=header-secret "
            "/Users/alice/private/project"
        )
        details = {
            "authorization": "Bearer secret-token",
            "nested": {
                "pwd": "abcd",
                "path": "/Users/alice/private/project",
                "count": 2,
                "enabled": True,
                "missing": None,
                "items": ["https://pan.example/s/x?auth_code=code-secret", 3],
            },
        }
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                common.emit_error(
                    common.INVALID_ARG,
                    message,
                    details,
                )

        self.assertEqual(raised.exception.code, 1)
        self.assertTrue(stdout.getvalue(), "emit_error did not write JSON to stdout")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"]["code"], common.INVALID_ARG)
        self.assertNotIn("secret", stdout.getvalue())
        self.assertNotIn("abcd", stdout.getvalue())
        self.assertNotIn("code-secret", stdout.getvalue())
        self.assertNotIn("/Users/alice/private/project", stdout.getvalue())
        self.assertEqual(payload["error"]["details"]["nested"]["count"], 2)
        self.assertIs(payload["error"]["details"]["nested"]["enabled"], True)
        self.assertIsNone(payload["error"]["details"]["nested"]["missing"])
        self.assertNotEqual(stderr.getvalue().strip(), "")
        self.assertNotIn("secret", stderr.getvalue())
        self.assertNotIn("abcd", stderr.getvalue())
        self.assertNotIn("code-secret", stderr.getvalue())
        self.assertNotIn("header-secret", stderr.getvalue())
        self.assertNotIn("secret-token", stderr.getvalue())
        self.assertNotIn("/Users/alice/private/project", stderr.getvalue())
        self.assertNotIn('"error"', stderr.getvalue())

    def test_log_redacts_query_credentials_authorization_and_personal_home(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            common.log(
                "url=https://pan.example/s/abc?pwd=abcd&access_token=xyz "
                "Authorization: Bearer bearer-secret "
                "path=/Users/alice/private/project",
                "error",
            )

        output = stderr.getvalue()
        self.assertNotIn("abcd", output)
        self.assertNotIn("xyz", output)
        self.assertNotIn("bearer-secret", output)
        self.assertNotIn("/Users/alice/private/project", output)
        self.assertIn("[REDACTED]", output)

    def test_safe_cloud_join_rejects_traversal_and_out_of_base_paths(self):
        if not hasattr(common, "safe_cloud_join"):
            self.fail("safe_cloud_join is not implemented")
        self.assertEqual(
            common.safe_cloud_join("/apps/bdpan", "片库", "Movies"),
            "/apps/bdpan/片库/Movies",
        )
        for candidate in ("../escape", "/other/root", "片库/../../escape", ""):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    common.safe_cloud_join("/apps/bdpan", candidate)

    def test_cloud_path_validation_requires_containment_under_base(self):
        if not hasattr(common, "is_within_cloud_base"):
            self.fail("is_within_cloud_base is not implemented")
        self.assertTrue(common.is_within_cloud_base("/apps/bdpan/片库", "/apps/bdpan"))
        self.assertFalse(common.is_within_cloud_base("/apps/bdpanx", "/apps/bdpan"))
        with self.assertRaises(ValueError):
            common.validate_cloud_path("/apps/bdpanx/escape", "/apps/bdpan")

    def test_cloud_path_rejects_raw_empty_components_and_double_slashes(self):
        for path, base in (
            ("/apps/bdpan//Library", "/apps/bdpan"),
            ("/apps/bdpan/Library", "/apps//bdpan"),
            ("/apps/bdpan/Library/", "/apps/bdpan"),
        ):
            with self.subTest(path=path, base=base):
                with self.assertRaises(ValueError):
                    common.validate_cloud_path(path, base)

        with self.assertRaises(ValueError):
            common.safe_cloud_join("/apps//bdpan", "Library")

    def test_authorization_header_redacts_any_scheme(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            common.log("Authorization: Digest username=alice credential=header-secret", "error")

        self.assertNotIn("Digest", stderr.getvalue())
        self.assertNotIn("header-secret", stderr.getvalue())

    def test_sensitive_field_families_redact_values_and_query_parameters(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        details = {
            "token": 1234,
            "pwd": 5678,
            "nested": {
                "auth_token": "secret-a",
                "session_token": "secret-b",
                "count": 2,
                "enabled": True,
                "missing": None,
            },
        }
        message = (
            "https://pan.example/s/x?auth_token=query-a&session_token=query-b "
            "token=plain-token"
        )
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                common.emit_error(common.INVALID_ARG, message, details)

        payload = json.loads(stdout.getvalue())
        safe_details = payload["error"]["details"]
        self.assertEqual(safe_details["token"], "[REDACTED]")
        self.assertEqual(safe_details["pwd"], "[REDACTED]")
        self.assertEqual(safe_details["nested"]["auth_token"], "[REDACTED]")
        self.assertEqual(safe_details["nested"]["session_token"], "[REDACTED]")
        self.assertEqual(safe_details["nested"]["count"], 2)
        self.assertIs(safe_details["nested"]["enabled"], True)
        self.assertIsNone(safe_details["nested"]["missing"])
        for leaked in ("1234", "5678", "secret-a", "secret-b", "query-a", "query-b", "plain-token"):
            self.assertNotIn(leaked, stdout.getvalue())
            self.assertNotIn(leaked, stderr.getvalue())


class SubprocessRoutingTests(unittest.TestCase):
    def test_run_seedhub_uses_loaded_repository_relative_cli_and_timeout(self):
        if not hasattr(common, "Settings"):
            self.fail("Settings is not implemented")
        settings = common.Settings(
            venv_python=Path("/tmp/python"),
            seedhub_cli=Path("/tmp/seedhub.py"),
            bdpan_bin=Path("/tmp/bdpan"),
            bdpan_base="/apps/bdpan",
            bdpan_lib="片库",
            network_timeout=11,
            bdpan_timeout=22,
            log_level="info",
            use_known_imdb_table=True,
        )
        with mock.patch("panlib.common.run_subprocess", return_value=(0, "{}", "")) as run:
            self.assertEqual(common.run_seedhub(["search", "x"], settings=settings), {})

        run.assert_called_once_with(
            ["/tmp/python", "/tmp/seedhub.py", "search", "x", "--json"],
            timeout=11,
        )

    def test_run_bdpan_uses_settings_binary_and_timeout(self):
        if not hasattr(common, "Settings"):
            self.fail("Settings is not implemented")
        settings = common.Settings(
            venv_python=Path("/tmp/python"),
            seedhub_cli=Path("/tmp/seedhub.py"),
            bdpan_bin=Path("/tmp/bdpan"),
            bdpan_base="/apps/bdpan",
            bdpan_lib="片库",
            network_timeout=11,
            bdpan_timeout=22,
            log_level="info",
            use_known_imdb_table=True,
        )
        with mock.patch("panlib.common.run_subprocess", return_value=(0, "ok", "")) as run:
            self.assertEqual(common.run_bdpan(["ls", "/apps/bdpan"], settings=settings), (0, "ok", ""))

        run.assert_called_once_with(["/tmp/bdpan", "ls", "/apps/bdpan"], timeout=22)


if __name__ == "__main__":
    unittest.main()
