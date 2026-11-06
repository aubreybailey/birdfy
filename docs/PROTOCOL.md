# Birdfy feeder — endpoints, authentication, and stream formats

Reference for the NI-8101 (Netvue/Birdfy) feeder as observed on the wire. Every
endpoint listed here is settable via environment variable; see `.env.example`
for the full list in one place.

Each claim below is marked **confirmed** (observed live or recovered from the
shipped JS/APK) or **unverified** (inferred, not yet proven).

## Two separate backends

The single most useful fact about this device: **the feeder firmware and the
phone/web app talk to completely different clouds.** Intercepting one tells you
nothing about the other.

| Plane | Hosts | Used by |
|-------|-------|---------|
| Firmware / device | `api-us.vicohome.io` | The feeder itself |
| App / account | `*.nvts.co`, `*.netvue.co` | Phone app, my.birdfy.com |
| Media upload | `nvs-*.s3.amazonaws.com` | The feeder's event uploads |

The app also fetches its own endpoint list at runtime from
`https://resource.netvue.com/app/res/birdfy/domains.json`, with a hardcoded
fallback suffix of `netvue.co` — so host names can move without an app update.
**Confirmed** (app bundle).

---

# 1. Feeder → cloud: the capture upload

This is the only plane you need to intercept to self-host captures.

## Hosts

```
nvs-us-east-1-motioncapture.s3.amazonaws.com    # stills
nvs-us-east-1-videomotion.s3.amazonaws.com      # video segments
```

**Confirmed** — these are the two hostnames `router/setup.sh` overrides, and
redirecting only these is sufficient. API and MQTT pass through untouched and
the feeder stays paired and online.

## Request shape

Plain `PUT` (occasionally `POST`) over TLS on 443, one object per request:

```
PUT /<device_id>/<camera_id>/<event_id>/image.jpg
PUT /<device_id>/<camera_id>/<event_id>/slice_<size>_<seq>_<flag>.ts
```

The last four path segments are the addressing scheme the capture server relies
on: `event_id` is the second-to-last segment, `camera_id` the third-to-last,
`device_id` the fourth-to-last. An event is therefore one `image.jpg` plus N
`.ts` segments sharing an `event_id`. **Confirmed** (`server.py:index_day`,
built against real captures).

## Authentication — and why interception works

Three properties, all **confirmed** by packet capture on the router:

- **No TLS certificate pinning.** The feeder accepts any certificate from a CA
  in its trust store, so a standard public cert for the S3 hostnames is enough
  to terminate its uploads. This is what makes the whole project possible.
- **No hostname-to-certificate binding beyond normal TLS.** A valid cert for a
  different name is presented and accepted.
- **DNS is not trusted to the DHCP server.** The feeder queries `8.8.8.8`
  directly, so a DNS override alone does nothing — its port-53 traffic has to be
  DNAT'd back to a resolver you control.

**Unverified: what credential the feeder puts on the PUT itself.** The capture
server never checks, and the recorded `.meta` keeps only `time`, `method`,
`path`, `host`, `content-type` and `size` — not the `Authorization` header or
the query string. So whether the feeder uses AWS SigV4 headers or a presigned
URL is still open. The capture server accepts any PUT and replies with an
S3-shaped `200` plus a synthetic ETag, which the feeder accepts.

To settle it, log the full request line and `Authorization` header in
`CaptureHandler._save`, trigger one event, then revert. A signature in the query
string means presigned; an `AWS4-HMAC-SHA256` header means SigV4.

## Stream formats

| What | Format | Notes |
|------|--------|-------|
| Thumbnail | JPEG, one `image.jpg` per event | What the species endpoint is given |
| Video | **MPEG-TS** segments, `.ts` | ~2 s each; sequence number is the middle field of `slice_<size>_<seq>_<flag>` |
| Live view | **Agora RTC over WebRTC** | UDP media + STUN/TURN on 3478/5349 |

**Confirmed.** Notably there is **no RTSP and no ONVIF** — port 554 is closed on
the camera, so the usual NVR integrations do not apply. Live video is only
reachable through Agora's SDK, which is why this project captures motion events
rather than pulling a continuous stream.

The feeder uploads TS segments, never a container file. This server stores them
as-is and derives playable media on request: `ffmpeg` remuxes the ordered
segments into MP4 (`/api/event/<date>/<id>/video.mp4`), and an HLS playlist is
generated for streaming (`/api/event/<date>/<id>/playlist.m3u8`).

