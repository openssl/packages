#!/usr/bin/env bash
# Host-side driver: build openssl<STREAM>-upstream as .deb for ONE deb release
# inside its own container using podman.
#
#   build/build-deb.sh [STREAM] [VERSION] [SUITE] [IMAGE]
#   build/build-deb.sh 4.0 4.0.1 bookworm            # IMAGE defaults to debian:<suite>
#   build/build-deb.sh 4.0 4.0.1 jammy ubuntu:22.04  # Ubuntu target
set -euo pipefail

STREAM="${1:-4.0}"
VERSION="${2:-4.0.1}"
SUITE="${3:-bookworm}"
IMAGE="${4:-debian:$SUITE}"
# amd64 (native here) or arm64 (emulated locally, native on aarch64 hosts).
ARCH="${ARCH:-amd64}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/output/openssl${STREAM}-upstream/deb/$SUITE"
mkdir -p "$OUT"

echo "== deb: openssl${STREAM}-upstream ${VERSION} on ${IMAGE} linux/${ARCH} (suite ${SUITE}) =="
podman run --rm --platform "linux/${ARCH}" \
    -v "$REPO":/src:ro \
    -v "$OUT":/out \
    -e STREAM="$STREAM" -e VERSION="$VERSION" -e CODENAME="$SUITE" \
    -e RUN_TESTS="${RUN_TESTS:-0}" -e JOBS="${JOBS:-}" \
    -e REVISION="${REVISION:-1}" -e SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-}" \
    "$IMAGE" \
    bash /src/packaging/deb/build-in-container.sh

echo "== artifacts in $OUT =="
ls -l "$OUT"
