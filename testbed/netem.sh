#!/usr/bin/env bash
# Shape registry egress to <mbit> Mbit/s (1000, 200, 50). Run on the host where the registry container lives.
set -euo pipefail
rate=${1:?mbit}
docker exec kind-registry sh -c "apk add --no-cache iproute2 >/dev/null 2>&1 || true; tc qdisc del dev eth0 root 2>/dev/null || true; tc qdisc add dev eth0 root tbf rate ${rate}mbit burst 32kbit latency 400ms"
echo "registry shaped to ${rate} Mbit/s"
