#!/usr/bin/env bash
# Build the FIPS module + helper .rpms. The fips.so is distro-independent
# (enable-fips only, links just libc); el9 is the default builder.
#
#   build/build-fips-rpm.sh [FIPSVER] [EL] [IMAGE]
set -euo pipefail

FIPSVER="${1:-3.1.2}"
EL="${2:-9}"
IMAGE="${3:-almalinux:$EL}"
ARCH="${ARCH:-amd64}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/output/openssl-fips${FIPSVER}-upstream/rpm"
mkdir -p "$OUT"

echo "== fips rpm: openssl-fips${FIPSVER}-upstream on ${IMAGE} linux/${ARCH} =="
podman run --rm --platform "linux/${ARCH}" \
    -v "$REPO":/src:ro \
    -v "$OUT":/out \
    -e FIPSVER="$FIPSVER" -e FIPS_CERT="${FIPS_CERT:-}" \
    "$IMAGE" \
    bash /src/packaging/rpm-fips/build-in-container.sh

echo "== artifacts in $OUT =="
ls -l "$OUT"
