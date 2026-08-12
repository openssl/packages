#!/usr/bin/env bash
# Runs INSIDE a debian:<codename> container. Two modes:
#   FIPS_STREAM unset  openssl-fips<FIPSVER>-upstream, pinned validated version
#   FIPS_STREAM=X.Y    openssl<X.Y>-upstream-fips, the stream's companion
set -euo pipefail

FIPSVER="${FIPSVER:?set FIPSVER, e.g. 3.1.2}"
REVISION="${REVISION:-1}"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
export SOURCE_DATE_EPOCH
CODENAME="${CODENAME:-bookworm}"
SRCREPO=/src
OUT=/out
WORK=/tmp/work

if [ -n "${FIPS_STREAM:-}" ]; then
    # A companion cannot carry a certificate: an upgrade would change its bytes.
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

# Subshell: os-release defines VERSION and ID, which must not clobber ours.
# shellcheck disable=SC1091
DEBDIST=$(
    . /etc/os-release
    : "${VERSION_ID:?no VERSION_ID in /etc/os-release}"
    case "$ID" in
        debian) echo "+deb${VERSION_ID}" ;;
        *)      echo "+${ID}${VERSION_ID}" ;;
    esac
)

echo ">> build ${PKG} ${FIPSVER}-${REVISION}${DEBDIST} on ${CODENAME}"
export DEBIAN_FRONTEND=noninteractive
# Bounded and retried: a mirror address with a broken path stalls the fetch,
# and apt's own timeout does not fire once the connection half-closes.
apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 update -qq
apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=3 \
    install -y --no-install-recommends \
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
date_r="$(date -R -u -d "@$SOURCE_DATE_EPOCH")"
subst() { sed -e "s/@FIPSVER@/${FIPSVER}/g" -e "s/@CODENAME@/${CODENAME}/g" \
              -e "s/@REVISION@/${REVISION}/g" -e "s/@DEBDIST@/${DEBDIST}/g" \
              -e "s|@PACKAGING_COMMIT@|${PACKAGING_COMMIT:-unknown}|g" \
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
