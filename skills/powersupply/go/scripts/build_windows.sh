#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
./scripts/sync_web.sh
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 "${GO:-go}" build \
  -trimpath -ldflags="-s -w -H windowsgui" \
  -o psu-desktop.exe ./cmd/psu-desktop
