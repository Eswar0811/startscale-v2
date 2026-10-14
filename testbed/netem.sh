#!/usr/bin/env bash
# Shape registry egress to <mbit> Mbit/s (1000, 200, 50) on *every* interface (the registry sits on both the
# default bridge and the kind network; shaping only eth0 silently does nothing for node pulls).
# Registry must run with --cap-add NET_ADMIN (testbed/setup.sh does this).
set -euo pipefail
rate=${1:?mbit}
docker exec kind-registry sh -c "
  apk add --no-cache iproute2 >/dev/null 2>&1 || true
  for i in \$(ls /sys/class/net | grep -v '^lo\$'); do
    tc qdisc del dev \$i root 2>/dev/null || true
    tc qdisc add dev \$i root tbf rate ${rate}mbit burst 256kbit latency 400ms
  done"
echo "registry shaped to ${rate} Mbit/s"
