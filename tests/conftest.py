"""Layer-3 package tests: install each built package in a clean container and
assert the as-installed properties the packaging is meant to guarantee.

Architecture: pytest runs on the host and drives target containers via podman.
The `target` fixture is parametrized over the release matrix — one long-lived
container per target, package installed once, reused by every test. A target
with no built packages is skipped (never silently dropped).

    STREAM=4.0 pytest tests/                 # all built targets
    pytest tests/ -k "deb-jammy or el9"      # a subset
"""
import glob
import os
import shutil
import subprocess

import pytest

STREAM = os.environ.get("STREAM", "4.0")
ARCH = os.environ.get("ARCH", "amd64")            # amd64 | arm64
DEB_ARCH = {"amd64": "amd64", "arm64": "arm64"}[ARCH]
RPM_ARCH = {"amd64": "x86_64", "arm64": "aarch64"}[ARCH]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PODMAN = shutil.which("podman") or "podman"

# (family, release, image) — one line per release, mirrors build/build-all.sh.
MATRIX = [
    ("deb", "bullseye", "debian:11"),
    ("deb", "bookworm", "debian:12"),
    ("deb", "trixie",   "debian:13"),
    ("deb", "focal",    "ubuntu:20.04"),
    ("deb", "jammy",    "ubuntu:22.04"),
    ("deb", "noble",    "ubuntu:24.04"),
    ("deb", "resolute", "ubuntu:26.04"),
    ("rpm", "9",  "almalinux:9"),
    ("rpm", "10", "almalinux:10"),
]


def pkgdir(fam, rel):
    # Output layout: output/<package>/deb/<suite>  |  output/<package>/rpm/el<el>
    base = os.path.join(REPO, "output", f"openssl{STREAM}-upstream")
    return (os.path.join(base, "deb", rel) if fam == "deb"
            else os.path.join(base, "rpm", f"el{rel}"))


def _main_pkgs(fam, rel):
    d = pkgdir(fam, rel)
    if fam == "deb":
        return glob.glob(os.path.join(d, f"openssl{STREAM}-upstream_*_{DEB_ARCH}.deb"))
    return [p for p in glob.glob(os.path.join(d, f"openssl{STREAM}-upstream-*.{RPM_ARCH}.rpm"))
            if not any(x in os.path.basename(p)
                       for x in ("-devel-", "-debuginfo-", "-debugsource-"))]


def _install_script(fam):
    # The distro's own openssl CLI is installed deliberately: several tests
    # compare against it to prove coexistence, and not every base image ships
    # it (almalinux:10 has openssl-libs but no openssl package).
    if fam == "deb":
        return (
            "set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null; "
            "apt-get install -y --no-install-recommends binutils gcc libc6-dev pkg-config "
            "openssl "
            f"/pkgs/openssl{STREAM}-upstream_*_{DEB_ARCH}.deb "
            f"/pkgs/openssl{STREAM}-upstream-dev_*_{DEB_ARCH}.deb "
            ">/dev/null 2>&1"
        )
    return (
        "set -e; dnf install -y -q binutils gcc glibc-devel pkgconf-pkg-config openssl "
        f"/pkgs/openssl{STREAM}-upstream-*.{RPM_ARCH}.rpm >/dev/null 2>&1"
    )


class Target:
    def __init__(self, family, release, image, cid):
        self.family, self.release, self.image, self.cid = family, release, image, cid
        self.stream = STREAM
        self.prefix = f"/opt/openssl/{STREAM}"

    def run(self, cmd, check=False):
        r = subprocess.run([PODMAN, "exec", self.cid, "bash", "-c", cmd],
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            raise AssertionError(f"cmd failed ({r.returncode}): {cmd}\n{r.stdout}\n{r.stderr}")
        return r

    def out(self, cmd):
        return self.run(cmd, check=True).stdout.strip()


@pytest.fixture(scope="session",
                params=MATRIX,
                ids=[f"{f}-{r}" for f, r, _ in MATRIX])
def target(request):
    if not shutil.which("podman"):
        pytest.skip("podman not available")
    fam, rel, image = request.param
    if not _main_pkgs(fam, rel):
        pytest.skip(f"no built packages in {pkgdir(fam, rel)} — build first")

    cid = subprocess.run(
        [PODMAN, "run", "-d", "--platform", f"linux/{ARCH}",
         "-v", f"{pkgdir(fam, rel)}:/pkgs:ro", image, "sleep", "infinity"],
        capture_output=True, text=True, check=True).stdout.strip()
    try:
        # The install itself is a test: an unmet libssl.so.N (bad Provides/Requires
        # filtering) would fail right here.
        inst = subprocess.run([PODMAN, "exec", cid, "bash", "-c", _install_script(fam)],
                              capture_output=True, text=True)
        assert inst.returncode == 0, f"package install failed:\n{inst.stdout}\n{inst.stderr}"
        yield Target(fam, rel, image, cid)
    finally:
        subprocess.run([PODMAN, "rm", "-f", cid], capture_output=True)
