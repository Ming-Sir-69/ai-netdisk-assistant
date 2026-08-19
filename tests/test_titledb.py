from __future__ import annotations

import json
import unittest

from panlib import titledb


def _response(rows):
    return json.dumps({"results": {"bindings": rows}})


def _row(imdb, year, zh=None, en=None, country=None):
    row = {"imdb": {"value": imdb}, "year": {"value": str(year)}}
    if country:
        row["country"] = {"value": country}
    if zh:
        row["zh"] = {"value": zh}
    if en:
        row["en"] = {"value": en}
    return row


class TitleLookupTests(unittest.TestCase):
    """按片名与年份查官方名称与 IMDB 编号。

    走 Wikidata 的公开 SPARQL 端点——它是为程序化查询设计的结构化接口，
    无需 API key，也不存在反爬挑战，因此**不触碰 IMDb 与豆瓣的网页层**
    （那两处才是 2026-08 之前被拦死的地方）。

    最重要的约束：**候选不唯一时绝不替调用方挑一个**。撞名在中文译名里极其
    常见（《蜜桃成熟时》同时命中 1977 年德国片和 1993 年港片），猜错会把
    错误的编号永久写进文件名。
    """

    def test_a_single_candidate_is_reported_as_confident(self):
        fetch = lambda query: _response([_row("tt0109412", 1992, "赤裸羔羊", "Naked Killer")])
        result = titledb.lookup("赤裸羔羊", 1992, fetch=fetch)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["candidates"][0]["imdb_id"], "tt0109412")
        self.assertEqual(result["candidates"][0]["title_en"], "Naked Killer")
        self.assertEqual(result["candidates"][0]["title_zh"], "赤裸羔羊")

    def test_duplicate_rows_for_one_film_collapse_to_one_candidate(self):
        # SPARQL 的多语言 OPTIONAL 会让同一部片出现多行，那不是歧义。
        rows = [
            _row("tt0107565", 1993, "蜜桃成熟時", "Crazy Love"),
            _row("tt0107565", 1993, "蜜桃成熟時", "Crazy Love"),
        ]
        result = titledb.lookup("蜜桃成熟时", 1993, fetch=lambda q: _response(rows))
        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["candidates"]), 1)

    def test_several_distinct_films_are_returned_as_ambiguous_without_picking(self):
        rows = [
            _row("tt0108609", 1993, "香港奇案之強姦", "Raped by an Angel"),
            _row("tt0107399", 1993, "警花肉搏強姦黨", "Beyond the Copline"),
        ]
        result = titledb.lookup("強姦", 1993, fetch=lambda q: _response(rows))
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertNotIn("imdb_id", result)

    def test_no_match_is_reported_plainly_so_none_can_be_justified(self):
        # 「查过且没有」才是写 {imdb-none} 的依据；「没能力查」不是。
        result = titledb.lookup("查无此片", 1996, fetch=lambda q: _response([]))
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["candidates"], [])

    def test_the_year_window_is_bounded_and_appears_in_the_query(self):
        seen = {}

        def fetch(query):
            seen["query"] = query
            return _response([])

        titledb.lookup("X", 2000, slack=2, fetch=fetch)
        self.assertIn("1998", seen["query"])
        self.assertIn("2002", seen["query"])

    def test_a_transport_failure_is_surfaced_not_swallowed_as_not_found(self):
        def fetch(query):
            raise OSError("connection reset")

        def fallback_fetch(title):
            raise OSError("fallback down")

        with self.assertRaises(titledb.LookupError):
            titledb.lookup("X", 2000, fetch=fetch, fallback_fetch=fallback_fetch)

    def test_primary_failure_falls_back_to_imdb_suggestion(self):
        """主源网络失败时自动走 IMDb suggestion API,并标注来源。"""

        def fetch(query):
            raise OSError("timeout")

        fallback_payload = json.dumps(
            {
                "d": [
                    {"id": "tt0097165", "l": "Dead Poets Society", "y": 1989},
                    {"id": "tt0097166", "l": "Out-of-window film", "y": 1970},
                    {"id": "nm1234567", "l": "A person, not a film", "y": 1989},
                ]
            }
        )

        result = titledb.lookup(
            "Dead Poets Society", 1989, fetch=fetch, fallback_fetch=lambda title: fallback_payload
        )
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["source"], "imdb-suggestion")
        self.assertEqual(result["candidates"][0]["imdb_id"], "tt0097165")
        # 降级源没有中文名与产地,调用方需要知道这一点
        self.assertIsNone(result["candidates"][0]["title_zh"])
        self.assertIsNone(result["candidates"][0]["country"])

    def test_an_empty_fallback_is_not_absence_proof(self):
        """降级源对中文片名覆盖弱:空结果只能算「查不通」,不能算「查过且没有」。"""

        def fetch(query):
            raise OSError("timeout")

        with self.assertRaises(titledb.LookupError):
            titledb.lookup(
                "死亡诗社", 1989, fetch=fetch, fallback_fetch=lambda title: json.dumps({"d": []})
            )

    def test_an_unparsable_response_is_not_treated_as_an_empty_result(self):
        with self.assertRaises(titledb.LookupError):
            titledb.lookup("X", 2000, fetch=lambda q: "<html>blocked</html>")

    def test_titles_are_escaped_so_a_quote_cannot_break_the_query(self):
        seen = {}

        def fetch(query):
            seen["query"] = query
            return _response([])

        titledb.lookup('Say "Hi"', 2000, fetch=fetch)
        self.assertNotIn('"Hi"', seen["query"].split("CONTAINS")[1][:40])


class OriginCorroborationTests(unittest.TestCase):
    """只靠片名匹配会给出「看起来很确定」的错误答案。

    实测：查 1995 年港片《灵与慾》时，唯一命中的是美国电视电影
    *Alien Nation: Body and Soul*——它恰好有个撞名的中文译名。单一结果并不
    等于正确结果，所以候选必须带上制片国家供调用方佐证；这个字段命名契约
    本来也需要（决定用中文名还是英文名）。
    """

    def test_country_of_origin_is_returned_with_each_candidate(self):
        fetch = lambda q: _response(
            [_row("tt0109412", 1992, "赤裸羔羊", "Naked Killer", "Hong Kong")]
        )
        result = titledb.lookup("赤裸羔羊", 1992, fetch=fetch)
        self.assertEqual(result["candidates"][0]["country"], "Hong Kong")

    def test_a_lone_match_from_elsewhere_is_still_surfaced_for_judgement(self):
        # 不替调用方否决，但必须让「产地不符」这件事可见。
        fetch = lambda q: _response(
            [_row("tt0112319", 1995, "靈與慾", "Alien Nation: Body and Soul", "United States")]
        )
        result = titledb.lookup("靈與慾", 1995, fetch=fetch)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["candidates"][0]["country"], "United States")

    def test_a_missing_country_does_not_break_the_lookup(self):
        fetch = lambda q: _response([_row("tt0107565", 1993, "蜜桃成熟時", "Crazy Love")])
        result = titledb.lookup("蜜桃成熟时", 1993, fetch=fetch)
        self.assertIsNone(result["candidates"][0]["country"])


if __name__ == "__main__":
    unittest.main()
