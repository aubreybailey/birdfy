# On-demand species — SOLVED via a public no-auth endpoint

## The win
There's a **public, no-auth** bird-ID endpoint. On-demand Design A needs **no login,
no account token, no HMAC signing, no CDN upload** — the sidecar just POSTs the
thumbnail bytes and gets a result back.

```
POST https://object-detect-bird-demo.netvue.co/demo/bird      (also /demo/bird2)
Headers: content-type: image/jpeg          # no auth header at all
Body:    raw image bytes (the event thumbnail)
```

Derived from the web bundle `main-application.42fb038c.js` (module `79f6`, the
"NetvueBirdfyAIDemo" / birds-identify flow):
`{baseURL:"https://object-detect-bird-demo.netvue.co", url:"demo/bird", method:"post",
 data:<image>, headers:{"content-type":<image.type>}}`.

## Verified live (2026-11-02)
POSTed a real feeder thumbnail (29 KB JPEG) → **HTTP 200**:
```json
{"data":[{"name":"bird","objects":[]},{"name":"squirrel","objects":[]}]}
```
The test image was the empty feeder tray, so `objects[]` is empty. The response
groups by category (`bird`, `squirrel`); when something is detected, `objects[]`
fills with the detection(s). (A 2 KB non-JPEG returns `{"ret":9,"msg":"...unsupported
image format"}` / HTTP 400 — so send a real JPEG.)

### Confirmed response (real bird JPEG, 2026-11-03)
```json
{"data":[
  {"name":"bird","objects":[
    {"left":0.47,"top":0.19,"width":0.37,"height":0.65,"confidence":30,
     "desc":[{"name":"Striated Heron","confidence":30}],"key":"04370"}]},
  {"name":"squirrel","objects":[]}]}
```
**Species = `data[name=="bird"].objects[].desc[].name`** (pick highest `desc.confidence`),
with a normalized bbox (`left/top/width/height`) and a species `key`. `/demo/bird` and
`/demo/bird2` returned identical results.

## Sidecar implementation (on-demand, nothing auto-sent)
Add to `browse_sidecar.py` an endpoint the viewer's **Identify** button calls:
```
POST /api/identify/<date>/<event_id>
  -> read the local thumbnail
  -> POST it to https://object-detect-bird-demo.netvue.co/demo/bird (content-type image/jpeg)
  -> parse data[name=="bird"].objects[0].<species field>
  -> cache species in CACHE_DIR/species.json keyed by event_id; return {species}
```
`index_day` sets `event["species"]` from that local cache. Only one image leaves,
only when the user taps Identify. No credentials, no account, no HMAC. This
**supersedes** the login/HMAC/CDN-upload approach in `nvts-auth-derivation.md`,
which is kept for reference and for the richer `/photoRecognition` API.

Try `/demo/bird2` too — likely a newer/better model variant; compare results.

## Status of the half-written sidecar
`server/browse_sidecar.py` on disk has uncommitted login+HMAC+background-B code
(now unnecessary for this simpler path). Rework it to the on-demand `/api/identify`
above and drop the background nvts loop. The viewer already renders `event.species`
and already has the Identify button — it just needs to call `/api/identify`.
