"""ELF hardening and package metadata for the installed stream.

The build asks each distribution for its own hardened flags — `hardening=+all`
via dpkg-buildflags on deb, %{optflags}/%{build_ldflags} on rpm — rather than
hard-coding a flag list. These tests assert the properties that survive into the
shipped objects, so a packaging change that quietly drops them fails here.

The FIPS provider module is deliberately exempt and is checked separately: it is
built with the bare `./Configure enable-fips` from its Security Policy, with no
distribution flags, so it has no BIND_NOW. Asserting otherwise would be
asserting a deviation from the validated build.
"""
import pytest


def _dynamic(target, path):
    return target.out(f"readelf -dW {path}")


def _segments(target, path):
    return target.out(f"readelf -lW {path}")


def _stream_objects(target):
    """The stream's executable and its two shared libraries."""
    libs = target.out(
        f"ls {target.prefix}/lib64/libcrypto-upstream.so.* "
        f"{target.prefix}/lib64/libssl-upstream.so.*").split()
    return [f"{target.prefix}/bin/openssl"] + [l for l in libs if ".so." in l]


def test_objects_are_position_independent(target):
    """PIE for the executable, and every shared object is DYN by construction.

    readelf renders a PIE as `DYN (Shared object file)` on the older targets, so
    the DF_1_PIE flag is the portable signal (binutils 2.34 onwards prints it).
    """
    dyn = _dynamic(target, f"{target.prefix}/bin/openssl")
    assert "PIE" in dyn, f"openssl is not a PIE:\n{dyn}"


def test_full_relro(target):
    """A GNU_RELRO segment plus BIND_NOW — partial RELRO alone leaves the PLT
    writable, so both halves matter."""
    for obj in _stream_objects(target):
        assert "GNU_RELRO" in _segments(target, obj), f"{obj}: no RELRO segment"
        assert "BIND_NOW" in _dynamic(target, obj), f"{obj}: not BIND_NOW"


def test_stack_is_not_executable(target):
    for obj in _stream_objects(target):
        stack = [l for l in _segments(target, obj).splitlines() if "GNU_STACK" in l]
        assert stack, f"{obj}: no GNU_STACK segment (stack permissions unspecified)"
        flags = stack[0].rsplit(None, 2)[-2]
        assert "E" not in flags, f"{obj}: executable stack ({stack[0]})"


def test_fortify_source_is_active(target):
    """_FORTIFY_SOURCE redirects the unsafe libc calls to their __*_chk variants,
    so their presence in the dynamic symbol table is the observable effect.

    __stack_chk_fail is excluded deliberately: that one comes from the stack
    protector, which is a different flag, and counting it would let this test pass
    with _FORTIFY_SOURCE switched off.
    """
    lib = target.out(f"ls {target.prefix}/lib64/libcrypto-upstream.so.*").split()[0]
    syms = target.out(
        f"readelf -sW --dyn-syms {lib} | grep -o '__[a-z_]*_chk' | sort -u || true")
    fortify = [s for s in syms.split() if not s.startswith("__stack_chk")]
    assert len(fortify) >= 3, \
        f"_FORTIFY_SOURCE looks inactive; only found: {syms.split()}"


def test_stack_protector_is_active(target):
    lib = target.out(f"ls {target.prefix}/lib64/libcrypto-upstream.so.*").split()[0]
    syms = target.out(f"readelf -sW --dyn-syms {lib} | grep -o '__stack_chk[a-z_]*' | sort -u")
    assert syms, "no __stack_chk_* symbols — the stack protector looks inactive"


# ---- packaging metadata ----------------------------------------------------

def test_no_build_host_leaks_into_rpm_metadata(target):
    """%_buildhost is pinned so a signed artifact does not record which machine
    happened to build it."""
    if target.family != "rpm":
        pytest.skip("rpm-only")
    host = target.out(f"rpm -q --qf '%{{BUILDHOST}}' openssl{target.stream}-upstream")
    assert host == "reproducible.openssl.local", host


def test_rpm_requires_no_openssl_libraries(target):
    """__requires_exclude keeps our private SONAMEs out of Requires; a leak here
    would make the package uninstallable on a machine without them."""
    if target.family != "rpm":
        pytest.skip("rpm-only")
    reqs = target.out(f"rpm -q --requires openssl{target.stream}-upstream")
    bad = [l for l in reqs.splitlines() if "libcrypto" in l or "libssl" in l]
    assert not bad, "unexpected library Requires:\n" + "\n".join(bad)


def test_devel_owns_the_development_files(target):
    """The -dev/-devel split is where dh_missing and %exclude mistakes show up:
    headers and link-time symlinks must be in the development package, and the
    runtime package must not carry them."""
    if target.family == "rpm":
        main = target.out(f"rpm -ql openssl{target.stream}-upstream").splitlines()
        devel = target.out(f"rpm -ql openssl{target.stream}-upstream-devel").splitlines()
    else:
        main = target.out(f"dpkg -L openssl{target.stream}-upstream").splitlines()
        devel = target.out(f"dpkg -L openssl{target.stream}-upstream-dev").splitlines()

    include = f"{target.prefix}/include/openssl/evp.h"
    # The link-time symlink keeps the stock name so that -lcrypto works; what
    # makes it ours is where it points.
    linktime = f"{target.prefix}/lib64/libcrypto.so"
    assert include in devel, f"{include} is not in the development package"
    assert include not in main, f"{include} leaked into the runtime package"
    assert linktime in devel, f"{linktime} is not in the development package"
    assert linktime not in main, f"{linktime} leaked into the runtime package"

    runtime = [f for f in main if "/lib64/libcrypto-upstream.so." in f]
    assert runtime, f"no versioned libcrypto in the runtime package:\n{main}"


def test_link_time_symlink_points_at_the_variant_soname(target):
    """`-lcrypto` has to end up needing libcrypto-upstream.so.N. The symlink the
    linker follows is the stock libcrypto.so, so if it ever pointed at a
    stock-named object every consumer would silently get a NEEDED the distribution
    could satisfy instead."""
    for base in ("libcrypto", "libssl"):
        link = target.out(f"readlink {target.prefix}/lib64/{base}.so")
        assert link.startswith(f"{base}-upstream.so."), f"{base}.so -> {link}"


def test_config_is_marked_as_configuration(target):
    """openssl.cnf must survive an upgrade that would otherwise overwrite local
    edits — conffile on deb, %config(noreplace) on rpm."""
    cnf = f"/etc/opt/openssl/{target.stream}/openssl.cnf"
    if target.family == "rpm":
        # fflags renders 'c' for %config and 'n' for noreplace.
        entry = target.out(
            f"rpm -q --qf '[%{{FILENAMES}}|%{{FILEFLAGS:fflags}}\\n]' "
            f"openssl{target.stream}-upstream | grep '^{cnf}|'")
        fflags = entry.split("|", 1)[1]
        assert "c" in fflags and "n" in fflags, f"not %config(noreplace): {entry}"
    else:
        conffiles = target.out(
            f"dpkg-query -W -f='${{Conffiles}}' openssl{target.stream}-upstream")
        assert cnf in conffiles, f"{cnf} is not a conffile:\n{conffiles}"
