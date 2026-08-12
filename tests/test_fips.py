"""FIPS provider tests: install a stream plus a FIPS module, activate it with
`openssl-fips-enable`, and check the module loads under the stream's libcrypto
and enforces approved-only crypto. Also where cross-major loading (a 3.x module
under 4.x libcrypto) is exercised.

Parametrized over the WHOLE matrix: modules are built per release, like every
other package, and each release installs and activates its own build.
"""
import glob
import os
import re
import subprocess

import pytest

from conftest import (MATRIX, STREAM, ARCH, DATADIR, DEB_ARCH, RPM_ARCH, REPO,
                      PODMAN, APT_OPTS, DNF_OPTS, EXEC_TIMEOUT, _run,
                      install_packages, pkgdir,
                      remove_container, start_container)

FIPS_VERSION = os.environ.get("FIPS_VERSION", "3.1.2")

# Every pinned version the build produces, not just the one the tests exercise
# by default: the presence checks have to cover all of them or a missing module
# publishes unnoticed.
FIPS_VALIDATED = os.environ.get("FIPS_VALIDATED", FIPS_VERSION).split()

# Every release we publish for: the module has to install and load on all of them.
FIPS_TARGETS = MATRIX

# Version coexistence and switching are distro-independent, so those tests use a
# single container rather than repeating across the matrix.
MULTI_TARGET = ("deb", "bookworm", "debian:12")

# The CMVP certificate each validated source version holds, mirroring the
# Makefile's CERT_<version> variables. A version absent from here is expected to
# report itself as not validated.
CERTIFICATES = {"3.1.2": "4985"}

# The stream companion module: openssl<STREAM>-upstream-fips, installed at
# /opt/openssl/fips/<STREAM>/, NOT validated, upgrades with the stream. Its
# enable argument is the stream label, unlike a validated module's full version.
COMPANION = STREAM


def built_fips_versions():
    """Every VALIDATED module version with packages in output/, oldest first."""
    found = set()
    for d in glob.glob(os.path.join(REPO, "output", "openssl-fips*-upstream")):
        m = re.fullmatch(r"openssl-fips(\d+\.\d+\.\d+)-upstream", os.path.basename(d))
        if m:
            found.add(m.group(1))
    return sorted(found, key=lambda v: [int(x) for x in v.split(".")])


def _fips_subdir(fam, rel):
    return os.path.join("deb", rel) if fam == "deb" else os.path.join("rpm", f"el{rel}")


def _fips_dir(fam, rel, version=FIPS_VERSION):
    return os.path.join(REPO, "output", f"openssl-fips{version}-upstream",
                        _fips_subdir(fam, rel))


def _fips_pkgs_present(fam, rel, version=FIPS_VERSION):
    d = _fips_dir(fam, rel, version)
    if fam == "deb":
        return bool(glob.glob(os.path.join(
            d, f"openssl-fips{version}-upstream_*_{DEB_ARCH}.deb")))
    return bool(glob.glob(os.path.join(
        d, f"openssl-fips{version}-upstream-*.{RPM_ARCH}.rpm")))


def _companion_dir(fam, rel):
    return os.path.join(REPO, "output", f"openssl{STREAM}-upstream-fips",
                        _fips_subdir(fam, rel))


def _companion_pkg_glob(fam, rel):
    if fam == "deb":
        return os.path.join(_companion_dir(fam, rel),
                            f"openssl{STREAM}-upstream-fips_*_{DEB_ARCH}.deb")
    return os.path.join(_companion_dir(fam, rel),
                        f"openssl{STREAM}-upstream-fips-[0-9]*.{RPM_ARCH}.rpm")


def _companion_pkgs_present(fam, rel):
    return bool(glob.glob(_companion_pkg_glob(fam, rel)))


