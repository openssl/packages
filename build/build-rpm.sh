#!/usr/bin/env bash
# Host-side driver: build openssl<STREAM>-upstream as .rpm for ONE EL release
# inside its own container using podman.
#
#   build/build-rpm.sh [STREAM] [VERSION] [EL] [IMAGE]
#   build/build-rpm.sh 4.0 4.0.1 9              # IMAGE defaults to almalinux:<el>
#   build/build-rpm.sh 4.0 4.0.1 10 almalinux:10
set -euo pipefail

STREAM="${1:-4.0}"
VERSION="${2:-4.0.1}"
EL="${3:-9}"
IMAGE="${4:-almalinux:$EL}"
# amd64 (native here) or arm64 (emulated locally, native on aarch64 hosts).
ARCH="${ARCH:-amd64}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/output/openssl${STREAM}-upstream/rpm/el$EL"
mkdir -p "$OUT"

echo "== rpm: openssl${STREAM}-upstream ${VERSION} on ${IMAGE} linux/${ARCH} (el${EL}) =="
podman run --rm --platform "linux/${ARCH}" \
    -v "$REPO":/src:ro \
    -v "$OUT":/out \
    -e STREAM="$STREAM" -e VERSION="$VERSION" \
    -e RUN_TESTS="${RUN_TESTS:-0}" \
    "$IMAGE" \
    bash /src/packaging/rpm/build-in-container.sh

echo "== artifacts in $OUT =="
ls -l "$OUT"
