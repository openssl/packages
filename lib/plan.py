#!/usr/bin/env python3
"""What a publish consists of: where it lands, what it ships, how it is recorded.

Everything here is derived from the run's goals, so the bucket check, the tag and
the repository indexes cannot disagree about what a publish covers.

Not meant to be run by hand. The Makefile names the tag and renders its
annotation; the pipeline creates it after a successful publish:

    $ make -s plan-tag GOALS="stream fips-companion" STAMP=20260812T121318Z
    publish/4.0.1-1/20260812T121318Z
The name carries the version-revisions published and a UTC stamp, which is what
makes it unique per publish: a backfill, a second architecture and a module-only
publish can all touch the same version-revision. Everything else — the goals,
and every package, release and architecture the run published — goes in the
annotation, which has no length limit worth worrying about.

The tag no longer decides whether a publish may proceed. lib/is_published.py
asks the bucket that, because the bucket is the real state and a tag written
after the upload can lag it.
"""
import argparse
import sys

from _goals import expand

def wanted(kinds, stream, version, fips_validated, arches):
    """Every (package, family, release, arch, version) this run would publish.

    The version is carried per entry because it differs by kind: stream packages
    and the companion module are the stream's own version, while a validated
    module keeps the pinned version it was built from.
    """
    found = []
    for arch in arches:
        for target in kinds["stream"]:
            found.append((f"openssl{stream}-upstream",)
                         + _split_target(target) + (arch, version))
        for target in kinds["companion"]:
            found.append((f"openssl{stream}-upstream-fips",)
                         + _split_target(target) + (arch, version))
        for fips_version in fips_validated:
            for target in kinds["validated"]:
                found.append((f"openssl-fips{fips_version}-upstream",)
                             + _split_target(target) + (arch, fips_version))
    return found


def _split_target(target):
    """(family, release) for a build target: deb-bookworm -> (deb, bookworm)."""
    family, _, release = target.partition("-")
    return (family, release)


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


def releases(kinds):
    """The release targets a run publishes, whose repository slices it will
    regenerate. The kinds are separate everywhere else because they have
    separate lifecycles; an index does not care which kind touched it."""
    return sorted(set(kinds["stream"]) | set(kinds["validated"]) | set(kinds["companion"]))


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


def cmd_releases(args):
    for release in releases(expand(args.goals, args.targets.split())):
        print(release)


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

    slices = sub.add_parser("releases", help="the release targets a run publishes")
    for flag in ("targets", "goals"):
        slices.add_argument(f"--{flag}", required=True)
    slices.set_defaults(run=cmd_releases)

    lister = sub.add_parser("packages", help="the source packages a run publishes")
    for flag in ("targets", "goals", "stream", "fips-validated"):
        lister.add_argument(f"--{flag}", required=True)
    lister.set_defaults(run=cmd_packages)

    args = parser.parse_args(argv[1:])
    args.run(args)


if __name__ == "__main__":
    main(sys.argv)
