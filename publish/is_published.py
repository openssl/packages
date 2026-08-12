#!/usr/bin/env python3
"""What the bucket already holds, so a run refuses before it builds.

Not meant to be run by hand. The Makefile lists what a run would publish and the
publishing pipeline checks it against the bucket:

    $ publish/is_published.py check --bucket gs://… --targets "…" --goals "…" \
          --arches "amd64 arm64" --version 4.0.1 --revision 1 --stream 4.0 \
          --fips-validated 3.1.2

A published file keeps its bytes forever, and builds are not reproducible, so
rebuilding an already-published version-revision produces different bytes for a
name that cannot be rewritten. make-repo.sh refuses that at the point of copying,
but only after a full build; this asks the same question of the bucket first.

The bucket is the real state. Tags record what was published, but they are
written after the upload, so a publish that succeeds while its tag push fails
leaves the tags behind reality — and only the bucket knows.
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "build"))
from goals import expand  # noqa: E402

# rpm names its architectures differently from everything else here; the deb
# name is the one the pipeline and the Makefile use. tests/test_published.py
# asserts this agrees with the test suite's own mapping.
RPM_ARCH = {"amd64": "x86_64", "arm64": "aarch64"}


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


def parse_deb(path):
    """(package, release, arch, version) for a pool object, None if not one.

    Pool layout is <…>/deb/pool/<suite>/<component>/o/<source>/<file>.deb, and a
    deb file name is <binary>_<version>_<arch>.deb. The version carries the
    revision and the suite qualifier: 4.0.1-1+deb12.
    """
    parts = path.strip("/").split("/")
    if len(parts) < 6 or not parts[-1].endswith(".deb"):
        return None
    try:
        suite = parts[parts.index("pool") + 1]
        source = parts[-2]
    except (ValueError, IndexError):
        return None
    fields = parts[-1][: -len(".deb")].split("_")
    if len(fields) != 3:
        return None
    _, version, arch = fields
    return (source, suite, arch, version)


def parse_rpm(path):
    """(package, release, arch, version) for a published rpm, None if not one.

    Layout is <…>/rpm/el<n>/<basearch>/<file>.rpm, and an rpm file name is
    <name>-<version>-<release>.<arch>.rpm — parsed right to left, because the
    name itself contains dashes.
    """
    parts = path.strip("/").split("/")
    if len(parts) < 4 or not parts[-1].endswith(".rpm"):
        return None
    el = parts[-3]
    stem = parts[-1][: -len(".rpm")]
    stem, _, arch = stem.rpartition(".")
    stem, _, release = stem.rpartition("-")
    name, _, version = stem.rpartition("-")
    if not (name and version and release and arch):
        return None
    # The directory name as-is (el9), which is what a rpm-el9 target splits to.
    return (name, el, arch, f"{version}-{release}")


def collisions(objects, want, revision):
    """The wanted publishes whose files are in the bucket already.

    A deb version is <upstream>-<revision><qualifier> and an rpm one is
    <upstream>-<revision>.<dist>, so both are matched on the exact
    <upstream>-<revision> prefix — 4.0.1-1 must not match 4.0.1-10.
    """
    found = []
    for package, family, release, arch, version in want:
        stamp = f"{version}-{revision}"
        want_arch = RPM_ARCH[arch] if family == "rpm" else arch
        for path in objects:
            parsed = parse_deb(path) if family == "deb" else parse_rpm(path)
            if not parsed:
                continue
            name, obj_release, obj_arch, obj_version = parsed
            if obj_release != release or obj_arch != want_arch:
                continue
            # Sub-packages share the source name as a prefix: a -dev or -devel
            # already published means that version-revision was published.
            if not name.startswith(package):
                continue
            rest = obj_version[len(stamp):]
            if obj_version.startswith(stamp) and (rest == "" or rest[0] in "+."):
                found.append((package, family, release, arch, path.rsplit("/", 1)[-1]))
                break
    return found


# gcloud reports an empty prefix as an error, and that is a first publish rather
# than a failure. Only that one phrasing counts: a missing bucket or a denied
# listing must fail loudly, because a guard that could not run is not a guard
# that passed, and a mistyped bucket would otherwise read as "nothing published".
NO_OBJECTS = ("matched no objects",)


def absent(stderr):
    """True when a listing error only means the prefix holds nothing yet."""
    lowered = (stderr or "").lower()
    return any(phrase in lowered for phrase in NO_OBJECTS)


def listing(bucket, prefix):
    """Object names under a bucket prefix."""
    r = subprocess.run(["gcloud", "storage", "ls", f"{bucket}/{prefix}/**"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        if absent(r.stderr):
            return []
        sys.exit(f"cannot list {bucket}/{prefix}: {(r.stderr or '').strip()}")
    return r.stdout.split()


def cmd_check(args):
    kinds = expand(args.goals, args.targets.split())
    want = wanted(kinds, args.stream, args.version, args.fips_validated.split(),
                  args.arches.split())
    if not want:
        sys.exit(f"Nothing to publish: '{args.goals}' names no build target.")
    objects = listing(args.bucket, "deb/pool") + listing(args.bucket, "rpm")
    taken = collisions(objects, want, args.revision)
    if not taken:
        versions = " ".join(sorted({v for *_, v in want}))
        print(f"Not published yet: {len(want)} package/release/arch combination(s) "
              f"at revision {args.revision} of {versions}.")
        return
    for package, family, release, arch, name in taken:
        print(f"  {package} {family}-{release} {arch}: {name}", file=sys.stderr)
    sys.exit(f"Already in the bucket at revision {args.revision} (above). A "
             f"published version-revision cannot be rebuilt: bump REVISION.")


def main(argv):
    parser = argparse.ArgumentParser(description="What openssl-packages has published.")
    sub = parser.add_subparsers(required=True)
    checker = sub.add_parser("check", help="fail if a run would republish anything")
    for flag in ("bucket", "targets", "goals", "arches", "version", "revision", "stream"):
        checker.add_argument(f"--{flag}", required=True)
    checker.add_argument("--fips-validated", required=True)
    checker.set_defaults(run=cmd_check)
    args = parser.parse_args(argv[1:])
    args.run(args)


if __name__ == "__main__":
    main(sys.argv)
