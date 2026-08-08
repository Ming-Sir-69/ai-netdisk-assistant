"""Strict, deterministic media folder and filename helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


_IMDB_RE = re.compile(r"^tt\d{7,8}$")
_YEAR_RE = re.compile(r"^(?:18|19|20|21)\d{2}$")
_EXTENSIONS = {"mkv", "mp4", "ts", "avi", "iso"}
_QUALITIES = {"2160p", "1080p", "1080p.REMUX", "1080p.BluRay", "720p", "WEB-DL"}
_INVALID_NAME_CHARS = set('/\\:*?"<>|')


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must not be empty")
    return stripped


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


def build_folder_name(title: str, imdb_id: str) -> str:
    """Generate ``{Name}.{imdb-ttXXXXXXX}`` safely."""

    return f"{sanitize(title)}.{{imdb-{_checked_imdb_id(imdb_id)}}}"


def build_movie_filename(title_en: str, year: str, quality: str, ext: str) -> str:
    """Generate a single movie/documentary filename."""

    return ".".join(
        (sanitize(title_en), _checked_year(year), _checked_quality(quality), _checked_extension(ext))
    )


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
