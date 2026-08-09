#!/usr/bin/env python3
"""
SeedHub CLI - 影视资源搜索 & 下载链接提取

搜索 SeedHub 影视资源，自动提取夸克网盘/百度网盘等下载链接。

[vendor-patch by seedhub-baidu-pan-workflow skill]
- 域名修复: seedhub.cc (DNS 已过期) → seeduck.cc (真实活跃域)
- 新增 --json flag: 输出机器可读 JSON
- 新增 --resource-type 过滤: 电影/剧集/动漫
- 百度网盘解析增强: follow link_start 中间页 + 提取码正则
"""

import sys
import os
import re
import json
import argparse
import urllib.parse
import html as html_lib
from pathlib import Path

try:
    import cloudscraper
except ImportError:
    print("❌ 缺少依赖: cloudscraper")
    print("   安装: pip install cloudscraper")
    sys.exit(1)

# [vendor-patch] 域名修复.  This is deliberately code-owned: environment
# variables must not redirect the live request target.  Offline input is an
# explicit ``--fixture-dir`` seam handled by the CLI below.
SEEDHUB_BASE = "https://seeduck.cc"
FIXTURE_BASE = "https://seedhub.example"


class SeedhubParseError(RuntimeError):
    """Raised when a fetched/fixture page is not a recognizable SeedHub page."""


class SeedhubNetworkError(RuntimeError):
    """Raised when the formal SeedHub request cannot be completed."""


class _FixtureResponse:
    def __init__(self, text: str, status_code: int = 200, headers: dict | None = None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}


