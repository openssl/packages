# OpenSSL Packages

Packaging sources for official OpenSSL binary packages (`.deb` and `.rpm`) for
Linux distributions.

Distributions freeze OpenSSL for the lifetime of a release, so a supported
distribution often cannot offer a current OpenSSL. These packages provide
upstream OpenSSL releases, built and maintained by the OpenSSL Corporation, that
install alongside the distribution's own OpenSSL without altering or replacing
it. Several OpenSSL versions can be installed at the same time, and each
receives patch updates within its release stream.

## What the packages provide

- Upstream OpenSSL, built from unmodified release tarballs with the default
  feature set.
- Installation under `/opt/openssl/<major>.<minor>`, with configuration under
  `/etc/opt/openssl/<major>.<minor>`.
- No effect on the distribution's OpenSSL: nothing is added to the global
  library search path, and the system `libcrypto`/`libssl`, the programs that
  depend on them, and the system trust configuration are untouched.
- Multiple release streams installed side by side, for example 4.0 and 4.1.
- FIPS provider modules as separate packages: pinned packages for
  NIST-validated source versions, and a per-stream companion module that
  upgrades with its stream.
- Development files, documentation, man pages and debug symbols.

## Supported distributions

Each distribution release gets its own build, made on that release with that
release's toolchain.

| Family | Releases |
| ------ | -------- |
| Debian | 11, 12, 13 |
| Ubuntu | 20.04 LTS, 22.04 LTS, 24.04 LTS, 26.04 LTS |
| Enterprise Linux 9 and 10 | RHEL, AlmaLinux, Rocky, Oracle, CentOS Stream |

Architectures: `x86_64` and `aarch64`. Ubuntu interim releases are not covered.

## Installing

A hosted apt/dnf repository is not yet available, so packages are installed
from files:

```sh
# Debian, Ubuntu
sudo apt install ./openssl4.0-upstream_4.0.1-1+deb12_amd64.deb

# Enterprise Linux
sudo dnf install ./openssl4.0-upstream-4.0.1-1.el9.x86_64.rpm
```

## Package names

Every package name carries an `upstream` marker. A distribution may ship its own
package for the same OpenSSL generation, and two packages with the same name from
different origins would compete in the resolver; the marker keeps them distinct.
It follows the version so that `apt search openssl` and `dnf search openssl` still
find these packages. There is no hyphen before the version digits, because rpm
file names parse as name-version-release and `openssl-4.0-4.0.1-1` would be read
wrongly.

### OpenSSL releases

Named for the release stream, `MAJOR.MINOR`. The package version is the full
upstream version, so patch releases update in place within a stream and streams
install alongside each other.

| Package | Contents |
| ------- | -------- |
| `openssl<MAJOR>.<MINOR>-upstream` | libraries, the `openssl` program, the stream helpers, and configuration under `/etc/opt/openssl/<MAJOR>.<MINOR>` |
| `openssl<MAJOR>.<MINOR>-upstream-dev` (Debian, Ubuntu)<br>`openssl<MAJOR>.<MINOR>-upstream-devel` (Enterprise Linux) | headers, static libraries, pkg-config and CMake files, API and guide man pages, source examples |
| `openssl<MAJOR>.<MINOR>-upstream-dbgsym` (Debian, Ubuntu)<br>`openssl<MAJOR>.<MINOR>-upstream-debuginfo` and `-debugsource` (Enterprise Linux) | debug symbols |

```
openssl4.0-upstream_4.0.1-1+deb12_amd64.deb           Debian 12
openssl4.0-upstream_4.0.1-1+ubuntu24.04_amd64.deb     Ubuntu 24.04
openssl4.0-upstream-dev_4.0.1-1+deb12_amd64.deb
openssl4.0-upstream-4.0.1-1.el9.x86_64.rpm            Enterprise Linux 9
openssl4.0-upstream-devel-4.0.1-1.el9.x86_64.rpm
```

Every distribution release gets its own build, so the package version carries
the release it was built for — `+deb12`, `+ubuntu24.04` on the deb side, the
usual `.el9`/`.el10` dist tag on rpm. Two packages for different releases never
share a file name.

Ubuntu ships debug symbols with a `.ddeb` extension rather than `.deb`.

Installed under `/opt/openssl/<MAJOR>.<MINOR>`. The path holds only the stream,
never the patch version, so references to it survive updates.

