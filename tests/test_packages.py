"""As-installed invariants and a functional crypto exercise, run against every
built target via the `target` fixture (see conftest.py)."""
import pytest

from conftest import VERSION


@pytest.fixture
def trust_restored(target):
    """Yields the trust-anchor helper and puts the stream's trust store back to
    the default afterwards, whatever the test did or how it failed.

    The container is shared by the whole session, so a test that mutates the
    trust store and then fails part-way would otherwise leave every later test
    that needs TLS broken — an ordering-dependent cascade rather than one clear
    failure.
    """
    tool = f"{target.prefix}/bin/openssl-trust-anchors"
    ssldir = f"/etc/opt/openssl/{target.stream}"
    try:
        yield tool
    finally:
        target.run(f"rm -rf {ssldir}/cert.pem {ssldir}/certs {ssldir}/trust.conf")
        target.run(f"{tool} system")


# ---- isolation and installed layout ---------------------------------------

def test_package_installed(target):
    assert target.run(f"test -x {target.prefix}/bin/openssl").returncode == 0


def test_version_matches_stream(target):
    ver = target.out(f"{target.prefix}/bin/openssl version").split()[1]
    assert ver.startswith(target.stream + "."), f"got {ver}, expected {target.stream}.x"


def test_version_is_the_one_this_run_asked_for(target):
    """The stream prefix alone accepts any point release, so a build reused
    under a new VERSION would pass while the publish tags name the new one."""
    if not VERSION:
        pytest.skip("VERSION unset; nothing to compare the packages against")
    ver = target.out(f"{target.prefix}/bin/openssl version").split()[1]
    assert ver == VERSION, f"packages are {ver}, but this run asked for {VERSION}"


def test_system_openssl_untouched(target):
    sysver = target.out("/usr/bin/openssl version").split()[1]
    assert not sysver.startswith(target.stream + "."), \
        f"system openssl is {sysver} — should be a different stream than ours"


def test_runpath_points_at_stream_libdir(target):
    dyn = target.out(f"readelf -d {target.prefix}/bin/openssl")
    assert "RUNPATH" in dyn and f"{target.prefix}/lib64" in dyn


def test_libraries_have_runpath(target):
    for base in ("libcrypto", "libssl"):
        dyn = target.out(f"readelf -d {target.prefix}/lib64/{base}-upstream.so.*")
        assert "RUNPATH" in dyn and f"{target.prefix}/lib64" in dyn, f"{base}: {dyn}"


def test_provider_module_still_loads_without_runpath(target):
    """Removing the modules' RUNPATH is only safe because a provider is
    dlopen'd by an already-loaded libcrypto, which satisfies its NEEDED.
    Prove it by actually loading one."""
    out = target.out(f"{target.prefix}/bin/openssl list -provider legacy -providers")
    assert "legacy" in out, out


def test_provider_modules_have_no_runpath(target):
    """Providers are dlopen'd by an already-loaded libcrypto, so they need no
    RUNPATH of their own (module_ldflags is empty in the variant target)."""
    mods = target.out(f"ls {target.prefix}/lib64/ossl-modules/*.so").split()
    assert mods, "expected at least one provider module"
    for m in mods:
        dyn = target.out(f"readelf -d {m}")
        assert "RUNPATH" not in dyn and "RPATH" not in dyn, f"{m} should have no rpath:\n{dyn}"


def test_links_our_libcrypto(target):
    ldd = target.out(f"ldd {target.prefix}/bin/openssl")
    assert f"{target.prefix}/lib64/libcrypto" in ldd


def test_soname_is_upstream_marked(target):
    """Our libs carry a distinct '-upstream' SONAME (can't collide with a
    distro's same-major libssl/libcrypto in one process)."""
    for base in ("libcrypto", "libssl"):
        dyn = target.out(f"readelf -d {target.prefix}/lib64/{base}-upstream.so.* | grep SONAME")
        assert f"{base}-upstream.so." in dyn, dyn


def test_consumers_need_marked_soname(target):
    needed = target.out(f"readelf -d {target.prefix}/bin/openssl | grep NEEDED")
    assert "libcrypto-upstream.so." in needed and "libssl-upstream.so." in needed, needed
    # and NOT the stock SONAMEs, which would be satisfiable by the distro's libs
    assert "[libcrypto.so." not in needed and "[libssl.so." not in needed, needed


def test_symbol_versions_are_variant_scoped(target):
    """shlib_variant also renames the symbol versions (OPENSSL_4.x ->
    OPENSSL_UPSTREAM_4.x), so a stock libcrypto cannot satisfy our symbol
    version requirements even if a SONAME somehow matched."""
    defs = target.out(
        f"readelf -V {target.prefix}/lib64/libcrypto-upstream.so.* "
        "| grep -o 'OPENSSL[A-Z_0-9.]*' | sort -u")
    assert "OPENSSL_UPSTREAM_" in defs, defs
    assert not any(v.startswith("OPENSSL_4") or v.startswith("OPENSSL_3")
                   for v in defs.split()), defs


