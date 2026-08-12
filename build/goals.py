#!/usr/bin/env python3
"""Expand make goals into the release targets they name, by package kind.

Not meant to be run by hand. The Makefile calls it, passing its own release
targets, and tests/conftest.py imports expand() directly:

    $ make -s expand-goals GOALS="deb-bookworm fips-deb-bookworm"
    STREAM_TARGETS=deb-bookworm
    VALIDATED_TARGETS=deb-bookworm
    COMPANION_TARGETS=deb-bookworm

A goal can be shorthand for many releases ('stream', 'fips-deb', 'all'), so
resolving one needs the list of releases. That list is a parameter rather than
something defined here: the Makefile owns it, and a second copy is one more thing
to keep in step.

The test suite requires what the result names; the publishing pipeline tags it
and indexes it. One implementation, so they cannot disagree about what a goal
covers.
"""
import sys

ALL_KINDS = ("stream", "validated", "companion")

# Longest prefix first: 'fips-validated-deb' also starts with 'fips-'.
# A '-publish' goal builds more than it publishes — the modules need stream
# packages to be tested against — but what it publishes is the modules alone,
# so it expands exactly as its plain counterpart does.
KINDS = (("fips-validated-publish", ("validated",)),
         ("fips-validated", ("validated",)),
         ("fips-companion", ("companion",)),
         ("fips", ("validated", "companion")))


def expand(goals, every):
    """Map a make-goals string to {kind: [release target]} over the targets in
    `every`. Goals that name no release target contribute nothing."""
    groups = {"all": list(every), "stream": list(every),
              "deb": [t for t in every if t.startswith("deb-")],
              "rpm": [t for t in every if t.startswith("rpm-")]}
    found = {kind: set() for kind in ALL_KINDS}
    for goal in goals.split():
        # 'all' covers every kind, as the make target does; anything else is the
        # stream packages unless a fips- prefix says otherwise.
        kinds = ALL_KINDS if goal == "all" else ("stream",)
        name = goal
        for prefix, module_kinds in KINDS:
            if goal == prefix or goal.startswith(prefix + "-"):
                kinds = module_kinds
                name = "all" if goal == prefix else goal[len(prefix) + 1:]
                break
        hits = groups.get(name, [name] if name in every else [])
        for kind in kinds:
            found[kind].update(hits)
    return {kind: sorted(hits) for kind, hits in found.items()}


def main(argv):
    if len(argv) != 4 or argv[1] != "--targets":
        sys.exit(f'usage: make -s expand-goals GOALS="<goals>"\n'
                 f'   or: {argv[0]} --targets "<release targets>" "<goals>"')
    found = expand(argv[3], argv[2].split())
    for kind in ("stream", "validated", "companion"):
        print(f"{kind.upper()}_TARGETS={' '.join(found[kind])}")


if __name__ == "__main__":
    main(sys.argv)
