"""ELF hardening and package metadata for the installed stream.

The build asks each distribution for its own hardened flags rather than
hard-coding a list; these tests assert the properties that survive into the
shipped objects. The FIPS module is exempt and checked in test_fips.py: it is
built with the bare Security Policy command, so it has no BIND_NOW.
"""
import re

import pytest

from conftest import PACKAGING_COMMIT, REVISION, deb_dist_tag


def _dynamic(target, path):
    return target.out(f"readelf -dW {path}")


def _package_names(target):
    if target.family == "rpm":
        return [f"openssl{target.stream}-upstream",
                f"openssl{target.stream}-upstream-devel"]
    return [f"openssl{target.stream}-upstream",
            f"openssl{target.stream}-upstream-dev"]


def _file_list(target, pkg):
    cmd = f"rpm -ql {pkg}" if target.family == "rpm" else f"dpkg -L {pkg}"
    return target.out(cmd).splitlines()


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


def test_package_version_carries_the_revision(target):
    """The revision is what makes a republish of the same upstream version
    upgradable, so it has to reach the package metadata and not just the
    filename. A broken substitution would only show up at publish time."""
    expected = f"{target.stream}."
    for pkg in _package_names(target):
        if target.family == "rpm":
            got = target.out(f"rpm -q --qf '%{{VERSION}}-%{{RELEASE}}' {pkg}")
            ver, _, rel = got.partition("-")
            assert rel.split(".")[0] == REVISION, f"{pkg}: release {rel!r} != {REVISION}"
        else:
            got = target.out(f"dpkg-query -W -f='${{Version}}' {pkg}")
            ver, _, rel = got.rpartition("-")
            want = REVISION + deb_dist_tag(target)
            assert rel == want, f"{pkg}: revision {rel!r} != {want!r}"
        assert ver.startswith(expected), f"{pkg}: version {ver!r} is not {expected}x"


def test_no_html_manual_is_packaged(target):
    """We install man pages only. On rpm this is what %make_install would undo:
    the bare `install` target pulls in install_html_docs and stages the whole
    HTML manual into %{prefix}/share/doc, which %files then claims."""
    for pkg in _package_names(target):
        html = [f for f in _file_list(target, pkg) if "/share/doc/" in f and "/html" in f]
        assert not html, f"{pkg} ships {len(html)} HTML manual files, e.g. {html[:2]}"


def test_no_unsubstituted_placeholders_in_shipped_metadata(target):
    """Every template is rendered at build time; a leaked @TOKEN@ would ship in
    public package metadata. Provisional wording is checked here too, for the
    same reason: it is visible to anyone running apt/dnf."""
    placeholder = re.compile(r"@[A-Z_]+@")
    provisional = re.compile(r"proof-of-concept|placeholder|FIXME|TODO", re.I)

    for pkg in _package_names(target):
        if target.family == "rpm":
            texts = {
                "description": target.out(f"rpm -q --qf '%{{DESCRIPTION}}' {pkg}"),
                "summary": target.out(f"rpm -q --qf '%{{SUMMARY}}' {pkg}"),
                "changelog": target.out(f"rpm -q --changelog {pkg}"),
            }
        else:
            texts = {
                "description": target.out(f"dpkg-query -W -f='${{Description}}' {pkg}"),
                "changelog": target.out(
                    f"zcat /usr/share/doc/{pkg}/changelog.Debian.gz"),
            }
        for what, text in texts.items():
            assert not placeholder.search(text), \
                f"{pkg} {what} has an unsubstituted placeholder: " \
                f"{placeholder.search(text).group(0)}"
            assert not provisional.search(text), \
                f"{pkg} {what} has provisional wording: {provisional.search(text).group(0)}"


def test_packages_record_the_packaging_commit(target):
    """An artifact has to say which packaging built it: the external record can
    be lost or drift, the field inside the package cannot."""
    if not PACKAGING_COMMIT:
        pytest.skip("PACKAGING_COMMIT unset; nothing to compare against")
    for pkg in _package_names(target):
        if target.family == "rpm":
            got = target.out(f"rpm -q --qf '%{{VCS}}' {pkg}")
        else:
            # dpkg strips the XB- prefix when copying the field into the binary.
            got = target.out(f"dpkg-query -f '${{Packaging-Commit}}' -W {pkg}")
        assert got.endswith(PACKAGING_COMMIT), f"{pkg}: {got!r} does not name {PACKAGING_COMMIT}"
