import math
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit


RETRY_DELAYS = (60, 300, 900, 3600, 14400)


class DownloadRetry(RuntimeError):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class DownloadRateLimited(DownloadRetry):
    def __init__(self, retry_after=None):
        super().__init__("KuKuTool 限流（429）。", retry_after)


def retry_after_seconds(header, now=None):
    if not header:
        return None
    value = header.strip()
    if len(value) <= 10 and value.isascii() and value.isdecimal():
        return int(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0, math.ceil(date.timestamp() - (time.time() if now is None else now)))
    except (ValueError, TypeError, OverflowError):
        return None


def wechat_share_url(value):
    if not value:
        return None
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.netloc.lower() != "weixin.qq.com":
            return None
    except ValueError:
        return None
    if re.fullmatch(r"/sph/[A-Za-z0-9_-]{1,128}/?", url.path):
        return "https://weixin.qq.com" + url.path.rstrip("/")
    return None