def _fips_install_script(fam, with_validated, with_companion):
    # binutils supplies readelf, for the module's ELF properties. Each module
    # kind rides along when built for this release: a run publishing only the
    # companion still has to load and activate it.
    validated_deb = f"/fips/openssl-fips{FIPS_VERSION}-upstream_*_{DEB_ARCH}.deb "
    validated_rpm = f"/fips/openssl-fips{FIPS_VERSION}-upstream-*.{RPM_ARCH}.rpm "
    companion_deb = f"/fips-companion/openssl{STREAM}-upstream-fips_*_{DEB_ARCH}.deb"
    companion_rpm = f"/fips-companion/openssl{STREAM}-upstream-fips-[0-9]*.{RPM_ARCH}.rpm"
    if fam == "deb":
        return (
            f"set -e; export DEBIAN_FRONTEND=noninteractive;"
            f" apt-get {APT_OPTS} update -qq >/dev/null; "
            f"apt-get {APT_OPTS} install -y --no-install-recommends binutils "
            f"/pkgs/openssl{STREAM}-upstream_*_{DEB_ARCH}.deb "
            + (validated_deb if with_validated else "")
            + (companion_deb if with_companion else "") + " >/dev/null 2>&1"
        )
    return (
        f"set -e; dnf install -y -q {DNF_OPTS} binutils "
        f"/pkgs/openssl{STREAM}-upstream-*.{RPM_ARCH}.rpm "
        + (validated_rpm if with_validated else "")
        + (companion_rpm if with_companion else "") + " >/dev/null 2>&1"
    )


class FipsTarget:
    def __init__(self, family, cid, validated_installed=False, companion_installed=False):
        self.family, self.cid = family, cid
        self.validated_installed = validated_installed
        self.companion_installed = companion_installed
        self.stream = STREAM
        self.prefix = f"/opt/openssl/{STREAM}"
        self.ossl = f"{self.prefix}/bin/openssl"
        self.helper = f"{self.prefix}/bin/openssl-fips-enable"

    def run(self, cmd, check=False, timeout=EXEC_TIMEOUT):
        r = _run([PODMAN, "exec", self.cid, "bash", "-c", cmd], timeout, cmd)
        if check and r.returncode != 0:
            raise AssertionError(f"cmd failed ({r.returncode}): {cmd}\n{r.stdout}\n{r.stderr}")
        return r

    def out(self, cmd):
        return self.run(cmd, check=True).stdout.strip()


def _needs_validated(t):
    if not t.validated_installed:
        pytest.skip(f"validated module {FIPS_VERSION} not built for this run")


@pytest.fixture(scope="module",
                params=FIPS_TARGETS,
                ids=[f"{f}-{r}" for f, r, _ in FIPS_TARGETS])
def fips_target(request):
    fam, rel, image = request.param
    # Either module kind is enough to be worth testing: a run may publish only
    # the companion, and gating on the validated module would silently skip it.
    with_validated = _fips_pkgs_present(fam, rel)
    with_companion = _companion_pkgs_present(fam, rel)
    if not (with_validated or with_companion):
        pytest.skip(f"no FIPS module packages for {fam}-{rel}")
    if not glob.glob(os.path.join(pkgdir(fam, rel), f"openssl{STREAM}-upstream*")):
        pytest.skip(f"stream {STREAM} packages for {fam}/{rel} not built")
    mounts = {pkgdir(fam, rel): "/pkgs", DATADIR: "/testdata"}
    if with_validated:
        mounts[_fips_dir(fam, rel)] = "/fips"
    if with_companion:
        mounts[_companion_dir(fam, rel)] = "/fips-companion"
    cid = install_packages(image, mounts,
                           _fips_install_script(fam, with_validated, with_companion),
                           f"fips {fam}-{rel}")
    try:
        yield FipsTarget(fam, cid, validated_installed=with_validated,
                         companion_installed=with_companion)
    finally:
        remove_container(cid)


def test_module_installed(fips_target):
    t = fips_target
    _needs_validated(t)
    assert t.run(f"test -e /opt/openssl/fips/{FIPS_VERSION}/fips.so").returncode == 0
    assert t.run(f"test -x {t.helper}").returncode == 0


def test_helper_list_reports_validation_status(fips_target):
    """`list` shows each installed module and whether it is NIST-validated."""
    t = fips_target
    _needs_validated(t)
    out = t.out(f"{t.helper} list")
    assert t.stream in out and FIPS_VERSION in out, out
    # 3.1.2 ships a 'validated' marker naming its CMVP certificate.
    if FIPS_VERSION == "3.1.2":
        assert "validated" in out and "4985" in out, out


