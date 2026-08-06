#!/usr/bin/env bash
# Sign the repository indexes with an HSM key, then verify each signature.
#
#   publish/sign-repo.sh <cka-label> <cert> [repo-dir]
#
#   deb  Release -> InRelease (cleartext, what apt prefers) and Release.gpg
#   rpm  repodata/repomd.xml -> repomd.xml.asc, what repo_gpgcheck=1 reads
#
# Requires: sq-pkcs11 and sqv on PATH, PKCS11_MODULE_PATH set.
set -euo pipefail

KEY_LABEL=${1:?usage: sign-repo.sh <cka-label> <cert> [repo-dir]}
CERT=${2:?usage: sign-repo.sh <cka-label> <cert> [repo-dir]}
REPO=${3:-repo}

[ -r "$CERT" ] || {
    echo "$CERT is not readable; it is what --input-cert derives the key creation time from." >&2
    exit 1
}

# sign <mode: cleartext|detached> <output> <input>
sign() {
    local mode=$1 output=$2 input=$3
    if [ "$mode" = cleartext ]; then
        sq-pkcs11 sign --force --cleartext \
            --key-label "$KEY_LABEL" --input-cert "$CERT" \
            --output "$output" -- "$input"
    else
        sq-pkcs11 sign --force \
            --key-label "$KEY_LABEL" --input-cert "$CERT" \
            --output "$output" -- "$input"
    fi
}

SIGNED=0

while IFS= read -r release; do
    dir=$(dirname "$release")
    sign cleartext "$dir/InRelease" "$release"
    sign detached "$dir/Release.gpg" "$release"
    sqv --keyring "$CERT" --signature-file "$dir/Release.gpg" "$release"
    SIGNED=$((SIGNED + 1))
done < <(find "$REPO/deb/dists" -mindepth 2 -maxdepth 2 -type f -name Release 2>/dev/null | sort)

while IFS= read -r repomd; do
    sign detached "$repomd.asc" "$repomd"
    sqv --keyring "$CERT" --signature-file "$repomd.asc" "$repomd"
    SIGNED=$((SIGNED + 1))
done < <(find "$REPO/rpm" -type f -name repomd.xml 2>/dev/null | sort)

if [ "$SIGNED" -eq 0 ]; then
    echo "Nothing was signed: no Release or repomd.xml found under $REPO." >&2
    exit 1
fi

echo "Signed and verified $SIGNED index files."
