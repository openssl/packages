#!/usr/bin/env bash
# Runs INSIDE a debian:<codename> container. Builds the FIPS module packages:
#   openssl-fips<FIPSVER>-upstream   (the fips.so)
set -euo pipefail

FIPSVER="${FIPSVER:?set FIPSVER, e.g. 3.1.2}"
CODENAME="${CODENAME:-bookworm}"
SRCREPO=/src
OUT=/out
WORK=/tmp/work

echo ">> build openssl-fips${FIPSVER}-upstream on ${CODENAME}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    build-essential debhelper perl wget ca-certificates file xz-utils >/dev/null

mkdir -p "$WORK" "$OUT"
cd "$WORK"
tarball="openssl-${FIPSVER}.tar.gz"
wget -q "https://github.com/openssl/openssl/releases/download/openssl-${FIPSVER}/${tarball}"
tar xf "$tarball"
cd "openssl-${FIPSVER}"

cp -r "$SRCREPO/packaging/deb-fips/debian" debian
date_r="$(date -R)"
subst() { sed -e "s/@FIPSVER@/${FIPSVER}/g" -e "s/@CODENAME@/${CODENAME}/g" \
        -e "s/@FIPS_CERT@/${FIPS_CERT:-}/g" \
              -e "s/@DATE@/${date_r}/g" "$1"; }
subst debian/control.in > debian/control
subst debian/changelog.in > debian/changelog
subst debian/module.install.in > "debian/openssl-fips${FIPSVER}-upstream.install"
rm -f debian/*.in
sed -i -e "s/@FIPSVER@/${FIPSVER}/g" -e "s/@FIPS_CERT@/${FIPS_CERT:-}/g" debian/rules
chmod +x debian/rules

echo ">> dpkg-buildpackage (binary only)"
dpkg-buildpackage -b -us -uc

echo ">> collect artifacts"
for f in ../*.deb ../*.ddeb; do [ -e "$f" ] && cp -v "$f" "$OUT"/; done
ls -l "$OUT"