def test_companion_module_installed_and_activates(fips_target):
    """The stream companion module: named after the stream, installed at a
    stream-stable path, reporting its real source version, activating and
    enforcing approved-only crypto on every release."""
    t = fips_target
    if not t.companion_installed:
        pytest.skip(f"companion module for stream {STREAM} not built")

    assert t.run(f"test -e /opt/openssl/fips/{COMPANION}/fips.so").returncode == 0
    # named after the stream, owned by the stream-named package
    pkg = f"openssl{STREAM}-upstream-fips"
    if t.family == "deb":
        owner = t.out(f"dpkg -S /opt/openssl/fips/{COMPANION}/fips.so")
        assert owner.startswith(pkg + ":"), owner
    else:
        assert t.out(f"rpm -qf /opt/openssl/fips/{COMPANION}/fips.so").startswith(pkg)
    # the version file records the actual source version and list reports it
    version = t.out(f"cat /opt/openssl/fips/{COMPANION}/version")
    assert version.startswith(STREAM + "."), version
    line = [l for l in t.out(f"{t.helper} list").splitlines()
            if l.strip().startswith(COMPANION + " ")]
    assert line and version in line[0] and "NOT NIST-validated" in line[0], line

    r = t.run(f"{t.helper} {COMPANION}")
    assert r.returncode == 0, f"enabling the companion failed:\n{r.stdout}\n{r.stderr}"
    assert "fips" in t.out(f"{t.ossl} list -providers")
    assert t.run(f"printf abc | {t.ossl} dgst -md5").returncode != 0, \
        "md5 must be blocked with the companion module active"
    t.run(f"{t.helper} disable", check=True)


def test_enable_and_provider_loads(fips_target):
    """The crux: fipsinstall + the module loading under this stream's libcrypto,
    selected by absolute path (config 'module' key), with nothing symlinked."""
    t = fips_target
    _needs_validated(t)
    en = t.run(f"{t.helper} {FIPS_VERSION}")
    assert en.returncode == 0, f"enable failed:\n{en.stdout}\n{en.stderr}"
    providers = t.run(f"{t.ossl} list -providers")
    assert "fips" in providers.stdout, providers.stdout + providers.stderr
    # the module is referenced by path, not copied/symlinked into the stream
    assert t.run(f"test -e {t.prefix}/lib64/ossl-modules/fips.so").returncode != 0, \
        "no fips.so should be symlinked into the stream's module directory"
    cnf = t.out(f"cat /etc/opt/openssl/{t.stream}/fipsmodule.cnf")
    assert f"/opt/openssl/fips/{FIPS_VERSION}/fips.so" in cnf, cnf


def test_fips_enforces_approved_only(fips_target):
    t = fips_target
    _needs_validated(t)
    t.run(f"{t.helper} {FIPS_VERSION}", check=True)
    ok = t.run(f"printf abc | {t.ossl} dgst -sha256")
    assert ok.returncode == 0, f"sha256 should work in FIPS mode:\n{ok.stderr}"
    blocked = t.run(f"printf abc | {t.ossl} dgst -md5")
    assert blocked.returncode != 0, "md5 must be blocked in FIPS mode"


def test_fips_loads_via_env_without_touching_system_config(fips_target):
    """Exercise the FIPS provider purely through OPENSSL_CONF /
    OPENSSL_CONF_INCLUDE / OPENSSL_MODULES, using the checked-in config at
    tests/data/fips-and-base.cnf, leaving the installed configuration
    untouched. Proves the module works independently of our activation helper.
    """
    t = fips_target
    _needs_validated(t)
    installed_cnf = f"/etc/opt/openssl/{t.stream}/openssl.cnf"
    before = t.run(f"cat {installed_cnf}").stdout
    script = f'''set -e
D=$(mktemp -d); mkdir -p "$D/modules"
cp /opt/openssl/fips/{FIPS_VERSION}/fips.so "$D/modules/fips.so"
cp /testdata/fips-and-base.cnf "$D/openssl.cnf"
{t.ossl} fipsinstall -provider_name fips -module "$D/modules/fips.so" \
    -out "$D/fipsmodule.cnf" >/dev/null 2>&1
export OPENSSL_CONF="$D/openssl.cnf" OPENSSL_CONF_INCLUDE="$D" OPENSSL_MODULES="$D/modules"
{t.ossl} list -providers | grep -q fips && echo FIPS_LOADED
printf abc | {t.ossl} dgst -sha256 >/dev/null 2>&1 && echo SHA256_OK
printf abc | {t.ossl} dgst -md5 >/dev/null 2>&1 && echo MD5_UNEXPECTED || echo MD5_BLOCKED
'''
    out = t.run(script)
    combined = out.stdout + out.stderr
    assert "FIPS_LOADED" in out.stdout, combined
    assert "SHA256_OK" in out.stdout, combined
    assert "MD5_BLOCKED" in out.stdout, combined
    assert t.run(f"cat {installed_cnf}").stdout == before, \
        "the installed openssl.cnf must not be modified"


