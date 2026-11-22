import json
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

API = "https://api.heygen.com"
VOICES = ("x9yUsHEv2yOPCBKlOk10", "80b17a1be1594e578b92c0ddf4a37fc8")


def api(key, path, data=None):
    headers = {"X-Api-Key": key, "Content-Type": "application/json"}
    request = Request(API + path, json.dumps(data).encode() if data is not None else None, headers)
    try:
        with urlopen(request, timeout=90) as response:
            body = json.load(response)
    except HTTPError as error:
        try:
            message = json.load(error).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        raise RuntimeError(f"HeyGen HTTP {error.code} {message}".strip()) from None
    except URLError:
        raise RuntimeError("连接 HeyGen 失败，请检查网络后重试。") from None
    return body["data"]


def download(url, path):
    if urlsplit(url).scheme != "https":
        raise RuntimeError("HeyGen 返回了不可用的媒体地址。")
    result = subprocess.run(
        ["curl", "--proto", "=https", "--max-redirs", "5", "-fsL", "--max-time", "180", "-o", str(path), url],
        capture_output=True, timeout=190,
    )
    if result.returncode:
        raise RuntimeError("下载 HeyGen 媒体失败。")


def speech(key, text, role, destination):
    body = api(key, "/v3/models/audio/tts", {"language": "ko", "voice_id": VOICES[role], "text": text})
    download(body["audio_url"], destination)


def upload(key, path, media_type):
    if path.stat().st_size > 50_000_000:
        raise RuntimeError("HeyGen 素材超过 50 MB，请改用较短的片段。")
    # curl reads the header from stdin so the API key does not appear in the process arguments.
    proc = subprocess.run(
        ["curl", "-sS", "--max-time", "180", "-H", "@-", "-F", f"file=@{path};type={media_type}", API + "/v3/assets"],
        input=f"X-Api-Key: {key}\n", text=True, capture_output=True, timeout=190,
    )
    if proc.returncode:
        raise RuntimeError("HeyGen 素材上传失败。")
    result = json.loads(proc.stdout)
    if result.get("error"):
        raise RuntimeError(result["error"].get("message", "HeyGen 素材上传失败。"))
    return {"type": "asset_id", "asset_id": result["data"]["asset_id"]}


def lipsync(key, picture, narration, output, report, job_path):
    if job_path.exists():
        job = job_path.read_text().strip()
    else:
        response = api(key, "/v3/lipsyncs", {
            "video": upload(key, picture, "video/mp4"),
            "audio": upload(key, narration, "audio/wav"),
            "mode": "precision", "enable_watermark": False, "enable_dynamic_duration": False,
            "enable_speech_enhancement": False, "disable_music_track": True,
            "keep_the_same_format": True, "fps_mode": "passthrough",
        })
        job = response["lipsync_id"]
        partial = job_path.with_suffix(".tmp")
        partial.write_text(job)
        partial.replace(job_path)
    report(76, "等待 HeyGen 口型")
    deadline = time.monotonic() + 25 * 60
    while time.monotonic() < deadline:
        response = api(key, "/v3/lipsyncs/" + job)
        if response["status"] == "completed":
            download(response["video_url"], output)
            return
        if response["status"] in {"failed", "not_found"}:
            job_path.unlink(missing_ok=True)
            raise RuntimeError(response.get("failure_message") or "HeyGen 没能生成口型。")
        time.sleep(10)
    raise RuntimeError("HeyGen 仍在处理，可以重试继续等待原任务。")