class _FixtureScraper:
    """Small file-backed input seam that still exercises the real parsers."""

    def __init__(self, fixture_dir: str):
        self.fixture_dir = Path(fixture_dir)

    def get(self, url: str, **_kwargs):
        path = urllib.parse.urlparse(url).path
        filename = "search.html" if path.startswith("/s/") else "detail.html"
        fixture = self.fixture_dir / filename
        try:
            return _FixtureResponse(fixture.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise SeedhubParseError(f"fixture {filename} unavailable") from exc


_BAIDU_SHARE_URL_RE = (
    r"https://pan\.baidu\.(?:com|example)/s/[A-Za-z0-9_-]{6,64}"
    r"(?:\?pwd=[A-Za-z0-9]{4})?"
    r"(?=$|[\s<>\"'])"
)
_QUARK_SHARE_URL_RE = (
    r"https://pan\.quark\.cn/s/[A-Za-z0-9_-]{6,64}(?=$|[\s<>\"'])"
)
_BAIDU_PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{4}$")
_QR_MAX_BYTES = 2 * 1024 * 1024
_QR_MAX_PIXELS = 16_000_000
_QR_MAX_IMAGES = 4
_QR_HINT_RE = re.compile(r"(?:qr|qrcode|qr-code|二维码|扫码)", re.IGNORECASE)


def _normalise_baidu_share(value: str, *, allow_fixture: bool = False) -> tuple[str, str]:
    """Return a canonical Baidu share URL and a separately carried password."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("Baidu share URL is empty")
    raw = html_lib.unescape(value).strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Baidu share URL is malformed") from exc
    allowed_hosts = {"pan.baidu.com"}
    if allow_fixture:
        allowed_hosts.add("pan.baidu.example")
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() not in allowed_hosts
        or port is not None
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Baidu share URL left the official host")
    if not re.fullmatch(r"/s/[A-Za-z0-9_-]{6,64}", parsed.path):
        raise ValueError("Baidu share URL path is invalid")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - {"pwd"} or any(len(values) != 1 for values in query.values()):
        raise ValueError("Baidu share URL query is invalid")
    password = query.get("pwd", [""])[0]
    if password and not _BAIDU_PASSWORD_RE.fullmatch(password):
        raise ValueError("Baidu share URL password is invalid")
    return parsed._replace(query="").geturl(), password


def _direct_baidu_candidates(html: str) -> list[str]:
    """Extract only explicit, allowlisted direct-link shapes from HTML."""

    candidates: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        for match in re.finditer(_BAIDU_SHARE_URL_RE, html_lib.unescape(value)):
            candidate = match.group(0)
            if candidate not in candidates:
                candidates.append(candidate)

    # The current SeedHub template exposes the canonical link on this anchor.
    for tag in re.findall(r"<a\b[^>]*>", html, flags=re.IGNORECASE):
        class_match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
        if class_match and "direct-pan" in class_match.group(2).split():
            href_match = re.search(r"\bhref\s*=\s*(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
            if href_match:
                add(href_match.group(2))

    # Some variants store the same value in a short inline variable.
    for match in re.finditer(
        r"\b(?:var|let|const)\s+panLink\s*=\s*(['\"])(.*?)\1",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        add(match.group(2))

    # Keep the existing redirect shape as a third, explicit source.
    for match in re.finditer(
        rf"window\.location\.href\s*=\s*(['\"])(\s*{_BAIDU_SHARE_URL_RE})\1",
        html,
        flags=re.IGNORECASE,
    ):
        add(match.group(2))

    # Last, accept a canonical URL rendered as plain text in the page.
    add(html)
    return candidates


def _qr_image_sources(html: str, page_url: str) -> list[tuple[str, bytes | str]]:
    """Return data images or same-origin HTTPS image URLs only."""

    candidates: list[tuple[int, str, bytes | str]] = []
    page = urllib.parse.urlsplit(page_url)
    if page.scheme.lower() != "https" or not page.hostname or page.port is not None:
        return []
    for tag in re.findall(r"<(?:img|source)\b[^>]*>", html, flags=re.IGNORECASE):
        src_match = re.search(r"\bsrc\s*=\s*(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
        if not src_match:
            continue
        source = html_lib.unescape(src_match.group(2)).strip()
        if source.lower().startswith("data:"):
            header, separator, encoded = source.partition(",")
            if not separator:
                continue
            metadata = header[5:].split(";", 1)[0].lower()
            if not metadata.startswith("image/") or ";base64" not in header.lower():
                continue
            if len(encoded) > _QR_MAX_BYTES * 2:
                continue
            try:
                import base64

                content = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                continue
            if len(content) <= _QR_MAX_BYTES:
                priority = 0 if _QR_HINT_RE.search(tag) else 1
                candidates.append((priority, metadata, content))
            continue

        absolute = urllib.parse.urljoin(page_url, source)
        parsed = urllib.parse.urlsplit(absolute)
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname is None
            or parsed.hostname.lower() != page.hostname.lower()
            or parsed.port is not None
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            continue
        priority = 0 if _QR_HINT_RE.search(tag) else 1
        candidates.append((priority, "url", parsed.geturl()))
    candidates.sort(key=lambda item: item[0])
    # Prefer explicitly labelled QR images.  A small generic fallback keeps
    # simple QR-only pages working without fetching every page image.
    hinted = [item for item in candidates if item[0] == 0]
    selected = hinted if hinted else candidates[:2]
    return [(mime, source) for _, mime, source in selected[:_QR_MAX_IMAGES]]


def _decode_qr_payload(content: bytes) -> list[str]:
    """Decode QR text locally; dependency errors are explicit parse failures."""

    if len(content) > _QR_MAX_BYTES:
        return []
    try:
        from io import BytesIO

        from PIL import Image, UnidentifiedImageError
        import zxingcpp
    except ImportError as exc:
        raise SeedhubParseError("QR decoder dependencies are unavailable") from exc
    try:
        with Image.open(BytesIO(content)) as image:
            if image.width <= 0 or image.height <= 0 or image.width * image.height > _QR_MAX_PIXELS:
                return []
            image.load()
            decoded = zxingcpp.read_barcodes(image.convert("RGB"))
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
        return []
    values: list[str] = []
    for result in decoded:
        text = getattr(result, "text", "")
        if isinstance(text, str) and text and text not in values:
            values.append(text)
    return values


def _qr_baidu_candidates(
    scraper,
    html: str,
    page_url: str,
    *,
    allow_fixture: bool = False,
) -> list[tuple[str, str]]:
    """Decode same-origin QR images and retain only canonical Baidu shares."""

    candidates: list[tuple[str, str]] = []
    for mime, source in _qr_image_sources(html, page_url):
        if mime == "url":
            try:
                response = scraper.get(
                    source,
                    allow_redirects=False,
                    timeout=10,
                )
            except Exception:
                continue
            if response.status_code != 200:
                continue
            content_type = str(response.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                continue
            content = getattr(response, "content", b"")
            if not isinstance(content, bytes) or len(content) > _QR_MAX_BYTES:
                continue
        else:
            content = source
        for decoded in _decode_qr_payload(content):
            try:
                candidate = _normalise_baidu_share(decoded, allow_fixture=allow_fixture)
            except ValueError:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _validated_redirect(location: str, kind: str) -> str:
    if kind == "baidu":
        try:
            _normalise_baidu_share(location)
        except ValueError as exc:
            raise SeedhubNetworkError("intermediate redirect left the expected share host") from exc
        return location
    try:
        parsed = urllib.parse.urlsplit(location)
        port = parsed.port
    except ValueError as exc:
        raise SeedhubNetworkError("intermediate redirect URL was malformed") from exc
    expected_host = "pan.quark.cn"
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != expected_host
        or port is not None
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or not re.fullmatch(r"/s/[A-Za-z0-9_-]{6,64}", parsed.path)
    ):
        raise SeedhubNetworkError("intermediate redirect left the expected share host")
    return location


def _fetch_intermediate(scraper, url: str, kind: str):
    try:
        response = scraper.get(url, allow_redirects=False, timeout=10)
    except SeedhubParseError:
        raise
    except Exception as exc:
        raise SeedhubNetworkError("intermediate request failed") from exc
    if response.status_code == 200:
        return response, None
    if 300 <= response.status_code < 400:
        location = response.headers.get("location") or response.headers.get("Location")
        if not location:
            raise SeedhubNetworkError("intermediate redirect was missing a location")
        return response, _validated_redirect(urllib.parse.urljoin(url, location), kind)
    raise SeedhubNetworkError("intermediate request returned a non-success status")


def create_scraper(fixture_dir: str | None = None):
    if fixture_dir is not None:
        return _FixtureScraper(fixture_dir)
    return cloudscraper.create_scraper()


def search(keyword: str, limit: int = 20, fixture_dir: str | None = None) -> list[dict]:
    """搜索影视资源，返回结果列表"""
    scraper = create_scraper(fixture_dir)
    base = FIXTURE_BASE if fixture_dir is not None else SEEDHUB_BASE
    url = f"{base}/s/{urllib.parse.quote(keyword)}/"

    try:
        r = scraper.get(url, timeout=30)
        if r.status_code != 200:
            raise SeedhubNetworkError("SeedHub search returned a non-success status")
    except SeedhubParseError:
        raise
    except Exception as exc:
        raise SeedhubNetworkError("SeedHub search request failed") from exc

    html = r.text

    # Parse movie cards
    movies = re.findall(
        r'title="([^"]+)"[^>]*class="image"[^>]*href="(/movies/\d+)/?"', html
    )
    infos = re.findall(
        r"<li>(\d{4}\s*/\s*(?:电影|剧集|动漫)[^<]*)</li>", html
    )
    ratings = re.findall(
        r'豆瓣评分:\s*<a[^>]*>([^<]+)</a>', html
    )

    if fixture_dir is not None and not movies:
        raise SeedhubParseError("fixture search page has no movie cards")

    results = []
    for i, (title, path) in enumerate(movies[:limit]):
        m = re.search(r"/movies/(\d+)/?", path)
        movie_id = m.group(1) if m else "unknown"
        results.append({
            "title": title,
            "info": infos[i].strip() if i < len(infos) else "",
            "rating": ratings[i] if i < len(ratings) else "?",
            "id": movie_id,
            "url": f"{base}/movies/{movie_id}/",
        })

    return results


def get_links(
    movie_id: str,
    quark_limit: int = 10,
    fixture_dir: str | None = None,
) -> dict:
    """获取电影的下载链接"""
    movie_id = movie_id.strip("/").split("/")[-1]
    base = FIXTURE_BASE if fixture_dir is not None else SEEDHUB_BASE
    url = f"{base}/movies/{movie_id}/"

    scraper = create_scraper(fixture_dir)

    try:
        r = scraper.get(url, timeout=30)
        if r.status_code != 200:
            raise SeedhubNetworkError("SeedHub detail returned a non-success status")
    except SeedhubParseError:
        raise
    except Exception as exc:
        raise SeedhubNetworkError("SeedHub detail request failed") from exc

    html = r.text

    # Extract title
    title_match = re.search(r"<h1[^>]*>.*?#</a>\s*([^<]+)", html)
    title = title_match.group(1).strip() if title_match else "未知标题"

    # Extract all link_start URLs
    all_hrefs = re.findall(
        r'href="(/link_start/\?redirect_to=pan_id_\d+&movie_title=[^"]+)"', html
    )
    if fixture_dir is not None and not all_hrefs:
        raise SeedhubParseError("fixture detail page has no link_start entries")

    # Deduplicate
    seen = set()
    unique_links = []
    for link in all_hrefs:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    # Classify links by type
    classified = {
        "title": title,
        "quark": [],
        "baidu": [],
        "aliyun": [],
        "uc": [],
        "xunlei": [],
        "magnet": re.findall(r'(magnet:\?xt=[^\s<"]+)', html),
        "thunder": re.findall(r'(thunder://[^\s<"]+)', html),
        "ed2k": re.findall(r'(ed2k://[^\s<"]+)', html),
    }

    for link in unique_links:
        esc_link = re.escape(link)
        pattern = rf'(.{{0,300}}href="{esc_link}".{{0,100}})'
        match = re.search(pattern, html)
        if not match:
            continue

        context = match.group(1)
        dl_match = re.search(r'data-link="([^"]+)"', context)
        link_type = dl_match.group(1) if dl_match else "unknown"
        title_match = re.search(r'title="([^"]+)"', context)
        desc = title_match.group(1) if title_match else ""

        if "quark" in link_type.lower():
            classified["quark"].append({"path": link, "desc": desc})
        elif "baidu" in link_type.lower():
            classified["baidu"].append({"path": link, "desc": desc})
        elif "alipan" in link_type.lower() or "aliyun" in link_type.lower():
            classified["aliyun"].append({"path": link, "desc": desc})
        elif "uc" in link_type.lower():
            classified["uc"].append({"path": link, "desc": desc})
        elif "xunlei" in link_type.lower():
            classified["xunlei"].append({"path": link, "desc": desc})

    # Resolve quark links (follow redirects to get actual URLs)
    resolved_quark = []
    quark_failures = 0
    attempted_quark = classified["quark"][:quark_limit]
    for item in attempted_quark:
        try:
            redirect_url = f"{base}{item['path']}"
            r2, direct_url = _fetch_intermediate(scraper, redirect_url, "quark")
            actual_links = [direct_url] if direct_url else re.findall(
                rf'({_QUARK_SHARE_URL_RE})', r2.text
            )
            if actual_links:
                item["url"] = _validated_redirect(actual_links[0], "quark")
                resolved_quark.append(item)
        except SeedhubNetworkError:
            quark_failures += 1

    if attempted_quark and not resolved_quark and quark_failures == len(attempted_quark):
        raise SeedhubNetworkError("all Quark intermediate requests failed")

    classified["quark_resolved"] = resolved_quark

    # [vendor-patch] Resolve baidu links: follow link_start 中间页 + 提取码正则
    resolved_baidu = []
    baidu_failures = 0
    attempted_baidu = classified["baidu"][:quark_limit]
    for item in attempted_baidu:
        try:
            redirect_url = f"{base}{item['path']}"
            r2, direct_url = _fetch_intermediate(scraper, redirect_url, "baidu")
            # Direct-first: redirect, .direct-pan, panLink, window.location,
            # then a canonical URL rendered as plain text.
            raw_candidates = [direct_url] if direct_url else []
            raw_candidates.extend(_direct_baidu_candidates(r2.text))
            parsed_candidates: list[tuple[str, str]] = []
            for raw_candidate in raw_candidates:
                if not raw_candidate:
                    continue
                try:
                    parsed_candidate = _normalise_baidu_share(
                        raw_candidate,
                        allow_fixture=fixture_dir is not None,
                    )
                except ValueError:
                    continue
                if parsed_candidate not in parsed_candidates:
                    parsed_candidates.append(parsed_candidate)
            if not parsed_candidates:
                parsed_candidates.extend(
                    _qr_baidu_candidates(
                        scraper,
                        r2.text,
                        redirect_url,
                        allow_fixture=fixture_dir is not None,
                    )
                )
            if not parsed_candidates:
                continue
            baidu_url, url_password = parsed_candidates[0]
            # 提取码：从 desc 文本正则拿 4 位字母数字
            pwd_match = re.search(
                r'(?:提取码|密码|pwd|code)[：:\s]*([a-zA-Z0-9]{4})',
                item["desc"],
            )
            pwd = url_password or (pwd_match.group(1) if pwd_match else "")
            item["url"] = baidu_url
            item["pwd"] = pwd
            resolved_baidu.append(item)
        except SeedhubNetworkError:
            baidu_failures += 1

    if attempted_baidu and not resolved_baidu and baidu_failures == len(attempted_baidu):
        raise SeedhubNetworkError("all Baidu intermediate requests failed")

    classified["baidu_resolved"] = resolved_baidu
    return classified


def clean_desc(desc: str, max_len: int = 60) -> str:
    """清理资源描述"""
    desc = re.sub(r"今天|昨天|提取码[^\s]*", "", desc).strip()
    desc = desc.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return desc[:max_len] if len(desc) > max_len else desc


def _emit_json_error(code: str, message: str) -> None:
    """Keep parser failures machine-readable for the wrapper CLI."""
    print(json.dumps({"__error__": {"code": code, "message": message}}, ensure_ascii=False))


def cmd_search(args):
    """搜索命令"""
    keyword = args.keyword
    try:
        results = search(keyword, limit=args.limit, fixture_dir=args.fixture_dir)
    except SeedhubNetworkError:
        if getattr(args, "json", False):
            _emit_json_error("NETWORK", "SeedHub search request failed")
            raise SystemExit(1)
        print("❌ 搜索请求失败", file=sys.stderr)
        sys.exit(1)
    except SeedhubParseError as exc:
        if getattr(args, "json", False):
            _emit_json_error("PARSE", str(exc))
            raise SystemExit(1)
        print("❌ 搜索结果解析失败", file=sys.stderr)
        sys.exit(1)

    # [vendor-patch] JSON 输出分支
    if getattr(args, "json", False):
        # 资源类型过滤（基于 info 字段：含 "电影"/"剧集"/"动漫"）
        if getattr(args, "resource_type", "all") != "all":
            type_map = {"movie": "电影", "tv": "剧集", "anime": "动漫"}
            target = type_map[args.resource_type]
            results = [r for r in results if target in r.get("info", "")]
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    print(f"🔍 搜索: {keyword}")

    if not results:
        print("❌ 未找到相关结果")
        return

    # [vendor-patch] 应用资源类型过滤
    if getattr(args, "resource_type", "all") != "all":
        type_map = {"movie": "电影", "tv": "剧集", "anime": "动漫"}
        target = type_map[args.resource_type]
        results = [r for r in results if target in r.get("info", "")]
        if not results:
            print(f"❌ 类型 {args.resource_type} 无结果")
            return

    print(f"\n找到 {len(results)} 个结果:\n")

    for i, item in enumerate(results, 1):
        print(f"{i}. {item['title']}")
        print(f"   📅 {item['info'] or 'N/A'} | ⭐ 豆瓣 {item['rating']}")
        print(f"   📌 ID: {item['id']}")
        print()


def cmd_links(args):
    """获取下载链接"""
    movie_id = args.movie_id
    try:
        data = get_links(
            movie_id,
            quark_limit=args.limit,
            fixture_dir=args.fixture_dir,
        )
    except SeedhubNetworkError:
        if getattr(args, "json", False):
            _emit_json_error("NETWORK", "SeedHub detail request failed")
            raise SystemExit(1)
        print("❌ 详情页请求失败", file=sys.stderr)
        sys.exit(1)
    except SeedhubParseError as exc:
        if getattr(args, "json", False):
            _emit_json_error("PARSE", str(exc))
            raise SystemExit(1)
        print("❌ 详情页解析失败", file=sys.stderr)
        sys.exit(1)

    if not data:
        print("❌ 获取失败", file=sys.stderr)
        sys.exit(1)

    # [vendor-patch] JSON 输出分支
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print(f"🎬 获取下载链接...")
    print(f"📽️ {data['title']}")
    print("━" * 50)

    found = False

    if data.get("quark_resolved"):
        found = True
        total = len(data["quark"])
        resolved = data["quark_resolved"]
        print(f"\n🔗 夸克网盘 ({total}个, 已解析{len(resolved)}个):")
        for item in resolved:
            print(f"   • {clean_desc(item['desc'])}")
            print(f"     {item['url']}")

    # [vendor-patch] 百度网盘解析结果展示
    if data.get("baidu_resolved"):
        found = True
        total = len(data["baidu"])
        resolved = data["baidu_resolved"]
        print(f"\n📦 百度网盘 ({total}个, 已解析{len(resolved)}个):")
        for item in resolved:
            pwd_str = f" 提取码:{item['pwd']}" if item.get("pwd") else " 无提取码"
            print(f"   • {clean_desc(item['desc'], 50)}{pwd_str}")
            print(f"     {item['url']}")

    if data.get("baidu") and not data.get("baidu_resolved"):
        found = True
        print(f"\n📦 百度网盘 ({len(data['baidu'])}个, 解析失败):")
        for item in data["baidu"][:5]:
            print(f"   • {clean_desc(item['desc'], 50)}")

    if data.get("aliyun"):
        found = True
        print(f"\n📦 阿里云盘 ({len(data['aliyun'])}个):")
        for item in data["aliyun"][:5]:
            print(f"   • {clean_desc(item['desc'], 50)}")

    if data.get("uc"):
        found = True
        print(f"\n📦 UC网盘 ({len(data['uc'])}个):")
        for item in data["uc"][:3]:
            print(f"   • {clean_desc(item['desc'], 50)}")

    if data.get("magnet"):
        found = True
        print(f"\n🧲 磁力链接 ({len(data['magnet'])}个):")
        for link in data["magnet"][:5]:
            print(f"   {link[:80]}...")

    if data.get("thunder"):
        found = True
        print(f"\n⚡ 迅雷链接 ({len(data['thunder'])}个):")
        for link in data["thunder"][:5]:
            print(f"   {link[:80]}...")

    if not found:
        print("❌ 未找到下载链接")
    else:
        print(f"\n💡 夸克链接已自动解析为可直接访问的 URL")


def main():
    parser = argparse.ArgumentParser(
        description="SeedHub CLI - 影视资源搜索 & 下载链接提取",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s search 怪奇物语
  %(prog)s search "至尊马蒂" --limit 5
  %(prog)s links 119254
  %(prog)s links 129054 --limit 20
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # search
    sp_search = subparsers.add_parser("search", aliases=["s"], help="搜索影视资源")
    sp_search.add_argument("keyword", help="搜索关键词")
    sp_search.add_argument("--limit", "-n", type=int, default=20, help="最大结果数 (默认: 20)")
    sp_search.add_argument(
        "--resource-type",
        choices=["all", "movie", "tv", "anime"],
        default="all",
        help="资源类型过滤（默认: all）",
    )
    # [vendor-patch] --json 输出
    sp_search.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出（机器可读）",
    )
    sp_search.add_argument(
        "--fixture-dir",
        default=None,
        help=argparse.SUPPRESS,
    )
    sp_search.set_defaults(func=cmd_search)

    # links
    sp_links = subparsers.add_parser("links", aliases=["l"], help="获取下载链接")
    sp_links.add_argument("movie_id", help="电影 ID (从搜索结果获取)")
    sp_links.add_argument("--limit", "-n", type=int, default=10, help="解析的链接数 (默认: 10)")
    # [vendor-patch] --json 输出
    sp_links.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出（机器可读）",
    )
    sp_links.add_argument(
        "--fixture-dir",
        default=None,
        help=argparse.SUPPRESS,
    )
    sp_links.set_defaults(func=cmd_links)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