@pytest.fixture
def module_bytes_restored(fips_target):
    """Puts the module file and the activation state back afterwards.

    This test corrupts a module on purpose. The container is shared by the rest
    of the module's tests, so leaving it corrupted on failure would turn one
    clear failure into a run of confusing ones.
    """
    t = fips_target
    module = f"/opt/openssl/fips/{FIPS_VERSION}/fips.so"
    t.run(f"cp {module} /tmp/fips.so.orig", check=True)
    try:
        yield module
    finally:
        t.run(f"cp /tmp/fips.so.orig {module}")
        t.run(f"{t.helper} {FIPS_VERSION}")


def test_verify_detects_stale_config(fips_target, module_bytes_restored):
    """`verify` confirms a good config and fails once the module changes."""
    t = fips_target
    _needs_validated(t)
    module = module_bytes_restored
    t.run(f"{t.helper} {FIPS_VERSION}", check=True)
    ok = t.run(f"{t.helper} verify")
    assert ok.returncode == 0, ok.stdout + ok.stderr

    t.run(f"printf x >> {module}", check=True)
    stale = t.run(f"{t.helper} verify")
    assert stale.returncode != 0, "verify should fail on a changed module"
    assert "STALE" in stale.stderr, stale.stdout + stale.stderr


def test_disable_restores_default(fips_target):
    t = fips_target
    _needs_validated(t)
    t.run(f"{t.helper} {FIPS_VERSION}", check=True)
    t.run(f"{t.helper} disable", check=True)
    assert t.run(f"printf abc | {t.ossl} dgst -md5").returncode == 0


def test_module_elf_properties(fips_target):
    """Properties the module must have on every family.

    No RUNPATH: it is dlopen'd by an already-loaded libcrypto, which satisfies its
    NEEDED, so it needs no search path of its own. RELRO and a non-executable
    stack come from the compiler defaults and hold regardless of what the
    packaging passes.
    """
    t = fips_target
    _needs_validated(t)
    module = f"/opt/openssl/fips/{FIPS_VERSION}/fips.so"
    dyn = t.out(f"readelf -dW {module}")
    assert "RUNPATH" not in dyn and "RPATH" not in dyn, dyn

    seg = t.out(f"readelf -lW {module}")
    assert "GNU_RELRO" in seg, "no RELRO segment"
    stack = [l for l in seg.splitlines() if "GNU_STACK" in l]
    assert stack, "no GNU_STACK segment (stack permissions unspecified)"
    assert "E" not in stack[0].rsplit(None, 2)[-2], f"executable stack: {stack[0]}"


def test_module_carries_the_distribution_link_flags(fips_target):
    """The module should get the distribution's link flags, as it does on rpm via
    %set_build_flags. On deb it does not: overriding dh_auto_configure bypasses
    where debhelper would supply dpkg-buildflags, so the link gets no LDFLAGS.

    Xfails only while the flag is genuinely absent, so fixing those rules makes
    this pass rather than leaving a stale expected failure.
    """
    t = fips_target
    _needs_validated(t)
    dyn = t.out(f"readelf -dW /opt/openssl/fips/{FIPS_VERSION}/fips.so")
    if t.family == "deb" and "BIND_NOW" not in dyn:
        pytest.xfail("deb-fips rules do not export dpkg-buildflags; see the docstring")
    assert "BIND_NOW" in dyn, f"the module did not get the distribution LDFLAGS:\n{dyn}"


# ---- several modules installed at once ---------------------------------------

# Module identifiers as the helper takes them: full versions for validated
# modules, the stream label for the companion.
MULTI_MODULES = built_fips_versions() + [COMPANION]


def _module_pkg_spec(fam, rel, module):
    """Package glob for a module id, as a path under the /output mount."""
    if module == COMPANION:
        pkg = f"openssl{STREAM}-upstream-fips"
    else:
        pkg = f"openssl-fips{module}-upstream"
    suffix = f"_*_{DEB_ARCH}.deb" if fam == "deb" else f"-[0-9]*.{RPM_ARCH}.rpm"
    return f"/output/{pkg}/{_fips_subdir(fam, rel)}/{pkg}{suffix}"


