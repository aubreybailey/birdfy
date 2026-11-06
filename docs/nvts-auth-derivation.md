# nvts auth — derived from the APK + web JS (for sidecar self-login)

Goal: let the browse sidecar authenticate itself (email+password it holds as
secrets) and mint/refresh its own token, instead of extracting an encrypted
token from browser/app storage (phone app is non-debuggable; run-as blocked).

## Auth model (CONFIRMED TWO WAYS, 2026-11-04)
All signed API calls use **chained HMAC-SHA256** in `x-nvs-*` headers. **There is
NO Bearer auth anywhere for nvts** — the only `Authorization: Bearer` strings in the
web app are AWS SDK-JS's built-in generic signer (unused) and the Stripe
publishable key.

Proof 1 — live server error (unsigned request):
`GET https://centralapi.nvts.co/devices/{sn}/events` → `403 {"msg":"ERR_USER_SIGNATURE_INVALID","ret":73}`.
The server names the *signature*, not a missing token.

Proof 2 — exact signer recovered from the web bundle (`my.birdfy.com`, bundle with
the request interceptor). Deminified:
```js
// p(token, ucid, udid, userid, time)
p = function(e,t,r,i,n){
  var a="sha256", o="nvs1"+e;
  var c=createHmac(a,o).update(t).digest("hex");   // key=nvs1+token, msg=ucid
  var s=createHmac(a,c).update(r).digest("hex");    // msg=udid
  var u=createHmac(a,s).update(i).digest("hex");    // msg=userid
  var d=createHmac(a,u).update(n).digest("hex");    // msg=time (Date.now() ms string)
  return createHmac(a,d).update("nvs1_request").digest("hex");
};
// request interceptor (only signs when x-nvs-version is present + token non-empty):
//   headers["x-nvs-ucid"]=store.ucid; headers["x-nvs-udid"]=store.udid;
//   if (headers["x-nvs-version"]=='{"signature":2}' && store.token.length>0){
//     n=store.userID.toString(); a=Date.now().toString();
//     headers["x-nvs-userid"]=n; headers["x-nvs-time"]=a;
//     headers["x-nvs-signature"]=p(store.token,ucid,udid,n,a);
//   }
```
Python (verified byte-identical to the JS above):
```python
def sign(token, ucid, udid, userid, ts):   # ts = Date.now() ms, str
    key = ("nvs1" + token).encode()
    for v in [ucid, udid, userid, ts, "nvs1_request"]:
        key = hmac.new(key, v.encode(), hashlib.sha256).hexdigest().encode()
    return key.decode()
# headers: x-nvs-version {"signature":2}, x-nvs-ucid, x-nvs-udid,
#          x-nvs-userid, x-nvs-time=ts, x-nvs-signature=sign(...)
```
**The four signing seeds (`token, ucid, udid, userID`) all come straight from the
login response** (web store writes `token=e.token; ucid=e.ucid; udid=e.udid;
userID=e.userID`). `udid` is server-issued, not client-generated — so one login
gives everything needed to sign.

## Login (host CONFIRMED by DNS + web bundle, 2026-11-04)
- Base: **`https://localweb.netvue.co/v1/`** — bare, **NOT region-prefixed**.
  `localweb.netvue.co` (3.210.187.105) and `localweb.nvts.co` (100.50.228.148)
  both resolve; `us-localweb.*` / `api.netvue.co` do NOT resolve. Earlier
  region-prefix guess was wrong.
- Two flows in the web app:
  - password: `loginWithPassword` (username/email + password, plaintext over TLS),
  - passwordless: request code `{action:"login", channel:"email", target:<email>}`
    then `loginByCode({username:<email>, code:<otp>})`.
- Response returns `token` (the signer seed), `ucid`, `udid`, `userID`,
  `refreshToken`, `expiresIn`. (Some models also name `accessToken`; the live store
  key is `token`.)
- Refresh via `refreshToken` when `expiresIn` elapses.

## Event/species API (CONFIRMED, from web JS)
`GET https://centralapi.nvts.co/devices/{serialNumber}/events`
 params: `limit, startKey, startTime, endTime, ignoreAiLabels=false, reverse=true, filterBy`
 (also `/events/bydate/{YYYY-MM-DD}?endTime&limit&tz&ignoreAiLabels`)
 → `events[]`, species in **`aiLabels[].commonName`**. serialNumber = device SN in path.

## Known constants / hosts (web bundle baseURLs, 2026-11-04)
- auth/login: `https://localweb.netvue.co/v1/`
- events/devices: `https://centralapi.nvts.co` (CloudFront-fronted)
- central API v3 (recognition tasks etc.): `https://capiv3.netvue.co/`
  (note `.netvue.co` — the web app's host; `capiv3.nvts.co` also exists, AWS
  API-Gateway-fronted, and masks every unmatched/unauthed path as
  `403 MissingAuthenticationToken`, so it won't reveal routes anonymously)
- also seen: `localapi2.nvts.co/`, `api2.netvue.co/`
- `ucid`, `udid`, `userID` and the device serial all come from your own login
  response and the device path — there are no shared constants to hardcode.

## Residual unknowns (confirm on first real login)
- Exact `/v1/` path for password login vs. the OTP request/verify pair.
- Whether `/login` itself is signed (likely a lighter/unsigned pre-auth call).
- Exact refresh-token endpoint + body.
The signer and the seed provenance are fully solved; only the login wire shape
remains, and that needs one real login (we have the user's account) to pin down.
