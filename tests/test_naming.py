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


class RecursiveGroupNamingTests(unittest.TestCase):
    """递归分组契约（2026-08-15 起）：`.{series}` 后缀标识分组节点，层数不限。

    这三个分组函数此前在整个仓库零测试覆盖，且生产代码从未调用——
    而云端 91 部电影正用这套结构，属于契约与实现脱节。
    """

    def test_group_folder_name_is_idempotent_and_marks_the_node(self):
        self.assertEqual(naming.group_folder_name("Spider-Man"), "Spider-Man.{series}")
        # 已带后缀的不再重复追加
        self.assertEqual(
            naming.group_folder_name("Spider-Man.{series}"), "Spider-Man.{series}"
        )
        self.assertEqual(
            naming.group_folder_name("Marvel Cinematic Universe"),
            "Marvel.Cinematic.Universe.{series}",
        )

    def test_is_group_folder_separates_groups_from_content_nodes(self):
        self.assertTrue(naming.is_group_folder("Spider-Man.{series}"))
        self.assertTrue(naming.is_group_folder("Spider-Man.{series}/"))
        # 内容节点：单体带年份、分季带 Sxx，都不带后缀
        self.assertFalse(naming.is_group_folder("Spider-Man.2002"))
        self.assertFalse(naming.is_group_folder("Loki.S01"))
        self.assertFalse(naming.is_group_folder(""))

    def test_group_path_supports_unlimited_depth_and_no_group_at_all(self):
        self.assertEqual(naming.build_group_relative_path([]), "")
        self.assertEqual(
            naming.build_group_relative_path(["Marvel"]), "Marvel.{series}"
        )
        # 蜘蛛侠的按主演分线：三层分组是合法结构，不再要求拉平
        self.assertEqual(
            naming.build_group_relative_path(["Marvel", "Spider-Man", "Spider-Man.Tobey"]),
            "Marvel.{series}/Spider-Man.{series}/Spider-Man.Tobey.{series}",
        )

    def test_group_path_rejects_unsafe_or_empty_segments(self):
        for bad in (["../escape"], [""], ["a/b"], ["ok", ".."]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    naming.build_group_relative_path(bad)

    def test_shared_main_title_prefers_known_titles_over_the_heuristic(self):
        # 不给已知系列时启发式会切错（这正是它必须由调用方确认的原因）
        self.assertEqual(
            naming.shared_main_title("Ant-Man and the Wasp Quantumania"),
            "Ant-Man.and.the.Wasp",
        )
        self.assertEqual(
            naming.shared_main_title(
                "Ant-Man and the Wasp Quantumania", ["Ant-Man"]
            ),
            "Ant-Man",
        )


class BuildWithPlaceholderTests(unittest.TestCase):
    """构造文件名时也要能写出占位符，否则「查过且无」这条规则无法执行。

    判定函数早就认 {imdb-none} 了，但构造函数只认真实编号——规则写得出来、
    落不了地。红灯区(1996) 查过确无条目，正是卡在这里。
    """

    def test_movie_filename_can_be_built_with_the_placeholder(self):
        self.assertEqual(
            naming.build_movie_filename("红灯区", "1996", None, "mp4", "none"),
            "红灯区.1996.{imdb-none}.mp4",
        )

    def test_episode_filename_can_be_built_with_the_placeholder(self):
        self.assertEqual(
            naming.build_episode_filename("某剧", 1, 2, "none", None, "mkv"),
            "某剧.S01E02.{imdb-none}.mkv",
        )

    def test_what_it_builds_is_recognised_as_normalized(self):
        built = naming.build_movie_filename("红灯区", "1996", None, "mp4", "none")
        self.assertTrue(naming.is_normalized_movie_filename(built))

    def test_arbitrary_placeholder_text_is_still_rejected(self):
        for bad in ("tbd", "unknown", "null", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    naming.build_movie_filename("片", "2001", None, "mkv", bad)


class LegacyContainerExtensionTests(unittest.TestCase):
    """rmvb / webm 也是视频容器。

    片库里有 9 个 rmvb 和 1 个 webm，命名都已经规范，却因为不在扩展名清单里
    被判成「非媒体文件」——一个纯粹由清单遗漏造成的误报。
    """

    def test_legacy_video_containers_are_recognised(self):
        for ext in ("rmvb", "webm"):
            with self.subTest(ext=ext):
                self.assertTrue(naming.validate_extension(ext))
                self.assertTrue(
                    naming.is_normalized_movie_filename(f"Home.Alone.1990.{{imdb-tt0099785}}.{ext}")
                )

    def test_images_and_notes_remain_out_of_scope(self):
        for ext in ("jpg", "nfo", "txt", "pdf"):
            with self.subTest(ext=ext):
                self.assertFalse(naming.validate_extension(ext))


class OptionalQualityTests(unittest.TestCase):
    """清晰度拿不到就不写（铭哥 2026-08-15 定）。

    云端接口不返回宽高，抽样探测又缺通道，所以「测不出清晰度」是常态而非
    异常。必填会让这批文件永远整理不了。
    """

    def test_movie_filename_omits_the_segment_when_quality_is_unknown(self):
        self.assertEqual(
            naming.build_movie_filename("The Movie", "2020", None, "mkv", "tt1234567"),
            "The.Movie.2020.{imdb-tt1234567}.mkv",
        )

    def test_episode_filename_omits_the_segment_when_quality_is_unknown(self):
        self.assertEqual(
            naming.build_episode_filename("Loki", 1, 2, "tt1286039", None, "mkv"),
            "Loki.S01E02.{imdb-tt1286039}.mkv",
        )

    def test_a_known_quality_is_still_required_to_be_valid(self):
        with self.assertRaises(ValueError):
            naming.build_movie_filename("X", "2020", "9001p", "mkv", "tt1234567")


class PlaceholderImdbTests(unittest.TestCase):
    """无 IMDB 编号统一写 {imdb-none}（铭哥 2026-08-15 定）。

    旧规则是「省略该段」，导致这批文件与「漏写了」无法区分，
    每次扫描都被重新标记为待整理，永远处理不完。
    """

    def test_placeholder_counts_as_normalized_for_movies_and_episodes(self):
        self.assertTrue(
            naming.is_normalized_movie_filename("玉蒲团.1991.{imdb-none}.mkv")
        )
        self.assertTrue(
            naming.is_normalized_movie_filename("玉蒲团.1991.{imdb-none}.1080p.mkv")
        )
        self.assertTrue(
            naming.is_normalized_episode_filename("某剧.S01E01.{imdb-none}.mkv")
        )

    def test_missing_segment_is_still_not_normalized(self):
        # 「确认没有编号」写 none；「漏写了」仍必须判为待整理
        self.assertFalse(naming.is_normalized_movie_filename("玉蒲团.1991.mkv"))
        self.assertFalse(naming.is_normalized_movie_filename("玉蒲团.1991.1080p.mkv"))

    def test_placeholder_must_be_exactly_none_not_arbitrary_text(self):
        for bad in ("{imdb-tbd}", "{imdb-}", "{imdb-unknown}", "{imdb-null}"):
            with self.subTest(bad=bad):
                self.assertFalse(
                    naming.is_normalized_movie_filename(f"片.2001.{bad}.mkv")
                )


if __name__ == "__main__":
    unittest.main()
