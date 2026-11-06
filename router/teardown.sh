#!/bin/sh
# Birdfy local capture — teardown
# Run ON the OpenWRT router as root. Reverts all changes from setup.sh.
#
# Usage: ./teardown.sh <feeder-ip>

set -e

FEEDER_IP="${1:?Usage: $0 <feeder-ip>}"
ROUTER_IP="${ROUTER_IP:-192.168.1.1}"

echo "=== Birdfy capture teardown ==="

iptables -t nat -D PREROUTING -s "$FEEDER_IP" -p udp --dport 53 \
  -j DNAT --to-destination ${ROUTER_IP}:53 2>/dev/null && \
  echo "[-] Removed UDP DNS DNAT" || echo "[~] UDP DNS DNAT not found"
iptables -t nat -D PREROUTING -s "$FEEDER_IP" -p tcp --dport 53 \
  -j DNAT --to-destination ${ROUTER_IP}:53 2>/dev/null && \
  echo "[-] Removed TCP DNS DNAT" || echo "[~] TCP DNS DNAT not found"

rm -f /tmp/dnsmasq.d/birdfy-capture.conf
/etc/init.d/dnsmasq restart
echo "[-] dnsmasq override removed"

rm -f /etc/nginx/conf.d/birdfy-capture.conf
nginx -t && nginx -s reload
echo "[-] nginx capture proxy removed"

echo "=== Teardown complete. Feeder will reconnect to cloud on next DNS refresh. ==="
