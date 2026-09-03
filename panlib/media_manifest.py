"""Strict validation and deterministic target planning for media manifests.

The manifest layer is intentionally side-effect free.  It only compares the
declared source identity with a caller-provided discovery snapshot and builds
canonical cloud paths; all cloud reads and mutations remain the responsibility
of the command layer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .common import Settings, safe_cloud_join, validate_cloud_path
from .naming import (
    build_episode_filename,
    build_folder_name,
    build_movie_filename,
    build_season_filename,
    build_season_folder_name,
    build_work_folder_name,
    normalize_movie_title,
    normalize_quality,
    group_folder_name,
    validate_extension,
    validate_imdb_id,
    validate_media_id,
    validate_quality,
    validate_year,
)


MAX_MANIFEST_BYTES = 1_048_576
CATEGORY_DIRS = {
    "movie": "Movies",
    "tv": "TV shows",
    "anime": "Animation",  # 2026-08-30 铭哥定：旧名"动漫"已原地改名为 Animation，
    # 云端两个网盘根下的目录都已改完；这里若不同步会让审计和整理全部错认路径。
    "documentary": "Documentary",
    "webdrama": "网剧",
}

_MANIFEST_KEYS = {"version", "category", "groups", "items"}
_ITEM_KEYS = {
    "source_path",
    "fs_id",
    "size",
    "layout",
    "canonical_title",
    "year",
    "imdb_id",
    "season",
    "episode",
    "quality",
}
_LAYOUTS = {"single", "episode", "season"}


def _fail(message: str) -> None:
    raise ValueError(message)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        _fail(f"{field} must be a string")
    stripped = value.strip()
    if not stripped:
        _fail(f"{field} must not be empty")
    return stripped


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{field} must be a positive integer")
    return value


def _optional_positive_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_integer(value, field)


def _manifest_fs_id(value: object) -> int | str | None:
    """Accept numeric or opaque discovered IDs, but never booleans/empties."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        _fail("fs_id must be an integer, string, or null")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            _fail("fs_id must not be empty")
    return value


def _source_path(entry: Mapping[str, Any]) -> str | None:
    value = entry.get("path")
    if value is None:
        value = entry.get("full_path")
    return value if isinstance(value, str) else None


def _source_fs_id(entry: Mapping[str, Any]) -> object:
    if "fs_id" in entry:
        return entry["fs_id"]
    if "fsid" in entry:
        return entry["fsid"]
    return None


def _source_is_directory(entry: Mapping[str, Any]) -> bool:
    for key in ("isdir", "is_dir", "is_directory"):
        if key not in entry:
            continue
        value = entry[key]
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "no", "off"}
        return bool(value)
    return False


def _validated_sources(
    sources: list[dict],
    *,
    base: str,
) -> dict[str, list[Mapping[str, Any]]]:
    if not isinstance(sources, list):
        _fail("sources must be a list")
    by_path: dict[str, list[Mapping[str, Any]]] = {}
    for entry in sources:
        if not isinstance(entry, Mapping):
            continue
        raw_path = _source_path(entry)
        if raw_path is None:
            continue
        try:
            canonical_path = validate_cloud_path(raw_path, base)
        except (TypeError, ValueError):
            continue
        by_path.setdefault(canonical_path, []).append(entry)
    return by_path


def _validate_source_dir(source_dir: str, settings: Settings) -> tuple[str, PurePosixPath]:
    if not isinstance(source_dir, str):
        _fail("source_dir must be a string")
    try:
        canonical = validate_cloud_path(source_dir, settings.bdpan_base)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid source_dir: {source_dir}") from exc
    return canonical, PurePosixPath(canonical)


def _derive_extension(source_path: str) -> str:
    suffix = PurePosixPath(source_path).suffix
    if not suffix or "." in suffix[1:]:
        _fail("source_path must use one supported media extension")
    extension = suffix[1:].lower()
    if not validate_extension(extension):
        _fail(f"unsupported media extension: {extension}")
    return extension


def _format_keys(keys: set[object]) -> str:
    return ", ".join(sorted((str(key) for key in keys)))


def _normalise_top_level(payload: dict[str, Any]) -> tuple[int, str, list[str], list[Any]]:
    unknown = set(payload) - _MANIFEST_KEYS
    if unknown:
        _fail("manifest contains unknown top-level key(s): " + _format_keys(unknown))

    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        _fail("manifest version must be integer 1")

    category = _required_text(payload.get("category"), "category")
    if category not in CATEGORY_DIRS:
        _fail(f"unsupported category: {category}")

    # 分组层没有封闭名单：按从外到内的顺序声明即可，层数不限。
    # 每一段都过命名原语校验，因此路径分隔符、遍历和空段会被拒绝。
    raw_groups = payload.get("groups", [])
    if raw_groups is None:
        raw_groups = []
    if not isinstance(raw_groups, list):
        _fail("groups must be a list of group names, outermost first")
    groups: list[str] = []
    for index, value in enumerate(raw_groups):
        name = _required_text(value, f"groups[{index}]")
        try:
            groups.append(group_folder_name(name))
        except ValueError as exc:
            _fail(f"groups[{index}] is not a valid group name: {exc}")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        _fail("items must be a non-empty list")
    return 1, category, groups, items


