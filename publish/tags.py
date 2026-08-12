#!/usr/bin/env python3
"""Publish tags: the record in git that a version-revision was published.

Not meant to be run by hand. The Makefile lists the tags a run would create, and
the publishing pipeline checks them against the remote before it builds:

    $ make -s publish-tags GOALS="stream fips-companion" ARCHES="amd64 arm64"
    publish/4.0.1-1/deb-bookworm/amd64
    publish/fips-companion-4.0.1-1/deb-bookworm/amd64
    $ publish/tags.py check --repo <url> publish/4.0.1-1/deb-bookworm/amd64

A tag asserts that what it names was published, which makes the namespace
append-only: an existing version-revision must never be rebuilt and republished
under the same name. The check reports the next free revision and never picks
one itself, because auto-incrementing would let a double publish succeed
silently.

One implementation of the format, so the side that creates the tags and the side
that checks them cannot disagree about it.
"""
import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "build"))
from goals import expand  # noqa: E402

# publish/<identity>-<revision>/<target>/<arch>. The identity is what a revision
# counts within, so publish/4.0.1 and publish/fips-companion-4.0.1 are separate
# series with their own revisions.
TAG = re.compile(r"^publish/(?P<identity>[^/]+)-(?P<revision>\d+)/[^/]+/[^/]+$")


def tags(kinds, arches, version, revision, fips_validated):
    """The publish tags a run creates: one per published target and arch.

    `kinds` is what build/goals.py expanded the run's goals into, so the tags
    can never name something the run did not build.
    """
    found = []
    for arch in arches:
        for target in kinds["stream"]:
            found.append(f"publish/{version}-{revision}/{target}/{arch}")
        for target in kinds["companion"]:
            found.append(f"publish/fips-companion-{version}-{revision}/{target}/{arch}")
        for fips_version in fips_validated:
            for target in kinds["validated"]:
                found.append(
                    f"publish/fips-validated-{fips_version}-{revision}/{target}/{arch}")
    return found


def split(tag):
    """(identity, revision) for a publish tag, None for any other ref."""
    m = TAG.match(tag)
    return (f"publish/{m['identity']}", int(m["revision"])) if m else None


def remote_tags(ls_remote):
    """The tag names in `git ls-remote --tags` output."""
    names = set()
    for line in ls_remote.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        ref = fields[-1]
        # An annotated tag is listed a second time, peeled to its commit.
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            names.add(ref[len("refs/tags/"):])
    return names


def next_free(existing, wanted):
    """The wanted tags that are published already, and the next free revision of
    every identity they belong to."""
    taken = sorted(tag for tag in wanted if tag in existing)
    highest = {}
    for tag in existing:
        parsed = split(tag)
        if parsed:
            identity, revision = parsed
            highest[identity] = max(highest.get(identity, 0), revision)
    free = {}
    for tag in taken:
        parsed = split(tag)
        if parsed:
            free[parsed[0]] = highest[parsed[0]] + 1
    return taken, free


def cmd_list(args):
    kinds = expand(args.goals, args.targets.split())
    for tag in tags(kinds, args.arches.split(), args.version, args.revision,
                    args.fips_validated.split()):
        print(tag)


def cmd_check(args):
    ls = subprocess.run(["git", "ls-remote", "--tags", args.repo],
                        capture_output=True, text=True)
    if ls.returncode != 0:
        sys.exit(f"Could not reach {args.repo} to check whether the publish tags "
                 f"already exist:\n{ls.stderr.strip()}")
    taken, free = next_free(remote_tags(ls.stdout), args.tags)
    if not taken:
        print(f"Publish tags are free: {' '.join(args.tags)}")
        return
    revisions = ", ".join(f"{identity} -> -{revision}"
                          for identity, revision in sorted(free.items()))
    sys.exit(f"Already published, so this run would republish it: {', '.join(taken)}.\n"
             f"Next free revision: {revisions}. Re-run with REVISION set to that.")


def main(argv):
    parser = argparse.ArgumentParser(description="Publish tags for openssl-packages.")
    sub = parser.add_subparsers(required=True)

    lister = sub.add_parser("list", help="the publish tags a run would create")
    lister.add_argument("--targets", required=True, help="every release target")
    lister.add_argument("--goals", required=True, help="the make goals the run builds")
    lister.add_argument("--arches", required=True)
    lister.add_argument("--version", required=True)
    lister.add_argument("--revision", required=True)
    lister.add_argument("--fips-validated", required=True, help="pinned module versions")
    lister.set_defaults(run=cmd_list)

    checker = sub.add_parser("check", help="fail if any of these tags is published already")
    checker.add_argument("--repo", required=True, help="git URL of openssl/packages")
    checker.add_argument("tags", nargs="+")
    checker.set_defaults(run=cmd_check)

    args = parser.parse_args(argv[1:])
    args.run(args)


if __name__ == "__main__":
    main(sys.argv)