### FIPS provider modules

Two kinds of module package, with different lifecycles.

**Validated modules** are named for the full source version they were built
from, `MAJOR.MINOR.PATCH`, because a NIST CMVP certificate is tied to an exact
source version. These packages are pinned: they never move to a different
source release, so what was validated is what stays installed. Several can be
installed together, independently of any stream.

| Package | Contents |
| ------- | -------- |
| `openssl-fips<VERSION>-upstream` | the provider module, under `/opt/openssl/fips/<VERSION>` |
| `openssl-fips<VERSION>-upstream-dbgsym` (Debian, Ubuntu)<br>`openssl-fips<VERSION>-upstream-debuginfo` and `-debugsource` (Enterprise Linux) | debug symbols |

```
openssl-fips3.1.2-upstream_3.1.2-1_amd64.deb        Debian, Ubuntu
openssl-fips3.1.2-upstream-3.1.2-1.el9.x86_64.rpm   Enterprise Linux
```

**The stream companion module** is named for its stream, like every other
stream package, and upgrades in step with it — it is built from the same
source release as the stream's packages and is **not** NIST-validated. It is
useful for developing and testing FIPS-mode behaviour against current code
without freezing on old module versions.

| Package | Contents |
| ------- | -------- |
| `openssl<MAJOR>.<MINOR>-upstream-fips` | the provider module, under `/opt/openssl/fips/<MAJOR>.<MINOR>` |

```
openssl4.0-upstream-fips_4.0.1-1_amd64.deb          Debian, Ubuntu
openssl4.0-upstream-fips-4.0.1-1.el9.x86_64.rpm     Enterprise Linux
```

`openssl-fips-enable list` reports each installed module's status: the
certificate number for a validated module, the actual source version for the
stream companion.

## Using an installed stream

Because nothing is placed on the global `PATH`, select a stream for the current
shell:

```sh
source /opt/openssl/4.0/enable
openssl version
openssl_upstream_deactivate      # restore the previous environment
```

Sourcing another stream's `enable` switches cleanly; the command is namespaced
so it does not interfere with other tools that provide a `deactivate`.

Programs are otherwise run by full path, for example
`/opt/openssl/4.0/bin/openssl`.

### Building software against a stream

The `-dev` / `-devel` package installs headers, static libraries, pkg-config
files and CMake package configuration. `pkg-config` files carry the library
path, so programs built through them find the correct libraries at run time
without any environment variable or system-wide configuration:

```sh
source /opt/openssl/4.0/enable
gcc app.c $(pkg-config --cflags --libs openssl) -o app
```

Source examples referenced by the OpenSSL guides are installed with the
development package, under `/opt/openssl/<major>.<minor>/share/doc`.

### CA trust anchors

Each stream keeps its own trust store under
`/etc/opt/openssl/<major>.<minor>`. By default it is linked to the
distribution's CA trust anchors, so certificate verification behaves as it does
for the system OpenSSL.

To use your own anchors instead, decline the system ones at install time — the
same on both package families:

```sh
USE_SYSTEM_TRUST_ANCHORS=no sudo apt install ./openssl4.0-upstream_*.deb
USE_SYSTEM_TRUST_ANCHORS=no sudo dnf install ./openssl4.0-upstream-*.rpm
```

The choice is recorded and preserved across updates, and can be changed later:

```sh
openssl-trust-anchors status
openssl-trust-anchors none      # stream-private, initially empty trust store
openssl-trust-anchors system
```

With `none`, add anchors to `/etc/opt/openssl/<major>.<minor>/certs` and run
`openssl rehash` on that directory, or point applications at their own store
with `SSL_CERT_FILE` / `SSL_CERT_DIR`.

### Enabling a FIPS provider module

Modules install under `/opt/openssl/fips/`, independently of any stream, so one
module can serve any installed stream and several modules can be installed
together: validated modules under their full version, the stream companion
under its stream label.

Activation is an explicit administrative step, because the module's self-tests
must run on the machine that will use it:

```sh
openssl-fips-enable list         # installed modules and their validation status
openssl-fips-enable 3.1.2        # activate a validated module for this stream
openssl-fips-enable 4.0          # or the 4.0 stream's companion module
openssl-fips-enable verify       # confirm the configuration still matches the module
openssl-fips-enable disable
```