The app exposes an "Add RTMP" push feature gated per-device by
`DeviceRTMPStreamingAbility`. **Unverified for the NI-8101** — if supported, it
would allow a continuous push to a local RTMP server and would be a much better
path than event capture.

---

# 2. App → cloud: account and event API

Only needed for the optional paid recognition path. Not required to capture.

## Endpoints

| Purpose | Endpoint |
|---------|----------|
| Login | `https://localweb.netvue.co/v1/users/login` |
| Events / devices | `https://centralapi.nvts.co` |
| Recognition tasks | `https://capiv3.nvts.co` |

`localweb.netvue.co` and `localweb.nvts.co` both resolve; the base is **not**
region-prefixed (`us-localweb.*` does not resolve). `capiv3.nvts.co` sits behind
AWS API Gateway and masks every unauthenticated path as
`403 MissingAuthenticationToken`, so it will not reveal routes anonymously.
**Confirmed** by DNS plus the web bundle.

## Authentication: chained HMAC-SHA256

**There is no Bearer auth anywhere in nvts.** The only `Authorization: Bearer`
strings in the web app belong to an unused AWS SDK signer and the Stripe
publishable key. Signed calls instead carry `x-nvs-*` headers.

The signature is five chained HMAC-SHA256 rounds, each round's hex digest
becoming the next round's key:

```python
def sign(token, ucid, udid, userid, ts):   # ts = Date.now() in ms, as a string
    key = ("nvs1" + token).encode()
    for v in [ucid, udid, userid, ts, "nvs1_request"]:
        key = hmac.new(key, v.encode(), hashlib.sha256).hexdigest().encode()
    return key.decode()
```

Headers on a signed request:

```
x-nvs-version: {"signature":2}
x-nvs-ucid:    <ucid>
x-nvs-udid:    <udid>
x-nvs-userid:  <userID>
x-nvs-time:    <ms timestamp, same value passed to sign()>
x-nvs-signature: <sign(...)>
```

**Confirmed two ways:** the signer was deminified out of the `my.birdfy.com`
bundle and reimplemented byte-identically in Python, and an unsigned request to
`centralapi.nvts.co` returns `403 {"msg":"ERR_USER_SIGNATURE_INVALID","ret":73}`
— the server names the signature, not a missing token.

All four signing seeds (`token`, `ucid`, `udid`, `userID`) come straight from
the login response, and `udid` is server-issued rather than client-generated, so
a single login yields everything needed to sign. The client signs only when
`x-nvs-version` is present and the token is non-empty.

Password login sends the email and password over TLS; there is also a
passwordless flow (request a code, then `loginByCode`). The response carries
`token`, `ucid`, `udid`, `userID`, `refreshToken` and `expiresIn`.
**Unverified:** the exact refresh-token endpoint and body.

Species on the account API live at `aiLabels[].commonName` on
`GET /devices/{serialNumber}/events`. **Confirmed** (web JS).

---

# 3. Species identification: public, no auth

```
POST https://object-detect-bird-demo.netvue.co/demo/bird
Content-Type: image/jpeg
Body: raw JPEG bytes
```

No authentication, no account, no signing. **Confirmed live.** `/demo/bird2`
exists and returned identical results.

```json
{"data":[
  {"name":"bird","objects":[
    {"left":0.47,"top":0.19,"width":0.37,"height":0.65,"confidence":30,
     "desc":[{"name":"Striated Heron","confidence":30}],"key":"04370"}]},
  {"name":"squirrel","objects":[]}]}
```

Species is `data[name=="bird"].objects[].desc[].name`, taking the highest
`desc.confidence`, with a normalized bounding box and a stable species `key`.
Results group by category, so `objects[]` is empty when nothing is detected.
A non-JPEG body returns `400 {"ret":9,...unsupported image format}`.

This is what `POST /api/identify/<date>/<event_id>` uses. One image leaves the
network, only when asked, and the result is cached in `species.json`.

---

## Verifying any of this yourself

Everything above came from the router, not from the device. Passive capture
scoped to the feeder is enough for most of it:

```sh
tcpdump -ni any host <feeder-ip> and \(port 443 or port 53\) -c 200
```

That yields the DNS names it resolves, the hosts and ports it holds open, and
the TLS SNI in its ClientHellos. Keep captures scoped to the feeder's address,
and revert any DNS or firewall change you make while testing.