def _normalise_item(
    raw_item: object,
    *,
    settings: Settings,
    source_root: PurePosixPath,
    discovered: dict[str, list[Mapping[str, Any]]],
    category: str,
    groups: list[str],
) -> dict[str, Any]:
    if not isinstance(raw_item, dict):
        _fail("each manifest item must be an object")
    unknown = set(raw_item) - _ITEM_KEYS
    if unknown:
        _fail("manifest item contains unknown key(s): " + _format_keys(unknown))
    # Identity and naming fields are always required.  Layout-dependent
    # fields may be omitted when they are not applicable; omission is treated
    # the same as an explicit JSON null and is represented explicitly in the
    # normalized output.
    missing = (_ITEM_KEYS - {"year", "season", "episode", "quality"}) - set(raw_item)
    if missing:
        _fail("manifest item is missing required field(s): " + ", ".join(sorted(missing)))

    raw_source_path = raw_item["source_path"]
    if not isinstance(raw_source_path, str):
        _fail("source_path must be a string")
    try:
        source_path = validate_cloud_path(raw_source_path, settings.bdpan_base)
    except (TypeError, ValueError) as exc:
        raise ValueError("source_path must stay under BDPAN_BASE") from exc
    source_path_obj = PurePosixPath(source_path)
    try:
        relative = source_path_obj.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("source_path must be a strict descendant of source_dir") from exc
    if not relative.parts:
        _fail("source_path must be a strict descendant of source_dir")

    matches = discovered.get(source_path, [])
    if len(matches) != 1:
        _fail("source_path must exactly match one discovered source")
    live = matches[0]
    if _source_is_directory(live):
        _fail("source_path must identify a regular media file")

    manifest_fs_id = _manifest_fs_id(raw_item["fs_id"])
    live_fs_id = _source_fs_id(live)
    if isinstance(live_fs_id, bool):
        _fail("discovered fs_id must not be boolean")
    if live_fs_id is None:
        if manifest_fs_id is not None:
            _fail("fs_id must be null when the discovered source has no fs_id")
    elif manifest_fs_id != live_fs_id:
        _fail("manifest fs_id does not match the discovered source")

    live_size = live.get("size")
    if isinstance(live_size, bool) or not isinstance(live_size, int):
        _fail("discovered source size must be an integer")
    manifest_size = raw_item["size"]
    if isinstance(manifest_size, bool) or not isinstance(manifest_size, int):
        _fail("size must be an integer")
    if manifest_size != live_size:
        _fail("manifest size does not match the discovered source")

    layout = _required_text(raw_item["layout"], "layout")
    if layout not in _LAYOUTS:
        _fail(f"unsupported layout: {layout}")

    canonical_title = normalize_movie_title(
        _required_text(raw_item["canonical_title"], "canonical_title")
    )
    year = _optional_text(raw_item.get("year"), "year")
    if year is not None and not validate_year(year):
        _fail("year must be a four-digit value between 1800 and 2199")

    imdb_id = _required_text(raw_item["imdb_id"], "imdb_id")
    if not validate_media_id(imdb_id):
        _fail("imdb_id must match tt followed by 7-8 digits, or be 'none'")

    season = _optional_positive_integer(raw_item.get("season"), "season")
    episode = _optional_positive_integer(raw_item.get("episode"), "episode")

    # 清晰度可缺省：云端不返回宽高、抽样探测又缺通道，「测不出」是常态。
    # 缺省时文件名省略该段；给了值就必须是受支持的取值，不接受占位文字。
    raw_quality = raw_item.get("quality")
    if raw_quality is None:
        quality = None
    else:
        quality = _required_text(raw_quality, "quality")
        if not validate_quality(quality):
            _fail(f"unsupported quality: {quality}")
        quality = normalize_quality(quality)

    if layout == "single":
        if year is None:
            _fail("single layout requires year")
        if season is not None or episode is not None:
            _fail("single layout forbids season and episode")
    elif layout == "episode":
        if year is not None:
            _fail("episode layout forbids year")
        if season is None or episode is None:
            _fail("episode layout requires season and episode")
    else:  # season
        if year is not None:
            _fail("season layout forbids year")
        if season is None:
            _fail("season layout requires season")
        if episode is not None:
            _fail("season layout forbids episode")

    extension = _derive_extension(source_path)

    # 类别根始终生效：分组不再覆盖它，因此剧集不会被分组带进 Movies。
    root = safe_cloud_join(
        settings.bdpan_base,
        settings.bdpan_lib,
        CATEGORY_DIRS[category],
    )

    parent_parts: list[str] = [root, *groups]
    if layout == "single":
        item_dir_name = build_folder_name(canonical_title, imdb_id, year)
        target_dir = safe_cloud_join(*parent_parts, item_dir_name)
        target_name = build_movie_filename(
            canonical_title, year, quality, extension, imdb_id
        )
    else:
        # 分季内容天然会增长，所以一律有作品分组层；未显式声明时按作品名建立。
        if not groups:
            parent_parts.append(group_folder_name(canonical_title))
        item_dir_name = build_season_folder_name(canonical_title, season)
        target_dir = safe_cloud_join(*parent_parts, item_dir_name)
        if layout == "episode":
            target_name = build_episode_filename(
                canonical_title,
                season,
                episode,
                imdb_id,
                quality,
                extension,
            )
        else:
            target_name = build_season_filename(
                canonical_title,
                season,
                imdb_id,
                quality,
                extension,
            )

    return {
        "source_path": source_path,
        "fs_id": manifest_fs_id,
        "size": manifest_size,
        "layout": layout,
        "canonical_title": canonical_title,
        "year": year,
        "imdb_id": imdb_id,
        "season": season,
        "episode": episode,
        "quality": quality,
        "extension": extension,
        "target_dir": target_dir,
        "target_name": target_name,
    }


