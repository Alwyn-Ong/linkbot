import logging

import requests

logger = logging.getLogger(__name__)

JINA_BASE = "https://r.jina.ai/"

_INSTAGRAM_HOSTS = ("instagram.com", "www.instagram.com")
_TIKTOK_HOSTS = ("tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com")


def _fetch_playwright(url: str) -> str:
    import asyncio
    import concurrent.futures

    async def _run():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            text = await page.inner_text("body")
            await browser.close()
            return text

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run()).result()


class _QuietLogger:
    """Keeps yt-dlp's own output out of the log; extraction failures are handled below."""

    def debug(self, msg): logger.debug("yt-dlp: %s", msg)
    def info(self, msg): logger.debug("yt-dlp: %s", msg)
    def warning(self, msg): logger.debug("yt-dlp: %s", msg)
    def error(self, msg): logger.debug("yt-dlp: %s", msg)


def _fetch_tiktok(url: str) -> str:
    import yt_dlp

    # yt-dlp only supports TikTok /video/ URLs, not /photo/ slideshow posts.
    # The same item is often reachable under /video/, so try that first.
    yt_url = url.replace("/photo/", "/video/")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "logger": _QuietLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        # Photo posts, unsupported items, and TikTok-side extractor breakage all fall
        # back to scraping the rendered page for the caption text.
        logger.info("yt-dlp could not extract %s (%s), falling back to Playwright", yt_url, e)
        return _fetch_playwright(url)

    fields = (
        ("Title", info.get("title")),
        ("Description", info.get("description")),
        ("Author", info.get("uploader") or info.get("creator") or info.get("channel")),
        ("Upload date", info.get("upload_date")),
    )
    text = "\n".join(f"{label}: {value}" for label, value in fields if value).strip()
    if not text:
        return _fetch_playwright(url)
    return text


def fetch(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host in _INSTAGRAM_HOSTS:
        return _fetch_playwright(url)
    if host in _TIKTOK_HOSTS:
        return _fetch_tiktok(url)
    response = requests.get(JINA_BASE + url, timeout=30)
    response.raise_for_status()
    return response.text
