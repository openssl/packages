"""Guard for automated runs.

The per-target fixtures skip when a target's packages are absent, which is what
makes a partial local build usable. In an automated run that is dangerous: an
incomplete artifact download would skip everything and still report success.

Set REQUIRE_ALL_TARGETS=1 to require that every target in the matrix, and the
FIPS module packages, are actually present.
"""
import os

import pytest

from conftest import MATRIX, pkgdir, _main_pkgs
from test_fips import FIPS_VERSION, _fips_dir, _fips_pkgs_present

requires_full_matrix = pytest.mark.skipif(
    not os.environ.get("REQUIRE_ALL_TARGETS"),
    reason="set REQUIRE_ALL_TARGETS=1 to require the whole matrix",
)


@requires_full_matrix
def test_every_target_has_packages():
    missing = [f"{fam}-{rel} (looked in {pkgdir(fam, rel)})"
               for fam, rel, _ in MATRIX if not _main_pkgs(fam, rel)]
    assert not missing, "no packages for: " + "; ".join(missing)


@requires_full_matrix
def test_fips_module_packages_present():
    missing = [f"{fam} (looked in {_fips_dir(fam)})"
               for fam in ("deb", "rpm") if not _fips_pkgs_present(fam)]
    assert not missing, f"no FIPS {FIPS_VERSION} packages for: " + "; ".join(missing)
