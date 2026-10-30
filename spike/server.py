# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk>=0.7.5"]
# ///
"""Server web netizen: halaman web/ + API ke run_issue.run. Satu-satunya model: Jev (TypeSafe).

Jalankan dari folder netizen:  uv run spike/server.py     lalu buka http://localhost:8798
GET  /api/personas                  -> persona umum (id, label)
POST /api/run                       -> {"id"}   body:
     {"key": <TypeSafe API key pengguna, wajib>, "text"?, "image"?: <png/jpg base64>, "platforms"?,
      "subject"?, "messenger"?, "target"?, "earlier"?: {platform: [{"text","reaction"}]}, "context"?}
     text atau image harus ada. earlier = episode sebelumnya dari akun yang sama (follow-up post).
GET  /api/run/<id>                  -> {"status": running|done|error, "result"?, "error"?}
Key pengguna dipakai sekali untuk request itu dan tidak disimpan; server tidak punya key sendiri.
Satu simulasi berjalan pada satu waktu; permintaan lain dapat 429.
"""

import asyncio
import json
import os
import re
import sys
import threading
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_issue import IMAGE_HEADERS, PLATFORMS, run, save, web_view  # noqa: E402

ROOT = Path(__file__).resolve().parent
WEB = ROOT.parent / "web"
JOBS: dict[str, dict] = {}
BUSY = threading.Lock()
B64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


def worker(job_id: str, req: dict) -> None:
    async def go():
        async with AsyncTypeSafeClient(api_key=req["key"], headers=IMAGE_HEADERS if req["image"] else None) as client:
            r = await run(client, req["text"], req["subject"], req["target"], req["messenger"], req["platforms"], job_id,
                          image_b64=req["image"], earlier=req["earlier"], context=req["context"])
        save(r, job_id)
        return web_view(r)
    try:
        JOBS[job_id].update(status="done", result=asyncio.run(go()))
    except Exception as e:  # the page shows the message; the trace stays in the server log
        traceback.print_exc()
        JOBS[job_id].update(status="error", error=f"{type(e).__name__}: {e}")
    finally:
        BUSY.release()


def validate(body: dict) -> dict | str:
    key = str(body.get("key", "")).strip()
    if not 10 <= len(key) <= 300 or not key.isascii() or any(c.isspace() for c in key):
        return "isi API key TypeSafe kamu (console.typesafe.ai)"
    text = str(body.get("text", "")).strip()
    image = body.get("image") or ""
    if image and (not isinstance(image, str) or len(image) > 6_000_000 or not B64.match(image)):
        return "gambar harus png/jpg base64 di bawah 4 MB"
    if not image and not 10 <= len(text) <= 1000:
        return "teks post harus 10 sampai 1000 karakter, atau unggah gambar"
    if len(text) > 1000:
        return "teks post maksimal 1000 karakter"
    platforms = body.get("platforms") or list(PLATFORMS[:4])
    if not isinstance(platforms, list) or not 1 <= len(platforms) <= 4 or any(p not in PLATFORMS for p in platforms):
        return "platforms harus 1 sampai 4 dari " + ", ".join(PLATFORMS)
    earlier = body.get("earlier") or {}
    if not isinstance(earlier, dict):
        return "earlier harus objek per platform"
    clean = {}
    for pl, eps in earlier.items():
        if pl not in PLATFORMS or not isinstance(eps, list) or len(eps) > 8:
            return "earlier: maksimal 8 episode per platform"
        clean[pl] = [{"text": str(e.get("text", ""))[:1000], "reaction": str(e.get("reaction", ""))[:600]}
                     for e in eps if isinstance(e, dict)]
    extra = {k: str(body.get(k, ""))[:200].strip() for k in ("subject", "messenger", "target")}
    extra["context"] = str(body.get("context", ""))[:1500].strip()
    return {"key": key, "text": text, "image": image, "platforms": platforms, "earlier": clean, **extra}


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
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 8_000_000)) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "JSON tidak valid"})
        req = validate(body if isinstance(body, dict) else {})
        if isinstance(req, str):
            return self.send_json(400, {"error": req})
        if not BUSY.acquire(blocking=False):
            return self.send_json(429, {"error": "sedang ada simulasi lain, coba lagi sebentar"})
        job_id = uuid.uuid4().hex[:8]
        JOBS[job_id] = {"status": "running", "text": req["text"] or "[gambar]", "platforms": req["platforms"]}
        for old in list(JOBS)[:-20]:
            del JOBS[old]
        threading.Thread(target=worker, args=(job_id, req), daemon=True).start()
        self.send_json(202, {"id": job_id})

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    port = int(os.environ.get("PORT", "8798"))
    print(f"netizen web  http://127.0.0.1:{port}  (key dari pengguna per request)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