def _module_pkgs_present(fam, rel, module):
    if module == COMPANION:
        return _companion_pkgs_present(fam, rel)
    return _fips_pkgs_present(fam, rel, module)


def _multi_install_script(fam, rel, modules):
    specs = [_module_pkg_spec(fam, rel, m) for m in modules]
    if fam == "deb":
        return (f"set -e; export DEBIAN_FRONTEND=noninteractive;"
            f" apt-get {APT_OPTS} update -qq >/dev/null; "
                f"apt-get {APT_OPTS} install -y --no-install-recommends binutils "
                f"/pkgs/openssl{STREAM}-upstream_*_{DEB_ARCH}.deb " + " ".join(specs)
                + " >/dev/null 2>&1")
    return (f"set -e; dnf install -y -q {DNF_OPTS} binutils "
            f"/pkgs/openssl{STREAM}-upstream-*.{RPM_ARCH}.rpm " + " ".join(specs)
            + " >/dev/null 2>&1")


def _multi_container():
    if len(MULTI_MODULES) < 2:
        pytest.skip("need two FIPS modules built (e.g. make fips-deb fips-rpm)")
    fam, rel, image = MULTI_TARGET
    for m in MULTI_MODULES:
        if not _module_pkgs_present(fam, rel, m):
            pytest.skip(f"FIPS module {m} packages for {fam}-{rel} not built")
    if not glob.glob(os.path.join(pkgdir(fam, rel), f"openssl{STREAM}-upstream*")):
        pytest.skip(f"stream {STREAM} packages for {fam}/{rel} not built")

    cid = install_packages(image, {pkgdir(fam, rel): "/pkgs",
                                  os.path.join(REPO, "output"): "/output",
                                  DATADIR: "/testdata"},
                          _multi_install_script(fam, rel, MULTI_MODULES),
                          f"fips multi {fam}-{rel}")
    try:
        yield FipsTarget(fam, cid, companion_installed=True)
    finally:
        remove_container(cid)


@pytest.fixture(scope="module")
def fips_multi():
    yield from _multi_container()


@pytest.fixture
def fips_multi_fresh():
    """Own container, for the tests that uninstall a module."""
    yield from _multi_container()


def test_modules_coexist_and_report_their_validation_status(fips_multi):
    """Validated modules and the stream companion install side by side under
    /opt/openssl/fips/, and `list` distinguishes them — the distinction a user
    has to be able to see before choosing."""
    t = fips_multi
    out = t.out(f"{t.helper} list")
    for m in MULTI_MODULES:
        assert m in out, f"{m} missing from list output:\n{out}"
        assert t.run(f"test -e /opt/openssl/fips/{m}/fips.so").returncode == 0

    for line in out.splitlines():
        for m in MULTI_MODULES:
            if line.strip().startswith(m + " "):
                if m in CERTIFICATES:
                    assert "validated," in line and CERTIFICATES[m] in line, line
                elif m == COMPANION:
                    assert "tracks" in line and "NOT NIST-validated" in line, line
                else:
                    assert "NOT NIST-validated" in line, line


@pytest.mark.parametrize("module", MULTI_MODULES)
def test_each_module_can_be_activated(fips_multi, module):
    """Every installed module must activate for this stream and enforce
    approved-only crypto — including a module from a different major than the
    libcrypto loading it."""
    t = fips_multi
    r = t.run(f"{t.helper} {module}")
    assert r.returncode == 0, f"enabling {module} failed:\n{r.stdout}\n{r.stderr}"

    providers = t.run(f"{t.ossl} list -providers")
    assert "fips" in providers.stdout, providers.stdout + providers.stderr
    cnf = t.out(f"cat /etc/opt/openssl/{t.stream}/fipsmodule.cnf")
    assert f"/opt/openssl/fips/{module}/fips.so" in cnf, cnf
    assert t.out(f"cat /etc/opt/openssl/{t.stream}/fips-enabled") == module

    assert t.run(f"printf abc | {t.ossl} dgst -sha256").returncode == 0
    assert t.run(f"printf abc | {t.ossl} dgst -md5").returncode != 0, \
        f"md5 must be blocked with module {module} active"
    assert t.run(f"{t.helper} verify").returncode == 0


