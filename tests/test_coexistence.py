"""Two OpenSSL library families alive in one process — the outcome the isolation
machinery exists for, which the rest of the suite only checks statically.

Two shapes, built from real sources under tests/data: dual_libcrypto.c dlopens
both libcryptos by path in either order, and plugin_host.c + plugin.c is a
program linked against the system libcrypto loading a plugin linked against
ours. Both sides must return SHA-256("abc") while sharing the process.
"""
import subprocess

import pytest

from conftest import (DATADIR, PODMAN, STREAM, built_streams, pkgdir,
                      start_container, _main_pkgs)

SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def _system_libcrypto(target):
    """The distribution's libcrypto, as the loader resolves it for /usr/bin/openssl.

    Fully resolved, because ldd reports the /lib path while /proc/self/maps reports
    the /usr/lib one on merged-usr systems.
    """
    out = target.out(
        "ldd /usr/bin/openssl 2>/dev/null | awk '/libcrypto\\.so/ {print $3}'")
    path = out.splitlines()[0].strip() if out else ""
    assert path and target.run(f"test -e {path}").returncode == 0, \
        f"could not locate the distribution libcrypto (ldd said {out!r})"
    return target.out(f"readlink -f {path}")


def _our_libcrypto(target):
    path = target.out(f"ls {target.prefix}/lib64/libcrypto-upstream.so.*").split()[0]
    return target.out(f"readlink -f {path}")


def _tagged(stdout):
    """Collect the repeated tagged lines the C helpers print."""
    got = {"VERSION": [], "DIGEST": [], "MAPPED": []}
    for line in stdout.splitlines():
        tag, _, rest = line.partition(" ")
        if tag in got:
            got[tag].append(rest.strip())
    return got


@pytest.fixture
def dual_binary(target):
    """Compile dual_libcrypto.c in the target; it links nothing but libdl."""
    r = target.run("gcc -O0 -o /tmp/dual /testdata/dual_libcrypto.c -ldl")
    assert r.returncode == 0, f"could not build dual_libcrypto.c:\n{r.stderr}"
    return "/tmp/dual"


@pytest.mark.parametrize("order", ["system-first", "upstream-first"])
def test_both_libcryptos_load_and_work_in_one_process(target, dual_binary, order):
    ours, theirs = _our_libcrypto(target), _system_libcrypto(target)
    first, second = ((theirs, ours) if order == "system-first" else (ours, theirs))

    r = target.run(f"{dual_binary} {first} {second}")
    assert r.returncode == 0, f"loading both failed ({order}):\n{r.stdout}\n{r.stderr}"

    got = _tagged(r.stdout)
    assert len(got["VERSION"]) == 2, got

    # Each object reports its own version: the second dlopen was not handed the
    # first object, and neither load was quietly skipped.
    versions = [v.split()[1] for v in got["VERSION"]]
    assert len(set(versions)) == 2, f"both reported the same version: {versions}"
    ours_reported = [v for v in versions if v.startswith(target.stream + ".")]
    assert len(ours_reported) == 1, f"expected exactly one {target.stream}.x: {versions}"

    # Both computed the digest correctly while sharing the process.
    assert got["DIGEST"] == [SHA256_ABC, SHA256_ABC], got["DIGEST"]

    # Both files are genuinely mapped at the same time.
    mapped = {m.strip() for m in got["MAPPED"]}
    assert ours in mapped, f"{ours} not mapped: {sorted(mapped)}"
    assert theirs in mapped, f"{theirs} not mapped: {sorted(mapped)}"


def test_system_linked_host_can_dlopen_an_upstream_linked_plugin(target):
    """The real-world shape: a program built against the distribution's OpenSSL
    loads a plugin built against ours, and both keep working."""
    build = (
        "set -e; "
        # The plugin uses our pkg-config, so it gets our SONAMEs and RUNPATH.
        f". {target.prefix}/enable; "
        "gcc -O0 -fPIC -shared -o /tmp/plugin.so /testdata/plugin.c "
        "$(pkg-config --cflags --libs libcrypto); "
        # The host is built after reverting, so pkg-config resolves to the
        # distribution's libcrypto.pc and its system headers.
        "openssl_upstream_deactivate; "
        "gcc -O0 -o /tmp/host /testdata/plugin_host.c "
        "$(pkg-config --cflags --libs libcrypto) -ldl"
    )
    r = target.run(build)
    assert r.returncode == 0, f"build failed:\n{r.stdout}\n{r.stderr}"

    host_needed = target.out("readelf -dW /tmp/host | grep NEEDED")
    assert "[libcrypto.so." in host_needed, \
        f"host is not linked against the distribution libcrypto:\n{host_needed}"
    plugin_needed = target.out("readelf -dW /tmp/plugin.so | grep NEEDED")
    assert "libcrypto-upstream.so." in plugin_needed, plugin_needed

    r = target.run("/tmp/host /tmp/plugin.so")
    assert r.returncode == 0, f"host+plugin failed:\n{r.stdout}\n{r.stderr}"

    out = dict(line.split(" ", 1) for line in r.stdout.splitlines() if " " in line)
    host_ver = out["HOST_VERSION"].split()[1]
    plugin_ver = out["PLUGIN_VERSION"].split()[1]
    assert plugin_ver.startswith(target.stream + "."), \
        f"the plugin bound to the wrong libcrypto: {plugin_ver}"
    assert not host_ver.startswith(target.stream + "."), \
        f"the host bound to our libcrypto: {host_ver}"

    assert out["HOST_DIGEST"] == SHA256_ABC, out
    assert out["PLUGIN_DIGEST"] == SHA256_ABC, out
    # The host's own library still works with the plugin's resident alongside it.
    assert out["HOST_DIGEST_AFTER"] == SHA256_ABC, out


