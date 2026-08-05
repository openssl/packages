"""Guards against a green run that tested less than it looks like it did.

The per-target fixtures skip when packages are absent, which makes a partial
local build usable but would let an incomplete artifact download report success.
REQUIRE_ALL_TARGETS=1 makes absence a failure. The matrix-vs-Makefile check
needs no packages and always runs.
"""
import os
import shutil
import subprocess

import pytest

from conftest import MATRIX, REPO, pkgdir, target_name, _main_pkgs
from test_fips import (COMPANION, FIPS_VERSION, _companion_dir,
                       _companion_pkgs_present, _fips_dir, _fips_pkgs_present)

requires_full_matrix = pytest.mark.skipif(
    not os.environ.get("REQUIRE_ALL_TARGETS"),
    reason="set REQUIRE_ALL_TARGETS=1 to require the whole matrix",
)


def test_matrix_matches_makefile_targets():
    """The build matrix (Makefile) and the test matrix (conftest) are separate
    lists, and CI generates its build jobs from the first while the test job
    iterates the second. If they drift, a release can be built, uploaded and
    published without a single test ever touching it — and the completeness
    checks below would not notice, because they only iterate MATRIX.
    """
    if shutil.which("make") is None:
        pytest.skip("make not available")
    r = subprocess.run(["make", "-s", "ci-targets"], cwd=REPO,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"make -s ci-targets failed:\n{r.stdout}\n{r.stderr}"

    built = set(r.stdout.split())
    tested = {target_name(fam, rel) for fam, rel, _ in MATRIX}
    assert built == tested, (
        "the Makefile and tests/conftest.py matrices disagree — "
        f"built but never tested: {sorted(built - tested)}; "
        f"tested but never built: {sorted(tested - built)}")


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


@requires_full_matrix
def test_companion_fips_module_packages_present():
    missing = [f"{fam} (looked in {_companion_dir(fam)})"
               for fam in ("deb", "rpm") if not _companion_pkgs_present(fam)]
    assert not missing, \
        f"no companion FIPS module for stream {COMPANION}: " + "; ".join(missing)