def test_switching_modules_rewrites_the_configuration(fips_multi):
    """Switching leaves no trace of the previous module: the recorded module, the
    configuration and the MAC all move together, so `verify` stays truthful."""
    t = fips_multi
    first, second = MULTI_MODULES[0], MULTI_MODULES[-1]

    t.run(f"{t.helper} {first}", check=True)
    t.run(f"{t.helper} {second}", check=True)

    cnf = t.out(f"cat /etc/opt/openssl/{t.stream}/fipsmodule.cnf")
    assert f"/opt/openssl/fips/{second}/fips.so" in cnf, cnf
    assert f"/opt/openssl/fips/{first}/fips.so" not in cnf, \
        f"the previous module is still referenced:\n{cnf}"
    assert t.out(f"cat /etc/opt/openssl/{t.stream}/fips-enabled") == second
    assert t.run(f"{t.helper} verify").returncode == 0
    assert f"Enabled for {t.stream}: {second}" in t.out(f"{t.helper} list")


def test_companion_reinstall_reactivates_it(fips_multi_fresh):
    """The companion upgrades with the stream, which replaces module bytes under
    an enabled configuration. The package's postinst must re-run the activation
    (self-tests and a fresh MAC) so the provider keeps loading — silently
    breaking FIPS on `apt upgrade` is not acceptable. Reinstalling exercises the
    same maintainer-script path as an upgrade."""
    t = fips_multi_fresh
    t.run(f"{t.helper} {COMPANION}", check=True)
    # Wreck the recorded module MAC to prove the reinstall is what repairs it.
    # It has to be the module-mac value: the MAC is computed over fips.so and
    # only recorded in the cnf, so appended garbage would be ignored.
    t.run(f"sed -i 's/^module-mac.*/module-mac = 00:00/' "
          f"/etc/opt/openssl/{t.stream}/fipsmodule.cnf", check=True)
    assert t.run(f"{t.helper} verify").returncode != 0, \
        "the MAC should be broken before the reinstall"

    r = t.run(f"{'dpkg -i' if t.family == 'deb' else 'rpm -U --replacepkgs'} "
              f"{_module_pkg_spec(t.family, MULTI_TARGET[1], COMPANION)} 2>&1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "re-activated" in (r.stdout + r.stderr), r.stdout + r.stderr

    assert t.run(f"{t.helper} verify").returncode == 0, \
        "the maintainer script did not re-activate the module"
    assert t.run(f"printf abc | {t.ossl} dgst -md5").returncode != 0, \
        "FIPS enforcement must survive a module upgrade"


def test_removing_an_inactive_module_leaves_the_active_one_alone(fips_multi_fresh):
    t = fips_multi_fresh
    active, removed = MULTI_MODULES[0], MULTI_MODULES[-1]
    t.run(f"{t.helper} {active}", check=True)

    r = t.run(_remove_cmd(t.family, removed))
    assert r.returncode == 0, r.stdout + r.stderr

    assert t.run(f"test -e /opt/openssl/fips/{removed}/fips.so").returncode != 0
    assert t.run(f"{t.helper} verify").returncode == 0, "the active module was disturbed"
    assert t.run(f"printf abc | {t.ossl} dgst -md5").returncode != 0, \
        "FIPS enforcement was lost when an unrelated module was removed"


def test_removing_the_active_module_is_reported_not_silent(fips_multi_fresh):
    """Nothing deactivates FIPS behind the administrator's back when the module
    they selected goes away — but `verify` has to say so plainly, and the stream
    must not fall back to unapproved crypto."""
    t = fips_multi_fresh
    active = MULTI_MODULES[0]
    t.run(f"{t.helper} {active}", check=True)

    r = t.run(_remove_cmd(t.family, active))
    assert r.returncode == 0, r.stdout + r.stderr

    v = t.run(f"{t.helper} verify")
    assert v.returncode != 0, "verify should fail once the active module is gone"
    assert "no longer installed" in v.stderr, v.stdout + v.stderr
    assert t.run(f"printf abc | {t.ossl} dgst -md5").returncode != 0, \
        "removing the module must not silently re-enable unapproved crypto"


def _remove_cmd(fam, module):
    if module == COMPANION:
        pkg = f"openssl{STREAM}-upstream-fips"
    else:
        pkg = f"openssl-fips{module}-upstream"
    if fam == "deb":
        return f"DEBIAN_FRONTEND=noninteractive apt-get remove -y {pkg} 2>&1"
    return f"dnf remove -y {pkg} 2>&1"
