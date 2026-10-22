'''验证前端资源移动后的页面引用和两个静态挂载入口。'''

import asyncio
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import urljoin, urlparse

from api.app import app


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class PageResources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attributes) -> None:
        attrs = dict(attributes)
        if tag == "script" and attrs.get("src"):
            self.urls.append(attrs["src"])
        if tag == "link" and attrs.get("href"):
            self.urls.append(attrs["href"])


class FrontendAssetTests(unittest.TestCase):
    def test_page_resources_load_through_web_and_login_mounts(self) -> None:
        checked = set()
        for page in FRONTEND.glob("*.html"):
            resources = PageResources()
            resources.feed(page.read_text(encoding="utf-8"))
            for mount in ("web", "login"):
                paths = [f"/{mount}/{page.name}"]
                paths.extend(urljoin(paths[0], url) for url in resources.urls)
                for path in paths:
                    if urlparse(path).scheme or path in checked:
                        continue
                    checked.add(path)
                    with self.subTest(path=path):
                        prefix, _, resource = path.lstrip("/").partition("/")
                        mount = next(route for route in app.routes if route.path == f"/{prefix}")
                        response = asyncio.run(mount.app.get_response(resource, {"type": "http", "method": "GET", "headers": []}))
                        self.assertEqual(response.status_code, 200)

    def test_stylesheet_asset_urls_resolve_after_move(self) -> None:
        for stylesheet in (FRONTEND / "styles").glob("*.css"):
            urls = re.findall(r"url\(['\"]?([^)'\"]+)['\"]?\)", stylesheet.read_text())
            for url in urls:
                if url.startswith(("data:", "http:", "https:")):
                    continue
                target = ROOT / url.lstrip("/") if url.startswith("/") else stylesheet.parent / url
                with self.subTest(stylesheet=stylesheet.name, url=url):
                    self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
