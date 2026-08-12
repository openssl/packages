"""Expand make goals into the release targets they name, by package kind.

    expand("stream fips-companion", ["deb-bookworm", "rpm-el9"])
    {"stream": [...], "validated": [], "companion": [...]}

A goal can be shorthand for many releases ('stream', 'fips-deb', 'all'), so
resolving one needs the list of releases. That list is a parameter rather than
something defined here: the Makefile owns it, and a second copy is one more thing
to keep in step.

Imported by the test suite and by the rest of publish/, so a goal means the same
thing to what is built, what is published and what is recorded.
"""
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
