# Paid on-demand recognition — the full pipeline (derived 2026-11-04)

Goal: identify an arbitrary local snapshot using the user's **paid unlimited AI
recognition** entitlement, from our own sidecar, without the phone app.

Source: `com.birdfy.smarthome` v1.24.2 `libapp.so` (pulled live off this phone:
`pm path` → world-readable `base.apk` + `split_config.arm64_v8a.apk`), plus the
`my.birdfy.com` web bundle. Everything below is confirmed from those unless marked
**[needs 1 live capture]**.

## Auth (SOLVED — see nvts-auth-derivation.md)
Chained HMAC-SHA256 in `x-nvs-*` headers. **No Bearer anywhere.** The four signing
seeds (`token, ucid, udid, userID`) all come from the login response. The signer is
byte-verified against the web JS.

### Login call — EXACT (confirmed live 2026-11-05 via error-envelope probing)
```
POST https://localweb.netvue.co/v1/users/login
Headers:  content-type: application/json
          x-nvs-ucid: <ucid>     # required pre-auth; a dummy ("0000000000") is accepted
          x-nvs-udid: <udid>     # required pre-auth; client device UUID
Body:     {"username": <email, .toLowerCase().trim()>,
           "password": <md5(password) hex, lowercase>,   # NOT plaintext — md5 client-side
           "locale": "en",
           "platform": 0}        # int; 0 = web
```
Observed responses: bad creds → HTTP 400 `{"ret":5,"msg":"user or password error"}`;
missing fields → 422 `{"ret":1,"msg":"[locale may not be null, username , password may not be null]"}`;
missing id headers → 400 `{"ret":1,"msg":"[header x-nvs-udid may not be null, header x-nvs-ucid may not be null]"}`.
Success is `ret:0` with the token + seeds. (`POST /v1/users` is signup: needs
`username, password, email, locale` + `x-nvs-ucid`.) Email-OTP alt: `loginByCode`
sends `{username, code}` to the same unified login after a send-code call.
`platform:0` is the web value; the app may send a different int — either works.

## The models (all confirmed in libapp.so, json_serializable classes)
Recognition:
- `CreatePhotoRecognitionTaskResponse`, `PhotoRecognitionTaskResult`,
  `PhotoRecognitionSubject`, `PhotoRecognitionCandidate` (`speciesId, commonName,
  scientificName, confidence`), `PhotoRecognitionBoundingBox`,
  `PhotoRecognitionImageInput`, `PhotoRecognitionLocationInfo/Point`,
  `GetPhotoRecognitionHistoryResponse`, `PhotoRecognitionHistoryRecord`,
  `PhotoRecognitionError`, `ManualAiRecognitionRequest/Response`, `AiRecognitionResult`.
- Request fields: `fileKey, captureTime, longitude, latitude, locationLabel`.
- Result fields: `taskId(s), subjectId, speciesId, boundingBox, candidates[]`.

CDN / upload:
- `CDNResourceUrlRequest`, `CdnJwtToken`, `buildAwsPublicCdnUrl`, `bucketKey`↔`fileKey`,
  `backupFileKeys`, `generateSignedAvatarUrlWithBucketKey`, `_captureImageBucketKey`.
- Upload (two-phase): `applyForUploadAttachmentInfo` → `AttachmentUploadMetadata` /
  `AttachmentUploadResponse` / `FileUploadResponse`, then PUT bytes, then complete.
  Response carries: `presignedUrl, method, headers, contentType, fileKey/bucketKey,
  expireAt/expiresIn, attachmentId`. (`presignedUrl` string confirmed in the binary.)

## Hosts
- login/auth: `https://localweb.netvue.co/v1/`
- recognition (central API v3): `https://capiv3.nvts.co` (prod; `test-centralapi.nvts.co`
  exists too; web app also uses `capiv3.netvue.co`). API-Gateway-fronted — masks
  everything unsigned as `403 {"message":"Missing Authentication Token"}`.
- events + pre-computed species: `https://centralapi.nvts.co` (CloudFront)
- image CDN (read): `cdn-nvs-<region>-<purpose>.netvue.co` (e.g.
  `cdn-nvs-us-east-1-community.netvue.co`); feeder capture bucket (the one we DNS-
  redirect to the NAS): `nvs-us-east-1-motioncapture...s3.amazonaws.com`.
- **species reference images**: `https://resource.netvue.com/server-resource/bird-images/<speciesKey>.jpg`
  (`<speciesKey>` is the 5-digit `key` in a result, e.g. `04370.jpg` = Striated Heron).
  Free, no auth — nice for showing a thumbnail next to an ID.

## End-to-end the sidecar would run
1. `POST localweb.netvue.co/v1/users/login` (md5 password + ucid/udid headers) → `{token,ucid,udid,userID}`.
2. `applyForUploadAttachmentInfo` (signed x-nvs) → `{presignedUrl, method, headers, fileKey}`.  **[needs 1 live capture: exact path + body/response JSON]**
3. `PUT`/`POST` the thumbnail bytes to `presignedUrl` with the given `method`+`headers`.
4. (maybe) complete-upload call. **[needs 1 live capture]**
5. `POST capiv3.nvts.co/photoRecognition/tasks` (signed x-nvs)
   `{fileKey, captureTime, longitude, latitude, locationLabel}` → `{task:{taskId}}`.
   (Paths `/photoRecognition/tasks|status|history` confirmed earlier from a real
   Create run in the dev-menu debug page.)
6. Poll `POST capiv3.nvts.co/photoRecognition/status {taskIds:[...]}` →
   `subjects[].candidates[0].commonName`.

## The only gaps (both need ONE authenticated live run)
- Exact `applyForUploadAttachmentInfo` HTTP path + request/response JSON (route is
  runtime-assembled, not a static string).
- Confirm capiv3 recognition calls are x-nvs-signed (near-certain: same shared app
  API client/interceptor) vs. some capiv3-specific scheme.

### How to close them (pick one)
- **Easiest:** log in from the sidecar with the user's account (we have it), then
  empirically call `applyForUploadAttachmentInfo` and read the response. Pure CLI.
- **Or:** on-device capture of one real run via the dev-menu **Photo Recognition
  Debug** page (`birdfy://developer_debug` → 拍鸟识别 → 接口调试) with mitmproxy +
  a user-trusted CA (works only if the app isn't cert-pinned; the router MITM failed
  only because of a *mismatched* self-signed cert, not necessarily pinning).

## Fallback already shipped
The free, no-auth demo endpoint (`object-detect-bird-demo.netvue.co/demo/bird`) is
already wired as the on-demand identifier (see ondemand-species-endpoint.md). This
paid pipeline is the resilient upgrade — better model, your entitlement, not a demo
widget that can vanish.
