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

    def test_folder_and_episode_names_keep_imdb_marker(self):
        self.assertEqual(
            naming.build_folder_name("Limitless", "tt1219289"),
            "Limitless.{imdb-tt1219289}",
        )
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
            naming.build_folder_name("Show", "bad-id")
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


if __name__ == "__main__":
    unittest.main()
