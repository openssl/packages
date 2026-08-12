"""The bucket pre-flight: does a run's output already exist in the repository?

Pure parsing and matching, so these run without a bucket or a build. The object
names are the ones the build really produces (see the assertions against
output/ in test_matrix_completeness.py).
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "publish"))
sys.path.insert(0, os.path.join(REPO, "build"))
from goals import expand  # noqa: E402
from is_published import (RPM_ARCH, absent, collisions, parse_deb,  # noqa: E402
                       parse_rpm, wanted)
from conftest import ARCH, RPM_ARCH as SUITE_RPM_ARCH  # noqa: E402

pytestmark = pytest.mark.unit

BUCKET = "gs://some-bucket"
EVERY = ["deb-bookworm", "rpm-el9"]

# What the pool holds after publishing 4.0.1-1 for bookworm and el9, amd64 only.
PUBLISHED = [
    f"{BUCKET}/deb/pool/bookworm/main/o/openssl4.0-upstream/"
    "openssl4.0-upstream_4.0.1-1+deb12_amd64.deb",
    f"{BUCKET}/deb/pool/bookworm/main/o/openssl4.0-upstream/"
    "openssl4.0-upstream-dev_4.0.1-1+deb12_amd64.deb",
    f"{BUCKET}/rpm/el9/x86_64/openssl4.0-upstream-4.0.1-1.el9.x86_64.rpm",
    f"{BUCKET}/rpm/el9/x86_64/openssl4.0-upstream-devel-4.0.1-1.el9.x86_64.rpm",
]


def test_the_rpm_architecture_names_agree_with_the_test_suite():
    """This mapping exists here and in conftest; drift would make the pre-flight
    look in the wrong architecture directory and pass a republish."""
    assert RPM_ARCH[ARCH] == SUITE_RPM_ARCH
    assert RPM_ARCH == {"amd64": "x86_64", "arm64": "aarch64"}


def test_a_deb_pool_object_parses_to_its_identity():
    assert parse_deb(PUBLISHED[0]) == ("openssl4.0-upstream", "bookworm", "amd64",
                                       "4.0.1-1+deb12")


def test_an_rpm_object_parses_despite_dashes_in_the_name():
    assert parse_rpm(PUBLISHED[3]) == ("openssl4.0-upstream-devel", "el9", "x86_64",
                                       "4.0.1-1.el9")


@pytest.mark.parametrize("path", [
    f"{BUCKET}/deb/dists/bookworm/main/binary-amd64/Packages",
    f"{BUCKET}/rpm/el9/x86_64/repodata/repomd.xml",
    f"{BUCKET}/deb/pool/bookworm/main/o/openssl4.0-upstream/",
])
def test_anything_that_is_not_a_package_is_ignored(path):
    assert parse_deb(path) is None or not path.endswith(".deb")
    assert parse_rpm(path) is None or not path.endswith(".rpm")


def test_a_run_that_would_republish_is_caught():
    want = wanted(expand("stream", EVERY), "4.0", "4.0.1", ["3.1.2"], ["amd64"])
    taken = collisions(PUBLISHED, want, "1")
    assert {(p, f, r) for p, f, r, _, _ in taken} == {
        ("openssl4.0-upstream", "deb", "bookworm"),
        ("openssl4.0-upstream", "rpm", "el9")}


def test_a_new_revision_is_free():
    want = wanted(expand("stream", EVERY), "4.0", "4.0.1", ["3.1.2"], ["amd64"])
    assert collisions(PUBLISHED, want, "2") == []


def test_a_revision_prefix_is_not_a_match():
    """4.0.1-1 must not look published because 4.0.1-10 exists."""
    published = [p.replace("4.0.1-1+", "4.0.1-10+").replace("4.0.1-1.el9", "4.0.1-10.el9")
                 for p in PUBLISHED]
    want = wanted(expand("stream", EVERY), "4.0", "4.0.1", ["3.1.2"], ["amd64"])
    assert collisions(published, want, "1") == []
    assert collisions(published, want, "10") != []


def test_the_other_architecture_is_free_after_a_single_arch_publish():
    """Completing a split-arch publish at the same revision has to be allowed."""
    want = wanted(expand("stream", EVERY), "4.0", "4.0.1", ["3.1.2"], ["arm64"])
    assert collisions(PUBLISHED, want, "1") == []


def test_a_module_only_publish_is_free_when_only_streams_are_published():
    """The case the tags could not express: streams published, modules not."""
    want = wanted(expand("fips-validated-publish", EVERY), "4.0", "4.0.1", ["3.1.2"], ["amd64"])
    assert collisions(PUBLISHED, want, "1") == []


def test_a_companion_republish_is_caught_independently_of_the_stream():
    companion = f"{BUCKET}/deb/pool/bookworm/main/o/openssl4.0-upstream-fips/" \
                "openssl4.0-upstream-fips_4.0.1-1+deb12_amd64.deb"
    want = wanted(expand("fips-companion-deb-bookworm", EVERY), "4.0", "4.0.1", ["3.1.2"], ["amd64"])
    assert collisions([companion], want, "1") != []
    assert collisions(PUBLISHED, want, "1") == []


def test_an_empty_bucket_is_a_first_publish():
    want = wanted(expand("all", EVERY), "4.0", "4.0.1", ["3.1.2"], ["amd64", "arm64"])
    assert collisions([], want, "1") == []


# Verbatim from gcloud: the first is a prefix that holds nothing, the rest are
# failures that must not be mistaken for one.
def test_an_empty_prefix_is_recognised_as_a_first_publish():
    assert absent("ERROR: (gcloud.storage.ls) One or more URLs matched no objects.")


@pytest.mark.parametrize("stderr", [
    "ERROR: (gcloud.storage.ls) There was a problem refreshing your current auth"
    " tokens: Reauthentication failed. cannot prompt during non-interactive execution.",
    "ERROR: (gcloud.storage.ls) HTTPError 403: does not have storage.objects.list access",
    "ERROR: (gcloud.storage.ls) HTTPError 503: Service Unavailable",
    # A mistyped bucket must not read as "nothing published yet".
    "ERROR: (gcloud.storage.ls) HTTPError 404: The specified bucket does not exist.",
    "",
])
def test_a_guard_that_could_not_run_is_not_a_guard_that_passed(stderr):
    assert not absent(stderr)


def test_a_published_validated_module_is_caught_at_its_own_version():
    """A validated module keeps the version it was built from, not the stream's,
    so matching everything against the stream version would miss it entirely."""
    module = f"{BUCKET}/rpm/el9/x86_64/openssl-fips3.1.2-upstream-3.1.2-1.el9.x86_64.rpm"
    want = wanted(expand("fips-validated-publish", EVERY), "4.0", "4.0.1", ["3.1.2"], ["amd64"])
    assert [w[0] for w in collisions([module], want, "1")] == ["openssl-fips3.1.2-upstream"]
    assert collisions([module], want, "2") == []
