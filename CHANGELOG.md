# Changelog

Changes to the **packaging** — what the packages install, how they are named and
how they are built. For changes to OpenSSL itself, see the upstream
[CHANGES](https://github.com/openssl/openssl/blob/master/CHANGES.md) for the
version a package carries; on Debian and Ubuntu it is also installed as
`/usr/share/doc/<package>/changelog.gz`.

One entry per publish, headed by the package version it produced:
`<upstream version>-<package revision>`. A revision bump with the same upstream
version means the packaging changed, and the entry says how.

## Unreleased

Nothing has been published yet. Packaging decisions that will matter to anyone
installing the first release:

- **FIPS provider modules come in two kinds.** A NIST-validated source version
  is a pinned package named for that version (`openssl-fips3.1.2-upstream`); it
  never moves to different bytes. Each stream additionally has a companion
  module named for the stream (`openssl4.0-upstream-fips`), which is **not**
  validated and upgrades in step with the stream.
- **FIPS provider modules are built per distribution release**, like every
  other package, so each release installs a module built on its own toolchain.
- **Source tarballs are verified before a build proceeds** — a SHA-256 pinned in
  this repository, then the upstream release signature against a keyring
  committed alongside it.
- **Package versions name the release they were built for.** deb: a suite
  qualifier in the revision (`4.0.1-1+deb12`, `+ubuntu24.04`); rpm: the usual
  dist tag (`.el9`). Every distribution release gets its own build, and two
  builds never share a file name.
- **Packages install under `/opt/openssl/<stream>`** with configuration in
  `/etc/opt/openssl/<stream>`, and never touch the distribution's own OpenSSL:
  no entry is added to the runtime linker search path, and the libraries carry
  distinct SONAMEs and symbol versions.
