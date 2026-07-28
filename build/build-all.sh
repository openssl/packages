#!/usr/bin/env bash
# Build openssl<STREAM>-upstream across the full per-release matrix.
# Each release is built on its own release, with that release's toolchain.
#
#   build/build-all.sh [STREAM] [VERSION] [deb|rpm|all]
#   build/build-all.sh 4.0 4.0.1 all
#
# Targets are one line each — add a release by adding a line. A failing target
# is recorded and the run continues (nothing is silently skipped).
set -uo pipefail

STREAM="${1:-4.0}"
VERSION="${2:-4.0.1}"
WHICH="${3:-all}"
# Exported to the workers; building both arches means running this twice.
ARCH="${ARCH:-amd64}"
export ARCH
HERE="$(cd "$(dirname "$0")" && pwd)"

# deb: "suite|image"  (image tag is authoritative; suite labels the repo/changelog)
DEB_TARGETS=(
    "bullseye|debian:11"
    "bookworm|debian:12"
    "trixie|debian:13"
    "focal|ubuntu:20.04"
    "jammy|ubuntu:22.04"
    "noble|ubuntu:24.04"
    "resolute|ubuntu:26.04"
)

# rpm: "el|image"
RPM_TARGETS=(
    "9|almalinux:9"
    "10|almalinux:10"
)

RESULTS=()
# Arguments: label, then the command and its arguments.
run() {
    local label="$1"; shift
    echo; echo "############################ $label ############################"
    if "$@"; then RESULTS+=("OK    $label"); else RESULTS+=("FAIL  $label"); fi
}

if [ "$WHICH" = all ] || [ "$WHICH" = deb ]; then
    for t in "${DEB_TARGETS[@]}"; do
        suite="${t%%|*}"; image="${t##*|}"
        run "deb  $suite ($image)" "$HERE/build-deb.sh" "$STREAM" "$VERSION" "$suite" "$image"
    done
fi

if [ "$WHICH" = all ] || [ "$WHICH" = rpm ]; then
    for t in "${RPM_TARGETS[@]}"; do
        el="${t%%|*}"; image="${t##*|}"
        run "rpm  el$el ($image)" "$HERE/build-rpm.sh" "$STREAM" "$VERSION" "$el" "$image"
    done
fi

echo; echo "==================== SUMMARY  openssl${STREAM}-upstream ${VERSION} (${ARCH}) ===================="
printf '%s\n' "${RESULTS[@]}"
fails=$(printf '%s\n' "${RESULTS[@]}" | grep -c '^FAIL' || true)
echo "-----------------------------------------------------------------------"
echo "$fails target(s) failed"
exit "$fails"
