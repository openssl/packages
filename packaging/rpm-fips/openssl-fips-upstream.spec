# FIPS provider module. Pass --define "fipsver X.Y.Z" and, for a version that
# holds a NIST CMVP certificate, --define "fips_cert <number>".
# Configured with `enable-fips` and no other OpenSSL options, per the module
# Security Policy.

%global fipsver   %{?fipsver}%{!?fipsver:3.1.2}
%global fipsroot  /opt/openssl/fips/%{fipsver}
%global _buildhost reproducible.openssl.local
%global __provides_exclude_from ^/opt/openssl/


Name:           openssl-fips%{fipsver}-upstream
Version:        %{fipsver}
Release:        1%{?dist}
Summary:        OpenSSL FIPS provider %{fipsver} (upstream, per validated version)
License:        Apache-2.0
URL:            https://openssl-library.org
Vendor:         OpenSSL Corporation
Source0:        openssl-%{fipsver}.tar.gz

BuildRequires:  gcc make perl-interpreter perl-core perl(FindBin) perl(IPC::Cmd)

%description
The OpenSSL FIPS provider module (fips.so) built from validated source release
%{fipsver} with enable-fips only, installed at %{fipsroot}/fips.so — a
stream-independent path so one module can serve any installed OpenSSL stream.


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

%files
%dir /opt/openssl
%dir /opt/openssl/fips
%dir %{fipsroot}
%{fipsroot}/fips.so
%if "%{?fips_cert}" != ""
%{fipsroot}/validated
%endif


%changelog
* Tue Jul 21 2026 OpenSSL Packages <openssl-packages@openssl.org> - %{fipsver}-1
- OpenSSL FIPS provider %{fipsver} packaged for /opt (proof-of-concept build).
