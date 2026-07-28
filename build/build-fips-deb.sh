#!/usr/bin/env bash
# Build the FIPS module + helper .debs. The fips.so is distro-independent
# (built with enable-fips only, links just libc), so one deb build serves all
# deb releases; bookworm is the default builder.
#
#   build/build-fips-deb.sh [FIPSVER] [SUITE] [IMAGE]
set -euo pipefail

FIPSVER="${1:-3.1.2}"
SUITE="${2:-bookworm}"
IMAGE="${3:-debian:$SUITE}"
ARCH="${ARCH:-amd64}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/output/openssl-fips${FIPSVER}-upstream/deb"
mkdir -p "$OUT"

echo "== fips deb: openssl-fips${FIPSVER}-upstream on ${IMAGE} linux/${ARCH} =="
podman run --rm --platform "linux/${ARCH}" \
    -v "$REPO":/src:ro \
    -v "$OUT":/out \
    -e FIPSVER="$FIPSVER" -e CODENAME="$SUITE" -e FIPS_CERT="${FIPS_CERT:-}" \
    "$IMAGE" \
    bash /src/packaging/deb-fips/build-in-container.sh

echo "== artifacts in $OUT =="
ls -l "$OUT"
