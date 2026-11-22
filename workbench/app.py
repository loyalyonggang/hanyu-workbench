import ipaddress
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import uuid4

from flask import Flask, Response, abort, jsonify, request, send_file
from werkzeug.serving import make_server

import heygen
import pipeline
from download_retry import DownloadRateLimited, DownloadRetry, RETRY_DELAYS, wechat_share_url

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("WORKBENCH_DATA_DIR", ROOT / "data")).resolve()
PORT = int(os.getenv("WORKBENCH_PORT", "8790"))
PUBLIC_HOST = os.getenv("WORKBENCH_PUBLIC_HOST", "")
EXAMPLE_SOURCE = ROOT.parent / "原片.mp4"
EXAMPLE_VIDEO = ROOT.parent / "二虎_韩语口型修订版.mp4"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
TOKEN = secrets.token_urlsafe(24)
WAKE = threading.Event()
ARCHIVES = {}
ARCHIVE_LOCK = threading.Lock()
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_050_000_000
app.config["MAX_FORM_PARTS"] = 80


@contextmanager
def db():
    connection = sqlite3.connect(DATA / "jobs.sqlite3", timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    (DATA / "jobs").mkdir(exist_ok=True)
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT, options TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued', stage TEXT NOT NULL DEFAULT '排队中',
            percent INTEGER NOT NULL DEFAULT 0, duration REAL, message TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        columns = {row["name"] for row in con.execute("PRAGMA table_info(jobs)")}
        if "retry_at" not in columns:
            con.execute("ALTER TABLE jobs ADD COLUMN retry_at INTEGER NOT NULL DEFAULT 0")
        if "download_attempts" not in columns:
            con.execute("ALTER TABLE jobs ADD COLUMN download_attempts INTEGER NOT NULL DEFAULT 0")
        con.execute("CREATE TABLE IF NOT EXISTS download_cooldown (provider TEXT PRIMARY KEY, resume_at INTEGER NOT NULL)")
        con.execute("""UPDATE jobs SET state='failed', stage='处理已中断',
                     message='工作台已重启，点重试可继续处理。' WHERE state='running'""")


def read_key():
    path = DATA / ".heygen-key"
    return os.getenv("HEYGEN_API_KEY") or (path.read_text().strip() if path.exists() else "")


def change(job_id, **fields):
    statement = ", ".join(f"{name}=?" for name in fields)
    with db() as con:
        con.execute(f"UPDATE jobs SET {statement} WHERE id=?", (*fields.values(), job_id))


def reuse_source(job, folder):
    source = folder / "input.media"
    if source.is_file() or not (url := wechat_share_url(job["url"])):
        return
    with db() as con:
        rows = con.execute("SELECT id,url,title FROM jobs WHERE url IS NOT NULL AND id<>? ORDER BY rowid DESC",
                           (job["id"],)).fetchall()
    for row in rows:
        if wechat_share_url(row["url"]) != url:
            continue
        previous = DATA / "jobs" / row["id"] / "input.media"
        if not previous.is_file():
            continue
        try:
            os.link(previous, source)
        except FileNotFoundError:
            continue
        change(job["id"], title=row["title"])
        return


def defer_download(con, job_id, resume_at, message="KuKuTool 限流（429）。"):
    con.execute("""UPDATE jobs SET state='queued',stage='等待下载恢复',percent=8,
                   message=?,retry_at=? WHERE id=?""",
                (message + "工作台会自动重试。", resume_at, job_id))


def reschedule_download(job, error):
    attempts = job["download_attempts"] + 1
    delay = error.retry_after
    if delay is None:
        delay = RETRY_DELAYS[min(attempts, len(RETRY_DELAYS)) - 1]
    target = int(time.time()) + max(30, delay)
    with db() as con:
        if isinstance(error, DownloadRateLimited):
            target = con.execute("""INSERT INTO download_cooldown VALUES ('kuku',?)
                ON CONFLICT(provider) DO UPDATE SET resume_at=MAX(resume_at,excluded.resume_at)
                RETURNING resume_at""", (target,)).fetchone()[0]
        con.execute("UPDATE jobs SET download_attempts=? WHERE id=?", (attempts, job["id"]))
        if attempts <= len(RETRY_DELAYS):
            defer_download(con, job["id"], target, str(error))
        else:
            con.execute("""UPDATE jobs SET state='failed',stage='下载重试结束',retry_at=?,message=?
                           WHERE id=?""", (target, str(error) + "自动重试次数已用完，可重新排队。", job["id"]))


def process_next():
    now = int(time.time())
    with db() as con:
        item = con.execute("""UPDATE jobs SET state='running',stage='初始化',percent=2,message='',retry_at=0
            WHERE id=(SELECT id FROM jobs WHERE state='queued' AND retry_at<=? ORDER BY rowid LIMIT 1)
            RETURNING *""", (now,)).fetchone()
    if not item:
        return False
    job = dict(item)
    job["options"] = json.loads(job["options"])
    folder = DATA / "jobs" / job["id"]
    try:
        reuse_source(job, folder)
        if job["url"] and not (folder / "input.media").is_file():
            with db() as con:
                cooldown = con.execute("SELECT resume_at FROM download_cooldown WHERE provider='kuku'").fetchone()
                if cooldown and cooldown["resume_at"] > now:
                    defer_download(con, job["id"], cooldown["resume_at"])
                    return True
        duration, message = pipeline.process(
            folder, job, read_key(),
            lambda progress, stage: change(job["id"], percent=progress, stage=stage),
            lambda title: change(job["id"], title=title[:200]),
        )
        stage = "原片已下载" if job["options"].get("source_only") else "已导出"
        change(job["id"], state="done", stage=stage, percent=100, duration=duration, message=message)
    except DownloadRetry as error:
        reschedule_download(job, error)
    except Exception as error:
        change(job["id"], state="failed", stage="处理失败", message=str(error)[:500] or type(error).__name__)
    return True


def worker():
    while True:
        if not process_next():
            WAKE.wait(2)
            WAKE.clear()


@app.before_request
def local_only():
    allowed_hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    if PUBLIC_HOST:
        allowed_hosts.add(PUBLIC_HOST)
    if request.host not in allowed_hosts:
        abort(403)
    if request.method in {"POST", "PUT", "DELETE"} and request.headers.get("X-Workbench") != TOKEN:
        abort(403)


@app.after_request
def no_external_access(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def home():
    return Response((ROOT / "static/index.html").read_text().replace("__TOKEN__", TOKEN), mimetype="text/html",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/settings")
def settings():
    model_ready = False
    try:
        if pipeline.LLAMA:
            with urlopen(pipeline.LLAMA.rstrip("/") + "/health", timeout=2) as response:
                model_ready = json.load(response).get("status") == "ok"
        else:
            with urlopen(pipeline.OLLAMA + "/api/tags", timeout=2) as response:
                model_ready = any(model["name"] == pipeline.MODEL for model in json.load(response)["models"])
    except (OSError, ValueError):
        pass
    return jsonify(heygen=bool(read_key()), env_key=bool(os.getenv("HEYGEN_API_KEY")),
                   whisper=pipeline.WHISPER.is_file() and bool(shutil.which("whisper-cli")),
                   ollama=model_ready, model=pipeline.MODEL, example=EXAMPLE_VIDEO.is_file(),
                   example_source=EXAMPLE_SOURCE.is_file(),
                   kuku=pipeline.KUKU_MODE == "playwright" or bool(shutil.which("ego-browser")),
                   output=str(DATA / "jobs") if not PUBLIC_HOST else None, local_voice=pipeline.LOCAL_VOICE,
                   server=bool(PUBLIC_HOST))


@app.post("/api/settings")
def save_settings():
    key = (request.get_json(silent=True) or {}).get("key")
    if not isinstance(key, str) or len(key) > 320 or any(ch.isspace() for ch in key.strip()):
        return jsonify(error="请输入有效的 HeyGen API Key。"), 400
    key = key.strip()
    if os.getenv("HEYGEN_API_KEY"):
        return jsonify(error="API Key 由启动环境提供。"), 409
    path = DATA / ".heygen-key"
    if not key:
        path.unlink(missing_ok=True)
        return jsonify(heygen=False)
    try:
        heygen.api(key, "/v3/users/me")
    except (RuntimeError, KeyError) as error:
        return jsonify(error=f"HeyGen 连接失败。{error}"), 400
    fd, temp = tempfile.mkstemp(dir=DATA)
    with os.fdopen(fd,"w") as handle:
        handle.write(key)
    os.replace(temp,path)
    return jsonify(heygen=True)


@app.get("/api/jobs")
def list_jobs():
    with db() as con:
        rows = con.execute("""SELECT id,title,state,stage,percent,duration,message,created,retry_at,url,options
                               FROM jobs ORDER BY rowid DESC""").fetchall()
    results = []
    for row in rows:
        job = dict(row)
        job["source_ready"] = bool(job.pop("url")) and (DATA / "jobs" / job["id"] / "input.media").is_file()
        job["source_only"] = bool(json.loads(job.pop("options")).get("source_only"))
        results.append(job)
    return jsonify(results)


def valid_url(value):
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or "." not in url.hostname or len(value)>1800 or url.username or url.password:
        raise ValueError("每行请输入一个完整的 HTTPS 视频分享链接。")
    try:
        ipaddress.ip_address(url.hostname)
    except ValueError:
        return
    raise ValueError("请输入平台分享页链接。")


@app.post("/api/jobs")
def create_jobs():
    try:
        options = json.loads(request.form.get("options","{}"))
        source_only = request.form.get("source_only") == "1"
        provider=options.get("provider", "local" if pipeline.LOCAL_VOICE else "heygen")
        mode=options.get("caption_mode","yellow")
        y=int(options.get("caption_y",83))
        note=options.get("note","")
        lipsync=options.get("lipsync",False) is True
        if provider not in {"local","heygen"} or mode not in {"yellow","cover","keep"} or not 45<=y<=92:
            raise ValueError("字幕或配音设置无效。")
        if not isinstance(note,str) or len(note)>500:
            raise ValueError("翻译备注最多 500 字。")
        if not source_only and provider == "local" and not pipeline.LOCAL_VOICE:
            raise ValueError("服务器的离线配音暂不可用，请选择 HeyGen。")
        if not source_only and (provider=="heygen" or lipsync) and not read_key():
            raise ValueError("请先在设置中连接 HeyGen。")
        options={"provider":provider,"caption_mode":mode,"caption_y":y,"note":note,"lipsync":lipsync,
                 "watermark":options.get("watermark",False) is True,"source_only":source_only}
        raw=request.form.get("links","").strip()
        urls = []
        for line in raw.splitlines():
            if line := line.strip():
                valid_url(line)
                urls.append(wechat_share_url(line) or line)
        urls = list(dict.fromkeys(urls))
        files=[file for file in request.files.getlist("files") if file.filename]
        for file in files:
            if Path(file.filename).suffix.lower() not in VIDEO_EXTENSIONS:
                raise ValueError("支持 MP4、MOV、MKV、WebM、M4V 和 AVI。")
        sample=request.form.get("sample")=="1" and EXAMPLE_SOURCE.is_file()
        if source_only and (files or sample):
            raise ValueError("只下载原片时请提交分享链接。")
        if not 1 <= len(urls)+len(files)+int(sample) <= 30:
            raise ValueError("每批请选择 1 到 30 条视频。")
    except (TypeError, ValueError, AttributeError) as error:
        return jsonify(error=str(error)), 400
    work = []
    options_json = json.dumps(options, ensure_ascii=False)
    try:
        for title,url,file in [(url,None,None) for url in urls]+[(file.filename,None,file) for file in files]+(
            [("二虎示例 · 原片",None,EXAMPLE_SOURCE)] if sample else []
        ):
            if title in urls and file is None:
                url=title
                title=urlsplit(url).hostname+" · "+urlsplit(url).path.rstrip("/").split("/")[-1]
            job_id=uuid4().hex
            folder=DATA / "jobs" / job_id
            folder.mkdir()
            work.append((job_id,Path(title).stem[:200] if file is not None else title[:200],url,options_json))
            if file is not None:
                if isinstance(file,Path):
                    shutil.copyfile(file,folder/"input.media")
                else:
                    file.save(folder/"input.media")
        with db() as con:
            con.executemany("INSERT INTO jobs (id,title,url,options) VALUES (?,?,?,?)",work)
    except (OSError,sqlite3.Error) as error:
        for job_id,*_ in work:
            shutil.rmtree(DATA/"jobs"/job_id,ignore_errors=True)
        return jsonify(error=f"写入视频失败。{error}"), 400
    WAKE.set()
    return jsonify(ids=[item[0] for item in work]), 202


@app.post("/api/jobs/<string:job_id>/retry")
def retry(job_id):
    data = request.get_json(silent=True)
    offline = isinstance(data, dict) and data.get("provider") == "local"
    with db() as con:
        row = con.execute("SELECT options FROM jobs WHERE id=? AND state='failed'", (job_id,)).fetchone()
        if not row:
            return jsonify(error="只有失败或中断的任务可以重试。"), 409
        options = json.loads(row["options"])
        if offline:
            if not pipeline.LOCAL_VOICE:
                return jsonify(error="离线配音暂不可用。"), 409
            options.update(provider="local", lipsync=False)
        count = con.execute("""UPDATE jobs SET state='queued',stage='排队中',percent=0,message='',options=?,
                               retry_at=0,download_attempts=0 WHERE id=? AND state='failed'""",
                            (json.dumps(options,ensure_ascii=False), job_id)).rowcount
    if not count:
        return jsonify(error="任务状态已更新。"), 409
    WAKE.set()
    return jsonify(ok=True)


def output_name(job):
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", job["title"]).strip(" .")[:105] or job["id"][:8]


@app.get("/api/jobs/<string:job_id>/<kind>")
def media(job_id, kind):
    if kind not in {"video","subs","preview","source"}:
        abort(404)
    with db() as con:
        job = con.execute("SELECT id,title,state,url,options FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        abort(404)
    folder = DATA / "jobs" / job["id"]
    if kind == "source":
        path = folder / "input.media"
        if not job["url"] or not path.is_file():
            abort(404)
        try:
            suffix = pipeline.source_suffix(path)
        except (RuntimeError, ValueError, KeyError):
            abort(404)
        return send_file(path, as_attachment=True, download_name=output_name(job) + "_原片" + suffix)
    if job["state"] != "done" or json.loads(job["options"]).get("source_only"):
        abort(404)
    filename = "字幕.srt" if kind == "subs" else "成片.mp4"
    path = folder / filename
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="application/x-subrip" if kind=="subs" else "video/mp4",
                     as_attachment=kind!="preview", download_name=output_name(job)+"_韩语"+path.suffix)


@app.post("/api/archive")
def archive():
    ids=(request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids,list) or not 1<=len(ids)<=30 or not all(isinstance(i,str) for i in ids):
        return jsonify(error="请选择 1 到 30 条已完成任务。"),400
    with db() as con:
        rows=[con.execute("SELECT id,title,options FROM jobs WHERE id=? AND state='done'",(i,)).fetchone() for i in dict.fromkeys(ids)]
    if not all(rows):
        return jsonify(error="所选任务包含尚未完成的视频。"),409
    ticket=secrets.token_urlsafe(18)
    with ARCHIVE_LOCK:
        now=time.monotonic()
        for old in tuple(ARCHIVES):
            if ARCHIVES[old][0]<now:
                ARCHIVES.pop(old)
        ARCHIVES[ticket]=(now+180,rows)
    return jsonify(url="/api/archive/"+ticket)


@app.get("/api/archive/<string:ticket>")
def download_archive(ticket):
    with ARCHIVE_LOCK:
        details=ARCHIVES.pop(ticket,None)
    if not details or details[0]<time.monotonic():
        abort(404)
    rows=details[1]
    temp=tempfile.TemporaryFile()
    with zipfile.ZipFile(temp,"w",allowZip64=True) as archive_file:
        for row in rows:
            root=DATA/"jobs"/row["id"]
            bundle=output_name(row)+"_"+row["id"][:6]
            if json.loads(row["options"]).get("source_only"):
                path = root / "input.media"
                archive_file.write(path, f"{bundle}/原片{pipeline.source_suffix(path)}")
            else:
                for entry in ("成片.mp4", "字幕.srt"):
                    archive_file.write(root / entry, f"{bundle}/{entry}")
    temp.seek(0)
    return send_file(temp, mimetype="application/zip", as_attachment=True, download_name="视频批量下载.zip")


@app.get("/api/example")
def example():
    if not EXAMPLE_VIDEO.is_file():
        abort(404)
    return send_file(EXAMPLE_VIDEO,mimetype="video/mp4")


@app.post("/api/output")
def open_output():
    if PUBLIC_HOST:
        abort(404)
    subprocess.Popen(["open",str(DATA/"jobs")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return jsonify(ok=True)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="这一批文件总体积超过 1 GB。请拆成几批上传。"),413


if __name__ == "__main__":
    if PUBLIC_HOST:
        from waitress import create_server

        server = create_server(app, host="127.0.0.1", port=PORT, threads=6, channel_timeout=350)
        serve = server.run
    else:
        server = make_server("127.0.0.1", PORT, app, threaded=True)
        serve = server.serve_forever
    init()
    threading.Thread(target=worker, daemon=True).start()
    print(f"韩语视频工作台 http://127.0.0.1:{PORT}/", flush=True)
    serve()
