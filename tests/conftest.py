"""Layer-3 package tests: install each built package in a clean container and
assert the as-installed properties the packaging is meant to guarantee.

Architecture: pytest runs on the host and drives target containers via podman.
The `target` fixture is parametrized over the release matrix — one long-lived
container per target, package installed once, reused by every test. A target
with no built packages is skipped (never silently dropped).

    STREAM=4.0 pytest tests/                 # all built targets
    pytest tests/ -k "deb-jammy or el9"      # a subset

Tests that reach the public internet are marked `network` and deselected unless
RUN_NETWORK_TESTS=1; everything else is self-contained, TLS included (see the
`tls_server` fixture, which runs a server behind a CA in the container's own
system trust store).
"""
import glob
import os
import re
import shutil
import subprocess

import pytest

STREAM = os.environ.get("STREAM", "4.0")
# Must match what the packages under test were built with; make test passes it.
REVISION = os.environ.get("REVISION", "1")
ARCH = os.environ.get("ARCH", "amd64")            # amd64 | arm64
DEB_ARCH = {"amd64": "amd64", "arm64": "arm64"}[ARCH]
RPM_ARCH = {"amd64": "x86_64", "arm64": "aarch64"}[ARCH]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATADIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PODMAN = shutil.which("podman") or "podman"

# (family, release, image) — one line per release. Kept in step with the
# Makefile's build targets by tests/test_matrix_completeness.py.
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


def target_name(fam, rel):
    """The Makefile target that builds this matrix entry."""
    return f"deb-{rel}" if fam == "deb" else f"rpm-el{rel}"


def pkgdir(fam, rel, stream=STREAM):
    # Output layout: output/<package>/deb/<suite>  |  output/<package>/rpm/el<el>
    base = os.path.join(REPO, "output", f"openssl{stream}-upstream")
    return (os.path.join(base, "deb", rel) if fam == "deb"
            else os.path.join(base, "rpm", f"el{rel}"))


def _main_pkgs(fam, rel, stream=STREAM):
    d = pkgdir(fam, rel, stream)
    if fam == "deb":
        return glob.glob(os.path.join(d, f"openssl{stream}-upstream_*_{DEB_ARCH}.deb"))
    return [p for p in glob.glob(os.path.join(d, f"openssl{stream}-upstream-*.{RPM_ARCH}.rpm"))
            if not any(x in os.path.basename(p)
                       for x in ("-devel-", "-debuginfo-", "-debugsource-"))]


def built_streams():
    """Every stream that has packages in output/, newest label first.

    Used by the coexistence tests, which need a second stream installed
    alongside STREAM and skip when only one has been built.
    """
    found = set()
    for d in glob.glob(os.path.join(REPO, "output", "openssl*-upstream")):
        m = re.fullmatch(r"openssl(\d+\.\d+)-upstream", os.path.basename(d))
        if m:
            found.add(m.group(1))
    return sorted(found, key=lambda s: [int(x) for x in s.split(".")], reverse=True)


