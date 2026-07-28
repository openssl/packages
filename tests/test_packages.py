"""As-installed invariants and a functional crypto exercise, run against every
built target via the `target` fixture (see conftest.py)."""
import pytest

# ---- isolation and installed layout ---------------------------------------

def test_package_installed(target):
    assert target.run(f"test -x {target.prefix}/bin/openssl").returncode == 0


def test_version_matches_stream(target):
    ver = target.out(f"{target.prefix}/bin/openssl version").split()[1]
    assert ver.startswith(target.stream + "."), f"got {ver}, expected {target.stream}.x"


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


def test_trust_anchors_toggle(target):
    """The system CA anchors are opt-out: `none` unwires the stream's trust
    store (TLS then fails), `system` restores it."""
    ssldir = f"/etc/opt/openssl/{target.stream}"
    tool = f"{target.prefix}/bin/openssl-trust-anchors"
    tls = (f'echo Q | {target.prefix}/bin/openssl s_client -connect www.openssl.org:443 '
           f'-servername www.openssl.org -verify_return_error -brief 2>&1')

    target.run(f"{tool} none", check=True)
    assert target.run(f"test -e {ssldir}/cert.pem").returncode != 0, "cert.pem should be unwired"
    assert "Verification: OK" not in target.run(tls).stdout, "TLS should fail with no anchors"

    target.run(f"{tool} system", check=True)
    assert target.run(f"test -L {ssldir}/cert.pem").returncode == 0, "cert.pem should be relinked"
    assert "Verification: OK" in target.run(tls).stdout, "TLS should verify again"


def test_trust_anchors_chosen_at_install_time(target):
    """USE_SYSTEM_TRUST_ANCHORS=no at install time opts out — the same
    mechanism on both package families, no pre-created files."""
    ssldir = f"/etc/opt/openssl/{target.stream}"
    tool = f"{target.prefix}/bin/openssl-trust-anchors"
    if target.family == "deb":
        reinstall = (f"USE_SYSTEM_TRUST_ANCHORS=no dpkg -i "
                     f"/pkgs/openssl{target.stream}-upstream_*_*.deb")
    else:
        reinstall = (f"USE_SYSTEM_TRUST_ANCHORS=no rpm -U --replacepkgs "
                     f"/pkgs/openssl{target.stream}-upstream-[0-9]*.rpm")
    # start from the default, then reinstall opting out
    target.run(f"{tool} system", check=True)
    target.run(f"rm -f {ssldir}/trust.conf", check=True)
    r = target.run(reinstall)
    assert r.returncode == 0, f"reinstall failed:\n{r.stdout}\n{r.stderr}"
    assert target.run(f"test -e {ssldir}/cert.pem").returncode != 0, \
        "install-time opt-out should leave the trust store unwired"
    assert "no" in target.out(f"cat {ssldir}/trust.conf").lower(), "choice should be recorded"
    # and the recorded choice survives a plain reinstall (no env var)
    target.run(reinstall.replace("USE_SYSTEM_TRUST_ANCHORS=no ", ""), check=True)
    assert target.run(f"test -e {ssldir}/cert.pem").returncode != 0, \
        "recorded opt-out should survive an upgrade"
    target.run(f"{tool} system", check=True)   # restore for other tests


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


def test_live_tls_handshake(target):
    r = target.run(
        f'echo Q | {target.prefix}/bin/openssl s_client -connect www.openssl.org:443 '
        f'-servername www.openssl.org -verify_return_error -brief 2>&1')
    assert "Verification: OK" in (r.stdout + r.stderr), (r.stdout + r.stderr)


# ---- -dev: compile a real consumer and run it -----------------------------

PROG = r'''#include <openssl/evp.h>
#include <openssl/opensslv.h>
#include <stdio.h>
int main(void){
    unsigned char md[32]; size_t n = 0;
    EVP_Q_digest(NULL, "SHA256", NULL, "abc", 3, md, &n);
    printf("%s %zu\n", OpenSSL_version(OPENSSL_VERSION_STRING), n);
    return 0;
}'''


def test_devel_compile_and_run(target):
    script = (
        f'set -e; . {target.prefix}/enable; '
        f'cat > /tmp/t.c <<"EOF"\n{PROG}\nEOF\n'
        f'gcc /tmp/t.c $(pkg-config --cflags --libs openssl) -o /tmp/t; '
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
