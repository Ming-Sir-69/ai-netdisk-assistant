import unittest

import panlib.naming as naming


class NamingValidationTests(unittest.TestCase):
    def test_valid_imdb_year_quality_and_extension_build_movie_name(self):
        if not hasattr(naming, "validate_imdb_id"):
            self.fail("validate_imdb_id is not implemented")
        self.assertTrue(naming.validate_imdb_id("tt1219289"))
        self.assertTrue(naming.validate_year("2011"))
        self.assertEqual(naming.normalize_quality("1080p BluRay"), "1080p.BluRay")
        self.assertEqual(
            naming.build_movie_filename("Mr. & Mrs. Smith", "2005", "1080p", "mkv"),
            "Mr.&.Mrs.Smith.2005.1080p.mkv",
        )
        # 传入 imdb_id 时，电影文件名带 IMDB 段（2026-08-11 起规则）
        self.assertEqual(
            naming.build_movie_filename(
                "Mr. & Mrs. Smith", "2005", "1080p", "mkv", "tt0356910"
            ),
            "Mr.&.Mrs.Smith.2005.{imdb-tt0356910}.1080p.mkv",
        )

    def test_movie_folder_uses_title_year_without_imdb_id(self):
        # 文件夹不带 IMDB（2026-08-11 起规则）：IMDB 只在视频文件名上；点分隔
        self.assertEqual(
            naming.build_folder_name("A Walk in the Clouds", "tt0114887", "1995"),
            "A.Walk.in.the.Clouds.1995",
        )

    def test_country_selects_the_canonical_movie_title(self):
        self.assertEqual(
            naming.select_movie_title(["China"], "中国机长", "The Captain"),
            "中国机长",
        )
        self.assertEqual(
            naming.select_movie_title(["United States"], "毒液", "Venom"),
            "Venom",
        )

    def test_episode_names_keep_imdb_marker(self):
        self.assertEqual(
            naming.build_episode_filename("Breaking Bad", 1, 3, "tt0903747", "1080p", "mkv"),
            "Breaking.Bad.S01E03.{imdb-tt0903747}.1080p.mkv",
        )

    def test_episode_parser_handles_common_single_and_multi_episode_forms(self):
        if not hasattr(naming, "parse_episode") or not hasattr(naming, "parse_episodes"):
            self.fail("episode parsing is not implemented")
        self.assertEqual(naming.parse_episode("Show.S02E03.mkv"), (2, 3))
        self.assertEqual(naming.parse_episode("Show 3x04.mkv"), (3, 4))
        self.assertEqual(naming.parse_episode("Show 第4季第5集"), (4, 5))
        self.assertEqual(
            naming.parse_episodes("Show.S01E01E02.mkv"), [(1, 1), (1, 2)]
        )

    def test_episode_batch_rejects_collision_prone_inputs(self):
        if not hasattr(naming, "build_episode_filenames"):
            self.fail("build_episode_filenames is not implemented")
        with self.assertRaises(ValueError):
            naming.build_episode_filenames(
                "Show",
                ["Show.S01E01.part-a.mkv", "Show.S01E01.part-b.mkv"],
                "tt1234567",
                "1080p",
                "mkv",
            )

    def test_sanitize_rejects_path_separators_traversal_colon_control_and_empty(self):
        for value in ("", "../escape", "a/b", "a\\b", "a:b", "bad\nname"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    naming.sanitize(value)

    def test_strict_media_fields_reject_invalid_values(self):
        invalid_movies = (
            ("Show", "20x1", "1080p", "mkv"),
            ("Show", "2020", "", "mkv"),
            ("Show", "2020", "1080p", "."),
        )
        for title, year, quality, ext in invalid_movies:
            with self.subTest(year=year, quality=quality, ext=ext):
                with self.assertRaises(ValueError):
                    naming.build_movie_filename(title, year, quality, ext)

        with self.assertRaises(ValueError):
            naming.build_folder_name("Show", "bad-id", "2020")
        with self.assertRaises(ValueError):
            naming.build_episode_filename("Show", 0, 1, "tt1234567", "1080p", "mkv")

    def test_rejects_malformed_extensions_and_quality_prefix_suffixes(self):
        for ext in ("..mkv", "foo.mkv", "mov"):
            with self.subTest(ext=ext):
                with self.assertRaises(ValueError):
                    naming.build_movie_filename("Show", "2020", "1080p", ext)

        for quality in ("2160p-untrusted", "oops1080p", "1080p.BluRay-extra"):
            with self.subTest(quality=quality):
                with self.assertRaises(ValueError):
                    naming.build_movie_filename("Show", "2020", quality, "mkv")


class HierarchicalNamingTests(unittest.TestCase):
    def test_universe_dir_name_maps_supported_keys_and_none(self):
        self.assertEqual(
            naming.universe_dir_name("marvel"), "Marvel Cinematic Universe"
        )
        self.assertEqual(naming.universe_dir_name("dc"), "DC Cinematic Universe")
        self.assertIsNone(naming.universe_dir_name(None))

    def test_universe_dir_name_rejects_unknown_and_legacy_keys(self):
        for key in ("", "MCU", "unknown"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    naming.universe_dir_name(key)

    def test_work_folder_name_preserves_canonical_word_spaces(self):
        self.assertEqual(naming.build_work_folder_name("Loki"), "Loki")
        self.assertEqual(naming.build_work_folder_name("Moon Knight"), "Moon Knight")

    def test_season_folder_name_sanitizes_title_and_pads_season(self):
        self.assertEqual(naming.build_season_folder_name("Loki", 1), "Loki.S01")
        self.assertEqual(
            naming.build_season_folder_name("Moon Knight", 2), "Moon.Knight.S02"
        )

    def test_hierarchical_names_reject_invalid_titles_and_seasons(self):
        for title in ("", "../escape", "a/b", "bad\nname"):
            with self.subTest(title=title):
                with self.assertRaises(ValueError):
                    naming.build_work_folder_name(title)
                with self.assertRaises(ValueError):
                    naming.build_season_folder_name(title, 1)

        for season in (0, -1, True):
            with self.subTest(season=season):
                with self.assertRaises(ValueError):
                    naming.build_season_folder_name("Loki", season)

    def test_is_normalized_movie_filename_ignores_quality_segment(self):
        # 清晰度是执行标准不是判断标准：有/无清晰度段都判定已规范，
        # 避免占位或缺失清晰度被误判为待整理而重复调整（铭哥 2026-08-11）。
        self.assertTrue(
            naming.is_normalized_movie_filename("Limitless.2011.{imdb-tt1219289}.mkv")
        )
        self.assertTrue(
            naming.is_normalized_movie_filename(
                "Limitless.2011.{imdb-tt1219289}.1080p.mkv"
            )
        )
        # 字幕扩展名同样视为已规范
        self.assertTrue(
            naming.is_normalized_movie_filename("Limitless.2011.{imdb-tt1219289}.ass")
        )
        # 裸 tt（无花括号）不是新规范 → 未规范
        self.assertFalse(
            naming.is_normalized_movie_filename("Limitless.2011.tt1219289.mkv")
        )
        # 非媒体扩展名 → 未规范
        self.assertFalse(naming.is_normalized_movie_filename("poster.jpg"))

    def test_is_normalized_episode_filename(self):
        self.assertTrue(
            naming.is_normalized_episode_filename("Loki.S01E01.{imdb-tt1286039}.mkv")
        )
        self.assertTrue(
            naming.is_normalized_episode_filename(
                "Loki.S02.{imdb-tt1286039}.1080p.mkv"
            )
        )
        self.assertFalse(
            naming.is_normalized_episode_filename("Loki.S01E01.tt1286039.mkv")
        )


if __name__ == "__main__":
    unittest.main()
