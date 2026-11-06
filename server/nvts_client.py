#!/usr/bin/env python3
"""
nvts_client — authenticated client for Netvue/Birdfy's cloud (nvts), so the sidecar
can use the user's PAID unlimited AI recognition on a local snapshot.

Auth is chained HMAC-SHA256 in x-nvs-* headers (NO Bearer). Seeds (token/ucid/udid/
userID) come from POST /v1/users/login. See docs/recognition-paid-pipeline.md and
docs/nvts-auth-derivation.md for the full derivation.

Stdlib only. Designed to run ON THE NAS (never through a MITM proxy). Credentials
come from env: NVS_EMAIL, NVS_PASSWORD. Session + device id are cached in CACHE_DIR.

Two things are confirmed-by-code and ready; one (the upload-apply route) is
discovered at runtime and then cached — discover_upload_apply() probes candidates
and logs the winner so you can pin it in the docs.
"""
import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid

CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")
NVS_EMAIL = os.environ.get("NVS_EMAIL", "")
NVS_PASSWORD = os.environ.get("NVS_PASSWORD", "")
NVS_LOGIN_URL = os.environ.get("NVS_LOGIN_URL", "https://localweb.netvue.co/v1/users/login")
NVS_API_BASE = os.environ.get("NVS_API_BASE", "https://capiv3.nvts.co").rstrip("/")
# Allow an override once the real upload-apply path is known (then it's pinned, no probing).
NVS_UPLOAD_APPLY_PATH = os.environ.get("NVS_UPLOAD_APPLY_PATH", "")

SESSION_FILE = os.path.join(CACHE_DIR, "nvs_session.json")
DEVICE_FILE = os.path.join(CACHE_DIR, "nvs_device.json")

# Only set NVS_INSECURE=1 for throwaway testing behind a TLS-intercepting proxy.
# The NAS must NOT need this — real creds must never cross a MITM.
_CTX = ssl.create_default_context()
if os.environ.get("NVS_INSECURE") == "1":
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE


def _log(*a):
    print("[nvts]", *a, flush=True)


def md5hex(s):
    return hashlib.md5(s.encode()).hexdigest()


def sign(token, ucid, udid, userid, ts):
    """Chained HMAC-SHA256, byte-verified against the web bundle's signer."""
    k = ("nvs1" + token).encode()
    for v in [ucid, udid, str(userid), ts, "nvs1_request"]:
        k = hmac.new(k, v.encode(), hashlib.sha256).hexdigest().encode()
    return k.decode()


def _http(method, url, data=None, headers=None, timeout=25):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=_CTX)
        return r.getcode(), dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _json_body(code, body):
    try:
        return json.loads(body.decode() or "{}")
    except Exception:
        return {"_nonjson": body[:200].decode("latin1", "replace"), "_code": code}


# ------------------------- device identity -------------------------
def _device():
    """Stable udid/ucid for this sidecar, persisted so the session is reproducible."""
    try:
        with open(DEVICE_FILE) as f:
            return json.load(f)
    except Exception:
        d = {"udid": str(uuid.uuid4()), "ucid": "0000000000"}
        _save(DEVICE_FILE, d)
        return d


