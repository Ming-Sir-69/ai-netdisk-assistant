"""Strict, deterministic media folder and filename helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


_IMDB_RE = re.compile(r"^tt\d{7,8}$")
_YEAR_RE = re.compile(r"^(?:18|19|20|21)\d{2}$")
_EXTENSIONS = {
    "mkv", "mp4", "ts", "avi", "iso",
    "ass", "srt", "ssa", "sub", "sup", "vtt", "idx",
}
_QUALITIES = {"2160p", "1080p", "1080p.REMUX", "1080p.BluRay", "720p", "WEB-DL"}
_INVALID_NAME_CHARS = set('/\\:*?"<>|')

UNIVERSE_DIRS = {
    "marvel": "Marvel Cinematic Universe",
    "dc": "DC Cinematic Universe",
}


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must not be empty")
    return stripped


def universe_dir_name(key: str | None) -> str | None:
    """Return the canonical directory name for a supported universe key."""

    if key is None:
        return None
    value = _require_text(key, "universe")
    try:
        return UNIVERSE_DIRS[value]
    except KeyError:
        raise ValueError(f"unsupported universe: {key}") from None


def sanitize(name: str) -> str:
    """Convert benign punctuation to dots and reject path/unsafe input."""

    value = _require_text(name, "name")
    if ".." in value or any(char in _INVALID_NAME_CHARS for char in value):
        raise ValueError("name contains a path separator, traversal or illegal character")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("name contains a control character")

    sanitized = re.sub(r"[\s()\[\]【】]+", ".", value)
    sanitized = re.sub(r"\.{2,}", ".", sanitized).strip(".")
    if not sanitized or sanitized in {".", ".."}:
        raise ValueError("name becomes empty after sanitization")
    return sanitized


def normalize_movie_title(name: str) -> str:
    """Validate a canonical movie title while preserving word spaces."""

    value = _require_text(name, "movie_title")
    if ".." in value or any(char in _INVALID_NAME_CHARS for char in value):
        raise ValueError("movie_title contains a path separator, traversal or illegal character")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("movie_title contains a control character")
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized or normalized in {".", ".."}:
        raise ValueError("movie_title must not be empty")
    return normalized


_CHINA_COUNTRY_NAMES = {
    "china", "cn", "prc", "mainland china", "people's republic of china",
    "中国", "中国大陆",
}


def select_movie_title(
    production_countries: Iterable[str], title_zh: str, title_en: str
) -> str:
    """Choose the canonical title from structured production-country data."""

    countries = {
        _require_text(country, "production_country").casefold()
        for country in production_countries
    }
    if not countries:
        raise ValueError("at least one production_country is required")
    if countries.intersection(_CHINA_COUNTRY_NAMES):
        return normalize_movie_title(title_zh)
    return normalize_movie_title(title_en)


def is_chinese(name: str) -> bool:
    """Simple check for the presence of a CJK Unified Ideograph."""

    return bool(re.search(r"[\u4e00-\u9fff]", str(name)))


def validate_imdb_id(imdb_id: str) -> bool:
    """Return whether an IMDB identifier is ``tt`` plus 7–8 digits."""

    return isinstance(imdb_id, str) and bool(_IMDB_RE.fullmatch(imdb_id.strip()))


def _checked_imdb_id(imdb_id: str) -> str:
    value = _require_text(imdb_id, "imdb_id")
    if not validate_imdb_id(value):
        raise ValueError("imdb_id must match tt followed by 7-8 digits")
    return value


def validate_year(year: str) -> bool:
    """Return whether a year is a four-digit media release year."""

    return isinstance(year, str) and bool(_YEAR_RE.fullmatch(year.strip()))


def _checked_year(year: str) -> str:
    value = _require_text(year, "year")
    if not validate_year(value):
        raise ValueError("year must be a four-digit value between 1800 and 2199")
    return value


def _checked_extension(ext: str) -> str:
    value = _require_text(ext, "extension").lower()
    if value.startswith("."):
        value = value[1:]
    if not value or "." in value:
        raise ValueError(f"unsupported media extension: {ext}")
    if value not in _EXTENSIONS:
        raise ValueError(f"unsupported media extension: {ext}")
    return value


def normalize_quality(quality: str) -> str:
    """Normalize common quality labels to stable filename tokens."""

    value = _require_text(quality, "quality")
    q = re.sub(r"\s+", "", value).lower()
    aliases = {
        "2160p": "2160p",
        "4k": "2160p",
        "uhd": "2160p",
        "1080p": "1080p",
        "1080p.remux": "1080p.REMUX",
        "1080premux": "1080p.REMUX",
        "1080p原盘": "1080p.REMUX",
        "1080p.bluray": "1080p.BluRay",
        "1080pbluray": "1080p.BluRay",
        "1080p蓝光": "1080p.BluRay",
        "720p": "720p",
        "web-dl": "WEB-DL",
        "webdl": "WEB-DL",
    }
    if q in aliases:
        return aliases[q]
    return value


def _checked_quality(quality: str) -> str:
    normalized = normalize_quality(quality)
    if normalized not in _QUALITIES:
        raise ValueError(f"unsupported quality: {quality}")
    return normalized


def validate_quality(quality: str) -> bool:
    """Return whether a quality value is one of the declared aliases."""

    try:
        return normalize_quality(quality) in _QUALITIES
    except ValueError:
        return False


def validate_extension(ext: str) -> bool:
    """Return whether a media extension is supported by source discovery."""

    try:
        _checked_extension(ext)
    except ValueError:
        return False
    return True


def _checked_index(value: int | str, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field} must be a positive integer")
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def build_work_folder_name(canonical_title: str) -> str:
    """Generate a validated work/collection folder name."""

    return normalize_movie_title(canonical_title)


def build_season_folder_name(canonical_title: str, season: int) -> str:
    """Generate a validated season folder name with a zero-padded marker."""

    season_number = _checked_index(season, "season")
    return f"{sanitize(canonical_title)}.S{season_number:02d}"


def build_folder_name(title: str, imdb_id: str, year: str | None = None) -> str:
    """Generate a movie folder or the legacy TV folder marker safely.

    IMDB ID 只出现在视频文件名中，文件夹名不带 IMDB（2026-08-11 起）。
    ``imdb_id`` 参数保留用于校验与未来兼容，但不进入文件夹名。
    """

    if year is None:
        return f"{sanitize(title)}.{{imdb-{_checked_imdb_id(imdb_id)}}}"
    _checked_imdb_id(imdb_id)  # 校验但不入名
    return ".".join((sanitize(title), _checked_year(year)))


def build_movie_filename(
    title_en: str, year: str, quality: str, ext: str, imdb_id: str | None = None
) -> str:
    """Generate a single movie/documentary filename.

    IMDB ID 只在视频文件名上显示（2026-08-11 起规则）。传入 ``imdb_id``
    时插入 ``{imdb-ttXXX}`` 段；为 None 时保持旧格式（向后兼容）。
    """

    parts = [sanitize(title_en), _checked_year(year)]
    if imdb_id is not None:
        parts.append(f"{{imdb-{_checked_imdb_id(imdb_id)}}}")
    parts.extend([_checked_quality(quality), _checked_extension(ext)])
    return ".".join(parts)


def build_episode_filename(
    title_en: str,
    season: int,
    episode: int,
    imdb_id: str,
    quality: str,
    ext: str,
) -> str:
    """Generate ``Title.SxxExx.{imdb-id}.quality.ext``."""

    season_number = _checked_index(season, "season")
    episode_number = _checked_index(episode, "episode")
    return ".".join(
        (
            sanitize(title_en),
            f"S{season_number:02d}E{episode_number:02d}",
            f"{{imdb-{_checked_imdb_id(imdb_id)}}}",
            _checked_quality(quality),
            _checked_extension(ext),
        )
    )


def build_season_filename(
    title_en: str,
    season: int,
    imdb_id: str,
    quality: str,
    ext: str,
) -> str:
    """Generate a full-season filename."""

    season_number = _checked_index(season, "season")
    return ".".join(
        (
            sanitize(title_en),
            f"S{season_number:02d}",
            f"{{imdb-{_checked_imdb_id(imdb_id)}}}",
            _checked_quality(quality),
            _checked_extension(ext),
        )
    )


_SINGLE_EPISODE_RE = re.compile(
    r"(?i)(?<![a-z0-9])s(?P<season>\d{1,2})(?P<episodes>(?:e\d{1,4})+)(?![a-z0-9])"
)
_RANGE_EPISODE_RE = re.compile(
    r"(?i)(?<![a-z0-9])s(?P<season>\d{1,2})e(?P<first>\d{1,4})\s*[-_]\s*e?(?P<last>\d{1,4})(?![a-z0-9])"
)
_X_EPISODE_RE = re.compile(
    r"(?i)(?<![a-z0-9])(?P<season>\d{1,2})x(?P<episode>\d{1,4})(?![a-z0-9])"
)
_WORD_EPISODE_RE = re.compile(
    r"(?i)\bseason\s*(?P<season>\d{1,2})\s*(?:episode|ep|e)\s*(?P<episode>\d{1,4})\b"
)
_ZH_EPISODE_RE = re.compile(r"第(?P<season>\d{1,2})季第(?P<episode>\d{1,4})集")


def parse_episodes(source_name: str) -> list[tuple[int, int]]:
    """Extract one or more ``(season, episode)`` pairs from a source name."""

    value = _require_text(source_name, "source_name")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("source_name contains a control character")

    ranged = _RANGE_EPISODE_RE.search(value)
    if ranged:
        season = _checked_index(ranged.group("season"), "season")
        first = _checked_index(ranged.group("first"), "episode")
        last = _checked_index(ranged.group("last"), "episode")
        if last < first or last - first > 100:
            raise ValueError("episode range is invalid or too large")
        return [(season, episode) for episode in range(first, last + 1)]

    match = _SINGLE_EPISODE_RE.search(value)
    if match:
        season = _checked_index(match.group("season"), "season")
        episodes = re.findall(r"e(\d{1,4})", match.group("episodes"), re.IGNORECASE)
        return [(season, _checked_index(episode, "episode")) for episode in episodes]

    for pattern in (_X_EPISODE_RE, _WORD_EPISODE_RE, _ZH_EPISODE_RE):
        match = pattern.search(value)
        if match:
            return [
                (
                    _checked_index(match.group("season"), "season"),
                    _checked_index(match.group("episode"), "episode"),
                )
            ]
    return []


def parse_episode(source_name: str) -> tuple[int, int] | None:
    """Return the first parsed episode, or ``None`` when no marker exists."""

    episodes = parse_episodes(source_name)
    return episodes[0] if episodes else None


extract_episode = parse_episode


def _coerce_episode_values(item: object) -> list[tuple[int, int]]:
    if isinstance(item, str):
        parsed = parse_episodes(item)
        if not parsed:
            raise ValueError(f"could not parse season/episode from {item!r}")
        return parsed
    if isinstance(item, (tuple, list)) and len(item) == 2:
        return [(_checked_index(item[0], "season"), _checked_index(item[1], "episode"))]
    raise ValueError("episode input must be a source name or (season, episode) pair")


def reject_collisions(names: Iterable[str]) -> list[str]:
    """Return names once, failing if two actions target the same filename."""

    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"filename collision: {name}")
        seen.add(name)
        unique.append(name)
    return unique


validate_unique_names = reject_collisions


def build_episode_filenames(
    title_en: str,
    source_names: Iterable[object],
    imdb_id: str,
    quality: str,
    ext: str,
) -> list[str]:
    """Build distinct episode targets from source names or episode tuples."""

    targets: list[str] = []
    for item in source_names:
        for season, episode in _coerce_episode_values(item):
            targets.append(
                build_episode_filename(title_en, season, episode, imdb_id, quality, ext)
            )
    if not targets:
        raise ValueError("at least one episode is required")
    return reject_collisions(targets)


# --- 系列电影结构约束 ---------------------------------------------------------

_SERIES_MARKER = "{series}"


def series_folder_name(shared_title: str) -> str:
    """Build a series parent folder name from a shared main title.

    同系列不同期的电影必须归入一个系列副文件夹，命名为
    ``{共享主标题}.{series}``，与单部的 ``{imdb-ttXXXXXXX}`` 文件夹区分。

    >>> series_folder_name("The.Lord.of.the.Rings")
    'The.Lord.of.the.Rings.{series}'
    """

    base = sanitize(shared_title)
    if base.endswith(_SERIES_MARKER):
        return base
    return f"{base}.{_SERIES_MARKER}"


def is_series_folder(name: str) -> bool:
    """Return whether a folder name is a series parent folder."""

    return isinstance(name, str) and name.rstrip("/").endswith(_SERIES_MARKER)


def shared_main_title(title_en: str, known_main_titles: Iterable[str] | None = None) -> str:
    """Best-effort extraction of the shared main title for series grouping.

    优先用 ``known_main_titles``（已有系列主标题）做最长前缀匹配；
    否则按启发式去掉末尾副标题段。副标题常为多段（如 The.Two.Towers），
    因此启发式只作参考，最终归属由调用方确认。
    """

    cleaned = sanitize(title_en)
    if known_main_titles:
        candidates = sorted(
            (sanitize(t) for t in known_main_titles),
            key=len,
            reverse=True,
        )
        for main in candidates:
            if cleaned == main or cleaned.startswith(main + "."):
                return main
    parts = [p for p in cleaned.split(".") if p]
    stop = {"part", "chapter", "episode", "ii", "iii", "iv", "v"}
    for i, token in enumerate(parts):
        if token.lower() in stop or token.isdigit():
            return ".".join(parts[:i]) if i > 0 else ".".join(parts)
    return ".".join(parts[:-1]) if len(parts) > 1 else ".".join(parts)


# ---------------------------------------------------------------------------
# “已规范”判定（判断标准，区别于清晰度这个“执行标准”）
#
# 规则（铭哥 2026-08-11 拍板）：清晰度是执行/重命名时的规范，不是判断
# 是否需要整理的维度。因此判定“已规范”只看结构与 IMDB 标记，不看清晰度。
# 只要视频文件名含 ``{imdb-ttXXXXXXX}`` 段且扩展名合法，即视为已规范——
# 有没有清晰度段都算，避免占位清晰度或缺失清晰度被误判为“待整理”而重复调整。
# ---------------------------------------------------------------------------

_NORMALIZED_IMDB_RE = re.compile(r"\{imdb-tt\d{7,8}\}")


def _media_extension_of(name: str) -> str | None:
    """Return the lowercased extension when it is a known media/subtitle ext."""

    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[-1].lower()
    return ext if ext in _EXTENSIONS else None


def is_normalized_movie_filename(name: str) -> bool:
    """Return whether a movie/documentary filename is already normalized.

    已规范 = 文件名含 ``{imdb-ttXXXXXXX}`` 段，且扩展名是受支持的媒体/字幕
    扩展名。清晰度段可有可无（清晰度是执行标准，不是判断标准）。

    >>> is_normalized_movie_filename("Limitless.2011.{imdb-tt1219289}.mkv")
    True
    >>> is_normalized_movie_filename("Limitless.2011.{imdb-tt1219289}.1080p.mkv")
    True
    >>> is_normalized_movie_filename("Limitless.2011.tt1219289.mkv")
    False
    """

    if not isinstance(name, str) or not _NORMALIZED_IMDB_RE.search(name):
        return False
    return _media_extension_of(name) is not None


def is_normalized_episode_filename(name: str) -> bool:
    """Return whether an episode/season filename is already normalized.

    已规范 = 含 ``SxxExx``（单集）或 ``Sxx``（整季）标记 + ``{imdb-ttXXX}``
    段，扩展名合法。清晰度同样不作为判断维度。

    >>> is_normalized_episode_filename("Loki.S01E01.{imdb-tt1286039}.mkv")
    True
    >>> is_normalized_episode_filename("Loki.S02.{imdb-tt1286039}.1080p.mkv")
    True
    """

    if not isinstance(name, str) or not _NORMALIZED_IMDB_RE.search(name):
        return False
    if parse_episode(name) is None and not re.search(r"(?i)\bS\d{2}\b", name):
        return False
    return _media_extension_of(name) is not None
