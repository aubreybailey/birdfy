#!/bin/sh
# unblock-remote-live.sh — remove all birdfy-* live-stream firewall rules (full revert).
# Apply:  ssh root@<router> 'sh -s' < unblock-remote-live.sh
set -e
while idx=$(uci show firewall 2>/dev/null | sed -n "s/firewall\.@rule\[\([0-9]*\)\]\.name='birdfy-[^']*'/\1/p" | head -1); [ -n "$idx" ]; do
  uci delete "firewall.@rule[$idx]"
done
uci commit firewall
/etc/init.d/firewall reload >/dev/null 2>&1 || fw3 reload >/dev/null 2>&1
echo "birdfy: removed all birdfy-* firewall rules"