A module without a NIST CMVP certificate still restricts operations to approved
algorithms, which is useful for development and testing, but it does not make
an installation FIPS 140-3 compliant.

When the stream companion module is upgraded along with its stream, it is
re-activated automatically for any stream that has it enabled, so its integrity
checksum keeps matching the installed bytes. Validated modules never change, so
they are never re-activated behind your back.

## How the packages are built

**Per distribution release.** Every supported release is built on that release,
with its own compiler, packaging tools and hardening flags. This keeps binaries
appropriate to the platform they run on — including protection schemes that
distributions adopt over time, such as Intel CET — and keeps what is built and
what is tested in step.

**Unmodified upstream source.** Packages are built from the released tarball
with no downstream patches and the default feature set. Only the installation
layout is configured; toolchain and hardening flags are the distribution's
standard package-build flags.

**Isolated from the system OpenSSL.** Three measures together:

- No `ld.so.conf.d` entry is installed, so the libraries stay off the global
  search path.
- The shipped programs and libraries carry a `RUNPATH` pointing at their own
  stream, and the pkg-config files pass it on to anything built against them.
- The libraries are built with a distinct variant name and distinct symbol
  versions — `libcrypto-upstream.so.<n>` with `OPENSSL_UPSTREAM_*` symbol
  versions. The dynamic linker identifies libraries by name rather than by
  path, so this is what allows these libraries and a distribution's own
  same-generation OpenSSL to be present in one process without being confused
  for one another.

FIPS provider modules are built from their own source release with `enable-fips`
and no other OpenSSL options, following the module's Security Policy.

## Building the packages

Builds run in containers, one per target distribution release, so no build
dependencies are installed on the host.

Requirements: `podman`, `make`, and `uv` for the test suite. For `aarch64`
builds on an `x86_64` host, `qemu-user-static` binfmt handlers must be
registered once.

```sh
make help                        # targets and the current matrix
make deb-bookworm                # one distribution release
make rpm-el9
make -j3 all                     # every stream package
make fips                        # FIPS provider module packages
make VERSION=4.0.2 deb-bookworm  # a different upstream version
make RUN_TESTS=1 deb-bookworm    # also run OpenSSL's own test suite
make test                        # package tests, in clean containers
make lint                        # shellcheck
make clean
```

Built packages are written to `output/<package>/<format>/<release>/`.

Each target runs `build/build-*.sh`, which starts the container for that
release and runs `packaging/<format>/build-in-container.sh` inside it: the
upstream tarball is downloaded, the templated packaging tree is filled in, and
`dpkg-buildpackage` or `rpmbuild` produces the packages. The scripts can be run
directly without `make`.

### Architectures

```sh
make ARCH=arm64 deb-bookworm
```

On an `x86_64` host, `aarch64` builds run under emulation. That is sufficient
to build correct packages, since the real `aarch64` toolchain is used rather
than a cross-compiler, but emulation is not a substitute for testing: OpenSSL
selects optimised code paths from the CPU features it detects at run time, so
`aarch64` packages should be tested on `aarch64` hardware.

## Testing

Two independent layers.

**OpenSSL's own test suite** runs at build time when `RUN_TESTS=1` is set. It is
off by default: a released tarball has already passed it, so it is used as a
check on a particular compiler and platform combination rather than on every
rebuild.

**Package tests** (`tests/`, pytest) install the built packages in a clean
container of the release they were built for and check the properties the
packaging is meant to guarantee: the installed layout, that the distribution's
OpenSSL is untouched, library and symbol naming, run-time library resolution,
configuration location, certificate verification against the trust store over a
real TLS connection, the trust-anchor choice, the shell environment helpers,
building and running a program against the development package, package
dependency metadata, and the FIPS activation lifecycle.

```sh
make test
make test PYTEST_ARGS='-k "bookworm or rpm-9"'
```

## Repository layout

```
Makefile                        task runner over the build scripts
build/                          host-side build drivers (podman)
packaging/common/               templates shared by both package families
packaging/deb/                  Debian and Ubuntu packaging
packaging/deb-fips/             FIPS module packaging, Debian and Ubuntu
packaging/rpm/                  Enterprise Linux packaging
packaging/rpm-fips/             FIPS module packaging, Enterprise Linux
tests/                          package test suite
```

## License

Apache License 2.0, the same terms as OpenSSL itself. See
[`LICENSE.txt`](LICENSE.txt).