def test_no_global_linker_config(target):
    r = target.run("ls /etc/ld.so.conf.d/ 2>/dev/null | grep -i openssl")
    assert r.returncode != 0, f"leaked ld.so.conf.d entry: {r.stdout}"


def test_config_lives_under_etc(target):
    assert target.run(f"test -f /etc/opt/openssl/{target.stream}/openssl.cnf").returncode == 0


def test_ca_trust_wired(target):
    assert target.run(f"test -L /etc/opt/openssl/{target.stream}/cert.pem").returncode == 0


def test_trust_anchors_toggle(target, tls_server, trust_restored):
    """The system CA anchors are opt-out: `none` unwires the stream's trust
    store (TLS then fails), `system` restores it.

    The server runs inside the container behind a CA installed into the
    distribution's own trust store, so a successful handshake proves the system
    anchors really are reached through our cert.pem — with no internet involved.
    """
    ssldir = f"/etc/opt/openssl/{target.stream}"
    tool = trust_restored

    target.run(f"{tool} none", check=True)
    assert target.run(f"test -e {ssldir}/cert.pem").returncode != 0, "cert.pem should be unwired"
    assert not tls_server.verifies(), "TLS should fail with no anchors"
    # ...and it is the anchors that are gone, not the server that is broken:
    # naming the CA explicitly still verifies.
    assert tls_server.verifies(f"-CAfile {tls_server.ca_file}"), \
        "an explicitly supplied CA should still verify when there are no anchors"

    target.run(f"{tool} system", check=True)
    assert target.run(f"test -L {ssldir}/cert.pem").returncode == 0, "cert.pem should be relinked"
    assert tls_server.verifies(), "TLS should verify again"


def test_administrator_provided_trust_store_is_preserved(target, trust_restored):
    """The helper manages only its own symlinks: a real file left by an
    administrator is reported and kept, never replaced."""
    ssldir = f"/etc/opt/openssl/{target.stream}"
    tool = trust_restored

    target.run(f"{tool} none", check=True)
    target.run(f"rm -f {ssldir}/cert.pem", check=True)
    target.run(f"printf '# administrator bundle\\n' > {ssldir}/cert.pem", check=True)

    r = target.run(f"{tool} system")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "keeping administrator-provided" in r.stderr, r.stdout + r.stderr
    assert target.run(f"test -L {ssldir}/cert.pem").returncode != 0, \
        "an administrator-provided cert.pem must not be replaced by our symlink"
    assert "administrator bundle" in target.out(f"cat {ssldir}/cert.pem")
    assert "administrator-provided" in target.out(f"{tool} status")


@pytest.mark.parametrize("frontend", ["package-manager", "low-level"])
def test_trust_anchors_chosen_at_install_time(target, trust_restored, frontend):
    """USE_SYSTEM_TRUST_ANCHORS=no at install time opts out — the same mechanism
    on both package families, no pre-created files.

    Exercised through both the high-level frontend the documentation tells people
    to use (apt/dnf, which invoke maintainer scripts through their own
    environment) and the low-level tool (dpkg/rpm). The variable has to reach the
    scripts either way, and only apt/dnf is what anyone will actually type.
    """
    ssldir = f"/etc/opt/openssl/{target.stream}"
    tool = trust_restored
    if target.family == "deb":
        pkgs = f"/pkgs/openssl{target.stream}-upstream_*_*.deb"
        reinstall = (f"DEBIAN_FRONTEND=noninteractive apt-get install -y --reinstall "
                     f"--allow-downgrades {pkgs}" if frontend == "package-manager"
                     else f"dpkg -i {pkgs}")
    else:
        pkgs = f"/pkgs/openssl{target.stream}-upstream-[0-9]*.rpm"
        reinstall = (f"dnf reinstall -y {pkgs}" if frontend == "package-manager"
                     else f"rpm -U --replacepkgs {pkgs}")

    # start from the default, then reinstall opting out
    target.run(f"{tool} system", check=True)
    target.run(f"rm -f {ssldir}/trust.conf", check=True)
    r = target.run(f"USE_SYSTEM_TRUST_ANCHORS=no {reinstall}")
    assert r.returncode == 0, f"reinstall failed:\n{r.stdout}\n{r.stderr}"
    assert target.run(f"test -e {ssldir}/cert.pem").returncode != 0, \
        "install-time opt-out should leave the trust store unwired"
    assert "no" in target.out(f"cat {ssldir}/trust.conf").lower(), "choice should be recorded"

    # and the recorded choice survives a plain reinstall (no env var)
    r = target.run(reinstall)
    assert r.returncode == 0, f"plain reinstall failed:\n{r.stdout}\n{r.stderr}"
    assert target.run(f"test -e {ssldir}/cert.pem").returncode != 0, \
        "recorded opt-out should survive an upgrade"


# ---- functional: does the shipped library actually work -------------------

