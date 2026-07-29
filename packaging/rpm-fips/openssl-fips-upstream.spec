# FIPS provider module, built in one of two modes:
#   --define "fipsver X.Y.Z"                      pinned validated version,
#     [--define "fips_cert <number>"]             openssl-fips<X.Y.Z>-upstream
#   --define "fipsver X.Y.Z" --define "fips_stream X.Y"
#     the stream's companion module, openssl<X.Y>-upstream-fips, NOT validated,
#     upgrades with the stream.
# Configured with `enable-fips` and no other OpenSSL options, per the module
# Security Policy.

%global fipsver   %{?fipsver}%{!?fipsver:3.1.2}
%global moddir    %{?fips_stream}%{!?fips_stream:%{fipsver}}
%global pkgname   %{?fips_stream:openssl%{fips_stream}-upstream-fips}%{!?fips_stream:openssl-fips%{fipsver}-upstream}
%global fipsroot  /opt/openssl/fips/%{moddir}
%global _buildhost reproducible.openssl.local
%global __provides_exclude_from ^/opt/openssl/

# A certificate belongs to a pinned version; a stream companion cannot carry
# one, or an upgrade would silently change certified bytes.
%if "%{?fips_stream}" != "" && "%{?fips_cert}" != ""
%{error:fips_stream and fips_cert are mutually exclusive}
%endif

Name:           %{pkgname}
Version:        %{fipsver}
Release:        1%{?dist}
Summary:        OpenSSL FIPS provider %{fipsver} (upstream%{?fips_stream:, %{fips_stream} stream companion, not validated})
License:        Apache-2.0
URL:            https://openssl-library.org
Vendor:         OpenSSL Corporation
Source0:        openssl-%{fipsver}.tar.gz

BuildRequires:  gcc make perl-interpreter perl-core perl(FindBin) perl(IPC::Cmd)

%description
%if "%{?fips_stream}" != ""
The OpenSSL FIPS provider module (fips.so) built from the same source release
as the openssl%{fips_stream}-upstream packages, with enable-fips only,
installed at %{fipsroot}/fips.so. It upgrades in step with the
%{fips_stream} stream. This module is NOT NIST-validated: it enforces
approved-only algorithms but does not make an installation FIPS 140-3
compliant. On upgrade it is re-activated automatically for any stream that
has it enabled.
%else
The OpenSSL FIPS provider module (fips.so) built from source release
%{fipsver} with enable-fips only, installed at %{fipsroot}/fips.so — a
stream-independent path so one module can serve any installed OpenSSL stream.
This version is pinned: the package never moves to a different source release.
%endif


%prep
%autosetup -n openssl-%{fipsver}

%build
# Exact build command from the module Security Policy (3.1.2, cert #4985) §11.1,
# Crypto Officer Guidance / Installation, step 1: `./Configure enable-fips` then
# `make`. The Security Policy prescribes a command, not an environment, so the
# build environment is the platform's normal one for a package build: this spec
# would otherwise be an anomaly, because rpmbuild does not export its %%optflags
# into %%build automatically, and Configure absorbs CFLAGS/LDFLAGS from the
# environment. Validation is source-based and the source is unmodified; the
# integrity MAC is computed over whatever bytes result.
%set_build_flags
./Configure enable-fips
# providers/fips.so is MODULES{fips}, so build_modules is what produces it. The
# default target also builds the test programs, which this package does not ship;
# skipping them leaves fips.so byte-identical.
%make_build build_modules

%install
install -Dm755 providers/fips.so %{buildroot}%{fipsroot}/fips.so
# A 'validated' marker records the NIST CMVP certificate for source versions
# that hold one; openssl-fips-enable reports it. Absent => not validated.
%if "%{?fips_cert}" != ""
echo "NIST CMVP certificate #%{fips_cert}" > %{buildroot}%{fipsroot}/validated
%endif
# A stream companion's directory is named after the stream, so the source
# version it was built from is recorded beside it for the helper to report.
%if "%{?fips_stream}" != ""
echo "%{fipsver}" > %{buildroot}%{fipsroot}/version
%endif

%post
# Re-activate this module for any stream that has it enabled. The stream's
# fipsmodule.cnf holds an integrity MAC over the module bytes; after an upgrade
# replaces them the MAC is stale and the FIPS provider refuses to load, so the
# re-run of fipsinstall (module self-tests included) must happen here. A failure
# is reported loudly but does not fail the install.
for enabled in /etc/opt/openssl/*/fips-enabled; do
    [ -r "$enabled" ] || continue
    [ "$(cat "$enabled")" = "%{moddir}" ] || continue
    stream=$(basename "$(dirname "$enabled")")
    helper="/opt/openssl/$stream/bin/openssl-fips-enable"
    if [ -x "$helper" ] && "$helper" "%{moddir}" >/dev/null 2>&1; then
        echo "OpenSSL $stream: FIPS module %{moddir} re-activated." >&2
    else
        echo "WARNING: OpenSSL $stream: activation of FIPS module %{moddir}" >&2
        echo "failed; the FIPS provider will NOT load for this stream until" >&2
        echo "you run: $helper %{moddir}" >&2
    fi
done

%files
%dir /opt/openssl
%dir /opt/openssl/fips
%dir %{fipsroot}
%{fipsroot}/fips.so
%if "%{?fips_cert}" != ""
%{fipsroot}/validated
%endif
%if "%{?fips_stream}" != ""
%{fipsroot}/version
%endif


%changelog
* Tue Jul 21 2026 OpenSSL Packages <openssl-packages@openssl.org> - %{fipsver}-1
- OpenSSL FIPS provider %{fipsver} packaged for /opt (proof-of-concept build).
