# Birdfy

Self-hosted capture, browsing, and species identification for the Birdfy smart
feeder (NI-8101 / Netvue). One container receives the feeder's uploads and
serves a viewer with on-demand bird ID — no cloud dependency, no account needed.

## Quick start

```sh
docker compose up -d
# then open http://localhost:8086 for the gallery, or use the API:
curl http://localhost:8086/api/days          # captured events
curl -X POST http://localhost:8086/api/identify/2026-11-05/<event_id>   # species
```

To get the feeder uploading here in the first place, see
[`router/README.md`](router/README.md) — then power-cycle the feeder.

## What's in the box

| Component | Path | What it does |
|-----------|------|-------------|
| **Server** | `server/` | Combined capture + browse + species ID in one container |
| **App** | `app/` | Android viewer — event gallery, video playback, ntfy push, species button |
| **Router** | `router/` | OpenWRT scripts for DNS redirect + TLS termination |
| **Docs** | `docs/` | Research notes, design docs, handoffs |

## Architecture

```
                  DNS (iptables DNAT)         TLS termination (nginx)
  ┌──────────┐  ──────────────────►  ┌──────────┐  ────────────►  ┌──────────────┐
  │  Birdfy  │     S3 PUT (443)      │  Router  │    HTTP PUT     │              │
  │  Feeder  │  ──────────────────►  │ (OpenWRT)│  ────────────►  │   birdfy     │
  └──────────┘                       └──────────┘                 │   :8085      │
                                                                  │   capture    │
  ┌──────────┐      browse API / identify                         │              │
  │  Viewer  │  ◄─────────────────────────────────────────────►   │   :8086      │
  │  App     │                                                    │   browse +   │
  └──────────┘      ntfy push                                     │   species ID │
       ▲        ◄──────────────────  ntfy  ◄──────────────────    └──────────────┘
       └─ notification
```

The feeder's S3 upload domains are DNS-redirected to the router, which
TLS-terminates (the feeder accepts any valid CA cert) and proxies to the capture
port. API and signaling traffic pass through to the cloud so the feeder stays
online. The viewer app talks to the browse port for events, media, and species.

## Server

One Python process, two ports, stdlib only (+ ffmpeg for MP4 remux):

- **`:8085` capture** — accepts the feeder's redirected S3 PUTs, writes
  JPEG/TS + `.meta` to disk, returns S3-compatible responses
- **`:8086` browse** — event API, media serving, HLS playlists, MP4 remux,
  on-demand species identification, ntfy push on new events

### Species identification

`POST /api/identify/<date>/<event_id>` sends the event thumbnail to a public
bird-ID endpoint (no auth, no account) and returns the species. Results are
cached in `species.json` and shown in the gallery.

There's also a paid recognition path (`server/nvts_client.py`) that uses your
Birdfy subscription for higher-quality results. It is a standalone module the
server does not call; see `docs/PROTOCOL.md` for its endpoints and auth.

### Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `TZ` | `UTC` | Timezone for day folders (e.g. `America/New_York`) |
| `CAPTURE_DIR` | `/data/captures` | Media storage |
| `CACHE_DIR` | `/cache` | MP4 cache + species cache |
| `CAPTURE_PORT` | `8085` | Capture listener |
| `BROWSE_PORT` | `8086` | Browse API listener |
| `MAX_BODY_MB` | `50` | Max upload size |
| `NTFY_URL` | — | ntfy server (enables push; run your own, not included) |
| `NTFY_TOPIC` | — | ntfy topic |
| `NTFY_TOKEN` | — | ntfy bearer token, if your server requires auth |
| `WATCH_INTERVAL` | `4` | Seconds between new-event scans |
| `DEMO_BIRD_URL` | `https://object-detect-bird-demo.netvue.co/demo/bird` | Bird ID endpoint |

## App

Android viewer built without Gradle (WebView + Java, `javac` → `d8` → `aapt2`
→ `apksigner`). Auto-updates via Obtainium from GitHub releases.

See `app/` for source.

## Getting the feeder to upload here

The server is standalone — but the feeder's cloud endpoints are baked into its
firmware, so capturing its uploads means intercepting them on your router. Those
scripts and their setup live in **[`router/README.md`](router/README.md)**; none
of it is part of the container.

## Key findings

- The feeder firmware (`*.vicohome.io`) and the app (`*.nvts.co`) use
  completely different backends
- No TLS certificate pinning — any valid CA cert works for interception
- The feeder queries 8.8.8.8 directly, bypassing DHCP DNS
- Only the S3 upload domains need redirecting; API/MQTT pass through so the
  feeder stays paired and functional
- There's a public, no-auth bird species ID endpoint that works on any JPEG

## Docs

| File | Topic |
|------|-------|
| `docs/ondemand-species-endpoint.md` | Free demo bird-ID endpoint (verified) |
| `docs/nvts-auth-derivation.md` | nvts HMAC-SHA256 auth scheme |
| `docs/recognition-paid-pipeline.md` | Paid recognition pipeline |
| `docs/birdfy-dev-menu.md` | Hidden developer menu in the official app |
| `router/README.md` | Router interception setup and live-stream blocking |
| `docs/PROTOCOL.md` | Endpoints, authentication, and stream formats |

## License

Interoperability research on hardware the author owns. Use at your own risk.
