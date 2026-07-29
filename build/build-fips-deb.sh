#!/usr/bin/env bash
# Build the FIPS module .debs. The fips.so links only libc, so one build serves
# every deb release — but it inherits a glibc symbol-version floor from whatever
# built it, and glibc is compatible only forwards. The builder must therefore be
# the OLDEST glibc we target: bullseye and focal are both 2.31, and a module
# built on bookworm (2.36) needs GLIBC_2.34 and will not install on either.
#
#   build/build-fips-deb.sh [FIPSVER] [SUITE] [IMAGE]
set -euo pipefail

FIPSVER="${1:-3.1.2}"
SUITE="${2:-bullseye}"
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
    -e JOBS="${JOBS:-}" \
    "$IMAGE" \
    bash /src/packaging/deb-fips/build-in-container.sh

echo "== artifacts in $OUT =="
ls -l "$OUT"
