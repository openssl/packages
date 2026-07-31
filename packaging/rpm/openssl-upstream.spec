# Spec for openssl<stream>-upstream. Pass --define "stream X.Y" --define
# "version X.Y.Z" (see packaging/rpm/build-in-container.sh). Pristine upstream
# source, default configuration, installed under /opt.

%global stream      %{?stream}%{!?stream:4.0}
%global revision    %{?revision}%{!?revision:1}
%global prefix      /opt/openssl/%{stream}
%global etcparent   /etc/opt/openssl
%global ssldir      %{etcparent}/%{stream}

# Do not leak the (possibly foreign) build host into signed artifacts.
%global _buildhost  reproducible.openssl.local

# Never advertise our private libraries, and never turn our own intra-package
# SONAME links into unmet external Requires. libc etc. are kept.
%global __provides_exclude_from ^%{prefix}/.*$
%global __requires_exclude ^lib(ssl|crypto).*\\.so

Name:           openssl%{stream}-upstream
Version:        %{version}
Release:        %{revision}%{?dist}
Summary:        OpenSSL %{stream} upstream build (installed under /opt)
License:        Apache-2.0
URL:            https://openssl-library.org
Vendor:         OpenSSL Corporation
Source0:        openssl-%{version}.tar.gz
Source1:        setup-shlib-variant.sh
Source2:        enable.in
Source3:        trust-anchors.in
Source4:        variant-target.conf.in
Source5:        fips-enable.in
Source6:        openssl-fips.cnf.in

BuildRequires:  gcc make perl-interpreter perl-core
BuildRequires:  perl(FindBin) perl(IPC::Cmd) perl(Pod::Html) perl(Pod::Man)
Requires:       ca-certificates

%description
Official upstream OpenSSL %{stream}, built from pristine source with the
default feature set and installed under %{prefix} so that it coexists with —
and never interferes with — the distribution's own OpenSSL. Configuration
lives under %{ssldir}. Source %{prefix}/enable to put it on PATH.

%package devel
Summary:        Development files for OpenSSL %{stream} upstream build
Requires:       %{name} = %{version}-%{release}

%description devel
Headers, pkg-config files, CMake package-config (exporter) files, static libraries, link-time shared-object
symlinks, API/guide man pages and the source demos for OpenSSL %{stream}.

%prep
%autosetup -n openssl-%{version}

%build
# Default configuration: only the /opt layout args plus the distro's hardened
# flags. The synthesised '-upstream' target carries shlib_variant and RUNPATH.
cp %{SOURCE1} setup-shlib-variant.sh
# setup-shlib-variant.sh reads the target template from alongside itself.
cp %{SOURCE4} variant-target.conf.in
VARIANT_TARGET=$(sh setup-shlib-variant.sh -upstream)
export OPENSSL_LOCAL_CONFIG_DIR=$PWD/.openssl-local-config
./Configure "$VARIANT_TARGET" \
    --prefix=%{prefix} \
    --openssldir=%{ssldir} \
    --libdir=lib64 \
    shared \
    %{optflags} \
    %{build_ldflags}
# Build exactly what gets installed, which is not what the default target builds.
%make_build build_inst_sw build_man_docs

%check
# Upstream's own suite — redundant for code correctness, useful as a
# per-toolchain gate. Off by default; enable with --define "run_tests 1".
# The `test` target builds the test programs itself.
%if "%{?run_tests}" == "1"
make test
%endif

%install
# NOT %%make_install: that runs the bare `install` target too, which drags in
# install_html_docs and stages an HTML manual we do not ship.
make DESTDIR=%{buildroot} install_sw install_ssldirs install_man_docs

# Per-stream enable/deactivate script (interactive convenience).
sed -e 's|@PREFIX@|%{prefix}|g' -e 's|@STREAM@|%{stream}|g' \
    %{SOURCE2} > %{buildroot}%{prefix}/enable

# Trust-anchor policy helper (called from %%post; user-runnable later).
sed -e 's|@PREFIX@|%{prefix}|g' -e 's|@STREAM@|%{stream}|g' \
    %{SOURCE3} > %{buildroot}%{prefix}/bin/openssl-trust-anchors
chmod 755 %{buildroot}%{prefix}/bin/openssl-trust-anchors

# FIPS module selection/activation helper (per stream).
sed -e 's|@PREFIX@|%{prefix}|g' -e 's|@STREAM@|%{stream}|g' \
    %{SOURCE5} > %{buildroot}%{prefix}/bin/openssl-fips-enable
chmod 755 %{buildroot}%{prefix}/bin/openssl-fips-enable

# Configuration template the FIPS helper instantiates when enabling a module.
install -Dm644 %{SOURCE6} %{buildroot}%{prefix}/share/openssl-fips.cnf.in

# Ship the source demos with -devel; the ossl-guide-* man pages reference them.
mkdir -p %{buildroot}%{prefix}/share/doc/%{name}
cp -r demos %{buildroot}%{prefix}/share/doc/%{name}/demos

# Embed RUNPATH in pkg-config so consumers resolve our libs at run time.
sed -i 's|^Libs: |Libs: -Wl,-rpath,${libdir} |' \
    %{buildroot}%{prefix}/lib64/pkgconfig/*.pc

# The CA dirs are wired to the distro trust store in %%post, not shipped.
rm -rf %{buildroot}%{ssldir}/certs

# Allow our intentional absolute RUNPATH past the EL rpmbuild QA check.
export QA_RPATHS=0x0002

%post
# Apply the recorded trust-anchor policy; rpm cannot prompt, so trust.conf or
# USE_SYSTEM_TRUST_ANCHORS is the install-time interface.
%{prefix}/bin/openssl-trust-anchors apply || :

%postun
# Only on final erasure, never on upgrade ($1 == 0); remove only our symlinks,
# never administrator-provided files.
if [ "$1" = 0 ]; then
    [ -L %{ssldir}/cert.pem ] && rm -f %{ssldir}/cert.pem || :
    [ -L %{ssldir}/certs ]    && rm -f %{ssldir}/certs    || :
fi

%files
%license LICENSE.txt
%{prefix}/
%exclude %{prefix}/include
%exclude %{prefix}/lib64/*.a
%exclude %{prefix}/lib64/*.so
%exclude %{prefix}/lib64/pkgconfig
%exclude %{prefix}/lib64/cmake
%exclude %{prefix}/share/man/man3
%exclude %{prefix}/share/man/man7
%exclude %{prefix}/share/doc
%dir %{etcparent}
%dir %{ssldir}
%config(noreplace) %{ssldir}/openssl.cnf
%{ssldir}/openssl.cnf.dist
%config(noreplace) %{ssldir}/ct_log_list.cnf
%{ssldir}/ct_log_list.cnf.dist
%dir %{ssldir}/misc
%{ssldir}/misc/*
%dir %{ssldir}/private

%files devel
%{prefix}/include
%{prefix}/lib64/*.a
%{prefix}/lib64/*.so
%{prefix}/lib64/pkgconfig
%{prefix}/lib64/cmake
%{prefix}/share/man/man3
%{prefix}/share/man/man7
%{prefix}/share/doc

%changelog
* Tue Jul 21 2026 OpenSSL Packages <openssl-packages@openssl.org> - %{version}-%{revision}
- Upstream OpenSSL %{version}, packaged for /opt.
