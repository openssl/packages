"""Guards against a green run that tested less than it looks like it did.

The per-target fixtures skip when packages are absent, which makes a partial
local build usable but would let an incomplete artifact download report success.
REQUIRE_TARGETS names the make goals the run built, and absence of anything they
name is a failure. The matrix-vs-Makefile check needs no packages and always runs.
"""
import shutil
import subprocess
import tempfile

import pytest

from conftest import (COMPANION_REQUIRED, MATRIX, REPO, REQUIRE_TARGETS, required_targets,
                      STREAM_REQUIRED, VALIDATED_REQUIRED, pkgdir, target_name,
                      _main_pkgs)
from test_fips import (COMPANION, FIPS_VALIDATED, _companion_dir,
                       _companion_pkgs_present, _fips_dir, _fips_pkgs_present)

requires_stream_targets = pytest.mark.skipif(
    not STREAM_REQUIRED,
    reason=f"REQUIRE_TARGETS={REQUIRE_TARGETS!r} names no stream packages",
)
requires_validated_targets = pytest.mark.skipif(
    not VALIDATED_REQUIRED,
    reason=f"REQUIRE_TARGETS={REQUIRE_TARGETS!r} names no validated FIPS modules",
)
requires_companion_targets = pytest.mark.skipif(
    not COMPANION_REQUIRED,
    reason=f"REQUIRE_TARGETS={REQUIRE_TARGETS!r} names no companion FIPS modules",
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


@requires_stream_targets
def test_every_target_has_packages():
    missing = [f"{fam}-{rel} (looked in {pkgdir(fam, rel)})"
               for fam, rel, _ in MATRIX
               if target_name(fam, rel) in STREAM_REQUIRED and not _main_pkgs(fam, rel)]
    assert not missing, "no packages for: " + "; ".join(missing)


@requires_validated_targets
@pytest.mark.parametrize("version", FIPS_VALIDATED)
def test_fips_module_packages_present(version):
    missing = [f"{fam}-{rel} (looked in {_fips_dir(fam, rel, version)})"
               for fam, rel, _ in MATRIX
               if target_name(fam, rel) in VALIDATED_REQUIRED
               and not _fips_pkgs_present(fam, rel, version)]
    assert not missing, f"no FIPS {version} packages for: " + "; ".join(missing)


@requires_companion_targets
def test_companion_fips_module_packages_present():
    missing = [f"{fam}-{rel} (looked in {_companion_dir(fam, rel)})"
               for fam, rel, _ in MATRIX
               if target_name(fam, rel) in COMPANION_REQUIRED
               and not _companion_pkgs_present(fam, rel)]
    assert not missing, \
        f"no companion FIPS module for stream {COMPANION}: " + "; ".join(missing)


# Every goal the vocabulary accepts, crossed with every scope it can narrow to.
_TARGETS = [target_name(fam, rel) for fam, rel, _ in MATRIX]
_KINDS = ["fips", "fips-validated", "fips-companion",
          "fips-publish", "fips-validated-publish", "fips-companion-publish"]
GOALS = (["all", "stream", "deb", "rpm"] + _TARGETS
         + [kind + scope for kind in _KINDS
            for scope in ["", "-deb", "-rpm"] + [f"-{t}" for t in _TARGETS]])


def test_every_goal_is_both_a_make_target_and_understood_by_the_grammar():
    """The two halves have to agree. A goal make builds but the grammar cannot
    expand publishes nothing, silently; a goal the grammar expands but make
    cannot build fails the run late, after the pre-flight has passed.

    "make knows it" has to mean "it builds something": a name listed in .PHONY
    with no rule behind it exits 0 and does nothing, which is how a whole family
    of goals went missing without any target failing.
    """
    if shutil.which("make") is None:
        pytest.skip("make not available")
    with tempfile.TemporaryDirectory() as stamps:
        builds_nothing = []
        for goal in GOALS:
            r = subprocess.run(["make", "-n", goal, f"STAMPDIR={stamps}"], cwd=REPO,
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0 or "build/build-" not in r.stdout:
                builds_nothing.append(goal)
    assert not builds_nothing, "no make target builds: " + " ".join(builds_nothing)

    covers_nothing = [goal for goal in GOALS if not any(required_targets(goal))]
    assert not covers_nothing, "the grammar expands to nothing for: " + " ".join(covers_nothing)
