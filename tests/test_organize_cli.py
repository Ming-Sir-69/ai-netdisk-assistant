from __future__ import annotations

import json
import importlib.util
from importlib.machinery import SourceFileLoader
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
ORGANIZE = REPO_ROOT / "bin" / "panlib-organize"
FAKE = REPO_ROOT / "tests" / "fakes" / "bdpan"


class OrganizeCliTests(unittest.TestCase):
    def run_cli(
        self,
        extra: list[str],
        *,
        state: dict,
        fake_fail: str = "",
        inject_after_ls: int | None = None,
        inject_before: str = "",
        inject_dir: str = "",
        inject_name: str = "",
        return_state: bool = False,
        manifest_file: Path | None = None,
    ):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        log = root / "calls.json"
        state_path = root / "state.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "BDPAN_BIN": str(FAKE),
                "BDPAN_BASE": "/safe/base",
                "BDPAN_LIB": "Library",
                "BDPAN_FAKE_LOG": str(log),
                "BDPAN_FAKE_STATE": str(state_path),
            }
        )
        if fake_fail:
            env["BDPAN_FAKE_FAIL"] = fake_fail
        if inject_after_ls is not None:
            env["BDPAN_FAKE_INJECT_AFTER_LS"] = str(inject_after_ls)
            env["BDPAN_FAKE_INJECT_DIR"] = inject_dir
            env["BDPAN_FAKE_INJECT_NAME"] = inject_name
        if inject_before:
            env["BDPAN_FAKE_INJECT_BEFORE"] = inject_before
            env["BDPAN_FAKE_INJECT_DIR"] = inject_dir
            env["BDPAN_FAKE_INJECT_NAME"] = inject_name
        command = [sys.executable, str(ORGANIZE)] + extra
        if manifest_file is not None:
            command.extend(["--manifest-file", str(manifest_file)])
        proc = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        calls = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
        final_state = json.loads(state_path.read_text(encoding="utf-8"))
        tmp.cleanup()
        if return_state:
            return proc, calls, final_state
        return proc, calls

    def base_args(self) -> list[str]:
        return [
            "--source-dir",
            "/safe/base/Library/Movies/incoming",
            "--target-dir",
            "/safe/base/Library/Movies/Limitless",
            "--title-en",
            "Limitless",
            "--imdb-id",
            "tt1219289",
            "--year",
            "2011",
            "--quality",
            "1080p",
            "--mode",
            "tv",
        ]

    def episode_state(self):
        return {
            "directories": [
                "/safe/base/Library/Movies/incoming",
                "/safe/base/Library/Movies",
                "/safe/base/Library/Movies/Limitless",
                "/safe/base/Library/Movies/Limitless/Limitless.S01",
            ],
            "entries": {
                "/safe/base/Library/Movies/incoming": [
                    {"server_filename": "Limitless.S01E01.mkv", "isdir": False},
                    {"server_filename": "Limitless.S01E02.mkv", "isdir": False},
                ],
                "/safe/base/Library/Movies": [],
                "/safe/base/Library/Movies/Limitless": [
                    {"server_filename": "Limitless.S01", "isdir": True},
                ],
                "/safe/base/Library/Movies/Limitless/Limitless.S01": [],
            },
        }

    def test_default_plan_has_distinct_episode_targets_and_no_mutation(self):
        proc, calls = self.run_cli(self.base_args(), state=self.episode_state())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        actions = payload["data"]["actions"]
        renames = [item for item in actions if item["action"] == "rename"]
        self.assertEqual([item["new_name"] for item in renames], [
            "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv",
            "Limitless.S01E02.{imdb-tt1219289}.1080p.mkv",
        ])
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls"])
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_execute_orders_mkdir_mv_then_rename_and_never_removes_by_default(self):
        state = self.episode_state()
        state["directories"].remove("/safe/base/Library/Movies/Limitless/Limitless.S01")
        state["entries"].pop("/safe/base/Library/Movies/Limitless/Limitless.S01")
        state["entries"]["/safe/base/Library/Movies/Limitless"] = []
        proc, calls = self.run_cli(self.base_args() + ["--execute"], state=state)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([item[0] for item in calls], [
            "ls", "ls", "ls", "ls", "ls", "mkdir", "ls", "mv", "ls", "rename",
            "ls", "mv", "ls", "rename",
        ])
        self.assertEqual(calls[5][1], "/safe/base/Library/Movies/Limitless/Limitless.S01")
        self.assertEqual(calls[9][0:2], ["rename", "/safe/base/Library/Movies/Limitless/Limitless.S01/Limitless.S01E01.mkv"])
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_unknown_episode_fails_before_any_mutation(self):
        state = self.episode_state()
        state["entries"]["/safe/base/Library/Movies/incoming"] = [
            {"server_filename": "Limitless.release.mkv", "isdir": False}
        ]
        proc, calls = self.run_cli(self.base_args() + ["--execute"], state=state)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls"])

    def test_failed_mv_stops_and_never_removes_source(self):
        initial = self.episode_state()
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            fake_fail="mv:1",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["code"], "NETWORK")
        self.assertEqual(error["details"]["failed_action"]["action"], "mv")
        self.assertEqual(error["details"]["completed"], [])
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls", "ls", "mv"])
        self.assertNotIn("rm", [item[0] for item in calls])
        self.assertEqual(final_state, initial)

    def test_failed_rename_stops_before_next_file_and_never_removes_source(self):
        initial = self.episode_state()
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            fake_fail="rename:1",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["code"], "NETWORK")
        self.assertEqual(error["details"]["failed_action"]["action"], "rename")
        self.assertEqual(
            [item["action"] for item in error["details"]["completed"]],
            ["mv"],
        )
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls", "ls", "mv", "ls", "rename"])
        self.assertNotIn("rm", [item[0] for item in calls])
        self.assertEqual(
            final_state["entries"]["/safe/base/Library/Movies/incoming"],
            [{"server_filename": "Limitless.S01E02.mkv", "isdir": False}],
        )
        self.assertEqual(
            final_state["entries"]["/safe/base/Library/Movies/Limitless/Limitless.S01"],
            [{"server_filename": "Limitless.S01E01.mkv", "isdir": False}],
        )

    def test_remove_empty_source_is_disabled_without_mutation(self):
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute", "--remove-empty-source"],
            state=self.episode_state(),
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])
        self.assertEqual(final_state, self.episode_state())

    def test_nested_discovery_is_explicit_and_recursive(self):
        state = {
            "directories": [
                "/safe/base/Library/Movies/incoming",
                "/safe/base/Library/Movies/incoming/part-1",
                "/safe/base/Library/Movies",
                "/safe/base/Library/Movies/Limitless",
                "/safe/base/Library/Movies/Limitless/Limitless.S01",
            ],
            "entries": {
                "/safe/base/Library/Movies/incoming": [
                    {"server_filename": "part-1", "isdir": True}
                ],
                "/safe/base/Library/Movies/incoming/part-1": [
                    {"server_filename": "Limitless.S01E01.mkv", "isdir": False}
                ],
                "/safe/base/Library/Movies": [],
                "/safe/base/Library/Movies/Limitless": [
                    {"server_filename": "Limitless.S01", "isdir": True},
                ],
                "/safe/base/Library/Movies/Limitless/Limitless.S01": [],
            },
        }
        proc, calls = self.run_cli(self.base_args() + ["--depth", "2"], state=state)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(["ls", "/safe/base/Library/Movies/incoming/part-1", "--json"], calls)
        actions = json.loads(proc.stdout)["data"]["actions"]
        self.assertEqual(actions[-2]["from"], "/safe/base/Library/Movies/incoming/part-1/Limitless.S01E01.mkv")

    def test_target_source_basename_collision_fails_before_any_mutation(self):
        state = self.episode_state()
        state["entries"]["/safe/base/Library/Movies/Limitless/Limitless.S01"] = [
            {"server_filename": "Limitless.S01E01.mkv", "isdir": False}
        ]
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=state,
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls"])
        self.assertEqual(final_state, state)

    def test_target_file_type_mismatch_fails_before_any_mutation(self):
        state = self.episode_state()
        target = "/safe/base/Library/Movies/Limitless/Limitless.S01"
        parent = "/safe/base/Library/Movies"
        state["directories"].remove(target)
        state["entries"].pop(target)
        state["entries"]["/safe/base/Library/Movies/Limitless"] = [
            {"server_filename": "Limitless.S01", "isdir": False}
        ]
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"], state=state, return_state=True
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls"])
        self.assertEqual(final_state, state)

    def test_successful_execute_persists_expected_fake_state(self):
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"], state=self.episode_state(), return_state=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        source_entries = final_state["entries"]["/safe/base/Library/Movies/incoming"]
        target_entries = final_state["entries"]["/safe/base/Library/Movies/Limitless/Limitless.S01"]
        self.assertEqual(source_entries, [])
        self.assertEqual(
            sorted(item["server_filename"] for item in target_entries),
            [
                "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv",
                "Limitless.S01E02.{imdb-tt1219289}.1080p.mkv",
            ],
        )
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_movie_plan_moves_sup_subtitles_but_excludes_poster(self):
        source = "/safe/base/Library/Movies/incoming"
        target = "/safe/base/Library/Movies/A.Walk.in.the.Clouds.1995"
        state = {
            "directories": [source, target],
            "entries": {
                source: [
                    {"server_filename": "云中漫步 1995 原盘简体中字.sup", "isdir": False},
                    {"server_filename": "云中漫步 1995 原盘繁体中字.sup", "isdir": False},
                    {"server_filename": "云中漫步.jpg", "isdir": False},
                ],
                target: [
                    {
                        "server_filename": "A.Walk.in.the.Clouds.1995.1080p.REMUX.mkv",
                        "isdir": False,
                    }
                ],
            },
        }
        args = [
            "--source-dir", source,
            "--target-dir", target,
            "--title-en", "A Walk in the Clouds",
            "--imdb-id", "tt0114887",
            "--year", "1995",
            "--quality", "1080p.REMUX",
            "--mode", "movie",
        ]

        proc, calls = self.run_cli(args, state=state)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        actions = json.loads(proc.stdout)["data"]["actions"]
        planned = [item["new_name"] for item in actions if item["action"] == "rename"]
        self.assertEqual(
            planned,
            [
                "A.Walk.in.the.Clouds.1995.{imdb-tt0114887}.1080p.REMUX.zh-Hans.sup",
                "A.Walk.in.the.Clouds.1995.{imdb-tt0114887}.1080p.REMUX.zh-Hant.sup",
            ],
        )
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])

    def test_movie_plan_excludes_explicit_and_unnamed_posters(self):
        source = "/safe/base/Library/Movies/incoming"
        target = "/safe/base/Library/Movies/The.Captain.2019"
        state = {
            "directories": [source],
            "entries": {
                source: [
                    {"server_filename": "中国机长.mp4", "isdir": False},
                    {"server_filename": "中国机长.poster.jpg", "isdir": False},
                    {"server_filename": "001.jpg", "isdir": False},
                    {"server_filename": "002.jpg", "isdir": False},
                ],
                "/safe/base/Library/Movies": [],
            },
        }
        args = [
            "--source-dir", source,
            "--target-dir", target,
            "--title-en", "The Captain",
            "--imdb-id", "tt10218664",
            "--year", "2019",
            "--quality", "2160p",
            "--mode", "movie",
        ]

        proc, calls = self.run_cli(args, state=state)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)["data"]
        self.assertEqual(
            [item["new_name"] for item in payload["actions"] if item["action"] == "rename"],
            ["The.Captain.2019.{imdb-tt10218664}.2160p.mp4"],
        )
        self.assertEqual(payload["source_count"], 1)
        planned_sources = {
            item["old_name"] for item in payload["actions"] if item["action"] == "mv"
        }
        self.assertEqual(planned_sources, {"中国机长.mp4"})
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])

    def test_movie_plan_uses_chinese_title_and_excludes_every_image(self):
        source = "/safe/base/Library/Movies/incoming"
        target = "/safe/base/Library/Movies/中国机长.2019"
        state = {
            "directories": [source],
            "entries": {
                source: [
                    {"server_filename": "The.Captain.2019.2160p.mp4", "isdir": False},
                    {"server_filename": "poster.jpg", "isdir": False},
                    {"server_filename": "readme.txt", "isdir": False},
                ],
                "/safe/base/Library/Movies": [],
            },
        }
        args = [
            "--source-dir", source,
            "--target-dir", target,
            "--title-en", "The Captain",
            "--title-zh", "中国机长",
            "--production-country", "China",
            "--imdb-id", "tt10218664",
            "--year", "2019",
            "--quality", "2160p",
            "--mode", "movie",
        ]

        proc, calls = self.run_cli(args, state=state)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)["data"]
        self.assertEqual(payload["source_count"], 1)
        self.assertEqual(
            [item["new_name"] for item in payload["actions"] if item["action"] == "rename"],
            ["中国机长.2019.{imdb-tt10218664}.2160p.mp4"],
        )
        self.assertEqual(
            {item["old_name"] for item in payload["actions"] if item["action"] == "mv"},
            {"The.Captain.2019.2160p.mp4"},
        )
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_movie_plan_leaves_all_jpgs_when_no_unique_explicit_poster_exists(self):
        source = "/safe/base/Library/Movies/incoming"
        target = "/safe/base/Library/Movies/The.Captain.2019"
        state = {
            "directories": [source],
            "entries": {
                source: [
                    {"server_filename": "中国机长.mp4", "isdir": False},
                    {"server_filename": "001.jpg", "isdir": False},
                    {"server_filename": "002.jpg", "isdir": False},
                ],
                "/safe/base/Library/Movies": [],
            },
        }
        args = [
            "--source-dir", source,
            "--target-dir", target,
            "--title-en", "The Captain",
            "--imdb-id", "tt10218664",
            "--year", "2019",
            "--quality", "2160p",
            "--mode", "movie",
        ]

        proc, calls = self.run_cli(args, state=state)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)["data"]
        self.assertEqual(
            [item["new_name"] for item in payload["actions"] if item["action"] == "rename"],
            ["The.Captain.2019.{imdb-tt10218664}.2160p.mp4"],
        )
        self.assertEqual(payload["source_count"], 1)
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])

    def test_movie_execute_keeps_unselected_jpgs_in_source_for_archive(self):
        source = "/safe/base/Library/Movies/incoming"
        target = "/safe/base/Library/Movies/The.Captain.2019"
        state = {
            "directories": [source],
            "entries": {
                source: [
                    {"server_filename": "中国机长.mp4", "isdir": False},
                    {"server_filename": "中国机长.poster.jpg", "isdir": False},
                    {"server_filename": "001.jpg", "isdir": False},
                    {"server_filename": "002.jpg", "isdir": False},
                ],
                "/safe/base/Library/Movies": [],
            },
        }
        args = [
            "--source-dir", source,
            "--target-dir", target,
            "--title-en", "The Captain",
            "--imdb-id", "tt10218664",
            "--year", "2019",
            "--quality", "2160p",
            "--mode", "movie",
            "--execute",
        ]

        proc, calls, final_state = self.run_cli(args, state=state, return_state=True)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            sorted(item["server_filename"] for item in final_state["entries"][source]),
            ["001.jpg", "002.jpg", "中国机长.poster.jpg"],
        )
        self.assertEqual(
            sorted(item["server_filename"] for item in final_state["entries"][target]),
            ["The.Captain.2019.{imdb-tt10218664}.2160p.mp4"],
        )
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_preflight_toctou_target_collision_stops_before_mutation(self):
        target = "/safe/base/Library/Movies/Limitless/Limitless.S01"
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=self.episode_state(),
            inject_after_ls=4,
            inject_dir=target,
            inject_name="Limitless.S01E01.{imdb-tt1219289}.1080p.mkv",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])
        self.assertNotIn("rm", [item[0] for item in calls])
        self.assertEqual(
            final_state["entries"][target],
            [{"server_filename": "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv", "isdir": False}],
        )

    def test_fake_mv_no_clobber_stops_when_collision_appears_after_fresh_ls(self):
        target = "/safe/base/Library/Movies/Limitless/Limitless.S01"
        initial = self.episode_state()
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            inject_after_ls=4,
            inject_dir=target,
            inject_name="Limitless.S01E01.mkv",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls", "ls"])
        self.assertEqual(final_state["entries"][target], [
            {"server_filename": "Limitless.S01E01.mkv", "isdir": False}
        ])
        self.assertEqual(final_state["entries"]["/safe/base/Library/Movies/incoming"], initial["entries"]["/safe/base/Library/Movies/incoming"])

    def test_fake_rename_no_clobber_stops_when_collision_appears_after_fresh_ls(self):
        target = "/safe/base/Library/Movies/Limitless/Limitless.S01"
        injected = "Limitless.S01E01.{imdb-tt1219289}.1080p.mkv"
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=self.episode_state(),
            inject_after_ls=5,
            inject_dir=target,
            inject_name=injected,
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls", "ls", "mv", "ls"])
        self.assertEqual(
            sorted(item["server_filename"] for item in final_state["entries"][target]),
            sorted(["Limitless.S01E01.mkv", injected]),
        )

    def test_fake_mkdir_no_clobber_stops_when_target_file_appears_before_mkdir(self):
        target = "/safe/base/Library/Movies/Limitless"
        parent = "/safe/base/Library/Movies"
        initial = self.episode_state()
        season = "/safe/base/Library/Movies/Limitless/Limitless.S01"
        initial["directories"].remove(season)
        initial["entries"].pop(season)
        initial["directories"].remove(target)
        initial["entries"].pop(target)
        initial["entries"][parent] = []
        proc, calls, final_state = self.run_cli(
            self.base_args() + ["--execute"],
            state=initial,
            inject_before="mkdir",
            inject_dir=parent,
            inject_name="Limitless",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls", "ls", "mkdir"])
        self.assertNotIn(target, final_state["directories"])
        self.assertEqual(
            final_state["entries"][parent],
            [{"server_filename": "Limitless", "isdir": False}],
        )

    def loki_args(self, *, target="/safe/base/Library/Movies/Loki") -> list[str]:
        return [
            "--source-dir", "/safe/base/Library/Movies/incoming",
            "--target-dir", target,
            "--title-en", "Loki",
            "--imdb-id", "tt1286039",
            "--year", "2021",
            "--quality", "1080p",
            "--mode", "tv",
        ]

    def loki_state(self, *, target_exists=True, season_dirs=()):
        work = "/safe/base/Library/Movies/Loki"
        directories = [
            "/safe/base/Library/Movies",
            "/safe/base/Library/Movies/incoming",
        ]
        entries = {
            "/safe/base/Library/Movies": [],
            "/safe/base/Library/Movies/incoming": [
                {"server_filename": "Loki.S01E01.mkv", "isdir": False},
                {"server_filename": "Loki.S02E01.mkv", "isdir": False},
            ],
        }
        if target_exists:
            directories.append(work)
            entries[work] = []
        for season in season_dirs:
            season_dir = f"{work}/Loki.S{season:02d}"
            directories.append(season_dir)
            entries.setdefault(work, []).append(
                {"server_filename": f"Loki.S{season:02d}", "isdir": True}
            )
            entries[season_dir] = []
        return {"directories": directories, "entries": entries}

    def falcon_args(self, *, mode="tv", expected=None, season=1) -> list[str]:
        args = [
            "--source-dir", "/safe/base/Library/TV/incoming",
            "--target-dir", "/safe/base/Library/TV/Falcon",
            "--title-en", "Falcon",
            "--imdb-id", "tt0000001",
            "--quality", "1080p",
            "--mode", mode,
            "--season", str(season),
        ]
        if expected is not None:
            args.extend(["--expected-episodes", str(expected)])
        if mode == "season":
            args.extend(["--year", "2021"])
        return args

    def falcon_state(self, names, *, subtitles=()):
        source = "/safe/base/Library/TV/incoming"
        parent = "/safe/base/Library/TV"
        return {
            "directories": [parent, source],
            "entries": {
                parent: [],
                source: [
                    {"server_filename": name, "isdir": False}
                    for name in [*names, *subtitles]
                ],
            },
        }

    def test_loki_plan_places_each_episode_under_its_season(self):
        proc, calls = self.run_cli(
            self.loki_args(),
            state=self.loki_state(target_exists=True, season_dirs=(1, 2)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(
            {item["to"] for item in data["actions"] if item["action"] == "mv"},
            {
                "/safe/base/Library/Movies/Loki/Loki.S01",
                "/safe/base/Library/Movies/Loki/Loki.S02",
            },
        )
        self.assertEqual(
            [item["new_name"] for item in data["actions"] if item["action"] == "rename"],
            [
                "Loki.S01E01.{imdb-tt1286039}.1080p.mkv",
                "Loki.S02E01.{imdb-tt1286039}.1080p.mkv",
            ],
        )
        self.assertEqual(
            [item["from"] for item in data["actions"] if item["action"] == "rename"],
            [
                "/safe/base/Library/Movies/Loki/Loki.S01/Loki.S01E01.mkv",
                "/safe/base/Library/Movies/Loki/Loki.S02/Loki.S02E01.mkv",
            ],
        )
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_missing_work_and_seasons_are_created_parent_before_child(self):
        proc, calls, final_state = self.run_cli(
            self.loki_args() + ["--execute"],
            state=self.loki_state(target_exists=False),
            return_state=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mkdirs = [item[1] for item in calls if item[0] == "mkdir"]
        self.assertEqual(
            mkdirs,
            [
                "/safe/base/Library/Movies/Loki",
                "/safe/base/Library/Movies/Loki/Loki.S01",
                "/safe/base/Library/Movies/Loki/Loki.S02",
            ],
        )
        self.assertEqual(
            [item["to"] for item in json.loads(proc.stdout)["data"]["actions"] if item["action"] == "mv"],
            [
                "/safe/base/Library/Movies/Loki/Loki.S01",
                "/safe/base/Library/Movies/Loki/Loki.S02",
            ],
        )
        self.assertEqual(final_state["entries"]["/safe/base/Library/Movies/incoming"], [])

    def test_existing_work_and_season_directories_are_reused(self):
        proc, calls = self.run_cli(
            self.loki_args() + ["--execute"],
            state=self.loki_state(target_exists=True, season_dirs=(1, 2)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("mkdir", [item[0] for item in calls])

    def test_same_final_name_in_distinct_seasons_is_not_a_global_collision(self):
        proc, calls = self.run_cli(
            self.loki_args(),
            state=self.loki_state(target_exists=True, season_dirs=(1, 2)),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        names = [item["new_name"] for item in json.loads(proc.stdout)["data"]["actions"] if item["action"] == "rename"]
        self.assertEqual(len(names), 2)
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls", "ls"])

    def test_per_season_collision_rejects_before_any_mutation(self):
        state = self.loki_state(target_exists=True, season_dirs=(1, 2))
        state["entries"]["/safe/base/Library/Movies/Loki/Loki.S01"] = [
            {"server_filename": "Loki.S01E01.{imdb-tt1286039}.1080p.mkv", "isdir": False}
        ]
        proc, calls, final_state = self.run_cli(
            self.loki_args() + ["--execute"], state=state, return_state=True
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertEqual(final_state, state)

    def test_missing_work_parent_is_rejected_without_mkdir(self):
        state = self.loki_state(target_exists=False)
        state["directories"].remove("/safe/base/Library/Movies")
        state["entries"].pop("/safe/base/Library/Movies")
        proc, calls = self.run_cli(self.loki_args() + ["--execute"], state=state)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mkdir", [item[0] for item in calls])

    def test_work_directory_appearance_before_mkdir_fails_fast(self):
        proc, calls, final_state = self.run_cli(
            self.loki_args() + ["--execute"],
            state=self.loki_state(target_exists=False),
            inject_before="mkdir",
            inject_dir="/safe/base/Library/Movies",
            inject_name="Loki",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertIn({"server_filename": "Loki", "isdir": False}, final_state["entries"]["/safe/base/Library/Movies"])

    def test_season_directory_appearance_before_mkdir_fails_fast(self):
        state = self.loki_state(target_exists=True, season_dirs=(2,))
        proc, calls, final_state = self.run_cli(
            self.loki_args() + ["--execute"], state=state,
            inject_before="mkdir",
            inject_dir="/safe/base/Library/Movies/Loki",
            inject_name="Loki.S01",
            return_state=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertIn({"server_filename": "Loki.S01", "isdir": False}, final_state["entries"]["/safe/base/Library/Movies/Loki"])

    def test_mkdir_failure_returns_exact_completed_actions(self):
        proc, calls = self.run_cli(
            self.loki_args() + ["--execute"],
            state=self.loki_state(target_exists=False), fake_fail="mkdir:2"
        )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["details"]["failed_action"]["path"], "/safe/base/Library/Movies/Loki/Loki.S01")
        self.assertEqual([item["path"] for item in error["details"]["completed"]], ["/safe/base/Library/Movies/Loki"])
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_numeric_fallback_maps_falcon_episodes_exactly(self):
        names = [f"{episode:02d}.mp4" for episode in range(1, 7)]
        proc, calls = self.run_cli(
            self.falcon_args(expected=6), state=self.falcon_state(names)
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(
            [item["new_name"] for item in data["actions"] if item["action"] == "rename"],
            [f"Falcon.S01E{episode:02d}.{{imdb-tt0000001}}.1080p.mp4" for episode in range(1, 7)],
        )
        self.assertTrue(all(item["to"] == "/safe/base/Library/TV/Falcon/Falcon.S01" for item in data["actions"] if item["action"] == "mv"))
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_numeric_fallback_requires_explicit_season_before_cloud_read(self):
        args = self.falcon_args(expected=2)
        season_index = args.index("--season")
        del args[season_index : season_index + 2]
        proc, calls = self.run_cli(
            args,
            state=self.falcon_state(["01.mp4", "02.mp4"]),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_numeric_subtitle_inherits_matching_episode(self):
        proc, calls = self.run_cli(
            self.falcon_args(expected=1),
            state=self.falcon_state(["01.mp4"], subtitles=["01.srt"]),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        renames = [item["new_name"] for item in json.loads(proc.stdout)["data"]["actions"] if item["action"] == "rename"]
        self.assertEqual(
            renames,
            [
                "Falcon.S01E01.{imdb-tt0000001}.1080p.mp4",
                "Falcon.S01E01.{imdb-tt0000001}.1080p.srt",
            ],
        )
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_numeric_fallback_rejects_invalid_inputs_before_mutation(self):
        cases = [
            ("missing expected count", ["01.mp4", "02.mp4"], None),
            ("gap", ["01.mp4", "03.mp4"], 2),
            ("duplicate", ["01.mp4", "01.mkv"], 2),
            ("mixed parsed and numeric", ["01.mp4", "Falcon.S01E02.mp4"], 2),
            ("wrong count", ["01.mp4", "02.mp4"], 3),
            ("nonnumeric", ["01.mp4", "x.mp4"], 2),
        ]
        for label, names, expected in cases:
            with self.subTest(label=label):
                args = self.falcon_args(expected=expected)
                proc, calls = self.run_cli(args, state=self.falcon_state(names))
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
                self.assertNotIn("mv", [item[0] for item in calls])
                self.assertNotIn("mkdir", [item[0] for item in calls])

    def test_numeric_fallback_rejects_unmatched_subtitle(self):
        proc, calls = self.run_cli(
            self.falcon_args(expected=1),
            state=self.falcon_state(["01.mp4"], subtitles=["02.srt"]),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_expected_episodes_is_invalid_outside_tv_mode(self):
        proc, calls = self.run_cli(
            self.falcon_args(mode="season", expected=1),
            state=self.falcon_state(["01.mp4"]),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def xmen_manifest(self) -> dict:
        return {
            "version": 1,
            "category": "movie",
            "groups": ["Marvel", "X-Men"],
            "items": [
                {
                    "source_path": "/safe/base/Library/Movies/incoming/1. X-Men.2000.mkv",
                    "fs_id": 201,
                    "size": 1000,
                    "layout": "single",
                    "canonical_title": "X-Men",
                    "year": "2000",
                    "imdb_id": "tt0120903",
                    "season": None,
                    "episode": None,
                    "quality": "1080p",
                },
                {
                    "source_path": "/safe/base/Library/Movies/incoming/2. X2.2003.mkv",
                    "fs_id": 202,
                    "size": 2000,
                    "layout": "single",
                    "canonical_title": "X2",
                    "year": "2003",
                    "imdb_id": "tt0290334",
                    "season": None,
                    "episode": None,
                    "quality": "1080p",
                },
            ],
        }

    def xmen_state(self):
        return {
            "directories": [
                "/safe/base/Library",
                "/safe/base/Library/Movies",
                "/safe/base/Library/Movies/incoming",
            ],
            "entries": {
                "/safe/base/Library": [],
                "/safe/base/Library/Movies": [],
                "/safe/base/Library/Movies/incoming": [
                    {
                        "server_filename": "1. X-Men.2000.mkv",
                        "isdir": False,
                        "fs_id": 201,
                        "size": 1000,
                    },
                    {
                        "server_filename": "2. X2.2003.mkv",
                        "isdir": False,
                        "fs_id": 202,
                        "size": 2000,
                    },
                ],
            },
        }

    def write_manifest(self, root: Path, value: dict) -> Path:
        path = root / "manifest.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def manifest_plan_ref(self, manifest_file: Path, state: dict) -> str:
        proc, calls = self.run_cli(
            ["--source-dir", "/safe/base/Library/Movies/incoming"],
            state=state,
            manifest_file=manifest_file,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])
        return json.loads(proc.stdout)["data"]["plan_ref"]

    def test_manifest_plan_removes_numeric_prefixes_and_never_writes(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            proc, calls = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        data = payload["data"]
        self.assertRegex(data["plan_ref"], r"^[0-9a-f]{64}$")
        self.assertFalse(data["executed"])
        self.assertTrue(data["execute_required"])
        self.assertEqual(
            data["targets"],
            [
                {
                    "target_dir": "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X-Men.2000",
                    "target_name": "X-Men.2000.{imdb-tt0120903}.1080p.mkv",
                },
                {
                    "target_dir": "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X2.2003",
                    "target_name": "X2.2003.{imdb-tt0290334}.1080p.mkv",
                },
            ],
        )
        self.assertEqual(
            [item["path"] for item in data["actions"] if item["action"] == "mkdir"],
            [
                "/safe/base/Library/Movies/Marvel.{series}",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X-Men.2000",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X2.2003",
            ],
        )
        self.assertEqual(
            [item["to"] for item in data["actions"] if item["action"] == "mv"],
            [
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X-Men.2000",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X2.2003",
            ],
        )
        # Numeric source prefixes remain visible in source actions for audit;
        # only deterministic target paths/names must omit them.
        self.assertNotIn("1. ", json.dumps(data["targets"], ensure_ascii=False))
        self.assertNotIn("2. ", json.dumps(data["targets"], ensure_ascii=False))
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])

    def test_manifest_execute_requires_plan_ref_before_mutation(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute",
                ],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_manifest_wrong_plan_ref_rejects_before_mutation(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", "0" * 64,
                ],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])
        self.assertNotIn("rename", [item[0] for item in calls])

    def test_manifest_malformed_plan_ref_rejects_before_any_read(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", "not-a-sha256",
                ],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_manifest_plan_ref_drift_rejects_before_mutation(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            plan_ref = self.manifest_plan_ref(manifest_file, self.xmen_state())
            drifted_state = self.xmen_state()
            universe = "/safe/base/Library/Movies/Marvel.{series}"
            drifted_state["directories"].append(universe)
            drifted_state["entries"][universe] = []
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=drifted_state,
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_manifest_source_fsid_and_size_drift_reject_before_mutation(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            plan_ref = self.manifest_plan_ref(manifest_file, self.xmen_state())
            for field, value in (("fs_id", 999), ("size", 9999)):
                with self.subTest(field=field):
                    drifted_state = self.xmen_state()
                    drifted_state["entries"][
                        "/safe/base/Library/Movies/incoming"
                    ][0][field] = value
                    proc, calls = self.run_cli(
                        [
                            "--source-dir", "/safe/base/Library/Movies/incoming",
                            "--execute", "--plan-ref", plan_ref,
                        ],
                        state=drifted_state,
                        manifest_file=manifest_file,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(
                        json.loads(proc.stdout)["error"]["code"], "INVALID_ARG"
                    )
                    self.assertNotIn("mkdir", [item[0] for item in calls])
                    self.assertNotIn("mv", [item[0] for item in calls])

    def test_manifest_source_path_drift_rejects_before_mutation(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest = self.xmen_manifest()
            manifest["items"][0]["source_path"] = (
                "/safe/base/Library/Movies/incoming/missing.mkv"
            )
            manifest_file = self.write_manifest(Path(manifest_root), manifest)
            proc, calls = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_manifest_legacy_option_mixing_is_zero_write(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            for option in (
                ["--target-dir", "/safe/base/Library/Movies/X-Men"],
                ["--title-en", "X-Men"],
                ["--mode", "movie"],
            ):
                with self.subTest(option=option[0]):
                    proc, calls = self.run_cli(
                        [
                            "--source-dir", "/safe/base/Library/Movies/incoming",
                            *option,
                        ],
                        state=self.xmen_state(),
                        manifest_file=manifest_file,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(
                        json.loads(proc.stdout)["error"]["code"], "INVALID_ARG"
                    )
                    self.assertEqual(calls, [])

    def test_plan_ref_without_manifest_or_execute_is_zero_read(self):
        proc, calls = self.run_cli(
            [
                "--source-dir", "/safe/base/Library/Movies/incoming",
                "--plan-ref", "a" * 64,
            ],
            state=self.xmen_state(),
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_manifest_plan_ref_without_execute_is_zero_read(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--plan-ref", "a" * 64,
                ],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertEqual(calls, [])

    def test_manifest_target_collision_duplicate_source_and_target_reject(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            cases = []
            collision = self.xmen_state()
            target = (
                "/safe/base/Library/Movies/Marvel.{series}/"
                "X-Men.{series}/X-Men.2000"
            )
            collision["directories"].append(target)
            collision["entries"][target] = [
                {
                    "server_filename": "X-Men.2000.{imdb-tt0120903}.1080p.mkv",
                    "isdir": False,
                    "fs_id": 201,
                    "size": 1000,
                }
            ]
            cases.append(("existing target final", self.xmen_manifest(), collision))

            duplicate_source = self.xmen_manifest()
            duplicate_source["items"][1]["source_path"] = duplicate_source["items"][0][
                "source_path"
            ]
            duplicate_source["items"][1]["fs_id"] = duplicate_source["items"][0]["fs_id"]
            duplicate_source["items"][1]["size"] = duplicate_source["items"][0]["size"]
            cases.append(("duplicate source", duplicate_source, self.xmen_state()))

            duplicate_target = self.xmen_manifest()
            for field in ("canonical_title", "year", "imdb_id"):
                duplicate_target["items"][1][field] = duplicate_target["items"][0][field]
            cases.append(("duplicate target", duplicate_target, self.xmen_state()))

            for label, manifest, state in cases:
                with self.subTest(label=label):
                    manifest_file = self.write_manifest(Path(manifest_root), manifest)
                    proc, calls = self.run_cli(
                        ["--source-dir", "/safe/base/Library/Movies/incoming"],
                        state=state,
                        manifest_file=manifest_file,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(
                        json.loads(proc.stdout)["error"]["code"], "INVALID_ARG"
                    )
                    self.assertNotIn("mkdir", [item[0] for item in calls])
                    self.assertNotIn("mv", [item[0] for item in calls])

    def cross_collision_manifest(self) -> dict:
        return {
            "version": 1,
            "category": "tv",
            "groups": ["Falcon"],
            "items": [
                {
                    "source_path": "/safe/base/Library/TV/incoming/other.mkv",
                    "fs_id": 401,
                    "size": 4001,
                    "layout": "episode",
                    "canonical_title": "Falcon",
                    "year": None,
                    "imdb_id": "tt0000001",
                    "season": 1,
                    "episode": 1,
                    "quality": "1080p",
                },
                {
                    "source_path": (
                        "/safe/base/Library/TV/incoming/"
                        "Falcon.S01E01.{imdb-tt0000001}.1080p.mkv"
                    ),
                    "fs_id": 402,
                    "size": 4002,
                    "layout": "episode",
                    "canonical_title": "Falcon",
                    "year": None,
                    "imdb_id": "tt0000001",
                    "season": 1,
                    "episode": 2,
                    "quality": "1080p",
                },
            ],
        }

    def cross_collision_state(self) -> dict:
        source_dir = "/safe/base/Library/TV/incoming"
        return {
            "directories": ["/safe/base/Library", source_dir],
            "entries": {
                "/safe/base/Library": [],
                source_dir: [
                    {"server_filename": "other.mkv", "isdir": False, "fs_id": 401, "size": 4001},
                    {
                        "server_filename": "Falcon.S01E01.{imdb-tt0000001}.1080p.mkv",
                        "isdir": False,
                        "fs_id": 402,
                        "size": 4002,
                    },
                ],
            },
        }

    def test_manifest_cross_collision_old_basename_vs_other_final_rejects_before_write(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(
                Path(manifest_root), self.cross_collision_manifest()
            )
            proc, calls = self.run_cli(
                ["--source-dir", "/safe/base/Library/TV/incoming"],
                state=self.cross_collision_state(),
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])

    def xmen_external_manifest_and_state(self):
        manifest = self.xmen_manifest()
        state = {
            "directories": ["/safe/base/Library", "/safe/base/incoming"],
            "entries": {
                "/safe/base/Library": [],
                "/safe/base/incoming": [],
            },
        }
        for item, entry in zip(
            manifest["items"],
            (
                {"server_filename": "1. X-Men.2000.mkv", "isdir": False, "fs_id": 201, "size": 1000},
                {"server_filename": "2. X2.2003.mkv", "isdir": False, "fs_id": 202, "size": 2000},
            ),
        ):
            item["source_path"] = item["source_path"].replace(
                "/safe/base/Library/Movies/incoming", "/safe/base/incoming"
            )
            state["entries"]["/safe/base/incoming"].append(entry)
        return manifest, state

    def test_manifest_missing_category_parent_is_created_in_strict_order(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest, state = self.xmen_external_manifest_and_state()
            manifest_file = self.write_manifest(Path(manifest_root), manifest)
            proc, calls = self.run_cli(
                ["--source-dir", "/safe/base/incoming"],
                state=state,
                manifest_file=manifest_file,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(
            [item["path"] for item in data["actions"] if item["action"] == "mkdir"],
            [
                "/safe/base/Library/Movies",
                "/safe/base/Library/Movies/Marvel.{series}",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X-Men.2000",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X2.2003",
            ],
        )
        self.assertEqual([item[0] for item in calls], ["ls", "ls", "ls", "ls", "ls", "ls", "ls"])

    def test_manifest_execute_writes_missing_category_parent_before_universe(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest, state = self.xmen_external_manifest_and_state()
            manifest_file = self.write_manifest(Path(manifest_root), manifest)
            plan_proc, _ = self.run_cli(
                ["--source-dir", "/safe/base/incoming"],
                state=state,
                manifest_file=manifest_file,
            )
            plan_ref = json.loads(plan_proc.stdout)["data"]["plan_ref"]
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/incoming",
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=state,
                manifest_file=manifest_file,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mkdirs = [item[1] for item in calls if item[0] == "mkdir"]
        self.assertEqual(
            mkdirs,
            [
                "/safe/base/Library/Movies",
                "/safe/base/Library/Movies/Marvel.{series}",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X-Men.2000",
                "/safe/base/Library/Movies/Marvel.{series}/X-Men.{series}/X2.2003",
            ],
        )
        mutation_names = [item[0] for item in calls if item[0] in {"mv", "rename"}]
        self.assertTrue(mutation_names)
        first_move_index = next(index for index, item in enumerate(calls) if item[0] == "mv")
        self.assertTrue(all(item[0] == "mkdir" or item[0] == "ls" for item in calls[:first_move_index]))

    def test_manifest_target_entry_order_is_fingerprint_stable_but_content_drift_changes_ref(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            universe = "/safe/base/Library/Movies/Marvel.{series}"
            collection = universe + "/X-Men.{series}"
            state_a = self.xmen_state()
            for path in ("/safe/base/Library/Movies", universe, collection):
                state_a["directories"].append(path)
                state_a["entries"][path] = [
                    {"server_filename": "z.txt", "isdir": False, "fs_id": 900, "size": 9, "path": path + "/z.txt"},
                    {"server_filename": "a.txt", "isdir": False, "fs_id": 901, "size": 8, "path": path + "/a.txt"},
                ]
            state_b = json.loads(json.dumps(state_a))
            for path in ("/safe/base/Library/Movies", universe, collection):
                state_b["entries"][path].reverse()
            state_c = json.loads(json.dumps(state_a))
            state_c["entries"][collection][0]["size"] = 99
            proc_a, _ = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=state_a,
                manifest_file=manifest_file,
            )
            proc_b, _ = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=state_b,
                manifest_file=manifest_file,
            )
            proc_c, _ = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=state_c,
                manifest_file=manifest_file,
            )
        self.assertEqual(proc_a.returncode, 0, proc_a.stderr)
        self.assertEqual(proc_b.returncode, 0, proc_b.stderr)
        self.assertEqual(proc_c.returncode, 0, proc_c.stderr)
        ref_a = json.loads(proc_a.stdout)["data"]["plan_ref"]
        ref_b = json.loads(proc_b.stdout)["data"]["plan_ref"]
        ref_c = json.loads(proc_c.stdout)["data"]["plan_ref"]
        self.assertEqual(ref_a, ref_b)
        self.assertNotEqual(ref_a, ref_c)

    def test_manifest_action_carries_expected_source_identity(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            proc, _ = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        moves = [
            item for item in json.loads(proc.stdout)["data"]["actions"] if item["action"] == "mv"
        ]
        self.assertEqual(
            [(item["expected_fs_id"], item["expected_size"]) for item in moves],
            [(201, 1000), (202, 2000)],
        )

    def test_manifest_action_identity_toctou_stops_before_mutation(self):
        loader = SourceFileLoader("organize_cli_identity_test", str(ORGANIZE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        spec.loader.exec_module(module)
        cases = [
            {
                "action": "mv",
                "from": "/safe/base/incoming/movie.mkv",
                "to": "/safe/base/Movies/Movie.2020",
                "old_name": "movie.mkv",
                "new_name": "Movie.2020.1080p.mkv",
            },
            {
                "action": "rename",
                "from": "/safe/base/Movies/Movie.2020/movie.mkv",
                "old_name": "movie.mkv",
                "new_name": "Movie.2020.1080p.mkv",
            },
        ]
        for action in cases:
            action.update({"expected_fs_id": 101, "expected_size": 1000})
            if action["action"] == "mv":
                destination_entries = ([], True)
            else:
                destination_entries = (
                    [{"server_filename": "movie.mkv", "isdir": False, "fs_id": 101, "size": 1000}],
                    True,
                )
            replaced_source = (
                [{"server_filename": "movie.mkv", "isdir": False, "fs_id": 999, "size": 1000}],
                True,
            )
            with self.subTest(action=action["action"]), mock.patch.object(
                module, "_list_target", side_effect=[destination_entries, replaced_source]
            ), mock.patch.object(module, "_run_mutation") as mutate:
                with self.assertRaises(module.OperationFailure) as raised:
                    module._execute([action], object())
            self.assertEqual(raised.exception.action, action)
            self.assertEqual(raised.exception.completed, [])
            mutate.assert_not_called()

    def test_manifest_raw_legacy_flag_presence_including_empty_and_episode_is_zero_read(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            for option in (["--episode", "1"], ["--title-en", ""], ["-t", ""]):
                with self.subTest(option=option[0]):
                    proc, calls = self.run_cli(
                        ["--source-dir", "/safe/base/Library/Movies/incoming", *option],
                        state=self.xmen_state(),
                        manifest_file=manifest_file,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
                    self.assertEqual(calls, [])

    def test_manifest_rejects_attached_target_short_and_long_abbreviation_before_read(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            for option in (["-t/legacy"], ["--target-d=/legacy"]):
                with self.subTest(option=option[0]):
                    proc, calls = self.run_cli(
                        ["--source-dir", "/safe/base/Library/Movies/incoming", *option],
                        state=self.xmen_state(),
                        manifest_file=manifest_file,
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(calls, [])

    def test_manifest_same_name_omits_rename_action(self):
        manifest = self.xmen_manifest()
        source_name = "X-Men.2000.1080p.mkv"
        manifest["items"][0]["source_path"] = "/safe/base/Library/Movies/incoming/" + source_name
        state = self.xmen_state()
        state["entries"]["/safe/base/Library/Movies/incoming"][0]["server_filename"] = source_name
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), manifest)
            proc, calls = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=state,
                manifest_file=manifest_file,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        actions = json.loads(proc.stdout)["data"]["actions"]
        first = [item for item in actions if item.get("from", "").endswith(source_name)]
        # 新规则：文件名带 IMDB，源是旧名（无 IMDB），故 mv 后必须 rename
        self.assertEqual([item["action"] for item in first], ["mv", "rename"])

    def test_manifest_same_name_success_call_order_has_no_first_rename(self):
        manifest = self.xmen_manifest()
        source_name = "X-Men.2000.1080p.mkv"
        manifest["items"][0]["source_path"] = "/safe/base/Library/Movies/incoming/" + source_name
        state = self.xmen_state()
        state["entries"]["/safe/base/Library/Movies/incoming"][0]["server_filename"] = source_name
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), manifest)
            plan_proc, _ = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=state,
                manifest_file=manifest_file,
            )
            plan_ref = json.loads(plan_proc.stdout)["data"]["plan_ref"]
            proc, calls, final_state = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=state,
                manifest_file=manifest_file,
                return_state=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mutations = [item[0] for item in calls if item[0] in {"mkdir", "mv", "rename"}]
        self.assertEqual(mutations[:4], ["mkdir", "mkdir", "mkdir", "mkdir"])
        # 新规则：两部电影文件名都带 IMDB，源是旧名，故每个都 mv+rename
        self.assertEqual(mutations[4:], ["mv", "rename", "mv", "rename"])
        self.assertEqual(final_state["entries"]["/safe/base/Library/Movies/incoming"], [])

    def test_manifest_postcondition_source_still_exists_is_unverified_and_classified(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            plan_ref = self.manifest_plan_ref(manifest_file, self.xmen_state())
            source_parent = "/safe/base/Library/Movies/incoming"
            proc, calls = self.run_cli(
                [
                    "--source-dir", source_parent,
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=self.xmen_state(),
                inject_after_ls=17,
                inject_dir=source_parent,
                inject_name="1. X-Men.2000.mkv",
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["code"], "NETWORK")
        self.assertEqual(error["details"]["postcondition"]["status"], "unverified")
        self.assertEqual(error["details"]["failed_action"]["action"], "postcondition")
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_manifest_postcondition_rejects_wrong_identity_and_duplicate_target(self):
        loader = SourceFileLoader("organize_cli_for_test", str(ORGANIZE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        spec.loader.exec_module(module)
        target_dir = "/safe/base/Library/Movies/X-Men.{series}/X-Men.2000"
        source_path = "/safe/base/Library/Movies/incoming/X-Men.2000.mkv"
        item = {
            "target_dir": target_dir,
            "target_name": "X-Men.2000.{imdb-tt0120903}.1080p.mkv",
            "source_path": source_path,
            "fs_id": 201,
            "size": 1000,
        }
        plan = {"normalized": {"items": [item]}}
        cases = {
            "wrong size": [
                {"server_filename": item["target_name"], "isdir": False, "fs_id": 201, "size": 999}
            ],
            "wrong fs id": [
                {"server_filename": item["target_name"], "isdir": False, "fs_id": 999, "size": 1000}
            ],
            "duplicate": [
                {"server_filename": item["target_name"], "isdir": False, "fs_id": 201, "size": 1000},
                {"server_filename": item["target_name"], "isdir": False, "fs_id": 201, "size": 1000},
            ],
        }
        for label, entries in cases.items():
            with self.subTest(label=label), mock.patch.object(
                module, "_list_target", return_value=(entries, True)
            ):
                with self.assertRaises(ValueError):
                    module._verify_manifest_postcondition(plan, object())

    def test_manifest_target_appearance_toctou_rejects_before_mutation(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            target = (
                "/safe/base/Library/Movies/Marvel.{series}/"
                "X-Men.{series}/X-Men.2000"
            )
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref",
                    self.manifest_plan_ref(manifest_file, self.xmen_state()),
                ],
                state=self.xmen_state(),
                # Inject after the source listing (an existing directory) so
                # the fresh hierarchy read observes the target before any
                # mkdir action is allowed.
                inject_after_ls=1,
                inject_dir=target,
                inject_name="X-Men.2000.{imdb-tt0120903}.1080p.mkv",
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "INVALID_ARG")
        self.assertNotIn("mkdir", [item[0] for item in calls])
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_manifest_without_outer_group_uses_category_root_directly(self):
        manifest = self.xmen_manifest()
        manifest["groups"] = ["X-Men"]
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), manifest)
            proc, calls = self.run_cli(
                ["--source-dir", "/safe/base/Library/Movies/incoming"],
                state=self.xmen_state(),
                manifest_file=manifest_file,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        targets = json.loads(proc.stdout)["data"]["targets"]
        self.assertEqual(
            targets[0]["target_dir"],
            "/safe/base/Library/Movies/X-Men.{series}/X-Men.2000",
        )
        self.assertEqual(
            [item["path"] for item in json.loads(proc.stdout)["data"]["actions"] if item["action"] == "mkdir"],
            [
                "/safe/base/Library/Movies/X-Men.{series}",
                "/safe/base/Library/Movies/X-Men.{series}/X-Men.2000",
                "/safe/base/Library/Movies/X-Men.{series}/X2.2003",
            ],
        )
        self.assertNotIn("mkdir", [item[0] for item in calls])

    def season_manifest(self) -> dict:
        return {
            "version": 1,
            "category": "tv",
            "groups": [],
            "items": [
                {
                    "source_path": "/safe/base/Library/TV/incoming/Falcon.S02.mkv",
                    "fs_id": 301,
                    "size": 3000,
                    "layout": "season",
                    "canonical_title": "Falcon",
                    "year": None,
                    "imdb_id": "tt0000001",
                    "season": 2,
                    "episode": None,
                    "quality": "1080p",
                }
            ],
        }

    def season_manifest_state(self) -> dict:
        return {
            "directories": [
                "/safe/base/Library",
                "/safe/base/Library/TV/incoming",
            ],
            "entries": {
                "/safe/base/Library": [],
                "/safe/base/Library/TV/incoming": [
                    {
                        "server_filename": "Falcon.S02.mkv",
                        "isdir": False,
                        "fs_id": 301,
                        "size": 3000,
                    }
                ],
            },
        }

    def test_manifest_normalizes_in_place_without_moving(self):
        # 文件已经在目标目录里、只差名字时，多发一次 mv 只会凭空增加失败面。
        manifest = self.season_manifest()
        target = "/safe/base/Library/TV shows/Falcon.{series}/Falcon.S02"
        manifest["items"][0]["source_path"] = f"{target}/Falcon.S02.raw.mkv"
        state = self.season_manifest_state()
        state["directories"] += [
            "/safe/base/Library/TV shows",
            "/safe/base/Library/TV shows/Falcon.{series}",
            target,
        ]
        state["entries"][target] = [
            {"server_filename": "Falcon.S02.raw.mkv", "isdir": False, "fs_id": 301, "size": 3000}
        ]
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), manifest)
            proc, calls = self.run_cli(
                ["--source-dir", target], state=state, manifest_file=manifest_file
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        actions = json.loads(proc.stdout)["data"]["actions"]
        kinds = [item["action"] for item in actions]
        self.assertIn("rename", kinds)
        self.assertNotIn("mv", kinds)

    def test_manifest_season_target_uses_work_and_padded_season(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.season_manifest())
            proc, calls = self.run_cli(
                ["--source-dir", "/safe/base/Library/TV/incoming"],
                state=self.season_manifest_state(),
                manifest_file=manifest_file,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(
            data["targets"],
            [
                {
                    "target_dir": "/safe/base/Library/TV shows/Falcon.{series}/Falcon.S02",
                    "target_name": "Falcon.S02.{imdb-tt0000001}.1080p.mkv",
                }
            ],
        )
        self.assertEqual(
            [item["path"] for item in data["actions"] if item["action"] == "mkdir"],
            [
                "/safe/base/Library/TV shows",
                "/safe/base/Library/TV shows/Falcon.{series}",
                "/safe/base/Library/TV shows/Falcon.{series}/Falcon.S02",
            ],
        )
        self.assertEqual(calls[0][0], "ls")
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_manifest_successfully_verifies_every_target_identity_and_source_absence(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            plan_ref = self.manifest_plan_ref(manifest_file, self.xmen_state())
            proc, calls, final_state = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=self.xmen_state(),
                manifest_file=manifest_file,
                return_state=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["postcondition"]["status"], "verified")
        self.assertEqual(
            {(item["fs_id"], item["size"]) for item in data["postcondition"]["targets"]},
            {(201, 1000), (202, 2000)},
        )
        self.assertEqual(
            data["postcondition"]["sources_absent"],
            [
                "/safe/base/Library/Movies/incoming/1. X-Men.2000.mkv",
                "/safe/base/Library/Movies/incoming/2. X2.2003.mkv",
            ],
        )
        self.assertEqual(final_state["entries"]["/safe/base/Library/Movies/incoming"], [])
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_manifest_mkdir_failure_reports_partial_without_retry_or_move(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            plan_ref = self.manifest_plan_ref(manifest_file, self.xmen_state())
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=self.xmen_state(),
                fake_fail="mkdir:2",
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["details"]["failed_action"]["action"], "mkdir")
        self.assertEqual([item["path"] for item in error["details"]["completed"]], [
            "/safe/base/Library/Movies/Marvel.{series}",
        ])
        self.assertEqual([item[0] for item in calls].count("mkdir"), 2)
        self.assertNotIn("mv", [item[0] for item in calls])

    def test_manifest_mv_failure_reports_partial_without_retry_or_rename(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            plan_ref = self.manifest_plan_ref(manifest_file, self.xmen_state())
            proc, calls = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=self.xmen_state(),
                fake_fail="mv:1",
                manifest_file=manifest_file,
            )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["details"]["failed_action"]["action"], "mv")
        self.assertEqual(len(error["details"]["completed"]), 4)
        self.assertEqual([item[0] for item in calls].count("mv"), 1)
        self.assertNotIn("rename", [item[0] for item in calls])
        self.assertNotIn("rm", [item[0] for item in calls])

    def test_manifest_rename_failure_reports_mv_only_and_no_retry_delete(self):
        with tempfile.TemporaryDirectory() as manifest_root:
            manifest_file = self.write_manifest(Path(manifest_root), self.xmen_manifest())
            plan_ref = self.manifest_plan_ref(manifest_file, self.xmen_state())
            proc, calls, final_state = self.run_cli(
                [
                    "--source-dir", "/safe/base/Library/Movies/incoming",
                    "--execute", "--plan-ref", plan_ref,
                ],
                state=self.xmen_state(),
                fake_fail="rename:1",
                manifest_file=manifest_file,
                return_state=True,
            )
        self.assertNotEqual(proc.returncode, 0)
        error = json.loads(proc.stdout)["error"]
        self.assertEqual(error["details"]["failed_action"]["action"], "rename")
        self.assertEqual(
            [item["action"] for item in error["details"]["completed"]],
            ["mkdir", "mkdir", "mkdir", "mkdir", "mv"],
        )
        self.assertEqual([item[0] for item in calls].count("rename"), 1)
        self.assertNotIn("rm", [item[0] for item in calls])
        self.assertEqual(final_state["entries"]["/safe/base/Library/Movies/incoming"][0]["server_filename"], "2. X2.2003.mkv")

    def test_legacy_season_execute_keeps_work_and_season_hierarchy(self):
        state = self.falcon_state(["Falcon.S02.mkv"])
        proc, calls, final_state = self.run_cli(
            self.falcon_args(mode="season", season=2) + ["--execute"],
            state=state,
            return_state=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        target = "/safe/base/Library/TV/Falcon/Falcon.S02"
        self.assertEqual(
            [item[1] for item in calls if item[0] == "mkdir"],
            ["/safe/base/Library/TV/Falcon", target],
        )
        self.assertEqual(
            final_state["entries"][target],
            [{"server_filename": "Falcon.S02.{imdb-tt0000001}.1080p.mkv", "isdir": False}],
        )


if __name__ == "__main__":
    unittest.main()