# ---- two of our own streams side by side -----------------------------------

COEXIST_TARGET = ("deb", "bookworm", "debian:12")


class StreamPair:
    def __init__(self, cid, a, b):
        self.cid, self.a, self.b = cid, a, b

    def run(self, cmd, check=False):
        r = subprocess.run([PODMAN, "exec", self.cid, "bash", "-c", cmd],
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            raise AssertionError(f"cmd failed ({r.returncode}): {cmd}\n{r.stdout}\n{r.stderr}")
        return r

    def out(self, cmd):
        return self.run(cmd, check=True).stdout.strip()


def _two_stream_container():
    """A container with STREAM and one other built stream installed.

    Skips unless a second stream has been built, e.g.

        make STREAM=3.6 VERSION=3.6.0 deb-bookworm

    The case worth the most is two streams of the SAME major, which would share a
    libcrypto-upstream.so.N SONAME; that cannot be exercised until a second
    same-major release exists.
    """
    others = [s for s in built_streams() if s != STREAM]
    if not others:
        pytest.skip("only one stream built — build a second one to test coexistence")
    other = others[0]

    fam, rel, image = COEXIST_TARGET
    if not _main_pkgs(fam, rel) or not _main_pkgs(fam, rel, stream=other):
        pytest.skip(f"need {fam}-{rel} packages for both {STREAM} and {other}")

    cid = start_container(image, {pkgdir(fam, rel): "/pkgs",
                                 pkgdir(fam, rel, other): "/pkgs-other",
                                 DATADIR: "/testdata"})
    install = (
        "set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null; "
        "apt-get install -y --no-install-recommends ca-certificates openssl "
        f"/pkgs/openssl{STREAM}-upstream_*.deb "
        f"/pkgs-other/openssl{other}-upstream_*.deb >/dev/null 2>&1"
    )
    try:
        r = subprocess.run([PODMAN, "exec", cid, "bash", "-c", install],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"installing both streams failed:\n{r.stdout}\n{r.stderr}"
        yield StreamPair(cid, STREAM, other)
    finally:
        subprocess.run([PODMAN, "rm", "-f", cid], capture_output=True)


@pytest.fixture(scope="module")
def two_streams():
    yield from _two_stream_container()


@pytest.fixture
def two_streams_fresh():
    """Own container, for the tests that uninstall things."""
    yield from _two_stream_container()


def test_streams_are_independent(two_streams):
    """Each stream keeps its own prefix, configuration directory and libraries."""
    t = two_streams
    for stream in (t.a, t.b):
        version = t.out(f"/opt/openssl/{stream}/bin/openssl version").split()[1]
        assert version.startswith(stream + "."), f"{stream}: reported {version}"
        assert t.run(f"test -f /etc/opt/openssl/{stream}/openssl.cnf").returncode == 0
        ldd = t.out(f"ldd /opt/openssl/{stream}/bin/openssl")
        assert f"/opt/openssl/{stream}/lib64/libcrypto" in ldd, ldd


def test_enable_switches_between_streams_without_stacking(two_streams):
    """Sourcing the second stream's enable reverts the first, so PATH never
    accumulates entries and deactivating returns to the original."""
    t = two_streams
    script = (
        f'before="$PATH"; . /opt/openssl/{t.a}/enable >/dev/null; '
        f'. /opt/openssl/{t.b}/enable >/dev/null; '
        f'case ":$PATH:" in *":/opt/openssl/{t.a}/bin:"*) echo STACKED; exit 1 ;; esac; '
        f'[ "$(openssl version | cut -d" " -f2 | cut -d. -f1,2)" = "{t.b}" ] '
        '|| { echo WRONG_STREAM; exit 1; }; '
        'openssl_upstream_deactivate; '
        '[ "$PATH" = "$before" ] && echo OK || { echo NOT_RESTORED; exit 1; }'
    )
    assert t.out(script) == "OK"


def test_removing_one_stream_leaves_the_other_working(two_streams_fresh):
    """Independent removal: the shared /etc/opt/openssl parent must not let one
    package's removal disturb the other's installation or trust store."""
    t = two_streams_fresh
    r = t.run("DEBIAN_FRONTEND=noninteractive apt-get remove -y "
              f"openssl{t.b}-upstream 2>&1")
    assert r.returncode == 0, r.stdout + r.stderr

    version = t.out(f"/opt/openssl/{t.a}/bin/openssl version").split()[1]
    assert version.startswith(t.a + "."), version
    assert t.run(f"test -f /etc/opt/openssl/{t.a}/openssl.cnf").returncode == 0
    assert t.run(f"test -L /etc/opt/openssl/{t.a}/cert.pem").returncode == 0, \
        "removing the other stream disturbed this stream's trust store"
