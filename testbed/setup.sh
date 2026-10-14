#!/usr/bin/env bash
# Phase 1 testbed bring-up. Requires docker, kind, kubectl.  Usage: testbed/setup.sh
set -euo pipefail
cd "$(dirname "$0")"
docker inspect kind-registry >/dev/null 2>&1 || docker run -d --restart=always -p 127.0.0.1:5000:5000 --name kind-registry registry:2
kind create cluster --name startscale --config kind-5node.yaml
docker network connect kind kind-registry 2>/dev/null || true
kubectl apply -f stress-ng-daemonset.yaml
echo "Build the three image sizes with: testbed/build_images.sh ; shape registry bandwidth with: testbed/netem.sh <mbit>"
