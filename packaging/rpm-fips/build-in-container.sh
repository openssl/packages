#!/usr/bin/env bash
# Runs INSIDE an almalinux:<rel> container. Builds the FIPS module + helper rpms.
set -euo pipefail

FIPSVER="${FIPSVER:?set FIPSVER, e.g. 3.1.2}"
SRCREPO=/src
OUT=/out

echo ">> build openssl-fips${FIPSVER}-upstream (rpm)"
dnf -y install --setopt=install_weak_deps=False \
    rpm-build redhat-rpm-config gcc make wget ca-certificates \
    perl-interpreter perl-core 'perl(FindBin)' 'perl(IPC::Cmd)' >/dev/null

topdir="$(rpm --eval '%{_topdir}')"
mkdir -p "$topdir"/{SOURCES,SPECS,RPMS,BUILD,BUILDROOT} "$OUT"

wget -q "https://github.com/openssl/openssl/releases/download/openssl-${FIPSVER}/openssl-${FIPSVER}.tar.gz" \
    -O "$topdir/SOURCES/openssl-${FIPSVER}.tar.gz"

cp "$SRCREPO/packaging/rpm-fips/openssl-fips-upstream.spec" "$topdir/SPECS/"

echo ">> rpmbuild (JOBS=${JOBS:-auto})"
FC=()
[ -n "${FIPS_CERT:-}" ] && FC=(--define "fips_cert ${FIPS_CERT}")
# Pin %make_build's -j; see packaging/rpm/build-in-container.sh.
JB=()
[ -n "${JOBS:-}" ] && JB=(--define "_smp_build_ncpus ${JOBS}")
rpmbuild -bb --define "fipsver ${FIPSVER}" "${FC[@]}" "${JB[@]}" \
    "$topdir/SPECS/openssl-fips-upstream.spec"

echo ">> collect artifacts"
find "$topdir/RPMS" -name '*.rpm' -exec cp -v {} "$OUT"/ \;
ls -l "$OUT"
