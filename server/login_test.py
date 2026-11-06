#!/usr/bin/env python3
"""
First-run test for the paid-recognition pipeline. RUN THIS ON THE NAS, never behind
a TLS-intercepting proxy (your real credentials must not cross a MITM).

  NVS_EMAIL=you@example.com NVS_PASSWORD='...' CACHE_DIR=/tmp/nvs \
      python3 server/login_test.py [path/to/a/bird.jpg]

What it does, in order:
  1) Logs in  -> confirms the contract + prints which field names the server uses
     (so you can simplify nvts_client if they differ from token/ucid/udid/userID).
  2) Makes one signed call to prove the signature is accepted by the API.
  3) Probes the upload-apply route and prints the winner (pin it as
     NVS_UPLOAD_APPLY_PATH and record it in docs/recognition-paid-pipeline.md).
  4) If you pass an image path, runs the FULL identify (upload -> task -> poll)
     and prints the species.

Nothing here writes to the repo. Session/device caches land in CACHE_DIR.
Prints redact the token.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nvts_client as nv  # noqa: E402


def redact(sess):
    s = dict(sess)
    if s.get("token"):
        s["token"] = s["token"][:6] + "…(" + str(len(s["token"])) + " chars)"
    if s.get("refreshToken"):
        s["refreshToken"] = "…(" + str(len(s["refreshToken"])) + " chars)"
    return s


def main():
    if not (nv.NVS_EMAIL and nv.NVS_PASSWORD):
        print("Set NVS_EMAIL and NVS_PASSWORD first.")
        return 2
    print("== 1) LOGIN ==", nv.NVS_LOGIN_URL)
    sess = nv.login()
    print(json.dumps(redact(sess), indent=2))

    print("\n== 2) SIGNED API SANITY (any call; we just want 'not a signature error') ==")
    code, obj, _ = nv.api("POST", "photoRecognition/status", sess=sess, json_body={"taskIds": []})
    print("photoRecognition/status -> HTTP %s  %s" % (code, json.dumps(obj)[:300]))
    if code in (401, 403):
        print("  !! signature still rejected — capiv3 may want a different scheme; capture one app run.")

    print("\n== 3) DISCOVER UPLOAD-APPLY ROUTE ==")
    found = nv.discover_upload_apply(sess)
    if found:
        print("  -> WINNER:", found[0])
        print("  -> response:", json.dumps(found[1])[:400])
        print("  Pin it:  export NVS_UPLOAD_APPLY_PATH=%s" % found[0])
    else:
        print("  -> none matched; review the probe log above.")

    if len(sys.argv) > 1:
        img_path = sys.argv[1]
        print("\n== 4) FULL IDENTIFY on", img_path, "==")
        with open(img_path, "rb") as f:
            img = f.read()
        species, conf = nv.identify_paid(img)
        print("  species=%r confidence=%r" % (species, conf))
    else:
        print("\n(Pass an image path as arg to run the full upload->task->poll identify.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
