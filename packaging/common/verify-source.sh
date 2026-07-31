#!/bin/sh
# Verify an OpenSSL source tarball before anything is unpacked from it.
#
#   verify-source.sh <tarball> <detached-signature>
#
# Two fatal checks: the SHA-256 pinned in sources.sha256, then the upstream
# signature against openssl-release-keys.asc beside this script. That keyring is
# the allowlist; no keyserver or WKD is consulted.
set -eu

TARBALL="${1:?usage: verify-source.sh <tarball> <signature>}"
SIGNATURE="${2:?usage: verify-source.sh <tarball> <signature>}"

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PINS="$HERE/sources.sha256"
KEYRING="$HERE/openssl-release-keys.asc"
NAME=$(basename "$TARBALL")

die() {
    echo "ERROR: source verification failed: $*" >&2
    exit 1
}

[ -r "$TARBALL" ]   || die "$TARBALL is not readable"
[ -r "$SIGNATURE" ] || die "$SIGNATURE is not readable (the .asc must be downloaded too)"
[ -r "$PINS" ]      || die "missing $PINS"
[ -r "$KEYRING" ]   || die "missing $KEYRING"

# ---- 1. pinned checksum ----------------------------------------------------

# An unpinned version is an error, not a pass.
pin=$(grep -v '^[[:space:]]*#' "$PINS" | grep "[[:space:]]$NAME\$" || :)
[ -n "$pin" ] || die "no pinned SHA-256 for $NAME in $PINS. Verify the upstream
signature by hand, then add the checksum (see the header of that file)."

echo ">> verifying $NAME against its pinned SHA-256"
printf '%s\n' "$pin" | (cd "$(dirname "$TARBALL")" && sha256sum -c --strict -) \
    || die "$NAME does not match its pinned SHA-256 in $PINS.
Either the download is corrupt or the upstream artifact changed; do not proceed."

# ---- 2. upstream signature -------------------------------------------------

echo ">> verifying the upstream signature of $NAME"
command -v gpg >/dev/null 2>&1 || die "gpg is not installed in this container"

GNUPGHOME=$(mktemp -d)
export GNUPGHOME
chmod 700 "$GNUPGHOME"
cleanup() { rm -rf "$GNUPGHOME"; }
trap cleanup EXIT

gpg --batch --quiet --import "$KEYRING" \
    || die "could not import $KEYRING"

# VALIDSIG from --status-fd is the authority, not gpg's exit status.
status="$GNUPGHOME/status"
gpg --batch --status-fd 3 --verify "$SIGNATURE" "$TARBALL" 3>"$status" >/dev/null 2>&1 || :

if ! grep -q '^\[GNUPG:\] VALIDSIG ' "$status"; then
    echo "--- gpg status output ---" >&2
    cat "$status" >&2 || :
    die "no valid signature on $NAME from any key in $KEYRING"
fi

signer=$(awk '/^\[GNUPG:\] VALIDSIG /{print $3; exit}' "$status")
echo ">> $NAME: good signature from $signer"
