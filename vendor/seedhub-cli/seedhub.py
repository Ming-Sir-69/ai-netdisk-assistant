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
    r"(?=$|[\s<>\"'])"
)
_QUARK_SHARE_URL_RE = (
    r"https://pan\.quark\.cn/s/[A-Za-z0-9_-]{6,64}(?=$|[\s<>\"'])"
)


def _validated_redirect(location: str, kind: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(location)
        port = parsed.port
    except ValueError as exc:
        raise SeedhubNetworkError("intermediate redirect URL was malformed") from exc
    expected_host = "pan.baidu.com" if kind == "baidu" else "pan.quark.cn"
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
            # 真实 pan.baidu.com 分享链接（window.location.href 赋值或重定向）
            url_match = None
            if direct_url is None:
                url_match = re.search(
                    rf'window\.location\.href\s*=\s*["\']({_BAIDU_SHARE_URL_RE})',
                    r2.text,
                )
                if not url_match:
                    # 兜底：HTML 里直接出现的 pan.baidu.com 链接
                    url_match = re.search(
                        rf'({_BAIDU_SHARE_URL_RE})',
                        r2.text,
                    )
            baidu_url = direct_url or (url_match.group(1) if url_match else "")
            if not baidu_url:
                continue
            if fixture_dir is None:
                baidu_url = _validated_redirect(baidu_url, "baidu")
            # 提取码：从 desc 文本正则拿 4 位字母数字
            pwd_match = re.search(
                r'(?:提取码|密码|pwd|code)[：:\s]*([a-zA-Z0-9]{4})',
                item["desc"],
            )
            pwd = pwd_match.group(1) if pwd_match else ""
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
