#!/usr/bin/env bash
# Runs INSIDE a debian:<codename> container. Downloads the OpenSSL source,
# lays down the templated debian/ dir, and builds the .deb(s).
set -euo pipefail

STREAM="${STREAM:?set STREAM, e.g. 4.0}"
VERSION="${VERSION:?set VERSION, e.g. 4.0.1}"
REVISION="${REVISION:-1}"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
export SOURCE_DATE_EPOCH
CODENAME="${CODENAME:-bookworm}"
SRCREPO=/src
OUT=/out
WORK=/tmp/work

echo ">> build openssl${STREAM}-upstream ${VERSION} on ${CODENAME}"
export DEBIAN_FRONTEND=noninteractive
# Bounded and retried: a mirror address with a broken path stalls the fetch,
# and apt's own timeout does not fire once the connection half-closes.
apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 update -qq
apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 \
    install -y --no-install-recommends \
    build-essential debhelper perl wget ca-certificates gnupg file xz-utils >/dev/null

mkdir -p "$WORK" "$OUT"
cd "$WORK"
tarball="openssl-${VERSION}.tar.gz"
url="https://github.com/openssl/openssl/releases/download/openssl-${VERSION}/${tarball}"
echo ">> fetch $url"
wget -q "$url" "$url.asc"
sh "$SRCREPO/packaging/common/verify-source.sh" "$tarball" "$tarball.asc"
tar xf "$tarball"
cd "openssl-${VERSION}"

cp -r "$SRCREPO/packaging/deb/debian" debian
cp "$SRCREPO/packaging/common/setup-shlib-variant.sh" setup-shlib-variant.sh
cp "$SRCREPO/packaging/common/variant-target.conf.in" variant-target.conf.in
cp "$SRCREPO/packaging/common/openssl-fips.cnf.in" openssl-fips.cnf.in
PKG="openssl${STREAM}-upstream"
date_r="$(date -R -u -d "@$SOURCE_DATE_EPOCH")"
subst() {
    sed -e "s|@STREAM@|${STREAM}|g" \
        -e "s|@PREFIX@|/opt/openssl/${STREAM}|g" \
        -e "s|@VERSION@|${VERSION}|g" \
        -e "s|@REVISION@|${REVISION}|g" \
        -e "s|@CODENAME@|${CODENAME}|g" \
        -e "s|@DATE@|${date_r}|g" "$1"
}

subst "$SRCREPO/packaging/common/enable.in" > enable
subst "$SRCREPO/packaging/common/trust-anchors.in" > trust-anchors
subst "$SRCREPO/packaging/common/fips-enable.in" > fips-enable
subst debian/control.in > debian/control
subst debian/changelog.in > debian/changelog
subst debian/postinst.in > "debian/${PKG}.postinst"
subst debian/main.install.in > "debian/${PKG}.install"
subst debian/dev.install.in > "debian/${PKG}-dev.install"
rm -f debian/*.in
sed -i "s/@STREAM@/${STREAM}/g" debian/rules
chmod +x debian/rules "debian/${PKG}.postinst"

echo ">> dpkg-buildpackage (binary only; RUN_TESTS=${RUN_TESTS:-0})"
export RUN_TESTS="${RUN_TESTS:-0}"
dpkg-buildpackage -b -us -uc

echo ">> collect artifacts"
# Debian ships dbgsym as .deb, Ubuntu as .ddeb — collect both.
for f in ../*.deb ../*.ddeb; do
    [ -e "$f" ] && cp -v "$f" "$OUT"/
done
ls -l "$OUT"
