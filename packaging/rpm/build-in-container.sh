#!/usr/bin/env bash
# Runs INSIDE an almalinux:<rel> container. Downloads the OpenSSL source and
# builds the .rpm(s) with rpmbuild.
set -euo pipefail

STREAM="${STREAM:?set STREAM, e.g. 4.0}"
VERSION="${VERSION:?set VERSION, e.g. 4.0.1}"
SRCREPO=/src
OUT=/out

echo ">> build openssl${STREAM}-upstream ${VERSION} (rpm)"
dnf -y install --setopt=install_weak_deps=False \
    rpm-build redhat-rpm-config gcc make wget ca-certificates \
    perl-interpreter perl-core 'perl(FindBin)' 'perl(IPC::Cmd)' \
    'perl(Pod::Html)' 'perl(Pod::Man)' >/dev/null

topdir="$(rpm --eval '%{_topdir}')"
mkdir -p "$topdir"/{SOURCES,SPECS,RPMS,BUILD,BUILDROOT} "$OUT"

tarball="openssl-${VERSION}.tar.gz"
url="https://github.com/openssl/openssl/releases/download/openssl-${VERSION}/${tarball}"
echo ">> fetch $url"
wget -q "$url" -O "$topdir/SOURCES/$tarball"

cp "$SRCREPO/packaging/rpm/openssl-upstream.spec" "$topdir/SPECS/"
cp "$SRCREPO/packaging/common/setup-shlib-variant.sh" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/enable.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/trust-anchors.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/variant-target.conf.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/fips-enable.in" "$topdir/SOURCES/"
cp "$SRCREPO/packaging/common/openssl-fips.cnf.in" "$topdir/SOURCES/"

echo ">> rpmbuild (RUN_TESTS=${RUN_TESTS:-0})"
RT=()
[ "${RUN_TESTS:-0}" = 1 ] && RT=(--define "run_tests 1")
rpmbuild -bb \
    --define "stream ${STREAM}" \
    --define "version ${VERSION}" \
    "${RT[@]}" \
    "$topdir/SPECS/openssl-upstream.spec"

echo ">> collect artifacts"
find "$topdir/RPMS" -name '*.rpm' -exec cp -v {} "$OUT"/ \;
ls -l "$OUT"
