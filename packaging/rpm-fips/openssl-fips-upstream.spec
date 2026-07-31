# FIPS provider module. Two modes:
#   --define "fipsver X.Y.Z" [--define "fips_cert N"]  pinned validated version
#   --define "fipsver X.Y.Z" --define "fips_stream X.Y"  stream companion
# Configured with `enable-fips` and nothing else, per the Security Policy.

%global fipsver   %{?fipsver}%{!?fipsver:3.1.2}
%global revision  %{?revision}%{!?revision:1}
%global changelog_date %{?changelog_date}%{!?changelog_date:Tue Jul 21 2026}
%global moddir    %{?fips_stream}%{!?fips_stream:%{fipsver}}
%global pkgname   %{?fips_stream:openssl%{fips_stream}-upstream-fips}%{!?fips_stream:openssl-fips%{fipsver}-upstream}
%global fipsroot  /opt/openssl/fips/%{moddir}
%global _buildhost reproducible.openssl.local
%global __provides_exclude_from ^/opt/openssl/

# A companion cannot carry a certificate: an upgrade would change certified bytes.
%if "%{?fips_stream}" != "" && "%{?fips_cert}" != ""
%{error:fips_stream and fips_cert are mutually exclusive}
%endif

Name:           %{pkgname}
Version:        %{fipsver}
Release:        %{revision}%{?dist}
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
# The Security Policy's exact command (3.1.2 cert #4985, §11.1 step 1). The SP
# prescribes a command, not an environment, so %%set_build_flags gives this
# build the platform's normal package-build flags like every other spec.
%set_build_flags
./Configure enable-fips
# providers/fips.so is MODULES{fips}. Skipping the test programs the default
# target would also build leaves fips.so byte-identical.
%make_build build_modules

%install
install -Dm755 providers/fips.so %{buildroot}%{fipsroot}/fips.so
# Records the CMVP certificate; absent means not NIST-validated.
%if "%{?fips_cert}" != ""
echo "NIST CMVP certificate #%{fips_cert}" > %{buildroot}%{fipsroot}/validated
%endif
# The companion's dir is the stream, so record the source version beside it.
%if "%{?fips_stream}" != ""
echo "%{fipsver}" > %{buildroot}%{fipsroot}/version
%endif

%post
# An upgrade replaces the module bytes, staling the MAC in each stream's
# fipsmodule.cnf, so re-activate every stream that has this module enabled.
# A failure is reported loudly but does not fail the install.
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
* %{changelog_date} OpenSSL Packages <openssl-packages@openssl.org> - %{fipsver}-%{revision}
- OpenSSL FIPS provider %{fipsver}, packaged for /opt.
- Packaging changes: https://github.com/openssl/packages/blob/main/CHANGELOG.md
