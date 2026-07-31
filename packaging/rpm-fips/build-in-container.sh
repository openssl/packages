#!/usr/bin/env bash
# Runs INSIDE an almalinux:<rel> container. Builds the FIPS module + helper rpms.
set -euo pipefail

FIPSVER="${FIPSVER:?set FIPSVER, e.g. 3.1.2}"
REVISION="${REVISION:-1}"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
export SOURCE_DATE_EPOCH
CHANGELOG_DATE="$(LC_ALL=C date -u -d "@$SOURCE_DATE_EPOCH" "+%a %b %d %Y")"
SRCREPO=/src
OUT=/out

# FIPS_STREAM set => the stream's companion module (openssl<X.Y>-upstream-fips);
# unset => the pinned validated module. See openssl-fips-upstream.spec.
if [ -n "${FIPS_STREAM:-}" ]; then
    [ -z "${FIPS_CERT:-}" ] || {
        echo "ERROR: FIPS_STREAM and FIPS_CERT are mutually exclusive" >&2; exit 1; }
    PKG="openssl${FIPS_STREAM}-upstream-fips"
else
    PKG="openssl-fips${FIPSVER}-upstream"
fi

echo ">> build ${PKG} ${FIPSVER} (rpm)"
dnf -y install --setopt=install_weak_deps=False \
    rpm-build redhat-rpm-config gcc make wget ca-certificates gnupg2 \
    perl-interpreter perl-core 'perl(FindBin)' 'perl(IPC::Cmd)' >/dev/null

topdir="$(rpm --eval '%{_topdir}')"
mkdir -p "$topdir"/{SOURCES,SPECS,RPMS,BUILD,BUILDROOT} "$OUT"

tarball="openssl-${FIPSVER}.tar.gz"
url="https://github.com/openssl/openssl/releases/download/openssl-${FIPSVER}/${tarball}"
wget -q "$url" -O "$topdir/SOURCES/$tarball"
wget -q "$url.asc" -O "$topdir/SOURCES/$tarball.asc"
sh "$SRCREPO/packaging/common/verify-source.sh" \
    "$topdir/SOURCES/$tarball" "$topdir/SOURCES/$tarball.asc"

cp "$SRCREPO/packaging/rpm-fips/openssl-fips-upstream.spec" "$topdir/SPECS/"

echo ">> rpmbuild (JOBS=${JOBS:-auto})"
FC=()
[ -n "${FIPS_CERT:-}" ] && FC=(--define "fips_cert ${FIPS_CERT}")
FS=()
[ -n "${FIPS_STREAM:-}" ] && FS=(--define "fips_stream ${FIPS_STREAM}")
# Pin %make_build's -j; see packaging/rpm/build-in-container.sh.
JB=()
[ -n "${JOBS:-}" ] && JB=(--define "_smp_build_ncpus ${JOBS}")
rpmbuild -bb --define "fipsver ${FIPSVER}" --define "revision ${REVISION}" \
    --define "changelog_date ${CHANGELOG_DATE}" "${FC[@]}" "${FS[@]}" "${JB[@]}" \
    "$topdir/SPECS/openssl-fips-upstream.spec"

echo ">> collect artifacts"
find "$topdir/RPMS" -name '*.rpm' -exec cp -v {} "$OUT"/ \;
ls -l "$OUT"
