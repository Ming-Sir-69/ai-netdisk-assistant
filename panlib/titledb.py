"""Look up a film's official titles, year and IMDB id from structured data.

查询走 Wikidata 的公开 SPARQL 端点：它是为程序化查询设计的结构化接口，
不需要 API key，也没有反爬挑战——**因此不触碰 IMDb 与豆瓣的网页层**，
而那两处正是此前被拦死的地方（豆瓣 dae 拦截、IMDb 直搜 202）。

它一次给齐命名契约需要的三样东西：官方中文名、官方英文名、发行年份，
外加 IMDB 编号。

**候选不唯一时绝不替调用方挑一个。** 中文译名撞名极其常见——《蜜桃成熟时》
同时命中 1977 年的德国片和 1993 年的港片——猜错会把错误编号永久写进文件名。
歧义留给上层按证据链裁决。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Callable

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "panlib-titledb/1.0 (personal media library)"
TIMEOUT = 60

_QUERY = """SELECT ?imdb ?zh ?en ?year WHERE {{
  ?item wdt:P345 ?imdb ; wdt:P577 ?date .
  BIND(YEAR(?date) AS ?year)
  FILTER(?year >= {low} && ?year <= {high})
  ?item rdfs:label ?label .
  FILTER(CONTAINS(?label, "{needle}"))
  OPTIONAL {{ ?item rdfs:label ?zh . FILTER(LANG(?zh) = "zh") }}
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
}} LIMIT {limit}"""


class LookupError(RuntimeError):
    """The lookup could not be completed, which is not the same as no match."""


def _escape(value: str) -> str:
    """Escape a literal for SPARQL so a quote cannot terminate the string."""

    return value.replace("\\", "\\\\").replace('"', '\\"')


def _default_fetch(query: str) -> str:
    url = f"{ENDPOINT}?query={urllib.parse.quote(query)}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def lookup(
    title: str,
    year: int,
    *,
    slack: int = 1,
    limit: int = 8,
    fetch: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Return ``{status, candidates}`` for one title within a year window.

    ``status`` is ``found`` (exactly one film), ``ambiguous`` (several) or
    ``not_found``. Only ``not_found`` justifies writing ``{imdb-none}``——
    「查过且没有」才是依据，「没能力查」不是。
    """

    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must not be empty")
    query = _QUERY.format(
        needle=_escape(title.strip()),
        low=int(year) - int(slack),
        high=int(year) + int(slack),
        limit=int(limit),
    )
    try:
        raw = (fetch or _default_fetch)(query)
    except Exception as exc:  # transport, timeout, DNS…
        raise LookupError(f"title lookup could not reach the endpoint: {exc}") from exc

    try:
        rows = json.loads(raw)["results"]["bindings"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        # 一个读不懂的响应（挑战页、错误页）绝不能当成「没有结果」，
        # 否则会被误当作写 none 的依据。
        raise LookupError("title lookup returned an unreadable response") from exc

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        imdb = str(row.get("imdb", {}).get("value", ""))
        if not imdb or imdb in seen:
            continue
        seen.add(imdb)
        candidates.append(
            {
                "imdb_id": imdb,
                "title_zh": row.get("zh", {}).get("value"),
                "title_en": row.get("en", {}).get("value"),
                "year": row.get("year", {}).get("value"),
            }
        )

    if not candidates:
        status = "not_found"
    elif len(candidates) == 1:
        status = "found"
    else:
        status = "ambiguous"
    return {"status": status, "query_title": title, "query_year": year, "candidates": candidates}
