#!/usr/bin/env bash
# Same app code at three layer sizes (~80 MB / ~600 MB / ~2.2 GB) so size is a clean variable.
# Pin and record digests in results/image_digests.txt for the data card.
set -euo pipefail
cd "$(dirname "$0")/../target-app"
for spec in "small:0" "medium:520" "large:2120"; do
  tag=${spec%%:*}; mb=${spec##*:}
  docker build -f - -t localhost:5000/startscale-target:$tag . <<EOF
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
RUN if [ $mb -gt 0 ]; then head -c ${mb}000000 /dev/urandom > /opt/ballast.bin; fi
ENV STARTUP_DELAY_MS=0 POD_NAME=local NODE_NAME=local
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000"]
EOF
  docker push localhost:5000/startscale-target:$tag
done
docker images --digests localhost:5000/startscale-target | tee ../results/image_digests.txt
