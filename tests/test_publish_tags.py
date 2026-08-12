"""The publish tag format, which is the pipeline's append-only publish guard.

Pure logic: the tags a run would create, and reading them back off the remote.
Nothing here builds or installs anything, so it runs anywhere.
"""
import os
import sys

import pytest

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "publish"))
from goals import expand  # noqa: E402
from tags import packages, next_free, remote_tags, split, tags  # noqa: E402

pytestmark = pytest.mark.unit

KINDS = {"stream": ["deb-bookworm", "rpm-el9"],
         "validated": ["rpm-el9"],
         "companion": ["deb-bookworm"]}


def test_a_tag_is_created_per_published_target_and_arch():
    assert tags(KINDS, ["amd64", "arm64"], "4.0.1", "1", ["3.1.2"]) == [
        "publish/4.0.1-1/deb-bookworm/amd64",
        "publish/4.0.1-1/rpm-el9/amd64",
        "publish/fips-companion-4.0.1-1/deb-bookworm/amd64",
        "publish/fips-validated-3.1.2-1/rpm-el9/amd64",
        "publish/4.0.1-1/deb-bookworm/arm64",
        "publish/4.0.1-1/rpm-el9/arm64",
        "publish/fips-companion-4.0.1-1/deb-bookworm/arm64",
        "publish/fips-validated-3.1.2-1/rpm-el9/arm64",
    ]


def test_a_goal_naming_nothing_publishes_nothing():
    empty = {"stream": [], "validated": [], "companion": []}
    assert tags(empty, ["amd64"], "4.0.1", "1", ["3.1.2"]) == []


def test_every_tag_a_run_creates_reads_back_to_its_own_identity():
    """The tag ends in /<target>/<arch> and targets contain hyphens, so an
    identity taken from the last hyphen of the whole tag would be wrong."""
    created = tags(KINDS, ["amd64"], "4.0.1", "2", ["3.1.2"])
    assert [split(tag) for tag in created] == [
        ("publish/4.0.1", 2),
        ("publish/4.0.1", 2),
        ("publish/fips-companion-4.0.1", 2),
        ("publish/fips-validated-3.1.2", 2),
    ]


@pytest.mark.parametrize("ref", [
    "openssl-4.0.1",
    "publish/4.0.1-1",
    "publish/4.0.1/deb-bookworm/amd64",
    "publish/4.0.1-1/deb-bookworm/amd64/extra",
    "publish/4.0.1-x/deb-bookworm/amd64",
])
def test_anything_that_is_not_a_publish_tag_is_ignored(ref):
    assert split(ref) is None


def test_the_module_kinds_are_separate_revision_series():
    """A stream and its modules are published on their own schedules, so their
    revisions must not be counted together."""
    assert split("publish/4.0.1-1/deb-bookworm/amd64")[0] != \
        split("publish/fips-companion-4.0.1-1/deb-bookworm/amd64")[0]


LS_REMOTE = """\
0000000000000000000000000000000000000000\trefs/heads/main
1111111111111111111111111111111111111111\trefs/tags/publish/4.0.1-1/deb-bookworm/amd64
1111111111111111111111111111111111111111\trefs/tags/publish/4.0.1-1/deb-bookworm/amd64^{}
2222222222222222222222222222222222222222\trefs/tags/publish/4.0.1-2/deb-bookworm/amd64
3333333333333333333333333333333333333333\trefs/tags/publish/fips-companion-4.0.1-3/rpm-el9/amd64
4444444444444444444444444444444444444444\trefs/tags/openssl-4.0.1
"""


def test_an_annotated_tag_is_not_counted_twice():
    """ls-remote lists an annotated tag again, peeled to its commit."""
    assert remote_tags(LS_REMOTE) == {
        "publish/4.0.1-1/deb-bookworm/amd64",
        "publish/4.0.1-2/deb-bookworm/amd64",
        "publish/fips-companion-4.0.1-3/rpm-el9/amd64",
        "openssl-4.0.1",
    }


def test_a_free_tag_is_not_reported_as_taken():
    taken, free = next_free(remote_tags(LS_REMOTE),
                            ["publish/4.0.1-3/deb-bookworm/amd64"])
    assert (taken, free) == ([], {})


def test_a_published_tag_reports_the_next_free_revision_of_its_identity():
    taken, free = next_free(remote_tags(LS_REMOTE),
                            ["publish/4.0.1-1/deb-bookworm/amd64"])
    assert taken == ["publish/4.0.1-1/deb-bookworm/amd64"]
    assert free == {"publish/4.0.1": 3}


def test_the_next_free_revision_is_reported_per_identity():
    taken, free = next_free(remote_tags(LS_REMOTE),
                            ["publish/4.0.1-2/deb-bookworm/amd64",
                             "publish/fips-companion-4.0.1-3/rpm-el9/amd64"])
    assert len(taken) == 2
    assert free == {"publish/4.0.1": 3, "publish/fips-companion-4.0.1": 4}


def test_an_arch_published_on_its_own_still_blocks_that_arch():
    """A single-arch publish tags only the arch it built, so the other arch can
    be completed later at the same revision."""
    taken, _ = next_free(remote_tags(LS_REMOTE),
                         ["publish/4.0.1-1/deb-bookworm/amd64",
                          "publish/4.0.1-1/deb-bookworm/arm64"])
    assert taken == ["publish/4.0.1-1/deb-bookworm/amd64"]


def test_a_run_publishes_only_the_packages_its_goals_name():
    """A validated-module publish builds the streams its modules are tested
    against; indexing those would republish them."""
    every = ["deb-bookworm", "rpm-el9"]
    validated_only = expand("fips-validated-publish", every)
    assert packages(validated_only, "4.0", ["3.1.2"]) == ["openssl-fips3.1.2-upstream"]

    stream_publish = expand("stream fips-companion", every)
    assert packages(stream_publish, "4.0", ["3.1.2"]) == [
        "openssl4.0-upstream", "openssl4.0-upstream-fips"]


def test_a_backfill_publishes_every_kind_it_builds():
    kinds = expand("deb-bookworm fips-deb-bookworm", ["deb-bookworm", "rpm-el9"])
    assert packages(kinds, "4.0", ["3.1.2"]) == [
        "openssl-fips3.1.2-upstream", "openssl4.0-upstream", "openssl4.0-upstream-fips"]