def normalize_media_manifest(
    payload: object,
    *,
    settings: Settings,
    source_dir: str,
    sources: list[dict],
) -> dict:
    """Validate a manifest object and return its canonical, side-effect-free plan."""

    if not isinstance(payload, dict):
        _fail("manifest must be one JSON object")
    _, category, groups, raw_items = _normalise_top_level(payload)
    _, source_root = _validate_source_dir(source_dir, settings)
    discovered = _validated_sources(sources, base=settings.bdpan_base)

    normalized_items: list[dict[str, Any]] = []
    source_paths: set[str] = set()
    targets: set[tuple[str, str]] = set()
    for raw_item in raw_items:
        # Validate source identity before deriving targets.  Keeping this
        # sequence deterministic also makes duplicate diagnostics predictable.
        item = _normalise_item(
            raw_item,
            settings=settings,
            source_root=source_root,
            discovered=discovered,
            category=category,
            groups=groups,
        )
        source_path = item["source_path"]
        if source_path in source_paths:
            _fail("duplicate source_path in manifest")
        source_paths.add(source_path)
        target_identity = (item["target_dir"], item["target_name"])
        if target_identity in targets:
            _fail("duplicate final target in manifest")
        targets.add(target_identity)
        normalized_items.append(item)

    return {
        "version": 1,
        "category": category,
        "groups": groups,
        "items": normalized_items,
    }


def load_media_manifest(
    path: str | Path,
    *,
    settings: Settings,
    source_dir: str,
    sources: list[dict],
) -> dict:
    """Read and normalize a bounded UTF-8 JSON manifest file."""

    try:
        manifest_path = Path(path)
        if not manifest_path.is_file():
            _fail("manifest path must be a regular file")
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            _fail("manifest exceeds MAX_MANIFEST_BYTES")
        raw = manifest_path.read_bytes()
    except ValueError:
        raise
    except (OSError, TypeError) as exc:
        raise ValueError("unable to read manifest file") from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        _fail("manifest exceeds MAX_MANIFEST_BYTES")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("manifest must be UTF-8 JSON") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("manifest is not valid JSON") from exc
    return normalize_media_manifest(
        payload,
        settings=settings,
        source_dir=source_dir,
        sources=sources,
    )


def _snapshot_canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalize_snapshot(value: object, *, list_key: str | None = None) -> object:
    """Recursively normalize cloud-returned source/target collections only."""

    if isinstance(value, Mapping):
        return {
            key: _normalize_snapshot(item, list_key=key if isinstance(key, str) else None)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        normalized = [_normalize_snapshot(item) for item in value]
        if list_key in {"sources", "targets"}:
            # Sort, but do not deduplicate: multiplicity and every field still
            # participate in the fingerprint, so real drift is preserved.
            normalized.sort(key=_snapshot_canonical_json)
        return normalized
    return value


def manifest_plan_ref(normalized_manifest: dict, snapshots: object) -> str:
    """Return a stable SHA-256 fingerprint for a manifest and live snapshots."""

    try:
        stable_snapshots = _normalize_snapshot(snapshots)
        encoded = _snapshot_canonical_json(
            {"manifest": normalized_manifest, "snapshots": stable_snapshots}
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("manifest and snapshots must be JSON serializable") from exc
    return hashlib.sha256(encoded).hexdigest()
