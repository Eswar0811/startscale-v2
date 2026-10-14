#!/usr/bin/env bash
# Stops the collector if host free space drops below $1 GiB (default 12), so a full disk can't corrupt the VM again.
min=${1:-12}
while pgrep -f startscale.harness.collector >/dev/null; do
  free=$(df -g /System/Volumes/Data | awk 'NR==2{print $4}')
  if [ "$free" -lt "$min" ]; then pkill -f startscale.harness.collector; echo "DISK GUARD: ${free} GiB free < ${min}; collector stopped $(date)"; exit 1; fi
  sleep 20
done
echo "collector exited normally $(date)"
