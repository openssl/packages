"""FIPS provider tests: install a stream + the FIPS module + the helper in a
clean container, activate FIPS with `openssl-fips-enable`, and check that the
module loads under the stream's libcrypto and enforces approved-only crypto.

This is where cross-major loading (a 3.x-validated module under a 4.x
libcrypto) is exercised empirically. Parametrized over
one deb and one rpm target; skips if the FIPS packages aren't built yet.
"""
import glob
import os
import subprocess

import pytest

from conftest import STREAM, ARCH, DEB_ARCH, RPM_ARCH, REPO, PODMAN, pkgdir

FIPS_VERSION = os.environ.get("FIPS_VERSION", "3.1.2")

# (family, release, image) — FIPS module is distro-independent; test on one of each.
FIPS_TARGETS = [
    ("deb", "bookworm", "debian:12"),
    ("rpm", "9", "almalinux:9"),
]


def _fips_dir(fam):
    return os.path.join(REPO, "output", f"openssl-fips{FIPS_VERSION}-upstream",
                        "deb" if fam == "deb" else "rpm")


def _fips_pkgs_present(fam):
    d = _fips_dir(fam)
    if fam == "deb":
        return bool(glob.glob(os.path.join(
            d, f"openssl-fips{FIPS_VERSION}-upstream_*_{DEB_ARCH}.deb")))
    return bool(glob.glob(os.path.join(
        d, f"openssl-fips{FIPS_VERSION}-upstream-*.{RPM_ARCH}.rpm")))


def _fips_install_script(fam):
    if fam == "deb":
        return (
            "set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null; "
            "apt-get install -y --no-install-recommends "
            f"/pkgs/openssl{STREAM}-upstream_*_{DEB_ARCH}.deb "
            f"/fips/openssl-fips{FIPS_VERSION}-upstream_*_{DEB_ARCH}.deb >/dev/null 2>&1"
        )
    return (
        "set -e; dnf install -y -q "
        f"/pkgs/openssl{STREAM}-upstream-*.{RPM_ARCH}.rpm "
        f"/fips/openssl-fips{FIPS_VERSION}-upstream-*.{RPM_ARCH}.rpm >/dev/null 2>&1"
    )


class FipsTarget:
    def __init__(self, family, cid):
        self.family, self.cid = family, cid
        self.stream = STREAM
        self.prefix = f"/opt/openssl/{STREAM}"
        self.ossl = f"{self.prefix}/bin/openssl"
        self.helper = f"{self.prefix}/bin/openssl-fips-enable"

    def run(self, cmd, check=False):
        r = subprocess.run([PODMAN, "exec", self.cid, "bash", "-c", cmd],
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            raise AssertionError(f"cmd failed ({r.returncode}): {cmd}\n{r.stdout}\n{r.stderr}")
        return r

    def out(self, cmd):
        return self.run(cmd, check=True).stdout


@pytest.fixture(scope="module",
                params=FIPS_TARGETS,
                ids=[f"{f}-{r}" for f, r, _ in FIPS_TARGETS])
def fips_target(request):
    fam, rel, image = request.param
    if not _fips_pkgs_present(fam):
        pytest.skip(f"FIPS {FIPS_VERSION} packages for {fam} not built")
    if not glob.glob(os.path.join(pkgdir(fam, rel), f"openssl{STREAM}-upstream*")):
        pytest.skip(f"stream {STREAM} packages for {fam}/{rel} not built")
    fipsdir = _fips_dir(fam)
    datadir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    cid = subprocess.run(
        [PODMAN, "run", "-d", "--platform", f"linux/{ARCH}",
         "-v", f"{pkgdir(fam, rel)}:/pkgs:ro", "-v", f"{fipsdir}:/fips:ro",
         "-v", f"{datadir}:/testdata:ro",
         image, "sleep", "infinity"],
        capture_output=True, text=True, check=True).stdout.strip()
    try:
        inst = subprocess.run([PODMAN, "exec", cid, "bash", "-c", _fips_install_script(fam)],
                              capture_output=True, text=True)
        assert inst.returncode == 0, f"install failed:\n{inst.stdout}\n{inst.stderr}"
        yield FipsTarget(fam, cid)
    finally:
        subprocess.run([PODMAN, "rm", "-f", cid], capture_output=True)


def test_module_installed(fips_target):
    t = fips_target
    assert t.run(f"test -e /opt/openssl/fips/{FIPS_VERSION}/fips.so").returncode == 0
    assert t.run(f"test -x {t.helper}").returncode == 0


def test_helper_list_reports_validation_status(fips_target):
    """`list` shows each installed module and whether it is NIST-validated."""
    t = fips_target
    out = t.out(f"{t.helper} list")
    assert t.stream in out and FIPS_VERSION in out, out
    # 3.1.2 ships a 'validated' marker naming its CMVP certificate.
    if FIPS_VERSION == "3.1.2":
        assert "validated" in out and "4985" in out, out


def test_enable_and_provider_loads(fips_target):
    """The crux: fipsinstall + the module loading under this stream's libcrypto,
    selected by absolute path (config 'module' key), with nothing symlinked."""
    t = fips_target
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


def test_verify_detects_stale_config(fips_target):
    """`verify` confirms a good config and fails once the module changes."""
    t = fips_target
    module = f"/opt/openssl/fips/{FIPS_VERSION}/fips.so"
    t.run(f"{t.helper} {FIPS_VERSION}", check=True)
    ok = t.run(f"{t.helper} verify")
    assert ok.returncode == 0, ok.stdout + ok.stderr

    t.run(f"cp {module} /tmp/f.so && printf x >> {module}", check=True)
    stale = t.run(f"{t.helper} verify")
    assert stale.returncode != 0, "verify should fail on a changed module"
    assert "STALE" in stale.stderr, stale.stdout + stale.stderr

    t.run(f"cp /tmp/f.so {module}", check=True)          # restore the module
    t.run(f"{t.helper} {FIPS_VERSION}", check=True)


def test_disable_restores_default(fips_target):
    t = fips_target
    t.run(f"{t.helper} {FIPS_VERSION}", check=True)
    t.run(f"{t.helper} disable", check=True)
    assert t.run(f"printf abc | {t.ossl} dgst -md5").returncode == 0
