#!/usr/bin/env python3
"""The publish tag: one per publish, recording what it published and from where.

Not meant to be run by hand. The Makefile names the tag and renders its
annotation; the pipeline creates it after a successful publish:

    $ make -s publish-tags GOALS="stream fips-companion" STAMP=20260812T121318Z
    publish/4.0.1-1/20260812T121318Z
    $ make -s publish-manifest GOALS="stream fips-companion" ARCHES="amd64 arm64"
    openssl4.0-upstream 4.0.1-1 deb-bookworm amd64
    …

The name carries the version-revisions published and a UTC stamp, which is what
makes it unique per publish: a backfill, a second architecture and a module-only
publish can all touch the same version-revision. Everything else — the goals,
and every package, release and architecture the run published — goes in the
annotation, which has no length limit worth worrying about.

The tag no longer decides whether a publish may proceed. publish/is_published.py
asks the bucket that, because the bucket is the real state and a tag written
after the upload can lag it.
"""
import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "build"))
from goals import expand  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "publish"))
from is_published import wanted  # noqa: E402

def identities(kinds, version, revision, fips_validated):
    """The version-revisions a run publishes, for the tag name.

    Stream packages and the companion module carry the stream's version; a
    validated module carries the pinned version it was built from, so a run
    publishing only modules is not named after a stream it did not publish.
    """
    found = []
    if kinds["stream"] or kinds["companion"]:
        found.append(f"{version}-{revision}")
    if kinds["validated"]:
        found += [f"fips-{v}-{revision}" for v in fips_validated]
    return sorted(set(found))


def tag(kinds, version, revision, fips_validated, stamp):
    """The single tag a publish creates."""
    named = identities(kinds, version, revision, fips_validated)
    if not named:
        return None
    return f"publish/{'+'.join(named)}/{stamp}"


def manifest(kinds, stream, version, revision, fips_validated, arches):
    """The annotation body: every package, release and arch the run published.

    Reuses the pre-flight's own expansion, so the record cannot describe
    something different from what was checked against the bucket.
    """
    return [f"{package} {package_version}-{revision} {family}-{release} {arch}"
            for package, family, release, arch, package_version
            in wanted(kinds, stream, version, fips_validated, arches)]


def packages(kinds, stream, fips_validated):
    """The source packages a run publishes, as they are named in output/.

    A run may build more than it publishes — a validated-module publish builds
    the stream packages its modules are tested against — so the repository is
    told what to index rather than taking whatever the build left behind.
    """
    found = set()
    if kinds["stream"]:
        found.add(f"openssl{stream}-upstream")
    if kinds["companion"]:
        found.add(f"openssl{stream}-upstream-fips")
    if kinds["validated"]:
        found.update(f"openssl-fips{v}-upstream" for v in fips_validated)
    return sorted(found)


def cmd_name(args):
    kinds = expand(args.goals, args.targets.split())
    named = tag(kinds, args.version, args.revision, args.fips_validated.split(), args.stamp)
    if not named:
        sys.exit(f"Nothing to publish: '{args.goals}' names no build target.")
    print(named)


def cmd_manifest(args):
    kinds = expand(args.goals, args.targets.split())
    for line in manifest(kinds, args.stream, args.version, args.revision,
                         args.fips_validated.split(), args.arches.split()):
        print(line)


def cmd_packages(args):
    kinds = expand(args.goals, args.targets.split())
    for package in packages(kinds, args.stream, args.fips_validated.split()):
        print(package)


def main(argv):
    parser = argparse.ArgumentParser(description="The publish tag for openssl-packages.")
    sub = parser.add_subparsers(required=True)

    namer = sub.add_parser("name", help="the tag a publish creates")
    for flag in ("targets", "goals", "version", "revision", "fips-validated", "stamp"):
        namer.add_argument(f"--{flag}", required=True)
    namer.set_defaults(run=cmd_name)

    body = sub.add_parser("manifest", help="what the tag's annotation records")
    for flag in ("targets", "goals", "stream", "version", "revision",
                 "fips-validated", "arches"):
        body.add_argument(f"--{flag}", required=True)
    body.set_defaults(run=cmd_manifest)

    lister = sub.add_parser("packages", help="the source packages a run publishes")
    for flag in ("targets", "goals", "stream", "fips-validated"):
        lister.add_argument(f"--{flag}", required=True)
    lister.set_defaults(run=cmd_packages)

    args = parser.parse_args(argv[1:])
    args.run(args)


if __name__ == "__main__":
    main(sys.argv)