def _install_script(fam):
    # The distro's own openssl CLI and development headers are installed
    # deliberately: several tests compare against it to prove coexistence, and
    # not every base image ships it (almalinux:10 has openssl-libs but no
    # openssl package). ca-certificates provides the system trust store and the
    # update-ca-* tools the trust-anchor tests drive.
    if fam == "deb":
        return (
            "set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null; "
            "apt-get install -y --no-install-recommends binutils gcc libc6-dev pkg-config "
            "ca-certificates openssl libssl-dev "
            f"/pkgs/openssl{STREAM}-upstream_*_{DEB_ARCH}.deb "
            f"/pkgs/openssl{STREAM}-upstream-dev_*_{DEB_ARCH}.deb "
            ">/dev/null 2>&1"
        )
    return (
        "set -e; dnf install -y -q binutils gcc glibc-devel pkgconf-pkg-config "
        "ca-certificates openssl openssl-devel "
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


def start_container(image, mounts):
    """Run a detached container with {host_path: container_path} mounted read-only."""
    argv = [PODMAN, "run", "-d", "--platform", f"linux/{ARCH}"]
    for host, dest in mounts.items():
        argv += ["-v", f"{host}:{dest}:ro"]
    argv += [image, "sleep", "infinity"]
    return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture(scope="session",
                params=MATRIX,
                ids=[f"{f}-{r}" for f, r, _ in MATRIX])
def target(request):
    if not shutil.which("podman"):
        pytest.skip("podman not available")
    fam, rel, image = request.param
    if not _main_pkgs(fam, rel):
        pytest.skip(f"no built packages in {pkgdir(fam, rel)} — build first")

    cid = start_container(image, {pkgdir(fam, rel): "/pkgs", DATADIR: "/testdata"})
    try:
        # The install itself is a test: an unmet libssl.so.N (bad Provides/Requires
        # filtering) would fail right here.
        inst = subprocess.run([PODMAN, "exec", cid, "bash", "-c", _install_script(fam)],
                              capture_output=True, text=True)
        assert inst.returncode == 0, f"package install failed:\n{inst.stdout}\n{inst.stderr}"
        yield Target(fam, rel, image, cid)
    finally:
        subprocess.run([PODMAN, "rm", "-f", cid], capture_output=True)


# ---- a TLS server the container itself trusts ------------------------------

TLS_DIR = "/opt/tls-test"
TLS_PORT = 4433

# Generated with the distro's openssl, so our client is talking to an
# independent implementation. The CA goes into the distribution's trust store,
# which is what our stream's cert.pem symlink resolves to — so a successful
# handshake proves the system anchors really are honoured, with no internet.
_TLS_SETUP = f"""set -e
D={TLS_DIR}; mkdir -p "$D"
SYS=/usr/bin/openssl
"$SYS" req -x509 -newkey rsa:2048 -nodes -sha256 -days 2 \
    -subj "/CN=openssl-packages test CA" -keyout "$D/ca.key" -out "$D/ca.crt" 2>/dev/null
"$SYS" req -new -newkey rsa:2048 -nodes -sha256 \
    -subj "/CN=localhost" -keyout "$D/server.key" -out "$D/server.csr" 2>/dev/null
printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\\n' > "$D/ext"
"$SYS" x509 -req -in "$D/server.csr" -CA "$D/ca.crt" -CAkey "$D/ca.key" \
    -CAcreateserial -days 2 -sha256 -extfile "$D/ext" -out "$D/server.crt" 2>/dev/null
if [ -d /usr/local/share/ca-certificates ]; then
    cp "$D/ca.crt" /usr/local/share/ca-certificates/openssl-packages-test.crt
    update-ca-certificates >/dev/null 2>&1
else
    cp "$D/ca.crt" /etc/pki/ca-trust/source/anchors/openssl-packages-test.crt
    update-ca-trust extract >/dev/null 2>&1
fi
nohup "$SYS" s_server -www -quiet -accept {TLS_PORT} \
    -cert "$D/server.crt" -key "$D/server.key" </dev/null >/tmp/s_server.log 2>&1 &
for _ in $(seq 1 50); do
    (exec 3<>/dev/tcp/127.0.0.1/{TLS_PORT}) 2>/dev/null && exit 0
    sleep 0.2
done
echo "s_server never came up" >&2; cat /tmp/s_server.log >&2; exit 1
"""


class LocalTLS:
    """A TLS endpoint in the target container, trusted via the system store."""

    def __init__(self, target):
        self.target = target
        self.host, self.port = "localhost", TLS_PORT
        self.ca_file = f"{TLS_DIR}/ca.crt"

    def client_cmd(self, *extra):
        return (f"echo Q | {self.target.prefix}/bin/openssl s_client "
                f"-connect 127.0.0.1:{self.port} -servername {self.host} "
                f"-verify_hostname {self.host} -verify_return_error -brief "
                + " ".join(extra) + " 2>&1")

    def verifies(self, *extra):
        r = self.target.run(self.client_cmd(*extra))
        return "Verification: OK" in (r.stdout + r.stderr)


@pytest.fixture(scope="session")
def tls_server(target):
    r = target.run(_TLS_SETUP)
    assert r.returncode == 0, f"could not start the local TLS server:\n{r.stdout}\n{r.stderr}"
    return LocalTLS(target)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: reaches the public internet; needs RUN_NETWORK_TESTS=1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_NETWORK_TESTS"):
        return
    skip = pytest.mark.skip(reason="set RUN_NETWORK_TESTS=1 to run tests that need the internet")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
