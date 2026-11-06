#!/bin/sh
# Birdfy local capture — router setup
# Run ON the OpenWRT router as root. Redirects feeder's S3 uploads
# to a local capture server while keeping API/MQTT on the real cloud.
#
# Usage: ./setup.sh <feeder-ip> <capture-server-ip>
# Example: ./setup.sh 192.168.1.50 192.168.1.10
# Override the router's own address with ROUTER_IP= if it is not 192.168.1.1.

set -e

FEEDER_IP="${1:?Usage: $0 <feeder-ip> <capture-server-ip>}"
CAPTURE_IP="${2:?Usage: $0 <feeder-ip> <capture-server-ip>}"
# The router's own LAN address, where its dnsmasq and nginx listen.
ROUTER_IP="${ROUTER_IP:-192.168.1.1}"
CONF="/tmp/dnsmasq.d/birdfy-capture.conf"
# Any cert the feeder's CA store trusts works -- it does not pin. Point these at
# your own fullchain and key.
SSL_CERT="${SSL_CERT:?set SSL_CERT to your fullchain cert path}"
SSL_KEY="${SSL_KEY:?set SSL_KEY to your private key path}"

echo "=== Birdfy capture setup ==="
echo "Feeder:  $FEEDER_IP"
echo "Capture: $CAPTURE_IP"

# Step 1: redirect feeder's DNS (it queries 8.8.8.8 directly)
iptables -t nat -C PREROUTING -s "$FEEDER_IP" -p udp --dport 53 \
  -j DNAT --to-destination ${ROUTER_IP}:53 2>/dev/null || \
  iptables -t nat -I PREROUTING -s "$FEEDER_IP" -p udp --dport 53 \
    -j DNAT --to-destination ${ROUTER_IP}:53
iptables -t nat -C PREROUTING -s "$FEEDER_IP" -p tcp --dport 53 \
  -j DNAT --to-destination ${ROUTER_IP}:53 2>/dev/null || \
  iptables -t nat -I PREROUTING -s "$FEEDER_IP" -p tcp --dport 53 \
    -j DNAT --to-destination ${ROUTER_IP}:53
echo "[+] DNS DNAT: feeder -> router dnsmasq"

# Step 2: override S3 upload domains -> router (nginx TLS terminates)
cat > "$CONF" <<EOF
# Birdfy feeder S3 upload intercept
address=/nvs-us-east-1-motioncapture.s3.amazonaws.com/${ROUTER_IP}
address=/nvs-us-east-1-videomotion.s3.amazonaws.com/${ROUTER_IP}
EOF
/etc/init.d/dnsmasq restart
echo "[+] dnsmasq: S3 domains -> router"

# Step 3: nginx upstream for the capture server
cat > /etc/nginx/conf.d/birdfy-capture.conf <<EOF
server {
    listen 443 ssl;
    server_name nvs-us-east-1-motioncapture.s3.amazonaws.com
                nvs-us-east-1-videomotion.s3.amazonaws.com;

    ssl_certificate     ${SSL_CERT};
    ssl_certificate_key ${SSL_KEY};

    client_max_body_size 50m;

    location / {
        proxy_pass http://${CAPTURE_IP}:8085;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_request_buffering off;
    }
}
EOF
nginx -t && nginx -s reload
echo "[+] nginx: TLS proxy -> capture:8085"

echo "=== Setup complete. Reboot the feeder to activate. ==="