def test_enable_deactivate_roundtrip(target):
    """source enable -> stream on PATH + deactivate fn present; then
    openssl_upstream_deactivate -> PATH restored exactly."""
    p = target.prefix
    script = (
        f'before="$PATH"; . {p}/enable >/dev/null; '
        f'case ":$PATH:" in *":{p}/bin:"*) ;; *) echo NOT_ON_PATH; exit 1 ;; esac; '
        'command -v openssl_upstream_deactivate >/dev/null || {{ echo NO_FUNC; exit 1; }}; '
        'openssl_upstream_deactivate; '
        '[ "$PATH" = "$before" ] && echo OK || {{ echo NOT_RESTORED; exit 1; }}'
    ).replace("{{", "{").replace("}}", "}")
    assert target.out(script) == "OK"


@pytest.mark.parametrize("var", ["PATH", "PKG_CONFIG_PATH", "MANPATH"])
def test_enable_restores_every_variable_it_touches(target, var):
    """enable exports three variables and claims to restore each to exactly what
    it was — including back to *unset* when it started unset, which is why the
    script bothers with the ${var+x} dance. PATH alone passing proves nothing
    about the other two.
    """
    p = target.prefix
    # was-set case: a known value must come back byte for byte
    was_set = (
        f'export {var}=/sentinel/value; '
        f'. {p}/enable >/dev/null; '
        f'[ "${var}" = /sentinel/value ] && {{ echo NOT_MODIFIED; exit 1; }}; '
        f'case ":${var}:" in *"{p}"*) ;; *) echo STREAM_MISSING; exit 1 ;; esac; '
        f'openssl_upstream_deactivate; '
        f'[ "${var}" = /sentinel/value ] && echo OK || {{ echo "GOT:${var}"; exit 1; }}'
    )
    assert target.out(was_set) == "OK", f"{var} was not restored to its previous value"

    # was-unset case: it must end up unset again, not empty
    was_unset = (
        f'unset {var}; . {p}/enable >/dev/null; openssl_upstream_deactivate; '
        f'if [ -n "${{{var}+x}}" ]; then echo "STILL_SET:${var}"; exit 1; fi; echo OK'
    )
    assert target.out(was_unset) == "OK", f"{var} was left set after deactivation"


def test_default_provider_loads(target):
    assert "default" in target.out(f"{target.prefix}/bin/openssl list -providers")


def test_sha256_matches_system(target):
    """Cross-check our digest against the distro's openssl for the same input."""
    ours = target.out(f"printf abc | {target.prefix}/bin/openssl dgst -sha256 -r").split()[0]
    sysd = target.out("printf abc | /usr/bin/openssl dgst -sha256 -r").split()[0]
    assert ours == sysd and len(ours) == 64


def test_aes_roundtrip(target):
    o = f"{target.prefix}/bin/openssl"
    cmd = (f'printf "secret text" | {o} enc -aes-256-cbc -pbkdf2 -pass pass:pw '
           f'| {o} enc -d -aes-256-cbc -pbkdf2 -pass pass:pw')
    assert target.out(cmd) == "secret text"


def test_ec_keygen(target):
    out = target.out(f"{target.prefix}/bin/openssl genpkey -algorithm EC "
                     f"-pkeyopt ec_paramgen_curve:P-256 2>&1")
    assert "PRIVATE KEY" in out


def test_tls_handshake(target, tls_server):
    """A full handshake and chain verification against a server in the container,
    trusted through the distribution's CA store. Hermetic, so a failure here is
    always our packaging and never someone else's network."""
    assert tls_server.verifies(), target.run(tls_server.client_cmd()).stdout


@pytest.mark.network
def test_live_tls_handshake(target):
    """The same handshake against the real internet. Deselected by default: it is
    a useful smoke test of the shipped trust store, but it makes an unrelated
    network problem look like a packaging regression."""
    r = target.run(
        f'echo Q | {target.prefix}/bin/openssl s_client -connect www.openssl.org:443 '
        f'-servername www.openssl.org -verify_return_error -brief 2>&1')
    assert "Verification: OK" in (r.stdout + r.stderr), (r.stdout + r.stderr)


# ---- -dev: compile a real consumer and run it -----------------------------

def test_devel_compile_and_run(target):
    script = (
        f'set -e; . {target.prefix}/enable; '
        f'gcc /testdata/consumer.c $(pkg-config --cflags --libs openssl) -o /tmp/t; '
        # the pkg-config-embedded rpath must land in the consumer binary
        f'readelf -d /tmp/t | grep -q "{target.prefix}/lib64"; '
        f'/tmp/t'
    )
    out = target.out(script)
    ver, ndigits = out.split()
    assert ver.startswith(target.stream + ".") and ndigits == "32"


# ---- rpm-specific: Provides must not advertise our private libs -----------

def test_rpm_provides_do_not_leak(target):
    if target.family != "rpm":
        pytest.skip("rpm-only")
    prov = target.out(f"rpm -q --provides openssl{target.stream}-upstream")
    for bad in ("libssl.so", "libcrypto.so", "pkgconfig("):
        assert bad not in prov, f"leaked provide {bad!r}:\n{prov}"
