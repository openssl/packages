#!/usr/bin/env bash
# Runs INSIDE an almalinux:<rel> container. Downloads the OpenSSL source and
# builds the .rpm(s) with rpmbuild.
set -euo pipefail

STREAM="${STREAM:?set STREAM, e.g. 4.0}"
VERSION="${VERSION:?set VERSION, e.g. 4.0.1}"
REVISION="${REVISION:-1}"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
export SOURCE_DATE_EPOCH
CHANGELOG_DATE="$(LC_ALL=C date -u -d "@$SOURCE_DATE_EPOCH" "+%a %b %d %Y")"
SRCREPO=/src
OUT=/out

echo ">> build openssl${STREAM}-upstream ${VERSION} (rpm)"
# --setopt timeout/retries: a mirror address with a broken path stalls the
# fetch, and the default retry count is too low to redraw a working one.
dnf -y install --setopt=install_weak_deps=False \
    --setopt=timeout=30 --setopt=retries=10 \
    rpm-build redhat-rpm-config gcc make wget ca-certificates gnupg2 \
    perl-interpreter perl-core 'perl(FindBin)' 'perl(IPC::Cmd)' \
    'perl(Pod::Html)' 'perl(Pod::Man)' >/dev/null

topdir="$(rpm --eval '%{_topdir}')"
mkdir -p "$topdir"/{SOURCES,SPECS,RPMS,BUILD,BUILDROOT} "$OUT"

tarball="openssl-${VERSION}.tar.gz"
url="https://github.com/openssl/openssl/releases/download/openssl-${VERSION}/${tarball}"
echo ">> fetch $url"
wget -q "$url" -O "$topdir/SOURCES/$tarball"
wget -q "$url.asc" -O "$topdir/SOURCES/$tarball.asc"
sh "$SRCREPO/packaging/common/verify-source.sh" \
    "$topdir/SOURCES/$tarball" "$topdir/SOURCES/$tarball.asc"

cp "$SRCREPO/packaging/rpm/openssl-upstream.spec" "$topdir/SPECS/"
cp "$SRCREPO/packaging/common/setup-shlib-variant.sh" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/enable.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/trust-anchors.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/variant-target.conf.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/fips-enable.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/openssl-fips.cnf.in" "$topdir/SOURCES/"

echo ">> rpmbuild (RUN_TESTS=${RUN_TESTS:-0}, JOBS=${JOBS:-auto})"
RT=()
[ "${RUN_TESTS:-0}" = 1 ] && RT=(--define "run_tests 1")
# Pin %make_build's -j; %{_smp_build_ncpus} is what it derives from on EL9 and
# EL10 alike. Left at rpm's own detection when JOBS is unset.
JB=()
[ -n "${JOBS:-}" ] && JB=(--define "_smp_build_ncpus ${JOBS}")
rpmbuild -bb \
    --define "stream ${STREAM}" \
    --define "version ${VERSION}" \
    --define "revision ${REVISION}" \
    --define "changelog_date ${CHANGELOG_DATE}" \
    "${RT[@]}" "${JB[@]}" \
    "$topdir/SPECS/openssl-upstream.spec"

echo ">> collect artifacts"
find "$topdir/RPMS" -name '*.rpm' -exec cp -v {} "$OUT"/ \;
ls -l "$OUT"
