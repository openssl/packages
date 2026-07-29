#!/usr/bin/env bash
# Runs INSIDE a debian:<codename> container. Builds a FIPS module package in one
# of two modes:
#   FIPS_STREAM unset  openssl-fips<FIPSVER>-upstream, pinned validated version
#                      at /opt/openssl/fips/<FIPSVER>/ (FIPS_CERT names the
#                      NIST CMVP certificate)
#   FIPS_STREAM=X.Y    openssl<X.Y>-upstream-fips, the stream's companion module
#                      at /opt/openssl/fips/<X.Y>/, NOT validated, upgrades with
#                      the stream
set -euo pipefail

FIPSVER="${FIPSVER:?set FIPSVER, e.g. 3.1.2}"
CODENAME="${CODENAME:-bookworm}"
SRCREPO=/src
OUT=/out
WORK=/tmp/work

if [ -n "${FIPS_STREAM:-}" ]; then
    # A certificate belongs to a pinned version; a stream companion cannot
    # carry one, or an upgrade would silently change certified bytes.
    [ -z "${FIPS_CERT:-}" ] || {
        echo "ERROR: FIPS_STREAM and FIPS_CERT are mutually exclusive" >&2; exit 1; }
    PKG="openssl${FIPS_STREAM}-upstream-fips"
    MODDIR="${FIPS_STREAM}"
    CONTROL=control-companion.in
else
    PKG="openssl-fips${FIPSVER}-upstream"
    MODDIR="${FIPSVER}"
    CONTROL=control.in
fi

echo ">> build ${PKG} ${FIPSVER} on ${CODENAME}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    build-essential debhelper perl wget ca-certificates gnupg file xz-utils >/dev/null

mkdir -p "$WORK" "$OUT"
cd "$WORK"
tarball="openssl-${FIPSVER}.tar.gz"
url="https://github.com/openssl/openssl/releases/download/openssl-${FIPSVER}/${tarball}"
wget -q "$url" "$url.asc"
sh "$SRCREPO/packaging/common/verify-source.sh" "$tarball" "$tarball.asc"
tar xf "$tarball"
cd "openssl-${FIPSVER}"

cp -r "$SRCREPO/packaging/deb-fips/debian" debian
date_r="$(date -R)"
subst() { sed -e "s/@FIPSVER@/${FIPSVER}/g" -e "s/@CODENAME@/${CODENAME}/g" \
              -e "s/@FIPSPKG@/${PKG}/g" -e "s/@MODDIR@/${MODDIR}/g" \
              -e "s/@FIPS_CERT@/${FIPS_CERT:-}/g" \
              -e "s/@FIPS_STREAM@/${FIPS_STREAM:-}/g" \
              -e "s/@DATE@/${date_r}/g" "$1"; }
subst "debian/$CONTROL" > debian/control
subst debian/changelog.in > debian/changelog
subst debian/module.install.in > "debian/${PKG}.install"
subst debian/postinst.in > "debian/${PKG}.postinst"
rm -f debian/*.in
sed -i -e "s/@FIPSVER@/${FIPSVER}/g" -e "s/@FIPS_CERT@/${FIPS_CERT:-}/g" \
       -e "s/@FIPS_STREAM@/${FIPS_STREAM:-}/g" -e "s/@MODDIR@/${MODDIR}/g" debian/rules
chmod +x debian/rules "debian/${PKG}.postinst"

echo ">> dpkg-buildpackage (binary only)"
dpkg-buildpackage -b -us -uc

echo ">> collect artifacts"
for f in ../*.deb ../*.ddeb; do [ -e "$f" ] && cp -v "$f" "$OUT"/; done
ls -l "$OUT"
