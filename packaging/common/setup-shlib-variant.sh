#!/bin/sh
# Prepare a local Configure target that builds our libraries with a distinct
# shared-library variant.
set -eu

VARIANT="${1:--upstream}"
DIR="$PWD/.openssl-local-config"
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
TEMPLATE="$HERE/variant-target.conf.in"

[ -r "$TEMPLATE" ] || {
    echo "setup-shlib-variant: missing template $TEMPLATE" >&2
    exit 1
}

# ./config -t is a dry run that reports the target it would pick for this host.
BASE=$(./config -t 2>/dev/null | sed -n 's/^Configuring OpenSSL version .* for target //p')
[ -n "$BASE" ] || { echo "setup-shlib-variant: cannot detect base target" >&2; exit 1; }

mkdir -p "$DIR"
sed -e "s|@BASE@|${BASE}|g" \
    -e "s|@VARIANT@|${VARIANT}|g" \
    "$TEMPLATE" > "$DIR/openssl-variant.conf"

echo "${BASE}${VARIANT}"
