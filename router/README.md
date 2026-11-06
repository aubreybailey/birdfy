# Router setup (OpenWRT)

**The server does not need any of this.** `docker compose up -d` gives you a
working capture + browse service, and the viewer app talks to it directly.

The router config exists for one reason: the feeder's cloud endpoints are baked
into its firmware. You can't point it at your own server, so to capture its
uploads you have to intercept them in flight. That's what these scripts do, and
it all happens on the router — nothing here ships in the container.

If you only want to browse captures you already have, or you're replacing the
feeder's uploads some other way, skip this directory entirely.

## What makes interception possible

Three properties of the feeder, found by packet-capturing it on the router
(see `../docs/PROTOCOL.md`):

- It queries `8.8.8.8` directly, ignoring the DHCP-advertised DNS server — so
  overriding DNS requires forcing its queries back to the router.
- It does **not** pin TLS certificates. Any cert from a CA it trusts works, so
  the router can terminate TLS for the S3 upload hosts.
- Its uploads and its control plane are different hosts. Only the S3 upload
  domains need redirecting; API and MQTT pass through to the real cloud, so the
  feeder stays paired, online, and functional.

## Porting to a non-OpenWRT router

The scripts are OpenWRT-flavored (`uci`, `/etc/init.d/dnsmasq`, fw3), but only
three mechanisms actually matter, and every router OS has an equivalent:

1. Force the feeder's port-53 traffic to a resolver you control (DNAT).
2. Answer the two S3 upload hostnames with your own address (a DNS override).
3. Terminate TLS for those hostnames with a cert the feeder trusts, and proxy
   to the capture port.

On NixOS, nftables plus `services.dnsmasq` and an nginx virtualHost get you the
same result declaratively.

## Site-specific values

These scripts assume a stock OpenWRT layout. Adjust for your network:

Nothing is hardcoded to one network — each script takes what it needs as an
argument or environment variable:

| Variable | Used by | Required? |
|----------|---------|-----------|
| `SSL_CERT` / `SSL_KEY` | `setup.sh` | **Yes** — your fullchain and private key |
| `FEEDER_MAC` | `block-remote-live.sh` | **Yes** — find it in `/tmp/dhcp.leases` |
| `ROUTER_IP` | `setup.sh`, `teardown.sh` | No, defaults to `192.168.1.1` |

The feeder and capture-server addresses are positional arguments to `setup.sh`.

## Capture interception

```sh
scp setup.sh root@<router>:/tmp/
ssh root@<router> "SSL_CERT=/etc/acme/example/fullchain.cer \
                  SSL_KEY=/etc/acme/example/example.key \
                  sh /tmp/setup.sh <feeder-ip> <capture-server-ip>"
```

Three things happen:

1. **iptables DNAT** forces the feeder's port-53 traffic (UDP and TCP) to the
   router's own dnsmasq, defeating its hardcoded `8.8.8.8`.
2. **dnsmasq overrides** resolve the two S3 upload domains to the router.
3. **nginx** listens on 443 for those hostnames, terminates TLS with a real
   cert, and proxies to `<capture-server>:8085`.

Power-cycle the feeder afterwards so it re-resolves DNS.

Revert with `teardown.sh <feeder-ip>`. The feeder returns to the real cloud on
its next DNS refresh.

## Blocking the remote live stream

Separate, optional, and independent of capture. This stops the feeder serving
live video to Netvue/Agora on remote demand (the **Live** button in the app and
on my.birdfy.com), making the feed LAN-only.

Live view uses Agora RTC: UDP media plus STUN/TURN on 3478/5349. The script adds
fw3 rules rejecting the feeder's **WAN-bound** traffic on those paths. Because
the rules only match wan-dest traffic, local capture — feeder → router nginx →
server, entirely intra-LAN — is unaffected.

```sh
# stream mode (default): block WAN UDP + STUN/TURN
ssh root@<router> 'FEEDER_MAC=aa:bb:cc:dd:ee:ff sh -s' < block-remote-live.sh

# full mode: block all feeder WAN access
ssh root@<router> 'FEEDER_MAC=aa:bb:cc:dd:ee:ff MODE=full sh -s' < block-remote-live.sh

# revert
ssh root@<router> 'sh -s' < unblock-remote-live.sh
```

**stream** deliberately leaves the feeder's control channel (TCP 443) up, so the
device stays "online" and keeps uploading. **full** blocks everything, which is
more thorough but riskier: if the feeder needs its cloud control channel to
decide to upload, local capture stops. Verify a capture still lands, and fall
back to stream if not.

Rules persist across reboots via `uci commit`. Reverting removes every
`birdfy-*` rule.

### If live still works after stream mode

Agora can fall back to a TCP relay on 443, which stream mode leaves open for the
control channel. Escalate to `MODE=full`, then confirm capture still works.

## Verify

- **Capture works:** wave at the feeder; a new event should appear within
  seconds at `http://<capture-server>:8086/api/days`.
- **Remote live fails:** press **Live** in the app. It should spin or fail.
- **Rules are live:** on the router, `iptables -L zone_lan_forward -vn | grep -i <feeder-mac-prefix>`
  shows the REJECT rules, and their counters rise when live is attempted.

## Notes

- Give the feeder a static DHCP lease so its IP is stable. The firewall match is
  by MAC, so this is tidiness rather than a requirement.
- **`setup.sh` does not survive a router reboot**, by design — it makes no
  permanent changes to your router. The nginx block lands in
  `/etc/nginx/conf.d/` and persists, but the dnsmasq override goes to
  `/tmp/dnsmasq.d/` (tmpfs) and the DNS redirect is a runtime `iptables -I` with
  no `uci` entry. After a restart the feeder simply goes back to uploading to
  the real cloud, so re-run `setup.sh` when you want capture back. Whether to
  make any of it permanent is yours to decide, in your own router config.
- The live-stream block is the exception: it uses `uci commit`, so it does
  persist, and `unblock-remote-live.sh` fully reverts it.
