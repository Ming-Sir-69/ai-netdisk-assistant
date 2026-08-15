from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from panlib.common import load_settings
from panlib.media_manifest import (
    MAX_MANIFEST_BYTES,
    load_media_manifest,
    manifest_plan_ref,
    normalize_media_manifest,
)


class MediaManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = load_settings(
            environ={"BDPAN_BASE": "/apps/bdpan", "BDPAN_LIB": "片库"}
        )
        self.source_dir = "/apps/bdpan/Library/Movies/incoming"

    def tearDown(self):
        self.temp.cleanup()

    def source(
        self,
        name: str,
        *,
        fs_id: int | None = 101,
        size: int = 1000,
        directory: str | None = None,
    ) -> dict:
        parent = directory or self.source_dir
        return {
            "path": parent.rstrip("/") + "/" + name,
            "fs_id": fs_id,
            "size": size,
        }

    def payload(self, *, items: list[dict], **overrides) -> dict:
        payload = {
            "version": 1,
            "category": "movie",
            "universe": None,
            "collection": None,
            "items": items,
        }
        payload.update(overrides)
        return payload

    def item(self, source: dict, **overrides) -> dict:
        value = {
            "source_path": source["path"],
            "fs_id": source["fs_id"],
            "size": source["size"],
            "layout": "single",
            "canonical_title": "Movie",
            "year": "2020",
            "imdb_id": "tt1234567",
            "season": None,
            "episode": None,
            "quality": "1080p",
        }
        value.update(overrides)
        return value

    def normalize(self, payload: object, sources: list[dict] | None = None) -> dict:
        return normalize_media_manifest(
            payload,
            settings=self.settings,
            source_dir=self.source_dir,
            sources=self.sources if sources is None else sources,
        )

    def write_manifest(self, value: object, *, raw: bytes | None = None) -> Path:
        path = self.root / "manifest.json"
        if raw is None:
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        else:
            path.write_bytes(raw)
        return path

    @property
    def sources(self) -> list[dict]:
        return [self.source("1. Movie.2020.mkv")]

    def test_marvel_loki_episode_target(self):
        source = self.source("01. Loki.S01E01.mkv")
        normalized = self.normalize(
            self.payload(
                category="tv",
                universe="marvel",
                collection="Loki",
                items=[
                    self.item(
                        source,
                        source_path=source["path"],
                        fs_id=101,
                        layout="episode",
                        canonical_title="Loki",
                        year=None,
                        imdb_id="tt1286039",
                        season=1,
                        episode=1,
                    )
                ],
            ),
            [source],
        )
        self.assertEqual(
            normalized["items"][0],
            {
                "source_path": source["path"],
                "fs_id": 101,
                "size": 1000,
                "layout": "episode",
                "canonical_title": "Loki",
                "year": None,
                "imdb_id": "tt1286039",
                "season": 1,
                "episode": 1,
                "quality": "1080p",
                "extension": "mkv",
                "target_dir": "/apps/bdpan/片库/Movies/Marvel Cinematic Universe/Loki/Loki.S01",
                "target_name": "Loki.S01E01.{imdb-tt1286039}.1080p.mkv",
            },
        )

    def test_no_universe_tv_target_uses_a_work_folder(self):
        source = self.source("The.Bear.S02E03.mkv")
        normalized = self.normalize(
            self.payload(
                category="tv",
                items=[
                    self.item(
                        source,
                        layout="episode",
                        canonical_title="The Bear",
                        year=None,
                        imdb_id="tt14452776",
                        season=2,
                        episode=3,
                    )
                ],
            ),
            [source],
        )
        self.assertEqual(
            normalized["items"][0]["target_dir"],
            "/apps/bdpan/片库/TV shows/The Bear/The.Bear.S02",
        )
        self.assertEqual(
            normalized["items"][0]["target_name"],
            "The.Bear.S02E03.{imdb-tt14452776}.1080p.mkv",
        )

    def test_marvel_xmen_two_movie_targets_remove_numeric_prefixes(self):
        first = self.source("1. X-Men.2000.mkv", fs_id=201, size=1000)
        second = self.source("2. X2.2003.mkv", fs_id=202, size=2000)
        normalized = self.normalize(
            self.payload(
                universe="marvel",
                collection="X-Men film series",
                items=[
                    self.item(
                        first,
                        fs_id=201,
                        size=1000,
                        canonical_title="X-Men",
                        year="2000",
                        imdb_id="tt0120903",
                    ),
                    self.item(
                        second,
                        fs_id=202,
                        size=2000,
                        canonical_title="X2",
                        year="2003",
                        imdb_id="tt0290334",
                    ),
                ],
            ),
            [first, second],
        )
        self.assertEqual(
            [item["target_dir"] for item in normalized["items"]],
            [
                "/apps/bdpan/片库/Movies/Marvel Cinematic Universe/X-Men film series/X-Men.2000",
                "/apps/bdpan/片库/Movies/Marvel Cinematic Universe/X-Men film series/X2.2003",
            ],
        )
        self.assertEqual(
            [item["target_name"] for item in normalized["items"]],
            ["X-Men.2000.{imdb-tt0120903}.1080p.mkv", "X2.2003.{imdb-tt0290334}.1080p.mkv"],
        )
        for item in normalized["items"]:
            self.assertNotIn("/1.", item["target_dir"])
            self.assertNotIn("/2.", item["target_dir"])
            self.assertFalse(item["target_name"].startswith(("1.", "2.")))

    def test_dc_universe_maps_to_movies_root(self):
        source = self.source("Batman.2022.mkv")
        normalized = self.normalize(
            self.payload(
                universe="dc",
                items=[
                    self.item(
                        source,
                        canonical_title="The Batman",
                        year="2022",
                        imdb_id="tt1874999",
                    )
                ],
            ),
            [source],
        )
        self.assertEqual(
            normalized["items"][0]["target_dir"],
            "/apps/bdpan/片库/Movies/DC Cinematic Universe/The.Batman.2022",
        )

    def test_load_rejects_malformed_utf8_oversized_and_non_regular_files(self):
        malformed = self.write_manifest({}, raw=b'{"version": 1,')
        with self.assertRaises(ValueError) as raised:
            load_media_manifest(
                malformed,
                settings=self.settings,
                source_dir=self.source_dir,
                sources=self.sources,
            )
        self.assertIsInstance(raised.exception.__cause__, json.JSONDecodeError)

        oversized = self.write_manifest({}, raw=b"{" + b" " * MAX_MANIFEST_BYTES + b"}")
        with self.assertRaises(ValueError):
            load_media_manifest(
                oversized,
                settings=self.settings,
                source_dir=self.source_dir,
                sources=self.sources,
            )

        invalid_utf8 = self.write_manifest({}, raw=b"\xff")
        with self.assertRaises(ValueError):
            load_media_manifest(
                invalid_utf8,
                settings=self.settings,
                source_dir=self.source_dir,
                sources=self.sources,
            )

        directory = self.root / "manifest-dir"
        directory.mkdir()
        with self.assertRaises(ValueError):
            load_media_manifest(
                directory,
                settings=self.settings,
                source_dir=self.source_dir,
                sources=self.sources,
            )

    def test_load_rejects_unknown_keys_and_wrong_version(self):
        source = self.sources[0]
        for payload in (
            self.payload(items=[self.item(source, extra="nope")]),
            self.payload(items=[self.item(source)], extra="nope"),
            self.payload(items=[self.item(source)], version=2),
            self.payload(items=[self.item(source)], version=True),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.normalize(payload)

    def test_source_must_be_under_base_source_dir_and_discovered_exactly_once(self):
        source = self.sources[0]
        escaped = self.item(source, source_path="/apps/bdpan/Library/Movies/other.mkv")
        with self.assertRaises(ValueError):
            self.normalize(self.payload(items=[escaped]))

        outside = self.item(source, source_path="/elsewhere/incoming/movie.mkv")
        with self.assertRaises(ValueError):
            self.normalize(self.payload(items=[outside]))

        not_discovered = self.item(
            source,
            source_path=self.source_dir + "/not-discovered.mkv",
        )
        with self.assertRaises(ValueError):
            self.normalize(self.payload(items=[not_discovered]))

        with self.assertRaises(ValueError):
            self.normalize(self.payload(items=[self.item(source)]), sources=[])

    def test_source_identity_drift_and_duplicate_source_or_target_are_rejected(self):
        source = self.sources[0]
        with self.assertRaises(ValueError):
            self.normalize(self.payload(items=[self.item(source, fs_id=999)]))
        with self.assertRaises(ValueError):
            self.normalize(self.payload(items=[self.item(source, size=999)]))
        with self.assertRaises(ValueError):
            self.normalize(
                self.payload(items=[self.item(source), self.item(source)]),
                [source],
            )

        first = self.source("one.mkv", fs_id=301, size=301)
        second = self.source("two.mkv", fs_id=302, size=302)
        with self.assertRaises(ValueError):
            self.normalize(
                self.payload(
                    items=[
                        self.item(first, fs_id=301, size=301),
                        self.item(second, fs_id=302, size=302),
                    ]
                ),
                [first, second],
            )

    def test_invalid_category_universe_layout_title_year_imdb_quality_are_rejected(self):
        source = self.sources[0]
        cases = (
            {"category": "music"},
            {"universe": "MCU"},
            {"layout": "folder"},
            {"canonical_title": "../escape"},
            {"year": "202"},
            {"imdb_id": "imdb1234567"},
            {"quality": "1080p-extra"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.normalize(self.payload(items=[self.item(source, **overrides)]))

    def test_layout_required_and_forbidden_fields_are_rejected(self):
        source = self.sources[0]
        invalid = (
            {"layout": "single", "year": None},
            {"layout": "single", "season": 1},
            {"layout": "single", "episode": 1},
            {"layout": "episode", "year": "2020"},
            {"layout": "episode", "season": None, "episode": 1, "year": None},
            {"layout": "episode", "season": 1, "episode": None, "year": None},
            {"layout": "season", "year": "2020"},
            {"layout": "season", "season": None},
            {"layout": "season", "season": 1, "episode": 1},
            {"layout": "episode", "season": True, "episode": 1, "year": None},
            {"layout": "episode", "season": 1, "episode": False, "year": None},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.normalize(
                        self.payload(
                            category="tv",
                            items=[
                                self.item(
                                    source,
                                    canonical_title="Show",
                                    imdb_id="tt1234567",
                                    **overrides,
                                )
                            ],
                        )
                    )

    def test_layout_dependent_null_fields_may_be_omitted(self):
        source = self.sources[0]
        episode = self.item(
            source,
            layout="episode",
            canonical_title="Show",
            imdb_id="tt1234567",
            season=1,
            episode=1,
            year=None,
        )
        del episode["year"]
        normalized = self.normalize(
            self.payload(category="tv", items=[episode]),
            [source],
        )
        self.assertIsNone(normalized["items"][0]["year"])

    def test_season_target_uses_work_and_padded_season_folder(self):
        source = self.source("1. Loki.S02.mkv")
        normalized = self.normalize(
            self.payload(
                category="tv",
                universe="marvel",
                collection="Loki",
                items=[
                    self.item(
                        source,
                        layout="season",
                        canonical_title="Loki",
                        year=None,
                        imdb_id="tt1286039",
                        season=2,
                        episode=None,
                    )
                ],
            ),
            [source],
        )
        self.assertEqual(
            normalized["items"][0]["target_dir"],
            "/apps/bdpan/片库/Movies/Marvel Cinematic Universe/Loki/Loki.S02",
        )
        self.assertEqual(
            normalized["items"][0]["target_name"],
            "Loki.S02.{imdb-tt1286039}.1080p.mkv",
        )

    def test_size_fsid_and_extension_are_strict_and_extension_comes_from_source(self):
        source = self.source("movie.MKV", fs_id=None, size=0)
        normalized = self.normalize(
            self.payload(
                items=[
                    self.item(
                        source,
                        fs_id=None,
                        size=0,
                    )
                ]
            ),
            [source],
        )
        self.assertEqual(normalized["items"][0]["extension"], "mkv")

        for overrides in ({"size": True}, {"fs_id": True}, {"fs_id": 1.0}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.normalize(self.payload(items=[self.item(source, **overrides)]), [source])

        unsupported = self.source("movie.txt", fs_id=103, size=3)
        with self.assertRaises(ValueError):
            self.normalize(self.payload(items=[self.item(unsupported, fs_id=103, size=3)]), [unsupported])

    def test_manifest_plan_ref_is_stable_and_detects_source_or_target_drift(self):
        source = self.sources[0]
        normalized = self.normalize(self.payload(items=[self.item(source)]))
        snapshots = {
            "sources": [{"path": source["path"], "fs_id": source["fs_id"], "size": source["size"]}],
            "targets": [],
        }
        reference = manifest_plan_ref(normalized, snapshots)
        self.assertRegex(reference, r"^[0-9a-f]{64}$")
        self.assertEqual(
            reference,
            manifest_plan_ref(
                dict(reversed(normalized.items())),
                {"targets": [], "sources": list(reversed(snapshots["sources"]))},
            ),
        )
        self.assertNotEqual(
            reference,
            manifest_plan_ref(
                normalized,
                {"sources": [{"path": source["path"], "fs_id": 999}], "targets": []},
            ),
        )
        self.assertNotEqual(
            reference,
            manifest_plan_ref(
                normalized,
                {"sources": snapshots["sources"], "targets": [{"path": "/apps/bdpan/片库/Movies"}]},
            ),
        )

    def test_manifest_plan_ref_ignores_cloud_source_and_target_list_order(self):
        source = self.sources[0]
        normalized = self.normalize(self.payload(items=[self.item(source)]))
        snapshots = {
            "sources": [
                {"path": "/apps/bdpan/Library/Movies/incoming/a.mkv", "fs_id": 10, "size": 100},
                {"path": "/apps/bdpan/Library/Movies/incoming/b.mkv", "fs_id": 11, "size": 200},
            ],
            "targets": [
                {"target_dir": "/apps/bdpan/片库/Movies/A", "target_name": "a.mkv"},
                {"target_dir": "/apps/bdpan/片库/Movies/B", "target_name": "b.mkv"},
            ],
        }
        reversed_snapshots = {
            "targets": list(reversed(snapshots["targets"])),
            "sources": list(reversed(snapshots["sources"])),
        }
        self.assertEqual(
            manifest_plan_ref(normalized, snapshots),
            manifest_plan_ref(normalized, reversed_snapshots),
        )


if __name__ == "__main__":
    unittest.main()
