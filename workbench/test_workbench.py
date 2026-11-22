import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app
import pipeline
from download_retry import DownloadRateLimited, DownloadRetry, retry_after_seconds


class WorkbenchTest(unittest.TestCase):
    def test_srt_order_and_bounds(self):
        raw = "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n2\n00:00:00,950 --> 00:00:02,000\n再见\n"
        cues = pipeline.parse_srt(raw, 1.8)
        self.assertEqual([(i["start"], i["end"], i["zh"]) for i in cues],
                         [(0, 1, "你好"), (1, 1.8, "再见")])

    def test_original_only_can_queue_without_a_heygen_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "DATA", Path(directory)), \
                patch.object(app, "read_key", return_value=""):
            app.init()
            client = app.app.test_client()
            response = client.post("/api/jobs", base_url="http://127.0.0.1:8790",
                                   headers={"X-Workbench": app.TOKEN},
                                   data={"options": '{"provider":"heygen","lipsync":true}', "source_only": "1",
                                         "links": "https://weixin.qq.com/sph/sample/?from=share"})
            self.assertEqual(response.status_code, 202)
            job_id, = response.json["ids"]
            with app.db() as con:
                row = con.execute("SELECT url,options FROM jobs WHERE id=?", (job_id,)).fetchone()
            self.assertEqual(row["url"], "https://weixin.qq.com/sph/sample")
            self.assertTrue(json.loads(row["options"])["source_only"])

    def test_rate_limit_survives_restart_and_keeps_other_jobs_running(self):
        self.assertEqual(retry_after_seconds("120"), 120)
        self.assertEqual(retry_after_seconds("Thu, 01 Jan 1970 00:02:00 GMT", now=30), 90)
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "DATA", Path(directory)), \
                patch.object(pipeline, "LOCAL_VOICE", True), patch.object(app.time, "time", return_value=1000):
            app.init()
            client = app.app.test_client()
            base = "http://127.0.0.1:8790"
            headers = {"X-Workbench": app.TOKEN}
            links = client.post("/api/jobs", base_url=base, headers=headers,
                                data={"links": "https://weixin.qq.com/sph/one\nhttps://weixin.qq.com/sph/two",
                                      "source_only": "1"}).json["ids"]
            upload = client.post("/api/jobs", base_url=base, headers=headers,
                                 data={"files": (io.BytesIO(b"upload"), "upload.mp4")}).json["ids"][0]
            with patch.object(pipeline, "process", side_effect=[DownloadRateLimited(120), (1, "")]) as process:
                self.assertTrue(app.process_next())
                app.init()
                self.assertTrue(app.process_next())
                self.assertTrue(app.process_next())
                self.assertFalse(app.process_next())
                self.assertEqual(process.call_count, 2)
                waited = {row["id"]: row for row in client.get("/api/jobs", base_url=base).json}
                for link in links:
                    self.assertEqual(waited[link]["state"], "queued")
                    self.assertEqual(waited[link]["retry_at"], 1120)
                self.assertEqual(waited[upload]["state"], "done")
            previous = Path(directory) / "jobs" / links[0] / "input.media"
            previous.write_bytes(b"cached original")
            cached = client.post("/api/jobs", base_url=base, headers=headers, data={
                "links": "https://weixin.qq.com/sph/one?shared=1", "source_only": "1"}).json["ids"][0]
            with patch.object(pipeline, "video_input_info", return_value={"format":{"duration":"1", "format_name":"mov"}}):
                self.assertTrue(app.process_next())
                response = client.get(f"/api/jobs/{cached}/source", base_url=base)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b"cached original")
                response.close()
                self.assertEqual(client.get(f"/api/jobs/{cached}/video", base_url=base).status_code, 404)
                ticket = client.post("/api/archive", base_url=base, headers=headers, json={"ids": [cached]}).json["url"]
                response = client.get(ticket, base_url=base)
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    name, = archive.namelist()
                    self.assertTrue(name.endswith("/原片.mp4"))
                    self.assertEqual(archive.read(name), b"cached original")
                response.close()
            with patch.object(app.time, "time", return_value=1120), patch.object(
                    pipeline, "process", return_value=(1,"")) as process:
                self.assertTrue(app.process_next())
                self.assertEqual(process.call_args.args[1]["id"], links[0])

    def test_download_timeout_leaves_other_links_runnable(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "DATA", Path(directory)):
            app.init()
            client = app.app.test_client()
            base = "http://127.0.0.1:8790"
            headers = {"X-Workbench": app.TOKEN}
            first, second = client.post("/api/jobs", base_url=base, headers=headers, data={
                "links": "https://weixin.qq.com/sph/one\nhttps://weixin.qq.com/sph/two",
                "source_only": "1"}).json["ids"]
            with patch.object(pipeline, "process", side_effect=[DownloadRetry("下载响应超时。"), (1, "")]) as process:
                self.assertTrue(app.process_next())
                self.assertTrue(app.process_next())
                self.assertFalse(app.process_next())
                self.assertEqual(process.call_count, 2)
            rows = {row["id"]: row for row in client.get("/api/jobs", base_url=base).json}
            self.assertEqual(rows[first]["stage"], "等待下载恢复")
            self.assertIn("超时", rows[first]["message"])
            self.assertEqual(rows[second]["state"], "done")

    def test_batch_retry_download_and_local_request_boundary(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "DATA", Path(directory)):
            app.init()
            client = app.app.test_client()
            base = "http://127.0.0.1:8790"
            headers = {"X-Workbench": app.TOKEN}
            self.assertEqual(client.get("/", base_url="http://malicious.test:8790").status_code, 403)
            self.assertEqual(client.post("/api/jobs", base_url=base).status_code, 403)
            payload = {"links": "https://weixin.qq.com/sph/example", "options": json.dumps({})}
            payload["files"] = (io.BytesIO(b"test input"), "sample.mp4")
            submit = client.post("/api/jobs", data=payload, base_url=base, headers=headers)
            self.assertEqual(submit.status_code, 202)
            numbers = submit.json["ids"]
            self.assertEqual(len(numbers), 2)
            app.change(numbers[0], state="failed")
            self.assertTrue(client.post(f"/api/jobs/{numbers[0]}/retry", base_url=base, headers=headers).json["ok"])
            self.assertEqual(client.get(f"/api/jobs/{numbers[0]}/video", base_url=base).status_code, 404)
            for number in numbers:
                folder = Path(directory) / "jobs" / number
                (folder / "成片.mp4").write_bytes(b"placeholder")
                (folder / "字幕.srt").write_text("안녕하세요")
                app.change(number, state="done")
            ticket = client.post("/api/archive", json={"ids": numbers}, base_url=base, headers=headers).json["url"]
            response = client.get(ticket, base_url=base)
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
                self.assertEqual(len(bundle.namelist()), 4)
                self.assertIsNone(bundle.testzip())
            response.close()


if __name__ == "__main__":
    unittest.main()
