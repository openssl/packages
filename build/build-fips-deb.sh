#!/usr/bin/env bash
# Build the FIPS module .debs. One build serves every deb release, so the
# builder must be the OLDEST glibc we target.
#
#   build/build-fips-deb.sh [FIPSVER] [SUITE] [IMAGE]
set -euo pipefail

FIPSVER="${1:-3.1.2}"
SUITE="${2:-bullseye}"
IMAGE="${3:-debian:$SUITE}"
ARCH="${ARCH:-amd64}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# FIPS_STREAM=X.Y builds the stream's companion module instead of a pinned
# validated version; the package name differs (see build-in-container.sh).
if [ -n "${FIPS_STREAM:-}" ]; then
    PKG="openssl${FIPS_STREAM}-upstream-fips"
else
    PKG="openssl-fips${FIPSVER}-upstream"
fi
OUT="$REPO/output/${PKG}/deb"
mkdir -p "$OUT"

echo "== fips deb: ${PKG} ${FIPSVER} on ${IMAGE} linux/${ARCH} =="
podman run --rm --platform "linux/${ARCH}" \
    -v "$REPO":/src:ro \
    -v "$OUT":/out \
    -e FIPSVER="$FIPSVER" -e CODENAME="$SUITE" -e FIPS_CERT="${FIPS_CERT:-}" \
    -e FIPS_STREAM="${FIPS_STREAM:-}" \
    -e JOBS="${JOBS:-}" -e REVISION="${REVISION:-1}" \
    -e SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-}" \
    "$IMAGE" \
    bash /src/packaging/deb-fips/build-in-container.sh

echo "== artifacts in $OUT =="
ls -l "$OUT"
