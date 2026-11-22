from urllib.parse import urlsplit

from playwright.sync_api import Error, TimeoutError, sync_playwright

from download_retry import DownloadRateLimited, DownloadRetry, retry_after_seconds


def parse_response(response):
    url = urlsplit(response.url)
    return url.hostname == "dy.kukutool.com" and (
        url.path == "/api/parse"
        or (response.status >= 400 and (
            url.path == "/api/parse-entitlement-status" or url.path.startswith("/api/auth-")
        ))
    )


def check_response(response):
    if response is None:
        return
    if response.status == 429:
        raise DownloadRateLimited(retry_after_seconds(response.headers.get("retry-after")))
    if response.status in {500, 502, 503, 504}:
        raise DownloadRetry(f"KuKuTool 暂时不可用（HTTP {response.status}）。",
                            retry_after_seconds(response.headers.get("retry-after")))
    if response.status >= 400:
        raise RuntimeError(f"KuKuTool 返回 HTTP {response.status}，可在 KuKuTool 手动下载后上传原片。")


def download_from_kuku(url, output):
    stage = "启动浏览器"
    rate_limit = None

    def capture_limit(response):
        nonlocal rate_limit
        if response.status != 429:
            return
        host = urlsplit(response.url).hostname
        if parse_response(response) or (stage == "下载视频" and host in {
                "dy.kukutool.com", "finder.video.qq.com", "findermp.video.qq.com"}):
            rate_limit = DownloadRateLimited(retry_after_seconds(response.headers.get("retry-after")))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(accept_downloads=True)
            page.on("response", capture_limit)
            stage = "加载网页"
            check_response(page.goto("https://dy.kukutool.com/en", timeout=25000, wait_until="domcontentloaded"))
            try:
                page.wait_for_load_state("load", timeout=9000)
            except TimeoutError:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=7000)
            except TimeoutError:
                pass
            stage = "解析分享链接"
            page.get_by_placeholder("Paste text with link", exact=True).fill(url, timeout=10000)
            with page.expect_response(parse_response, timeout=45000) as result:
                page.get_by_role("button", name="Parse Video", exact=True).click(timeout=10000)
            check_response(result.value)
            button = page.get_by_role("button", name="DownloadVideo", exact=True).first
            button.wait_for(timeout=30000)
            stage = "下载视频"
            with page.expect_download(timeout=45000) as event:
                button.click()
            item = event.value
            item.save_as(output)
            return item.suggested_filename
    except TimeoutError:
        if rate_limit is not None:
            raise rate_limit from None
        raise DownloadRetry(f"KuKuTool 在「{stage}」阶段响应超时。") from None
    except Error:
        raise RuntimeError(f"KuKuTool 在「{stage}」阶段未完成。若网站要求验证，可手动下载后导入。") from None
