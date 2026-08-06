#!/usr/bin/env bash
# Sign every .rpm in a package tree with an HSM key, then prove it took.
#
#   publish/sign-rpms.sh <cka-label> <cert> [package-dir]
#
# rpmsign shells out to a gpg command line; %__gpg points it at
# sq-pkcs11-gpg-shim so the key never leaves the HSM. %_gpg_name is the CKA_LABEL.
#
# Requires: rpm (rpmsign, rpmkeys), sq-pkcs11, sq-pkcs11-gpg-shim on PATH,
# and PKCS11_MODULE_PATH pointing at the vendor PKCS#11 library.
set -euo pipefail

KEY_LABEL=${1:?usage: sign-rpms.sh <cka-label> <cert> [package-dir]}
CERT=${2:?usage: sign-rpms.sh <cka-label> <cert> [package-dir]}
PKGDIR=${3:-output}

[ -r "$CERT" ] || {
    echo "$CERT is not readable; it is what --input-cert derives the key creation time from." >&2
    exit 1
}

mapfile -t RPMS < <(find "$PKGDIR" -type f -name '*.rpm' | sort)
if [ ${#RPMS[@]} -eq 0 ]; then
    # A deb-only scope legitimately has nothing to sign.
    echo "No .rpm packages under $PKGDIR; nothing to sign."
    exit 0
fi

# Resolve the shim before use: an empty --define is not an error to rpm, it just
# reports "Macro %__gpg has empty body" and never says what was missing.
SHIM=${SQ_PKCS11_GPG_SHIM:-$(command -v sq-pkcs11-gpg-shim || true)}
[ -x "$SHIM" ] || {
    echo "sq-pkcs11-gpg-shim not found on PATH (PATH=$PATH). It ships in the sq-pkcs11 release tarball from v0.4.1; set SQ_PKCS11_GPG_SHIM to override." >&2
    exit 1
}

# sq-pkcs11 reads the certificate through the shim's environment contract.
export SQ_PKCS11_CERT="$CERT"

rpmsign --addsign \
    --define "_gpg_name $KEY_LABEL" \
    --define "__gpg $SHIM" \
    "${RPMS[@]}"

# Verify against a scratch rpmdb so the signing host keeps no state. --checksig
# exits 0 for an UNSIGNED package ("digests OK"), so the exit status proves
# nothing on its own — the signature line has to be there.
DB=$(mktemp -d)
trap 'rm -rf -- "$DB"' EXIT
rpm --initdb --dbpath "$DB"
rpmkeys --dbpath "$DB" --import "$CERT"

UNVERIFIED=0
for PKG in "${RPMS[@]}"; do
    RESULT=$(rpmkeys --dbpath "$DB" --checksig "$PKG" 2>&1 || true)
    case "$RESULT" in
    *"signatures OK"*) ;;
    *)
        echo "$RESULT" >&2
        UNVERIFIED=1
        ;;
    esac
done
[ "$UNVERIFIED" -eq 0 ] || exit 1

echo "Signed and verified ${#RPMS[@]} rpm packages."
