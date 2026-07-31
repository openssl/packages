#!/usr/bin/env bash
# Build the FIPS module .rpms. One build serves every EL release, so the
# builder must be the OLDEST glibc we target — el9.
#
#   build/build-fips-rpm.sh [FIPSVER] [EL] [IMAGE]
set -euo pipefail

FIPSVER="${1:-3.1.2}"
EL="${2:-9}"
IMAGE="${3:-almalinux:$EL}"
ARCH="${ARCH:-amd64}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# FIPS_STREAM=X.Y builds the stream's companion module instead of a pinned
# validated version; the package name differs (see build-in-container.sh).
if [ -n "${FIPS_STREAM:-}" ]; then
    PKG="openssl${FIPS_STREAM}-upstream-fips"
else
    PKG="openssl-fips${FIPSVER}-upstream"
fi
OUT="$REPO/output/${PKG}/rpm"
mkdir -p "$OUT"

echo "== fips rpm: ${PKG} ${FIPSVER} on ${IMAGE} linux/${ARCH} =="
podman run --rm --platform "linux/${ARCH}" \
    -v "$REPO":/src:ro \
    -v "$OUT":/out \
    -e FIPSVER="$FIPSVER" -e FIPS_CERT="${FIPS_CERT:-}" \
    -e FIPS_STREAM="${FIPS_STREAM:-}" -e JOBS="${JOBS:-}" \
    -e REVISION="${REVISION:-1}" -e SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-}" \
    "$IMAGE" \
    bash /src/packaging/rpm-fips/build-in-container.sh

echo "== artifacts in $OUT =="
ls -l "$OUT"
