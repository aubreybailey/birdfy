#!/usr/bin/env python3
"""
birdfy — combined capture + browse server.

One container, two HTTP servers in one process:
  - Capture (:CAPTURE_PORT) — accepts the feeder's redirected S3 PUTs, writes
    media + .meta to CAPTURE_DIR.
  - Browse  (:BROWSE_PORT)  — read-only API for the viewer app, on-demand
    species identification, ntfy push on new events.

Stdlib only. ffmpeg on PATH enables /video.mp4 remux.

Env:
  CAPTURE_DIR      data directory                  (default /data/captures)
  CACHE_DIR        writable scratch for MP4s       (default /cache)
  CAPTURE_PORT     capture listener                (default 8085)
  BROWSE_PORT      browse API listener             (default 8086)
  MAX_BODY_MB      max upload size                 (default 50)
  NTFY_URL / NTFY_TOPIC / NTFY_TOKEN               (optional; enables push)
  WATCH_INTERVAL   seconds between new-event scans (default 4)
  DEMO_BIRD_URL    bird-ID endpoint                (default https://object-detect-bird-demo.netvue.co/demo/bird)
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CAPTURE_DIR = os.environ.get("CAPTURE_DIR", "/data/captures")
CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")
CAPTURE_PORT = int(os.environ.get("CAPTURE_PORT", "8085"))
BROWSE_PORT = int(os.environ.get("BROWSE_PORT", "8086"))
MAX_BODY = int(os.environ.get("MAX_BODY_MB", "50")) * 1024 * 1024
NTFY_URL = os.environ.get("NTFY_URL", "").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")
WATCH_INTERVAL = int(os.environ.get("WATCH_INTERVAL", "4"))
DEMO_BIRD_URL = os.environ.get(
    "DEMO_BIRD_URL",
    "https://object-detect-bird-demo.netvue.co/demo/bird",
)
WEB_DIR = os.environ.get(
    "WEB_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
)

STATIC_TYPES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}
# No slashes in the name, so this cannot escape WEB_DIR.
STATIC_RE = re.compile(r"/([A-Za-z0-9_.-]+\.(?:html|js|css))")

STORE = Path(CAPTURE_DIR)
SEG_RE = re.compile(r"slice_\d+_(\d+)_\d+\.ts$")
DATE_RE = r"\d{4}-\d{2}-\d{2}"


# ========================= CAPTURE =========================

def _guess_ext(path, content_type, body):
    clean = path.split("?")[0]
    if "." in clean.split("/")[-1]:
        return "." + clean.split(".")[-1]
    ct_map = {
        "image/jpeg": ".jpg", "image/png": ".png",
        "video/mp4": ".mp4", "application/octet-stream": "",
    }
    for prefix, ext in ct_map.items():
        if content_type.startswith(prefix):
            return ext
    if body[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if body[:4] == b"\x89PNG":
        return ".png"
    if len(body) > 8 and body[4:8] == b"ftyp":
        return ".mp4"
    return ".bin"


class CaptureHandler(BaseHTTPRequestHandler):
    def do_PUT(self):
        self._save("PUT")

    def do_POST(self):
        self._save("POST")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"birdfy-capture alive\n")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def _save(self, method):
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            self.send_response(413)
            self.end_headers()
            return
        body = self.rfile.read(length) if length else b""
        if not body:
            self._s3_ok()
            return

        # Local time, so day folders match the user's calendar. Set TZ to pick
        # the zone; the .meta timestamp keeps its UTC offset either way.
        now = datetime.now().astimezone()
        day_dir = STORE / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        ext = _guess_ext(self.path, self.headers.get("Content-Type", ""), body)
        ts = now.strftime("%H%M%S")
        digest = hashlib.sha256(body).hexdigest()[:12]
        filename = f"{ts}_{digest}{ext}"
        out = day_dir / filename

        out.write_bytes(body)
        (day_dir / f"{filename}.meta").write_text(
            f"time: {now.isoformat()}\n"
            f"method: {method}\n"
            f"path: {self.path}\n"
            f"host: {self.headers.get('Host', '?')}\n"
            f"content-type: {self.headers.get('Content-Type', '?')}\n"
            f"size: {len(body)}\n"
        )
        print(f"[{now.strftime('%H:%M:%S')}] {method} {self.path[:80]} -> {out.name} ({len(body)} bytes)")
        self._s3_ok(digest)

    def _s3_ok(self, etag="d41d8cd98f00b204e9800998ecf8427e"):
        self.send_response(200)
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


# ========================= BROWSE =========================

# ----- species cache (file-backed) -----
SPECIES_CACHE_FILE = os.path.join(CACHE_DIR, "species.json")
_species_lock = threading.Lock()


def _load_species_cache():
    try:
        with open(SPECIES_CACHE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_species_cache(cache):
    tmp = SPECIES_CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, SPECIES_CACHE_FILE)


def get_cached_species(event_id):
    with _species_lock:
        return _load_species_cache().get(event_id)


def set_cached_species(event_id, species_info):
    with _species_lock:
        c = _load_species_cache()
        c[event_id] = species_info
        _save_species_cache(c)


def identify_demo(date, event_id):
    cached = get_cached_species(event_id)
    if cached:
        return cached

    ev = next((e for e in index_day(date) if e["event_id"] == event_id), None)
    if not ev or not ev["thumbnail"]:
        return {"error": "no thumbnail for this event"}

    thumb_path = os.path.join(CAPTURE_DIR, date, ev["thumbnail"])
    with open(thumb_path, "rb") as f:
        img_bytes = f.read()

    req = urllib.request.Request(
        DEMO_BIRD_URL, data=img_bytes, method="POST",
        headers={"Content-Type": "image/jpeg"})
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())

    species = None
    confidence = 0
    bbox = None
    species_key = None
    for category in resp.get("data", []):
        if category.get("name") != "bird":
            continue
        for obj in category.get("objects", []):
            for desc in obj.get("desc", []):
                if desc.get("confidence", 0) >= confidence:
                    species = desc.get("name")
                    confidence = desc.get("confidence", 0)
                    species_key = obj.get("key")
                    bbox = {k: obj[k] for k in ("left", "top", "width", "height") if k in obj}

    result = {
        "species": species,
        "confidence": confidence,
        "bbox": bbox,
        "key": species_key,
        "source": "demo",
    }
    if species:
        set_cached_species(event_id, result)
    return result


def enrich_events(date, events):
    for ev in events:
        cached = get_cached_species(ev["event_id"])
        ev["species"] = cached.get("species") if cached else None
    return events


# ----- data indexing -----

def event_id_from_path(path):
    parts = [p for p in path.split("/") if p]
    return parts[-2] if len(parts) >= 2 else None


def read_meta(mpath):
    m = {}
    try:
        with open(mpath) as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    m[k.strip()] = v.strip()
    except OSError:
        return None
    return m


def list_days():
    if not os.path.isdir(CAPTURE_DIR):
        return []
    return sorted(d for d in os.listdir(CAPTURE_DIR) if re.fullmatch(DATE_RE, d))


def index_day(date):
    day_dir = os.path.join(CAPTURE_DIR, date)
    events = {}
    if not os.path.isdir(day_dir):
        return []
    for name in os.listdir(day_dir):
        if not name.endswith(".meta"):
            continue
        meta = read_meta(os.path.join(day_dir, name))
        if not meta or "path" not in meta:
            continue
        upath = meta["path"]
        ev = event_id_from_path(upath)
        if not ev:
            continue
        disk = name[:-5]
        e = events.setdefault(ev, {
            "event_id": ev, "time": meta.get("time", ""),
            "thumbnail": None, "segments": [], "_segmeta": [],
            "device_id": "", "camera_id": "",
        })
        parts = [p for p in upath.split("/") if p]
        if len(parts) >= 4:
            e["device_id"], e["camera_id"] = parts[-4], parts[-3]
        if os.path.basename(upath) == "image.jpg":
            e["thumbnail"] = disk
            e["time"] = meta.get("time", e["time"])
        else:
            seq = SEG_RE.search(upath)
            e["_segmeta"].append((int(seq.group(1)) if seq else 0, disk))
    out = []
    for e in events.values():
        e["_segmeta"].sort()
        e["segments"] = [d for _, d in e["_segmeta"]]
        del e["_segmeta"]
        out.append(e)
    out.sort(key=lambda x: x["time"])
    return out


# ----- media -----

def event_mp4(date, event_id):
    ev = next((e for e in index_day(date) if e["event_id"] == event_id), None)
    if not ev or not ev["segments"]:
        return None
    cdir = os.path.join(CACHE_DIR, date)
    os.makedirs(cdir, exist_ok=True)
    out = os.path.join(cdir, f"{event_id}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    day_dir = os.path.join(CAPTURE_DIR, date)
    listfile = os.path.join(cdir, f"{event_id}.txt")
    with open(listfile, "w") as f:
        for seg in ev["segments"]:
            f.write(f"file '{os.path.join(day_dir, seg)}'\n")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
             "-c", "copy", "-movflags", "+faststart", out],
            check=True, capture_output=True, timeout=60)
        return out
    except Exception as e:
        print("ffmpeg remux failed:", e, flush=True)
        return None


def mp4_available(date, event_id):
    cached = os.path.join(CACHE_DIR, date, f"{event_id}.mp4")
    if os.path.exists(cached):
        return True
    has_seg = any(e["event_id"] == event_id and e["segments"] for e in index_day(date))
    return bool(shutil.which("ffmpeg") and has_seg)


def playlist(date, event_id):
    ev = next((e for e in index_day(date) if e["event_id"] == event_id), None)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:3", "#EXT-X-MEDIA-SEQUENCE:0"]
    if ev:
        for seg in ev["segments"]:
            lines += ["#EXTINF:2.0,", f"/api/media/{date}/{seg}"]
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


# ----- ntfy watcher -----

def publish_ntfy(date, event_id):
    if not (NTFY_URL and NTFY_TOPIC):
        return
    try:
        req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}",
                                     data=f"{date}/{event_id}".encode(), method="POST")
        req.add_header("Title", "Bird spotted")
        req.add_header("Tags", "bird")
        if NTFY_TOKEN:
            req.add_header("Authorization", f"Bearer {NTFY_TOKEN}")
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:
        print("ntfy publish failed:", e, flush=True)


def watcher():
    seen = set()
    first = True
    while True:
        try:
            days = list_days()
            if days:
                for ev in index_day(days[-1]):
                    if ev["thumbnail"] and ev["event_id"] not in seen:
                        seen.add(ev["event_id"])
                        if not first:
                            publish_ntfy(days[-1], ev["event_id"])
            first = False
        except Exception as e:
            print("watcher error:", e, flush=True)
        time.sleep(WATCH_INTERVAL)


# ----- browse HTTP handler -----

class BrowseHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj).encode(), "application/json")

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._send(404, b"not found\n")

    def do_HEAD(self):
        p = self.path.split("?", 1)[0]
        m = re.fullmatch(rf"/api/event/({DATE_RE})/([^/]+)/video\.mp4", p)
        code = (200 if mp4_available(m.group(1), m.group(2)) else 404) if m else 200
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _static(self, name):
        ctype = STATIC_TYPES[os.path.splitext(name)[1]]
        return self._file(os.path.join(WEB_DIR, name), ctype)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/health":
            return self._send(200, b"birdfy alive\n")
        if p == "/":
            if os.path.isfile(os.path.join(WEB_DIR, "index.html")):
                return self._static("index.html")
            return self._send(200, b"birdfy alive\n")
        m = STATIC_RE.fullmatch(p)
        if m:
            return self._static(m.group(1))
        if p == "/api/days":
            return self._json(list_days())
        m = re.fullmatch(rf"/api/events/({DATE_RE})", p)
        if m:
            return self._json(enrich_events(m.group(1), index_day(m.group(1))))
        m = re.fullmatch(rf"/api/media/({DATE_RE})/([^/]+)", p)
        if m:
            fp = os.path.join(CAPTURE_DIR, m.group(1), m.group(2))
            ctype = "image/jpeg" if fp.endswith(".jpg") else "video/mp2t"
            return self._file(fp, ctype)
        m = re.fullmatch(rf"/api/event/({DATE_RE})/([^/]+)/video\.mp4", p)
        if m:
            out = event_mp4(m.group(1), m.group(2))
            return self._file(out, "video/mp4") if out else self._send(404, b"no mp4\n")
        m = re.fullmatch(rf"/api/event/({DATE_RE})/([^/]+)/playlist\.m3u8", p)
        if m:
            return self._send(200, playlist(m.group(1), m.group(2)).encode(),
                              "application/vnd.apple.mpegurl")
        self._send(404, b"not found\n")

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        m = re.fullmatch(rf"/api/identify/({DATE_RE})/([^/]+)", p)
        if m:
            try:
                result = identify_demo(m.group(1), m.group(2))
                return self._json(result)
            except Exception as e:
                print(f"identify failed: {e}", flush=True)
                return self._send(500,
                    json.dumps({"error": str(e)}).encode(), "application/json")
        self._send(404, b"not found\n")


# ========================= MAIN =========================

if __name__ == "__main__":
    STORE.mkdir(parents=True, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    threading.Thread(target=watcher, daemon=True).start()

    capture = ThreadingHTTPServer(("0.0.0.0", CAPTURE_PORT), CaptureHandler)
    threading.Thread(target=capture.serve_forever, daemon=True).start()

    print(f"birdfy capture=:{CAPTURE_PORT}  browse=:{BROWSE_PORT}  "
          f"data={CAPTURE_DIR}  cache={CACHE_DIR}  "
          f"ntfy={'on' if NTFY_URL and NTFY_TOPIC else 'off'}  "
          f"identify=demo", flush=True)

    ThreadingHTTPServer(("0.0.0.0", BROWSE_PORT), BrowseHandler).serve_forever()
