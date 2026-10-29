# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7"]
# ///
"""Server web netizen: halaman web/ + API ke run_issue.run.

Jalankan dari folder netizen:  uv run spike/server.py     lalu buka http://localhost:8798
GET  /api/personas                                   -> persona umum (id, label) untuk limbo kosong
GET  /api/latest                                     -> hasil simulasi terakhir yang selesai
POST /api/run  {"text", "platforms"?, "subject"?, "messenger"?, "target"?, "pass"?} -> {"id"}
GET  /api/run/<id>                                   -> {"status": running|done|error, "result"?, "error"?}
NETIZEN_PASS di .env: kalau diset, POST /api/run wajib membawa "pass" yang sama (halaman publik, tiap run
memakan token). Satu simulasi berjalan pada satu waktu; permintaan lain dapat 429.
"""

import asyncio
import json
import os
import sys
import threading
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_issue import PLATFORMS, run, save, web_view  # noqa: E402
from spike import load_env  # noqa: E402

ROOT = Path(__file__).resolve().parent
WEB = ROOT.parent / "web"
LATEST = ROOT / "results" / "web_latest.json"
JOBS: dict[str, dict] = {}
BUSY = threading.Lock()


def worker(job_id: str, req: dict) -> None:
    async def go():
        async with AsyncTypeSafeClient() as client:
            r = await run(client, req["text"], req["subject"], req["target"], req["messenger"], req["platforms"], job_id)
        save(r, job_id)
        return web_view(r)
    try:
        result = asyncio.run(go())
        LATEST.parent.mkdir(exist_ok=True)
        LATEST.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        JOBS[job_id].update(status="done", result=result)
    except Exception as e:  # the page shows the message; the trace stays in the server log
        traceback.print_exc()
        JOBS[job_id].update(status="error", error=f"{type(e).__name__}: {e}")
    finally:
        BUSY.release()


def validate(body: dict) -> dict | str:
    text = str(body.get("text", "")).strip()
    if not 10 <= len(text) <= 1000:
        return "teks post harus 10 sampai 1000 karakter"
    platforms = body.get("platforms") or list(PLATFORMS[:4])
    if not isinstance(platforms, list) or not 1 <= len(platforms) <= 4 or any(p not in PLATFORMS for p in platforms):
        return "platforms harus 1 sampai 4 dari " + ", ".join(PLATFORMS)
    extra = {k: str(body.get(k, ""))[:200].strip() for k in ("subject", "messenger", "target")}
    want = os.environ.get("NETIZEN_PASS", "")
    if want and str(body.get("pass", "")) != want:
        return "kode akses salah"
    return {"text": text, "platforms": platforms, **extra}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def send_json(self, code: int, data) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/personas":
            ps = json.loads((ROOT / "personas.json").read_text(encoding="utf-8"))
            return self.send_json(200, [{"id": p["id"], "label": p["label"]} for p in ps])
        if self.path == "/api/latest":
            if LATEST.exists():
                return self.send_json(200, json.loads(LATEST.read_text(encoding="utf-8")))
            return self.send_json(404, {"error": "belum ada simulasi"})
        if self.path.startswith("/api/run/"):
            job = JOBS.get(self.path.rsplit("/", 1)[1])
            return self.send_json(200, job) if job else self.send_json(404, {"error": "run tidak ditemukan"})
        if self.path.startswith("/api/"):
            return self.send_json(404, {"error": "tidak ada"})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/run":
            return self.send_json(404, {"error": "tidak ada"})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 16000)) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "JSON tidak valid"})
        req = validate(body if isinstance(body, dict) else {})
        if isinstance(req, str):
            return self.send_json(400, {"error": req})
        if not BUSY.acquire(blocking=False):
            return self.send_json(429, {"error": "sedang ada simulasi lain, coba lagi sebentar"})
        job_id = uuid.uuid4().hex[:8]
        JOBS[job_id] = {"status": "running", "text": req["text"], "platforms": req["platforms"]}
        for old in list(JOBS)[:-20]:
            del JOBS[old]
        threading.Thread(target=worker, args=(job_id, req), daemon=True).start()
        self.send_json(202, {"id": job_id})

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    load_env()
    if not os.environ.get("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY missing (put it in netizen/.env)")
    port = int(os.environ.get("PORT", "8798"))
    print(f"netizen web  http://127.0.0.1:{port}  (pass {'ON' if os.environ.get('NETIZEN_PASS') else 'off'})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
