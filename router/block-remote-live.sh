#!/bin/sh
# block-remote-live.sh — stop the Birdfy feeder serving its live video to nvts/Agora
# on remote demand. Runs ON the OpenWRT router (fw3). Matches the feeder by MAC so
# it survives DHCP IP changes. The local S3 capture (feeder -> router nginx) is
# intra-LAN and is NOT affected by these wan-dest rules.
#
#   MODE=stream  (default) block the live/WebRTC path (all UDP to WAN + STUN/TURN
#                TCP 3478/5349). Keeps the feeder's nvts control channel (TCP 443)
#                up, so it stays "online" and keeps uploading to the local capture.
#   MODE=full    block ALL feeder WAN access (most thorough; "don't talk to them at
#                all"). Verify a capture still lands afterwards — if the feeder needs
#                its cloud control channel to upload, revert to stream.
#
# Apply from a workstation (FEEDER_MAC is required):
#   ssh root@<router> 'FEEDER_MAC=aa:bb:cc:dd:ee:ff sh -s' < block-remote-live.sh
#   ssh root@<router> 'FEEDER_MAC=aa:bb:cc:dd:ee:ff MODE=full sh -s' < block-remote-live.sh
# Find it on the router with: cat /tmp/dhcp.leases
set -e
FEEDER_MAC="${FEEDER_MAC:?set FEEDER_MAC to your feeder's MAC (see /tmp/dhcp.leases)}"
MODE="${MODE:-stream}"

# remove any prior birdfy-* rules first (idempotent)
while idx=$(uci show firewall 2>/dev/null | sed -n "s/firewall\.@rule\[\([0-9]*\)\]\.name='birdfy-[^']*'/\1/p" | head -1); [ -n "$idx" ]; do
  uci delete "firewall.@rule[$idx]"
done

newrule() { uci add firewall rule >/dev/null; uci set firewall.@rule[-1].name="$1"
  uci set firewall.@rule[-1].src='lan'; uci set firewall.@rule[-1].src_mac="$FEEDER_MAC"
  uci set firewall.@rule[-1].dest='wan'; }

if [ "$MODE" = "full" ]; then
  newrule birdfy-wan-block; uci set firewall.@rule[-1].proto='all'
  uci set firewall.@rule[-1].target='DROP'
else
  newrule birdfy-live-udp;  uci set firewall.@rule[-1].proto='udp'
  uci set firewall.@rule[-1].target='REJECT'
  newrule birdfy-live-turn; uci set firewall.@rule[-1].proto='tcp'
  uci set firewall.@rule[-1].dest_port='3478 5349'
  uci set firewall.@rule[-1].target='REJECT'
fi
uci commit firewall
/etc/init.d/firewall reload >/dev/null 2>&1 || fw3 reload >/dev/null 2>&1
echo "birdfy: applied MODE=$MODE block for feeder $FEEDER_MAC"
