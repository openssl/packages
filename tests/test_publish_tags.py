"""The publish tag: one per publish, recording what it published.

The tag is a record, not a gate — lib/is_published.py asks the bucket whether
a publish may proceed. So these check that the name is unique per publish and
honest about what it names, and that the annotation carries the detail the name
no longer does.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
from _goals import expand  # noqa: E402
from is_published import parse_deb, parse_rpm  # noqa: E402
from plan import (identities, manifest, packages, releases, tag,  # noqa: E402
                  wanted)

pytestmark = pytest.mark.unit

EVERY = ["deb-bookworm", "deb-noble", "rpm-el9"]
STAMP = "20260812T121318Z"


def _tag(goals, version="4.0.1", revision="1", fips=("3.1.2",)):
    return tag(expand(goals, EVERY), version, revision, list(fips), STAMP)


def test_a_publish_creates_exactly_one_tag():
    """It used to be one per package, release and arch — 36 for a stream
    publish. The detail moved into the annotation."""
    assert _tag("stream fips-companion") == f"publish/4.0.1-1/{STAMP}"


def test_a_module_only_publish_is_not_named_after_the_stream():
    """It builds streams to test the modules against but publishes neither."""
    assert _tag("fips-validated-publish") == f"publish/fips-3.1.2-1/{STAMP}"


def test_a_run_publishing_both_names_both():
    assert _tag("deb-bookworm fips-deb-bookworm") == \
        f"publish/4.0.1-1+fips-3.1.2-1/{STAMP}"


def test_identities_are_sorted_and_deduplicated():
    """Two goals covering the same identity must not name it twice, and the
    order must not depend on how the goals were typed."""
    kinds = expand("stream fips-companion deb-bookworm", EVERY)
    assert identities(kinds, "4.0.1", "1", ["3.1.2"]) == ["4.0.1-1"]
    assert identities(expand("all", EVERY), "4.0.1", "1", ["3.5.0", "3.1.2"]) == \
        ["4.0.1-1", "fips-3.1.2-1", "fips-3.5.0-1"]


def test_the_stamp_distinguishes_publishes_of_one_version_revision():
    """A backfill, a second architecture and a module-only publish all touch the
    same version-revision, so the name cannot be derived from it alone."""
    first = tag(expand("stream", EVERY), "4.0.1", "1", ["3.1.2"], "20260812T121318Z")
    later = tag(expand("stream", EVERY), "4.0.1", "1", ["3.1.2"], "20260901T090000Z")
    assert first != later


def test_goals_naming_nothing_produce_no_tag():
    assert tag(expand("deb-forky", EVERY), "4.0.1", "1", ["3.1.2"], STAMP) is None


@pytest.mark.parametrize("goals", ["stream fips-companion", "fips-validated-publish",
                                   "all", "deb-bookworm fips-deb-bookworm"])
def test_every_tag_is_a_legal_ref_name(goals):
    """Git accepts the name and no path component exceeds what a filesystem will
    hold: a ref is stored as a path, and each component caps at 255 bytes."""
    name = _tag(goals)
    assert subprocess.run(["git", "check-ref-format", f"refs/tags/{name}"]).returncode == 0
    assert all(len(part.encode()) <= 255 for part in name.split("/"))


def test_the_name_stays_short_with_many_validated_versions():
    fips = ["3.1.2", "3.5.0", "3.7.1", "4.0.3", "4.2.0"]
    name = _tag("all", fips=fips)
    assert all(len(part.encode()) <= 255 for part in name.split("/"))


def test_the_annotation_records_every_package_release_and_arch():
    lines = manifest(expand("deb-bookworm fips-deb-bookworm", EVERY), "4.0", "4.0.1",
                     "1", ["3.1.2"], ["amd64", "arm64"])
    assert sorted(lines) == sorted([
        "openssl4.0-upstream 4.0.1-1 deb-bookworm amd64",
        "openssl4.0-upstream-fips 4.0.1-1 deb-bookworm amd64",
        "openssl-fips3.1.2-upstream 3.1.2-1 deb-bookworm amd64",
        "openssl4.0-upstream 4.0.1-1 deb-bookworm arm64",
        "openssl4.0-upstream-fips 4.0.1-1 deb-bookworm arm64",
        "openssl-fips3.1.2-upstream 3.1.2-1 deb-bookworm arm64",
    ])


# What make-repo.sh --record writes: the files a run added, as repository-relative
# paths. Sub-packages included, which is the reason the annotation records this
# rather than a list derived from the goals.
RECORD = [
    "deb/pool/bookworm/main/o/openssl4.0-upstream/openssl4.0-upstream_4.0.1-5+deb12_amd64.deb",
    "deb/pool/bookworm/main/o/openssl4.0-upstream/openssl4.0-upstream-dev_4.0.1-5+deb12_amd64.deb",
    "deb/pool/bookworm/main/o/openssl4.0-upstream/openssl4.0-upstream-dbgsym_4.0.1-5+deb12_amd64.deb",
    "deb/pool/bookworm/main/o/openssl4.0-upstream-fips/openssl4.0-upstream-fips_4.0.1-5+deb12_amd64.deb",
    "rpm/el10/x86_64/openssl4.0-upstream-4.0.1-5.el10.x86_64.rpm",
    "rpm/el10/x86_64/openssl4.0-upstream-devel-4.0.1-5.el10.x86_64.rpm",
]


def test_a_recorded_publish_stays_within_what_the_goals_planned():
    """The annotation is observed and the plan is derived, so they can disagree.
    A file whose package or release is outside the plan means the run put
    something in the repository it never intended to publish.
    """
    kinds = expand("deb-bookworm fips-companion-deb-bookworm rpm-el10",
                   ["deb-bookworm", "rpm-el10"])
    planned_packages = packages(kinds, "4.0", ["3.1.2"])
    planned_releases = releases(kinds)
    for path in RECORD:
        parsed = parse_deb(path) if path.endswith(".deb") else parse_rpm(path)
        assert parsed, f"unparsable record entry: {path}"
        name, release, _, _ = parsed
        assert any(name.startswith(pkg) for pkg in planned_packages), \
            f"{path} is not a package these goals publish"
        family = "deb" if path.endswith(".deb") else "rpm"
        assert f"{family}-{release}" in planned_releases, \
            f"{path} is in a release these goals do not reindex"


def test_a_record_outside_the_plan_is_caught():
    """The validated module was not among the goals, so recording it is a bug."""
    kinds = expand("deb-bookworm fips-companion-deb-bookworm", ["deb-bookworm", "rpm-el10"])
    planned = packages(kinds, "4.0", ["3.1.2"])
    stray = ("deb/pool/bookworm/main/o/openssl-fips3.1.2-upstream/"
             "openssl-fips3.1.2-upstream_3.1.2-1+deb12_amd64.deb")
    name = parse_deb(stray)[0]
    assert not any(name.startswith(pkg) for pkg in planned)


def test_a_validated_module_is_recorded_at_its_own_version():
    lines = manifest(expand("fips-validated-publish", EVERY), "4.0", "4.0.1", "1",
                     ["3.1.2"], ["amd64"])
    assert all("3.1.2-1" in line for line in lines)
    assert not any("4.0.1" in line for line in lines)


def test_the_published_packages_are_the_ones_the_goals_name():
    assert packages(expand("fips-validated-publish", EVERY), "4.0", ["3.1.2"]) == \
        ["openssl-fips3.1.2-upstream"]
    assert packages(expand("stream fips-companion", EVERY), "4.0", ["3.1.2"]) == \
        ["openssl4.0-upstream", "openssl4.0-upstream-fips"]


def test_the_published_releases_are_the_slices_to_reindex():
    """One list, deduplicated across kinds: an index does not care which kind
    touched it, only that the release needs regenerating."""
    assert releases(expand("deb-bookworm fips-deb-bookworm", EVERY)) == ["deb-bookworm"]
    assert releases(expand("stream", EVERY)) == sorted(EVERY)
    assert releases(expand("deb-forky", EVERY)) == []


def test_every_published_package_belongs_to_a_reindexed_release():
    """The repository would otherwise hold a package no index mentions."""
    kinds = expand("all", EVERY)
    reindexed = set(releases(kinds))
    published = {f"{family}-{release}" for _, family, release, _, _
                 in wanted(kinds, "4.0", "4.0.1", ["3.1.2"], ["amd64"])}
    assert published <= reindexed