def _save(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception as e:
        _log("save failed", path, e)


# ------------------------- login / session -------------------------
def _unwrap(obj):
    """nvts wraps payloads as {ret, msg, data:{...}} — return the inner data."""
    if isinstance(obj, dict) and "ret" in obj and isinstance(obj.get("data"), dict):
        return obj["data"], obj.get("ret"), obj.get("msg")
    return obj, obj.get("ret") if isinstance(obj, dict) else None, (obj.get("msg") if isinstance(obj, dict) else None)


def login():
    if not (NVS_EMAIL and NVS_PASSWORD):
        raise RuntimeError("NVS_EMAIL / NVS_PASSWORD not set")
    dev = _device()
    body = json.dumps({
        "username": NVS_EMAIL.lower().strip(),
        "password": md5hex(NVS_PASSWORD),
        "locale": "en",
        "platform": 0,
    }).encode()
    code, _, raw = _http("POST", NVS_LOGIN_URL, data=body, headers={
        "content-type": "application/json",
        "x-nvs-ucid": dev["ucid"],
        "x-nvs-udid": dev["udid"],
    })
    obj = _json_body(code, raw)
    data, ret, msg = _unwrap(obj)
    if ret not in (0, None) or code >= 400:
        raise RuntimeError("login failed: HTTP %s ret=%s msg=%r" % (code, ret, msg))
    # Field names tolerant: confirm against the first real response and simplify later.
    token = data.get("token") or data.get("accessToken")
    userid = data.get("userID") or data.get("userId") or data.get("userid")
    ucid = data.get("ucid") or dev["ucid"]
    udid = data.get("udid") or dev["udid"]
    if not token or userid is None:
        raise RuntimeError("login ok but token/userID missing; raw keys=%s" % list(data.keys()))
    exp = data.get("expiresIn") or data.get("expireIn") or 86400
    sess = {
        "token": token, "ucid": ucid, "udid": udid, "userID": userid,
        "refreshToken": data.get("refreshToken", ""),
        "expires_at": time.time() + float(exp) - 120,  # refresh a little early
    }
    _save(SESSION_FILE, sess)
    # keep the device file aligned with what the server bound the session to
    _save(DEVICE_FILE, {"udid": udid, "ucid": ucid})
    _log("login ok; userID=%s ucid=%s udid=%s" % (userid, ucid, udid))
    return sess


def get_session():
    try:
        with open(SESSION_FILE) as f:
            sess = json.load(f)
        if sess.get("token") and sess.get("expires_at", 0) > time.time():
            return sess
    except Exception:
        pass
    return login()


def signed_headers(sess, extra=None):
    ts = str(int(time.time() * 1000))
    h = {
        "x-nvs-version": '{"signature":2}',
        "x-nvs-ucid": sess["ucid"],
        "x-nvs-udid": sess["udid"],
        "x-nvs-userid": str(sess["userID"]),
        "x-nvs-time": ts,
        "x-nvs-signature": sign(sess["token"], sess["ucid"], sess["udid"], sess["userID"], ts),
    }
    if extra:
        h.update(extra)
    return h


def api(method, path, sess=None, json_body=None, raw=None, ctype="application/json", timeout=25):
    """Signed call to NVS_API_BASE. Retries once after a fresh login on 401/403/sig errors."""
    sess = sess or get_session()
    url = NVS_API_BASE + "/" + path.lstrip("/")
    data = raw if raw is not None else (json.dumps(json_body).encode() if json_body is not None else None)
    for attempt in (1, 2):
        headers = signed_headers(sess, {"content-type": ctype} if data is not None else None)
        code, hdrs, body = _http(method, url, data=data, headers=headers, timeout=timeout)
        obj = _json_body(code, body)
        ret = obj.get("ret") if isinstance(obj, dict) else None
        sig_err = code in (401, 403) or ret in (73,) or (isinstance(obj, dict) and "SIGNATURE" in str(obj.get("msg", "")).upper())
        if sig_err and attempt == 1:
            _log("auth rejected (HTTP %s ret=%s) — re-login and retry" % (code, ret))
            sess = login()
            continue
        return code, obj, body
    return code, obj, body


# ------------------------- upload-apply discovery -------------------------
# The app's applyForUploadAttachmentInfo route is runtime-built; probe candidates
# once, cache the winner. A winner responds with a presigned-URL-ish payload.
_APPLY_CANDIDATES = [
    "attachment/upload/apply", "attachments/upload/apply", "attachment/apply",
    "attachments", "attachment/upload", "upload/apply", "cdn/upload/apply",
    "cdn/resource/apply", "resource/upload/apply", "photoRecognition/upload",
    "photoRecognition/uploadUrl", "photoRecognition/presign",
]
_apply_cache = {"path": NVS_UPLOAD_APPLY_PATH or None}


def _looks_like_presign(obj):
    if not isinstance(obj, dict):
        return False
    data = obj.get("data", obj)
    if not isinstance(data, dict):
        return False
    keys = {k.lower() for k in data.keys()}
    return bool(keys & {"presignedurl", "uploadurl", "url", "puturl"}) and \
        bool(keys & {"filekey", "bucketkey", "key", "objectkey"})


def discover_upload_apply(sess=None, sample=None):
    """Probe candidate apply routes; return (path, response) for the first that looks
    like a presign. `sample` is a tiny body to send; shape is guessed, so a route may
    reject the body yet still prove it exists (non-404). Logs everything."""
    sess = sess or get_session()
    sample = sample or {"contentType": "image/jpeg", "fileName": "probe.jpg", "fileSize": 123}
    found = None
    for path in _APPLY_CANDIDATES:
        for method, bodyarg in (("POST", {"json_body": sample}), ("GET", {})):
            code, obj, _ = api(method, path, sess=sess, **bodyarg)
            tag = "PRESIGN!" if _looks_like_presign(obj) else ""
            msg = obj.get("msg") if isinstance(obj, dict) else ""
            _log("probe %-28s %-4s -> HTTP %s ret=%s %s %s" %
                 (path, method, code, (obj.get("ret") if isinstance(obj, dict) else "?"), str(msg)[:60], tag))
            if _looks_like_presign(obj):
                found = (path, obj)
                break
            # a 4xx that's NOT route-miss (ret==1/empty) is still a live route worth noting
        if found:
            break
    if found:
        _apply_cache["path"] = found[0]
        _log("UPLOAD-APPLY ROUTE =", found[0], "-> pin NVS_UPLOAD_APPLY_PATH and record in docs")
    else:
        _log("no upload-apply route matched; inspect the logs above / capture one real app run")
    return found


# ------------------------- the pipeline -------------------------
def upload_image(img_bytes, sess=None):
    """apply -> PUT bytes -> return fileKey. Tolerant of field-name variants."""
    sess = sess or get_session()
    path = _apply_cache.get("path")
    if not path:
        f = discover_upload_apply(sess)
        if not f:
            raise RuntimeError("upload-apply route unknown (run discover_upload_apply / login_test.py)")
        path, _ = f
    apply_body = {"contentType": "image/jpeg", "fileName": "snapshot.jpg", "fileSize": len(img_bytes)}
    code, obj, _ = api("POST", path, sess=sess, json_body=apply_body)
    data = obj.get("data", obj) if isinstance(obj, dict) else {}
    low = {k.lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
    put_url = low.get("presignedurl") or low.get("uploadurl") or low.get("url") or low.get("puturl")
    file_key = low.get("filekey") or low.get("bucketkey") or low.get("key") or low.get("objectkey")
    method = (low.get("method") or "PUT").upper()
    extra_headers = low.get("headers") or {"content-type": "image/jpeg"}
    if not (put_url and file_key):
        raise RuntimeError("apply response missing presignedUrl/fileKey: %r" % (data,))
    pc, _, pbody = _http(method, put_url, data=img_bytes, headers=extra_headers, timeout=60)
    if pc >= 300:
        raise RuntimeError("upload PUT failed HTTP %s: %s" % (pc, pbody[:200]))
    return file_key


def create_task(file_key, capture_time_ms=None, lat=0.0, lng=0.0, label="", sess=None):
    body = {"fileKey": file_key,
            "captureTime": int(capture_time_ms or time.time() * 1000),
            "longitude": lng, "latitude": lat, "locationLabel": label}
    code, obj, _ = api("POST", "photoRecognition/tasks", sess=sess, json_body=body)
    data = obj.get("data", obj) if isinstance(obj, dict) else {}
    task = (data.get("task") or data) if isinstance(data, dict) else {}
    task_id = task.get("taskId") or data.get("taskId")
    if not task_id:
        raise RuntimeError("create_task no taskId: HTTP %s %r" % (code, obj))
    return task_id


def poll_task(task_id, tries=12, delay=1.5, sess=None):
    for _ in range(tries):
        code, obj, _ = api("POST", "photoRecognition/status", sess=sess, json_body={"taskIds": [task_id]})
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        results = data if isinstance(data, list) else data.get("results") or data.get("tasks") or []
        for r in (results if isinstance(results, list) else [results]):
            status = (r.get("status") or "").lower() if isinstance(r, dict) else ""
            subjects = r.get("subjects") if isinstance(r, dict) else None
            if subjects:
                cands = (subjects[0] or {}).get("candidates") or []
                if cands:
                    c = cands[0]
                    return c.get("commonName"), c.get("confidence"), c
            if status in ("failed", "error"):
                return None, None, r
        time.sleep(delay)
    return None, None, {"status": "timeout"}


def identify_paid(img_bytes, capture_time_ms=None):
    """Full paid on-demand ID. Returns (species, confidence) or (None, reason)."""
    try:
        sess = get_session()
        fk = upload_image(img_bytes, sess)
        tid = create_task(fk, capture_time_ms, sess=sess)
        name, conf, _ = poll_task(tid, sess=sess)
        if name:
            return name, conf
        return None, "no candidate / timeout"
    except Exception as e:
        return None, "paid recogniser error: %s" % e
